# Database schema review (Sep 2026)

Radial Pulse backend · 27 tables · reviewed after migration 0011 · fixes in migration **0012**

This review was done on the **real database**: all migrations were run on PostgreSQL 16, then the
live schema was checked (indexes, keys, delete rules, data types, CHECK rules, row-level security),
and the app code that uses each table was read.

**Short verdict:** the design is good. Every table has a primary key, the tenant rules (row-level
security, same-clinic links) are strong, and nothing is hard-deleted. The bugs found are the
kind that do not show up with 10 rows but hurt at 100,000 rows, or that let bad data in
through a side door. **8 bugs were fixed** in migration 0012. **5 smaller items** are left as
recommendations.

---

## 1. Bugs found and fixed (migration 0012)

| # | Severity | Bug | What could go wrong | Fix |
|---|---|---|---|---|
| B1 | **High** | `work_items.source_finding_id` had **no index** | Every assessment re-run deletes the old findings. For **each** deleted finding, PostgreSQL read the whole `work_items` table to clear the link. Measured: 300 findings, 200,000 work items → **5.9 seconds** | Index added → **18 ms** (330× faster) |
| B2 | Medium | 8 more links had no index: `assessment_findings.clinic_id`, `notifications.clinic_id`, `report_artifacts.assessment_id` / `.asset_id`, `chat_messages.attachment_asset_id`, `assets.previous_version_id`, `work_items.approval_id`, `clinics.cover_asset_id` | Deleting a clinic, or checking "is this file used anywhere?", reads whole tables | Indexes added. Most are **partial** (`WHERE … IS NOT NULL`) because most rows have no link, so they stay tiny |
| B3 | **High** | **Race condition:** "Run assessment" checked "is one already running?" and then inserted | Two clicks at the same moment both pass the check → two running assessments, or a crash (500) on the duplicate sequence number | Database rule: **one queued/running assessment per clinic** (partial unique index). The API now answers **409** instead of 500 |
| B4 | Medium | 10 **duplicate indexes** (e.g. `clinic_memberships(clinic_id)` next to the unique key `(clinic_id, user_id)`) | They add no speed (the bigger index already starts with the same column), but every insert and update must write them | Removed |
| B5 | Medium | Notifications index was `(user_id, read_at)`, but the bell list is "my notifications, **newest first**" | PostgreSQL sorted all of a person's notifications on every page load | New index `(user_id, created_at, id)` + a small one for **unread only** |
| B6 | Medium | Emails: the app lower-cases them, but the **database did not check it** | Any other path (a script, a seed, a future endpoint) could create `Priya@x.com` next to `priya@x.com` → two accounts for one person, and sign-in finds the wrong one | CHECK `email = lower(trim(email))`. Existing emails are fixed automatically |
| B7 | Low | Country code accepted any 2 characters (`"I1"`, `"in"`) | Wrong country filters and reports | API checks two letters and upper-cases; database CHECK `^[A-Z]{2}$` |
| B8 | Medium | Numbers and dates had **no range rules** in the database | A bug could save a score of 150, a negative file size, "finished before started", or a "done" task with no finish date | 21 CHECK rules (next table) |

### The CHECK rules added (B8)

| Table | Rule |
|---|---|
| assessments | `sequence >= 1`, `overall_score` 0 to 100, `completed_at >= started_at` |
| assessment_components | `score` 0 to 100 |
| presence_profiles | `confidence` 0 to 1 |
| clinics | latitude −90 to 90, longitude −180 to 180, country = 2 upper-case letters |
| assets | `size_bytes >= 0`, `version >= 1`, a file is not its own previous version |
| report_artifacts, clinic_profiles | `version >= 1` |
| background_jobs | `attempts >= 0`, `max_attempts >= 1`, `finished_at >= started_at` |
| metric_snapshots | `retry_count >= 0` |
| consent_records | `revoked_at >= granted_at` |
| clinic_stage_history | a stage move must change the stage |
| work_items | status **done** ⇔ `completed_at` is set |
| users | email is lower-case and trimmed |

Every rule is something the app **already does**. The database now guarantees it, so a bug or a
script cannot break it. (A CHECK with an empty value passes: "no score yet" is still allowed.)

---

## 2. How the migration treats existing data

1. **Fixes what is safe automatically:** lower-cases emails (unless that would clash with another
   account), upper-cases countries, fills `completed_at` for done work items and clears it on the others.
