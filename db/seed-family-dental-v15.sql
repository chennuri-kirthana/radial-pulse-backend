-- Scenario: "Family Dental Clinic, Ahmedabad" touches all 22 tables (schema v15). Run on an EMPTY v15 database.
-- Short ids used in the explanation:  U1 Anil (Platform Admin) · U2 Ravi (DSM) · U3 Mehul (Clinic Administrator) · U4 Dr Pooja (practitioner)
--   ORG1 Shah Healthcare · C1 Family Dental Clinic · D1 Dr Pooja Shah · A1 first report
\set ON_ERROR_STOP 1
BEGIN;
-- STEP 1  Platform Admin portal: platform set up, Anil creates DSM Ravi
INSERT INTO platform_settings (id, support_email, support_phone)
VALUES (1, 'support@radialpulse.in', '+91 80000 00000');
INSERT INTO users (id, email, full_name, cognito_sub, platform_role) VALUES
 ('00000000-0000-0000-0000-00000000aa01','anil@radialpulse.in','Anil Kumar','sub-anil','platform_administrator'),
 ('00000000-0000-0000-0000-00000000aa02','ravi@radialpulse.in','Ravi Patel','sub-ravi','digital_success_manager');
INSERT INTO audit_events (clinic_id, actor_user_id, actor_type, action, resource_type, resource_id)
VALUES (NULL,'00000000-0000-0000-0000-00000000aa01','user','user.created','user','00000000-0000-0000-0000-00000000aa02');

-- STEP 2  Lead: Anil adds the business + clinic, assigns Ravi as DSM
SET LOCAL rp.user_id = '00000000-0000-0000-0000-00000000aa01';   -- Anil is acting (history + RLS)
SET LOCAL rp.stage_note = 'lead added';
INSERT INTO client_organizations (id, name) VALUES ('00000000-0000-0000-0000-00000000bb01','Shah Healthcare Pvt Ltd');
INSERT INTO clinics (id, client_organization_id, name, specialty, phone, website_url, address_line, city, state, postal_code, latitude, longitude, established_year)
VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000bb01','Family Dental Clinic','Family Dentistry',
        '+91 79 4000 1234','https://familydental.example','12 CG Road','Ahmedabad','Gujarat','380009',23.022500,72.571400, 2008);
INSERT INTO clinic_profiles (clinic_id, brand, services, schedule)
VALUES ('00000000-0000-0000-0000-00000000cc01','{"tagline":"Gentle care for every smile"}',
        '{"items":["Root canal","Braces","Teeth whitening"]}','{"mon_sat":"10:00-19:00"}');
INSERT INTO portfolio_allocations (client_organization_id, user_id) VALUES ('00000000-0000-0000-0000-00000000bb01','00000000-0000-0000-0000-00000000aa02');
INSERT INTO notifications (user_id, clinic_id, category, title, link)
VALUES ('00000000-0000-0000-0000-00000000aa02','00000000-0000-0000-0000-00000000cc01','portfolio_allocated','You were assigned Family Dental Clinic','/clinics/00000000-0000-0000-0000-00000000cc01');
INSERT INTO notification_preferences (user_id, category, channel, is_enabled) VALUES
 ('00000000-0000-0000-0000-00000000aa02','portfolio_allocated','email', true),
 ('00000000-0000-0000-0000-00000000aa02','portfolio_allocated','in_app', true);

-- STEP 3  Finder agents discover the clinic online
INSERT INTO clinic_online_profiles (clinic_id, platform, url, display_name, verification, confidence, discovered_by) VALUES
 ('00000000-0000-0000-0000-00000000cc01','google_business_profile','https://maps.google.com/?cid=123456','Family Dental Clinic','confirmed',0.950,'gbp-finder-agent'),
 ('00000000-0000-0000-0000-00000000cc01','instagram','https://instagram.com/familydental_amd','familydental_amd','unverified',0.700,'social-finder-agent');
SET LOCAL rp.user_id = '00000000-0000-0000-0000-00000000aa02';   -- Ravi is acting from here
SET LOCAL rp.stage_note = '';
UPDATE clinics SET stage='presence_discovered' WHERE id='00000000-0000-0000-0000-00000000cc01';

-- STEP 4  Digital Growth Team's report arrives; DSM Ravi reviews + approves + publishes
INSERT INTO digital_presence_assessments (id, clinic_id, digital_growth_report_id, status, overall_score, summary, started_at, completed_at)
VALUES ('00000000-0000-0000-0000-00000000ee01','00000000-0000-0000-0000-00000000cc01','seo-rpt-7781','completed',62.50,
        'Good reviews, weak website titles, Instagram inactive', now()-interval '2 hour', now()-interval '1 hour');
UPDATE digital_presence_assessments SET review_state='approved', review_note='Checked, ready for the client', reviewed_at=now(),
       publication_state='published', published_at=now() WHERE id='00000000-0000-0000-0000-00000000ee01';
INSERT INTO audit_events (clinic_id, actor_user_id, actor_type, action, resource_type, resource_id) VALUES
 ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa02','user','digital_presence_assessment.approved','digital_presence_assessment','00000000-0000-0000-0000-00000000ee01');
