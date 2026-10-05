# Milestone 1 API — what changed for the screens

Owner: Person 1 · For: Person 2 (web/mobile) · 26 Sep 2026 · **updated 27 Sep** (see section 7)

All routes are under `/api/v1` and need `Authorization: Bearer <Cognito access token>`.
Errors are always problem+json: `{ "type", "title", "status", "detail" }`.
**404 = no access to that clinic (or it does not exist). 403 = you can see it but may not do this.
409 = not allowed in the current state (the `detail` says why, in plain words).**

After pulling this branch, regenerate the contract. The frontend repo then builds its typed
client from this file (how is up to Person 2).

```bash
make openapi            # writes openapi/openapi.json
```

---

## 1. Screens → routes

| Screen | Route(s) |
|---|---|
| Admin / DSM dashboard tiles + charts | `GET /dashboard/summary` |
| Clinics list (Admin) / My Clinics (DSM) | `GET /clinics?group=…&stage=…&dsm_user_id=…&unassigned=…&q=…&archived=…` |
| Audit Reports (all clinics) | `GET /assessments?status=…&publication_state=…&clinic_id=…` (v0.1.1) |
| DSM work queue (all clinics) | `GET /work-items?owner_user_id=…&status=…&area=…&clinic_id=…` (v0.1.1) |
| Add Clinic | `POST /clinics` |
| Clinic details header / edit | `GET /clinics/{id}`, `PATCH /clinics/{id}` |
| Stepper | `POST /clinics/{id}/stage`, `GET /clinics/{id}/stage-history` |
| "Not interested" / bring back | `POST /clinics/{id}/archive`, `POST /clinics/{id}/restore` |
| Assigned DSM dropdown + "Update Assignment" | `PUT /clinics/{id}/assignment`, `DELETE /clinics/{id}/assignment`, history: `GET /clinics/{id}/assignments` |
| Practitioners (was Doctors) | `GET/POST /clinics/{id}/practitioners`, `PATCH /clinics/{id}/practitioners/{pid}` |
| Clinic team: Clinic Administrators + staff (mobile Profile → Team Members) | `GET/POST /clinics/{id}/team`, `PATCH /clinics/{id}/team/{mid}`, `POST /clinics/{id}/team/{mid}/resend-invite` |
| Users screen | `GET /users`, `POST /users`, `PATCH /users/{id}`, `POST /users/{id}/resend-invite` |
| Settings → My Profile | `GET /auth/me`, `PATCH /auth/me` |
| Findings "Fix Now / In Progress / Mark Done" | `POST /clinics/{id}/work-items` (with `source_finding_id`), `PATCH …/work-items/{wid}` |
| Pending-work chips | included in each `GET /clinics` row (`open_work`) |

---

## 2. Clinic stages

5 steps. The API tells you the tab: every clinic has `stage_group`, and `GET /clinics?group=…`
filters by it (v0.1.1). Display labels are the frontend's (the values below are the contract).

| Value | Label | Admin tab (`stage_group`) |
|---|---|---|
| `prospective_client` | New lead | `prospects` |
| `profile_enriched` | Found online | `prospects` |
| `assessment_completed` | Report ready | `in_progress` |
| `client_discussion` | In talks | `in_progress` |
| `active_client` | Customer | `active` |

A clinic that says no is **archived** (`is_active: false`, `archived_reason`), it keeps its stage.

---

## 3. Routes in detail

### `GET /clinics` — list with filters

Query: `group` (an Admin tab: `prospects`, `in_progress`, `active`), `stage` (repeat for several:
`?stage=prospective_client&stage=profile_enriched`; with `group` too, only their overlap),
`dsm_user_id`, `unassigned=true`, `q` (clinic name, practitioner name or website),
`archived=true` (only archived; default shows only live clinics), `limit`, `offset`.

Each row = the clinic fields (below) **plus**:

```json
{
  "primary_practitioner_name": "Dr. Rahul Mehta",
  "dsm": { "id": "…", "full_name": "Priya Shah", "email": "priya@radialpulse.com" },
  "open_work": [
    { "area": "search_readiness", "open_count": 3 },
    { "area": "google_business_profile", "open_count": 2 }
  ]
}
```

