# API contract changelog

What changed **for the screens** in each contract version. The full contract is
`openapi/openapi.json` (also attached to each GitHub Release). Version rules:
[docs/api/contract-versioning.md](../docs/api/contract-versioning.md).

## v0.5.0 — 2026-10-09

**Breaking** (minor bump), for other teams' backends only (no screen changes):
`/api/v1/internal/*` no longer accepts Cognito service tokens (client credentials). Callers now
sign each request with their own **AWS IAM role** (SigV4, service `execute-api`) and call the
separate internal **REST API** (`AWS_IAM` on every method + Central's resource policy).
- The `ServiceBearer` security scheme is gone. The internal routes list no security scheme in this
  contract: API Gateway checks the signature; the backend then checks the role and its scope.
- Same answers as before: no / unknown caller → 401, role without the route's scope → 403,
  IAM not set up in that environment → 503.
- People's routes (`/api/v1/...` with a Cognito access token) are unchanged.

## v0.4.1 — 2026-10-09

**New** (additions only, nothing removed or renamed): two read-only routes for other teams'
backends (Phase 1: the SEO team / Digital Growth Team). Scope `clinics.read`,
like the other `/api/v1/internal` routes. **Active client clinics only** (`stage = active_client`
and not archived).

- `GET /api/v1/internal/active-clinics?limit=&offset=` → `{items: [{clinic_id, name}], total, limit, offset}`.
  `total` = how many active client clinics there are. Ordered by name.
- `GET /api/v1/internal/clinic-nap/{clinic_id}` → `{clinic_id, name, address: {line, city, state,
  postal_code, country}, phone, website_url}`. `phone` / `website_url` are null when missing.
  A lead, an archived clinic and an unknown id all get the same 404 `not_found`.

## v0.4.0 — 2026-10-09

**Breaking** (minor bump): the API now follows database schema v15 and the official names in
`docs/00-terminology.md` (same name in every layer). Old paths and fields are gone, not aliased.

**Errors** (every route):
- Body is `type, title, status, code, detail, request_id`, plus `fields` (field → message) for 400.
- Bad input is **400 `invalid_request`** (was 422 `validation_error`). Conflicts are **409
  `state_conflict`** (was `conflict` / `invalid_state`). A switched-off or unknown account is
  **403 `account_disabled`** (was `not_provisioned`).

**Renamed paths** (all under `/api/v1`):

| Old | New |
|---|---|
| `/clinics/{id}/team` | `/clinics/{id}/clinic-members` (key is now `{user_id}`) |
| `/clinics/{id}/assignment(s)` | `/portfolio-allocations` and `/portfolio-allocations/{client_organization_id}` (per **Client Organization**, admin only) |
| `/clinics/{id}/practitioners` | `/clinics/{id}/clinic-practitioners` (+ `/lookup?registration_number=`) |
| `PATCH /clinics/{id}/practitioners/{pid}` | split: `/clinics/{id}/clinic-practitioners/{pid}` (this clinic's details) and `/practitioners/{pid}` (shared record) |
| `/clinics/{id}/profile` | `/clinics/{id}/clinic-profile` (the practitioner part moved to `/clinics/{id}/practitioner-profile`) |
| `/clinics/{id}/presence-profiles` | `/clinics/{id}/clinic-online-profiles` |
| `/clinics/{id}/assessments`, `/assessments` | `/clinics/{id}/digital-presence-assessments` (+ `/review`, `/publish`, `/retract`) |
| `/clinics/{id}/work-items`, `/work-items` | `/clinics/{id}/improvement-work-items` |
| `/clinics/{id}/chat/messages` | `/clinics/{id}/collaboration-messages` (+ `/{id}/replies`, attachments) |
| `/clinics/{id}/connections/{platform}` | `/clinics/{id}/connected-accounts` (by account id) |
| `/clinics/{id}/stage-history` | `/clinics/{id}/clinic-stage-changes` |
| `/settings/platform` | `/platform-settings` |
| `/auth/me/notification-settings` | `/auth/me/notification-preferences` |

**New**: `/client-organizations` (admin creates and renames), `/clinics/{id}/photos` (upload →
complete → DSM review / sort; view links), `/clinics/{id}/voice-samples`,
`/clinics/{id}/practitioner-profile` (the Practitioner Profile screen),
`POST /notifications/read-all`.

**Removed** (no table in v15): assets, approvals, snapshots, reports, `/media/taxonomy`, chat
"mark read" and inbox (no unread counts), asset download links. Starting a new "Connect" (OAuth)
waits for open question Q3.

**Changed rules / fields** (highlights):
- Roles: `platform_role` is `platform_administrator`, `digital_success_manager`, `clinic_member`
  or `practitioner`. `/auth/me` → `clinics[].clinic_member_role`, `is_digital_success_manager`,
  `is_practitioner`, and `practitioner_id`.
- Only the Platform Administrator creates clinics (new leads). Without `client_organization_id`
  the business is created in the same step. A DSM sees the clinics of his Client Organizations.
- Stage `profile_enriched` → `presence_discovered`. Clinic `operating_since` → `established_year`.
- Practitioners: `practice_start_year` (years of experience is computed), `services_and_conditions`,
  `approx_patients_treated`, `highlights`. Per clinic: `consultation_hours`
  (`{"mon":[{"from":"10:00","to":"14:00"}], ...}`), `weekly_off_days`, `consultation_fee` (a
  decimal like `"500.00"`, not paise), `consultation_fee_currency`, `consultation_time_zone`,
  `schedule_notes`.
- Work items: `owner_user_id` → `assignee_user_id`, `finding_code` → `opportunity_code`; no `area`.
- Notifications: `kind` → `category`.

## v0.3.1 — 2026-10-08

**Additions only** (patch): the Practitioner Profile. Nothing was removed or renamed; no new
required input. Details and examples: `docs/api/milestone1-api.md` → "Practitioner Profile".

For the screens:

- `GET /clinics/{id}/profile` has a new object **`practitioner_profile`** (always present):
  `practitioner_id`, `full_name`, `specialization`, `qualifications`, `years_of_experience`,
  `clinic_name`, `clinic_operating_since`, `clinic_address` (`address_line`, `city`, `state`,
  `postal_code`, `country`), `consultation_schedule`, `weekly_holiday`, `consultation_fee`,
  `services`, `patients_treated`, `professional_highlights`. Practitioner fields are `null` while the
  clinic has no main practitioner.
- `PUT /clinics/{id}/profile` accepts an optional `practitioner_profile` with the same fields (all
  optional; fields you leave out are not changed). It bumps `version` like the other sections.
- **Money**: `consultation_fee` is `{ "amount_minor": 50000, "currency": "INR" }` (paise; ₹500).
- **Schedule**: `consultation_schedule` is `{ "timezone", "days": { "mon": [{ "opens": "09:00",
  "closes": "13:00" }] }, "notes" }` — several windows per day, no overlaps.
- `weekly_holiday` is a list of day codes (`["sun"]`). A holiday with timings → 422.
- New errors on `PUT /clinics/{id}/profile` with `practitioner_profile`: 422 (bad values, or no
  `full_name` when the clinic has no practitioner yet), 409 (practitioners exist but none is main),
  403 (missing `practitioners:write` / `clinics:write`).
- Practitioners (`GET/POST /clinics/{id}/practitioners`, `PATCH …/{pid}`): new fields
  `years_of_experience`, `patients_treated`, `professional_highlights`, `consultation_schedule`,
  `weekly_holiday`, `consultation_fee`. `specialty` keeps its name there (the profile calls it
  `specialization`).
- Clinics (`GET/POST/PATCH /clinics…`): new field `operating_since` (a year, not in the future).

For backend services: `GET /internal/clinics/{id}/profile` returns the same `practitioner_profile`
(scope `profile.read`, unchanged; `team` stays empty).

## v0.3.0 — 2026-10-06

**Breaking** (minor bump while 0.x): sign-in changes from Google to **email + password**.

For the screens (web and mobile):

- Sign-in is Cognito **Managed Login** with email + password (Authorization Code + PKCE, public
  app clients). There is no Google button. Keep sending the **access token** as
  `Authorization: Bearer …`; nothing else about calling the API changes.
- `GET /auth/me` → `sign_in_method` is now `"email_password"` (was `"google"`).
- Inviting someone (`POST /users`, `POST /clinics/{id}/team`) creates their Cognito sign-in. Cognito
  emails a temporary password; on first sign-in Managed Login asks for a new one. "Resend invite"
  answers **409** once the person has chosen a password.
- `status` (Users screen) and `has_signed_in` (team) now mean "has signed in at least once".
- Deactivating a user also signs them out everywhere (their refresh token stops working).
- `GET /settings/integrations` → `invite_email` is now `"cognito"` or `"log"`.
- A user route refuses any access token that names no user (401).

New, for backend services only (never call these from an app):

- `POST /internal/clinics/{id}/snapshots` (scope `snapshots.write`),
  `POST /internal/clinics/{id}/reports` (`reports.write`; no `asset_id`),
  `GET /internal/clinics/{id}/profile` (`profile.read`; `team` is always empty),
  `GET /internal/clinics/{id}/presence-profiles` (`presence.read`).
  Cognito client-credentials tokens only (`ServiceBearer` in the contract); people's tokens get 401.

Addition (frontend):

- `GET /clinics/{id}/assets` has new filters `apron`, `angle` and `outfit` (doctor photos; codes from
  `GET /media/taxonomy`). An unknown code returns an empty list.

## v0.2.0 — 2026-10-05

**Breaking** (minor bump while 0.x). This release fixes the clinic media review workflow and
security issues found by the backend audit (5 Oct 2026). Frontend: please read every point.

Clinic media workflow (V1):

- **Who does what.** Only the Clinic Administrator uploads clinic media (`clinic_photo`,
  `practitioner_photo`, `audio` = voice samples), using the new permission `media:upload`. Only the
  DSM and the Platform Administrator approve, reject or ask for a retake (`redo`), using the new
  permission `media:review`. Clinic Administrators can no longer decide on clinic media. Staff can no
  longer upload it (403). Clinic Team Members can no longer upload it (403).
- **Review starts on confirm.** `POST …/assets/{id}/confirm` submits clinic media for review: the
  response has `approval_state: "submitted"` and a `review` object. No separate submit call is needed.
  Nothing can be reviewed before its upload is confirmed (409).
- **Retake = new upload.** After `redo` (or `reject`), upload the new file with
  `previous_version_id` = the old file. The new file starts its own review. The same file cannot
  be submitted again (409).
- **Labels (new, REQUIRED for clinic media)** on `POST …/assets/uploads`:
  `clinic_photo` needs `category`; `audio` needs `category` (voice sample type);
  `practitioner_photo` needs `practitioner_id` (a practitioner of this clinic), `apron`, `angle` and
  `outfit`. Labels on any other kind → 422. Codes come from the new **`GET /media/taxonomy`**
  (dimension, code, label, sort_order). Build the pickers from it; the list will grow.
- **`AssetRead`** has new fields: `practitioner_id`, `category`, `apron`, `angle`, `outfit` and
  `review` (`approval_id`, `state`, `clinic_message`, `internal_note`, `submitted_by_user_id`,
  `decided_by_user_id`, `available_actions`, `updated_at`).
- **New `GET /clinics/{id}/assets/{asset_id}`** (one file with labels and review).
- **New filters** on `GET /clinics/{id}/assets`: `status`, `approval_state` (e.g. `submitted` = the
  review queue), `practitioner_id`, `category`. On `GET /clinics/{id}/approvals`: `resource_type`.

- **Clinic Administrators no longer decide any review** (decision D24): `approvals:decide` is gone
  from the role. Report outputs (`report_artifact`), assessments and clinic media are approved,
  rejected, retaken, published and handed off by the DSM / Platform Administrator only. For clinic
  people `available_actions` is now empty on every review except a draft of their own media.

Review notes:

- `POST …/approvals/actions`: `comment` is now an **internal note** (Radial Pulse staff only; clinic
  people get 403 when they send one). New **`clinic_message`**: the reason the clinic reads (allowed
  with approve / reject / redo only).
- `ApprovalRead.last_comment` is the latest internal note and is **always null for clinic people**.
  New `ApprovalRead.clinic_message`.
- Clinic people no longer see staff-only reviews (assessment reviews) in `GET …/approvals`, and
  `GET …/approvals/{id}` answers 404 for them.

Other security fixes:

- `GET /clinics/{id}/audit-events`: clinic people no longer see review activity (`approval.*`) or
  assessment events (decision D25).

- Report files (`kind = report`, or any file of an unpublished report) are hidden from clinic people
  in the asset list, the single GET and `download-url` until the report is published. Clinic people
  cannot upload `report` files (403).
- Upload size limits per file type: images 25 MB, audio 50 MB, documents 50 MB, video 200 MB.
  The size is signed into the presigned PUT URL: upload exactly `size_bytes` bytes.

## v0.1.1 — 2026-09-27

Additions only (nothing removed or renamed). Asked for by the frontend team.

- **Approvals:** every approval now carries `available_actions`: the actions the **caller** may take
  right now (state, permissions, staff-only assessments and "already published" all applied).
  Show buttons from it; do not repeat the rules in the app.
- **Clinic stage groups:** `GET /clinics?group=prospects|in_progress|active` filters by Admin tab
  (D5: Prospects = stages 1-2, In Progress = 3-4, Active = 5), and every clinic has `stage_group`.
  The tile counts are unchanged in `GET /dashboard/summary`.
- **`GET /assessments`** (new): the Audit Reports list across every clinic the caller may see, each
  row with `clinic_name` and `primary_practitioner_name`. Filters: `status`, `publication_state`,
  `clinic_id`. Same scope as `GET /clinics`; clinic users see PUBLISHED assessments only.
- **`GET /work-items`** (new): the work queue across clinics, each row with `clinic_name`.
  Filters: `status`, `owner_user_id`, `area`, `clinic_id`. Same scope as `GET /clinics`.
- Local CORS defaults now include `http://localhost:4200`.

## v0.1.0 — 2026-09-27

First versioned contract. Base path `/api/v1`, Bearer token from Cognito, errors are
problem+json (404 = no access to that clinic, 403 = not allowed, 409 = wrong state,
422 = invalid input, 502 = another platform refused, 503 = not set up yet).

**69 routes**, by screen area:

| Area | Routes |
|---|---|
| Me | `GET/PATCH /auth/me` (now with `avatar_url`, `sign_in_method`, `last_login_at`) |
| Settings → My Profile photo | `POST /auth/me/avatar/uploads` · `POST /auth/me/avatar/confirm` · `DELETE /auth/me/avatar` |
| Settings → Notifications | `GET/PUT /auth/me/notification-settings` |
| Settings → General / Integrations (Admin) | `GET/PATCH /settings/platform` · `GET /settings/integrations` |
| Dashboard | `GET /dashboard/summary` |
| Users (Admin) | `GET/POST /users` · `PATCH /users/{id}` · `POST /users/{id}/resend-invite` |
| Clinics | `GET/POST /clinics` · `GET/PATCH /clinics/{id}` · stage, stage history, archive/restore |
| DSM of a clinic (Admin) | `PUT/DELETE /clinics/{id}/assignment` · `GET /clinics/{id}/assignments` |
| Clinic team | `GET/POST /clinics/{id}/team` · `PATCH …/team/{id}` · `…/resend-invite` |
| Practitioners | `GET/POST /clinics/{id}/practitioners` · `PATCH …/{id}` (link a doctor of the same business with `practitioner_id`) |
| Clinic profile | `GET/PUT /clinics/{id}/profile` |
| Online presence | `GET/POST /clinics/{id}/presence-profiles` · `PATCH …/{id}` |
| **Connected accounts (new)** | `GET /clinics/{id}/connections` · `GET …/{platform}` · `POST …/{platform}/start` · `POST …/{platform}/complete` · `POST …/{platform}/disconnect` |
| Numbers (Social Media, charts) | `GET/POST /clinics/{id}/snapshots` (`value_number`; new `latest=true`) |
| Assessments | `GET/POST /clinics/{id}/assessments` · `GET …/{id}` |
| Review & publish | `GET /clinics/{id}/approvals` · `GET …/{id}` · `POST …/approvals/actions` |
| Work items ("Fix Now") | `GET/POST /clinics/{id}/work-items` · `GET/PATCH …/{id}` |
| Reports | `GET/POST /clinics/{id}/reports` · `GET …/{id}` |
| Files | `POST /clinics/{id}/assets/uploads` · `…/{id}/confirm` · `GET …/assets` · `…/{id}/download-url` (new kind `chat_attachment`) |
| **Chat (new)** | `GET/POST /clinics/{id}/chat/messages` · `POST /clinics/{id}/chat/read` · `GET /chat/inbox` |
| Activity log | `GET /clinics/{id}/audit-events` |
| Notifications | `GET /notifications` · `POST /notifications/{id}/read` |

Not in v0.1.0 (planned for later versions): live chat push (WebSocket), a "Refresh data"
button for connected accounts, email copies of notifications, meetings and notes.
