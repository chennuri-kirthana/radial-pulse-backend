-- Access-rule tests for schema v14. Run on a v15 database AFTER seed-family-dental-v15.sql, as the owner.
\set ON_ERROR_STOP 1
-- second business, its DSM and clinic admin; a team member at Family Dental; an unpublished report
INSERT INTO users (id,email,full_name,platform_role) VALUES
 ('00000000-0000-0000-0000-00000000aa05','priya@radialpulse.in','Priya (other DSM)','digital_success_manager'),
 ('00000000-0000-0000-0000-00000000aa06','kiran@smilecare.example','Kiran (other clinic admin)','clinic_member'),
 ('00000000-0000-0000-0000-00000000aa07','sita@familydental.example','Sita (team member)','clinic_member');
INSERT INTO client_organizations (id,name) VALUES ('00000000-0000-0000-0000-00000000bb02','SmileCare LLP');
INSERT INTO clinics (id,client_organization_id,name) VALUES ('00000000-0000-0000-0000-00000000cc02','00000000-0000-0000-0000-00000000bb02','SmileCare Satellite');
INSERT INTO portfolio_allocations (client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-00000000bb02','00000000-0000-0000-0000-00000000aa05');
INSERT INTO clinic_members (clinic_id,user_id,role) VALUES
 ('00000000-0000-0000-0000-00000000cc02','00000000-0000-0000-0000-00000000aa06','clinic_administrator'),
 ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa07','clinic_team_member');
INSERT INTO collaboration_messages (clinic_id,sender_user_id,sender_name,sender_side,body)
VALUES ('00000000-0000-0000-0000-00000000cc02','00000000-0000-0000-0000-00000000aa06','Kiran','clinic','SmileCare private message');
INSERT INTO digital_presence_assessments (id,clinic_id,status) VALUES ('00000000-0000-0000-0000-00000000ee02','00000000-0000-0000-0000-00000000cc01','completed');
INSERT INTO client_organizations (id,name) VALUES ('00000000-0000-0000-0000-00000000bb03','New Lead Clinic Pvt');  -- no DSM yet

\set ON_ERROR_STOP 0
\pset footer off
-- what each person can SEE (rows visible in each table)
CREATE OR REPLACE FUNCTION pg_temp.seen() RETURNS TABLE(clinics bigint, orgs bigint, users bigint, members bigint, pracs bigint,
  reports bigint, work bigint, msgs bigint, photos bigint, voice bigint, conn bigint, audit bigint, stage_hist bigint, alloc bigint)
LANGUAGE sql AS $$ SELECT (SELECT count(*) FROM clinics),(SELECT count(*) FROM client_organizations),(SELECT count(*) FROM users),
 (SELECT count(*) FROM clinic_members),(SELECT count(*) FROM practitioners),(SELECT count(*) FROM digital_presence_assessments),
 (SELECT count(*) FROM improvement_work_items),(SELECT count(*) FROM collaboration_messages),(SELECT count(*) FROM photos),
 (SELECT count(*) FROM voice_samples),(SELECT count(*) FROM connected_accounts),(SELECT count(*) FROM audit_events),
 (SELECT count(*) FROM clinic_stage_changes),(SELECT count(*) FROM portfolio_allocations) $$;
GRANT EXECUTE ON FUNCTION pg_temp.seen() TO radial_app;

\echo '== VISIBILITY (rows each person sees)'
SET ROLE radial_app;
SET rp.user_id = '00000000-0000-0000-0000-00000000aa01'; SELECT 'admin Anil' who, * FROM pg_temp.seen();
SET rp.user_id = '00000000-0000-0000-0000-00000000aa02'; SELECT 'DSM Ravi (Family Dental)' who, * FROM pg_temp.seen();
SET rp.user_id = '00000000-0000-0000-0000-00000000aa05'; SELECT 'DSM Priya (SmileCare)' who, * FROM pg_temp.seen();
SET rp.user_id = '00000000-0000-0000-0000-00000000aa03'; SELECT 'clinic admin Mehul' who, * FROM pg_temp.seen();
SET rp.user_id = '00000000-0000-0000-0000-00000000aa07'; SELECT 'team member Sita' who, * FROM pg_temp.seen();
SET rp.user_id = '00000000-0000-0000-0000-00000000aa04'; SELECT 'practitioner Pooja' who, * FROM pg_temp.seen();
SET rp.user_id = '00000000-0000-0000-0000-00000000aa06'; SELECT 'other clinic admin Kiran' who, * FROM pg_temp.seen();
RESET rp.user_id; SELECT 'nobody (no user set)' who, * FROM pg_temp.seen();
RESET ROLE;

\echo '== WRITES'
SET ROLE radial_app;
\echo W1 Kiran (other clinic) edits Family Dental (expect 0 rows)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa06';
UPDATE clinics SET name='hacked' WHERE id='00000000-0000-0000-0000-00000000cc01';
\echo W2 Mehul (clinic admin) edits his clinic name (expect UPDATE 1) / moves its stage (expect ERROR)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa03';
UPDATE clinics SET phone='+91 79 4000 9999' WHERE id='00000000-0000-0000-0000-00000000cc01';
UPDATE clinics SET stage='client_discussion' WHERE id='00000000-0000-0000-0000-00000000cc01';
\echo W3 H5 Mehul edits the SHARED practitioner bio (expect 0 rows) / Pooja edits her own bio (expect 1) / Pooja edits her registration number (expect ERROR)
UPDATE practitioners SET bio='changed by clinic admin' WHERE id='00000000-0000-0000-0000-00000000dd01';
SET rp.user_id = '00000000-0000-0000-0000-00000000aa04';
UPDATE practitioners SET bio='Updated by Dr Pooja' WHERE id='00000000-0000-0000-0000-00000000dd01';
UPDATE practitioners SET registration_number='X-1' WHERE id='00000000-0000-0000-0000-00000000dd01';
\echo W4 Ravi (DSM) edits the practitioner name (expect 1)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa02';
UPDATE practitioners SET full_name='Dr. Pooja Shah' WHERE id='00000000-0000-0000-0000-00000000dd01';
\echo W5 Mehul approves a photo himself (expect ERROR) / Ravi approves it (expect 1)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa03';
UPDATE photos SET review_state='approved', reviewed_at=now() WHERE review_state='pending';
SET rp.user_id = '00000000-0000-0000-0000-00000000aa02';
UPDATE photos SET review_state='approved', reviewed_at=now() WHERE review_state='pending';
\echo W6 Ravi (DSM) uploads a photo (expect ERROR) / Sita (team member) uploads (expect ERROR) / Pooja uploads her own (expect 1)
INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes)
 VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000dd01','with_apron',1,'left_45','clinics/00000000-0000-0000-0000-00000000cc01/photos/d1.jpg','image/jpeg',10);
