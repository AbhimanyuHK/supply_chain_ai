from typing import Sequence

from sqlalchemy import select

from app.database.repositories.base import BaseRepository
from app.models.entities import PlanningRun


class PlanningRunRepository(BaseRepository[PlanningRun]):
    model = PlanningRun

    async def create(self, **fields) -> PlanningRun:
        """Adds and flushes a new row - does NOT commit (matches every other
        repository in this codebase; the caller owns the transaction)."""
        run = PlanningRun(**fields)
        self.session.add(run)
        await self.session.flush()
        return run

    async def find_by_scope_key(self, scope_key: str, limit: int = 20) -> Sequence[PlanningRun]:
        result = await self.session.execute(
            select(PlanningRun)
            .where(PlanningRun.scope_key == scope_key)
            .order_by(PlanningRun.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_recent(self, limit: int = 50) -> Sequence[PlanningRun]:
        result = await self.session.execute(
            select(PlanningRun).order_by(PlanningRun.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def get_by_id(self, run_id: int) -> PlanningRun | None:
        return await self.session.get(PlanningRun, run_id)