INSERT INTO improvement_work_items (clinic_id, title, priority, source_assessment_id, opportunity_code, assignee_user_id, due_at)
VALUES ('00000000-0000-0000-0000-00000000cc01','Add clinic name + city to website page titles','high',
        '00000000-0000-0000-0000-00000000ee01','title_missing_location','00000000-0000-0000-0000-00000000aa02', now()+interval '7 day');

-- STEP 5  Deal closes: Ravi invites Mehul as Clinic Administrator (Clinic Admin portal)
INSERT INTO users (id, email, full_name, cognito_sub, platform_role)
VALUES ('00000000-0000-0000-0000-00000000aa03','mehul@familydental.example','Mehul Shah','sub-mehul','clinic_member');
INSERT INTO clinic_members (clinic_id, user_id, role)
VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa03','clinic_administrator');
SET LOCAL rp.stage_note = 'signed';
UPDATE clinics SET stage='active_client' WHERE id='00000000-0000-0000-0000-00000000cc01';
INSERT INTO audit_events (clinic_id, actor_user_id, actor_type, action, resource_type, resource_id) VALUES
 ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa02','user','member.invited','user','00000000-0000-0000-0000-00000000aa03');

-- STEP 6  Mehul adds his doctor, Dr Pooja Shah, and she gets the Doctor portal login
INSERT INTO users (id, email, full_name, cognito_sub, platform_role)
VALUES ('00000000-0000-0000-0000-00000000aa04','pooja@familydental.example','Dr. Pooja Shah','sub-pooja','practitioner');
INSERT INTO practitioners (id, full_name, specialty, qualifications, registration_number, user_id,
                           practice_start_year, services_and_conditions, approx_patients_treated, highlights)
VALUES ('00000000-0000-0000-0000-00000000dd01','Dr. Pooja Shah','Family Dentistry','BDS, FAGE','GDC-A-12345','00000000-0000-0000-0000-00000000aa04',
        2011, '{"Root canal","Braces","Teeth whitening","Gum disease"}', 12000,
        'Gujarat Dental Council award for community dental camps (2019)');
INSERT INTO clinic_practitioners (clinic_id, practitioner_id, designation, consultation_hours, weekly_off_days,
                                  consultation_fee, consultation_fee_currency, consultation_time_zone, schedule_notes, is_primary)
VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000dd01','Chief Dentist',
        '{"mon":[{"from":"10:00","to":"14:00"}],"tue":[{"from":"10:00","to":"14:00"}],"wed":[{"from":"10:00","to":"14:00"}],
          "thu":[{"from":"10:00","to":"14:00"}],"fri":[{"from":"10:00","to":"14:00"},{"from":"17:00","to":"19:00"}],
          "sat":[{"from":"10:00","to":"13:00"}],"sun":[]}',
        '{sun}', 500.00, 'INR', 'Asia/Kolkata', 'Emergency appointments on call', true);

-- STEP 6b Practitioner portal > Details: Dr Pooja edits her bio; it goes live at once (no approval)
UPDATE practitioners SET bio='15 years of gentle family dentistry. Speaks Gujarati, Hindi and English.', updated_at=now()
 WHERE id='00000000-0000-0000-0000-00000000dd01';
INSERT INTO audit_events (clinic_id, actor_user_id, actor_type, action, resource_type, resource_id) VALUES
 ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa04','user','practitioner.updated','practitioner','00000000-0000-0000-0000-00000000dd01');

-- STEP 7  Doctor portal > Media: photos and voice
INSERT INTO photos (id, clinic_id, practitioner_id, attire, outfit_no, angle, original_key, mime_type, size_bytes, width, height, processing_status)
VALUES ('00000000-0000-0000-0000-00000000f001','00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000dd01',
        'with_apron',1,'front','clinics/00000000-0000-0000-0000-00000000cc01/photos/f001.jpg','image/jpeg',2400000,3000,4000,'ready');
INSERT INTO photos (id, clinic_id, category, original_key, mime_type, size_bytes, processing_status, review_state, reviewed_at)
VALUES ('00000000-0000-0000-0000-00000000f002','00000000-0000-0000-0000-00000000cc01','cover',
        'clinics/00000000-0000-0000-0000-00000000cc01/photos/f002.jpg','image/jpeg',1800000,'ready','approved', now());
INSERT INTO photos (id, clinic_id, original_key, mime_type, size_bytes, processing_status)
VALUES ('00000000-0000-0000-0000-00000000f003','00000000-0000-0000-0000-00000000cc01',
        'clinics/00000000-0000-0000-0000-00000000cc01/photos/f003.jpg','image/jpeg',1500000,'ready');
INSERT INTO voice_samples (id, clinic_id, practitioner_id, title, original_key, mime_type, size_bytes, duration_seconds, processing_status)
VALUES ('00000000-0000-0000-0000-00000000f101','00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000dd01','Reading sample 2',
        'clinics/00000000-0000-0000-0000-00000000cc01/voice/f101.m4a','audio/mp4',900000,95.5,'ready');