SET rp.user_id = '00000000-0000-0000-0000-00000000aa07';
INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes)
 VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000dd01','with_apron',1,'left_45','clinics/00000000-0000-0000-0000-00000000cc01/photos/d2.jpg','image/jpeg',10);
SET rp.user_id = '00000000-0000-0000-0000-00000000aa04';
INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes)
 VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000dd01','with_apron',1,'left_45','clinics/00000000-0000-0000-0000-00000000cc01/photos/d3.jpg','image/jpeg',10);
\echo W7 Sita (team member) sends a message (expect ERROR) / Pooja sends (expect 1) / Pooja sends as Ravi (expect ERROR)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa07';
INSERT INTO collaboration_messages(clinic_id,sender_user_id,sender_name,sender_side,body) VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa07','Sita','clinic','hi');
SET rp.user_id = '00000000-0000-0000-0000-00000000aa04';
INSERT INTO collaboration_messages(clinic_id,sender_user_id,sender_name,sender_side,body) VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa04','Dr Pooja','clinic','hello');
INSERT INTO collaboration_messages(clinic_id,sender_user_id,sender_name,sender_side,body) VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa02','Ravi','radial_pulse','fake');
\echo W8 Mehul makes himself Platform Administrator (expect ERROR)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa03';
UPDATE users SET platform_role='platform_administrator' WHERE id='00000000-0000-0000-0000-00000000aa03';
\echo W9 Ravi (DSM) allocates himself SmileCare (expect ERROR)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa02';
INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-00000000bb02','00000000-0000-0000-0000-00000000aa02');
\echo W10 anyone edits the audit log (expect ERROR, permission)
UPDATE audit_events SET action='x';
\echo W11 Ravi (DSM) writes stage history directly (expect ERROR, permission) / moves the stage (expect 1, history written)
INSERT INTO clinic_stage_changes(clinic_id,to_stage) VALUES ('00000000-0000-0000-0000-00000000cc01','client_discussion');
UPDATE clinics SET stage='client_discussion' WHERE id='00000000-0000-0000-0000-00000000cc01';
SELECT to_stage, changed_by_user_id = '00000000-0000-0000-0000-00000000aa02' AS by_ravi FROM clinic_stage_changes ORDER BY changed_at DESC LIMIT 1;
\echo W12 Mehul removes himself, the last Clinic Administrator (expect ERROR)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa03';
DELETE FROM clinic_members WHERE user_id='00000000-0000-0000-0000-00000000aa03';
\echo W13 Mehul adds the same Instagram with www, http and a trailing slash (expect ERROR, duplicate after cleaning)
INSERT INTO clinic_online_profiles(clinic_id,platform,url,discovered_by) VALUES ('00000000-0000-0000-0000-00000000cc01','instagram','http://WWW.Instagram.com/familydental_amd/','manual');
\echo W14 Ravi assigns work to Kiran from the other clinic (expect ERROR)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa02';
UPDATE improvement_work_items SET assignee_user_id='00000000-0000-0000-0000-00000000aa06';
\echo W15 Ravi (DSM) creates a new lead (expect ERROR) / Anil (admin) creates one (expect OK)
INSERT INTO client_organizations(id,name) VALUES ('00000000-0000-0000-0000-00000000bb04','Lead by Ravi');
SET rp.user_id = '00000000-0000-0000-0000-00000000aa01';
INSERT INTO client_organizations(id,name) VALUES ('00000000-0000-0000-0000-00000000bb04','Lead by Anil') RETURNING name;
INSERT INTO clinics(id,client_organization_id,name) VALUES ('00000000-0000-0000-0000-00000000cc04','00000000-0000-0000-0000-00000000bb04','Lead clinic') RETURNING name;
\echo W16 who sees the unallocated leads (expect admin 2 orgs + 1 clinic, DSMs 0)
SELECT 'admin' who, (SELECT count(*) FROM client_organizations WHERE id IN ('00000000-0000-0000-0000-00000000bb03','00000000-0000-0000-0000-00000000bb04')) orgs, (SELECT count(*) FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc04') clinics;
SET rp.user_id = '00000000-0000-0000-0000-00000000aa02';
SELECT 'DSM Ravi' who, (SELECT count(*) FROM client_organizations WHERE id IN ('00000000-0000-0000-0000-00000000bb03','00000000-0000-0000-0000-00000000bb04')) orgs, (SELECT count(*) FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc04') clinics;
SET rp.user_id = '00000000-0000-0000-0000-00000000aa05';
SELECT 'DSM Priya' who, (SELECT count(*) FROM client_organizations WHERE id IN ('00000000-0000-0000-0000-00000000bb03','00000000-0000-0000-0000-00000000bb04')) orgs, (SELECT count(*) FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc04') clinics;
\echo W17 admin allocates the lead to Ravi; now Ravi sees it (expect 1 org, 1 clinic)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa01';
INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-00000000bb04','00000000-0000-0000-0000-00000000aa02');
SET rp.user_id = '00000000-0000-0000-0000-00000000aa02';
SELECT 'DSM Ravi after allocation' who, (SELECT count(*) FROM client_organizations WHERE id='00000000-0000-0000-0000-00000000bb04') orgs, (SELECT count(*) FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc04') clinics;
RESET ROLE;
\echo '== FIRST SIGN-IN (rp_user_for_login)'
INSERT INTO users(id,email,platform_role) VALUES ('00000000-0000-0000-0000-00000000aa08','newadmin@familydental.example','clinic_member');
SET ROLE radial_app; RESET rp.user_id;
SELECT 'first login' AS step, * FROM rp_user_for_login('sub-new','NewAdmin@FamilyDental.example');
SELECT 'second login' AS step, * FROM rp_user_for_login('sub-new','anything');
SELECT 'unknown' AS step, count(*) FROM rp_user_for_login('sub-x','nobody@x.in');
RESET ROLE;
\echo '== SERVICE (radial_service, read only)'
SET ROLE radial_service;
SELECT (SELECT count(*) FROM clinics) clinics, (SELECT count(*) FROM photos) approved_photos, (SELECT count(*) FROM clinic_online_profiles) profiles;
SELECT secret_ref FROM connected_accounts;
SELECT count(*) FROM users;
UPDATE clinics SET name='x';
RESET ROLE;
\echo '== L4 practitioner link inactive -> his approved photos stop being live'
SELECT review_state, count(*) FROM photos WHERE practitioner_id='00000000-0000-0000-0000-00000000dd01' GROUP BY 1 ORDER BY 1;
UPDATE clinic_practitioners SET is_active=false WHERE practitioner_id='00000000-0000-0000-0000-00000000dd01';
SELECT review_state, review_note, count(*) FROM photos WHERE practitioner_id='00000000-0000-0000-0000-00000000dd01' GROUP BY 1,2 ORDER BY 1;
\echo '== M5 cleaned URLs'
SELECT url FROM clinic_online_profiles ORDER BY url;
\echo '== M4 deleting the whole clinic still works (expect DELETE 1)'
BEGIN; DELETE FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc02'; ROLLBACK;
