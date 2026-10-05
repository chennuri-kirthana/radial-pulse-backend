# API contract changelog

What changed **for the screens** in each contract version. The full contract is
`openapi/openapi.json` (also attached to each GitHub Release). Version rules:
[docs/api/contract-versioning.md](../docs/api/contract-versioning.md).

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
