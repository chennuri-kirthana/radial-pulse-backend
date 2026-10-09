from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.db.session import session_scope


def get_db() -> Iterator[Session]:
    yield from session_scope()
