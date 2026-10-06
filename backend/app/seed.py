import os
import wave
import struct
import math
import logging
import secrets
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.config import settings
from app.models import (
    Department, User, Station, ReceiverGroup, ReceiverGroupStation, 
    AlarmType, AudioFile, UserRole, StationStatus, DepartmentAlarmPermission
)
from app.core.security import hash_password, hash_device_token

logger = logging.getLogger("redcode.seed")

def generate_tone_wav(filename: str, freq: float = 880.0, duration_sec: float = 1.0, sample_rate: int = 44100):
    """Generates a clean local WAV audio file for offline hospital alarms"""
    os.makedirs(settings.AUDIO_UPLOAD_DIR, exist_ok=True)
    full_path = os.path.join(settings.AUDIO_UPLOAD_DIR, filename)
    if os.path.exists(full_path):
        return full_path

    n_samples = int(sample_rate * duration_sec)
    with wave.open(full_path, "w") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            val = math.sin(2.0 * math.pi * freq * t) * 0.6 + math.sin(2.0 * math.pi * (freq * 1.5) * t) * 0.3
            sample = int(val * 32767.0)
            wav_file.writeframes(struct.pack("<h", sample))
    return full_path

async def seed_database():
    async with AsyncSessionLocal() as session:
        # Check if users already exist
        admin_check = await session.execute(select(User).where(User.username == "admin"))
        if admin_check.scalar_one_or_none():
            logger.info("Database already seeded. Skipping initial seed.")
            return

        is_production = (settings.ENVIRONMENT == "production") and not settings.DEMO_MODE
        if is_production:
            if not settings.INITIAL_ADMIN_PASSWORD.strip():
                raise RuntimeError('Fresh production installation requires INITIAL_ADMIN_PASSWORD')
            session.add(User(username='admin', password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD), display_name='Quản trị hệ thống', role=UserRole.ADMIN.value, enabled=True))
            await session.commit()
            return
        logger.info(f"Seeding hospital data (Mode: {'PRODUCTION' if is_production else 'DEMO/DEV'})...")

        # 1. Departments
        depts_data = [
            ("TT", "Phòng Điều Hành Trung Tâm"),
            ("CC", "Khoa Cấp Cứu"),
            ("HSCC", "Khoa Hồi Sức Tích Cực (ICU)"),
            ("GMHS", "Khoa Gây Mê Hồi Sức"),
            ("KNT", "Khoa Ngoại Tổng Quát"),
            ("KCT", "Khoa Chấn Thương Chỉnh Hình"),
            ("KS", "Khoa Sản"),
            ("KN", "Khoa Nhi"),
            ("KKB", "Khoa Khám Bệnh"),
        ]
        dept_map = {}
        for code, name in depts_data:
            dept = Department(code=code, name=name, enabled=True)
            session.add(dept)
            await session.flush()
            dept_map[code] = dept

        # 2. Receiver Groups
        rg_all = ReceiverGroup(code="ALL_HOSPITAL", name="Toàn Bệnh Viện", description="Tất cả các trạm nhận toàn viện", enabled=True)
        rg_emg = ReceiverGroup(code="EMERGENCY_TEAM", name="Đội Cấp Cứu Phản Ứng Nhanh", description="Các khoa Hồi sức, Cấp cứu, Gây mê", enabled=True)
        rg_int = ReceiverGroup(code="INTERNAL_MED", name="Khối Nội Viện", description="Các khoa lâm sàng nội viện", enabled=True)
        session.add_all([rg_all, rg_emg, rg_int])
        await session.flush()

        # 3. Audio Files
        generate_tone_wav("red_code_1.wav", freq=950.0, duration_sec=1.2)
        generate_tone_wav("red_code_2.wav", freq=800.0, duration_sec=1.5)
        generate_tone_wav("blue_code.wav", freq=650.0, duration_sec=1.0)
        generate_tone_wav("fire_alarm.wav", freq=1100.0, duration_sec=0.8)

        audios = [
            ("AUDIO_RC1", "Còi Red Code 1", "/assets/audio/red_code_1.wav", "audio/wav"),
            ("AUDIO_RC2", "Còi Red Code 2", "/assets/audio/red_code_2.wav", "audio/wav"),
            ("AUDIO_BLUE", "Còi Blue Code", "/assets/audio/blue_code.wav", "audio/wav"),
            ("AUDIO_FIRE", "Còi Báo Cháy", "/assets/audio/fire_alarm.wav", "audio/wav"),
        ]
        for acode, aname, apath, amime in audios:
            af = AudioFile(code=acode, name=aname, file_path=apath, mime_type=amime, enabled=True)
            session.add(af)

        # 4. Alarm Types
        alarm_types_data = [
            ("RED_CODE_1", "RED CODE 1 — Ngừng Tuần Hoàn Hô Hấp", "Cấp cứu ngừng hô hấp tuần hoàn khẩn cấp", 1, "#dc2626", rg_emg.id, ["/assets/audio/red_code_1.wav"], 5, 1000),
            ("RED_CODE_2", "RED CODE 2 — Cấp Cứu Thảm Họa / Chấn Thương Hàng Loạt", "Cấp cứu tai nạn hàng loạt hoặc thảm họa", 2, "#b91c1c", rg_all.id, ["/assets/audio/red_code_2.wav"], 4, 1200),
            ("BLUE_CODE", "BLUE CODE — Cấp Cứu Nội Viện", "Hỗ trợ cấp cứu người bệnh tại các khoa nội trú", 3, "#2563eb", rg_emg.id, ["/assets/audio/blue_code.wav"], 3, 1500),
            ("FIRE_ALARM", "FIRE ALARM — Báo Cháy Khẩn Cấp", "Báo động cháy và sơ tán toàn bệnh viện", 1, "#ea580c", rg_all.id, ["/assets/audio/fire_alarm.wav"], 6, 800),
        ]
        created_alarm_types = []
        for code, name, desc, prio, col, gid, seq, rep, interval in alarm_types_data:
            at = AlarmType(
                code=code,
                name=name,
                description=desc,
                priority=prio,
                display_color=col,
                receiver_group_id=gid,
                audio_sequence=seq,
                repeat_count=rep,
                repeat_interval_ms=interval,
                enabled=True
            )
            session.add(at)
            await session.flush()
            created_alarm_types.append(at)

        # 5. Department Alarm Permissions (relational permissions)
        # By default, Emergency/ICU/Admin can trigger RED_CODE_1, RED_CODE_2, BLUE_CODE, FIRE_ALARM; all depts can trigger FIRE_ALARM
        for at in created_alarm_types:
            for dept_code, dept_obj in dept_map.items():
                is_allowed = True
                if at.code in ["RED_CODE_1", "RED_CODE_2"]:
                    # Clinical / Emergency departments
                    is_allowed = dept_code in ["TT", "CC", "HSCC", "GMHS", "KNT", "KCT", "KS", "KN"]
                session.add(DepartmentAlarmPermission(
                    department_id=dept_obj.id,
                    alarm_type_id=at.id,
                    enabled=is_allowed
                ))

        # 6. Users & Stations based on Environment Mode
        if is_production:
            # In production, require INITIAL_ADMIN_PASSWORD from environment
            admin_pwd = settings.INITIAL_ADMIN_PASSWORD.strip()
            if admin_pwd:
                admin_user = User(
                    username="admin",
                    password_hash=hash_password(admin_pwd),
                    display_name="Quản Trị Viên Hệ Thống",
                    department_id=dept_map["TT"].id,
                    role=UserRole.ADMIN.value,
                    enabled=True
                )
                session.add(admin_user)
                logger.info("Production admin user created from INITIAL_ADMIN_PASSWORD.")
            else:
                logger.warning("INITIAL_ADMIN_PASSWORD not configured. System administrator must be provisioned manually!")
        else:
            # DEMO / DEVELOPMENT Mode: Seed demo accounts & stations with secure tokens
            logger.info("Seeding demo accounts and stations for DEV/DEMO environment...")
            users_data = [
                ("admin", "admin123456", "Quản Trị Viên Hệ Thống", dept_map["TT"].id, UserRole.ADMIN.value),
                ("operator_cc", "pass123456", "Điều Dưỡng Cấp Cứu", dept_map["CC"].id, UserRole.OPERATOR.value),
                ("operator_hscc", "pass123456", "Bác Sĩ Hồi Sức", dept_map["HSCC"].id, UserRole.OPERATOR.value),
                ("viewer", "pass123456", "Trực Ban Giám Sát", dept_map["TT"].id, UserRole.VIEWER.value),
            ]
            for uname, pwd, dname, d_id, role in users_data:
                user = User(
                    username=uname,
                    password_hash=hash_password(pwd),
                    display_name=dname,
                    department_id=d_id,
                    role=role,
                    enabled=True
                )
                session.add(user)

            # Stations with secure random tokens
            stations_data = [
                ("ST-CC-01", "Kiosk Cấp Cứu", dept_map["CC"].id, "Khu vực sảnh cấp cứu", [rg_all.id, rg_emg.id]),
                ("ST-HSCC-01", "Trạm Hồi Sức Tích Cực", dept_map["HSCC"].id, "Phòng trực bác sĩ ICU", [rg_all.id, rg_emg.id]),
                ("ST-GMHS-01", "Trạm Gây Mê Hồi Sức", dept_map["GMHS"].id, "Khu phẫu thuật tầng 3", [rg_all.id, rg_emg.id]),
                ("ST-SAN-01", "Trạm Khoa Sản", dept_map["KS"].id, "Phòng sinh tầng 2", [rg_all.id, rg_int.id]),
                ("ST-DIEUHANH", "Trạm Điều Hành Trung Tâm", dept_map["TT"].id, "Phòng chỉ huy trực ban", [rg_all.id, rg_emg.id, rg_int.id]),
            ]
            for s_code, s_name, d_id, loc, r_group_ids in stations_data:
                # Generate cryptographically secure token for demo station
                demo_token = f"demo_token_{secrets.token_urlsafe(24)}"
                st = Station(
                    station_code=s_code,
                    name=s_name,
                    department_id=d_id,
                    location=loc,
                    device_token_hash=hash_device_token(demo_token),
                    enabled=True,
                    status=StationStatus.OFFLINE.value
                )
                session.add(st)
                await session.flush()

                for gid in r_group_ids:
                    session.add(ReceiverGroupStation(receiver_group_id=gid, station_id=st.id))

        await session.commit()
        logger.info("Initial seeding completed successfully!")
