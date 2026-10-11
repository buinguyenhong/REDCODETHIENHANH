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
        # start_monitor() đã được gọi lần nào chưa. Phân biệt "chưa từng giám sát"
        # (app đang khởi động, hoặc test dựng app không qua lifespan) với "đã giám
        # sát rồi mất" — chỉ vế sau mới là sự cố cần báo động.
        self._monitor_expected: bool = False
        self._lock = asyncio.Lock()

    async def start_monitor(self, offline_threshold_seconds: int = 15):
        self._monitor_expected = True
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._check_timeouts(offline_threshold_seconds))

    async def stop_monitor(self):
        # Dừng theo lệnh thì không còn "phải đang chạy" nữa. Không hạ cờ này, một
        # lần khởi động rồi tắt (ví dụ lifespan của test chạy trong cùng tiến trình)
        # sẽ để lại trạng thái "đã chạy rồi chết" và mọi lần đọc /api/health sau đó
        # đều báo suy giảm — che mất ca suy giảm thật.
        self._monitor_expected = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def connect_station(self, station_code: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            previous = self.active_stations.get(station_code)
            self.active_stations[station_code] = websocket
            self.last_heartbeats[station_code] = datetime.now(timezone.utc)

        # Đóng socket cũ NGOÀI lock. close() là I/O có thể treo với kết nối
        # half-open; giữ lock trong lúc đó sẽ chặn mọi broadcast_alarm và cả vòng
        # monitor nhịp tim — một thiết bị hỏng đủ để làm tê liệt phát báo động
        # toàn viện. Socket cũ đóng muộn cũng vô hại: handler của nó gọi
        # disconnect_station(code, socket_cũ) và bị guard danh tính chặn lại.
        #
        # Mã đóng phải là 4001 "Station session superseded", không phải 1000. Đóng
        # sớm ở đây thay cho việc để handler cũ tự phát hiện, nên mã 1000 sẽ khiến
        # client coi đây là đóng bình thường và thử lại sau ~1 giây — hai thiết bị
        # mở cùng mã trạm sẽ đá nhau liên tục, mỗi vòng kèm một lượt ghi DB và
        # broadcast STATION_STATUS. 4001 cho client biết phải chờ lâu (15 giây) và
        # hiện cảnh báo cho người trực.
        if previous is not None and previous is not websocket:
            try:
                await asyncio.wait_for(
                    previous.close(code=4001, reason='Station session superseded'), timeout=2
                )
            except Exception:
                logger.debug("Không đóng được socket cũ của trạm %s", station_code, exc_info=True)

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
            if websocket is None:
                # Không có danh tính socket thì không thể chứng minh đây là phiên của
                # mình, nên KHÔNG được đuổi phiên đang giữ trạm. Trước đây nhánh này
                # xoá thẳng socket đang sống — một vòng monitor nhịp tim cũ đủ để đá
                # trạm vừa kết nối lại ra khỏi hệ thống. Không có danh tính cũng
                # nghĩa là không có chuyển trạng thái nào để ghi: chỉ dọn dấu vết.
                if current_ws is not None:
                    logger.warning(
                        "Refused unidentified disconnect for station %s: a live socket is registered", station_code
                    )
                self.last_heartbeats.pop(station_code, None)
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

    async def touch_station(self, station_code: str) -> bool:
        """Làm mới đồng hồ sống cho trạm đang có socket, không ghi DB.

        Dùng cho các thông điệp chứng minh kênh realtime còn sống nhưng không
        mang theo trạng thái sẵn sàng (ví dụ PING). Nếu PING không làm mới đồng
        hồ, một client chỉ dùng PING sẽ bị monitor cắt ở ngưỡng 15 giây dù hoàn
        toàn khoẻ.
        """
        async with self._lock:
            if station_code not in self.active_stations:
                return False
            self.last_heartbeats[station_code] = datetime.now(timezone.utc)
            return True

    async def update_heartbeat(self, station_code: str, audio_ready: bool = False, client_ready: bool = True):
        now = datetime.now(timezone.utc)
        async with self._lock:
            # Chỉ theo dõi nhịp tim của trạm ĐANG có socket. Ghi vào last_heartbeats cho
            # một trạm không có kết nối (ví dụ heartbeat HTTP) sẽ tạo entry mồ côi khiến
            # monitor tưởng trạm vừa mất kết nối và đánh OFFLINE giả mỗi vòng.
            connected = station_code in self.active_stations
            if connected:
                self.last_heartbeats[station_code] = now

        if not connected:
            # Nhịp tim không kèm WebSocket (endpoint HTTP dự phòng): trạm còn sống
            # nhưng KHÔNG có kênh nhận báo động. Ghi websocket_connected=True ở đây
            # sẽ phủ nhận chính kết quả kiểm tra của endpoint và dựng lại đúng lời
            # nói dối "ONLINE" mà endpoint vừa sửa. last_seen_at đã do endpoint ghi.
            return

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

        Trả về số trạm gửi THÀNH CÔNG và số trạm đích, để tầng API nói được sự
        thật với người trực: một báo động "đã phát" tới 12 trạm nhưng chỉ 9 trạm
        đang có kết nối là thông tin khác hẳn với "đã phát tới mọi trạm".
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

        delivered = 0

        async def deliver(code, ws):
            nonlocal delivered
            try:
                await asyncio.wait_for(ws.send_text(json.dumps(message)), timeout=1)
                delivered += 1
            except Exception as e:
                logger.warning(f"Failed to send alarm to station {code}: {e}")
                dead_stations.append((code, ws))
        await asyncio.gather(*(deliver(code, ws) for code, ws in recipients))

        # 2. Send to all dashboard clients
        await self.broadcast_to_dashboards(message)

        # Cleanup any dead sockets. Phải truyền kèm socket đã hỏng: disconnect_station
        # dùng nó làm danh tính phiên, còn lời gọi không danh tính sẽ bị guard từ chối
        # (đúng như thiết kế) và socket chết nằm lại trong active_stations vĩnh viễn —
        # mọi báo động sau đó lại thử gửi vào xác đó, tốn 1 giây timeout mỗi lần.
        for code, ws in dead_stations:
            await self.disconnect_station(code, ws)

        return {"delivered": delivered, "targets": len(target_station_codes) if target_station_codes is not None else len(recipients)}

    @property
    def monitor_expected(self) -> bool:
        """start_monitor() đã từng được gọi chưa.

        Dùng để tách "chưa từng giám sát" khỏi "đã giám sát rồi chết". Không có
        cờ này thì /api/health buộc phải gộp hai thứ làm một, và mọi tiến trình
        chưa chạy tới bước start_monitor đều bị báo suy giảm.
        """
        return self._monitor_expected

    @property
    def monitor_running(self) -> bool:
        """Vòng giám sát nhịp tim còn sống hay không.

        Nếu task này chết, không trạm nào bị đánh dấu offline nữa và dashboard sẽ
        hiện ONLINE vĩnh viễn cho thiết bị đã rút điện — đúng loại hỏng im lặng mà
        /api/health phải nói ra thay vì luôn trả websocket="ok".
        """
        return self._monitor_task is not None and not self._monitor_task.done()

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
            await asyncio.wait_for(ws.send_text(json.dumps(message)), timeout=1)
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
                values = {
                    "websocket_connected": connected,
                    "status": status,
                    "last_seen_at": now,
                    "updated_at": now,
                }
                if not connected:
                    # Trạm đã mất kết nối thì không còn chứng cứ nào cho việc phát được
                    # âm thanh. Giữ cờ cũ sẽ khiến dashboard hiện "AUDIO READY" cho một
                    # trạm đã offline nhiều ngày — đúng loại tuyên bố sai cần tránh.
                    values["audio_ready"] = False
                    values["client_ready"] = False
                stmt = update(Station).where(Station.station_code == station_code).values(**values)
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

    async def _enforce_timeouts(self, timed_out: List[tuple], threshold_seconds: int):
        """Ngắt các trạm quá hạn, kiểm tra lại trạng thái ngay trước khi ngắt.

        ``timed_out`` là một **ảnh chụp** tại thời điểm quét. Giữa lúc chụp và lúc
        ngắt, một nhịp tim mới có thể đã tới — hoặc trạm đã kết nối lại bằng socket
        khác. Ngắt theo ảnh chụp cũ sẽ cắt đúng trạm vừa chứng minh mình còn sống,
        và vì WebSocket là kênh nhận báo động duy nhất, trạm đó im lặng cho tới khi
        client tự kết nối lại. Vì vậy phải kiểm lại **cả danh tính socket lẫn mốc
        nhịp tim mới nhất** dưới lock trước khi quyết định.
        """
        for code, ws in timed_out:
            async with self._lock:
                current_ws = self.active_stations.get(code)
                last_seen = self.last_heartbeats.get(code)
                # Socket đã bị thay bằng phiên mới, hoặc không còn dấu vết nhịp tim:
                # ảnh chụp này đã cũ, không có gì để ngắt.
                if current_ws is not ws or last_seen is None:
                    continue
                # Nhịp tim mới hơn ngưỡng nghĩa là trạm vẫn khoẻ — bỏ qua.
                if (datetime.now(timezone.utc) - last_seen).total_seconds() <= threshold_seconds:
                    continue

            logger.warning(f"Station {code} timed out ({threshold_seconds}s with no heartbeat). Marking offline.")
            try:
                await ws.close(code=1011, reason='Heartbeat timeout')
            except Exception:
                pass
            await self.disconnect_station(code, ws)

    async def _check_timeouts(self, threshold_seconds: int):
        while True:
            try:
                await asyncio.sleep(5)
                now = datetime.now(timezone.utc)
                async with AsyncSessionLocal() as session:
                    await expire_alarms(session)
                timed_out = []

                async with self._lock:
                    for code in list(self.last_heartbeats.keys()):
                        last_seen = self.last_heartbeats[code]
                        if (now - last_seen).total_seconds() <= threshold_seconds:
                            continue
                        ws = self.active_stations.get(code)
                        if ws is None:
                            # Entry heartbeat mồ côi: không còn socket nào cho trạm này
                            # (ví dụ trạm chỉ gửi heartbeat HTTP). Chỉ dọn dấu vết, không
                            # đánh dấu offline — chưa từng có kết nối thật để mất, và ghi
                            # DEVICE_DISCONNECTED ở đây sẽ làm nhấp nháy dashboard mỗi vòng.
                            del self.last_heartbeats[code]
                            continue
                        timed_out.append((code, ws))

                await self._enforce_timeouts(timed_out, threshold_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat timeout monitor: {e}")

manager = ConnectionManager()
