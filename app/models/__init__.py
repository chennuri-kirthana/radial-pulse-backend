"""Import every model here so ``Base.metadata`` is complete for Alembic and tests."""

from app.models.assessment import Assessment, AssessmentComponent, AssessmentFinding
from app.models.assets import Asset
from app.models.collaboration import ChatMessage, ChatReadState
from app.models.connections import PlatformConnection
from app.models.governance import Approval, ApprovalNote, AuditEvent
from app.models.identity import User
from app.models.jobs import BackgroundJob
from app.models.media import MediaTaxonomyValue
from app.models.presence import PresenceProfile
from app.models.profile import ClinicProfile, ConsentRecord
from app.models.reporting import MetricSnapshot, ReportArtifact
from app.models.settings import NotificationPreference, PlatformSettings
from app.models.tenancy import (
    Clinic,
    ClinicAssignment,
    ClinicMembership,
    ClinicPractitioner,
    ClinicStageHistory,
    Organization,
    Practitioner,
)
from app.models.work import Notification, WorkItem

__all__ = [
    "Approval",
    "ApprovalNote",
    "Assessment",
    "AssessmentComponent",
    "AssessmentFinding",
    "Asset",
    "AuditEvent",
    "BackgroundJob",
    "ChatMessage",
    "ChatReadState",
    "Clinic",
    "ClinicAssignment",
    "ClinicMembership",
    "ClinicPractitioner",
    "ClinicProfile",
    "ClinicStageHistory",
    "ConsentRecord",
    "MediaTaxonomyValue",
    "MetricSnapshot",
    "Notification",
    "NotificationPreference",
    "Organization",
    "PlatformConnection",
    "PlatformSettings",
    "Practitioner",
    "PresenceProfile",
    "ReportArtifact",
    "User",
    "WorkItem",
]
