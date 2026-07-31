"""Generic async repository base class.

Concrete repositories set `model` and add entity-specific query methods on
top of this; the session is injected via the constructor (DI) rather than
pulled from a global, so repositories are trivially testable against any
session (including a per-test rollback transaction).
"""

from collections.abc import Iterator, Sequence
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")

_DEFAULT_CHUNK_SIZE = 500


def chunked(seq: Sequence, size: int = _DEFAULT_CHUNK_SIZE) -> Iterator[Sequence]:
    """Yields `seq` in slices of at most `size`.

    Needed anywhere a list of ids is bound into a SQL `IN (...)` clause: at
    scale (10,000+ terminals) an unchunked `.in_(huge_list)` doesn't just run
    slowly, it can outright fail - SQLite caps bound parameters per statement
    at ~999 by default (`SQLITE_MAX_VARIABLE_NUMBER`). Chunking one list at
    500 leaves headroom for a query that binds more than one `.in_()` clause
    in the same statement (see inventory_repository.py, distance_matrix_repository.py,
    demand_history_repository.py, which use a smaller per-dimension chunk size
    for exactly that reason).
    """
    for start in range(0, len(seq), size):
        yield seq[start : start + size]


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
        rows: list[ModelT] = []
        for batch in chunked(values):
            result = await self.session.execute(select(self.model).where(column.in_(batch)))
            rows.extend(result.scalars().all())
        return rows
