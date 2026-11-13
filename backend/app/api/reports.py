import io
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple, List
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from zoneinfo import ZoneInfo
from app.database import get_db
from app.models import Alarm, AlarmType, Department, Station, SystemEvent, User, AlarmStationState
from app.api.deps import get_current_active_admin

router = APIRouter(prefix="/reports", tags=["Reports"])

def parse_date_range(from_date_str: Optional[str], to_date_str: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Half-open [start, end): date-only end is next hospital midnight.
    Naive datetimes are hospital local time; offset datetimes are normalized UTC.
    """
    start_dt = None
    end_dt = None
    if from_date_str and from_date_str.strip():
        clean_str = from_date_str.strip()
        try:
            dt = datetime.fromisoformat(clean_str)
        except ValueError:
            raise HTTPException(status_code=422, detail='Ngày không hợp lệ')
        if len(clean_str) <= 10:
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')).astimezone(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
        dt = dt.astimezone(timezone.utc)
        start_dt = dt

    if to_date_str and to_date_str.strip():
        clean_str = to_date_str.strip()
        try:
            dt = datetime.fromisoformat(clean_str)
        except ValueError:
            raise HTTPException(status_code=422, detail='Ngày không hợp lệ')
        if len(clean_str) <= 10:
            dt = (dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')) + timedelta(days=1)).astimezone(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
        dt = dt.astimezone(timezone.utc)
        end_dt = dt

    if start_dt and end_dt and start_dt >= end_dt:
        raise HTTPException(status_code=422, detail='Khoảng ngày không hợp lệ')
    return start_dt, end_dt

def _get_dialect_name(db: AsyncSession) -> str:
    bind = getattr(db, "bind", None)
    if bind is None:
        sync_session = getattr(db, "sync_session", None)
        bind = sync_session.get_bind() if sync_session is not None else None
    return bind.dialect.name if bind is not None else "sqlite"


def _sql_seconds_diff(dialect_name: str, start_col, end_col):
    if dialect_name == "postgresql":
        return func.extract("epoch", end_col - start_col)
    return (func.julianday(end_col) - func.julianday(start_col)) * 86400.0


@router.get("/summary")
async def get_summary_report(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_admin)
):
    start_dt, end_dt = parse_date_range(from_date, to_date)
    dialect_name = _get_dialect_name(db)

    alarm_filters: List[Any] = []
    if start_dt:
        alarm_filters.append(Alarm.created_at >= start_dt)
    if end_dt:
        alarm_filters.append(Alarm.created_at < end_dt)

    # SQL aggregation: tổng theo trạng thái, loại báo động, khoa/phòng, ngày và tháng
    # theo múi giờ bệnh viện (Asia/Ho_Chi_Minh, UTC+7), không tải toàn bộ lịch sử vào RAM.
    status_rows = (await db.execute(
        select(Alarm.status, func.count(Alarm.id))
        .where(*alarm_filters)
        .group_by(Alarm.status)
    )).all()
    by_status: Dict[str, int] = {status: int(count) for status, count in status_rows}
    total_alarms = sum(by_status.values())

    type_label = func.coalesce(AlarmType.name, "Không xác định")
    type_rows = (await db.execute(
        select(type_label, func.count(Alarm.id))
        .select_from(Alarm)
        .outerjoin(AlarmType, Alarm.alarm_type_id == AlarmType.id)
        .where(*alarm_filters)
        .group_by(type_label)
    )).all()
    by_type: Dict[str, int] = {name: int(count) for name, count in type_rows}

    dept_label = func.coalesce(Department.name, "Không xác định")
    dept_rows = (await db.execute(
        select(dept_label, func.count(Alarm.id))
        .select_from(Alarm)
        .outerjoin(Department, Alarm.source_department_id == Department.id)
        .where(*alarm_filters)
        .group_by(dept_label)
    )).all()
    by_dept: Dict[str, int] = {name: int(count) for name, count in dept_rows}

    if dialect_name == "postgresql":
        day_expr = func.to_char(func.timezone("Asia/Ho_Chi_Minh", Alarm.created_at), "YYYY-MM-DD")
        month_expr = func.to_char(func.timezone("Asia/Ho_Chi_Minh", Alarm.created_at), "YYYY-MM")
    else:
        day_expr = func.strftime("%Y-%m-%d", Alarm.created_at, "+7 hours")
        month_expr = func.strftime("%Y-%m", Alarm.created_at, "+7 hours")

    day_rows = (await db.execute(
        select(day_expr, func.count(Alarm.id))
        .where(*alarm_filters)
        .group_by(day_expr)
    )).all()
    by_day: Dict[str, int] = {day: int(count) for day, count in day_rows if day}

    month_rows = (await db.execute(
        select(month_expr, func.count(Alarm.id))
        .where(*alarm_filters)
        .group_by(month_expr)
    )).all()
    by_month: Dict[str, int] = {month: int(count) for month, count in month_rows if month}

    # Thời gian nhận / hiển thị (presentation) / ACK (dismiss) trung bình bằng SQL; trả None nếu thiếu dữ liệu.
    received_diff = case(
        (and_(AlarmStationState.received_at.is_not(None), AlarmStationState.received_at >= Alarm.created_at),
         _sql_seconds_diff(dialect_name, Alarm.created_at, AlarmStationState.received_at)),
        else_=None,
    )
    presentation_diff = case(
        (and_(AlarmStationState.displayed_at.is_not(None), AlarmStationState.displayed_at >= Alarm.created_at),
         _sql_seconds_diff(dialect_name, Alarm.created_at, AlarmStationState.displayed_at)),
        else_=None,
    )
    ack_diff = case(
        (and_(AlarmStationState.dismissed_at.is_not(None), AlarmStationState.dismissed_at >= Alarm.created_at),
         _sql_seconds_diff(dialect_name, Alarm.created_at, AlarmStationState.dismissed_at)),
        else_=None,
    )
    timing_row = (await db.execute(
        select(
            func.count(received_diff),
            func.avg(received_diff),
            func.count(presentation_diff),
            func.avg(presentation_diff),
            func.count(ack_diff),
            func.avg(ack_diff),
        )
        .select_from(AlarmStationState)
        .join(Alarm, Alarm.id == AlarmStationState.alarm_id)
        .where(*alarm_filters)
    )).one()
    recv_count, recv_avg, pres_count, pres_avg, ack_count, ack_avg = timing_row
    avg_received_seconds = round(float(recv_avg), 2) if (recv_count or 0) > 0 and recv_avg is not None else None
    avg_presentation_seconds = round(float(pres_avg), 2) if (pres_count or 0) > 0 and pres_avg is not None else None
    avg_ack_seconds = round(float(ack_avg), 2) if (ack_count or 0) > 0 and ack_avg is not None else None

    # Thống kê số lần offline & tổng thời gian offline theo trạm (ghép cặp DEVICE_DISCONNECTED -> DEVICE_CONNECTED).
    offline_stmt = select(func.count(SystemEvent.id)).where(SystemEvent.event_type == "DEVICE_DISCONNECTED")
    if start_dt:
        offline_stmt = offline_stmt.where(SystemEvent.created_at >= start_dt)
    if end_dt:
        offline_stmt = offline_stmt.where(SystemEvent.created_at < end_dt)
    offline_count = int((await db.execute(offline_stmt)).scalar() or 0)

    ev_filters: List[Any] = [
        SystemEvent.station_id.is_not(None),
        SystemEvent.event_type.in_(["DEVICE_DISCONNECTED", "DEVICE_CONNECTED"]),
    ]
    if start_dt:
        ev_filters.append(SystemEvent.created_at >= start_dt)
    if end_dt:
        ev_filters.append(SystemEvent.created_at < end_dt)

    ev_sub = (
        select(
            SystemEvent.station_id.label("station_id"),
            SystemEvent.event_type.label("event_type"),
            SystemEvent.created_at.label("created_at"),
            func.lead(SystemEvent.event_type).over(
                partition_by=SystemEvent.station_id,
                order_by=(SystemEvent.created_at.asc(), SystemEvent.id.asc()),
            ).label("next_event_type"),
            func.lead(SystemEvent.created_at).over(
                partition_by=SystemEvent.station_id,
                order_by=(SystemEvent.created_at.asc(), SystemEvent.id.asc()),
            ).label("next_created_at"),
        )
        .where(*ev_filters)
        .subquery()
    )
    paired_offline_dur = case(
        (
            and_(
                ev_sub.c.next_event_type == "DEVICE_CONNECTED",
                ev_sub.c.next_created_at.is_not(None),
                ev_sub.c.next_created_at >= ev_sub.c.created_at,
            ),
            _sql_seconds_diff(dialect_name, ev_sub.c.created_at, ev_sub.c.next_created_at),
        ),
        else_=None,
    )
    station_offline_rows = (await db.execute(
        select(
            ev_sub.c.station_id,
            Station.station_code,
            Station.name,
            func.count().label("offline_count"),
            func.count(paired_offline_dur).label("resolved_intervals_count"),
            func.sum(paired_offline_dur).label("offline_seconds"),
        )
        .select_from(ev_sub)
        .join(Station, Station.id == ev_sub.c.station_id)
        .where(ev_sub.c.event_type == "DEVICE_DISCONNECTED")
        .group_by(ev_sub.c.station_id, Station.station_code, Station.name)
        .order_by(Station.station_code.asc())
    )).all()

    by_station_offline = []
    total_paired_intervals = 0
    total_offline_seconds = 0.0
    for st_id, st_code, st_name, st_off_cnt, st_paired_cnt, st_off_sec in station_offline_rows:
        paired_cnt = int(st_paired_cnt or 0)
        total_paired_intervals += paired_cnt
        dur_val = round(float(st_off_sec), 2) if paired_cnt > 0 and st_off_sec is not None else None
        if dur_val is not None:
            total_offline_seconds += float(st_off_sec)
        by_station_offline.append({
            "station_id": st_id,
            "station_code": st_code,
            "station_name": st_name,
            "offline_count": int(st_off_cnt or 0),
            "resolved_intervals_count": paired_cnt,
            "offline_duration_seconds": dur_val,
        })

    return {
        "total_alarms": total_alarms,
        "by_day": by_day,
        "by_month": by_month,
        "by_type": by_type,
        "by_department": by_dept,
        "by_status": by_status,
        "device_offline_events_count": offline_count,
        "total_offline_duration_seconds": round(total_offline_seconds, 2) if total_paired_intervals > 0 else None,
        "by_station_offline": by_station_offline,
        "avg_received_seconds": avg_received_seconds,
        "avg_presentation_seconds": avg_presentation_seconds,
        "avg_ack_seconds": avg_ack_seconds,
    }

@router.get("/export-xlsx")
async def export_alarms_xlsx(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_admin)
):
    start_dt, end_dt = parse_date_range(from_date, to_date)

    stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.station_states).selectinload(AlarmStationState.station)
        )
        .order_by(Alarm.created_at.asc())
    )
    if start_dt:
        stmt = stmt.where(Alarm.created_at >= start_dt)
    if end_dt:
        stmt = stmt.where(Alarm.created_at < end_dt)

    alarms = (await db.execute(stmt)).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "BaoCao_Redcode"
    details = wb.create_sheet('TrangThai_Tram')
    details.append(['Alarm ID', 'Trạm', 'State', 'Received', 'Displayed', 'Audio started', 'Audio completed', 'Dismissed', 'Failed', 'Error'])
    def safe(value):
        return "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value
    def formatted(value):
        if not value:
            return ''
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).isoformat()
    def formatted_time(value):
        if not value:
            return ''
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%H:%M:%S')

    # Styling definitions
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    headers = [
        "STT", "Thời gian", "Mã báo động", "Tên báo động",
        "Khoa/Phòng", "Vị trí", "Ghi chú", "Người phát", "Trạng thái", "Thứ tự Server", "Chi tiết trạm nhận (States)"
    ]
    ws.append(headers)

    for col_idx, col_name in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    ws.row_dimensions[1].height = 26

    for idx, a in enumerate(alarms, 1):
        created_str = formatted(a.created_at)
        t_code = a.alarm_type.code if a.alarm_type else ""
        t_name = a.alarm_type.name if a.alarm_type else ""
        dept_name = a.source_department.name if a.source_department else ""
        user_name = a.created_by_user.display_name if a.created_by_user else ""

        # Summarize station states
        station_summaries = []
        if a.station_states:
            for st in a.station_states:
                st_code = st.station.station_code if st.station else f"ID-{st.station_id}"
                details.append([safe(v) for v in [a.id, st_code, st.state, formatted(st.received_at), formatted(st.displayed_at), formatted(st.audio_started_at), formatted(st.audio_completed_at), formatted(st.dismissed_at), formatted(st.failed_at), st.error_message]])
                st_text = f"{st_code}: {st.state}"
                if st.dismissed_at:
                    st_text += f" (Dismiss: {formatted_time(st.dismissed_at)})"
                station_summaries.append(st_text)
        stations_str = "; ".join(station_summaries) if station_summaries else "Chưa có trạm phản hồi"

        row_data = [
            idx,
            created_str,
            t_code,
            t_name,
            dept_name,
            a.source_location,
            a.note,
            user_name,
            a.status,
            a.server_sequence,
            stations_str
        ]
        ws.append([safe(v) for v in row_data])

        row_num = idx + 1
        ws.row_dimensions[row_num].height = 20
        for col_idx in range(1, len(row_data) + 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if col_idx in [1, 9, 10]:
                cell.alignment = Alignment(horizontal="center", vertical="center")

    # Column widths
    ws.column_dimensions['A'].width = 6
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 16
    ws.column_dimensions['D'].width = 26
    ws.column_dimensions['E'].width = 24
    ws.column_dimensions['F'].width = 26
    ws.column_dimensions['G'].width = 32
    ws.column_dimensions['H'].width = 20
    ws.column_dimensions['I'].width = 14
    ws.column_dimensions['J'].width = 14
    ws.column_dimensions['K'].width = 40

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"BaoCao_Redcode_{datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