`dsm` is `null` when nobody is assigned. Chip labels (SEO, GBP, Social, Profile…) are the frontend's;
the `area` values are the contract.

### Clinic object (`GET /clinics/{id}`, and inside lists)

```json
{
  "id": "…", "organization_id": "…", "name": "Smile Dental Care",
  "specialty": "General Dentistry, Implants", "description": "…", "email": "info@smiledentalcare.in",
  "phone": "+91 98765 43210", "website_url": "https://smiledentalcare.in",
  "address_line": "123 Health Street", "city": "Kakinada", "state": "Andhra Pradesh",
  "postal_code": "533001", "country": "IN",
  "latitude": 16.9891, "longitude": 82.2475, "cover_asset_id": null,
  "stage": "client_discussion", "stage_group": "in_progress", "stage_changed_at": "2026-09-26T05:00:00Z",
  "is_active": true, "archived_reason": null,
  "created_at": "…", "updated_at": "…"
}
```

### `POST /clinics` — add a clinic

Admin or DSM. A DSM who adds it becomes its DSM automatically. Starts at `prospective_client`.

```json
{ "name": "Smile Dental Care", "primary_practitioner_name": "Dr. Rahul Mehta",
  "website_url": "https://smiledentalcare.in", "city": "Kakinada",
  "latitude": 16.9891, "longitude": 82.2475 }
```

`latitude` and `longitude` must come together. `organization_id` = add as a branch of an existing business.

### `PATCH /clinics/{id}` — edit details

Admin, the clinic's DSM, or its Clinic Administrator. Any of: `name, specialty, description, email,
phone, website_url, address_line, city, state, postal_code, latitude, longitude, cover_asset_id`.
`cover_asset_id` must be an **uploaded `clinic_photo`** of this clinic. Stage and archiving are **not** here.

### `POST /clinics/{id}/stage` — move the stepper

Admin or the clinic's DSM only (clinic users get 403).

```json
{ "stage": "client_discussion", "note": "Met Dr. Rahul at the clinic" }
```

409 when: same stage · clinic archived · moving to `active_client` without an active Clinic Administrator
(add the doctor's login first).

### `GET /clinics/{id}/stage-history`

```json
[ { "id": "…", "from_stage": "prospective_client", "to_stage": "profile_enriched",
    "note": null, "changed_by_user_id": "…", "changed_at": "…" } ]
