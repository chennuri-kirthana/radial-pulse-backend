# Radial Pulse — Database Schema (Milestone 1)

Owner: Person 1 (Backend / Data) · Status: **v1.1 for Milestone 1** (next: mentor review) · 27 Sep 2026

> **v1.1 (27 Sep):** the weak spots from the schema review are fixed in migrations
> **0007–0009**. What changed is in [section 12](#12-changes-after-the-schema-review-migrations-00070009).

This is the full PostgreSQL schema for the Central platform. It **builds on the 20 tables
already in the repo** (migrations 0001–0004). Nothing is rebuilt from scratch.

Tag on every table:

- **KEEP** = already in the repo, no change
- **CHANGE** = already in the repo, a few columns added or renamed
- **NEW** = a new table

Columns marked **NEW** are the ones this design adds.

---

## 0. Decisions this schema is built on

"You" = decided by you. "Default" = you had no preference, so the recommended option was used.
Any of these can still be changed before the migrations are written.

| # | Topic | Decision | By |
|---|---|---|---|
| D1 | Clinic stages | **5 stages**, as in the screen design: New lead → Found online → Report ready → In talks → Customer. Leads are given to us; we only assign and work them. A clinic that says no is **archived** with a reason (no extra stage). See section 4 | You |
| D2 | DSMs per clinic | **Exactly one active DSM per clinic** (option A). The Admin can swap them | You |
| D3 | What is a "Client Organization"? | The **business** that owns one or more clinics. Already built as `organizations` | Default |
| D4 | New names in the database | `doctors` → **`practitioners`** everywhere. `clinic_id` is **not** renamed (row-level security depends on it) | Default |
| D5 | Admin screen tabs | **Prospects** = stages 1–2 · **In Progress** = stages 3–4 · **Active** = stage 5. Archived clinics are hidden (an "Archived" filter shows them) | Default |
| D6 | Who moves stages | The Admin or the clinic's DSM, **by hand**. No automatic moves in Milestone 1 | Default |
| D7 | Becoming a Customer | Only after the clinic has **at least one Clinic Administrator** (app login) | Default |
| D8 | Improvement Opportunity | = an **assessment finding** (a problem + its suggested fix + proof). No separate table | Default |
| D9 | Improvement Work Item | = a **work item**. Its status (To do / In progress / Done) lives here, **not** on the finding, so a re-assessment never wipes out progress | Earlier decision |
| D10 | Deleting | Nothing is hard-deleted. People and clinics are **deactivated** (`is_active = false`) | Default |
| D11 | Not in Milestone 1 | Chat, connected accounts, meetings/notes, staff profile photo. Outlined in section 9 | Default |
| D12 | How doctors log in | **Google only** (what is built today). No passwords, no email codes in Milestone 1 | You |
| D13 | Invites | An **automatic invite email** goes out when someone is added, and can be resent (`users.last_invited_at`) | You |
| D14 | Clinic Administrator adding people | **Yes:** a Clinic Administrator can add **other Clinic Administrators** to their own clinic(s). Staff (Team Member) logins come later | You |
| D15 | Who approves a report before the clinic sees it | **The clinic's DSM alone** (checks, approves, publishes). Who did it is recorded | You |
| D17 | Weak spots fixed (review, 27 Sep) | **#1** people tables under RLS · **#3** old rows archived to S3 · **#4** metric numbers in a real column · **#5** a doctor can work at several branches of the same business · **#6** fast, safe search · **#7** report status kept in step by the database. See section 12 | You |
| D18 | Chat, connected accounts, settings (27 Sep) | **Built** in migration 0010 (contract v0.1.0): `chat_messages`, `chat_read_states`, `platform_connections` (tokens in Secrets Manager), `platform_settings`, `notification_preferences`, `users.avatar_key`. Clinic Team Members read the chat but do not send. See section 13 | You |
| D16 | Clinic Team Member (clinic staff) | **Built:** view-only in their own clinic (details, doctors, online links, published reports, tasks, numbers) plus uploading photos/files. No editing, adding people, approving or activity log. Added by the Admin, the DSM or a Clinic Administrator | You |

---

## 1. The big picture

```
                         ┌──────────────┐
                         │    users     │  every login (staff + clinic people)
                         └──────┬───────┘
          ┌─────────────────────┼──────────────────────┐
          │ (DSM)               │ (Clinic Admin)       │
          ▼                     ▼                      │
 ┌──────────────────┐  ┌──────────────────┐            │
 │clinic_assignments│  │clinic_memberships│            │
 │ DSM ↔ clinic     │  │ clinic person ↔  │            │
 │ (1 DSM / clinic) │  │ clinic + role    │            │
 └────────┬─────────┘  └────────┬─────────┘            │
          └──────────┬──────────┘                      │
                     ▼                                 │
 ┌──────────────┐  ┌──────────────────────────────┐    │
 │organizations │─<│ clinics  (THE TENANT)        │    │
 │ the business │  │ + stage (client journey)     │    │
 └──────────────┘  └──────────────┬───────────────┘    │
                                  │ everything below has clinic_id
                                  │ and is protected by row-level security
     ┌──────────────┬─────────────┼───────────────┬──────────────┬──────────────┐
     ▼              ▼             ▼               ▼              ▼              ▼
 clinic_        clinic_stage_  clinic_profiles  presence_     assessments    work_items
 practitioners  history (NEW)  consent_records  profiles      └ components   approvals
                                                metric_        └ findings    assets
                                                snapshots                    report_artifacts
                                                                             background_jobs
                                                                             audit_events
```

Total: **22 tables** (20 existing + `clinic_stage_history` + `clinic_practitioners`).
`practitioners` (the doctor as a person) belongs to the **business** (`organizations`);
`clinic_practitioners` links a doctor to each clinic (branch) they work at.

---

## 2. Rules every table follows

1. **Ids** are UUIDs: a long random code like `3f2b8c1e-9a4d-…` instead of 1, 2, 3.
   They can't be guessed from a URL and can be created by the app without asking the database.
2. **Times** are stored in UTC (`timestamptz`). Screens show them in IST.
3. **Fixed lists** (roles, stages, statuses) are stored as text with a CHECK rule, not as
   PostgreSQL enum types. Adding a value = one small migration that updates the CHECK.
4. **Tenant key:** every clinic table has `clinic_id`. PostgreSQL row-level security (RLS)
   hides other clinics' rows from the app, even if a query forgets `WHERE clinic_id = …`.
5. **The app never logs in as the database owner.** API and worker use the `radial_app` role
   (read/write data only). Only migrations run as the owner.
6. **No hard deletes.** Use `is_active = false`. History stays complete.
7. **Every change writes one `audit_events` row** (who, what, when, which clinic).
   The app role cannot edit or delete audit rows.
8. **Who did it:** most tables have `created_by_user_id` / `updated_by_user_id` style columns.
   If that user is removed, the column becomes empty (the audit log still has it).

---

## 3. Tables

### A. People and access

#### `users` — CHANGE
Every login: Platform Administrators, Digital Success Managers, and clinic people.
A user is **not** a practitioner and **not** a clinic.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| email | text(320), unique | always lower-case; used to link the Google/email login on first sign-in |
| full_name | text(200) | |
| **phone** | text(32) | **NEW** — Settings screen |
| cognito_sub | text(64), unique | empty until the person signs in for the first time |
| platform_role | text | `platform_administrator` · `digital_success_manager` · `clinic_user` |
| is_active | bool | false = deactivated, cannot sign in |
| **last_invited_at** | timestamptz | **NEW** — when the last invite email went out (for "Resend invite") |
| last_login_at | timestamptz | |
| created_by_user_id | → users | |
| created_at, updated_at | timestamptz | |

User status shown on the Users screen is **worked out, not stored**:
`is_active = false` → *Deactivated* · no `cognito_sub` yet → *Invited* · otherwise → *Active*.

#### `organizations` — KEEP
The **Client Organization**: the business that owns one or more clinics (branches).
Created automatically when a clinic is added, so nobody has to manage it in V1.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text(200) | |
| created_by_user_id | → users | |
| created_at, updated_at | timestamptz | |

#### `clinics` — CHANGE (the tenant)
One clinic / branch. Almost every other table points here.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| organization_id | → organizations | required |
| name | text(200) | |
| **specialty** | text(200) | **NEW** — e.g. "General Dentistry, Implants" |
| **description** | text | **NEW** — short description (the starting input for enrichment) |
| **email** | text(320) | **NEW** |
| phone | text(32) | |
| website_url | text(500) | |
| address_line, city, state, postal_code | text | |
| country | text(2) | default `IN` |
| **latitude, longitude** | numeric(9,6) | **NEW** — the map pin |
| **cover_asset_id** | → assets | **NEW** — the clinic photo in the header |
| **stage** | text | **NEW** — where the clinic is in the client journey (section 4). Default `prospective_client` |
| **stage_changed_at** | timestamptz | **NEW** — "in this stage for 5 days" |
| is_active | bool | false = **archived** (e.g. the clinic said no). Not the same as the "Customer" stage |
| **archived_reason** | text | **NEW** — **required** when the clinic is archived, e.g. "Not interested, has an agency" |
| created_by_user_id | → users | |
| created_at, updated_at | timestamptz | |

#### `clinic_memberships` — KEEP
A **clinic-side** person and their role inside one clinic.
A Clinic Administrator with 3 branches has 3 rows.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | → clinics | |
| user_id | → users | |
| role | text | `clinic_administrator` · `clinic_team_member` (clinic staff: view-only + upload photos/files) |
| is_active | bool | |
| invited_by_user_id | → users | |
| created_at, updated_at | timestamptz | |

One row per (clinic, user).

#### `clinic_assignments` — CHANGE (Portfolio Allocation)
A **Digital Success Manager** allocated to a clinic.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | → clinics | |
| user_id | → users | must be a DSM |
| is_active | bool | true = this DSM looks after the clinic now. **Only one active row per clinic** (**NEW** unique index). false = a past allocation, kept for history |
| assigned_by_user_id | → users | |
| created_at, updated_at | timestamptz | |

Rules:
- A clinic has **at most one** active DSM at a time. The database refuses a second one.
- "Update Assignment" on the admin screen = in one step, end the current row
  (`is_active = false`) and add (or re-activate) the new DSM's row.
- A DSM who adds a clinic is its DSM automatically.
- Old rows are never deleted, so we can see who looked after the clinic before.

#### `practitioners` — CHANGE (renamed from `doctors`; split in 0008)
A doctor or other practitioner **as a person**, owned by the business. A record, not a login.
One doctor = one row, even if they work at three branches.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| **organization_id** | → organizations | **NEW (0008)** — the business the doctor belongs to |
| full_name | text(200) | e.g. "Dr. Rahul Mehta". Trigram search index |
| specialty | text(120) | |
| qualifications | text(300) | |
| registration_number | text(64) | medical council number (optional) |
| **bio** | text | **NEW** — short description (input for enrichment) |
| user_id | → users | optional link if this practitioner also has a login |
| created_at, updated_at | timestamptz | |

#### `clinic_practitioners` — NEW (0008)
Which doctor works at which clinic (branch). Only doctors of the **same business** can be linked.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | → clinics | |
| practitioner_id | → practitioners | unique together with `clinic_id` |
| is_primary | bool | the "Doctor Name" shown in clinic lists. At most one **active** primary per clinic |
| is_active | bool | the doctor stopped working at this branch = `false` |
| created_at, updated_at | timestamptz | |

### B. Client journey

#### `clinic_stage_history` — NEW
One row every time a clinic moves stage. Powers the stepper and shows who moved the clinic, and when.
**Append-only**: the app can add rows but never change or delete them.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | → clinics | |
| from_stage | text | empty for the first row (clinic created) |
| to_stage | text | |
| note | text | optional, e.g. "Met Dr. Rahul at the clinic" |
| changed_by_user_id | → users | |
| changed_at | timestamptz | |

The clinic row keeps the **current** stage. This table keeps **all past** stages.

#### `clinic_profiles` — KEEP
The one governed place for brand, audience, services and schedule (JSON sections).
Other teams read it through the API. One row per clinic. Has a `version` number so two
people editing at once get a clear "someone else changed this" error.

Columns: `clinic_id` (primary key), `brand`, `audience`, `services`, `schedule` (JSON),
`version`, `updated_by_user_id`, `created_at`, `updated_at`.

#### `consent_records` — KEEP
What the clinic agreed to (e.g. "you may analyse our website", "you may use our photos").

Columns: `id`, `clinic_id`, `consent_type`, `granted`, `granted_by_user_id`, `granted_at`,
`revoked_at`, `evidence` (JSON), `created_at`, `updated_at`.

### C. Digital presence and assessment

#### `presence_profiles` — KEEP
Where the clinic is found online: website, GBP, Instagram, Facebook, YouTube, LinkedIn, X,
Practo, Justdial, other. One table for all platforms.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | → clinics | |
| platform | text | see list above |
| url | text(1000) | |
| external_id | text(255) | GBP place id, Instagram handle, … |
| display_name | text(255) | |
| verification | text | `unverified` · `confirmed` · `rejected`. Engines may **never** overwrite a person's confirm/reject |
| confidence | numeric(4,3) | 0–1, from the finder; empty when a person added it |
| discovered_by | text(128) | `user:<id>` or `service:<engine>` |
| evidence | JSON | why we think it is this clinic |
| verified_by_user_id | → users | |
| created_at, updated_at | timestamptz | |

One row per (clinic, platform, url).

#### `assessments` — KEEP (Digital Presence Assessment)
One run of the combined assessment for one clinic. "Re-run Audit" = a new row.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | → clinics | |
| sequence | int | 1, 2, 3… per clinic |
| status | text | `queued` · `running` · `completed` · `partial` · `failed` |
| methodology_version | text(32) | which scoring rules were used |
| overall_score | numeric(5,2) | 0–100. Empty if nothing could be scored |
| summary | text | |
| requested_by_user_id | → users | |
| started_at, completed_at | timestamptz | |
| approval_state | text | `draft` · `submitted` · `approved` · `rejected` · `redo_requested` |
| publication_state | text | `unpublished` · `published` · `retracted` |
| published_at | timestamptz | |
| created_at, updated_at | timestamptz | |

**The publication gate:** a Clinic Administrator sees an assessment **only** when
`publication_state = published`.

#### `assessment_components` — KEEP
The 6 fixed sections of every assessment.

Columns: `id`, `assessment_id`, `clinic_id`, `key`
(`website` · `google_business_profile` · `local_search` · `search_readiness` ·
`social_presence` · `competitor_benchmark`), `status` (`pending` · `completed` · `failed` ·
`not_available`), `score`, `summary`, `engine_name`, `engine_version`, `computed_at`,
`status_reason`, `created_at`, `updated_at`.

A section with no engine yet is `not_available`, with **no** score. We never invent a score.

#### `assessment_findings` — KEEP (Improvement Opportunities)
One problem found by an engine, with the suggested fix and the proof.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| assessment_id | → assessments | |
| component_id | → assessment_components | |
| clinic_id | → clinics | |
| code | text(96) | **stable** code, e.g. `gbp.description_missing_keywords`. The same problem has the same code in every re-assessment |
| title | text(200) | "GBP description needs improvement" |
| priority | text | `critical` · `high` · `medium` · `low` · `info` |
| description | text | |
| recommendation | text | the "Suggested Fix" |
| evidence | JSON | list of {source URL, short excerpt, provider, time seen}. **Required** for critical and high |
| created_at | timestamptz | |

No status column here, on purpose (see `work_items`).

#### `metric_snapshots` — KEEP
Numbers pulled from a source at a point in time: followers, likes, views, review count…
Powers Social Presence Insights and growth charts.

Columns: `id`, `clinic_id`, `source` (GBP, Search Console, website crawl, Instagram,
Facebook, YouTube, LinkedIn, manual), `metric_key` (e.g. `instagram.followers`), `value`
(JSON), `schema_version`, `fetched_at`, `status` (`ok` · `stale` · `error` · `pending`),
`error_code`, `error_message`, `retry_count`, `next_retry_at`, `ingested_by_user_id`, `created_at`.

### D. Work and review

#### `work_items` — CHANGE (Improvement Work Items)
A concrete piece of work that is assigned and tracked. This is where
**Fix Now → In Progress → Done** lives.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | → clinics | |
| kind | text(64) | team-defined type, e.g. `gbp_update` |
| title | text(200) | |
| description | text | |
| **area** | text | **NEW** — `website` · `google_business_profile` · `local_search` · `search_readiness` · `social_presence` · `competitor_benchmark` · `clinic_profile` · `other`. Powers the "SEO 3 · GBP 2" chips |
| **finding_code** | text(96) | **NEW** — the finding this work fixes (same code across re-assessments) |
| **source_finding_id** | → assessment_findings | **NEW** — the exact finding it was created from (optional) |
| status | text | `todo` · `in_progress` · `blocked` · `in_review` · `done` · `cancelled` |
| priority | text | `low` · `normal` · `high` · `urgent` |
| owner_user_id | → users | who is doing it |
| created_by_user_id | → users | |
| due_at | timestamptz | |
| **completed_at** | timestamptz | **NEW** — when it moved to done |
| approval_id | → approvals | if the result needs review |
| source_team | text(32) | `central` · `digital_growth` · … |
| created_at, updated_at | timestamptz | |

Rule: **one open work item per finding per clinic** (unique index on `clinic_id + finding_code`
while status is not done/cancelled). So a re-assessment that finds the same problem again
shows the **existing** work item and its progress, instead of creating a duplicate.

#### `approvals` — KEEP
One review record per reviewable thing (an assessment, a report file, an asset).

Columns: `id`, `clinic_id`, `resource_type`, `resource_id`, `state`, `publication_state`,
`submitted_by_user_id`, `decided_by_user_id`, `assignee_user_id`, `last_comment`,
`created_at`, `updated_at`. One row per (resource_type, resource_id).

#### `notifications` — KEEP
In-app messages for one user ("An assessment is ready for review").

Columns: `id`, `user_id`, `clinic_id`, `kind`, `title`, `body`, `link`, `created_at`, `read_at`.

### E. Files and background work

#### `assets` — KEEP (one value renamed)
Metadata for every file in S3 (photos, logos, documents, exported PDFs). The file itself is in S3.

Columns: `id`, `clinic_id`, `owner_user_id`, `kind`, `mime_type`, `size_bytes`, `storage_key`,
`original_filename`, `checksum_sha256`, `version`, `previous_version_id`, `provenance`,
`status`, `approval_state`, `created_at`, `updated_at`.

`kind` value `doctor_photo` is renamed to **`practitioner_photo`**.

#### `report_artifacts` — KEEP
A generated **file** (e.g. the PDF export of an assessment, a monthly progress report).
Not a separate kind of audit. The product report is always the assessment.

Columns: `id`, `clinic_id`, `report_type`, `report_key`, `version`, `title`, `provenance`,
`owner_user_id`, `assessment_id`, `asset_id`, `approval_state`, `publication_state`,
`published_at`, `created_at`, `updated_at`.

#### `background_jobs` — KEEP (one value added)
Record of slow work done by the worker. The queue message carries only ids.

Columns: `id`, `clinic_id`, `job_type`, `status`, `resource_type`, `resource_id`, `payload`,
`attempts`, `max_attempts`, `last_error`, `requested_by_user_id`, `started_at`, `finished_at`,
`created_at`, `updated_at`.

`job_type` gets a new value: **`presence.discover`** (the "Refresh Profile" button: the
Digital Presence Intelligence run on its own, without a full assessment).

### F. Audit

#### `audit_events` — KEEP (append-only)
One row per action. The app role can **only insert and read**. A trigger also blocks edits.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| occurred_at | timestamptz | |
| actor_user_id | → users | empty for system actions |
| actor_type | text | `user` or `service` |
| action | text | e.g. `clinic.create`, `clinic.stage_change`, `assignment.change`, `assessment.viewed` |
| resource_type, resource_id | text | |
| clinic_id | → clinics | empty for platform-level actions (e.g. creating a staff user) |
| request_id | text | ties the row to the API request log |
| details | JSON | small context only, never tokens or file contents |

What gets logged: **every change**, every **sign-in**, and every time a clinic person
**opens an assessment** (`assessment.viewed`). Plain page views are not logged.

---

## 4. Clinic stages (the client journey)

```
  1. New lead ──► 2. Found online ──► 3. Report ready ──► 4. In talks ──► 5. Customer

  Clinic says no (at any step)  ──►  archived with a reason  (can be brought back later)
```

| Stage (database name) | Plain name | What has happened | Admin screen tab |
|---|---|---|---|
| `prospective_client` | **New lead** | a clinic from the lead list we are given; nobody has worked on it yet | Prospects |
| `profile_enriched` | **Found online** | website / Google listing / social pages found and checked by the DSM | Prospects |
| `assessment_completed` | **Report ready** | the Digital Presence Assessment (score + findings) is done | In Progress |
| `client_discussion` | **In talks** | DSM is meeting the clinic (in person or Google Meet) about the report and the deal | In Progress |
| `active_client` | **Customer** | clinic said yes; the doctor has an app login (**Client Activation**) | Active |

These 5 steps are the stepper on the DSM's Clinic Details screen design
("Prospect → Profile Enriched → Audit Completed → Client Discussion → Client").

Rules:

1. Only the **Platform Administrator** and the clinic's **DSM** can change the stage.
2. In Milestone 1 all moves are **by hand** (the stepper). No automatic moves yet.
3. Moving to `active_client` needs **at least one active Clinic Administrator** on the clinic.
4. **Clinic says no:** the DSM or Admin archives it (`is_active = false`) and must give a reason.
   It keeps its stage and history, and can be brought back later.
5. Every move = one `clinic_stage_history` row + one `audit_events` row.

---

## 5. Where each screen gets its data

| Screen (mockup) | Tables |
|---|---|
| Admin dashboard tiles: Total / Active / Prospects / In Progress | `clinics.stage` (counted) |
| Admin "Clinic Growth Trend" | `clinics.created_at` (counted by month) |
| Admin "Key Highlights" (% with website, % with GBP, % with social) | `clinics.website_url`, `presence_profiles` |
| Clinics / My Clinics list: clinic, doctor, website, map, assigned user, status | `clinics`, `practitioners` (primary), `clinic_assignments` (the active one), `clinics.stage` |
| My Clinics "Pending Work" chips (SEO 3, GBP 2…) | `work_items` open, counted by `area` |
| Clinic details header | `clinics` + `cover_asset_id` → `assets` |
| Stepper (Prospect → … → Client) | `clinics.stage`, `clinic_stage_history` |
| Profile Enrichment panel: last enriched, sources found, completeness | `background_jobs` (`presence.discover`), `presence_profiles`, clinic fields filled in |
| Key Links (GBP, Justdial, Yellow Pages) | `presence_profiles` |
| Assessment: overall score, section scores, competitor score | `assessments`, `assessment_components` |
| Findings table: issue, priority, evidence, suggested fix | `assessment_findings` |
| Findings "Fix Now / In Progress / Mark Done" | `work_items` (matched by `finding_code`) |
| Social Media: followers, likes, views, growth chart | `metric_snapshots` |
| Audit Reports list | `assessments` (+ clinic, primary practitioner) |
| Users screen: role, status, assigned clinic count | `users`, `clinic_assignments` (counted) |
| Clinic app Home / Insights | `assessments` (**published only**), `assessment_findings` |
| Clinic app Reports (download) | `report_artifacts` (**published only**) → `assets` |
| Recent Activity feeds | `audit_events` |

---

## 6. Security: what is protected where

**Row-level security on every table (22 of 22)** since migration 0007.

Clinic tables (the database refuses other clinics' rows):
`clinics`, `clinic_practitioners`, `clinic_stage_history`, `clinic_profiles`,
`consent_records`, `assets`, `approvals`, `work_items`, `metric_snapshots`,
`report_artifacts`, `assessments`, `assessment_components`, `assessment_findings`,
`presence_profiles`, `background_jobs`, `audit_events`.

People tables (0007) follow **the signed-in person** (`app.user_id`) as well as the clinic scope:

| Table | The app can see a row when… |
|---|---|
| `users` | it is you · you created it · you are staff and it is a staff account · it has a membership or DSM assignment in one of your clinics · Platform Administrator (all) |
| `organizations` | it owns one of your clinics · you created it · all |
| `clinic_memberships`, `clinic_assignments` | the clinic is in your scope · or the row is about you |
| `notifications` | it is yours (or all) |
| `practitioners` | linked to one of your clinics · or the same business owns one of your clinics (so a sibling branch's doctor can be linked) |

Sign-in happens **before** the user is known, so two tiny `SECURITY DEFINER` lookups
(`rp_user_id_by_sub`, `rp_user_by_email`) return **only an id and a role**; everything else
is loaded after `app.user_id` is set. No DELETE policies anywhere (nothing is hard-deleted).

**Append-only** (the app can add, never change or delete):
`audit_events`, `clinic_stage_history`. Only exception: the monthly **archive job** (owner login,
`app.archiving = on`) may delete audit rows it has just copied to S3 (0009).

**Database roles:** owner (migrations only) · `radial_app` group (data only) with logins
`radial_api_iam`, `radial_worker_iam` (IAM auth in AWS) and `radial_app_local` (local dev).

---

## 7. Migration plan

Five new migrations on top of 0004. All have a working downgrade.

**0005 — new names**
- Rename table `doctors` → `practitioners` (its RLS policy moves with it).
- Rename asset kind `doctor_photo` → `practitioner_photo` (data + CHECK rule).

**0006 — Milestone 1 additions**
- `users`: add `phone`, `last_invited_at`.
- `clinics`: add `specialty`, `description`, `email`, `latitude`, `longitude`,
  `cover_asset_id`, `stage`, `stage_changed_at`, `archived_reason`.
  Existing clinics get `stage = prospective_client`.
- `clinic_assignments`: add a unique index (one **active** DSM per clinic).
  Existing clinics with more than one active DSM: the oldest stays active, the others are ended.
- `practitioners`: add `bio`, `is_primary` + unique index (one per clinic).
- `work_items`: add `area`, `finding_code`, `source_finding_id`, `completed_at` + unique
  index (one open item per finding code per clinic).
- `background_jobs`: allow job type `presence.discover`.
- New table `clinic_stage_history` with RLS and **insert/read only** for the app role.

**0007 — people tables under RLS (#1)**
- New settings `app.user_id`, `app.is_staff` + helpers `rp_user_id()`, `rp_is_staff()`.
- Policies on `users`, `organizations`, `clinic_memberships`, `clinic_assignments`, `notifications`.
- Sign-in lookups `rp_user_id_by_sub()`, `rp_user_by_email()` (return id + role only).

**0008 — a doctor at several branches (#5)**
- `practitioners.organization_id` (filled from the doctor's clinic).
- New `clinic_practitioners` (filled from the existing doctors), then `clinic_id`,
  `is_primary`, `is_active` move off `practitioners`.
- Downgrade: a doctor linked to 3 clinics becomes 3 rows again.

**0009 — search, numbers, status, archive (#6, #4, #7, #3)**
- `pg_trgm` + trigram indexes on clinic name, website, doctor name, user email and name.
- `metric_snapshots.value_number` (filled from `value->'value'` when it is a plain number).
- Deferred checks: a report/assessment/asset status copy must equal its `approvals` row at COMMIT.
- `audit_events` delete allowed only with `app.archiving = on` (the app role still has no DELETE).

---

## 8. Code changes that go with this schema (not schema, but needed)

1. **Publication gate fix:** a Clinic Administrator must **not** approve, reject or "redo" an
   **assessment**. Today they can (they hold `approvals:decide` with no limit on the type).
   Assessment review becomes staff-only.
2. Permission names `doctors:read/write` → `practitioners:read/write`; API path
   `/clinics/{id}/doctors` → `/clinics/{id}/practitioners`.
3. New API pieces: change stage, change a clinic's DSM, list clinics with filters (stage, assigned
   DSM, search by clinic / practitioner / website).
4. Update the TypeScript enum copies in `packages/shared-types` (the parity test will
   remind us).
5. **Clinic Administrators can add other Clinic Administrators** (D14): give them `team:manage`
   inside their own clinic(s) only. Rule: nobody can remove or deactivate a clinic's **last**
   active Clinic Administrator while the clinic is a Customer.
6. **Invite email** (D13): send it when a user or Clinic Administrator is added, and on
   "Resend invite". Sending the email needs Person 3 (Cognito or Amazon SES).

---

## 9. Later — outlined, not built in Milestone 1

| Feature | Plan |
|---|---|
| Meetings and notes | `client_meetings` (clinic, when, in person / Google Meet, notes, outcome) |
| Client decision per fix (Yes / Later / No) | extra columns on `work_items` (`client_decision`, `responsible_party` = our team or clinic) |
| Re-assessment every 1–2 weeks | a schedule that creates `background_jobs`; no new table |

---

## 10. What was checked

I loaded this schema into a real **PostgreSQL 16** (all 21 tables, RLS on 16) and ran these
checks **as the app role** (not the owner):

| Check | Result |
|---|---|
| No clinic scope set → app sees 0 clinics | ✅ |
| Scope = one clinic → only that clinic is visible | ✅ |
| Adding a practitioner to **another** clinic | ✅ refused by RLS |
| A second **active** DSM on the same clinic | ✅ refused |
| Swapping a clinic's DSM (end old, add new) | ✅ works; the old row is kept as history |
| A second **primary** practitioner on the same clinic | ✅ refused |
| A second **open** work item for the same finding | ✅ refused; allowed again once the first is done |
| A stage outside the 5 allowed | ✅ refused |
| Archiving a clinic **without a reason** | ✅ refused |
| Bringing an archived clinic back | ✅ works |
| App editing or deleting stage history / audit rows | ✅ refused |
| Clinic cover photo link (clinic ↔ asset) | ✅ works |

Not checked yet: the real Alembic migrations (not written yet) and the full test suite
(this session cannot download Python packages; run `make test` locally).

---

Migrations 0007–0009 were checked the same way on PostgreSQL 16 (upgrade, every rule
below, downgrade, upgrade again) — see section 12.

---

## 11. Next steps

1. **Mentor review** of this document.
2. **Write migrations** `0005` (new names) and `0006` (Milestone 1 additions), with working downgrades.
3. **Code changes** in section 8, including the publication-gate fix.
4. **Tests:** RLS tests for `clinic_stage_history`, and tests for the one-DSM, stage and work-item rules.
5. **Regenerate the API contract** so Person 2 can build the screens against it.

---

## 12. Changes after the schema review (migrations 0007–0009)

| # | Weak spot | Fix | Where |
|---|---|---|---|
| 1 | People tables (`users`, `organizations`, `clinic_memberships`, `clinic_assignments`, `notifications`) were protected by the app only | RLS on all of them, keyed on the signed-in person (`app.user_id`) + clinic scope. Every table now has RLS; a test fails if a new table forgets it | 0007, `app/db/tenant.py`, `app/services/identity.py` |
| 3 | `metric_snapshots` and `audit_events` grow forever | Monthly job copies old rows to S3 (gzip JSON lines, one folder per month) and only then deletes them. Metrics after 180 days, audit after 365 | 0009, `app/services/archiving.py`, `python -m app.cli archive-old-data`, [archiving guide](../infrastructure/archiving.md) |
| 4 | Metric numbers hidden inside JSON | `value_number` column, filled on every data pull and back-filled | 0009, `app/services/reporting.py` |
| 5 | A doctor could belong to only one clinic | `practitioners` = the person (per business); `clinic_practitioners` = which branches they work at. API: `POST …/practitioners` with `practitioner_id` links an existing doctor | 0008, `app/services/clinics.py` |
| 6 | Search `ILIKE '%x%'` = full table scan; `%` and `_` typed by users acted as wildcards | Trigram (GIN) indexes; user text is escaped | 0009, `app/repositories/users.py::like_pattern` |
| 7 | Review status stored twice (approvals + copy on the resource) could drift | The database refuses to COMMIT if a copy differs from its approval row (order inside the transaction does not matter) | 0009 |

### Checked on PostgreSQL 16 (as the app role)

| Check | Result |
|---|---|
| Clinic Admin sees only people linked to their clinic; DSM sees staff + their clinics' people | ✅ |
| Nobody (except all-clinics) can read another person's notifications | ✅ |
| Sign-in lookups work before the user is known and return only id + role | ✅ |
| Existing doctors keep their clinic after 0008; primary doctor kept | ✅ |
| Same doctor linked to two branches of one business | ✅ works |
| Linking a doctor of **another** business | ✅ refused |
| 0008 downgrade splits a shared doctor back into one row per clinic | ✅ |
| Metric back-fill: 5432 → 5432, `true` / text → empty | ✅ |
| `ILIKE '%smile%'` uses the trigram index (Bitmap Index Scan) | ✅ |
| Approval inserted as draft, then submitted with its copy, in one transaction | ✅ commits |
| Approve + publish (4 updates, any order) | ✅ commits |
| Changing only the copy (e.g. publishing without an approval) | ✅ refused at commit |
| Changing only the approval | ✅ refused at commit |
| Owner deleting audit rows **without** the archive flag | ✅ refused |
| App role deleting audit rows **with** the archive flag | ✅ refused (no permission) |
| 0009 downgrade, then upgrade again | ✅ |

### Needs to happen outside this repo

- **Person 3:** the S3 archive bucket, a write-only task role, the ECS task and the monthly
  schedule — step by step in [archiving.md](../infrastructure/archiving.md).
- `CREATE EXTENSION pg_trgm` needs `rds_superuser`; the Aurora master user that runs migrations has it.

---

## 13. Chat, connected accounts and settings (migration 0010)

Full design: [chat-connections-settings.md](chat-connections-settings.md). Total now **27 tables**.

| Table | What | Row-level security |
|---|---|---|
| `chat_messages` | one message: clinic, sender (+ name and side copied), text, attachment | clinic in scope; app login may only read and add |
| `chat_read_states` | "I have read this clinic's chat up to …" (unread counts) | clinic in scope **and** your own |
| `platform_connections` | a clinic's connected Instagram/Facebook/GBP/YouTube/LinkedIn/X; `secret_ref` points at Secrets Manager (no tokens in the database) | clinic in scope; no delete |
| `platform_settings` | exactly one row: organization name, support email/phone, timezone, date format | read: everyone · change: Platform Administrator |
| `notification_preferences` | a person's on/off switch per category and channel (no row = on) | your own |
| `users.avatar_key` | profile photo in S3 (`users/<id>/avatar/…`) | (users rules) |

Also: asset kind `chat_attachment`; function `rp_notification_enabled()` (answers true/false
so a notification can respect someone else's switch without reading their settings).

Checked on PostgreSQL 16 as the app login: other clinics' messages invisible; writing a message
into another clinic refused; editing or deleting messages refused (no permission); someone
else's read position or switches invisible and not writable; platform settings changed only
with the all-clinics scope; nothing visible with no scope; CHECK rules (text or attachment,
sender side, single settings row, one connection per clinic + platform); downgrade and upgrade again.

---

## 14. Composite keys (migration 0011)

- **Same-clinic links:** 9 links now use composite foreign keys, e.g.
  `assessment_findings (assessment_id, clinic_id) → assessments (id, clinic_id)`. Parents got the
  matching unique keys `(id, clinic_id)` / `(id, assessment_id)`.
- **Natural keys added:** `assessment_findings (component_id, code)` and `practitioners
  (organization_id, registration_number)` when the number is known. Adding a doctor with a number
  already used in the business → **409** with the existing doctor's id (link them instead).
- The migration stops with a clear list if existing rows break a rule (cross-clinic links,
  duplicate registration numbers); duplicate findings are cleaned automatically.

Full table-by-table keys and 1:1 / 1:N / M:N relationships: [database-relationships.md](database-relationships.md).
