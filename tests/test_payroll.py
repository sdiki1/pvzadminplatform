from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import (
    Appeal,
    AdjustmentType,
    ApprovalStatus,
    Base,
    BrandEnum,
    GeoStatus,
    MotivationRecord,
    MotivationSource,
    Point,
    PlannedShift,
    Shift,
    ShiftState,
    User,
)
from app.db.repositories import ManualAdjustmentRepo
from app.services.payroll import PayrollService
from app.utils.dates import payroll_period_for_payout


@pytest.mark.asyncio
async def test_payroll_split_and_adjustments() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = Settings(
        BOT_TOKEN="123:token",
        ADMIN_IDS="",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )

    async with Session() as session:
        user1 = User(
            telegram_id=1001,
            full_name="Иванов Иван",
            last_name="Иванов",
            shift_rate_rub=Decimal("2500"),
        )
        user2 = User(
            telegram_id=1002,
            full_name="Петров Петр",
            last_name="Петров",
            shift_rate_rub=Decimal("2500"),
        )
        session.add_all([user1, user2])
        await session.flush()

        point = Point(
            name="WB Ленина 61",
            address="Лесной, Ленина 61",
            brand=BrandEnum.WB,
            latitude=58.6352,
            longitude=59.7852,
            radius_m=150,
            work_start=time(9, 0),
            work_end=time(21, 0),
            is_active=True,
        )
        session.add(point)
        await session.flush()

        shift1 = Shift(
            user_id=user1.id,
            point_id=point.id,
            shift_date=date(2026, 3, 10),
            state=ShiftState.CLOSED,
            opened_at=datetime(2026, 3, 10, 9, 0),
            open_lat=58.6352,
            open_lon=59.7852,
            open_distance_m=10,
            open_geo_status=GeoStatus.OK,
            open_approval_status=ApprovalStatus.APPROVED,
            closed_at=datetime(2026, 3, 10, 15, 0),
            close_lat=58.6352,
            close_lon=59.7852,
            close_distance_m=12,
            close_geo_status=GeoStatus.OK,
            close_approval_status=ApprovalStatus.APPROVED,
            duration_minutes=360,
        )
        shift2 = Shift(
            user_id=user2.id,
            point_id=point.id,
            shift_date=date(2026, 3, 10),
            state=ShiftState.CLOSED,
            opened_at=datetime(2026, 3, 10, 15, 0),
            open_lat=58.6352,
            open_lon=59.7852,
            open_distance_m=9,
            open_geo_status=GeoStatus.OK,
            open_approval_status=ApprovalStatus.APPROVED,
            closed_at=datetime(2026, 3, 10, 21, 0),
            close_lat=58.6352,
            close_lon=59.7852,
            close_distance_m=11,
            close_geo_status=GeoStatus.OK,
            close_approval_status=ApprovalStatus.APPROVED,
            duration_minutes=360,
        )
        session.add_all([shift1, shift2])

        session.add(
            MotivationRecord(
                source=MotivationSource.MAIN,
                record_date=date(2026, 3, 10),
                point_id=point.id,
                user_id=None,
                manager_name=None,
                acceptance_amount_rub=Decimal("1000"),
                issued_items_count=199,
                tickets_count=0,
                disputed_amount_rub=Decimal("0"),
            )
        )
        session.add(
            MotivationRecord(
                source=MotivationSource.DISPUTE,
                record_date=date(2026, 3, 10),
                point_id=None,
                user_id=user1.id,
                manager_name="Иванов",
                acceptance_amount_rub=Decimal("0"),
                issued_items_count=0,
                tickets_count=0,
                disputed_amount_rub=Decimal("300"),
                status="не оспорено",
            )
        )

        adj_repo = ManualAdjustmentRepo(session)
        await adj_repo.add(
            user_id=user2.id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 15),
            amount_rub=Decimal("200"),
            adjustment_type=AdjustmentType.BONUS,
            comment="Тест",
            created_by=None,
        )

        await session.commit()

        payroll_service = PayrollService(session, settings)
        _, rows = await payroll_service.run_payroll(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 15),
            payout_day=25,
            generated_by=None,
        )

        row_by_tg = {r.user.telegram_id: r for r in rows}

        assert row_by_tg[1001].base_amount_rub == Decimal("2500.00")
        assert row_by_tg[1001].motivation_amount_rub == Decimal("500.00")
        assert row_by_tg[1001].issued_bonus_rub == Decimal("0.00")
        assert row_by_tg[1001].dispute_deduction_rub == Decimal("300.00")
        assert row_by_tg[1001].total_amount_rub == Decimal("2700.00")

        assert row_by_tg[1002].base_amount_rub == Decimal("2500.00")
        assert row_by_tg[1002].motivation_amount_rub == Decimal("500.00")
        assert row_by_tg[1002].adjustments_rub == Decimal("200.00")
        assert row_by_tg[1002].total_amount_rub == Decimal("3200.00")


