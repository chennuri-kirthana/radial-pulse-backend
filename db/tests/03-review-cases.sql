-- Review cases R1-R8, M7, L2 (run on a v15 database AFTER seed-family-dental-v15.sql, as the owner).
\set ON_ERROR_STOP 0
\echo R1 assign a work item to a user from another clinic (expect ERROR)
INSERT INTO users(id,email,platform_role) VALUES ('00000000-0000-0000-0000-00000000ab01','stranger@other.in','clinic_member');
UPDATE improvement_work_items SET assignee_user_id='00000000-0000-0000-0000-00000000ab01';
\echo R1b assign to the Clinic Administrator (expect OK) and to the practitioner login (expect OK)
UPDATE improvement_work_items SET assignee_user_id='00000000-0000-0000-0000-00000000aa03' RETURNING 'ok admin' AS r;
UPDATE improvement_work_items SET assignee_user_id='00000000-0000-0000-0000-00000000aa04' RETURNING 'ok practitioner' AS r;
\echo R2 edit / delete / truncate an audit row (expect 3 ERRORS)
UPDATE audit_events SET action='edited';
DELETE FROM audit_events;
TRUNCATE audit_events;
\echo R3 updated_at changes by itself (expect true)
SELECT updated_at AS before FROM clinics LIMIT 1 \gset
BEGIN; UPDATE clinics SET name=name||''; COMMIT;
SELECT (updated_at > :'before') AS updated_at_changed FROM clinics LIMIT 1;
\echo R4 stage history with a wrong stage (expect ERROR)
INSERT INTO clinic_stage_changes(clinic_id,from_stage,to_stage) SELECT id,'foo','bar' FROM clinics LIMIT 1;
\echo R5 history written automatically and matches the clinic (expect 3 rows, last = active_client, with who)
SELECT from_stage, to_stage, note, changed_by_user_id IS NOT NULL AS has_who FROM clinic_stage_changes ORDER BY changed_at;
SELECT c.stage = (SELECT to_stage FROM clinic_stage_changes s WHERE s.clinic_id=c.id ORDER BY changed_at DESC LIMIT 1) AS matches FROM clinics c;
\echo R6 hard-delete the DSM user (expect ERROR) / deactivate instead (expect OK)
DELETE FROM users WHERE id='00000000-0000-0000-0000-00000000aa02';
UPDATE users SET is_active=false WHERE id='00000000-0000-0000-0000-00000000aa02' RETURNING 'deactivated' AS r;
\echo R7 remove the only Clinic Administrator (expect ERROR, fixed in v13)
BEGIN; DELETE FROM clinic_members WHERE role='clinic_administrator'; SELECT count(*) AS admins_left FROM clinic_members; ROLLBACK;
\echo R8 same profile with trailing slash (expect ERROR as duplicate, fixed in v13)
BEGIN; INSERT INTO clinic_online_profiles(clinic_id,platform,url,discovered_by) SELECT id,'instagram','https://instagram.com/familydental_amd/','x' FROM clinics LIMIT 1 RETURNING 'accepted' AS r8; ROLLBACK;
\echo M7 approve a photo without reviewed_at (expect ERROR)
UPDATE photos SET review_state='approved' WHERE review_state='pending';
\echo L2 restore a clinic but keep the reason (expect ERROR) / archive with reason then restore and clear (expect OK)
BEGIN;
UPDATE clinics SET is_active=false, archived_reason='not interested';
UPDATE clinics SET is_active=true;
ROLLBACK;
BEGIN;
UPDATE clinics SET is_active=false, archived_reason='not interested';
UPDATE clinics SET is_active=true, archived_reason=NULL RETURNING 'restored' AS r;
ROLLBACK;
