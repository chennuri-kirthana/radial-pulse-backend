-- v15 doctor profile fields: tests N1-N20 (run on a v15 database AFTER scenario/seed-family-dental-v15.sql, as the owner).
\set ON_ERROR_STOP 0
\pset footer off
\set d '\'00000000-0000-0000-0000-00000000dd01\''
\set c '\'00000000-0000-0000-0000-00000000cc01\''

\echo N1 doctor profile from the seed + experience calculated from practice_start_year (expect 1 row)
SELECT p.full_name, p.specialty, p.qualifications,
       extract(year FROM current_date)::int - p.practice_start_year AS years_of_experience,
       c.name AS clinic, c.established_year, c.address_line, c.city,
       cp.consultation_hours, cp.weekly_off_days, cp.consultation_fee, cp.consultation_fee_currency,
       cp.consultation_time_zone, cp.schedule_notes,
       p.services_and_conditions, p.approx_patients_treated, p.highlights
FROM practitioners p JOIN clinic_practitioners cp ON cp.practitioner_id = p.id JOIN clinics c ON c.id = cp.clinic_id
WHERE p.id = :d;

\echo N2 practice_start_year 1930 (expect ERROR, check)
UPDATE practitioners SET practice_start_year = 1930 WHERE id = :d;
\echo N3 practice_start_year next year (expect ERROR, cannot be in the future)
UPDATE practitioners SET practice_start_year = extract(year FROM current_date)::int + 1 WHERE id = :d;
\echo N4 practice_start_year this year (expect UPDATE 1)
UPDATE practitioners SET practice_start_year = extract(year FROM current_date)::int WHERE id = :d;
UPDATE practitioners SET practice_start_year = 2011 WHERE id = :d;
\echo N5 approx_patients_treated -1 (expect ERROR)
UPDATE practitioners SET approx_patients_treated = -1 WHERE id = :d;
\echo N6 services_and_conditions with an empty item / a NULL item (expect ERROR, ERROR)
UPDATE practitioners SET services_and_conditions = '{"Braces",""}' WHERE id = :d;
UPDATE practitioners SET services_and_conditions = ARRAY['Braces', NULL] WHERE id = :d;
\echo N7 weekly_off_days {sunday} (expect ERROR) / {sat,sun} (expect UPDATE 1)
UPDATE clinic_practitioners SET weekly_off_days = '{sunday}' WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET weekly_off_days = '{sat,sun}' WHERE practitioner_id = :d;
\echo N8 consultation_fee -1 (expect ERROR) / currency 'inr' (expect ERROR) / currency 'USD' (expect UPDATE 1)
UPDATE clinic_practitioners SET consultation_fee = -1 WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET consultation_fee_currency = 'inr' WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET consultation_fee_currency = 'USD' WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET consultation_fee_currency = 'INR', weekly_off_days = '{sun}' WHERE practitioner_id = :d;
\echo N9 clinic established_year 1700 (expect ERROR) / next year (expect ERROR) / 2008 (expect UPDATE 1)
UPDATE clinics SET established_year = 1700 WHERE id = :c;
UPDATE clinics SET established_year = extract(year FROM current_date)::int + 1 WHERE id = :c;
UPDATE clinics SET established_year = 2008 WHERE id = :c;
\echo N10 new clinic without the new fields (expect INSERT 0 1: all new fields are optional)
INSERT INTO clinics (id, client_organization_id, name) VALUES ('00000000-0000-0000-0000-00000000cc09','00000000-0000-0000-0000-00000000bb01','Blank Clinic');
DELETE FROM clinics WHERE id = '00000000-0000-0000-0000-00000000cc09';

