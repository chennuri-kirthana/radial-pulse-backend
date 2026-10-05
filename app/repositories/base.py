from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, obj: T) -> T:
        self.session.add(obj)
        self.session.flush()
        return obj

    def paginate(self, stmt: Select[Any], limit: int, offset: int) -> tuple[list[Any], int]:
        total = self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        items = list(self.session.scalars(stmt.limit(limit).offset(offset)))
        return items, int(total)
