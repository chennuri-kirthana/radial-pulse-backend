-- DEMO data for the /api/v1/internal Phase 1 routes (SEO team). FAKE clinics, DEV only, never PROD.
-- Run AFTER db/seed-family-dental-v15.sql, as the owner login, on database radial_pulse.
-- Adds one more business with:
--   C2 Bright Smile Dental (Surat)   active client, NO website and NO phone  -> NAP with nulls
--   C3 Sunrise Eye Care (Vadodara)   active client, full NAP
--   C4 City Skin Clinic (Rajkot)     a lead (prospective)                    -> 404 in the demo
--   C5 Old Ashram Road Branch        active client but ARCHIVED              -> 404 in the demo
-- With the family seed (C1 Family Dental Clinic, active), GET /active-clinics shows total = 3.
-- Safe to run twice: it does nothing if the demo business is already there.
\set ON_ERROR_STOP 1
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users WHERE id = '00000000-0000-0000-0000-00000000aa01') THEN
    RAISE EXCEPTION 'run db/seed-family-dental-v15.sql first';
  END IF;
END $$;

SET LOCAL rp.user_id = '00000000-0000-0000-0000-00000000aa01';   -- Anil (Platform Administrator) is acting

INSERT INTO client_organizations (id, name)
VALUES ('00000000-0000-0000-0000-00000000bb02', 'Demo Care Group Pvt Ltd')
ON CONFLICT (id) DO NOTHING;

SET LOCAL rp.stage_note = 'demo data';
INSERT INTO clinics (id, client_organization_id, name, specialty, phone, website_url, address_line, city, state, postal_code)
VALUES
 ('00000000-0000-0000-0000-00000000cc02','00000000-0000-0000-0000-00000000bb02','Bright Smile Dental','Dentistry',
  NULL, NULL, '4 Ring Road','Surat','Gujarat','395002'),
 ('00000000-0000-0000-0000-00000000cc03','00000000-0000-0000-0000-00000000bb02','Sunrise Eye Care','Ophthalmology',
  '+91 265 400 5678','https://sunriseeye.example','21 Alkapuri','Vadodara','Gujarat','390007'),
 ('00000000-0000-0000-0000-00000000cc04','00000000-0000-0000-0000-00000000bb02','City Skin Clinic','Dermatology',
  '+91 281 400 9012','https://cityskin.example','9 Kalawad Road','Rajkot','Gujarat','360005'),
 ('00000000-0000-0000-0000-00000000cc05','00000000-0000-0000-0000-00000000bb02','Old Ashram Road Branch','Dentistry',
  '+91 79 4000 9999','https://oldbranch.example','1 Ashram Road','Ahmedabad','Gujarat','380009')
ON CONFLICT (id) DO NOTHING;

-- Stage changes go through UPDATE (a trigger writes clinic_stage_changes; never insert there).
UPDATE clinics SET stage = 'active_client'
 WHERE id IN ('00000000-0000-0000-0000-00000000cc02','00000000-0000-0000-0000-00000000cc03','00000000-0000-0000-0000-00000000cc05')
   AND stage <> 'active_client';
UPDATE clinics SET is_active = false, archived_reason = 'Demo: branch closed'
 WHERE id = '00000000-0000-0000-0000-00000000cc05' AND is_active;

-- What the demo should show:
SELECT name, stage, is_active, coalesce(website_url, '(none)') AS website_url,
       CASE WHEN stage = 'active_client' AND is_active THEN 'in /active-clinics' ELSE '404 on /clinic-nap' END AS demo
FROM clinics ORDER BY name;
COMMIT;
