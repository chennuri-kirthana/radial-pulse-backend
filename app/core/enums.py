"""Allowed values, exactly as the CHECK rules in db/schema-v15.sql list them.

Names follow docs/00-terminology.md. If the schema changes, change these with it, never alone.
"""

from __future__ import annotations

from enum import StrEnum


class PlatformRole(StrEnum):
    """``users.platform_role``: decides the portal."""

    PLATFORM_ADMINISTRATOR = "platform_administrator"
    DIGITAL_SUCCESS_MANAGER = "digital_success_manager"
    #: Clinic Administrator or Clinic Team Member (the clinic role is in clinic_members.role)
    CLINIC_MEMBER = "clinic_member"
    PRACTITIONER = "practitioner"


class ClinicMemberRole(StrEnum):
    """``clinic_members.role``."""

    CLINIC_ADMINISTRATOR = "clinic_administrator"
    CLINIC_TEAM_MEMBER = "clinic_team_member"


class ClinicStage(StrEnum):
    """``clinics.stage``: Prospective Client → Client Activation."""

    PROSPECTIVE_CLIENT = "prospective_client"
    PRESENCE_DISCOVERED = "presence_discovered"
    ASSESSMENT_COMPLETED = "assessment_completed"
    CLIENT_DISCUSSION = "client_discussion"
    ACTIVE_CLIENT = "active_client"


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


#: Monday..Sunday, the order screens show.
WEEKDAYS: tuple[Weekday, ...] = tuple(Weekday)


class OnlineProfilePlatform(StrEnum):
    """``clinic_online_profiles.platform``."""

    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    GOOGLE_MAPS = "google_maps"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    YOUTUBE = "youtube"
    LINKEDIN = "linkedin"
    X = "x"
    PRACTO = "practo"
    JUSTDIAL = "justdial"
    OTHER = "other"


class OnlineProfileVerification(StrEnum):
    """``clinic_online_profiles.verification``."""

    UNVERIFIED = "unverified"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class AssessmentStatus(StrEnum):
    """``digital_presence_assessments.status``."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewState(StrEnum):
    """``digital_presence_assessments.review_state``."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REDO_REQUESTED = "redo_requested"


class PublicationState(StrEnum):
    """``digital_presence_assessments.publication_state``."""

    UNPUBLISHED = "unpublished"
    PUBLISHED = "published"
    RETRACTED = "retracted"


class WorkItemStatus(StrEnum):
    """``improvement_work_items.status``."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class WorkItemPriority(StrEnum):
    """``improvement_work_items.priority``."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationCategory(StrEnum):
    """``notification_preferences.category`` (and the categories the app sends)."""

    PORTFOLIO_ALLOCATED = "portfolio_allocated"
    WORK_ITEM_ASSIGNED = "work_item_assigned"
    APPROVAL_HANDOFF = "approval_handoff"
    CONNECTION_NEEDS_RECONNECT = "connection_needs_reconnect"


class NotificationChannel(StrEnum):
    """``notification_preferences.channel``."""

    IN_APP = "in_app"
    EMAIL = "email"


class SenderSide(StrEnum):
    """``collaboration_messages.sender_side``."""

    RADIAL_PULSE = "radial_pulse"
    CLINIC = "clinic"


class ConnectedAccountProvider(StrEnum):
    """``connected_accounts.provider``."""

    GOOGLE = "google"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    LINKEDIN = "linkedin"
    X = "x"


class ConnectedAccountStatus(StrEnum):
    """``connected_accounts.status``."""

    CONNECTED = "connected"
    NEEDS_RECONNECT = "needs_reconnect"
    DISCONNECTED = "disconnected"


class ConnectedResourceType(StrEnum):
    """``connected_account_resources.resource_type``."""

    GBP_LOCATION = "gbp_location"
    SEARCH_CONSOLE_SITE = "search_console_site"
    GA4_PROPERTY = "ga4_property"
    YOUTUBE_CHANNEL = "youtube_channel"
    INSTAGRAM_ACCOUNT = "instagram_account"
    FACEBOOK_PAGE = "facebook_page"
    LINKEDIN_PAGE = "linkedin_page"
    X_ACCOUNT = "x_account"


class PhotoAttire(StrEnum):
    """``photos.attire`` (practitioner photos)."""

    WITH_APRON = "with_apron"
    WITHOUT_APRON = "without_apron"


class PhotoAngle(StrEnum):
    """``photos.angle`` (practitioner photos)."""

    LEFT_90 = "left_90"
    LEFT_45 = "left_45"
    FRONT = "front"
    RIGHT_45 = "right_45"
    RIGHT_90 = "right_90"


class PhotoCategory(StrEnum):
    """``photos.category`` (clinic / hospital photos)."""

    EXTERIOR_SIGNAGE = "exterior_signage"
    RECEPTION_WAITING = "reception_waiting"
    CONSULT_PROCEDURE_ROOMS = "consult_procedure_rooms"
    EQUIPMENT_FACILITIES = "equipment_facilities"
    TEAM_AT_WORK = "team_at_work"
    LOGO = "logo"
    COVER = "cover"


class PhotoMimeType(StrEnum):
    """``photos.mime_type``."""

    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    HEIC = "image/heic"


class ProcessingStatus(StrEnum):
    """``photos.processing_status`` / ``voice_samples.processing_status``."""

    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class PhotoReviewState(StrEnum):
    """``photos.review_state``."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActorType(StrEnum):
    """``audit_events.actor_type`` (no CHECK in v15 yet: open question Q10)."""

    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"