@pytest.mark.asyncio
async def test_issued_bonus_full_hundred_threshold() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = Settings(
        BOT_TOKEN="123:token",
        ADMIN_IDS="",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )

    async with Session() as session:
        user = User(
            telegram_id=2001,
            full_name="Сидоров Сидор",
            last_name="Сидоров",
            shift_rate_rub=Decimal("2500"),
        )
        session.add(user)
        await session.flush()

        point = Point(
            name="WB Гоголя 18",
            address="Лесной, Гоголя 18",
            brand=BrandEnum.WB,
            latitude=58.6352,
            longitude=59.7852,
            radius_m=150,
            work_start=time(9, 0),
            work_end=time(21, 0),
            is_active=True,
        )
        session.add(point)
        await session.flush()

        shift = Shift(
            user_id=user.id,
            point_id=point.id,
            shift_date=date(2026, 3, 11),
            state=ShiftState.CLOSED,
            opened_at=datetime(2026, 3, 11, 9, 0),
            open_lat=58.6352,
            open_lon=59.7852,
            open_distance_m=10,
            open_geo_status=GeoStatus.OK,
            open_approval_status=ApprovalStatus.APPROVED,
            closed_at=datetime(2026, 3, 11, 21, 0),
            close_lat=58.6352,
            close_lon=59.7852,
            close_distance_m=10,
            close_geo_status=GeoStatus.OK,
            close_approval_status=ApprovalStatus.APPROVED,
            duration_minutes=720,
        )
        session.add(shift)

        session.add(
            MotivationRecord(
                source=MotivationSource.MAIN,
                record_date=date(2026, 3, 11),
                point_id=point.id,
                user_id=user.id,
                manager_name="Сидоров",
                acceptance_amount_rub=Decimal("0"),
                issued_items_count=199,
                tickets_count=0,
                disputed_amount_rub=Decimal("0"),
            )
        )
        await session.commit()

        payroll_service = PayrollService(session, settings)
        _, rows = await payroll_service.run_payroll(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 15),
            payout_day=25,
            generated_by=None,
        )

        assert len(rows) == 1
        assert rows[0].issued_bonus_rub == Decimal("100.00")


