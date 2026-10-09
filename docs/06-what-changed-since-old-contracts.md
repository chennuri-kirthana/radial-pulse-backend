# What changed since the old API contracts (in `old-contracts-OUTDATED/`)

Naming for all new code and paths: `docs/00-terminology.md`.

The old contracts were written for database v3. The database is now **v15**. Use the old files only for
**response shapes, paging and the error format**. Everything below overrides them.

## Renamed
| Old (contracts) | Now |
|---|---|
| `doctor` (role, portal, paths) | `practitioner` |
| `organizations`, `organization_id` | `client_organizations`, `client_organization_id` (path `/api/v1/client-organizations`) |
| `chat`, `/chat/...` | Client Collaboration: `collaboration_messages` (path `/api/v1/clinics/{clinic_id}/collaboration-messages`) |
| `work-items`, `work_items`, `finding_code`, `owner_user_id` | `improvement_work_items`, `opportunity_code`, `assignee_user_id` |
| `assessments`, `seo_report_id` | `digital_presence_assessments`, `digital_growth_report_id` |
| `clinic_user` login role, `clinic_staff` | `clinic_member`; Clinic Team Member |
| stage `profile_enriched` | `presence_discovered` |
| `clinic_dsm_assignments`, "assigned clinics" | `portfolio_allocations` per **Client Organization** |
| notification `kind`, category `clinic_assigned` | `category`, `portfolio_allocated` |
| scope `central/seo.read` | still to be confirmed (see service-to-service doc, section 14) |

## Removed (do NOT build)
- Practitioner profile-change approval: `/practitioners/{id}/profile-changes` (+ review). Edits go live directly.
- Voice review: `POST …/voice-samples/{id}/review`, "Needs re-record". Voice has no review; duplicate titles are refused.
- Unread counts and `POST …/chat/read` (no read markers).
- `is_owner` / "owner" on clinic members.
- `sequence` on reports.
- Work item `kind`, `area`, `source_team`.
- `platform_settings.organization_name`.

## Changed rules
- `POST /client-organizations` and `POST /clinics`: **Platform Administrator only** (was admin + DSM).
- DSM access = clinics of the Client Organizations allocated to them (was per clinic).
- Editing the shared practitioner record: practitioner himself, DSM, admin. **Not** the Clinic Administrator.
- Several Clinic Administrators allowed; the last active one can't be removed.
- Work item assignee must belong to the clinic.
- Photo approve of a replacement: old one becomes `rejected` ("Replaced by a newer photo").
- Stage history is written by the database; the API never inserts it.
