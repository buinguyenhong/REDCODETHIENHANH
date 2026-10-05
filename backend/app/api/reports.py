import io
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from app.database import get_db
from app.models import Alarm, AlarmType, Department, Station, SystemEvent, User
from app.api.deps import get_current_user

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.get("/summary")
async def get_summary_report(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    stmt = select(Alarm).options(
        selectinload(Alarm.alarm_type),
        selectinload(Alarm.source_department)
    )
    if from_date:
        stmt = stmt.where(Alarm.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        stmt = stmt.where(Alarm.created_at <= datetime.fromisoformat(to_date))

    alarms = (await db.execute(stmt)).scalars().all()

    total_alarms = len(alarms)
    by_type: Dict[str, int] = {}
    by_dept: Dict[str, int] = {}
    by_status: Dict[str, int] = {}

    for a in alarms:
        t_name = a.alarm_type.name if a.alarm_type else "Không xác định"
        d_name = a.source_department.name if a.source_department else "Không xác định"
        by_type[t_name] = by_type.get(t_name, 0) + 1
        by_dept[d_name] = by_dept.get(d_name, 0) + 1
        by_status[a.status] = by_status.get(a.status, 0) + 1

    # Count offline events from system_events
    offline_stmt = select(func.count(SystemEvent.id)).where(SystemEvent.event_type == "DEVICE_DISCONNECTED")
    offline_count = (await db.execute(offline_stmt)).scalar() or 0

    return {
        "total_alarms": total_alarms,
        "by_type": by_type,
        "by_department": by_dept,
        "by_status": by_status,
        "device_offline_events_count": offline_count
    }

@router.get("/export-xlsx")
async def export_alarms_xlsx(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user)
        )
        .order_by(Alarm.created_at.asc())
    )
    if from_date:
        stmt = stmt.where(Alarm.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        stmt = stmt.where(Alarm.created_at <= datetime.fromisoformat(to_date))

    alarms = (await db.execute(stmt)).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "BaoCao_Redcode"

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
        "Khoa/Phòng", "Vị trí", "Ghi chú", "Người phát", "Trạng thái", "Thứ tự Server"
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
        created_str = a.created_at.strftime("%d/%m/%Y %H:%M:%S") if a.created_at else ""
        t_code = a.alarm_type.code if a.alarm_type else ""
        t_name = a.alarm_type.name if a.alarm_type else ""
        dept_name = a.source_department.name if a.source_department else ""
        user_name = a.created_by_user.display_name if a.created_by_user else ""

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
            a.server_sequence
        ]
        ws.append(row_data)

        row_num = idx + 1
        ws.row_dimensions[row_num].height = 20
        for col_idx in range(1, len(row_data) + 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if col_idx in [1, 9, 10]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(vertical="center")

    # Column widths
    widths = [6, 20, 16, 26, 22, 22, 35, 18, 16, 14]
    for i, w in enumerate(widths, 1):
        col_letter = chr(64 + i) if i <= 26 else f"A{chr(64 + i - 26)}"
        ws.column_dimensions[col_letter].width = w

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"redcode_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
