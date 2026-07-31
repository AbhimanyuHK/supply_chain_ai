from collections.abc import Sequence

from sqlalchemy import select

from app.database.repositories.base import BaseRepository
from app.models.entities import PlanningRun, PlanningRunStatus


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

    async def find_success_by_scope_data_and_engine(
        self, scope_key: str, data_fingerprint: str, llm_provider: str, llm_model: str
    ) -> PlanningRun | None:
        """The idempotency cache lookup: an existing successful run for the exact
        same scope, the exact same underlying data, and the exact same engine.

        Filters `status == SUCCESS` explicitly (unlike `find_by_scope_key`, which
        is for history browsing and shows failures too) - a cached failure isn't
        something to "reuse," it should just be recomputed.
        """
        result = await self.session.execute(
            select(PlanningRun)
            .where(
                PlanningRun.scope_key == scope_key,
                PlanningRun.data_fingerprint == data_fingerprint,
                PlanningRun.llm_provider == llm_provider,
                PlanningRun.llm_model == llm_model,
                PlanningRun.status == PlanningRunStatus.SUCCESS,
            )
            .order_by(PlanningRun.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def list_recent(self, limit: int = 50) -> Sequence[PlanningRun]:
        result = await self.session.execute(
            select(PlanningRun).order_by(PlanningRun.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def get_by_id(self, run_id: int) -> PlanningRun | None:
        return await self.session.get(PlanningRun, run_id)
