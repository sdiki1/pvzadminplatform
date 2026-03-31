"""Import static Excel-derived datasets into DB.

This script imports:
- Motivation records (WB/OZON/disputes) from static data
- Shifts from 2026-01-01
- SOS incidents from 2026-01-01
- Defect incidents from 2026-01-01

All operational datasets are pre-generated and stored in Python modules, so
there is no runtime XLSX parsing.

Usage (local):
    python3 -m scripts.import_excel_data

Usage (Docker):
    docker compose exec -w /app app python -m scripts.import_excel_data
"""
from __future__ import annotations

import argparse
import asyncio
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.utils.parsing import normalize_text
from scripts.import_excel_ops_static_data import DEFECT_ROWS_2026, SHIFT_ROWS_2026, SOS_ROWS_2026, START_DATE
from scripts.import_excel_static_data import DISPUTE_ROWS, OZON_MAIN_ROWS, WB_MAIN_ROWS

DEFAULT_LAT = 58.6352
DEFAULT_LON = 59.7852
NICKNAMES = {
    "дима": "дмитрий",
    "даня": "даниил",
    "ксюша": "ксения",
    "даша": "дария",
    "дарья": "дария",
    "вика": "виктория",
    "варя": "варвара",
    "катя": "екатерина",
    "настя": "анастасия",
}


def _norm_key(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"[^\w\sа-яА-ЯёЁ]", " ", text, flags=re.UNICODE)
    text = normalize_text(text.replace("улица", "ул").replace("ул.", "ул"))
    return text


def _extract_address_key(value: str) -> str:
    text = _norm_key(value)
    parts = [p for p in text.split() if p not in {"пвз", "№1", "№2", "№3", "№4", "ул", "улица", "г", "город"}]
    return " ".join(parts)


def _to_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _period_bounds(dates: list[date]) -> tuple[date, date] | None:
    if not dates:
        return None
    return min(dates), max(dates)


def _build_required_points() -> list[dict]:
    return [
        {
            "name": "WB Гоголя 18",
            "address": "Свердловская область, Лесной, Гоголя 18",
            "brand": "wb",
            "short_name": "Гоголя 18",
            "work_start": datetime.strptime("09:00", "%H:%M").time(),
            "work_end": datetime.strptime("21:00", "%H:%M").time(),
        },
        {
            "name": "WB Ленина 61",
            "address": "Свердловская область, Лесной, Ленина 61",
            "brand": "wb",
            "short_name": "Ленина 61",
            "work_start": datetime.strptime("09:00", "%H:%M").time(),
            "work_end": datetime.strptime("21:00", "%H:%M").time(),
        },
        {
            "name": "WB Ленина 114",
            "address": "Свердловская область, Лесной, Ленина 114",
            "brand": "wb",
            "short_name": "Ленина 114",
            "work_start": datetime.strptime("09:00", "%H:%M").time(),
            "work_end": datetime.strptime("21:00", "%H:%M").time(),
        },
        {
            "name": "WB Мальского 5А",
            "address": "Свердловская область, Лесной, Мальского 5А",
            "brand": "wb",
            "short_name": "Мальского 5А",
            "work_start": datetime.strptime("10:00", "%H:%M").time(),
            "work_end": datetime.strptime("21:00", "%H:%M").time(),
        },
        {
            "name": "OZON Ленина 114",
            "address": "Свердловская область, Лесной, Ленина 114",
            "brand": "ozon",
            "short_name": "Ленина 114",
            "work_start": datetime.strptime("09:00", "%H:%M").time(),
            "work_end": datetime.strptime("21:00", "%H:%M").time(),
        },
        {
            "name": "WB Белинского 46А",
            "address": "Свердловская область, Лесной, Белинского 46А",
            "brand": "wb",
            "short_name": "Белинского 46А",
            "work_start": datetime.strptime("09:00", "%H:%M").time(),
            "work_end": datetime.strptime("21:00", "%H:%M").time(),
        },
    ]


