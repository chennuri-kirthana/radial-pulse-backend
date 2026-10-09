# Product decisions already made

These are final unless I say otherwise. If code would contradict one, stop and ask.
Database: `db/schema-v15.sql` (22 tables). Every decision below is already built into it.

## 1. Login and roles
- Login = **Amazon Cognito, email + password**. The web/mobile app talks to Cognito directly; our API only verifies the access token.
- **Invite-only:** a `users` row is created first (by an admin, DSM or Clinic Administrator). On first sign-in, `rp_user_for_login(sub, email)` links the Cognito `sub` to that row by email.
- `users.platform_role` decides the portal: `platform_administrator`, `digital_success_manager`, `clinic_member`, `practitioner`.
- A user's role can't change while they are linked to a clinic, portfolio or practitioner record (trigger). Remove the links first.
- Deleting a user who is still a clinic member or an allocated DSM is refused. **Deactivate** (`is_active = false`) instead.

## 2. Businesses and clinics
- **Client Organization** = the business; **clinics** = its branches (1 : N); `clinic_profiles` = 1 : 1 details of a clinic.
- 5 stages: `prospective_client` → `presence_discovered` → `assessment_completed` → `client_discussion` → `active_client`.
- Archive needs a reason; restore clears the reason and keeps the stage.
- **New leads (a business with no DSM yet) are created and seen ONLY by the Platform Administrator.**

## 3. Portfolio Allocation
- A **whole Client Organization** (all its clinics) is allocated to **one active DSM**. New branches are covered automatically.
- Only the Platform Administrator allocates. Past DSMs stay as inactive rows.

## 4. Clinic team
- Several **Clinic Administrators** per clinic are allowed (no "owner" flag). At least **one active** must remain (trigger).
- **Clinic Team Members are read-only.**

## 5. Practitioners
- **One shared record per practitioner** across all businesses (`practitioners`); linked to clinics via `clinic_practitioners` (M : N).
- Many practitioners per clinic are supported (the app shows one for now); one primary per clinic.
- Before creating one, staff look up by **registration number** (`rp_find_practitioner_by_registration`) and link the existing record.
- A practitioner may have their own login (`platform_role = 'practitioner'`). That login can never be a clinic member.
- Bio / qualifications / specialty edits go live **immediately** (no approval). Who may edit the shared record: the **practitioner himself, the DSM, the Platform Administrator**, not a Clinic Administrator. Name, registration number and login link: **DSM or Platform Administrator only**.

## 6. Photos
- **Practitioner photos:** attire (`with_apron` / `without_apron`) × `outfit_no` (app shows outfit 1) × 5 angles (`left_90`, `left_45`, `front`, `right_45`, `right_90`).
- **Hospital (clinic) photos:** categories `exterior_signage`, `reception_waiting`, `consult_procedure_rooms`, `equipment_facilities`, `team_at_work`, `logo`, `cover`. May be uploaded unsorted; the DSM sorts before approving.
- **Photos need approval by the DSM (or Platform Administrator).** Reject needs a note. `reviewed_at` is required once reviewed.
- Per slot: at most **1 live + 1 waiting** photo. Replace: the old photo stays live until the new one is approved. When the DSM approves the new one, in the **same transaction** first set the old one to `rejected` with note `Replaced by a newer photo`, then approve the new one (tested; the DSM is not allowed to delete photos).
- **Who uploads:** the Clinic Administrator, or the practitioner for **his own** photos. The DSM never uploads; team members can't.
- If a practitioner's link to a clinic becomes inactive, his approved photos there automatically stop being live (trigger).
- **AI photo pre-check (later):** Rekognition (face angle, sharpness, face count) + a vision model (apron) → result in `photos.check_results` as a **hint**. The DSM still decides.

## 7. Voice samples
- **No review.** A practitioner can't reuse a title at a clinic (case-insensitive). `reviewed_at` exists but is unused.

## 8. Digital Presence Assessments (reports)
- From the Digital Growth Team. DSM review: `draft`, `submitted`, `approved`, `rejected`, `redo_requested`.
- **Published only if approved.** Clinic people and practitioners see **published reports only**.
- One report queued/running per clinic. Listed newest first by `created_at` (no sequence number).

## 9. Improvement Work Items
- Minimal: title, description, status, priority, due date, assignee.
- "Fix Now" item = `source_assessment_id` filled **and** `opportunity_code` required. One **open** item per opportunity per clinic.
- The assignee must belong to the clinic (member, linked practitioner, its DSM, or a Platform Administrator).

## 10. Client Collaboration (chat)
- `collaboration_messages`: text and/or one attachment (image/PDF), replies **one level deep**.
- **No unread counts** (no read-marker table). Team members can read but not send.

## 11. Connected accounts
- The clinic connects its own Google / Instagram / Facebook / LinkedIn / X with OAuth (PKCE; `state` stored only as a hash; expires in 10 minutes).
- Tokens live in **AWS Secrets Manager**; the database stores only `secret_ref`.
- One login can manage several locations/sites; each location can be selected by **only one clinic**.

## 12. Other
- Notifications: in-app + email; each person switches categories on/off.
- `audit_events`: insert-only record of who did what.
- Profile URLs are cleaned before saving (https, lower-case host, no `www.`, no trailing `/`).

## 14. Practitioner profile (v15, decided 8 Oct)
Screen "Practitioner Profile" → database:
| Screen | Column |
|---|---|
| Practitioner full name / Specialization / Qualifications | `practitioners.full_name` / `specialty` / `qualifications` |
| Total years of medical experience | **computed**: current year − `practitioners.practice_start_year` (never stored) |
| "Client organization information": name / Operating since / Address | the **clinic's** `clinics.name` / `established_year` / `address_line, city, state, postal_code` (label stays "Client organization information"; data is the clinic's) |
| Consultation schedule (Mon–Sun) | `clinic_practitioners.consultation_hours` |
| Time zone / Schedule notes | `clinic_practitioners.consultation_time_zone` (default `Asia/Kolkata`) / `schedule_notes` |
| Weekly holiday | `clinic_practitioners.weekly_off_days` (e.g. `{sun}`) |
| Consultation fee | `clinic_practitioners.consultation_fee` + `consultation_fee_currency` (default `INR`) |
| Main services / conditions treated | `practitioners.services_and_conditions` (list) |
| Approximate patients treated / Professional highlights | `practitioners.approx_patients_treated` / `highlights` |
| Empty value | show "Not provided" |

- Fee, schedule, holiday, time zone, notes are **per clinic** (`clinic_practitioners`): one doctor can have different ones at each clinic.
- `consultation_hours` has ONE shape: `{"mon":[{"from":"10:00","to":"14:00"}], …, "sun":[]}`. Keys `mon`…`sun`;
  missing day or `[]` = "No consultation"; slots `HH:MM` 24-hour, `from` < `to`, several per day allowed. The database refuses anything else.
- Years can't be in the future; time zone must be a real one (database triggers).

## 13. Deliberately NOT done now (don't build unless asked)
- Deleting S3 files when rows are deleted (needs API + nightly job + bucket lifecycle rules).
- Similar-name search / merge for duplicate practitioners without a registration number.
- Allowed-value lists for `audit_events.actor_type`, `notifications.category`, `clinic_online_profiles.discovered_by`.
- Audit log retention / partitioning.
