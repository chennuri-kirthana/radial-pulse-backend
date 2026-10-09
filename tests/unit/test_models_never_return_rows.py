"""No model may use INSERT ... RETURNING (see app/db/base.py: the SELECT rule would refuse rows the
writer can't read, e.g. a team member's audit row). This keeps it that way for new models."""

from __future__ import annotations

import app.models  # noqa: F401
from app.db.base import Base


def test_no_model_reads_rows_back_on_insert() -> None:
    assert [m.class_.__name__ for m in Base.registry.mappers if m.eager_defaults is not False] == []
