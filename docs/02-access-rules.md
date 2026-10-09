# Access rules: who can see and change what

These rules are **enforced inside the database** (row-level security, section 12 of `db/schema-v15.sql`).
The API must **also** check roles before acting, so the user gets a clear 403 instead of an empty result.
Tests: `db/tests/04-access-rules-tests.sql`.

## Who is who
| Name | How the database knows |
|---|---|
| Platform Administrator (admin) | `users.platform_role = 'platform_administrator'` and active |
| DSM of a clinic | active `portfolio_allocations` row for the clinic's **Client Organization** |
| Clinic Administrator | active `clinic_members` row, role `clinic_administrator` |
| Team member | active `clinic_members` row, role `clinic_team_member` (read only) |
| Practitioner | `practitioners.user_id` = the login, **actively** linked to the clinic in `clinic_practitioners` |
| system | a background job that set `rp.actor = 'system'` |
| service | another backend using database role `radial_service` (read only) |

## Who can SEE what
| Data | Admin | DSM (own) | Clinic Admin | Team member | Practitioner | Other clinic |
|---|---|---|---|---|---|---|
| clinic, profile, online profiles, photos, practitioners list | all | ✓ | ✓ | ✓ | ✓ | ✗ |
| Digital Presence Assessments | all | all | **published only** | **published only** | **published only** | ✗ |
| team members, connected accounts | all | ✓ | ✓ | ✓ | ✗ | ✗ |
| work items | all | ✓ | ✓ | ✓ | only those assigned to him | ✗ |
| voice samples | all | ✓ | ✓ | ✗ | **own only** | ✗ |
| audit log | all | ✓ | ✓ | ✗ | ✗ | ✗ |
| stage history | all | ✓ | ✗ | ✗ | ✗ | ✗ |
| messages | all | ✓ | ✓ | ✓ | ✓ | ✗ |
| new leads (business with no DSM) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| notifications, notification preferences | own | own | own | own | own | — |
| platform settings | ✓ | ✓ | ✓ | ✓ | ✓ | — |

## Who can CHANGE what
| Action | Allowed |
|---|---|
| Create business / clinic | **Platform Administrator only** |
| Edit clinic details | admin, DSM, Clinic Administrator |
| Move stage, archive / restore, change Client Organization | admin, DSM |
| Allocate a DSM | admin only |
| Invite users | admin (any role); DSM / Clinic Administrator (only `clinic_member` or `practitioner` logins) |
| Add / change clinic members and practitioner links (incl. consultation schedule, weekly holiday, fee, time zone, schedule notes) | admin, DSM, Clinic Administrator (**not** the practitioner) |
| Edit the shared practitioner record (bio, qualifications, specialty, practice start year, services / conditions, patients treated, highlights) | admin, DSM of a linked clinic, **the practitioner himself** (not a Clinic Administrator) |
| Change practitioner name / registration number / login | admin, DSM |
| Upload / delete photos and voice | Clinic Administrator; the practitioner for his own. **Not** the DSM, **not** team members |
| Review / sort photos | admin, DSM |
| Online profiles | add: admin, DSM, Clinic Administrator; confirm / remove: admin, DSM |
| Reports (create, review, publish) | admin, DSM (and system jobs) |
| Work items | admin, DSM |
| Send a message | admin, DSM, Clinic Administrator, linked practitioner, **only as himself** |
| Connect accounts | admin, DSM, Clinic Administrator; OAuth tickets only by the person who started |
| Change someone's role, active flag, email | admin only |
| Platform settings | admin only |
| Audit log | add only (anyone signed in / system); nobody edits |
| Stage history | nobody directly (trigger only) |

## Backend services (`radial_service`): read only
`client_organizations`, `clinics`, `clinic_profiles`, `practitioners`, `clinic_practitioners`, `clinic_online_profiles`,
**approved** `photos`, `connected_accounts` (**without `secret_ref`**), `connected_account_resources`.
Used by this backend's read-only `/api/v1/internal/*` routes, for other teams' backends.
