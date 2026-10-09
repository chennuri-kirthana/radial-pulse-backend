-- Rules tests 30-38 (run right AFTER 01-rules-tests.sql on the same database, as the owner).
\set ON_ERROR_STOP 0
\echo T30 change the OWNER role to doctor (expect ERROR - the gap is closed)
UPDATE users SET platform_role='practitioner' WHERE id='00000000-0000-0000-0000-0000000000a1';
\echo T31 change the DSM role (expect ERROR) and the doctor role (expect ERROR)
UPDATE users SET platform_role='platform_administrator' WHERE id='00000000-0000-0000-0000-0000000000a4';
UPDATE users SET platform_role='clinic_member' WHERE id='00000000-0000-0000-0000-0000000000a2';
\echo T32 change role of a user with no links (expect OK) / same role re-saved (expect OK)
INSERT INTO users(id,email,platform_role) VALUES ('00000000-0000-0000-0000-0000000000a9','new@x.in','clinic_member');
UPDATE users SET platform_role='practitioner' WHERE id='00000000-0000-0000-0000-0000000000a9';
UPDATE users SET platform_role='clinic_member', full_name='Owner' WHERE id='00000000-0000-0000-0000-0000000000a1';
\echo T33 delete a practitioner: his clinic links go too (expect 0)
DELETE FROM practitioners WHERE id='00000000-0000-0000-0000-0000000000d2';
SELECT count(*) FROM clinic_practitioners WHERE practitioner_id='00000000-0000-0000-0000-0000000000d2';
\echo T38 voice has no review columns (expect ERROR)
INSERT INTO voice_samples(clinic_id,practitioner_id,title,original_key,mime_type,size_bytes,review_state) VALUES ('00000000-0000-0000-0000-0000000000c1','00000000-0000-0000-0000-0000000000d1','New','clinics/00000000-0000-0000-0000-0000000000c1/voice/9.m4a','audio/mp4',100,'pending');
