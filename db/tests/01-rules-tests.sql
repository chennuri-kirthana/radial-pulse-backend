-- Rules tests 1-24 (run on an EMPTY v15 database, as the table owner). Each block says what to expect.
\set ON_ERROR_STOP 0
\set c '\'00000000-0000-0000-0000-0000000000c1\''
INSERT INTO users(id,email,platform_role) VALUES
 ('00000000-0000-0000-0000-0000000000a1','owner@x.in','clinic_member'),
 ('00000000-0000-0000-0000-0000000000a2','doc@x.in','practitioner'),
 ('00000000-0000-0000-0000-0000000000a3','admin2@x.in','clinic_member'),
 ('00000000-0000-0000-0000-0000000000a4','dsm@x.in','digital_success_manager');
INSERT INTO client_organizations(id,name) VALUES ('00000000-0000-0000-0000-0000000000b1','Org');
INSERT INTO clinics(id,client_organization_id,name) VALUES (:c,'00000000-0000-0000-0000-0000000000b1','Family Dental');
\echo T1 doctor with a doctor login (expect OK)
INSERT INTO practitioners(id,full_name,user_id) VALUES ('00000000-0000-0000-0000-0000000000d1','Dr Pooja','00000000-0000-0000-0000-0000000000a2');
\echo T2 doctor linked to a clinic_member login (expect ERROR)
INSERT INTO practitioners(id,full_name,user_id) VALUES ('00000000-0000-0000-0000-0000000000d2','Dr Two','00000000-0000-0000-0000-0000000000a1');
INSERT INTO practitioners(id,full_name) VALUES ('00000000-0000-0000-0000-0000000000d2','Dr Two');
INSERT INTO clinic_practitioners(clinic_id,practitioner_id,is_primary) VALUES (:c,'00000000-0000-0000-0000-0000000000d1',true);
\echo T3 Clinic Administrator (expect OK)
INSERT INTO clinic_members(clinic_id,user_id,role) VALUES (:c,'00000000-0000-0000-0000-0000000000a1','clinic_administrator');
\echo T4 second Clinic Administrator (expect OK - no owner flag any more, all admins equal)
INSERT INTO clinic_members(clinic_id,user_id,role) VALUES (:c,'00000000-0000-0000-0000-0000000000a3','clinic_administrator');
\echo T5 same member twice (expect ERROR, primary key)
INSERT INTO clinic_members(clinic_id,user_id,role) VALUES (:c,'00000000-0000-0000-0000-0000000000a1','clinic_team_member');
\echo T6 practitioner login as clinic member (expect ERROR)
INSERT INTO clinic_members(clinic_id,user_id,role) VALUES (:c,'00000000-0000-0000-0000-0000000000a2','clinic_administrator');
\echo T7 unknown member role (expect ERROR)
UPDATE clinic_members SET role='owner' WHERE user_id='00000000-0000-0000-0000-0000000000a1';
\echo T8 second doctor at clinic (expect OK)
INSERT INTO clinic_practitioners(clinic_id,practitioner_id) VALUES (:c,'00000000-0000-0000-0000-0000000000d2');
\echo T9 DSM assignment (expect OK) / clinic_member as DSM (expect ERROR)
INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-0000000000b1','00000000-0000-0000-0000-0000000000a4');
INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-0000000000b1','00000000-0000-0000-0000-0000000000a3');
\echo T10 archive clinic without reason (expect ERROR - was a bug)
UPDATE clinics SET is_active=false WHERE id=:c;
\echo T11 report published while draft (expect ERROR)
INSERT INTO digital_presence_assessments(id,clinic_id,status,publication_state,published_at) VALUES ('00000000-0000-0000-0000-000000000e01',:c,'completed','published',now());
\echo T12 approve then publish (expect OK)
INSERT INTO digital_presence_assessments(id,clinic_id,status) VALUES ('00000000-0000-0000-0000-000000000e01',:c,'completed');
UPDATE digital_presence_assessments SET review_state='approved', reviewed_at=now(), publication_state='published', published_at=now() WHERE id='00000000-0000-0000-0000-000000000e01';
\echo T13 un-approve a published report (expect ERROR)
UPDATE digital_presence_assessments SET review_state='redo_requested' WHERE id='00000000-0000-0000-0000-000000000e01';
\echo T14 Fix Now task from report of same clinic (expect OK)
INSERT INTO improvement_work_items(clinic_id,title,source_assessment_id,opportunity_code) VALUES (:c,'Fix title','00000000-0000-0000-0000-000000000e01','title_missing');
\echo T15 doctor photo approved (OK), second live same angle (ERROR), waiting replacement (OK)
INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes,review_state,reviewed_at)
 VALUES (:c,'00000000-0000-0000-0000-0000000000d1','with_apron',1,'front','clinics/00000000-0000-0000-0000-0000000000c1/photos/1.jpg','image/jpeg',100,'approved',now());
INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes,review_state,reviewed_at)
 VALUES (:c,'00000000-0000-0000-0000-0000000000d1','with_apron',1,'front','clinics/00000000-0000-0000-0000-0000000000c1/photos/2.jpg','image/jpeg',100,'approved',now());
INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes)
 VALUES (:c,'00000000-0000-0000-0000-0000000000d1','with_apron',1,'front','clinics/00000000-0000-0000-0000-0000000000c1/photos/3.jpg','image/jpeg',100);
\echo T16 doctor photo missing angle (expect ERROR)
INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,original_key,mime_type,size_bytes)
 VALUES (:c,'00000000-0000-0000-0000-0000000000d1','with_apron',1,'clinics/00000000-0000-0000-0000-0000000000c1/photos/4.jpg','image/jpeg',100);
\echo T17 unsorted hospital photo (OK), approve without category (ERROR), sort+approve (OK)
INSERT INTO photos(id,clinic_id,original_key,mime_type,size_bytes) VALUES ('00000000-0000-0000-0000-0000000000f1',:c,'clinics/00000000-0000-0000-0000-0000000000c1/photos/6.jpg','image/jpeg',100);
UPDATE photos SET review_state='approved', reviewed_at=now() WHERE id='00000000-0000-0000-0000-0000000000f1';
UPDATE photos SET category='reception_waiting', review_state='approved', reviewed_at=now() WHERE id='00000000-0000-0000-0000-0000000000f1';
\echo T18 second live cover (expect OK then ERROR)
INSERT INTO photos(clinic_id,category,original_key,mime_type,size_bytes,review_state,reviewed_at) VALUES (:c,'cover','clinics/00000000-0000-0000-0000-0000000000c1/photos/c1.jpg','image/jpeg',100,'approved',now());
INSERT INTO photos(clinic_id,category,original_key,mime_type,size_bytes,review_state,reviewed_at) VALUES (:c,'cover','clinics/00000000-0000-0000-0000-0000000000c1/photos/c2.jpg','image/jpeg',100,'approved',now());
\echo T19 reject photo without note (expect ERROR)
UPDATE photos SET review_state='rejected' WHERE id='00000000-0000-0000-0000-0000000000f1';
\echo T20 voice for doctor NOT at clinic (expect ERROR) / at clinic (OK) / duplicate title (ERROR)
INSERT INTO voice_samples(clinic_id,practitioner_id,title,original_key,mime_type,size_bytes) VALUES (:c,'00000000-0000-0000-0000-0000000000e9','X','clinics/00000000-0000-0000-0000-0000000000c1/voice/0.m4a','audio/mp4',100);
INSERT INTO voice_samples(clinic_id,practitioner_id,title,original_key,mime_type,size_bytes) VALUES (:c,'00000000-0000-0000-0000-0000000000d1','Reading sample 2','clinics/00000000-0000-0000-0000-0000000000c1/voice/1.m4a','audio/mp4',100);
INSERT INTO voice_samples(clinic_id,practitioner_id,title,original_key,mime_type,size_bytes) VALUES (:c,'00000000-0000-0000-0000-0000000000d1','reading sample 2','clinics/00000000-0000-0000-0000-0000000000c1/voice/2.m4a','audio/mp4',100);
\echo T21 audit row survives deleting the user (expect actor id still there)
INSERT INTO audit_events(clinic_id,actor_user_id,actor_type,action,resource_type,resource_id) VALUES (:c,'00000000-0000-0000-0000-0000000000a3','user','photo.uploaded','photo','x');
DELETE FROM clinic_members WHERE user_id='00000000-0000-0000-0000-0000000000a3';  -- v12: membership must go first (RESTRICT)
DELETE FROM users WHERE id='00000000-0000-0000-0000-0000000000a3';
SELECT 'actor kept: ' || (actor_user_id IS NOT NULL) FROM audit_events WHERE action='photo.uploaded';
\echo T22 oauth ticket with no user (expect ERROR)
INSERT INTO oauth_states(clinic_id,provider,state_hash,redirect_uri,expires_at) VALUES (:c,'google','h','https://x',now()+interval '10 min');
\echo T23 notification preference twice (expect ERROR, primary key)
INSERT INTO notification_preferences(user_id,category,channel) VALUES ('00000000-0000-0000-0000-0000000000a1','portfolio_allocated','email');
INSERT INTO notification_preferences(user_id,category,channel) VALUES ('00000000-0000-0000-0000-0000000000a1','portfolio_allocated','email');
\echo T24 remove doctor from clinic deletes his photos + voice at that clinic (expect 0 0)
DELETE FROM improvement_work_items; DELETE FROM clinic_practitioners WHERE practitioner_id='00000000-0000-0000-0000-0000000000d1';
SELECT (SELECT count(*) FROM photos WHERE practitioner_id='00000000-0000-0000-0000-0000000000d1') || ' ' || (SELECT count(*) FROM voice_samples);
