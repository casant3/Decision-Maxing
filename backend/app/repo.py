"""Case repository: versioned snapshots + append-only event log.

Every save creates a new CaseVersionRow — state changes are auditable and
any prior version can be inspected or restored."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CaseRow, CaseVersionRow, EventRow, OutcomeRow
from app.schemas.aggregate import CaseFile, OutcomeReview


class CaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, case: CaseFile, reason: str) -> CaseFile:
        row = await self.session.get(CaseRow, case.case_id)
        if row is None:
            row = CaseRow(id=case.case_id)
            self.session.add(row)
        else:
            case.version = row.current_version + 1
        case.touch()
        row.title = case.title
        row.status = case.status.value
        row.current_version = case.version
        snapshot = json.loads(case.model_dump_json())
        self.session.add(
            CaseVersionRow(case_id=case.case_id, version=case.version, reason=reason, snapshot=snapshot)
        )
        await self.session.commit()
        return case

    async def load(self, case_id: str, version: int | None = None) -> CaseFile | None:
        q = select(CaseVersionRow).where(CaseVersionRow.case_id == case_id)
        q = q.where(CaseVersionRow.version == version) if version else q.order_by(desc(CaseVersionRow.version)).limit(1)
        result = await self.session.execute(q)
        row = result.scalar_one_or_none()
        return CaseFile.model_validate(row.snapshot) if row else None

    async def list_cases(self, limit: int = 50) -> list[CaseRow]:
        result = await self.session.execute(
            select(CaseRow).order_by(desc(CaseRow.updated_at)).limit(limit)
        )
        return list(result.scalars())

    async def log_event(self, case_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.session.add(EventRow(case_id=case_id, event_type=event_type, payload=payload or {}))
        await self.session.commit()

    async def events(self, case_id: str) -> list[EventRow]:
        result = await self.session.execute(
            select(EventRow).where(EventRow.case_id == case_id).order_by(EventRow.id)
        )
        return list(result.scalars())

    async def save_outcome(self, case_id: str, review: OutcomeReview) -> None:
        self.session.add(OutcomeRow(case_id=case_id, review=json.loads(review.model_dump_json())))
        await self.session.commit()
