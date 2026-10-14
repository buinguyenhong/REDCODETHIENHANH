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
        # Một lock cho mỗi trạm, dùng để xếp hàng các lượt ghi trạng thái của trạm
        # đó. Không dùng _lock cho việc này: _lock bảo vệ sổ trong bộ nhớ và không
        # được giữ qua I/O mạng/database. Xem _presence_lock().
        self._presence_locks: Dict[str, asyncio.Lock] = {}

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

        # Ghi trạng thái theo SỰ THẬT trong sổ phiên tại thời điểm ghi, rồi phát đi
        # đúng sự thật vừa ghi. Nếu trong lúc chờ lock mà phiên này đã bị thay (thiết
        # bị rớt rồi nối lại), giá trị trả về là trạng thái mới nhất — không phải
        # trạng thái ta định đặt — nên dashboard không bao giờ nhận một thông điệp
        # ONLINE cũ cho một trạm đã offline.
        connected = await self._sync_station_db_status(station_code, event="DEVICE_CONNECTED")
        await self._broadcast_station_status(station_code, connected)
        logger.info(f"Station connected: {station_code}")

    async def _broadcast_station_status(self, station_code: str, connected: bool):
        """Phát trạng thái trạm cho dashboard, luôn kèm đúng giá trị đã ghi vào DB.

        Tách riêng để ba đường dẫn cùng ghi trạng thái (kết nối, ngắt, cắt do quá
        hạn) không tự dựng thông điệp riêng và lệch nhau.
        """
        await self.broadcast_to_dashboards({
            "type": "STATION_STATUS",
            "station_code": station_code,
            "status": StationStatus.ONLINE.value if connected else StationStatus.OFFLINE.value,
            "websocket_connected": connected,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    async def _finalize_disconnect(self, station_code: str):
        """Hoàn tất việc một trạm rời sổ phiên: ghi DB, phát trạng thái, ghi log.

        Dùng chung cho hai đường dẫn cùng kết cục: handler ngắt kết nối và vòng
        giám sát nhịp tim cắt trạm quá hạn. Cả hai đã rút trạm khỏi ``active_stations``
        trước khi gọi hàm này, nên ``_sync_station_db_status`` thường suy ra OFFLINE.

        Ngoại lệ đáng lưu tâm: nếu một phiên mới đã kế chỗ trong lúc ta xử lý, sự
        thật là trạm ĐANG online. Khi đó hàm này không phát OFFLINE — phát OFFLINE cho
        một thiết bị vừa nối lại sẽ tắt đèn báo động của đúng khoa đang trực.
        """
        still_connected = await self._sync_station_db_status(station_code, event="DEVICE_DISCONNECTED")
        if still_connected:
            logger.info(
                f"Station {station_code}: phiên cũ rời đi nhưng một phiên mới đã kế chỗ; giữ nguyên ONLINE"
            )
            return
        await self._broadcast_station_status(station_code, False)
        logger.info(f"Station disconnected: {station_code}")

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

        # Ghi theo SỰ THẬT hiện tại, không theo ý định "tôi vừa ngắt". Nếu một phiên
        # mới đã kế chỗ trong lúc hàm này chạy, sự thật là trạm ĐANG online và bản
        # ghi phải nói đúng như vậy.
        await self._finalize_disconnect(station_code)

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

        # Lượt ghi này dùng chung đường ghi trạng thái với connect/disconnect, nên nó
        # xếp hàng sau các lượt ghi khác của cùng trạm và tự suy lại sự thật ngay
        # trước khi ghi: nếu phiên đã kết thúc trong lúc chờ, lượt ghi OFFLINE của
        # phiên đó mới là lượt cuối, và một lượt ghi ONLINE ở đây sẽ dựng lại đúng
        # trạng thái sai mà phát hiện P1 mô tả.
        await self._sync_station_db_status(
            station_code,
            readiness={"audio_ready": audio_ready, "client_ready": client_ready},
            seen_at=now,
        )

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
        """Gửi tới mọi dashboard đang mở, song song.

        Trước đây là vòng lặp tuần tự, mỗi socket chờ tối đa 1 giây. Hàm này nằm
        trên đường phản hồi của POST /api/alarms, nên vài dashboard treo nửa vời
        (máy ngủ, cáp đứt) cộng thẳng từng ấy giây vào thời gian người trực chờ
        xác nhận. Dùng chung khuôn với broadcast_alarm ở trên: gather song song,
        rồi dọn socket chết sau khi tất cả đã có kết quả.
        """
        msg_str = json.dumps(message)
        async with self._lock:
            dashboards = list(self.active_dashboards)

        dead_dashboards = []

        async def deliver(ws):
            try:
                await asyncio.wait_for(ws.send_text(msg_str), timeout=1)
            except Exception:
                dead_dashboards.append(ws)

        if dashboards:
            await asyncio.gather(*(deliver(ws) for ws in dashboards))

        for ws in dead_dashboards:
            await self.disconnect_dashboard(ws)

    @property
    def connected_station_codes(self) -> set:
        """Ảnh chụp mã các trạm đang có socket, đọc thuần từ sổ trong bộ nhớ.

        Dùng cho phản hồi phát lại báo động: số trạm nhận được phải suy ra từ sổ
        này chứ không lấy lại được kết quả gửi của lượt broadcast gốc. Không await
        nên không có điểm nhường quyền giữa chừng, ảnh chụp luôn nhất quán.
        """
        return set(self.active_stations)

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

    def _presence_lock(self, station_code: str) -> asyncio.Lock:
        """Lock tuần tự hoá các lượt ghi trạng thái hiện diện của MỘT trạm.

        Lock chính ``_lock`` chỉ bảo vệ sổ trong bộ nhớ; nó không thể bảo vệ thứ tự
        hoàn thành của hai giao dịch database, vì mỗi lượt ghi mở phiên riêng và
        ``commit`` là I/O. Khi lock chính đã được thả, hai lượt ghi connect/disconnect
        chạy song song và lượt nào commit sau sẽ thắng — bất kể lượt đó cũ hay mới.

        Vì vậy mỗi trạm có thêm một lock riêng, chỉ dùng để xếp hàng các lượt ghi
        trạng thái. Không phải lock toàn cục: nhịp tim của 100 trạm ghi vài giây một
        lần, dùng chung một lock sẽ khiến mọi trạm xếp hàng sau nhau vô ích.
        """
        lock = self._presence_locks.get(station_code)
        if lock is None:
            lock = asyncio.Lock()
            self._presence_locks[station_code] = lock
        return lock

    async def _sync_station_db_status(
        self,
        station_code: str,
        event: Optional[str] = None,
        readiness: Optional[Dict[str, bool]] = None,
        seen_at: Optional[datetime] = None,
    ) -> bool:
        """Ghi trạng thái hiện diện của trạm theo SỰ THẬT hiện tại trong bộ nhớ.

        Đây là điểm sửa cho phát hiện P1 "race khi cập nhật ONLINE/OFFLINE". Trước
        đây mỗi lời gọi tự khai trạng thái của mình: ``connect_station`` ghi ONLINE,
        ``disconnect_station`` ghi OFFLINE. Hai lượt ghi không được tuần tự hoá, nên
        một phiên cũ có thể commit OFFLINE *sau* khi phiên mới đã commit ONLINE, và
        database báo OFFLINE trong khi socket mới đang hoạt động — đúng lời nói dối
        nguy hiểm nhất với hệ thống này, vì bảng giám sát sẽ hiện một khoa đã tắt
        báo động trong khi khoa đó đang nhận báo động bình thường.

        Cách sửa: không ghi "trạng thái tôi định đặt" mà ghi "trạng thái đang đúng
        lúc này", và tuần tự hoá theo từng trạm. Lượt ghi cuối cùng luôn là lượt đọc
        sự thật muộn nhất, nên database hội tụ về đúng trạng thái của bộ nhớ bất kể
        thứ tự hoàn thành của các giao dịch.

        ``event`` là hành động của phiên (``DEVICE_CONNECTED``/``DEVICE_DISCONNECTED``)
        để ghi audit — nhưng chỉ ghi khi hành động đó khớp với trạng thái suy ra được.
        Một lượt ngắt bị một phiên mới kế chỗ không phải là "trạm mất kết nối", và
        ghi audit như vậy sẽ khiến người đọc log tưởng một khoa vừa rơi khỏi hệ thống.

        Trả về sự thật vừa đọc, để lời gọi broadcast đi cùng một sự thật với bản ghi
        database — nếu không, dashboard lại nhận một thông điệp OFFLINE cũ.
        """
        async with self._presence_lock(station_code):
            async with self._lock:
                connected = station_code in self.active_stations
            await self._update_station_db_status(station_code, connected, event, readiness, seen_at)
            return connected

    async def _update_station_db_status(
        self,
        station_code: str,
        connected: bool,
        event: Optional[str] = None,
        readiness: Optional[Dict[str, bool]] = None,
        seen_at: Optional[datetime] = None,
    ):
        now = datetime.now(timezone.utc)
        status = StationStatus.ONLINE.value if connected else StationStatus.OFFLINE.value
        # Audit chỉ ghi khi hành động của phiên khớp với trạng thái thật sự đã ghi.
        matched_event = "DEVICE_CONNECTED" if connected else "DEVICE_DISCONNECTED"
        event_type = event if event == matched_event else None
        async with AsyncSessionLocal() as session:
            try:
                # Update station
                values = {
                    "websocket_connected": connected,
                    "status": status,
                    "last_seen_at": seen_at or now,
                    "updated_at": now,
                }
                if not connected:
                    # Trạm đã mất kết nối thì không còn chứng cứ nào cho việc phát được
                    # âm thanh. Giữ cờ cũ sẽ khiến dashboard hiện "AUDIO READY" cho một
                    # trạm đã offline nhiều ngày — đúng loại tuyên bố sai cần tránh.
                    values["audio_ready"] = False
                    values["client_ready"] = False
                elif readiness is not None:
                    # Cờ sẵn sàng chỉ được ghi kèm một nhịp tim của phiên đang sống.
                    values["audio_ready"] = bool(readiness.get("audio_ready", False))
                    values["client_ready"] = bool(readiness.get("client_ready", True))
                stmt = update(Station).where(Station.station_code == station_code).values(**values)
                await session.execute(stmt)

                if event_type is not None:
                    station_id = (await session.execute(select(Station.id).where(Station.station_code == station_code))).scalar_one_or_none()
                    session.add(SystemEvent(
                        station_id=station_id,
                        event_type=event_type,
                        severity="INFO" if connected else "WARNING",
                        message=f"Station {station_code} {'connected' if connected else 'disconnected'}",
                        event_metadata={"station_code": station_code, "status": status},
                        created_at=now
                    ))
                await session.commit()
            except Exception as e:
                logger.error(f"Error updating station status in DB for {station_code}: {e}")

    async def _enforce_timeouts(self, timed_out: List[tuple], threshold_seconds: int):
        """Ngắt các trạm quá hạn: quyết định và thi hành trong CÙNG một bước nguyên tử.

        ``timed_out`` là một **ảnh chụp** tại thời điểm quét. Giữa lúc chụp và lúc
        ngắt, một nhịp tim mới có thể đã tới — hoặc trạm đã kết nối lại bằng socket
        khác. Ngắt theo ảnh chụp cũ sẽ cắt đúng trạm vừa chứng minh mình còn sống,
        và vì WebSocket là kênh nhận báo động duy nhất, trạm đó im lặng cho tới khi
        client tự kết nối lại. Vì vậy phải kiểm lại **cả danh tính socket lẫn mốc
        nhịp tim mới nhất** dưới lock trước khi quyết định.

        Kiểm lại là chưa đủ: nếu chỉ kiểm rồi thả lock để đóng socket, vẫn còn một
        khe giữa "đã kiểm xong" và "đã đóng" mà một nhịp tim hợp lệ lọt vào, làm
        trạng thái nhảy về ONLINE trong khi phiên đang bị ngắt. Nên ở đây quyết định
        và thi hành nằm chung một khối lock: ngay khi biết chắc phải ngắt, **rút
        phiên ra khỏi sổ trong cùng khối đó**. Từ thời điểm ấy, ``update_heartbeat``
        và ``touch_station`` đều từ chối trạm không còn socket, nên nhịp tim tới muộn
        không thể làm sống lại phiên đã bị kết luận là quá hạn — trạng thái và socket
        không còn cơ hội mâu thuẫn với nhau.

        Việc đóng socket (network I/O, có thể treo với kết nối half-open) vẫn nằm
        NGOÀI lock, đúng như yêu cầu: không giữ lock qua I/O mạng.
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
                # Chốt quyết định bằng cách rút phiên khỏi sổ ngay tại đây. Không có
                # bước await nào giữa lần kiểm cuối và lần rút này, nên không còn khe
                # để nhịp tim chen vào.
                del self.active_stations[code]
                self.last_heartbeats.pop(code, None)

            logger.warning(f"Station {code} timed out ({threshold_seconds}s with no heartbeat). Marking offline.")
            try:
                await ws.close(code=1011, reason='Heartbeat timeout')
            except Exception:
                pass

            # Phiên đã bị rút khỏi sổ nên handler của socket này gọi
            # disconnect_station(code, ws) sẽ bị guard danh tính từ chối và không ghi
            # gì thêm — hai lượt ghi trùng lặp sẽ nhấp nháy dashboard. Vì vậy chính
            # chỗ này hoàn tất chuyển trạng thái.
            await self._finalize_disconnect(code)

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