2. **Stops with a clear list** for anything it cannot fix safely, for example:
   ```
   Migration 0012 stopped; fix these rows first:
     1 row(s) in users break ck_users_email_lowercase: email = lower(trim(email))
     1 row(s) in assessments break ck_assessments_score_range: overall_score BETWEEN 0 AND 100
     1 clinic(s) have more than one queued/running assessment — mark the extras failed
   ```
3. **Downgrade** removes everything and restores the old indexes.

---

## 3. How it was tested (PostgreSQL 16)

| Test | Result |
|---|---|
| Upgrade 0011 → 0012 on a database with bad old rows | fixable rows fixed; the rest listed; migration stopped ✔ |
| Upgrade after cleaning | ✔ |
| 13 bad writes (upper-case email, `in`, latitude 95, 2nd running assessment, score 101, sequence 0, finished before started, done without date, date without done, same-stage move, size −1, version 0 …) | all **refused** ✔ |
| Good writes (done + date, reopen, real coordinates, first stage row, next assessment after the first finished) | all **accepted** ✔ |
| Speed: re-run deletes 300 findings with 200,000 work items | 5,910 ms → **18 ms** ✔ |
| Notification lists use the new indexes (EXPLAIN) | ✔ |
| Every link (except "who did it" links to users) has an index starting with it | ✔ (0 missing) |
| No single-column index duplicates a bigger one | ✔ (0 left) |
| Model indexes and CHECK rules = database (autogenerate will not see a difference) | ✔ |
| Downgrade, then upgrade again | ✔ |

New automatic tests (run them locally, see section 6):
- `tests/unit/test_schema_review.py`: fails if a **future** table adds a link without an index,
  or a duplicate index; checks the running-assessment rule, `completed_at`, and the country format.
- `tests/integration/test_schema_rules.py` (PostgreSQL): the database refuses a 2nd running
  assessment, impossible values and upper-case emails.

---

## 4. Checked and found OK (no change)

- **Primary keys:** all 27 tables. **Same-clinic links:** composite foreign keys since 0011.
- **Row-level security:** on every table, and the app uses its own role (`radial_app`), so the
  rules really apply (a table owner would skip them).
- **Delete rules:** clinic delete cascades cleanly, even with chat attachments and cover photos (tested).
- **Money/score types:** `numeric(5,2)` for scores, `numeric(9,6)` for coordinates: exact, no float errors.
- **Times:** every timestamp is `timestamptz` (time zone safe).
- **Secrets:** tokens are in AWS Secrets Manager, not in the database; the OAuth
  `code_verifier` is cleared right after the callback.

---

## 5. Recommendations (not changed now)

| # | Item | Why it was left |
|---|---|---|
| R1 | `updated_at` is set by the app only. A database trigger would also cover raw SQL updates | Changes behaviour of every table; do it together with a full test run |
| R2 | Primary keys have no database default. Adding `DEFAULT gen_random_uuid()` makes scripts and seeds easier | Not a bug; the app always sets the id |
| R3 | The worker may **claim a job that is already running** (SQS can deliver a message twice). A `locked_until` column (a lease) would stop two workers running the same job | Worker logic change; needs its own tests |
| R4 | "Who did it" links to `users` (`created_by_user_id`, …) have no index | Users are never hard-deleted, so nothing scans them. Add an index only when a screen filters by one |
| R5 | `ix_audit_events_action` is not used by any query today | Kept for audit searches the Admin may need; drop it if it stays unused |
| R6 | Indexes on big tables in production should be built with `CREATE INDEX CONCURRENTLY` | Tables are still small (not live yet), so a normal migration is fine now |

---

## 6. What to run on your machine

```
make migrate            # applies 0012
make check              # lint, types, unit + API tests (SQLite)
make integration-test   # PostgreSQL tests, including test_schema_rules.py
```

---

## 7. Files changed

| File | Change |
|---|---|
| `alembic/versions/20260928_0012_schema_review_fixes.py` | the migration (new) |
| `app/models/*.py` (12 files) | same indexes and CHECK rules as the migration; `WorkItem` keeps `completed_at` in step with the status |
| `app/services/assessments.py` | two requests at once → 409, not 500 |
| `app/schemas/common.py`, `app/schemas/clinics.py` | `CountryCode` type (two letters, upper-case) |
| `tests/unit/test_schema_review.py`, `tests/integration/test_schema_rules.py` | new tests |
| `docs/architecture/schema-review-2026-09.md` | this report |
| `README.md`, `AGENTS.md`, `docs/architecture/decisions.md` | migration list, rules, decision 24 |