```

### `POST /clinics/{id}/archive` · `POST /clinics/{id}/restore`

Admin or DSM. Archive needs `{ "reason": "Not interested, has an agency" }` (3+ characters).
Returns the clinic. 409 if already archived / not archived.

### `PUT /clinics/{id}/assignment` — set the clinic's DSM

Platform Administrator only. `{ "user_id": "<DSM id>" }`. Replaces the current DSM (the old one keeps
a history row and loses access). The new DSM gets a notification. Same DSM again = no change (200).
`DELETE /clinics/{id}/assignment` = no DSM (404 if there was none).

### Practitioners

`POST /clinics/{id}/practitioners`

```json
{ "full_name": "Dr. Neha Gupta", "specialty": "Orthodontics", "bio": "…", "is_primary": true }
```

Setting `is_primary: true` makes this the clinic's main practitioner (the old main one is un-marked).
List returns the main one first.

**Same doctor at another branch (new):** a doctor belongs to the business, so a doctor already
added at Branch 1 can be linked to Branch 2 of the **same business** — send only their id:

```json
{ "practitioner_id": "<id from Branch 1's list>", "is_primary": false }
```

- 404 if that doctor belongs to another business (or does not exist) · 409 if already linked here.
- 409 when the `registration_number` is already used by another doctor of the same business; the
  message includes that doctor's id, so the screen can offer "link this doctor instead".
- Send **either** `full_name` (new doctor) **or** `practitioner_id` (link), not both.
- `PATCH …/practitioners/{pid}`: name/specialty/bio/… change the doctor **everywhere**;
  `is_primary` / `is_active` change only **this clinic's** link.
- Response shape is unchanged: `id` is the doctor, `clinic_id`/`is_primary`/`is_active` are this clinic's link.

### Clinic team

- `POST /clinics/{id}/team` `{ "email": "dr.rahul@gmail.com", "full_name": "Dr. Rahul Mehta" }` →
  adds a Clinic Administrator and **sends an invite email**. Allowed for Admin, DSM **and the clinic's
  own Clinic Administrator**. Send `"role": "clinic_team_member"` to add **clinic staff** instead
  (view-only, plus uploading photos/files).
- Row: `{ id, clinic_id, user_id, email, full_name, role, is_active, has_signed_in }`.
- `PATCH /clinics/{id}/team/{membership_id}` `{ "is_active": false }` — 409 if it would leave a
  **Customer** clinic with no Clinic Administrator.
- `POST /clinics/{id}/team/{membership_id}/resend-invite` → 204; 409 if they already signed in.
- Adding an email that already has an account at **another** clinic works (same person, new
  membership). Adding a Radial Pulse **staff** email → 409.

### Users (Platform Administrator)

- `GET /users?platform_role=digital_success_manager&is_active=true&q=priya`
  Row: `{ id, email, full_name, phone, platform_role, is_active, status, last_invited_at, last_login_at,
  created_at, assigned_clinic_count }` · `status` = `invited` | `active` | `deactivated`.
- `POST /users` `{ "email", "full_name", "phone", "platform_role" }` → sends the invite email.
- `PATCH /users/{id}` `{ "full_name"?, "phone"?, "is_active"? }` — you cannot deactivate yourself (409).
- `POST /users/{id}/resend-invite` → 204; 409 if they already signed in.

### My Profile

`PATCH /auth/me` `{ "full_name"?, "phone"? }` → returns the same shape as `GET /auth/me` (now with `phone`).

### Dashboard

`GET /dashboard/summary` (Admin: all clinics · DSM: their clinics · clinic users: 403)

```json
{
  "total_clinics": 128, "prospects": 38, "in_progress": 14, "active": 76, "archived": 5,
  "by_stage": [ { "stage": "prospective_client", "count": 20 }, … ],
  "new_clinics_by_month": [ { "month": "2026-04", "count": 9 }, … 6 months, oldest first ],
  "assessments_awaiting_review": 6,
  "open_work_items": 24
}
```

Archived clinics are **not** in the totals.

### Work items ("Fix Now")

`POST /clinics/{id}/work-items` with only `{ "source_finding_id": "<finding id>" }` copies the title,
suggested fix, area and finding code from the finding. 409 if that problem already has an open item.
New fields on every work item: `area`, `finding_code`, `source_finding_id`, `completed_at`.
`GET …/work-items?area=google_business_profile` filters by area.
Map the buttons: Fix Now = create · In Progress = `PATCH {status: "in_progress"}` · Mark Done = `PATCH {status: "done"}`.
Handing a work item or approval to someone who has **no access to this clinic** → **422**
("Assignee has no access to this clinic"); to a deactivated person → 404.

### Assessments

Unchanged routes. New rules: a Clinic Administrator **cannot** approve, reject or "redo" an assessment
(403), and each time a clinic person opens one it is written to the audit log.

---

## 4. Removed / renamed

| Before | Now |
|---|---|
| `/clinics/{id}/doctors…` | `/clinics/{id}/practitioners…` |
| permissions `doctors:read/write` | `practitioners:read/write` |
| asset kind `doctor_photo` | `practitioner_photo` |
| `POST /clinics/{id}/assignments` + `DELETE …/assignments/{aid}` | `PUT` / `DELETE /clinics/{id}/assignment` |
| `PATCH /clinics/{id}` with `is_active` | `POST /clinics/{id}/archive` / `restore` |
| — | new permission `clinics:manage` (stages, archive) |

---

## 5. Every route (full list, 71 — contract v0.1.1)

All paths are under `/api/v1`. `{id}` is the clinic id.
For any `/clinics/{id}/…` route: **no access to the clinic → 404**, **access but missing
permission → 403**.

| Method | Path | Who may call it | What it does |
|---|---|---|---|
| GET | `/auth/me` | signed in | Who am I, and what can I do? |
| PATCH | `/auth/me` | signed in | Update my own name and phone (Settings → My Profile) |
| GET | `/clinics` | signed in | Clinics the caller may see, with filters (the Clinics / My Client Portfolio table) |
| POST | `/clinics` | `clinics:create` | Add a clinic (a lead) |
| GET | `/clinics/{id}` | `clinics:read` |  |
| PATCH | `/clinics/{id}` | `clinics:write` | Edit clinic details |
| GET | `/clinics/{id}/approvals` | `clinics:read` | Each row carries `available_actions` for the caller. Filters `state`, `resource_type`. Clinic people never see staff-only (assessment) reviews or internal notes |
| POST | `/clinics/{id}/approvals/actions` | `clinics:read` + the action's own permission (e.g. `approvals:publish`; clinic media: `media:upload` / `media:review`) | submit / approve / reject / redo (= request retake) / publish / handoff. `comment` = internal note (staff only); `clinic_message` = what the clinic reads |
| GET | `/clinics/{id}/approvals/{approval_id}` | `clinics:read` |  |
| POST | `/clinics/{id}/archive` | `clinics:manage` | Archive the clinic (e.g. it said no). A reason is required |
| GET | `/clinics/{id}/assessments` | `assessments:read` | Clinic users only see PUBLISHED assessments |
| POST | `/clinics/{id}/assessments` | `assessments:request` | Start a Digital Presence Assessment (runs in the background) |
| GET | `/clinics/{id}/assessments/{assessment_id}` | `assessments:read` | Full assessment: score, components, findings |
| GET | `/clinics/{id}/assets` | `assets:read` | Filters `kind`, `status`, `approval_state`, `practitioner_id`, `category`. Clinic people never see unpublished report files |
| POST | `/clinics/{id}/assets/uploads` | `assets:upload` (+ `media:upload` for clinic media, `reports:write` for report files) | Step 1: get a presigned URL to upload a file directly to S3 |
| POST | `/clinics/{id}/assets/{asset_id}/confirm` | `assets:upload` (+ as above) | Step 3: confirm the upload finished (API verifies the object in S3). Clinic media is submitted for review here |
| GET | `/clinics/{id}/assets/{asset_id}` | `assets:read` | One file with its labels and review |
| GET | `/clinics/{id}/assets/{asset_id}/download-url` | `assets:read` |  |
| GET | `/media/taxonomy` | signed in | Media labels: photo categories, doctor-photo apron / angle / outfit, voice samples |
| DELETE | `/clinics/{id}/assignment` | `assignments:manage` | Leave the clinic without a DSM |
| PUT | `/clinics/{id}/assignment` | `assignments:manage` |  |
| GET | `/clinics/{id}/assignments` | `clinics:read` | The clinic's DSM now (is_active=true) and before (history) |
| GET | `/clinics/{id}/audit-events` | `audit_log:read` | Who did what in this clinic (append-only) |
| GET | `/clinics/{id}/practitioners` | `practitioners:read` | Practitioners (main one first) |
| POST | `/clinics/{id}/practitioners` | `practitioners:write` |  |
| PATCH | `/clinics/{id}/practitioners/{practitioner_id}` | `practitioners:write` |  |
| GET | `/clinics/{id}/presence-profiles` | `presence:read` |  |
| POST | `/clinics/{id}/presence-profiles` | `presence:write` |  |
| PATCH | `/clinics/{id}/presence-profiles/{profile_id}` | `presence:write` | Confirm/reject a found profile |
| GET | `/clinics/{id}/profile` | `profile:read` | Client context: brand, audience, services, ... |
| PUT | `/clinics/{id}/profile` | `profile:write` |  |
| GET | `/clinics/{id}/reports` | `reports:read` | Clinic users only see PUBLISHED reports |
| POST | `/clinics/{id}/reports` | `reports:write` | Register a report version |
| GET | `/clinics/{id}/reports/{report_id}` | `reports:read` |  |
| POST | `/clinics/{id}/restore` | `clinics:manage` | Bring an archived clinic back |
| GET | `/clinics/{id}/snapshots` | `snapshots:read` |  |
| POST | `/clinics/{id}/snapshots` | `snapshots:write` | Ingest normalized metric snapshots (source, freshness, error/retry state) |
| POST | `/clinics/{id}/stage` | `clinics:manage` | Move the clinic to a stage |
| GET | `/clinics/{id}/stage-history` | `clinics:manage` | Every stage move |
| GET | `/clinics/{id}/team` | `clinics:read` | Clinic-side people and roles |
| POST | `/clinics/{id}/team` | `team:manage` | Add a Clinic Administrator (sends an invite email) |
| PATCH | `/clinics/{id}/team/{membership_id}` | `team:manage` | Deactivate or reactivate a team member |
| POST | `/clinics/{id}/team/{membership_id}/resend-invite` | `team:manage` |  |
| GET | `/clinics/{id}/work-items` | `work_items:read` |  |
| POST | `/clinics/{id}/work-items` | `work_items:write` |  |
| GET | `/clinics/{id}/work-items/{work_item_id}` | `work_items:read` |  |
| PATCH | `/clinics/{id}/work-items/{work_item_id}` | `work_items:write` | Update status/owner (owner change = handoff) |
| GET | `/dashboard/summary` | staff only (Admin, DSM) | Dashboard tiles and charts (Admin: all clinics; DSM: their clinics) |
| GET | `/assessments` | signed in | Audit Reports across the caller's clinics (clinic users: PUBLISHED only) — v0.1.1 |
| GET | `/work-items` | signed in | Work queue across the caller's clinics — v0.1.1 |
| GET | `/notifications` | signed in | My in-app notifications |
| POST | `/notifications/{notification_id}/read` | signed in |  |
| GET | `/users` | `users:read` | Users screen (status + assigned clinic count) |
| POST | `/users` | `users:manage` |  |
| PATCH | `/users/{user_id}` | `users:manage` | Edit or deactivate a user |
| POST | `/users/{user_id}/resend-invite` | `users:manage` |  |
| POST | `/auth/me/avatar/uploads` | signed in | Profile photo step 1: upload address |
| POST | `/auth/me/avatar/confirm` | signed in | Profile photo step 2: use it |
| DELETE | `/auth/me/avatar` | signed in | Remove my photo |
| GET | `/auth/me/notification-settings` | signed in | My notification switches |
| PUT | `/auth/me/notification-settings` | signed in | Change some switches |
| GET | `/settings/platform` | signed in | Organization name, support contact, timezone, date format |
| PATCH | `/settings/platform` | `settings:manage` (Admin) | Change them |
| GET | `/settings/integrations` | `settings:manage` (Admin) | Which outside services are set up |
| GET | `/chat/inbox` | signed in | My chats with unread counts |
| GET | `/clinics/{id}/chat/messages` | `chat:read` | Messages (oldest first); `before` / `after` for paging and polling |
| POST | `/clinics/{id}/chat/messages` | `chat:write` | Send text and/or one attachment |
| POST | `/clinics/{id}/chat/read` | `chat:read` | Mark read |
| GET | `/clinics/{id}/connections` | `connections:read` | Every platform with its status |
| GET | `/clinics/{id}/connections/{platform}` | `connections:read` | One platform |
| POST | `/clinics/{id}/connections/{platform}/start` | `connections:manage` | Start Connect (returns the sign-in address) |
| POST | `/clinics/{id}/connections/{platform}/complete` | `connections:manage` | Finish Connect with code + state |
| POST | `/clinics/{id}/connections/{platform}/disconnect` | `connections:manage` | Disconnect, delete the stored tokens |

## 6. Who has which permission

| Permission | Platform Administrator | DSM (own clinics) | Clinic Administrator (own clinic) | Clinic Team Member (own clinic) |
|---|---|---|---|---|
| `clinics:create`, `users:read`, `users:manage`, `assignments:manage` | ✅ | only `clinics:create` | — | — |
| `clinics:read` | ✅ | ✅ | ✅ | ✅ |
| `clinics:write` (edit clinic details) | ✅ | ✅ | ✅ | — |
| `clinics:manage` (stages, archive) | ✅ | ✅ | — | — |
| `team:manage` (add Clinic Administrators / Team Members) | ✅ | ✅ | ✅ | — |
| `practitioners:read`, `profile:read`, `presence:read`, `assets:read` | ✅ | ✅ | ✅ | ✅ |
| `practitioners:write`, `profile:write`, `presence:write` | ✅ | ✅ | ✅ | — |
| `assets:upload` (files) | ✅ | ✅ | ✅ | ✅ |
| `media:upload` (clinic photos, doctor photos, voice samples for review) | — | — | ✅ | — |
| `media:review` (approve / reject / request retake of clinic media) | ✅ | ✅ | — | — |
| `assessments:read` | ✅ | ✅ | ✅ **published only** | ✅ **published only** |
| `assessments:request` | ✅ | ✅ | — | — |
| `approvals:submit`, `approvals:publish` | ✅ | ✅ | — | — |
| `approvals:decide` | ✅ | ✅ | — (decision D24) | — |
| `reports:read` | ✅ | ✅ | ✅ published only | ✅ published only |
| `reports:write`, `snapshots:write`, `work_items:write` | ✅ | ✅ | — | — |
| `work_items:read`, `snapshots:read` | ✅ | ✅ | ✅ | ✅ |
| `audit_log:read` (activity log) | ✅ | ✅ | ✅ without review (`approval.*`) and assessment events (D25) | — |
| `chat:read` | ✅ | ✅ | ✅ | ✅ |
| `chat:write` | ✅ | ✅ | ✅ | — (decision D18) |
| `connections:read` | ✅ | ✅ | ✅ | ✅ |
| `connections:manage` | ✅ | ✅ | ✅ | — |
| `settings:manage` (platform settings, integrations) | ✅ | — | — | — |

Frontends get the caller's exact permissions from `GET /auth/me`. Use them to show or hide
buttons only; the API always checks again.

---

## 7. Changes on 27 Sep (schema review fixes)

| What | Change for the screens |
|---|---|
| Doctors at several branches | `POST …/practitioners` accepts `practitioner_id` to link an existing doctor of the same business (section 3, Practitioners) |
| Metric numbers | Every snapshot now has `value_number` (e.g. `5432.0`), or `null` when the value is not a plain number (text, true/false, a link). Use it for charts instead of reading `value.value` |
| Search | `q` on `/clinics` and `/users` treats `%` and `_` as normal characters ("100%" finds "100% Smile" only) and stays fast with thousands of rows |
| Handoff | 422 when the new owner cannot see the clinic (was 404) |
| Team | An existing clinic user from another clinic can be added by email |

Nothing was removed or renamed. Regenerate the typed client after pulling (`value_number` and
`practitioner_id` are new fields).

---

## 8. Contract v0.1.0 (27 Sep): chat, connected accounts, settings

The first versioned contract. Chat: poll `GET …/chat/messages?after=<last id>` for new
messages. Connect: `…/start` returns the sign-in address; after the platform sends the clinic
back with `code` and `state`, call `…/complete`. Other changes:

- `GET /auth/me` adds `avatar_url`, `sign_in_method` (`google`), `last_login_at`.
- `GET /clinics/{id}/snapshots?latest=true` returns only the newest value of each metric.
- Asset kind `chat_attachment` (images and PDFs).
- `GET /health` adds `contract_version`.
- New error codes: **502** (a platform refused the Connect), **503** (that platform is not set up yet).

---

## 9. Contract v0.1.1 (27 Sep): answers to the frontend's questions

Additions only. See `openapi/CHANGELOG.md` for the list. In short:

- **`available_actions`** on every approval: the buttons to show *this* caller. Empty for a clinic
  person on an assessment (D15), empty for a Clinic Team Member, no `publish` once published.
- **`stage_group`** on every clinic and `GET /clinics?group=…`: the Admin tabs come from the API.
- **`GET /assessments`** and **`GET /work-items`**: lists across every clinic the caller may see
  (same rule as `GET /clinics`), with `clinic_name` on each row. Filter with `clinic_id`, `status`,
  and (`assessments`) `publication_state` or (`work-items`) `owner_user_id`, `area`.
- **Labels** (stage names, chip names, enum text) stay in the frontend. The enum values in the
  contract are the source of truth; the API does not send display text.
- **Metric keys** (`GET …/snapshots`): no catalogue yet. Keys are dotted and owned by the team that
  produces them (`gbp.*`, `site.*`, `instagram.*`); the data-sync jobs that fill them are not built.
  Today the contract guarantees only `source`, `metric_key`, `value`, `value_number`, `fetched_at`.
- **Posts / reels**: not in V1. Connected accounts ask for read-only insights; nothing stores posts.
