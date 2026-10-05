from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select, update

from app.core.enums import ClinicRole, ClinicStage, WorkArea, WorkItemStatus
from app.models import (
    Clinic,
    ClinicAssignment,
    ClinicMembership,
    ClinicPractitioner,
    ClinicStageHistory,
    Organization,
    Practitioner,
    User,
    WorkItem,
)
from app.repositories.base import Repository
from app.repositories.users import like_pattern

OPEN_WORK_STATUSES = (
    WorkItemStatus.TODO,
    WorkItemStatus.IN_PROGRESS,
    WorkItemStatus.BLOCKED,
    WorkItemStatus.IN_REVIEW,
)


class OrganizationRepository(Repository):
    def get(self, organization_id: UUID) -> Organization | None:
        return self.session.get(Organization, organization_id)


class ClinicRepository(Repository):
    def get(self, clinic_id: UUID) -> Clinic | None:
        # Clinic IS the tenant; callers must already have passed the clinic access check.
        return self.session.get(Clinic, clinic_id)

    def list_accessible(
        self,
        clinic_ids: Iterable[UUID] | None,
        limit: int,
        offset: int,
        *,
        stages: Sequence[ClinicStage] | None = None,
        dsm_user_id: UUID | None = None,
        unassigned: bool = False,
        search: str | None = None,
        archived: bool = False,
    ) -> tuple[list[Any], int]:
        """``clinic_ids=None`` means all clinics (Platform Administrator). An empty set returns nothing.

        ``archived=False`` lists live clinics; ``archived=True`` lists only archived ones.
        ``search`` matches clinic name, website or any practitioner's name (case-insensitive).
        """
        stmt: Select[Any] = select(Clinic).where(Clinic.is_active.is_(not archived))
        if clinic_ids is not None:
            ids = list(clinic_ids)
            if not ids:
                return [], 0
            stmt = stmt.where(Clinic.id.in_(ids))
        if stages:
            stmt = stmt.where(Clinic.stage.in_(list(stages)))
        active_dsm = (
            select(ClinicAssignment.id)
            .where(ClinicAssignment.clinic_id == Clinic.id, ClinicAssignment.is_active.is_(True))
            .correlate(Clinic)
        )
        if dsm_user_id is not None:
            stmt = stmt.where(exists(active_dsm.where(ClinicAssignment.user_id == dsm_user_id)))
        if unassigned:
            stmt = stmt.where(~exists(active_dsm))
        if search:
            # The user's own % and _ are plain characters. Trigram indexes (0009) make this fast.
            pattern = like_pattern(search)
            practitioner_match = (
                select(ClinicPractitioner.id)
                .join(Practitioner, Practitioner.id == ClinicPractitioner.practitioner_id)
                .where(
                    ClinicPractitioner.clinic_id == Clinic.id,
                    ClinicPractitioner.is_active.is_(True),
                    Practitioner.full_name.ilike(pattern, escape="\\"),
                )
                .correlate(Clinic)
            )
            stmt = stmt.where(
                or_(
                    Clinic.name.ilike(pattern, escape="\\"),
                    Clinic.website_url.ilike(pattern, escape="\\"),
                    exists(practitioner_match),
                )
            )
        return self.paginate(stmt.order_by(Clinic.name, Clinic.id), limit, offset)

    def ids_in_organization(self, organization_id: UUID) -> list[UUID]:
        return list(self.session.scalars(select(Clinic.id).where(Clinic.organization_id == organization_id)))

    # ---- extra columns for list screens (one query each for a whole page of clinics) ----
    def primary_practitioner_names(self, clinic_ids: Sequence[UUID]) -> dict[UUID, str]:
        if not clinic_ids:
            return {}
        rows = self.session.execute(
            select(ClinicPractitioner.clinic_id, Practitioner.full_name)
            .join(Practitioner, Practitioner.id == ClinicPractitioner.practitioner_id)
            .where(
                ClinicPractitioner.clinic_id.in_(clinic_ids),
                ClinicPractitioner.is_primary.is_(True),
                ClinicPractitioner.is_active.is_(True),
            )
        )
        return {cid: name for cid, name in rows}

    def active_dsms(self, clinic_ids: Sequence[UUID]) -> dict[UUID, User]:
        if not clinic_ids:
            return {}
        rows = self.session.execute(
            select(ClinicAssignment.clinic_id, User)
            .join(User, User.id == ClinicAssignment.user_id)
            .where(ClinicAssignment.clinic_id.in_(clinic_ids), ClinicAssignment.is_active.is_(True))
        )
        return {cid: user for cid, user in rows}

    def open_work_counts(self, clinic_ids: Sequence[UUID]) -> dict[UUID, list[tuple[WorkArea, int]]]:
        if not clinic_ids:
            return {}
        rows = self.session.execute(
            select(WorkItem.clinic_id, WorkItem.area, func.count())
            .where(WorkItem.clinic_id.in_(clinic_ids), WorkItem.status.in_(OPEN_WORK_STATUSES))
            .group_by(WorkItem.clinic_id, WorkItem.area)
            .order_by(WorkItem.clinic_id, WorkItem.area)
        )
        result: dict[UUID, list[tuple[WorkArea, int]]] = {}
        for cid, area, count in rows:
            result.setdefault(cid, []).append((area, int(count)))
        return result


class StageHistoryRepository(Repository):
    """Append-only: there is deliberately no update or delete here."""

    def list_for_clinic(self, clinic_id: UUID) -> list[ClinicStageHistory]:
        stmt = (
            select(ClinicStageHistory)
            .where(ClinicStageHistory.clinic_id == clinic_id)
            .order_by(ClinicStageHistory.changed_at, ClinicStageHistory.id)
        )
        return list(self.session.scalars(stmt))


