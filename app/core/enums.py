"""Platform-wide enumerations.

THE SOURCE OF TRUTH for these values. They are exported to OpenAPI (as named
schemas) in openapi/openapi.json; the frontend generates its TypeScript types from
that file, so a change here reaches the screens through a new contract release.
Add values freely; renaming or removing a value needs a data migration and a
coordinated frontend change.

Stored in the database as plain strings (``native_enum=False``) so adding a value
never needs an ``ALTER TYPE``.
"""

from __future__ import annotations

from enum import StrEnum


class PlatformRole(StrEnum):
    """What a user is inside Radial Pulse itself (see docs/architecture/multi-tenancy.md).

    * PLATFORM_ADMINISTRATOR  — Central team. Platform-wide administration, every clinic.
    * DIGITAL_SUCCESS_MANAGER — internal Radial Pulse user; works ONLY on assigned clinics.
    * CLINIC_USER             — clinic-side person. Has no platform powers; what they can do
                                comes only from their clinic membership(s).
    """

    PLATFORM_ADMINISTRATOR = "platform_administrator"
    DIGITAL_SUCCESS_MANAGER = "digital_success_manager"
    CLINIC_USER = "clinic_user"


class ClinicRole(StrEnum):
    """What a clinic-side user is inside ONE clinic.

    A practitioner (doctor) is NOT automatically a Clinic Administrator (or a user at all):
    practitioners are records in `practitioners`; a login is a separate, optional link.
    """

    CLINIC_ADMINISTRATOR = "clinic_administrator"
    #: Clinic staff: view-only in their own clinic, plus uploading photos/files.
    CLINIC_TEAM_MEMBER = "clinic_team_member"


