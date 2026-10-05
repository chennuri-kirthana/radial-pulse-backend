from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, text

from app.core.enums import PlatformRole
from app.models import User
from app.repositories.base import Repository


@dataclass(frozen=True)
class AccountMatch:
    """Just enough to decide what to do with an email, without seeing the whole account."""

    id: UUID
    platform_role: PlatformRole


def like_pattern(search: str) -> str:
    """``%search%`` with the user's own % and _ treated as plain characters (use escape='\\')."""
    escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class UserRepository(Repository):
    """Reads accounts. On PostgreSQL the ``users`` table is under row-level security (0007): a
    person only sees themselves, the people of clinics in scope, staff (if staff), and accounts
    they created. The two ``find_*`` lookups below work BEFORE that is known (sign-in, adding a
    team member) through small SECURITY DEFINER functions that return only an id and a role."""

    def get(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_sub(self, cognito_sub: str) -> User | None:
        return self.session.scalar(select(User).where(User.cognito_sub == cognito_sub))

    def _postgres(self) -> bool:
        return self.session.get_bind().dialect.name == "postgresql"

    def find_id_by_sub(self, cognito_sub: str) -> UUID | None:
        """Sign-in: which account has this login? Works before the caller is known."""
        if self._postgres():
            found = self.session.scalar(text("SELECT rp_user_id_by_sub(:sub)"), {"sub": cognito_sub})
            return UUID(str(found)) if found else None
        return self.session.scalar(select(User.id).where(User.cognito_sub == cognito_sub))

    def find_by_email(self, email: str) -> AccountMatch | None:
        """Does an account with this email exist (anywhere)? Returns only its id and role."""
        if self._postgres():
            row = self.session.execute(
                text("SELECT id, platform_role FROM rp_user_by_email(:email)"), {"email": email.lower()}
            ).first()
        else:
            row = self.session.execute(
                select(User.id, User.platform_role).where(User.email == email.lower())
            ).first()
        if row is None:
            return None
        return AccountMatch(id=UUID(str(row[0])), platform_role=PlatformRole(row[1]))

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email.lower()))

    def list(
        self,
        limit: int,
        offset: int,
        *,
        platform_role: PlatformRole | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> tuple[list[Any], int]:
        stmt = select(User)
        if platform_role is not None:
            stmt = stmt.where(User.platform_role == platform_role)
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        if search:
            pattern = like_pattern(search)
            stmt = stmt.where(
                or_(User.email.ilike(pattern, escape="\\"), User.full_name.ilike(pattern, escape="\\"))
            )
        return self.paginate(stmt.order_by(User.created_at.desc(), User.id), limit, offset)
