# How the backend must use the database

Everything here was tested against `db/schema-v15.sql` on PostgreSQL 16.

## 1. Two database logins
| Login | Used by | Owns tables? | Access rules apply? |
|---|---|---|---|
| owner (e.g. `radial_owner`) | Alembic migrations only | yes | no (owner skips them) |
| app (e.g. `radial_api`) | the API and jobs | **no** | yes, via `SET LOCAL ROLE radial_app` |

```sql
-- once, by the owner/admin (names are examples)
CREATE ROLE radial_api LOGIN PASSWORD '…' IN ROLE radial_app;
```
The schema file creates the group roles `radial_app` and `radial_service` and all permissions.

## 2. Every request: one transaction
```python
# SQLAlchemy 2 (sketch)
with Session(engine) as s, s.begin():
    s.execute(text("SET LOCAL ROLE radial_app"))
    s.execute(text("SELECT set_config('rp.user_id', :uid, true)"), {"uid": str(user_id)})
    ...  # all queries for this request
```
- `set_config(name, value, true)` is the same as `SET LOCAL` and is safe with parameters.
- **Never** plain `SET` (it would stay on the pooled connection for the next user).
- Background job: `set_config('rp.actor', 'system', true)` instead of the user id.
- `radial_service` (read only) is used by this backend's `/api/v1/internal/*` routes (other teams' backends):
  those requests run `SET LOCAL ROLE radial_service` instead of `radial_app`, and set no `rp.user_id`.

## 3. Login (every request with a user token)
1. Verify the Cognito **access** token: signature (JWKS), issuer, expiry, `token_use = access`, `client_id`.
2. `SELECT id, platform_role, is_active FROM rp_user_for_login(:sub, :email)` (works before `rp.user_id` is set).
3. No row or `is_active = false` → 403 `account_disabled`. Otherwise set `rp.user_id = id`.

## 4. Things the database does by itself (don't duplicate in code)
| Automatic | Trigger / rule |
|---|---|
| `updated_at` on every update | `rp_set_updated_at` |
| stage history row when `clinics.stage` changes (who = `rp.user_id`, note = `rp.stage_note`) | `rp_record_stage_change` |
| cleaning profile URLs | `rp_clean_url` |
| refusing a practice-start / established year in the future, an unknown time zone (v15) | `rp_year_not_in_future`, `rp_check_time_zone` |
| refusing a `consultation_hours` value that isn't the per-day shape (v15) | CHECK using `rp_valid_consultation_hours` |
| photos stop being live when a practitioner link becomes inactive | `rp_inactive_practitioner_photos` |
| refusing: wrong login type in a link, role change while linked, assignee outside the clinic, removing the last Clinic Administrator, editing the audit log, clinic staff approving photos, non-staff moving stages | triggers (error code `check_violation` / `insufficient_privilege`) |

## 5. Specific flows
- **Move a stage:** `set_config('rp.stage_note', :note, true)`, then `UPDATE clinics SET stage = :stage`.
- **Archive:** `UPDATE clinics SET is_active = false, archived_reason = :reason`. **Restore:** `is_active = true, archived_reason = NULL`.
- **Approve a replacement photo:** same transaction: old live photo → `rejected` + note `Replaced by a newer photo` + `reviewed_at = now()`; then new photo → `approved` + `reviewed_at = now()`.
- **Review:** always set `reviewed_at = now()` when approving or rejecting (required by a CHECK rule). Reject needs a non-empty note.
- **Publish a report:** only when `review_state = 'approved'`; set `published_at`.
- **Upload (photos, voice, chat attachments):** 1) insert the row (`processing_status = 'uploading'`), 2) return a presigned S3 upload with the key `clinics/<clinic_id>/photos/<photo_id>.<ext>` (or `/voice/`), 3) on "complete", check the object exists, then mark `processing`/`ready`.
- **View a file:** presigned GET valid ~5 minutes + one `audit_events` row (action `photo.viewed` etc.). No download endpoint.
- **Audit:** in the same transaction as each change, insert into `audit_events` (`actor_user_id`, `actor_type = 'user'|'system'|'service'`, `action` like `photo.approved`, `resource_type`, `resource_id`, `request_id`).
- **OAuth connect:** store only `sha256(state)` in `oauth_states.state_hash`, expire after 10 minutes, delete after use; tokens go to Secrets Manager (`secret_ref`).
- **Remove a user:** deactivate (`is_active = false`). Deleting is refused while they are linked.

## 6. Error mapping
See the table in `CLAUDE.md`. Always the Problem JSON body with `code` and `request_id`.

## 7. Tests that must always pass
- `db/tests/01-rules-tests.sql` then `02-rules-tests-more.sql` on a fresh database.
- `03-review-cases.sql` on a fresh database + `db/seed-family-dental-v15.sql`.
- `04-access-rules-tests.sql` on **another** fresh database + seed (03 changes data).
- `05-doctor-profile-tests.sql` on **another** fresh database + seed.
Port them to pytest early (each "expect ERROR / OK" line becomes an assertion).