INSERT INTO voice_samples (clinic_id, practitioner_id, title, original_key, mime_type, size_bytes, duration_seconds, processing_status)
VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000dd01','Clinic greeting',
        'clinics/00000000-0000-0000-0000-00000000cc01/voice/f102.m4a','audio/mp4',700000,42.0,'ready');
INSERT INTO audit_events (clinic_id, actor_user_id, actor_type, action, resource_type, resource_id) VALUES
 ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa04','user','photo.uploaded','photo','00000000-0000-0000-0000-00000000f001'),
 ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa04','user','voice_sample.uploaded','voice_sample','00000000-0000-0000-0000-00000000f101');
-- DSM sorts the unsorted photo and approves it
UPDATE photos SET category='reception_waiting', review_state='approved', reviewed_at=now() WHERE id='00000000-0000-0000-0000-00000000f003';

-- STEP 8  Client Collaboration between the clinic and Radial Pulse
INSERT INTO collaboration_messages (id, clinic_id, sender_user_id, sender_name, sender_side, body)
VALUES ('00000000-0000-0000-0000-00000000c701','00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa03','Mehul Shah','clinic',
        'Can Dr Pooja upload two more reading samples?');
INSERT INTO collaboration_messages (clinic_id, sender_user_id, sender_name, sender_side, body, parent_message_id, created_at)
VALUES ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa02','Ravi Patel','radial_pulse',
        'Yes, please give each one a new title.','00000000-0000-0000-0000-00000000c701', now()+interval '1 min');

-- STEP 9  Mehul clicks "Connect Google" (Accounts tab)
INSERT INTO oauth_states (clinic_id, provider, state_hash, code_verifier, redirect_uri, started_by_user_id, expires_at)
VALUES ('00000000-0000-0000-0000-00000000cc01','google','9f86d081884c7d65','pkce-verifier-abc','https://app.radialpulse.in/oauth/callback',
        '00000000-0000-0000-0000-00000000aa03', now()+interval '10 min');
INSERT INTO connected_accounts (id, clinic_id, provider, external_account_id, external_account_name, scopes, secret_ref, token_expires_at, connected_at)
VALUES ('00000000-0000-0000-0000-00000000ca01','00000000-0000-0000-0000-00000000cc01','google','10987654321','mehul@familydental.example',
        '{https://www.googleapis.com/auth/business.manage}','arn:aws:secretsmanager:ap-south-1:111122223333:secret:rp/oauth/ca01',
        now()+interval '1 hour', now());
INSERT INTO connected_account_resources (connected_account_id, clinic_id, resource_type, external_id, display_name, is_selected) VALUES
 ('00000000-0000-0000-0000-00000000ca01','00000000-0000-0000-0000-00000000cc01','gbp_location','locations/555','Family Dental Clinic – CG Road', true),
 ('00000000-0000-0000-0000-00000000ca01','00000000-0000-0000-0000-00000000cc01','gbp_location','locations/556','Shah Dental – old listing', false);
DELETE FROM oauth_states WHERE clinic_id='00000000-0000-0000-0000-00000000cc01';  -- ticket used once, then deleted
INSERT INTO audit_events (clinic_id, actor_user_id, actor_type, action, resource_type, resource_id, details) VALUES
 ('00000000-0000-0000-0000-00000000cc01','00000000-0000-0000-0000-00000000aa03','user','account.connected','connected_account','00000000-0000-0000-0000-00000000ca01','{"provider":"google"}');
COMMIT;

-- Show one line per table: how many rows the scenario created
SELECT t, n FROM (VALUES
 ('platform_settings',(SELECT count(*) FROM platform_settings)),('users',(SELECT count(*) FROM users)),
 ('client_organizations',(SELECT count(*) FROM client_organizations)),('clinics',(SELECT count(*) FROM clinics)),
 ('clinic_profiles',(SELECT count(*) FROM clinic_profiles)),('clinic_stage_changes',(SELECT count(*) FROM clinic_stage_changes)),
 ('portfolio_allocations',(SELECT count(*) FROM portfolio_allocations)),('clinic_members',(SELECT count(*) FROM clinic_members)),
 ('practitioners',(SELECT count(*) FROM practitioners)),('clinic_practitioners',(SELECT count(*) FROM clinic_practitioners)),
 ('clinic_online_profiles',(SELECT count(*) FROM clinic_online_profiles)),('digital_presence_assessments',(SELECT count(*) FROM digital_presence_assessments)),
 ('improvement_work_items',(SELECT count(*) FROM improvement_work_items)),('audit_events',(SELECT count(*) FROM audit_events)),
 ('notifications',(SELECT count(*) FROM notifications)),('notification_preferences',(SELECT count(*) FROM notification_preferences)),
 ('collaboration_messages',(SELECT count(*) FROM collaboration_messages)),
 ('connected_accounts',(SELECT count(*) FROM connected_accounts)),('connected_account_resources',(SELECT count(*) FROM connected_account_resources)),
 ('oauth_states (used, then deleted)',(SELECT count(*) FROM oauth_states)),('photos',(SELECT count(*) FROM photos)),
 ('voice_samples',(SELECT count(*) FROM voice_samples))) v(t,n);
