"""The 22 tables of db/schema-v15.sql. Importing this package registers all of them."""

from app.models.assessments import DigitalPresenceAssessment, ImprovementWorkItem
from app.models.audit import AuditEvent
from app.models.clinics import Clinic, ClinicMember, ClinicOnlineProfile, ClinicProfile, ClinicStageChange
from app.models.collaboration import CollaborationMessage
from app.models.connections import ConnectedAccount, ConnectedAccountResource, OAuthState
from app.models.identity import User
from app.models.media import Photo, VoiceSample
from app.models.notifications import Notification, NotificationPreference
from app.models.organizations import ClientOrganization, PortfolioAllocation
from app.models.practitioners import ClinicPractitioner, Practitioner
from app.models.settings import PlatformSettings

__all__ = [
    "AuditEvent",
    "ClientOrganization",
    "Clinic",
    "ClinicMember",
    "ClinicOnlineProfile",
    "ClinicPractitioner",
    "ClinicProfile",
    "ClinicStageChange",
    "CollaborationMessage",
    "ConnectedAccount",
    "ConnectedAccountResource",
    "DigitalPresenceAssessment",
    "ImprovementWorkItem",
    "Notification",
    "NotificationPreference",
    "OAuthState",
    "Photo",
    "PlatformSettings",
    "PortfolioAllocation",
    "Practitioner",
    "User",
    "VoiceSample",
]
