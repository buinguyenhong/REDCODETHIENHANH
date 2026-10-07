"""Real TCP/Uvicorn/WebSocket acceptance on an isolated Alembic database.

Uses SQLite locally. CI can set LIVE_TEST_DATABASE_URL to a dedicated PostgreSQL
database. This measures transport, never claims physical speaker acceptance.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
import websockets


@pytest.mark.asyncio
async def test_live_reconnect_restart_and_100_receivers():
    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary:
        env = os.environ.copy()
        env.update(ENVIRONMENT='test', DEMO_MODE='true',
                   DATABASE_URL=os.getenv('LIVE_TEST_DATABASE_URL', 'sqlite+aiosqlite:///' + str(Path(temporary) / 'live.db').replace('\\', '/')),
                   AUDIO_UPLOAD_DIR=str(Path(temporary) / 'audio'), N8N_WEBHOOK_URL='http://127.0.0.1:1/unavailable')
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=backend, env=env, check=True, capture_output=True)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        http_url, ws_url = f'http://127.0.0.1:{port}', f'ws://127.0.0.1:{port}/ws'
        processes, receivers = [], []

        async def shutdown(process):
            if process.poll() is not None:
                return
            # Windows venv python.exe may launch a child interpreter; stop the
            # process tree so restart/cleanup cannot leave a live DB handle.
            if os.name == 'nt':
                await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                process.terminate()
            await asyncio.to_thread(process.wait, 10)

        async def boot():
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], cwd=backend, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            async with httpx.AsyncClient() as client:
                for _ in range(150):
                    if process.poll() is not None:
                        raise AssertionError('Live server exited at startup')
                    try:
                        if (await client.get(http_url + '/api/health')).status_code == 200:
                            return process
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(.1)
            raise AssertionError('Live server startup timeout')

        async def connect(station):
            ws = await websockets.connect(ws_url + '?' + urlencode({'type': 'station', 'station_code': station['station_code'], 'token': station['raw_device_token']}))
            assert json.loads(await ws.recv())['type'] == 'CONNECTION_ESTABLISHED'
            receivers.append(ws)
            return ws

        async def receive(ws, kind):
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if message['type'] == kind:
                    return message

        async def ack(ws, alarm_id, event):
            await ws.send(json.dumps({'type': 'STATION_EVENT', 'alarm_id': alarm_id, 'event_type': event, 'metadata': {}}))
            response = await receive(ws, 'STATION_EVENT_ACK')
            assert response['accepted'], response

        try:
            process = await boot()
            async with httpx.AsyncClient(base_url=http_url, timeout=30) as client:
                login = await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})
                headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
                station = (await client.post('/api/stations/register', headers=headers, json={'station_code': 'LIVE-0', 'name': 'Live', 'receiver_group_ids': [1]})).json()
                ws = await connect(station)
                alarm_a = (await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2})).json()
                assert (await receive(ws, 'ALARM_EVENT'))['data']['alarm_id'] == alarm_a['id']
                for event in ['RECEIVED', 'DISPLAYED', 'AUDIO_STARTED', 'AUDIO_COMPLETED']:
                    await ack(ws, alarm_a['id'], event)
                # Transport ACK here simulates a receiver protocol, not real audio.
                await ws.close()
                alarm_b = (await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2})).json()
                await client.post(f"/api/alarms/{alarm_a['id']}/cancel", headers=headers)
                ws = await connect(station)
                sync_path = '/api/stations/LIVE-0/active-alarms'
                credentials = {'X-Station-Token': station['raw_device_token']}
                sync = (await client.get(sync_path, headers=credentials)).json()
                assert alarm_b['id'] in [a['alarm_id'] for a in sync]
                assert alarm_a['id'] not in [a['alarm_id'] for a in sync]
                # Same station replaces old socket, old cleanup cannot kill new.
                replacement = await connect(station)
                await replacement.send(json.dumps({'type': 'PING'}))
                await receive(replacement, 'PONG')
                # Active alarm and outbox survive a process restart.
                await shutdown(process)
                process = await boot()
                ws = await connect(station)
                sync = (await client.get(sync_path, headers=credentials)).json()
                assert alarm_b['id'] in [a['alarm_id'] for a in sync]
                detail = (await client.get(f"/api/alarms/{alarm_a['id']}", headers=headers)).json()
                assert detail['status'] == 'CANCELLED'
                await client.post(f"/api/alarms/{alarm_b['id']}/cancel", headers=headers)
                await receive(ws, 'ALARM_CANCELLED')

                sockets = [ws]
                for index in range(1, 100):
                    registered = await client.post('/api/stations/register', headers=headers, json={'station_code': f'LIVE-{index}', 'name': f'Live {index}', 'receiver_group_ids': [1]})
                    assert registered.status_code == 201
                    sockets.append(await connect(registered.json()))
                async def keepalive():
                    while True:
                        await asyncio.gather(*(s.send(json.dumps({'type': 'HEARTBEAT', 'client_ready': True})) for s in sockets))
                        await asyncio.sleep(3)
                heartbeat = asyncio.create_task(keepalive())
                try:
                    expected, latencies = [], []
                    for index in range(10):
                        started = time.monotonic()
                        created = await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2, 'source_location': f'Live batch {index}'})
                        assert created.status_code == 201
                        expected.append(created.json()['id'])
                        messages = await asyncio.gather(*(receive(s, 'ALARM_EVENT') for s in sockets))
                        assert all(m['data']['alarm_id'] == expected[-1] for m in messages)
                        latencies.append(time.monotonic() - started)
                    assert len(set(expected)) == 10
                    # PING barrier drains older messages: no duplicate alarm.
                    for s in sockets:
                        await s.send(json.dumps({'type': 'PING', 'request_id': 'barrier'}))
                    async def barrier(s):
                        while True:
                            message = json.loads(await asyncio.wait_for(s.recv(), 10))
                            assert message['type'] != 'ALARM_EVENT', 'Unexpected duplicate alarm'
                            if message['type'] == 'PONG' and message.get('request_id') == 'barrier':
                                return
                    await asyncio.gather(*(barrier(s) for s in sockets))
                    ordered_latency = sorted(latencies)
                    print(f'Live transport: 100 sockets x 10 alarms; lost=0 duplicate=0; batch latency p50={ordered_latency[4]:.3f}s p95={ordered_latency[9]:.3f}s max={max(latencies):.3f}s')
                finally:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass
        finally:
            await asyncio.gather(*(s.close() for s in receivers), return_exceptions=True)
            for process in processes:
                if process.poll() is None:
                    await shutdown(process)