@pytest.mark.asyncio
async def test_manager_bonus_type3_uses_all_tickets_from_appeals_table() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = Settings(
        BOT_TOKEN="123:token",
        ADMIN_IDS="",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )

    async with Session() as session:
        manager = User(
            telegram_id=3001,
            full_name="Иванов Иван",
            last_name="Иванов",
            manager_bonus_type=3,
            shift_rate_rub=Decimal("2500"),
        )
        session.add(manager)
        await session.flush()

        point = Point(
            name="WB Ленина 114",
            address="Лесной, Ленина 114",
            brand=BrandEnum.WB,
            latitude=58.6352,
            longitude=59.7852,
            radius_m=150,
            work_start=time(9, 0),
            work_end=time(21, 0),
            is_active=True,
        )
        session.add(point)
        await session.flush()

        session.add_all(
            [
                Appeal(
                    case_date=date(2026, 3, 5),
                    point_id=point.id,
                    appeal_type="defect",
                    barcode="111",
                    ticket_number="T-100",
                    amount=Decimal("100"),
                    status="appealed",
                    assigned_manager_employee_id=manager.id,
                ),
                Appeal(
                    case_date=date(2026, 3, 7),
                    point_id=point.id,
                    appeal_type="substitution",
                    barcode="222",
                    ticket_number="T-101",
                    amount=Decimal("200"),
                    status="оспорено",
                    assigned_manager_raw="Иванов",
                ),
                Appeal(
                    case_date=date(2026, 3, 9),
                    point_id=point.id,
                    appeal_type="defect",
                    barcode="333",
                    ticket_number="T-102",
                    amount=Decimal("300"),
                    status="not_appealed",
                    assigned_manager_employee_id=manager.id,
                ),
            ]
        )
        await session.commit()

        payroll_service = PayrollService(session, settings)
        _, rows = await payroll_service.run_payroll(
            period_start=date(2026, 3, 16),
            period_end=date(2026, 3, 31),
            payout_day=10,
            generated_by=None,
        )

        assert len(rows) == 1
        assert rows[0].manager_bonus_rub == Decimal("600.00")


@pytest.mark.asyncio
async def test_reserve_and_substitution_bonuses_are_applied() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = Settings(
        BOT_TOKEN="123:token",
        ADMIN_IDS="",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        RESERVE_DUTY_BONUS_RUB=400,
        SUBSTITUTION_BONUS_RUB=500,
    )

    async with Session() as session:
        user = User(
            telegram_id=4001,
            full_name="Смирнова Анна",
            last_name="Смирнова",
            shift_rate_rub=Decimal("2500"),
        )
        session.add(user)
        await session.flush()

        point = Point(
            name="WB Мальского 5А",
            address="Лесной, Мальского 5А",
            brand=BrandEnum.WB,
            latitude=58.6352,
            longitude=59.7852,
            radius_m=150,
            work_start=time(10, 0),
            work_end=time(21, 0),
            is_active=True,
        )
        session.add(point)
        await session.flush()

        session.add(
            Shift(
                user_id=user.id,
                point_id=point.id,
                shift_date=date(2026, 3, 10),
                state=ShiftState.CLOSED,
                opened_at=datetime(2026, 3, 10, 10, 0),
                open_lat=58.6352,
                open_lon=59.7852,
                open_distance_m=10,
                open_geo_status=GeoStatus.OK,
                open_approval_status=ApprovalStatus.APPROVED,
                closed_at=datetime(2026, 3, 10, 21, 0),
                close_lat=58.6352,
                close_lon=59.7852,
                close_distance_m=11,
                close_geo_status=GeoStatus.OK,
                close_approval_status=ApprovalStatus.APPROVED,
                duration_minutes=660,
            )
        )

        session.add_all(
            [
                PlannedShift(
                    user_id=user.id,
                    point_id=point.id,
                    shift_date=date(2026, 3, 10),
                    is_substitution=True,
                    is_reserve=False,
                ),
                PlannedShift(
                    user_id=user.id,
                    point_id=point.id,
                    shift_date=date(2026, 3, 11),
                    is_substitution=False,
                    is_reserve=True,
                ),
            ]
        )
        await session.commit()

        payroll_service = PayrollService(session, settings)
        _, rows = await payroll_service.run_payroll(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 15),
            payout_day=25,
            generated_by=None,
        )

        assert len(rows) == 1
        assert rows[0].base_amount_rub == Decimal("2500.00")
        assert rows[0].reserve_bonus_rub == Decimal("400.00")
        assert rows[0].substitution_bonus_rub == Decimal("500.00")
        assert rows[0].total_amount_rub == Decimal("3400.00")


def test_payroll_periods() -> None:
    p10 = payroll_period_for_payout(10, date(2026, 3, 10))
    assert p10 == (date(2026, 2, 16), date(2026, 2, 28))

    p25 = payroll_period_for_payout(25, date(2026, 3, 25))
    assert p25 == (date(2026, 3, 1), date(2026, 3, 15))