class PractitionerRepository(Repository):
    """A practitioner (the person, one per business) + their link to each clinic they work at."""

    def list_for_clinic(
        self, clinic_id: UUID, limit: int, offset: int
    ) -> tuple[list[tuple[ClinicPractitioner, Practitioner]], int]:
        base = (
            select(ClinicPractitioner, Practitioner)
            .join(Practitioner, Practitioner.id == ClinicPractitioner.practitioner_id)
            .where(ClinicPractitioner.clinic_id == clinic_id)
        )
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.execute(
            base.order_by(ClinicPractitioner.is_primary.desc(), Practitioner.full_name, Practitioner.id)
            .limit(limit)
            .offset(offset)
        )
        return [(link, person) for link, person in rows], int(total)

    def get_in_clinic(
        self, clinic_id: UUID, practitioner_id: UUID
    ) -> tuple[ClinicPractitioner, Practitioner] | None:
        row = self.session.execute(
            select(ClinicPractitioner, Practitioner)
            .join(Practitioner, Practitioner.id == ClinicPractitioner.practitioner_id)
            .where(
                ClinicPractitioner.clinic_id == clinic_id,
                ClinicPractitioner.practitioner_id == practitioner_id,
            )
        ).first()
        return (row[0], row[1]) if row else None

    def get_person(self, practitioner_id: UUID) -> Practitioner | None:
        return self.session.get(Practitioner, practitioner_id)

    def find_by_registration(self, organization_id: UUID, registration_number: str) -> Practitioner | None:
        """The business's doctor with this medical registration number, if any (at most one)."""
        return self.session.scalar(
            select(Practitioner).where(
                Practitioner.organization_id == organization_id,
                Practitioner.registration_number == registration_number,
            )
        )

    def clear_primary(self, clinic_id: UUID) -> None:
        """Un-mark the clinic's current main practitioner (before marking another one)."""
        self.session.execute(
            update(ClinicPractitioner)
            .where(ClinicPractitioner.clinic_id == clinic_id, ClinicPractitioner.is_primary.is_(True))
            .values(is_primary=False)
            .execution_options(synchronize_session="fetch")
        )
        self.session.flush()


class MembershipRepository(Repository):
    def active_for_user(self, user_id: UUID) -> list[ClinicMembership]:
        stmt = select(ClinicMembership).where(
            ClinicMembership.user_id == user_id, ClinicMembership.is_active.is_(True)
        )
        return list(self.session.scalars(stmt))

    def get(self, clinic_id: UUID, user_id: UUID) -> ClinicMembership | None:
        return self.session.scalar(
            select(ClinicMembership).where(
                ClinicMembership.clinic_id == clinic_id, ClinicMembership.user_id == user_id
            )
        )

    def get_in_clinic(self, clinic_id: UUID, membership_id: UUID) -> ClinicMembership | None:
        return self.session.scalar(
            select(ClinicMembership).where(
                ClinicMembership.clinic_id == clinic_id, ClinicMembership.id == membership_id
            )
        )

    def count_active_admins(self, clinic_id: UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(ClinicMembership)
                .join(User, User.id == ClinicMembership.user_id)
                .where(
                    ClinicMembership.clinic_id == clinic_id,
                    ClinicMembership.role == ClinicRole.CLINIC_ADMINISTRATOR,
                    ClinicMembership.is_active.is_(True),
                    User.is_active.is_(True),
                )
            )
            or 0
        )

    def team_for_clinic(self, clinic_id: UUID) -> list[tuple[ClinicMembership, User]]:
        stmt = (
            select(ClinicMembership, User)
            .join(User, User.id == ClinicMembership.user_id)
            .where(ClinicMembership.clinic_id == clinic_id)
            .order_by(User.email)
        )
        return [(m, u) for m, u in self.session.execute(stmt).all()]


class AssignmentRepository(Repository):
    def active_for_user(self, user_id: UUID) -> list[ClinicAssignment]:
        stmt = select(ClinicAssignment).where(
            ClinicAssignment.user_id == user_id, ClinicAssignment.is_active.is_(True)
        )
        return list(self.session.scalars(stmt))

    def active_for_clinic(self, clinic_id: UUID) -> ClinicAssignment | None:
        return self.session.scalar(
            select(ClinicAssignment).where(
                ClinicAssignment.clinic_id == clinic_id, ClinicAssignment.is_active.is_(True)
            )
        )

    def for_clinic(self, clinic_id: UUID) -> list[ClinicAssignment]:
        """The clinic's DSM now and before (history), oldest first."""
        stmt = (
            select(ClinicAssignment)
            .where(ClinicAssignment.clinic_id == clinic_id)
            .order_by(ClinicAssignment.created_at)
        )
        return list(self.session.scalars(stmt))

    def find(self, clinic_id: UUID, user_id: UUID) -> ClinicAssignment | None:
        return self.session.scalar(
            select(ClinicAssignment).where(
                ClinicAssignment.clinic_id == clinic_id, ClinicAssignment.user_id == user_id
            )
        )

    def active_counts_by_user(self, user_ids: Sequence[UUID]) -> dict[UUID, int]:
        if not user_ids:
            return {}
        rows = self.session.execute(
            select(ClinicAssignment.user_id, func.count())
            .where(ClinicAssignment.user_id.in_(user_ids), ClinicAssignment.is_active.is_(True))
            .group_by(ClinicAssignment.user_id)
        )
        return {uid: int(n) for uid, n in rows}