async def _ensure_points(point_repo, brand_enum_cls) -> tuple[dict[str, int], dict[str, object]]:
    point_keys: dict[str, int] = {}
    points_by_name: dict[str, object] = {}
    for row in _build_required_points():
        point = await point_repo.create_or_update(
            name=row["name"],
            address=row["address"],
            brand=brand_enum_cls(row["brand"]),
            latitude=DEFAULT_LAT,
            longitude=DEFAULT_LON,
            radius_m=150,
            work_start=row["work_start"],
            work_end=row["work_end"],
            is_active=True,
            short_name=row["short_name"],
            address_normalized=row["address"],
            code=None,
            comment=None,
        )
        point_keys[f"{row['brand']}|{_extract_address_key(row['short_name'])}"] = point.id
        points_by_name[row["name"]] = point
    return point_keys, points_by_name


def _person_tokens(name: str | None) -> list[str]:
    if not name:
        return []
    t = normalize_text(name).replace("ё", "е")
    t = re.sub(r"[^а-яa-z\s\-]", " ", t, flags=re.UNICODE)
    tokens = [x for x in t.split() if x]
    out: list[str] = []
    for tok in tokens:
        out.append(NICKNAMES.get(tok, tok))
    return out


def _person_keys(name: str | None) -> set[str]:
    tokens = _person_tokens(name)
    if not tokens:
        return set()

    keys = {" ".join(tokens), tokens[0], tokens[-1]}
    if len(tokens) >= 2:
        keys.add(f"{tokens[0]} {tokens[1]}")
        keys.add(f"{tokens[1]} {tokens[0]}")
        keys.add(f"{tokens[0]} {tokens[-1]}")
        keys.add(f"{tokens[-1]} {tokens[0]}")
        initials = f"{tokens[0][0]}{tokens[1][0]}".upper()
        keys.add(initials)
    return keys


async def _build_user_name_map(user_repo) -> dict[str, int]:
    users = await user_repo.list_all()
    out: dict[str, int] = {}
    for user in users:
        for key in _person_keys(user.full_name):
            out[key] = user.id
    return out


def _resolve_user_id(user_map: dict[str, int], name: str | None) -> int | None:
    if not name:
        return None
    for key in _person_keys(name):
        if key in user_map:
            return user_map[key]
    return None


def _display_name(raw: str) -> str:
    return " ".join(str(raw).strip().split())


