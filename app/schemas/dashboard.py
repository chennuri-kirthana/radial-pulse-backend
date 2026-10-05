from __future__ import annotations

from app.core.enums import ClinicStage
from app.schemas.common import ApiModel


class StageCount(ApiModel):
    stage: ClinicStage
    count: int


class MonthCount(ApiModel):
    #: "YYYY-MM"
    month: str
    count: int


class DashboardSummary(ApiModel):
    """Numbers for the Admin and DSM dashboards, over the clinics the caller can see.

    Admin tiles: Total = ``total_clinics``; Prospects / In Progress / Active = the stage groups.
    Archived clinics are counted separately and are NOT in the other numbers.
    """

    total_clinics: int
    prospects: int  # New lead + Found online
    in_progress: int  # Report ready + In talks
    active: int  # Customer
    archived: int
    by_stage: list[StageCount]
    #: New clinics added per month, oldest first (last 6 months, including this one).
    new_clinics_by_month: list[MonthCount]
    #: Assessments finished but not yet published (waiting for DSM review) — "Audits Ready".
    assessments_awaiting_review: int
    open_work_items: int
