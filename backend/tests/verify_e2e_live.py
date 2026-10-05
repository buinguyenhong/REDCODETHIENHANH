import asyncio
import json
import httpx
import websockets

BACKEND_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"
FRONTEND_URL = "http://127.0.0.1:5173"

async def run_e2e_verification():
    print("=" * 60)
    print("REDCODE HOSPITAL — AUTOMATED LIVE E2E VERIFICATION")
    print("=" * 60)

    # 1. Test Frontend HTTP server
    print("\n[1/7] Testing Frontend Server (Vite)...")
    async with httpx.AsyncClient() as client:
        fe_res = await client.get(FRONTEND_URL)
        assert fe_res.status_code == 200, f"Frontend returned {fe_res.status_code}"
        assert "<div id=\"root\"></div>" in fe_res.text
        print("  --> Frontend Vite server is UP and serving React bundle (200 OK)")

    # 2. Test Backend Health Check
    print("\n[2/7] Testing Backend Health Check...")
    async with httpx.AsyncClient() as client:
        h_res = await client.get(f"{BACKEND_URL}/api/health")
        assert h_res.status_code == 200
        health_data = h_res.json()
        print(f"  --> Health status: {health_data}")
        assert health_data["status"] == "ok"
        assert health_data["database"] == "ok"

    # 3. Test Staff & Admin Login
    print("\n[3/7] Testing Authentication (Admin & Operator)...")
    async with httpx.AsyncClient() as client:
        admin_login = await client.post(f"{BACKEND_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin123456"
        })
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["access_token"]
        print("  --> Admin login SUCCESSful")

        op_login = await client.post(f"{BACKEND_URL}/api/auth/login", json={
            "username": "operator_cc",
            "password": "pass123456"
        })
        assert op_login.status_code == 200
        op_token = op_login.json()["access_token"]
        print("  --> Operator login SUCCESSful")

    # 4. Connect Receiver Station WebSocket
    print("\n[4/7] Connecting Receiver Station Kiosk via WebSocket (ST-CC-01)...")
    station_ws_url = f"{WS_URL}?type=station&station_code=ST-CC-01&token=station-token-cc-01"
    station_ws = await websockets.connect(station_ws_url)
    
    # Receive connection ACK
    ack_raw = await station_ws.recv()
    ack = json.loads(ack_raw)
    print(f"  --> Station connected: {ack}")
    assert ack["type"] == "CONNECTION_ESTABLISHED"

    # Send heartbeat
    await station_ws.send(json.dumps({
        "type": "HEARTBEAT",
        "audio_ready": True,
        "client_ready": True
    }))
    hb_ack_raw = await station_ws.recv()
    hb_ack = json.loads(hb_ack_raw)
    print(f"  --> Heartbeat ACK received: {hb_ack}")
    assert hb_ack["type"] == "HEARTBEAT_ACK"

    # 5. Connect Dashboard Monitor WebSocket
    print("\n[5/7] Connecting Dashboard Monitor WebSocket...")
    dash_ws_url = f"{WS_URL}?type=dashboard&token={admin_token}"
    dash_ws = await websockets.connect(dash_ws_url)
    dash_ack = json.loads(await dash_ws.recv())
    print(f"  --> Dashboard connected: {dash_ack}")

    # 6. Trigger Alarm as Operator
    print("\n[6/7] Operator triggers RED_CODE_1 alarm...")
    async with httpx.AsyncClient() as client:
        alarm_res = await client.post(
            f"{BACKEND_URL}/api/alarms",
            headers={"Authorization": f"Bearer {op_token}"},
            json={
                "alarm_type_id": 1,
                "source_location": "Khu Cấp Cứu Giường 01",
                "note": "Bệnh nhân ngưng tim ngưng thở khẩn cấp"
            }
        )
        assert alarm_res.status_code == 201
        alarm_created = alarm_res.json()
        alarm_id = alarm_created["id"]
        print(f"  --> Alarm created successfully (ID: {alarm_id}, Seq: {alarm_created['server_sequence']})")

    # Verify Station received the alarm broadcast over WebSocket
    station_event_raw = await asyncio.wait_for(station_ws.recv(), timeout=3.0)
    station_event = json.loads(station_event_raw)
    print(f"  --> Station ST-CC-01 received broadcast: {station_event['event']} for {station_event['data']['code']}")
    assert station_event["type"] == "ALARM_EVENT"
    assert station_event["data"]["alarm_id"] == alarm_id

    # Verify Dashboard received the alarm broadcast
    dash_event_raw = await asyncio.wait_for(dash_ws.recv(), timeout=3.0)
    dash_event = json.loads(dash_event_raw)
    assert dash_event["data"]["alarm_id"] == alarm_id
    print("  --> Dashboard monitor also received realtime alarm event")

    # 7. Local Dismiss by Station
    print("\n[7/7] Station ST-CC-01 performs Local Dismiss...")
    async with httpx.AsyncClient() as client:
        dismiss_res = await client.post(
            f"{BACKEND_URL}/api/stations/dismiss",
            json={
                "alarm_id": alarm_id,
                "station_code": "ST-CC-01",
                "note": "Điều dưỡng trực tiếp nhận"
            }
        )
        assert dismiss_res.status_code == 200
        print(f"  --> Dismiss response: {dismiss_res.json()}")

    # Verify Dashboard received ALARM_ACKNOWLEDGED event
    ack_event_raw = await asyncio.wait_for(dash_ws.recv(), timeout=3.0)
    ack_event = json.loads(ack_event_raw)
    print(f"  --> Dashboard received station ACK: Station {ack_event.get('station_code')} acknowledged alarm {ack_event.get('alarm_id')}")
    assert ack_event["type"] == "ALARM_ACKNOWLEDGED"

    # Verify XLSX Report export
    print("\n[Bonus] Verifying Excel XLSX Report Generation...")
    async with httpx.AsyncClient() as client:
        xlsx_res = await client.get(
            f"{BACKEND_URL}/api/reports/export-xlsx",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert xlsx_res.status_code == 200
        assert len(xlsx_res.content) > 1000
        print(f"  --> Excel export verified (Size: {len(xlsx_res.content)} bytes)")

    # Cleanup
    await station_ws.close()
    await dash_ws.close()

    print("\n" + "=" * 60)
    print("ALL LIVE END-TO-END VERIFICATION CHECKS PASSED 100%!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_e2e_verification())