async def _ensure_employee_users(session, user_map: dict[str, int], names: set[str]) -> int:
    from sqlalchemy import func, select

    from app.db.models import RoleEnum, User

    created = 0
    max_tg = (await session.execute(select(func.max(User.telegram_id)))).scalar() or 8_000_000_000
    next_tg = int(max_tg) + 1

    for raw in sorted(names):
        if not raw:
            continue
        if _resolve_user_id(user_map, raw):
            continue

        full_name = _display_name(raw)
        tokens = _person_tokens(full_name)
        last_name = tokens[0].capitalize() if tokens else None

        user = User(
            telegram_id=next_tg,
            full_name=full_name,
            last_name=last_name,
            role=RoleEnum.EMPLOYEE,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        for key in _person_keys(full_name) | _person_keys(raw):
            user_map[key] = user.id

        created += 1
        next_tg += 1

    if created:
        await session.commit()
    return created


def _resolve_point_id(point_keys: dict[str, int], brand: str, raw_name: str | None) -> int | None:
    if not raw_name:
        return None
    key = _extract_address_key(raw_name)
    exact = point_keys.get(f"{brand}|{key}")
    if exact:
        return exact

    needle = f"{brand}|{key}"
    for k, point_id in point_keys.items():
        if needle in k or k in needle:
            return point_id
    return None


def _extract_amount_from_text(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    text = str(raw).lower()
    matches = re.findall(r"(-?\d+(?:[\.,]\d+)?)\s*(?:р|руб)", text)
    if matches:
        try:
            return Decimal(matches[-1].replace(",", "."))
        except Exception:
            return None
    return None


def _sos_status_and_resolved_at(incident_day: date, resolution_comment: str | None) -> tuple[str, datetime | None]:
    if not resolution_comment:
        return "open", None
    r = normalize_text(resolution_comment)
    if "не реш" in r:
        return "unresolved", None
    if "контрол" in r:
        return "on_hold", None
    return "resolved", datetime.combine(incident_day, time(21, 0))


def _shift_times_from_mark(raw_mark: str | None, default_start: time, default_end: time) -> tuple[time, time]:
    if not raw_mark:
        return default_start, default_end

    txt = str(raw_mark)
    times = re.findall(r"(\d{1,2})[:\.](\d{2})", txt)
    if len(times) >= 2:
        try:
            start = time(int(times[0][0]), int(times[0][1]))
            end = time(int(times[1][0]), int(times[1][1]))
            return start, end
        except Exception:
            return default_start, default_end
    return default_start, default_end


async def import_static_rows(dry_run: bool) -> None:
    ops_start = _to_date(START_DATE)

    print(f"WB static rows: {len(WB_MAIN_ROWS)}")
    print(f"OZON static rows: {len(OZON_MAIN_ROWS)}")
    print(f"Disputes static rows: {len(DISPUTE_ROWS)}")
    print(f"Shifts >= {ops_start}: {len(SHIFT_ROWS_2026)}")
    print(f"SOS >= {ops_start}: {len(SOS_ROWS_2026)}")
    print(f"Defects >= {ops_start}: {len(DEFECT_ROWS_2026)}")

    if dry_run:
        print("Dry-run mode: nothing written to DB.")
        return

    from sqlalchemy import delete

    from app.db.models import (
        ApprovalStatus,
        BrandEnum,
        DefectIncident,
        GeoStatus,
        MotivationRecord,
        MotivationSource,
        Shift,
        ShiftState,
        SOSIncident,
    )
    from app.db.repositories import MotivationRepo, PointRepo, UserRepo
    from app.db.session import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as session:
        point_repo = PointRepo(session)
        user_repo = UserRepo(session)
        motivation_repo = MotivationRepo(session)

        point_keys, points_by_name = await _ensure_points(point_repo, BrandEnum)
        user_map = await _build_user_name_map(user_repo)

        # Create missing users needed for shifts/incidents.
        required_names = {r.get("employee_name") for r in SHIFT_ROWS_2026 if r.get("employee_name")}
        required_names.update({r.get("recorded_by_name") for r in SOS_ROWS_2026 if r.get("recorded_by_name")})
        required_names.update({r.get("recorded_by_name") for r in DEFECT_ROWS_2026 if r.get("recorded_by_name")})
        created_users = await _ensure_employee_users(session, user_map, {n for n in required_names if n})

        # ------------------------------------------------------------------
        # Motivation records (existing logic)
        # ------------------------------------------------------------------
        wb_records: list[MotivationRecord] = []
        for row in WB_MAIN_ROWS:
            wb_records.append(
                MotivationRecord(
                    source=MotivationSource.MAIN,
                    record_date=_to_date(row["record_date"]),
                    point_id=_resolve_point_id(point_keys, "wb", row.get("point_key")),
                    user_id=_resolve_user_id(user_map, row.get("manager_name")),
                    manager_name=row.get("manager_name"),
                    acceptance_amount_rub=Decimal(row.get("acceptance_amount_rub", "0")),
                    issued_items_count=int(row.get("issued_items_count", 0)),
                    tickets_count=int(row.get("tickets_count", 0)),
                    disputed_amount_rub=Decimal("0"),
                    status=None,
                    raw_payload=None,
                )
            )

        ozon_records: list[MotivationRecord] = []
        for row in OZON_MAIN_ROWS:
            ozon_records.append(
                MotivationRecord(
                    source=MotivationSource.OZON,
                    record_date=_to_date(row["record_date"]),
                    point_id=_resolve_point_id(point_keys, "ozon", row.get("point_key")),
                    user_id=_resolve_user_id(user_map, row.get("manager_name")),
                    manager_name=row.get("manager_name"),
                    acceptance_amount_rub=Decimal(row.get("acceptance_amount_rub", "0")),
                    issued_items_count=int(row.get("issued_items_count", 0)),
                    tickets_count=int(row.get("tickets_count", 0)),
                    disputed_amount_rub=Decimal("0"),
                    status=None,
                    raw_payload=None,
                )
            )

        dispute_records: list[MotivationRecord] = []
        for row in DISPUTE_ROWS:
            dispute_records.append(
                MotivationRecord(
                    source=MotivationSource.DISPUTE,
                    record_date=_to_date(row["record_date"]),
                    point_id=_resolve_point_id(point_keys, "wb", row.get("point_key")),
                    user_id=_resolve_user_id(user_map, row.get("manager_name")),
                    manager_name=row.get("manager_name"),
                    acceptance_amount_rub=Decimal("0"),
                    issued_items_count=0,
                    tickets_count=0,
                    disputed_amount_rub=Decimal(row.get("amount_rub", "0")),
                    status=row.get("status"),
                    raw_payload=None,
                )
            )

        wb_bounds = _period_bounds([_to_date(r["record_date"]) for r in WB_MAIN_ROWS])
        ozon_bounds = _period_bounds([_to_date(r["record_date"]) for r in OZON_MAIN_ROWS])
        dispute_bounds = _period_bounds([_to_date(r["record_date"]) for r in DISPUTE_ROWS])

        if wb_bounds:
            await motivation_repo.clear_source_in_period(MotivationSource.MAIN, wb_bounds[0], wb_bounds[1])
        if ozon_bounds:
            await motivation_repo.clear_source_in_period(MotivationSource.OZON, ozon_bounds[0], ozon_bounds[1])
        if dispute_bounds:
            await motivation_repo.clear_source_in_period(MotivationSource.DISPUTE, dispute_bounds[0], dispute_bounds[1])

        if wb_records:
            await motivation_repo.add_many(wb_records)
        if ozon_records:
            await motivation_repo.add_many(ozon_records)
        if dispute_records:
            await motivation_repo.add_many(dispute_records)

        # ------------------------------------------------------------------
        # Operational imports from 2026-01-01
        # ------------------------------------------------------------------
        await session.execute(
            delete(Shift).where(Shift.shift_date >= ops_start, Shift.notes.is_not(None), Shift.notes.ilike("[excel]%"))
        )
        await session.execute(
            delete(SOSIncident).where(SOSIncident.incident_date >= ops_start, SOSIncident.source == "excel")
        )
        await session.execute(
            delete(DefectIncident).where(DefectIncident.incident_date >= ops_start, DefectIncident.source == "excel")
        )
        await session.commit()

        shifts: list[Shift] = []
        skipped_shifts = 0
        for row in SHIFT_ROWS_2026:
            shift_day = _to_date(row["shift_date"])
            point = points_by_name.get(row.get("point_name"))
            user_id = _resolve_user_id(user_map, row.get("employee_name"))
            if not point or not user_id:
                skipped_shifts += 1
                continue

            open_t, close_t = _shift_times_from_mark(row.get("raw_mark"), point.work_start, point.work_end)
            opened_at = datetime.combine(shift_day, open_t)
            closed_at = datetime.combine(shift_day, close_t)
            if closed_at <= opened_at:
                closed_at += timedelta(hours=8)

            duration = max(0, int((closed_at - opened_at).total_seconds() // 60))
            shifts.append(
                Shift(
                    user_id=user_id,
                    point_id=point.id,
                    shift_date=shift_day,
                    state=ShiftState.CLOSED,
                    opened_at=opened_at,
                    open_lat=point.latitude,
                    open_lon=point.longitude,
                    open_distance_m=0,
                    open_geo_status=GeoStatus.OK,
                    open_approval_status=ApprovalStatus.APPROVED,
                    closed_at=closed_at,
                    close_lat=point.latitude,
                    close_lon=point.longitude,
                    close_distance_m=0,
                    close_geo_status=GeoStatus.OK,
                    close_approval_status=ApprovalStatus.APPROVED,
                    duration_minutes=duration,
                    notes=f"[excel] {row.get('raw_mark') or ''}".strip(),
                )
            )

        if shifts:
            session.add_all(shifts)
            await session.commit()

        sos_rows: list[SOSIncident] = []
        skipped_sos = 0
        for row in SOS_ROWS_2026:
            incident_day = _to_date(row["incident_date"])
            point = points_by_name.get(row.get("point_name"))
            if not point:
                skipped_sos += 1
                continue

            status, resolved_at = _sos_status_and_resolved_at(incident_day, row.get("resolution_comment"))
            total_amount = _extract_amount_from_text(row.get("products_raw"))
            recorded_by_id = _resolve_user_id(user_map, row.get("recorded_by_name"))

            sos_rows.append(
                SOSIncident(
                    point_id=point.id,
                    incident_date=incident_day,
                    incident_time=None,
                    cell_code=row.get("cell_code"),
                    client_name=row.get("client_name"),
                    client_phone=row.get("client_phone"),
                    description=row.get("description") or "",
                    products_raw=row.get("products_raw"),
                    total_amount=total_amount,
                    recorded_by_employee_id=recorded_by_id,
                    status=status,
                    resolution_comment=row.get("resolution_comment"),
                    resolved_at=resolved_at,
                    source="excel",
                )
            )

        if sos_rows:
            session.add_all(sos_rows)
            await session.commit()

        defects: list[DefectIncident] = []
        skipped_defects = 0
        for row in DEFECT_ROWS_2026:
            incident_day = _to_date(row["incident_date"])
            point = points_by_name.get(row.get("point_name"))
            if not point:
                skipped_defects += 1
                continue

            recorded_by_id = _resolve_user_id(user_map, row.get("recorded_by_name"))
            amount = Decimal(row["amount"]) if row.get("amount") else None

            defects.append(
                DefectIncident(
                    point_id=point.id,
                    incident_date=incident_day,
                    incident_time=None,
                    detected_by_role=row.get("detected_by_role") or "unknown",
                    detected_stage=row.get("detected_stage") or "other",
                    detected_source_raw=row.get("detected_source_raw"),
                    incident_type=row.get("incident_type") or "defect",
                    barcode=row.get("barcode"),
                    product_title=None,
                    problem_description=row.get("problem_description"),
                    full_description_raw=None,
                    action_type="excel_import",
                    action_comment=row.get("action_comment"),
                    amount=amount,
                    recorded_by_employee_id=recorded_by_id,
                    status="closed",
                    resolution_comment=None,
                    source="excel",
                )
            )

        if defects:
            session.add_all(defects)
            await session.commit()

        main_2026 = sum(1 for r in WB_MAIN_ROWS if _to_date(r["record_date"]) >= ops_start)

        print("Import complete.")
        print(f"Inserted MAIN (WB): {len(wb_records)}")
        print(f"Inserted OZON: {len(ozon_records)}")
        print(f"Inserted DISPUTE: {len(dispute_records)}")
        print(f"Inserted SHIFTS >= {ops_start}: {len(shifts)} (skipped: {skipped_shifts})")
        print(f"Inserted SOS >= {ops_start}: {len(sos_rows)} (skipped: {skipped_sos})")
        print(f"Inserted DEFECTS >= {ops_start}: {len(defects)} (skipped: {skipped_defects})")
        print(f"WB acceptance rows >= {ops_start}: {main_2026}")
        print(f"Created missing employees: {created_users}")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import static WB/OZON/disputes + ops datasets")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only")
    return parser


async def _amain() -> None:
    args = _build_arg_parser().parse_args()
    await import_static_rows(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(_amain())
