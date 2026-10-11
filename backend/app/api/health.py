import logging
import time

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_admin
from app.config import settings
from app.core.websocket_manager import manager
from app.database import get_db
from app.models import Station, User
from app.schemas import HealthResponse

logger = logging.getLogger("redcode.health")

router = APIRouter(prefix="/health", tags=["Health Check"])

@router.get("", response_model=HealthResponse)
async def get_health(db: AsyncSession = Depends(get_db)):
    """Trạng thái tổng hợp ở mức tối thiểu, dùng được cho probe không xác thực.

    Endpoint này trả các trường tổng hợp: không mã trạm, không thông báo lỗi thô,
    không chuỗi kết nối. Chi tiết chẩn đoán nằm ở ``/api/health/db`` và
    ``/api/health/websocket``, cả hai đều yêu cầu quyền ADMIN.

    Endpoint này **không gọi ra mạng ngoài**. Trước đây khi n8n được bật, mỗi lần
    đọc health còn chờ tới 1,5 giây để hỏi ``/healthz`` của n8n. Một probe hạ tầng
    gọi endpoint này vài giây một lần sẽ dồn request vào đó, và tệ hơn: độ trễ của
    một hệ thống phụ lại quyết định độ trễ của phép đo sức khoẻ hệ thống chính. n8n
    là đường bổ sung — báo động nội bộ không đi qua nó — nên trạng thái ở đây chỉ
    phản ánh **cấu hình** (``enabled``/``disabled``). Kiểm tra n8n có sống hay không
    là việc riêng, ở ``/api/health/n8n`` (ADMIN), và không bao giờ kéo ``status``
    của REDCODE xuống.
    """
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    # Vòng giám sát nhịp tim không chỉ đánh dấu trạm offline: mỗi vòng nó còn gọi
    # expire_alarms(). Vòng này chết nghĩa là (1) trạm rút điện vẫn hiện ONLINE vĩnh
    # viễn và (2) báo động ACTIVE hết hạn không bao giờ chuyển sang EXPIRED. Đó là
    # mất chức năng thật, nên phải hiện ra ở trường tổng hợp.
    #
    # Ba giá trị, không phải hai. "not_started" nghĩa là vòng giám sát chưa từng
    # được bật hoặc đã được dừng theo lệnh — app chưa xong bước khởi động, hoặc
    # đang tắt. Cả hai đều không phải sự cố. Cái đáng báo là đã bật rồi chết:
    # gộp "chưa từng bật" với "đã bật rồi chết" làm một sẽ khiến mọi lần đọc health
    # trong lúc khởi động đều báo suy giảm, và làm loãng đúng ca cần phát hiện.
    if not manager.monitor_expected:
        ws_status = "not_started"
    elif manager.monitor_running:
        ws_status = "ok"
    else:
        ws_status = "degraded"

    n8n_status = "enabled" if settings.N8N_ENABLED else "disabled"

    total_stations = 0
    if db_status == "ok":
        total_stations = (await db.execute(select(func.count(Station.id)))).scalar() or 0
    active_stations = len(manager.active_stations)

    # Hai câu hỏi khác nhau, trước đây bị gộp làm một trường:
    #
    # - liveness: tiến trình còn phục vụ được request này không. Trả lời được tức
    #   là còn sống; cách xử lý là restart tiến trình, không phải đọc thêm trường.
    # - status (readiness): hệ thống còn LÀM ĐƯỢC VIỆC CỦA NÓ không. Trước đây chỉ
    #   cần database "ok" là trả "ok", nên một tiến trình mất hẳn vòng giám sát vẫn
    #   tự báo HOẠT ĐỘNG trong khi đã mù với thiết bị offline và không còn kết thúc
    #   báo động hết hạn. Giờ readiness là kết quả gộp của cả hai vế.
    liveness = "ok"
    if db_status != "ok":
        overall_status = "error"
    elif ws_status == "degraded":
        overall_status = "degraded"
    else:
        overall_status = "ok"

    return HealthResponse(
        status=overall_status,
        liveness=liveness,
        database=db_status,
        websocket=ws_status,
        n8n=n8n_status,
        active_stations=active_stations,
        total_stations=total_stations
    )

@router.get("/db")
async def health_database(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin),
):
    """Độ trễ database, dành cho người vận hành. Yêu cầu ADMIN.

    Trước đây endpoint này công khai và trả nguyên văn thông báo exception của
    driver. Thông báo đó thường chứa host, cổng, tên user và đôi khi cả chuỗi kết
    nối — đủ để dựng bản đồ hạ tầng nội bộ từ một máy bất kỳ trong LAN. Lỗi thật
    được ghi vào log phía server; phản hồi HTTP chỉ nói database có phục vụ được
    hay không.
    """
    start = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.error("Health check database thất bại", exc_info=True)
        return {"status": "error", "latency_ms": latency_ms}

@router.get("/n8n")
async def health_n8n(admin: User = Depends(get_current_active_admin)):
    """Kiểm tra n8n có sống hay không. Yêu cầu ADMIN.

    Tách khỏi ``/api/health`` vì đây là phép đo **phụ thuộc mạng ngoài**, có thể
    chậm tới ``N8N_TIMEOUT_SECONDS``. Người vận hành gọi endpoint này khi cần biết
    vì sao thông báo đang tồn đọng, không phải để quyết định REDCODE còn chạy được
    hay không. n8n chết không làm trạng thái REDCODE suy giảm.
    """
    if not settings.N8N_ENABLED:
        return {"status": "disabled", "reachable": False, "latency_ms": None}
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            res = await client.get(settings.N8N_WEBHOOK_URL.split("/webhook")[0] + "/healthz")
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"status": "ok" if res.is_success else "degraded", "reachable": res.is_success, "latency_ms": latency_ms}
    except Exception:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.warning("Kiểm tra n8n thất bại", exc_info=True)
        return {"status": "degraded", "reachable": False, "latency_ms": latency_ms}

@router.get("/websocket")
async def health_websocket(admin: User = Depends(get_current_active_admin)):
    """Chi tiết kênh realtime, gồm mã trạm đang kết nối. Yêu cầu ADMIN.

    Danh sách mã trạm là sơ đồ các khoa đang trực — thông tin vận hành nội bộ,
    không dành cho một endpoint công khai không xác thực.
    """
    return {
        "status": "ok" if manager.monitor_running else "degraded",
        "monitor_running": manager.monitor_running,
        "monitor_expected": manager.monitor_expected,
        "active_connections": len(manager.active_dashboards) + len(manager.active_stations),
        "dashboard_connections": len(manager.active_dashboards),
        "active_stations_count": len(manager.active_stations),
        "active_station_codes": list(manager.active_stations.keys())
    }
