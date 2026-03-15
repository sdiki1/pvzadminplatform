from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import MotivationRecord, MotivationSource
from app.db.repositories import MotivationRepo, PointRepo, UserRepo
from app.services.google_sheets import GoogleSheetsService
from app.services.wb_workbook import WBWorkbookService
from app.utils.parsing import normalize_text


@dataclass
class SyncSummary:
    main_imported: int
    disputes_imported: int


class GoogleSyncService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.sheets = GoogleSheetsService(settings)
        self.workbook = WBWorkbookService(settings)
        self.motivation_repo = MotivationRepo(session)
        self.user_repo = UserRepo(session)
        self.point_repo = PointRepo(session)

    async def sync_period(self, period_start: date, period_end: date) -> SyncSummary:
        if not self.sheets.enabled:
            return SyncSummary(main_imported=0, disputes_imported=0)

        users = await self.user_repo.list_all()
        points = await self.point_repo.list_all()

        user_by_last_name = {}
        for u in users:
            if u.last_name:
                user_by_last_name[normalize_text(u.last_name)] = u.id

        point_keys = {}
        for p in points:
            point_keys[self._normalize_point_key(p.name)] = p.id
            point_keys[self._normalize_point_key(p.address)] = p.id
            point_keys[self._normalize_point_key(f"{p.name} {p.address}")] = p.id

        main_source_rows = self.sheets.fetch_main_stats()
        if not main_source_rows and self.workbook.enabled:
            main_source_rows = self.workbook.fetch_main_stats()

        main_rows = [r for r in main_source_rows if period_start <= r.record_date <= period_end]
        dispute_rows = [r for r in self.sheets.fetch_disputes() if period_start <= r.record_date <= period_end]

        await self.motivation_repo.clear_source_in_period(MotivationSource.MAIN, period_start, period_end)
        await self.motivation_repo.clear_source_in_period(MotivationSource.DISPUTE, period_start, period_end)

        main_records: list[MotivationRecord] = []
        for row in main_rows:
            user_id = self._match_user_id(row.manager_name, user_by_last_name)
            point_id = self._match_point_id(row.point_name, point_keys)
            main_records.append(
                MotivationRecord(
                    source=MotivationSource.MAIN,
                    record_date=row.record_date,
                    point_id=point_id,
                    user_id=user_id,
                    manager_name=row.manager_name,
                    acceptance_amount_rub=row.acceptance_amount_rub,
                    issued_items_count=row.issued_items_count,
                    tickets_count=row.tickets_count,
                    disputed_amount_rub=0,
                    status=None,
                    raw_payload=row.raw_payload,
                )
            )

        dispute_records: list[MotivationRecord] = []
        for row in dispute_rows:
            user_id = self._match_user_id(row.manager_name, user_by_last_name)
            dispute_records.append(
                MotivationRecord(
                    source=MotivationSource.DISPUTE,
                    record_date=row.record_date,
                    point_id=None,
                    user_id=user_id,
                    manager_name=row.manager_name,
                    acceptance_amount_rub=0,
                    issued_items_count=0,
                    tickets_count=0,
                    disputed_amount_rub=row.amount_rub,
                    status=row.status,
                    raw_payload=row.raw_payload,
                )
            )

        if main_records:
            await self.motivation_repo.add_many(main_records)
        if dispute_records:
            await self.motivation_repo.add_many(dispute_records)

        return SyncSummary(main_imported=len(main_records), disputes_imported=len(dispute_records))

    @staticmethod
    def _match_user_id(name: str | None, user_by_last_name: dict[str, int]) -> int | None:
        if not name:
            return None
        n = normalize_text(name)
        if not n:
            return None
        key = n.split()[0]
        return user_by_last_name.get(key)

    @staticmethod
    def _match_point_id(point_name: str | None, point_keys: dict[str, int]) -> int | None:
        if not point_name:
            return None
        n = GoogleSyncService._normalize_point_key(point_name)
        if n in point_keys:
            return point_keys[n]

        for key, point_id in point_keys.items():
            if n in key or key in n:
                return point_id
        return None

    @staticmethod
    def _normalize_point_key(value: str) -> str:
        n = normalize_text(value)
        n = re.sub(r"[^\w\sа-яА-ЯёЁ]", " ", n, flags=re.UNICODE)
        n = normalize_text(n)
        parts = [p for p in n.split() if p not in {"пвз", "wb", "wildberries", "ozon", "озон", "№", "no", "пункт"}]
        return " ".join(parts)
