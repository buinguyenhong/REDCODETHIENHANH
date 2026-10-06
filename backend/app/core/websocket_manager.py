import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Any, List
from fastapi import WebSocket
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models import Station, StationStatus, SystemEvent, AlarmEvent, Alarm, AlarmStatus
from app.core.alarm_lifecycle import expire_alarms

logger = logging.getLogger("redcode.websocket")

class ConnectionManager:
    def __init__(self):
        # Maps station_code -> WebSocket
        self.active_stations: Dict[str, WebSocket] = {}
        # Set of active dashboard/admin/operator WebSockets
        self.active_dashboards: Set[WebSocket] = set()
        # Track last heartbeat time: station_code -> datetime
        self.last_heartbeats: Dict[str, datetime] = {}
        # Background task for monitoring heartbeat timeout
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start_monitor(self, offline_threshold_seconds: int = 15):
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._check_timeouts(offline_threshold_seconds))

    async def stop_monitor(self):
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def connect_station(self, station_code: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            # If previous connection exists for this station, close it gracefully
            if station_code in self.active_stations:
                try:
                    await self.active_stations[station_code].close(code=1000)
                except Exception:
                    pass
            self.active_stations[station_code] = websocket
            self.last_heartbeats[station_code] = datetime.now(timezone.utc)

        # Mark station online in DB & log system event
        await self._update_station_db_status(station_code, True)
        await self.broadcast_to_dashboards({
            "type": "STATION_STATUS",
            "station_code": station_code,
            "status": StationStatus.ONLINE.value,
            "websocket_connected": True,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Station connected: {station_code}")

    async def connect_dashboard(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_dashboards.add(websocket)
        logger.info("Dashboard client connected")

    async def disconnect_station(self, station_code: str, websocket: Optional[WebSocket] = None):
        async with self._lock:
            current_ws = self.active_stations.get(station_code)
            if websocket is not None and current_ws is not websocket:
                logger.info(f"Ignored disconnect from obsolete socket for station: {station_code}")
                return

            if station_code in self.active_stations:
                del self.active_stations[station_code]
            if station_code in self.last_heartbeats:
                del self.last_heartbeats[station_code]

        await self._update_station_db_status(station_code, False)
        await self.broadcast_to_dashboards({
            "type": "STATION_STATUS",
            "station_code": station_code,
            "status": StationStatus.OFFLINE.value,
            "websocket_connected": False,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Station disconnected: {station_code}")

    async def disconnect_dashboard(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_dashboards:
                self.active_dashboards.remove(websocket)
        logger.info("Dashboard client disconnected")

    async def update_heartbeat(self, station_code: str, audio_ready: bool = False, client_ready: bool = True):
        now = datetime.now(timezone.utc)
        async with self._lock:
            self.last_heartbeats[station_code] = now

        async with AsyncSessionLocal() as session:
            try:
                stmt = (
                    update(Station)
                    .where(Station.station_code == station_code)
                    .values(
                        last_seen_at=now,
                        websocket_connected=True,
                        audio_ready=audio_ready,
                        client_ready=client_ready,
                        status=StationStatus.ONLINE.value,
                        updated_at=now
                    )
                )
                await session.execute(stmt)
                await session.commit()
            except Exception as e:
                logger.error(f"Error updating heartbeat in DB for {station_code}: {e}")

    async def broadcast_alarm(self, alarm_data: dict, target_station_codes: Optional[List[str]] = None):
        """
        Broadcasts alarm to target stations (if None, broadcast to all stations),
        and always sends to all dashboard monitors.
        """
        message = {
            "type": "ALARM_EVENT",
            "event": "ALARM_TRIGGERED",
            "data": alarm_data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # 1. Send to target stations
        dead_stations = []
        async with self._lock:
            if target_station_codes is None:
                recipients = list(self.active_stations.items())
            else:
                target_set = set(target_station_codes)
                recipients = [(code, ws) for code, ws in self.active_stations.items() if code in target_set]

        async def deliver(code, ws):
            try:
                await asyncio.wait_for(ws.send_text(json.dumps(message)), timeout=1)
            except Exception as e:
                logger.warning(f"Failed to send alarm to station {code}: {e}")
                dead_stations.append((code, ws))
        await asyncio.gather(*(deliver(code, ws) for code, ws in recipients))

        # 2. Send to all dashboard clients
        await self.broadcast_to_dashboards(message)

        # Cleanup any dead sockets
        for code, ws in dead_stations:
            await self.disconnect_station(code, ws)

    async def broadcast_to_dashboards(self, message: dict):
        dead_dashboards = []
        msg_str = json.dumps(message)
        async with self._lock:
            dashboards = list(self.active_dashboards)

        for ws in dashboards:
            try:
                await asyncio.wait_for(ws.send_text(msg_str), timeout=1)
            except Exception:
                dead_dashboards.append(ws)

        for ws in dead_dashboards:
            await self.disconnect_dashboard(ws)

    async def send_to_station(self, station_code: str, message: dict) -> bool:
        async with self._lock:
            ws = self.active_stations.get(station_code)
        if not ws:
            return False
        try:
            await ws.send_text(json.dumps(message))
            return True
        except Exception:
            await self.disconnect_station(station_code, ws)
            return False

    async def _update_station_db_status(self, station_code: str, connected: bool):
        now = datetime.now(timezone.utc)
        status = StationStatus.ONLINE.value if connected else StationStatus.OFFLINE.value
        async with AsyncSessionLocal() as session:
            try:
                # Update station
                stmt = (
                    update(Station)
                    .where(Station.station_code == station_code)
                    .values(
                        websocket_connected=connected,
                        status=status,
                        last_seen_at=now,
                        updated_at=now
                    )
                )
                res = await session.execute(stmt)

                # Log system event
                event_type = "DEVICE_CONNECTED" if connected else "DEVICE_DISCONNECTED"
                station_id = (await session.execute(select(Station.id).where(Station.station_code == station_code))).scalar_one_or_none()
                sys_event = SystemEvent(
                    station_id=station_id,
                    event_type=event_type,
                    severity="INFO" if connected else "WARNING",
                    message=f"Station {station_code} {'connected' if connected else 'disconnected'}",
                    event_metadata={"station_code": station_code, "status": status},
                    created_at=now
                )
                session.add(sys_event)
                await session.commit()
            except Exception as e:
                logger.error(f"Error updating station status in DB for {station_code}: {e}")

    async def _check_timeouts(self, threshold_seconds: int):
        while True:
            try:
                await asyncio.sleep(5)
                now = datetime.now(timezone.utc)
                async with AsyncSessionLocal() as session:
                    expired_ids = await expire_alarms(session)
                for alarm_id in expired_ids:
                    message = {'type': 'ALARM_EXPIRED', 'alarm_id': alarm_id}
                    await self.broadcast_to_dashboards(message)
                    for code in list(self.active_stations):
                        await self.send_to_station(code, message)
                timed_out = []

                async with self._lock:
                    for code, last_seen in list(self.last_heartbeats.items()):
                        elapsed = (now - last_seen).total_seconds()
                        if elapsed > threshold_seconds:
                            timed_out.append((code, self.active_stations.get(code)))

                for code, ws in timed_out:
                    logger.warning(f"Station {code} timed out ({threshold_seconds}s with no heartbeat). Marking offline.")
                    if ws is not None:
                        try:
                            await ws.close(code=1011, reason='Heartbeat timeout')
                        except Exception:
                            pass
                    await self.disconnect_station(code, ws)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat timeout monitor: {e}")

manager = ConnectionManager()
