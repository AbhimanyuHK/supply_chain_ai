"""Generic async repository base class.

Concrete repositories set `model` and add entity-specific query methods on
top of this; the session is injected via the constructor (DI) rather than
pulled from a global, so repositories are trivially testable against any
session (including a per-test rollback transaction).
"""

from typing import Generic, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> Sequence[ModelT]:
        result = await self.session.execute(select(self.model))
        return result.scalars().all()

    async def _list_by_column_in(self, column, values: Sequence[int]) -> Sequence[ModelT]:
        if not values:
            return []
        result = await self.session.execute(select(self.model).where(column.in_(values)))
        return result.scalars().all()