\echo N15 schedule in the old free shape {"mon_sat":"10:00-14:00"} (expect ERROR, one shape only)
UPDATE clinic_practitioners SET consultation_hours = '{"mon_sat":"10:00-14:00"}' WHERE practitioner_id = :d;
\echo N16 schedule with from after to / bad time 25:00 / extra key (expect ERROR x3)
UPDATE clinic_practitioners SET consultation_hours = '{"mon":[{"from":"14:00","to":"10:00"}]}' WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET consultation_hours = '{"mon":[{"from":"10:00","to":"25:00"}]}' WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET consultation_hours = '{"mon":[{"from":"10:00","to":"12:00","note":"x"}]}' WHERE practitioner_id = :d;
\echo N17 schedule: only Monday, two slots (expect UPDATE 1) / empty = no consultation any day (expect UPDATE 1)
UPDATE clinic_practitioners SET consultation_hours = '{"mon":[{"from":"09:00","to":"12:00"},{"from":"17:00","to":"20:00"}]}' WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET consultation_hours = '{}' WHERE practitioner_id = :d;
\echo N18 time zone 'Mars/Base' (expect ERROR) / 'Asia/Dubai' (expect UPDATE 1)
UPDATE clinic_practitioners SET consultation_time_zone = 'Mars/Base' WHERE practitioner_id = :d;
UPDATE clinic_practitioners SET consultation_time_zone = 'Asia/Dubai' WHERE practitioner_id = :d;
\echo N19 new clinic link without schedule fields gets defaults (expect '{}', '{}', INR, Asia/Kolkata)
INSERT INTO practitioners (id, full_name) VALUES ('00000000-0000-0000-0000-00000000dd09','Dr. Test');
INSERT INTO clinic_practitioners (clinic_id, practitioner_id) VALUES (:c, '00000000-0000-0000-0000-00000000dd09');
SELECT consultation_hours, weekly_off_days, consultation_fee_currency, consultation_time_zone FROM clinic_practitioners
 WHERE practitioner_id = '00000000-0000-0000-0000-00000000dd09';
DELETE FROM practitioners WHERE id = '00000000-0000-0000-0000-00000000dd09';
\echo N20 screen helper: the 7 weekdays with their slots or 'No consultation' (expect 7 rows)
UPDATE clinic_practitioners SET consultation_hours = '{"mon":[{"from":"10:00","to":"14:00"}],"fri":[{"from":"10:00","to":"14:00"},{"from":"17:00","to":"19:00"}]}' WHERE practitioner_id = :d;
SELECT d.day, coalesce((SELECT string_agg((s->>'from') || '–' || (s->>'to'), ', ')
                          FROM jsonb_array_elements(cp.consultation_hours->d.day) s), 'No consultation') AS timings
FROM clinic_practitioners cp,
     unnest(ARRAY['mon','tue','wed','thu','fri','sat','sun']) WITH ORDINALITY AS d(day, n)
WHERE cp.practitioner_id = :d ORDER BY d.n;

-- access rules (same rules as v14, new columns follow them)
SET ROLE radial_app;
\echo N11 Dr Pooja edits her own highlights + services (expect UPDATE 1)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa04';
UPDATE practitioners SET highlights = 'Updated by Dr Pooja', services_and_conditions = '{"Root canal","Braces"}' WHERE id = :d;
\echo N12 Dr Pooja edits her own fee at the clinic (expect UPDATE 0: only the clinic admin / DSM / admin manage clinic links, same as consultation_hours before v15)
UPDATE clinic_practitioners SET consultation_fee = 1 WHERE practitioner_id = :d;
\echo N13 Mehul (clinic admin) sets the fee and weekly off (expect UPDATE 1)
SET rp.user_id = '00000000-0000-0000-0000-00000000aa03';
UPDATE clinic_practitioners SET consultation_fee = 600, weekly_off_days = '{sun}' WHERE practitioner_id = :d;
RESET rp.user_id;
RESET ROLE;
\echo N14 read-only service role sees the new fields (expect 1 row)
SET ROLE radial_service;
SELECT p.full_name, p.practice_start_year, p.highlights, cp.consultation_fee, cp.weekly_off_days, c.established_year
FROM practitioners p JOIN clinic_practitioners cp ON cp.practitioner_id = p.id JOIN clinics c ON c.id = cp.clinic_id
WHERE p.id = :d;
RESET ROLE;