class ApprovalAction(StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    REDO = "redo"
    PUBLISH = "publish"
    HANDOFF = "handoff"


class ApprovalState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REDO_REQUESTED = "redo_requested"


class PublicationState(StrEnum):
    UNPUBLISHED = "unpublished"
    PUBLISHED = "published"
    RETRACTED = "retracted"


class WorkItemStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class WorkItemPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SnapshotStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
    ERROR = "error"
    PENDING = "pending"


class DataSource(StrEnum):
    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    WEBSITE_CRAWL = "website_crawl"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    YOUTUBE = "youtube"
    LINKEDIN = "linkedin"
    MANUAL = "manual"


class AssetKind(StrEnum):
    CLINIC_PHOTO = "clinic_photo"
    PRACTITIONER_PHOTO = "practitioner_photo"
    BRAND_ASSET = "brand_asset"
    LOGO = "logo"
    AUDIO = "audio"
    VIDEO = "video"
    REPORT = "report"
    GENERATED_MEDIA = "generated_media"
    DOCUMENT = "document"
    #: A photo or PDF sent in the clinic chat (Client Collaboration).
    CHAT_ATTACHMENT = "chat_attachment"


#: Clinic media the Clinic Administrator uploads and Radial Pulse staff review (V1):
#: hospital/clinic photos, doctor photos and voice samples.
REVIEWED_MEDIA_KINDS: frozenset[AssetKind] = frozenset(
    {AssetKind.CLINIC_PHOTO, AssetKind.PRACTITIONER_PHOTO, AssetKind.AUDIO}
)


class AssetStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    FAILED = "failed"
    DELETED = "deleted"


class MediaTaxonomyDimension(StrEnum):
    """WHICH list a media label belongs to. The VALUES live in the ``media_taxonomy`` table,
    so a new outfit or voice sample is a new row, not a code change."""

    #: Hospital/Clinic photos (asset kind clinic_photo) → ``category``.
    CLINIC_PHOTO_CATEGORY = "clinic_photo_category"
    #: Voice samples (asset kind audio) → ``category``.
    VOICE_SAMPLE = "voice_sample"
    #: Doctor photos (asset kind practitioner_photo) → ``apron``, ``angle``, ``outfit``.
    PRACTITIONER_APRON = "practitioner_apron"
    PRACTITIONER_ANGLE = "practitioner_angle"
    PRACTITIONER_OUTFIT = "practitioner_outfit"


class AssessmentStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"  # some components failed or were not available
    FAILED = "failed"


class AssessmentComponentKey(StrEnum):
    """The fixed, user-facing sections of the ONE Digital Presence Assessment.

    Engines (owned by domain teams) contribute to these keys. Adding a key is a product
    decision, not an engine decision.
    """

    WEBSITE = "website"
    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    LOCAL_SEARCH = "local_search"
    SEARCH_READINESS = "search_readiness"  # SEO + AEO + GEO readiness, presented as one section
    SOCIAL_PRESENCE = "social_presence"
    COMPETITOR_BENCHMARK = "competitor_benchmark"


class ComponentStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_AVAILABLE = "not_available"  # e.g. no GBP listing found, or no engine deployed yet


class FindingPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PresencePlatform(StrEnum):
    """Where a clinic can be found online. One generic table; add a value to support a new platform."""

    WEBSITE = "website"
    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    YOUTUBE = "youtube"
    LINKEDIN = "linkedin"
    X = "x"
    PRACTO = "practo"
    JUSTDIAL = "justdial"
    OTHER = "other"


class PresenceVerification(StrEnum):
    UNVERIFIED = "unverified"  # found by an engine or typed in, not yet checked by a person
    CONFIRMED = "confirmed"  # a person confirmed it belongs to the clinic
    REJECTED = "rejected"  # a person said it is NOT the clinic's


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # gave up after max attempts (message goes to the DLQ)


class JobType(StrEnum):
    ASSESSMENT_RUN = "assessment.run"
    #: "Refresh Profile": run Digital Presence Intelligence on its own. Reserved: no API route or
    #: worker handler yet (domain team work).
    PRESENCE_DISCOVER = "presence.discover"


class ClinicStage(StrEnum):
    """How far Radial Pulse has got with a clinic (the stepper on the Clinic Details screen).

    Leads are given to the team; a stage only records progress. A clinic that says no is
    ARCHIVED (``clinics.is_active = false`` + a reason), not moved to an extra stage.
    """

    PROSPECTIVE_CLIENT = "prospective_client"  # New lead
    PROFILE_ENRICHED = "profile_enriched"  # Found online
    ASSESSMENT_COMPLETED = "assessment_completed"  # Report ready
    CLIENT_DISCUSSION = "client_discussion"  # In talks
    ACTIVE_CLIENT = "active_client"  # Customer (Client Activation)


class ClinicStageGroup(StrEnum):
    """The Admin tabs (decision D5): Prospects = stages 1-2, In Progress = 3-4, Active = 5.

    The API applies this grouping itself (``GET /clinics?group=…``, ``stage_group`` on every
    clinic, the dashboard tiles) so no screen has to repeat it.
    """

    PROSPECTS = "prospects"
    IN_PROGRESS = "in_progress"
    ACTIVE = "active"

    @property
    def stages(self) -> tuple[ClinicStage, ...]:
        return STAGE_GROUPS[self]

    @classmethod
    def of(cls, stage: ClinicStage) -> ClinicStageGroup:
        return next(group for group, stages in STAGE_GROUPS.items() if stage in stages)


STAGE_GROUPS: dict[ClinicStageGroup, tuple[ClinicStage, ...]] = {
    ClinicStageGroup.PROSPECTS: (ClinicStage.PROSPECTIVE_CLIENT, ClinicStage.PROFILE_ENRICHED),
    ClinicStageGroup.IN_PROGRESS: (ClinicStage.ASSESSMENT_COMPLETED, ClinicStage.CLIENT_DISCUSSION),
    ClinicStageGroup.ACTIVE: (ClinicStage.ACTIVE_CLIENT,),
}


class WorkArea(StrEnum):
    """Which part of the clinic's digital presence a work item improves ("SEO 3 · GBP 2" chips).

    The first six are the assessment component keys; two extra buckets cover the rest.
    """

    WEBSITE = "website"
    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    LOCAL_SEARCH = "local_search"
    SEARCH_READINESS = "search_readiness"
    SOCIAL_PRESENCE = "social_presence"
    COMPETITOR_BENCHMARK = "competitor_benchmark"
    CLINIC_PROFILE = "clinic_profile"
    OTHER = "other"


class UserStatus(StrEnum):
    """Shown on the Users screen. Worked out from the user row, never stored."""

    INVITED = "invited"  # created, has not signed in yet
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


# ------------------------------------------------------------------ chat (Client Collaboration)
class ChatSide(StrEnum):
    """Which side of the conversation a message came from (left or right bubble)."""

    RADIAL_PULSE = "radial_pulse"  # Platform Administrator or Digital Success Manager
    CLINIC = "clinic"  # Clinic Administrator or Clinic Team Member


# ------------------------------------------------------------------ connected accounts
class ConnectionPlatform(StrEnum):
    """Accounts a clinic can connect with OAuth ("Connect Your Accounts").

    The website is not here: it needs no login, it is just a link (clinic details / presence).
    """

    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    YOUTUBE = "youtube"
    LINKEDIN = "linkedin"
    X = "x"


class ConnectionStatus(StrEnum):
    NOT_CONNECTED = "not_connected"  # never connected (not stored; shown by the API)
    PENDING = "pending"  # sign-in with the platform started, not finished
    CONNECTED = "connected"
    NEEDS_RECONNECT = "needs_reconnect"  # token expired or was revoked: press Connect again
    DISCONNECTED = "disconnected"


# ------------------------------------------------------------------ settings
class NotificationCategory(StrEnum):
    """Groups of in-app notifications a person can switch on/off (Settings → Notifications)."""

    CLINIC_ASSIGNED = "clinic_assigned"  # a clinic was assigned to me (DSM)
    WORK_ITEM_ASSIGNED = "work_item_assigned"  # a work item was given to me
    APPROVAL_HANDOFF = "approval_handoff"  # a review was handed to me


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"  # saved now; sending emails for notifications comes later


class DateFormat(StrEnum):
    DD_MMM_YYYY = "DD MMM YYYY"  # 27 Sep 2026
    DD_MM_YYYY = "DD/MM/YYYY"
    YYYY_MM_DD = "YYYY-MM-DD"
