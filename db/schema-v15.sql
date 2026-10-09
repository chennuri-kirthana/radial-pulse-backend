-- Radial Pulse — central team database schema (PostgreSQL 16)
-- Version 15 (final) · 22 tables · 8 Oct 2026
-- 4 portals: Platform Administrator · Digital Success Manager · Clinic Administrator · Practitioner
--            (users.platform_role decides the portal)
-- v4 = v3 with the project terminology (Project_Entity_Terminology_Mapping):
--   organizations          -> client_organizations   (Client Organization = the business; clinics = its branches)
--   clinic_dsm_assignments -> portfolio_allocations  (Portfolio Allocation)
--   chat_messages / chat_read_markers -> collaboration_messages / collaboration_read_markers (Client Collaboration)
--   work_items             -> improvement_work_items (Improvement Work Items); finding_code -> opportunity_code
--   platform_role 'doctor' -> 'practitioner'               (Practitioner)
--   stage 'profile_enriched' -> 'presence_discovered' (Digital Presence Intelligence Agent)
--   assessments.seo_report_id -> digital_growth_report_id (Digital Growth Team)
--   notification category 'clinic_assigned' -> 'portfolio_allocated'
-- v5 = v4 + your naming decisions (6 Oct):
--   improvement_work_items.owner_user_id -> assignee_user_id   ("owner" could be confused with the Clinic Owner)
--   clinic_members.is_owner removed (PDF: Clinic Owner -> Clinic Administrator; all Clinic Administrators are equal)
--   users.platform_role 'clinic_user' -> 'clinic_member'
-- v6 = v5 + your decision (6 Oct): only PHOTOS need approval.
--   table practitioner_profile_changes removed: a practitioner's bio / qualifications / specialty
--   edits now change the practitioners row directly (who changed what: audit_events).
-- v7 = v6 + review against Project_Entity_Terminology_Mapping (your decisions, 6 Oct):
--   assessments -> digital_presence_assessments (Digital Presence Assessment); column source_assessment_id kept
--   portfolio_allocations.clinic_id -> client_organization_id (PDF: "Allocation of client organizations to
--     Digital Success Managers"); one active DSM per Client Organization = all its clinics
--   platform_settings.organization_name removed
--   notifications.kind -> category (same name as notification_preferences.category)
-- v8 = v7 + your decision (6 Oct): table collaboration_read_markers removed (no unread counts / read position).
-- v9 = v8 + your decision (6 Oct): voice_samples has no review: review_state and review_note removed
--   (reviewed_at kept). A practitioner can't reuse a title: UNIQUE (clinic_id, practitioner_id, lower(title)).
-- v10 = v9 + your decision (6 Oct): digital_presence_assessments.sequence removed (the list is ordered by
--   created_at); its UNIQUE (clinic_id, sequence) and CHECK removed; index (clinic_id, created_at) added
--   so the list stays fast and the clinic_id foreign key keeps an index.
-- v11 = v10 + "make it minimal" (6 Oct): improvement_work_items.kind, area, source_team removed
--   (kind and source_team repeated source_assessment_id; area was not needed), and the (clinic_id, area, status) index.
-- Everything else (keys, rules, triggers) is unchanged from v10.
-- v12 = v11 + fixes from the senior review (6 Oct), no new tables:
--   H1 updated_at set automatically on every update (rp_set_updated_at, section 11)
--   H2 audit_events can't be changed or deleted (trigger)
--   H3 a work item's assignee must belong to that clinic (trigger)
--   M1 stage history accepts only the 5 stages (CHECK)
--   M2 stage history is written automatically when clinics.stage changes (trigger)
--   M3 deleting a user who is still a clinic member or an allocated DSM is refused (RESTRICT): deactivate instead
--   M7 reviewed_at must be filled once an assessment or photo has been reviewed (CHECK)
--   L2 an active clinic has no archived_reason; an archived one must have it (CHECK)
-- v13 = v12 + the rest of the review (6 Oct), no new tables:
--   M4 a clinic can't lose its last active Clinic Administrator (trigger)
--   M5 clinic_online_profiles.url is cleaned before saving, so near-duplicates are caught (trigger)
--   L4 when a practitioner's clinic link becomes inactive, his approved photos there stop being live (trigger)
--   H5 + H6 access rules: row-level security on all 22 tables (section 12), roles radial_app and radial_service
-- v14 = v13 + your decision (6 Oct): a new lead (Client Organization with no DSM yet) is visible ONLY to the
--   Platform Administrator. So only the Platform Administrator creates new businesses and clinics;
--   a DSM sees them once they are allocated to him.
-- v15 = v14 + doctor profile fields (your decisions, 8 Oct). No new tables, no renamed tables or keys:
--   practitioners:        practice_start_year (experience is calculated from it), services_and_conditions,
--                         approx_patients_treated, highlights
--   clinic_practitioners: weekly_off_days, consultation_fee, consultation_fee_currency,
--                         consultation_time_zone, schedule_notes
--                         (per clinic: a doctor can have a different fee / timings at each clinic;
--                          days & timings stay in the existing consultation_hours, now with ONE checked shape:
--                          {"mon":[{"from":"10:00","to":"14:00"}], ... "sun":[]}; a missing day = no consultation)
--   clinics:              established_year (operating since)
--   Reused as they are: practitioners.full_name / specialty / qualifications, clinics.name + address columns.
--   A year can't be in the future: trigger rp_year_not_in_future (a CHECK must not depend on today's date).
--   The time zone must be a real one (e.g. Asia/Kolkata): trigger rp_check_time_zone.
-- Conventions: plural snake_case tables · uuid primary key "id" · timestamptz · created_at/updated_at
-- Access rules (row-level security, roles radial_app / radial_service): section 12 at the end of this file.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =====================================================================  1. PEOPLE AND ACCESS
CREATE TABLE users (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email            varchar(320) NOT NULL,
  full_name        varchar(200),
  phone            varchar(32),
  cognito_sub      varchar(64),
  platform_role    varchar(32)  NOT NULL,          -- decides the portal
  avatar_key       varchar(512),
  is_active        boolean      NOT NULL DEFAULT true,
  last_login_at    timestamptz,
  created_at       timestamptz  NOT NULL DEFAULT now(),
  updated_at       timestamptz  NOT NULL DEFAULT now(),
  CONSTRAINT uq_users_email UNIQUE (email),
  CONSTRAINT uq_users_cognito_sub UNIQUE (cognito_sub),
  CONSTRAINT ck_users_email_lowercase CHECK (email = lower(trim(email))),
  CONSTRAINT ck_users_platform_role CHECK (platform_role IN ('platform_administrator','digital_success_manager','clinic_member','practitioner')),
  CONSTRAINT ck_users_avatar_key CHECK (avatar_key LIKE 'users/' || id || '/%')
);

CREATE TABLE client_organizations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        varchar(200) NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================  2. CLIENT ORGANIZATIONS, CLINICS AND PRACTITIONERS
CREATE TABLE clinics (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_organization_id  uuid NOT NULL REFERENCES client_organizations(id) ON DELETE RESTRICT,
  name             varchar(200) NOT NULL,
  specialty        varchar(200),
  description      text,
  email            varchar(320),
  phone            varchar(32),
  website_url      varchar(500),
  address_line     varchar(300),
  city             varchar(100),
  state            varchar(100),
  postal_code      varchar(20),
  country          varchar(2) NOT NULL DEFAULT 'IN',
  latitude         numeric(9,6),
  longitude        numeric(9,6),
  established_year smallint,                 -- v15: year the hospital / clinic started operating
  stage            varchar(32) NOT NULL DEFAULT 'prospective_client',  -- when it changed: clinic_stage_changes
  is_active        boolean NOT NULL DEFAULT true,
  archived_reason  text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_clinics_stage CHECK (stage IN ('prospective_client','presence_discovered','assessment_completed','client_discussion','active_client')),
  CONSTRAINT ck_clinics_country_code CHECK (country ~ '^[A-Z]{2}$'),
  CONSTRAINT ck_clinics_lat_lng_pair CHECK ((latitude IS NULL) = (longitude IS NULL)),
  CONSTRAINT ck_clinics_latitude_range CHECK (latitude BETWEEN -90 AND 90),
  CONSTRAINT ck_clinics_longitude_range CHECK (longitude BETWEEN -180 AND 180),
  CONSTRAINT ck_clinics_established_year CHECK (established_year BETWEEN 1800 AND 2100),
  -- active = no reason; archived = a reason is required (restore must clear it)
  CONSTRAINT ck_clinics_archive_reason CHECK (
    (is_active AND archived_reason IS NULL) OR
    (NOT is_active AND archived_reason IS NOT NULL AND length(trim(archived_reason)) > 0))
);
CREATE INDEX ix_clinics_client_organization_id ON clinics (client_organization_id);
CREATE INDEX ix_clinics_stage ON clinics (stage);
CREATE INDEX ix_clinics_name_trgm ON clinics USING gin (name gin_trgm_ops);

CREATE TABLE clinic_profiles (
  clinic_id   uuid PRIMARY KEY REFERENCES clinics(id) ON DELETE CASCADE,
  brand       jsonb NOT NULL DEFAULT '{}',
  audience    jsonb NOT NULL DEFAULT '{}',
  services    jsonb NOT NULL DEFAULT '{}',
  schedule    jsonb NOT NULL DEFAULT '{}',
  version     integer NOT NULL DEFAULT 1,           -- stops two people overwriting each other's edits
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_clinic_profiles_version_positive CHECK (version >= 1)
);

-- The ONLY record of stage moves (incl. who moved it). The API does NOT also write stage moves
-- to audit_events, so the same fact is never stored twice.
-- Rows are written AUTOMATICALLY by tr_clinics_stage_history (below) whenever clinics.stage is set,
-- so the history always matches the clinic. The API only runs, in the same transaction:
--   SET LOCAL rp.user_id = '<who>';  SET LOCAL rp.stage_note = '<optional note>';
CREATE TABLE clinic_stage_changes (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id   uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  from_stage  varchar(32),
  to_stage    varchar(32) NOT NULL,
  note        text,
  changed_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  changed_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_clinic_stage_changes_stage_changes CHECK (from_stage IS NULL OR from_stage <> to_stage),
  CONSTRAINT ck_clinic_stage_changes_from_stage CHECK (from_stage IN ('prospective_client','presence_discovered','assessment_completed','client_discussion','active_client')),
  CONSTRAINT ck_clinic_stage_changes_to_stage CHECK (to_stage IN ('prospective_client','presence_discovered','assessment_completed','client_discussion','active_client'))
);
CREATE INDEX ix_clinic_stage_changes_clinic_time ON clinic_stage_changes (clinic_id, changed_at);
CREATE INDEX ix_clinic_stage_changes_changed_by ON clinic_stage_changes (changed_by_user_id) WHERE changed_by_user_id IS NOT NULL;

CREATE FUNCTION rp_record_stage_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.stage IS DISTINCT FROM OLD.stage THEN
    -- clock_timestamp() (not now()) so two moves in one transaction still get different times
    INSERT INTO clinic_stage_changes (clinic_id, from_stage, to_stage, note, changed_by_user_id, changed_at)
    VALUES (NEW.id,
            CASE WHEN TG_OP = 'UPDATE' THEN OLD.stage END,
            NEW.stage,
            NULLIF(current_setting('rp.stage_note', true), ''),
            NULLIF(current_setting('rp.user_id', true), '')::uuid,
            clock_timestamp());
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER tr_clinics_stage_history AFTER INSERT OR UPDATE OF stage ON clinics
  FOR EACH ROW EXECUTE FUNCTION rp_record_stage_change();

-- One SHARED record per practitioner across all businesses (option A); each clinic's own details live in
-- clinic_practitioners. A clinic adds an EXISTING practitioner via rp_find_practitioner_by_registration().
-- user_id = the practitioner's own login for the Practitioner portal (optional, platform_role must be 'practitioner').
CREATE TABLE practitioners (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name            varchar(200) NOT NULL,
  specialty            varchar(120),
  qualifications       varchar(300),
  registration_number  varchar(64),
  bio                  text,
  practice_start_year  smallint,                     -- v15: year the doctor started practising; experience = this year - it
  services_and_conditions text[] NOT NULL DEFAULT '{}', -- v15: main services / conditions treated, e.g. {Root canal, Braces}
  approx_patients_treated integer,                   -- v15: approximate number of patients treated so far
  highlights           text,                         -- v15: milestones, achievements, professional highlights
  user_id              uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  -- "ka-1234 " and "KA-1234" must count as the same number, so store it normalised.
  CONSTRAINT ck_practitioners_registration_normalised
    CHECK (registration_number = upper(trim(registration_number)) AND registration_number <> ''),
  CONSTRAINT ck_practitioners_practice_start_year CHECK (practice_start_year BETWEEN 1940 AND 2100),
  CONSTRAINT ck_practitioners_services_and_conditions CHECK (array_position(services_and_conditions, '') IS NULL
    AND array_position(services_and_conditions, NULL) IS NULL),
  CONSTRAINT ck_practitioners_approx_patients_treated CHECK (approx_patients_treated >= 0)
);
CREATE UNIQUE INDEX uq_practitioners_registration_number ON practitioners (registration_number) WHERE registration_number IS NOT NULL;
CREATE UNIQUE INDEX uq_practitioners_user_id ON practitioners (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX ix_practitioners_full_name_trgm ON practitioners USING gin (full_name gin_trgm_ops);

-- Many practitioners per clinic are supported (the app shows one for now).
-- v15: the one allowed shape of consultation_hours (used by a CHECK, so it must always give the same answer):
--   an object whose keys are days (mon..sun); each day = a list of slots {"from":"HH:MM","to":"HH:MM"}, from < to.
CREATE FUNCTION rp_valid_consultation_hours(h jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE d text; slots jsonb; slot jsonb;
BEGIN
  IF jsonb_typeof(h) <> 'object' THEN RETURN false; END IF;
  FOR d, slots IN SELECT key, value FROM jsonb_each(h) LOOP
    IF d NOT IN ('mon','tue','wed','thu','fri','sat','sun') OR jsonb_typeof(slots) <> 'array' THEN RETURN false; END IF;
    FOR slot IN SELECT value FROM jsonb_array_elements(slots) LOOP
      IF jsonb_typeof(slot) <> 'object'
         OR (SELECT count(*) FROM jsonb_object_keys(slot)) <> 2
         OR coalesce(slot->>'from', '') !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
         OR coalesce(slot->>'to', '')   !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
         OR slot->>'from' >= slot->>'to' THEN
        RETURN false;
      END IF;
    END LOOP;
  END LOOP;
  RETURN true;
END $$;

CREATE TABLE clinic_practitioners (
  clinic_id        uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  practitioner_id  uuid NOT NULL REFERENCES practitioners(id) ON DELETE CASCADE,
  designation      varchar(120),
  consultation_hours jsonb NOT NULL DEFAULT '{}',  -- days & timings: {"mon":[{"from":"10:00","to":"14:00"}], ...}; missing day = no consultation
  weekly_off_days  text[] NOT NULL DEFAULT '{}',    -- v15: weekly holiday / non-consultation days, e.g. {sun}
  consultation_fee numeric(10,2),                   -- v15: fee at THIS clinic
  consultation_fee_currency char(3) NOT NULL DEFAULT 'INR',  -- v15
  consultation_time_zone varchar(64) NOT NULL DEFAULT 'Asia/Kolkata',  -- v15: time zone of the timings above
  schedule_notes   text,                            -- v15: e.g. "Emergency appointments on call"
  is_primary       boolean NOT NULL DEFAULT false,
  is_active        boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (clinic_id, practitioner_id),
  CONSTRAINT ck_clinic_practitioners_weekly_off_days
    CHECK (weekly_off_days <@ ARRAY['mon','tue','wed','thu','fri','sat','sun']::text[]),
  CONSTRAINT ck_clinic_practitioners_consultation_fee CHECK (consultation_fee >= 0),
  CONSTRAINT ck_clinic_practitioners_fee_currency CHECK (consultation_fee_currency ~ '^[A-Z]{3}$'),
  CONSTRAINT ck_clinic_practitioners_consultation_hours CHECK (rp_valid_consultation_hours(consultation_hours))
);
CREATE UNIQUE INDEX uq_clinic_practitioners_one_primary ON clinic_practitioners (clinic_id) WHERE is_primary AND is_active;
CREATE INDEX ix_clinic_practitioners_practitioner_id ON clinic_practitioners (practitioner_id);
-- L4: trigger tr_clinic_practitioners_inactive_photos is defined after the photos table (section 10).

-- Row-level security hides practitioners of other businesses. This lookup lets staff find an EXISTING
-- practitioner by registration number (exact match only, minimal fields) so they link him instead of
-- creating a duplicate. SECURITY DEFINER = runs as the owner, so it sees across businesses.
CREATE FUNCTION rp_find_practitioner_by_registration(p_number text)
RETURNS TABLE (id uuid, full_name varchar, specialty varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT p.id, p.full_name, p.specialty FROM practitioners p
   WHERE p.registration_number = upper(trim(p_number));
$$;

-- =====================================================================  3. CLINIC TEAM AND PORTFOLIO ALLOCATION
-- A user who is still a member can't be deleted (RESTRICT): deactivate the user or remove the membership first.
CREATE TABLE clinic_members (
  clinic_id   uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  role        varchar(32) NOT NULL,
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (clinic_id, user_id),
  CONSTRAINT ck_clinic_members_role CHECK (role IN ('clinic_administrator','clinic_team_member'))
);
CREATE INDEX ix_clinic_members_user_id ON clinic_members (user_id);

-- M4: a clinic can't lose its LAST active Clinic Administrator (delete, deactivate, role change or move).
-- Not checked when the clinic itself is being deleted.
CREATE FUNCTION rp_keep_one_clinic_admin() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF OLD.role = 'clinic_administrator' AND OLD.is_active
     AND (TG_OP = 'DELETE' OR NEW.role <> 'clinic_administrator' OR NOT NEW.is_active OR NEW.clinic_id <> OLD.clinic_id)
     AND EXISTS (SELECT 1 FROM clinics c WHERE c.id = OLD.clinic_id)
     AND NOT EXISTS (SELECT 1 FROM clinic_members m
                      WHERE m.clinic_id = OLD.clinic_id AND m.user_id <> OLD.user_id
                        AND m.role = 'clinic_administrator' AND m.is_active) THEN
    RAISE EXCEPTION 'clinic % must keep at least one active Clinic Administrator', OLD.clinic_id
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_clinic_members_keep_one_admin BEFORE UPDATE OR DELETE ON clinic_members
  FOR EACH ROW EXECUTE FUNCTION rp_keep_one_clinic_admin();

-- Each link must use the right kind of login:
--   clinic member -> 'clinic_member' · portfolio allocation -> 'digital_success_manager' · practitioner login -> 'practitioner'
-- So a practitioner's login can never be a clinic member (never a Clinic Administrator).
CREATE FUNCTION rp_check_user_role() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE wanted text := TG_ARGV[0];
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users u WHERE u.id = NEW.user_id AND u.platform_role = wanted) THEN
    RAISE EXCEPTION '% needs a user with platform_role %', TG_TABLE_NAME, wanted USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_clinic_members_role BEFORE INSERT OR UPDATE OF user_id ON clinic_members
  FOR EACH ROW EXECUTE FUNCTION rp_check_user_role('clinic_member');
CREATE TRIGGER tr_practitioners_user_role BEFORE INSERT OR UPDATE OF user_id ON practitioners
  FOR EACH ROW WHEN (NEW.user_id IS NOT NULL) EXECUTE FUNCTION rp_check_user_role('practitioner');

-- The checks above run when a LINK is made. This one closes the other door: a user's role can't be
-- changed while he is still linked (else a Clinic Administrator could become a 'practitioner' and stay a member).
-- To change a role: remove the links first, change the role, then link again with the right role.
CREATE FUNCTION rp_role_change_needs_no_links() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM clinic_members m WHERE m.user_id = NEW.id)
     OR EXISTS (SELECT 1 FROM portfolio_allocations d WHERE d.user_id = NEW.id)
     OR EXISTS (SELECT 1 FROM practitioners p WHERE p.user_id = NEW.id) THEN
    RAISE EXCEPTION 'cannot change platform_role of user %: remove the user''s clinic / portfolio / practitioner links first', NEW.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_users_role_change BEFORE UPDATE OF platform_role ON users
  FOR EACH ROW WHEN (NEW.platform_role IS DISTINCT FROM OLD.platform_role)
  EXECUTE FUNCTION rp_role_change_needs_no_links();

-- Portfolio Allocation: a whole Client Organization (all its clinics) is allocated to ONE active DSM.
-- My Client Portfolio = the client organizations where the DSM's row is active.
CREATE TABLE portfolio_allocations (
  client_organization_id  uuid NOT NULL REFERENCES client_organizations(id) ON DELETE CASCADE,
  user_id                 uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,  -- a DSM with allocations can't be deleted: deactivate
  is_active               boolean NOT NULL DEFAULT true,       -- past DSMs stay as inactive rows
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (client_organization_id, user_id)
);
CREATE UNIQUE INDEX uq_portfolio_allocations_one_active ON portfolio_allocations (client_organization_id) WHERE is_active;
CREATE INDEX ix_portfolio_allocations_user_id ON portfolio_allocations (user_id);
CREATE TRIGGER tr_portfolio_allocations_role BEFORE INSERT OR UPDATE OF user_id ON portfolio_allocations
  FOR EACH ROW EXECUTE FUNCTION rp_check_user_role('digital_success_manager');

-- =====================================================================  4. ONLINE PRESENCE AND REPORTS
-- url is cleaned by tr_clinic_online_profiles_clean_url before saving (see below).
CREATE TABLE clinic_online_profiles (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id     uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  platform      varchar(40) NOT NULL,
  url           varchar(1000) NOT NULL,
  external_id   varchar(255),
  display_name  varchar(255),
  verification  varchar(32) NOT NULL DEFAULT 'unverified',
  confidence    numeric(4,3),
  discovered_by varchar(128) NOT NULL,             -- which agent found it
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_clinic_online_profiles_clinic_platform_url UNIQUE (clinic_id, platform, url),
  -- The website lives in clinics.website_url (one source); this table is for the other platforms.
  CONSTRAINT ck_clinic_online_profiles_platform CHECK (platform IN
    ('google_business_profile','google_maps','instagram','facebook','youtube','linkedin','x','practo','justdial','other')),
  CONSTRAINT ck_clinic_online_profiles_verification CHECK (verification IN ('unverified','confirmed','rejected')),
  CONSTRAINT ck_clinic_online_profiles_confidence_range CHECK (confidence BETWEEN 0 AND 1)
);

-- M5: clean a profile URL so the same page can't be saved twice in slightly different forms:
-- trim, drop '#…', http -> https, add https:// if missing, lower-case host, drop 'www.', drop trailing '/'.
CREATE FUNCTION rp_clean_url(p_url text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v text; host text; rest text;
BEGIN
  v := regexp_replace(btrim(p_url), '#.*$', '');
  v := regexp_replace(v, '^http://', 'https://', 'i');
  IF v !~* '^https://' THEN v := 'https://' || v; END IF;
  host := substring(v from '^https://([^/?]+)');
  rest := coalesce(substring(v from '^https://[^/?]+(.*)$'), '');
  host := regexp_replace(lower(host), '^www\.', '');
  rest := regexp_replace(rest, '/+(\?|$)', '\1');
  RETURN 'https://' || host || rest;
END $$;
CREATE FUNCTION rp_clinic_online_profiles_clean_url() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.url := rp_clean_url(NEW.url);
  RETURN NEW;
END $$;
CREATE TRIGGER tr_clinic_online_profiles_clean_url BEFORE INSERT OR UPDATE OF url ON clinic_online_profiles
  FOR EACH ROW EXECUTE FUNCTION rp_clinic_online_profiles_clean_url();

CREATE TABLE digital_presence_assessments (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id           uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  digital_growth_report_id       varchar(128),
  status              varchar(32) NOT NULL DEFAULT 'queued',
  overall_score       numeric(5,2),
  summary             text,
  attempts            integer NOT NULL DEFAULT 0,
  last_error          text,
  started_at          timestamptz,
  completed_at        timestamptz,
  -- the DSM's review (was the separate table assessment_approvals, always 1 : 1)
  review_state        varchar(32) NOT NULL DEFAULT 'draft',
  review_note         text,
  reviewed_at         timestamptz,
  publication_state   varchar(32) NOT NULL DEFAULT 'unpublished',
  published_at        timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_digital_presence_assessments_id_clinic UNIQUE (id, clinic_id),
  CONSTRAINT uq_digital_presence_assessments_digital_growth_report_id UNIQUE (digital_growth_report_id),
  CONSTRAINT ck_digital_presence_assessments_status CHECK (status IN ('queued','running','completed','failed')),
  CONSTRAINT ck_digital_presence_assessments_review_state CHECK (review_state IN ('draft','submitted','approved','rejected','redo_requested')),
  CONSTRAINT ck_digital_presence_assessments_publication_state CHECK (publication_state IN ('unpublished','published','retracted')),
  -- the clinic sees a report only after the DSM approved it (was 2 deferred triggers, now 1 simple rule)
  CONSTRAINT ck_digital_presence_assessments_published_only_if_approved CHECK (publication_state <> 'published' OR review_state = 'approved'),
  CONSTRAINT ck_digital_presence_assessments_score_range CHECK (overall_score BETWEEN 0 AND 100),
  CONSTRAINT ck_digital_presence_assessments_attempts_not_negative CHECK (attempts >= 0),
  CONSTRAINT ck_digital_presence_assessments_finished_after_start CHECK (completed_at >= started_at),
  CONSTRAINT ck_digital_presence_assessments_published_has_date CHECK (publication_state <> 'published' OR published_at IS NOT NULL),
  CONSTRAINT ck_digital_presence_assessments_reviewed_has_date CHECK (review_state IN ('draft','submitted') OR reviewed_at IS NOT NULL)
);
-- A clinic's assessment list, newest first: ORDER BY created_at DESC.
CREATE INDEX ix_digital_presence_assessments_clinic_time ON digital_presence_assessments (clinic_id, created_at);
CREATE UNIQUE INDEX uq_digital_presence_assessments_one_in_progress ON digital_presence_assessments (clinic_id) WHERE status IN ('queued','running');

-- =====================================================================  5. WORK AND AUDIT
CREATE TABLE improvement_work_items (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id             uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  title                 varchar(200) NOT NULL,
  description           text,
  status                varchar(32) NOT NULL DEFAULT 'todo',
  priority              varchar(32) NOT NULL DEFAULT 'normal',
  source_assessment_id  uuid,                     -- filled = a "Fix Now" item from this assessment; empty = added by hand
  opportunity_code          varchar(96),
  assignee_user_id      uuid REFERENCES users(id) ON DELETE SET NULL,  -- who must do the work item
  due_at                timestamptz,
  completed_at          timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_improvement_work_items_source_assessment FOREIGN KEY (source_assessment_id, clinic_id)
    REFERENCES digital_presence_assessments (id, clinic_id),
  CONSTRAINT ck_improvement_work_items_status CHECK (status IN ('todo','in_progress','blocked','in_review','done','cancelled')),
  CONSTRAINT ck_improvement_work_items_priority CHECK (priority IN ('low','normal','high','urgent')),
  CONSTRAINT ck_improvement_work_items_completed_when_done CHECK ((status = 'done') = (completed_at IS NOT NULL)),
  CONSTRAINT ck_improvement_work_items_fix_now_has_code CHECK (source_assessment_id IS NULL OR opportunity_code IS NOT NULL)
);
CREATE INDEX ix_improvement_work_items_clinic_status ON improvement_work_items (clinic_id, status);
CREATE INDEX ix_improvement_work_items_assignee_user_id ON improvement_work_items (assignee_user_id) WHERE assignee_user_id IS NOT NULL;
CREATE INDEX ix_improvement_work_items_source_assessment ON improvement_work_items (source_assessment_id) WHERE source_assessment_id IS NOT NULL;
-- The assignee must belong to THIS clinic: an active member, a practitioner actively linked to it,
-- the active DSM of its Client Organization, or a Platform Administrator.
CREATE FUNCTION rp_check_work_item_assignee() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NEW.assignee_user_id IS NULL
     OR EXISTS (SELECT 1 FROM clinic_members m
                 WHERE m.clinic_id = NEW.clinic_id AND m.user_id = NEW.assignee_user_id AND m.is_active)
     OR EXISTS (SELECT 1 FROM clinic_practitioners cp JOIN practitioners p ON p.id = cp.practitioner_id
                 WHERE cp.clinic_id = NEW.clinic_id AND cp.is_active AND p.user_id = NEW.assignee_user_id)
     OR EXISTS (SELECT 1 FROM clinics c JOIN portfolio_allocations a ON a.client_organization_id = c.client_organization_id
                 WHERE c.id = NEW.clinic_id AND a.user_id = NEW.assignee_user_id AND a.is_active)
     OR EXISTS (SELECT 1 FROM users u
                 WHERE u.id = NEW.assignee_user_id AND u.platform_role = 'platform_administrator' AND u.is_active) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'assignee % does not belong to clinic %', NEW.assignee_user_id, NEW.clinic_id
    USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER tr_improvement_work_items_assignee BEFORE INSERT OR UPDATE OF assignee_user_id, clinic_id ON improvement_work_items
  FOR EACH ROW EXECUTE FUNCTION rp_check_work_item_assignee();
CREATE UNIQUE INDEX uq_improvement_work_items_one_open_per_opportunity ON improvement_work_items (clinic_id, opportunity_code)
  WHERE opportunity_code IS NOT NULL AND status NOT IN ('done','cancelled');

-- The ONE record of who did what (created, invited, assigned, uploaded, reviewed, connected, viewed ...).
-- Written in the SAME transaction as the change. Never updated or deleted.
-- No foreign keys on purpose: deleting a user or clinic must not change old log rows.
-- Append-only is ENFORCED by the triggers below.
CREATE TABLE audit_events (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  occurred_at    timestamptz NOT NULL DEFAULT now(),
  clinic_id      uuid,
  actor_user_id  uuid,
  actor_type     varchar(16) NOT NULL,
  action         varchar(64) NOT NULL,
  resource_type  varchar(64) NOT NULL,
  resource_id    varchar(64),
  request_id     varchar(128),
  details        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_audit_events_clinic_time ON audit_events (clinic_id, occurred_at);
CREATE INDEX ix_audit_events_resource ON audit_events (resource_type, resource_id, occurred_at);  -- "who uploaded / approved this?"

-- Enforced: rows can only be ADDED. UPDATE, DELETE and TRUNCATE are refused.
CREATE FUNCTION rp_audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only: rows cannot be changed or deleted'
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER tr_audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION rp_audit_events_append_only();
CREATE TRIGGER tr_audit_events_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION rp_audit_events_append_only();

-- =====================================================================  6. NOTIFICATIONS
CREATE TABLE notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  clinic_id   uuid REFERENCES clinics(id) ON DELETE CASCADE,
  category    varchar(40) NOT NULL,
  title       varchar(200) NOT NULL,
  body        text,
  link        varchar(500),
  read_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_notifications_user_created ON notifications (user_id, created_at, id);
CREATE INDEX ix_notifications_unread ON notifications (user_id, created_at) WHERE read_at IS NULL;
CREATE INDEX ix_notifications_clinic_id ON notifications (clinic_id) WHERE clinic_id IS NOT NULL;

CREATE TABLE notification_preferences (
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category    varchar(40) NOT NULL,
  channel     varchar(16) NOT NULL,
  is_enabled  boolean NOT NULL DEFAULT true,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, category, channel),
  CONSTRAINT ck_notification_preferences_category CHECK (category IN ('portfolio_allocated','work_item_assigned','approval_handoff','connection_needs_reconnect')),
  CONSTRAINT ck_notification_preferences_channel CHECK (channel IN ('in_app','email'))
);

-- =====================================================================  7. CLIENT COLLABORATION
CREATE TABLE collaboration_messages (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id        uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  sender_user_id   uuid REFERENCES users(id) ON DELETE SET NULL,
  sender_name      varchar(200) NOT NULL,
  sender_side      varchar(16) NOT NULL,
  body             text,
  attachment_key   varchar(512),
  attachment_name  varchar(255),
  parent_message_id uuid,                        -- reply count / last reply time are COUNTED from replies (not stored)
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_collaboration_messages_id_clinic UNIQUE (id, clinic_id),
  CONSTRAINT fk_collaboration_messages_parent FOREIGN KEY (parent_message_id, clinic_id)
    REFERENCES collaboration_messages (id, clinic_id) ON DELETE CASCADE,
  CONSTRAINT ck_collaboration_messages_not_own_parent CHECK (parent_message_id <> id),
  CONSTRAINT ck_collaboration_messages_sender_side CHECK (sender_side IN ('radial_pulse','clinic')),
  CONSTRAINT ck_collaboration_messages_body_or_attachment CHECK (body IS NOT NULL OR attachment_key IS NOT NULL),
  CONSTRAINT ck_collaboration_messages_attachment_key CHECK (attachment_key LIKE 'clinics/' || clinic_id || '/%'),
  CONSTRAINT ck_collaboration_messages_attachment_named CHECK ((attachment_key IS NULL) = (attachment_name IS NULL))
);
-- Collaboration list (replies included) = all rows of a clinic by time.
-- A thread = replies of one message, oldest first.
CREATE INDEX ix_collaboration_messages_clinic_time ON collaboration_messages (clinic_id, created_at, id);
CREATE INDEX ix_collaboration_messages_thread ON collaboration_messages (parent_message_id, created_at, id) WHERE parent_message_id IS NOT NULL;
CREATE INDEX ix_collaboration_messages_sender ON collaboration_messages (sender_user_id) WHERE sender_user_id IS NOT NULL;

-- Threads are ONE level deep: a reply can't have replies.
CREATE FUNCTION rp_collaboration_one_level_threads() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM collaboration_messages p WHERE p.id = NEW.parent_message_id AND p.parent_message_id IS NOT NULL) THEN
    RAISE EXCEPTION 'collaboration threads are one level deep: reply to the first message of the thread'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_collaboration_messages_one_level BEFORE INSERT ON collaboration_messages
  FOR EACH ROW WHEN (NEW.parent_message_id IS NOT NULL) EXECUTE FUNCTION rp_collaboration_one_level_threads();

-- =====================================================================  8. CONNECTED ACCOUNTS (OAuth)
CREATE TABLE connected_accounts (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id              uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  provider               varchar(24) NOT NULL,
  status                 varchar(24) NOT NULL DEFAULT 'connected',
  external_account_id    varchar(255) NOT NULL,
  external_account_name  varchar(255),
  scopes                 text[] NOT NULL DEFAULT '{}',
  secret_ref             varchar(512),
  token_expires_at       timestamptz,
  last_refreshed_at      timestamptz,
  last_error             text,
  connected_at           timestamptz,
  disconnected_at        timestamptz,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  -- Several logins per provider are allowed (e.g. practitioner's Google for the Business Profile,
  -- web developer's Google for Search Console), but the same login only once per clinic.
  CONSTRAINT uq_connected_accounts_clinic_provider_login UNIQUE (clinic_id, provider, external_account_id),
  CONSTRAINT uq_connected_accounts_id_clinic UNIQUE (id, clinic_id),
  -- instagram = "Instagram API with Instagram Login" (no Facebook Page needed); facebook = Facebook Pages.
  CONSTRAINT ck_connected_accounts_provider CHECK (provider IN ('google','instagram','facebook','linkedin','x')),
  CONSTRAINT ck_connected_accounts_status CHECK (status IN ('connected','needs_reconnect','disconnected')),
  CONSTRAINT ck_connected_accounts_connected_has_secret CHECK (status <> 'connected' OR secret_ref IS NOT NULL)
);

CREATE TABLE connected_account_resources (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  connected_account_id  uuid NOT NULL,
  clinic_id             uuid NOT NULL,
  resource_type         varchar(40) NOT NULL,
  external_id           varchar(255) NOT NULL,
  display_name          varchar(255),
  is_selected           boolean NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_connected_account_resources_account FOREIGN KEY (connected_account_id, clinic_id)
    REFERENCES connected_accounts (id, clinic_id) ON DELETE CASCADE,
  CONSTRAINT uq_connected_account_resources_account_type_external UNIQUE (connected_account_id, resource_type, external_id),
  CONSTRAINT ck_connected_account_resources_type CHECK (resource_type IN
    ('gbp_location','search_console_site','ga4_property','youtube_channel','instagram_account','facebook_page','linkedin_page','x_account'))
);
CREATE UNIQUE INDEX uq_connected_account_resources_one_selected
  ON connected_account_resources (clinic_id, resource_type) WHERE is_selected;
-- The same Business Profile location / website / page can be selected by ONLY ONE clinic
-- (otherwise clinic B could read clinic A's reviews and search data).
CREATE UNIQUE INDEX uq_connected_account_resources_selected_once
  ON connected_account_resources (resource_type, external_id) WHERE is_selected;
CREATE INDEX ix_connected_account_resources_clinic_id ON connected_account_resources (clinic_id);

CREATE TABLE oauth_states (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id           uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  provider            varchar(24) NOT NULL,
  state_hash          varchar(64) NOT NULL,
  code_verifier       varchar(128),
  redirect_uri        varchar(500) NOT NULL,
  started_by_user_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, -- KEPT: the callback must come from the SAME user
  expires_at          timestamptz NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_oauth_states_state_hash UNIQUE (state_hash),
  CONSTRAINT ck_oauth_states_expires_after_created CHECK (expires_at > created_at)
);
CREATE INDEX ix_oauth_states_clinic_id ON oauth_states (clinic_id);
CREATE INDEX ix_oauth_states_expires_at ON oauth_states (expires_at);
CREATE INDEX ix_oauth_states_started_by ON oauth_states (started_by_user_id);

-- No jobs table: the API calls this on every new "Connect" click, and a small daily scheduled
-- task calls it too. Returns how many expired tickets were removed.
CREATE FUNCTION rp_delete_expired_oauth_states() RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  WITH gone AS (DELETE FROM oauth_states WHERE expires_at < now() RETURNING 1) SELECT count(*)::int FROM gone;
$$;

-- =====================================================================  9. SETTINGS
CREATE TABLE platform_settings (
  id                 smallint PRIMARY KEY DEFAULT 1,
  support_email      varchar(320),
  support_phone      varchar(32),
  timezone           varchar(64) NOT NULL DEFAULT 'Asia/Kolkata',
  date_format        varchar(16) NOT NULL DEFAULT 'DD MMM YYYY',
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_platform_settings_single_row CHECK (id = 1)
);

-- =====================================================================  10. PHOTOS AND VOICE
-- Files live in a PRIVATE S3 bucket. The database stores only the file's S3 key + review status.
-- Who may change (upload / replace / delete): the Clinic Administrator, and a practitioner for his OWN files.
-- Who reviews PHOTOS (approve / ask re-upload / sort into a category): the clinic's DSM. The DSM cannot upload.
-- Voice samples have no review.
-- Nobody downloads: the API gives only short-lived VIEW links, and every view is written to audit_events.
-- Who uploaded / reviewed: audit_events. Approved = Verified = may be published by our system.
--
-- Photo review states:   database value -> what the app shows
--   pending  -> "Awaiting review"
--   approved -> "Verified"                    (review_note optional, e.g. "Good light, clear face")
--   rejected -> "Needs re-upload"             (review_note REQUIRED, e.g. "Photo is blurred")

-- 1. photos: practitioner photos AND hospital (clinic) photos, one row per uploaded file
CREATE TABLE photos (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id            uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,  -- needed: hospital photos have no practitioner

  -- practitioner photos only ("Five fixed angles per outfit, apron and non-apron"); empty = hospital photo
  practitioner_id      uuid,
  attire               varchar(16),               -- 'with_apron' / 'without_apron'
  outfit_no            smallint,                  -- 1, 2, 3 ... (app shows only Outfit 1 for now)
  angle                varchar(16),               -- 'left_90','left_45','front','right_45','right_90'

  -- clinic photos only ("Hospital photos")
  category             varchar(32),               -- NULL = "Uploaded photos, not yet sorted"; DSM sorts it

  -- the file
  original_key         varchar(512) NOT NULL,     -- S3 key of the original (private bucket)
  variants             jsonb NOT NULL DEFAULT '{}', -- {"thumb": key, "medium": key}
  mime_type            varchar(64)  NOT NULL,
  size_bytes           bigint       NOT NULL,
  width                integer,
  height               integer,
  processing_status    varchar(16)  NOT NULL DEFAULT 'uploading', -- uploading/processing/ready/failed

  -- the review
  review_state         varchar(16)  NOT NULL DEFAULT 'pending',   -- pending/approved/rejected
  review_note          text,                      -- reason when rejected; optional comment when approved
  reviewed_at          timestamptz,               -- WHO reviewed is in audit_events
  check_results        jsonb NOT NULL DEFAULT '{}', -- basic checks now, AI hints later
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),

  -- the practitioner must work at THIS clinic (same-clinic link)
  CONSTRAINT fk_photos_clinic_practitioner FOREIGN KEY (clinic_id, practitioner_id)
    REFERENCES clinic_practitioners (clinic_id, practitioner_id) ON DELETE CASCADE,
  CONSTRAINT ck_photos_attire   CHECK (attire IN ('with_apron','without_apron')),
  CONSTRAINT ck_photos_outfit   CHECK (outfit_no >= 1),
  CONSTRAINT ck_photos_angle    CHECK (angle IN ('left_90','left_45','front','right_45','right_90')),
  CONSTRAINT ck_photos_category CHECK (category IN ('exterior_signage','reception_waiting','consult_procedure_rooms',
                                                    'equipment_facilities','team_at_work','logo','cover')),
  -- practitioner photo   = practitioner + attire + outfit + angle, no category
  -- hospital photo = no practitioner fields; category may be empty only while NOT yet approved
  CONSTRAINT ck_photos_kind_fields CHECK (
    (practitioner_id IS NOT NULL AND attire IS NOT NULL AND outfit_no IS NOT NULL AND angle IS NOT NULL AND category IS NULL)
    OR
    (practitioner_id IS NULL AND attire IS NULL AND outfit_no IS NULL AND angle IS NULL
                             AND (category IS NOT NULL OR review_state <> 'approved'))),
  CONSTRAINT ck_photos_processing_status CHECK (processing_status IN ('uploading','processing','ready','failed')),
  CONSTRAINT ck_photos_review_state CHECK (review_state IN ('pending','approved','rejected')),
  CONSTRAINT ck_photos_rejected_has_note CHECK (review_state <> 'rejected' OR (review_note IS NOT NULL AND length(trim(review_note)) > 0)),
  CONSTRAINT ck_photos_reviewed_has_date CHECK (review_state = 'pending' OR reviewed_at IS NOT NULL),
  CONSTRAINT ck_photos_key_in_clinic_folder CHECK (original_key LIKE 'clinics/' || clinic_id || '/photos/%'),
  CONSTRAINT ck_photos_image_type CHECK (mime_type IN ('image/jpeg','image/png','image/webp','image/heic')),
  CONSTRAINT ck_photos_size_positive CHECK (size_bytes > 0)
);
-- Replace rule (pencil icon): the old approved photo stays live until the new one is approved, then the old one is deleted.
-- Practitioner: per clinic + practitioner + attire + outfit + angle -> at most 1 live + 1 waiting photo
CREATE UNIQUE INDEX uq_photos_practitioner_one_live ON photos (clinic_id, practitioner_id, attire, outfit_no, angle)
  WHERE practitioner_id IS NOT NULL AND review_state = 'approved';
CREATE UNIQUE INDEX uq_photos_practitioner_one_waiting ON photos (clinic_id, practitioner_id, attire, outfit_no, angle)
  WHERE practitioner_id IS NOT NULL AND review_state = 'pending';
-- Logo and cover: at most 1 live + 1 waiting per clinic. Other categories: no limit (3 is only a target).
CREATE UNIQUE INDEX uq_photos_logo_cover_one_live ON photos (clinic_id, category)
  WHERE category IN ('logo','cover') AND review_state = 'approved';
CREATE UNIQUE INDEX uq_photos_logo_cover_one_waiting ON photos (clinic_id, category)
  WHERE category IN ('logo','cover') AND review_state = 'pending';
CREATE INDEX ix_photos_clinic_practitioner ON photos (clinic_id, practitioner_id);
CREATE INDEX ix_photos_review_queue ON photos (clinic_id, created_at) WHERE review_state = 'pending';

-- L4: when a practitioner's link to a clinic becomes inactive, his APPROVED photos at that clinic stop being live.
--   no waiting replacement in that slot -> back to 'pending' (the DSM can approve again if he returns)
--   a waiting replacement already exists -> 'rejected' with a note (the slot allows only one waiting photo)
CREATE FUNCTION rp_inactive_practitioner_photos() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE photos p
     SET review_state = CASE WHEN w.id IS NULL THEN 'pending' ELSE 'rejected' END,
         review_note  = CASE WHEN w.id IS NULL THEN NULL ELSE 'Practitioner is no longer active at this clinic' END,
         reviewed_at  = CASE WHEN w.id IS NULL THEN NULL ELSE now() END
    FROM photos p2
    LEFT JOIN photos w ON w.clinic_id = p2.clinic_id AND w.practitioner_id = p2.practitioner_id
                      AND w.attire = p2.attire AND w.outfit_no = p2.outfit_no AND w.angle = p2.angle
                      AND w.review_state = 'pending'
   WHERE p.id = p2.id
     AND p2.clinic_id = NEW.clinic_id AND p2.practitioner_id = NEW.practitioner_id
     AND p2.review_state = 'approved';
  RETURN NULL;
END $$;
CREATE TRIGGER tr_clinic_practitioners_inactive_photos AFTER UPDATE OF is_active ON clinic_practitioners
  FOR EACH ROW WHEN (OLD.is_active AND NOT NEW.is_active) EXECUTE FUNCTION rp_inactive_practitioner_photos();

-- 2. voice_samples: a practitioner's recordings for the phone assistant
CREATE TABLE voice_samples (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id            uuid NOT NULL,             -- checked through the practitioner link below
  practitioner_id      uuid NOT NULL,             -- the practitioner whose voice it is
  title                varchar(120) NOT NULL,     -- "Reading sample 3", "Clinic greeting"
  original_key         varchar(512) NOT NULL,     -- S3 key (private bucket)
  mime_type            varchar(64)  NOT NULL,
  size_bytes           bigint       NOT NULL,
  duration_seconds     numeric(7,2),              -- filled after processing
  processing_status    varchar(16)  NOT NULL DEFAULT 'uploading',
  reviewed_at          timestamptz,
  check_results        jsonb NOT NULL DEFAULT '{}', -- e.g. noise level, later
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_voice_samples_clinic_practitioner FOREIGN KEY (clinic_id, practitioner_id)
    REFERENCES clinic_practitioners (clinic_id, practitioner_id) ON DELETE CASCADE,
  CONSTRAINT ck_voice_samples_title CHECK (length(trim(title)) > 0),
  CONSTRAINT ck_voice_samples_processing_status CHECK (processing_status IN ('uploading','processing','ready','failed')),
  CONSTRAINT ck_voice_samples_key_in_clinic_folder CHECK (original_key LIKE 'clinics/' || clinic_id || '/voice/%'),
  CONSTRAINT ck_voice_samples_audio_type CHECK (mime_type LIKE 'audio/%'),
  CONSTRAINT ck_voice_samples_size_positive CHECK (size_bytes > 0),
  CONSTRAINT ck_voice_samples_duration CHECK (duration_seconds > 0)
);
-- A practitioner can't use the same title twice at a clinic ("Clinic greeting" = "clinic greeting").
-- The API turns this error into the message: "This title is already used. Please give another title."
CREATE UNIQUE INDEX uq_voice_samples_one_per_title ON voice_samples (clinic_id, practitioner_id, lower(title));
CREATE INDEX ix_voice_samples_practitioner ON voice_samples (clinic_id, practitioner_id, created_at);

-- =====================================================================  11. updated_at, SET AUTOMATICALLY
-- Every table with an updated_at column gets it set to now() on every UPDATE, so the app can't forget.
CREATE FUNCTION rp_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER tr_client_organizations_updated_at BEFORE UPDATE ON client_organizations FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_clinic_members_updated_at BEFORE UPDATE ON clinic_members FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_clinic_online_profiles_updated_at BEFORE UPDATE ON clinic_online_profiles FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_clinic_practitioners_updated_at BEFORE UPDATE ON clinic_practitioners FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_clinic_profiles_updated_at BEFORE UPDATE ON clinic_profiles FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_clinics_updated_at BEFORE UPDATE ON clinics FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_connected_account_resources_updated_at BEFORE UPDATE ON connected_account_resources FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_connected_accounts_updated_at BEFORE UPDATE ON connected_accounts FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_digital_presence_assessments_updated_at BEFORE UPDATE ON digital_presence_assessments FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_improvement_work_items_updated_at BEFORE UPDATE ON improvement_work_items FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_notification_preferences_updated_at BEFORE UPDATE ON notification_preferences FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_photos_updated_at BEFORE UPDATE ON photos FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_platform_settings_updated_at BEFORE UPDATE ON platform_settings FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_portfolio_allocations_updated_at BEFORE UPDATE ON portfolio_allocations FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
-- v15: a year (practice start, clinic established) can't be in the future.
-- Done in a trigger, not a CHECK: PostgreSQL assumes CHECK conditions never change, and "today" does.
CREATE FUNCTION rp_year_not_in_future() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE y int := (to_jsonb(NEW) ->> TG_ARGV[0])::int;
BEGIN
  IF y IS NOT NULL AND y > extract(year FROM current_date)::int THEN
    RAISE EXCEPTION '% (%) cannot be in the future', TG_ARGV[0], y USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_practitioners_start_year BEFORE INSERT OR UPDATE OF practice_start_year ON practitioners
  FOR EACH ROW EXECUTE FUNCTION rp_year_not_in_future('practice_start_year');
CREATE TRIGGER tr_clinics_established_year BEFORE INSERT OR UPDATE OF established_year ON clinics
  FOR EACH ROW EXECUTE FUNCTION rp_year_not_in_future('established_year');
-- v15: consultation_time_zone must be a real time zone name (PostgreSQL knows the list).
CREATE FUNCTION rp_check_time_zone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = NEW.consultation_time_zone) THEN
    RAISE EXCEPTION 'consultation_time_zone "%" is not a known time zone (e.g. Asia/Kolkata)', NEW.consultation_time_zone
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_clinic_practitioners_time_zone BEFORE INSERT OR UPDATE OF consultation_time_zone ON clinic_practitioners
  FOR EACH ROW EXECUTE FUNCTION rp_check_time_zone();
CREATE TRIGGER tr_practitioners_updated_at BEFORE UPDATE ON practitioners FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();
CREATE TRIGGER tr_voice_samples_updated_at BEFORE UPDATE ON voice_samples FOR EACH ROW EXECUTE FUNCTION rp_set_updated_at();

-- =====================================================================  12. ACCESS RULES (ROW-LEVEL SECURITY)
-- Who may SEE or CHANGE which rows. The database checks this on every query, so a missing filter in the
-- API code can't leak another clinic's data. It is a safety net under the API's own checks.
--
-- How the API uses it, in EVERY transaction (after verifying the Cognito token):
--   SET LOCAL ROLE radial_app;                       -- the app's database role (row security applies)
--   SET LOCAL rp.user_id = '<users.id of the caller>';
-- Trusted background jobs (image processing, agents' results, notifications) instead set:
--   SET LOCAL rp.actor = 'system';
-- Service-to-service calls (/internal, e.g. the Digital Growth Team) use role radial_service: read-only.
-- The table owner (migrations) is not limited by these rules.
--
-- Who is who (from users.platform_role + links):
--   admin        = Platform Administrator
--   DSM          = Digital Success Manager with an ACTIVE portfolio allocation for the clinic's Client Organization
--   clinic admin = active clinic_members row with role 'clinic_administrator'
--   team member  = active clinic_members row with role 'clinic_team_member' (read only)
--   practitioner = practitioner login, ACTIVELY linked to the clinic (clinic_practitioners.is_active)

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radial_app') THEN CREATE ROLE radial_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radial_service') THEN CREATE ROLE radial_service NOLOGIN; END IF;
END $$;

-- ---------- helper functions (SECURITY DEFINER: they read the link tables without being limited themselves)
CREATE FUNCTION rp_uid() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('rp.user_id', true), '')::uuid
$$;
CREATE FUNCTION rp_is_system() RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT coalesce(current_setting('rp.actor', true), '') = 'system'
$$;
CREATE FUNCTION rp_is_admin() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM users u WHERE u.id = rp_uid() AND u.is_active AND u.platform_role = 'platform_administrator')
$$;
CREATE FUNCTION rp_is_any_dsm() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM users u WHERE u.id = rp_uid() AND u.is_active AND u.platform_role = 'digital_success_manager')
$$;
CREATE FUNCTION rp_is_dsm_of_org(p_org uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM portfolio_allocations a JOIN users u ON u.id = a.user_id
                  WHERE a.client_organization_id = p_org AND a.user_id = rp_uid() AND a.is_active AND u.is_active)
$$;
CREATE FUNCTION rp_is_dsm_of_clinic(p_clinic uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM clinics c WHERE c.id = p_clinic AND rp_is_dsm_of_org(c.client_organization_id))
$$;
CREATE FUNCTION rp_member_role(p_clinic uuid) RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT m.role FROM clinic_members m JOIN users u ON u.id = m.user_id
   WHERE m.clinic_id = p_clinic AND m.user_id = rp_uid() AND m.is_active AND u.is_active
$$;
CREATE FUNCTION rp_my_practitioner_id() RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT p.id FROM practitioners p JOIN users u ON u.id = p.user_id WHERE p.user_id = rp_uid() AND u.is_active
$$;
CREATE FUNCTION rp_is_linked_practitioner(p_clinic uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM clinic_practitioners cp
                  WHERE cp.clinic_id = p_clinic AND cp.practitioner_id = rp_my_practitioner_id() AND cp.is_active)
$$;
-- Radial Pulse staff for this clinic: admin or its DSM
CREATE FUNCTION rp_is_staff(p_clinic uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT rp_is_admin() OR rp_is_dsm_of_clinic(p_clinic)
$$;
-- may manage the clinic: staff or its clinic admin
CREATE FUNCTION rp_can_manage(p_clinic uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT rp_is_staff(p_clinic) OR rp_member_role(p_clinic) = 'clinic_administrator'
$$;
-- clinic team: staff + any active member (admin or team member)
CREATE FUNCTION rp_is_team(p_clinic uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT rp_is_staff(p_clinic) OR rp_member_role(p_clinic) IS NOT NULL
$$;
-- may see the clinic at all: team + actively linked practitioner
CREATE FUNCTION rp_can_see(p_clinic uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT rp_is_team(p_clinic) OR rp_is_linked_practitioner(p_clinic)
$$;
-- may see another user's row: self, admin, or that user works on a clinic I can see
CREATE FUNCTION rp_can_see_user(p_user uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT p_user = rp_uid() OR rp_is_admin()
      OR EXISTS (SELECT 1 FROM clinic_members m WHERE m.user_id = p_user AND rp_can_see(m.clinic_id))
      OR EXISTS (SELECT 1 FROM practitioners p JOIN clinic_practitioners cp ON cp.practitioner_id = p.id
                  WHERE p.user_id = p_user AND rp_can_see(cp.clinic_id))
      OR EXISTS (SELECT 1 FROM portfolio_allocations a JOIN clinics c ON c.client_organization_id = a.client_organization_id
                  WHERE a.user_id = p_user AND a.is_active AND rp_can_see(c.id))
$$;
-- may see a practitioner record: admin, the practitioner himself, or he is linked to a clinic I can see
CREATE FUNCTION rp_can_see_practitioner(p_practitioner uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT rp_is_admin() OR p_practitioner = rp_my_practitioner_id()
      OR EXISTS (SELECT 1 FROM clinic_practitioners cp WHERE cp.practitioner_id = p_practitioner AND rp_can_see(cp.clinic_id))
$$;
-- H5: may edit the SHARED practitioner record: admin, a DSM of a clinic he is linked to, or the practitioner himself.
-- (A Clinic Administrator can't: the record is shared with other businesses.)
CREATE FUNCTION rp_can_edit_practitioner(p_practitioner uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT rp_is_admin() OR p_practitioner = rp_my_practitioner_id()
      OR EXISTS (SELECT 1 FROM clinic_practitioners cp WHERE cp.practitioner_id = p_practitioner AND rp_is_dsm_of_clinic(cp.clinic_id))
$$;

-- First sign-in: the API knows only the token's sub + email, not yet users.id, so it can't pass the rules above.
-- Returns the user for this Cognito sub; on the very first sign-in links the invited user (same email, no sub yet).
CREATE FUNCTION rp_user_for_login(p_sub text, p_email text)
RETURNS TABLE (id uuid, platform_role varchar, is_active boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE users u SET cognito_sub = p_sub, last_login_at = now()
   WHERE u.cognito_sub IS NULL AND u.email = lower(trim(p_email))
     AND NOT EXISTS (SELECT 1 FROM users x WHERE x.cognito_sub = p_sub);
  RETURN QUERY SELECT u.id, u.platform_role, u.is_active FROM users u WHERE u.cognito_sub = p_sub;
END $$;

-- ---------- guards: things the rules can't express per column (only apply when row security is active)
-- users: only an admin changes someone's role, active flag, email or Cognito link
CREATE FUNCTION rp_users_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF row_security_active(TG_RELID) AND NOT rp_is_admin() AND NOT rp_is_system()
     AND (NEW.platform_role IS DISTINCT FROM OLD.platform_role OR NEW.is_active IS DISTINCT FROM OLD.is_active
          OR NEW.email IS DISTINCT FROM OLD.email OR NEW.cognito_sub IS DISTINCT FROM OLD.cognito_sub) THEN
    RAISE EXCEPTION 'only a Platform Administrator can change role, active flag, email or login link'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_users_guard BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION rp_users_guard();

-- clinics: only staff (admin / DSM) move the stage, archive/restore, or change the Client Organization
CREATE FUNCTION rp_clinics_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF row_security_active(TG_RELID) AND NOT rp_is_staff(OLD.id) AND NOT rp_is_system()
     AND (NEW.stage IS DISTINCT FROM OLD.stage OR NEW.is_active IS DISTINCT FROM OLD.is_active
          OR NEW.archived_reason IS DISTINCT FROM OLD.archived_reason
          OR NEW.client_organization_id IS DISTINCT FROM OLD.client_organization_id) THEN
    RAISE EXCEPTION 'only the DSM or a Platform Administrator can change stage, archive or Client Organization'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_clinics_guard BEFORE UPDATE ON clinics FOR EACH ROW EXECUTE FUNCTION rp_clinics_guard();

-- practitioners: name, registration number and login link only by staff (admin / DSM)
CREATE FUNCTION rp_practitioners_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF row_security_active(TG_RELID) AND NOT rp_is_admin() AND NOT rp_is_system()
     AND NOT EXISTS (SELECT 1 FROM clinic_practitioners cp WHERE cp.practitioner_id = OLD.id AND rp_is_dsm_of_clinic(cp.clinic_id))
     AND (NEW.full_name IS DISTINCT FROM OLD.full_name OR NEW.registration_number IS DISTINCT FROM OLD.registration_number
          OR NEW.user_id IS DISTINCT FROM OLD.user_id) THEN
    RAISE EXCEPTION 'only the DSM or a Platform Administrator can change name, registration number or login'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_practitioners_guard BEFORE UPDATE ON practitioners FOR EACH ROW EXECUTE FUNCTION rp_practitioners_guard();

-- photos: only staff (admin / DSM) review: review_state, review_note, reviewed_at, and sorting into a category
CREATE FUNCTION rp_photos_review_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF row_security_active(TG_RELID) AND NOT rp_is_staff(NEW.clinic_id) AND NOT rp_is_system()
     AND (NEW.review_state IS DISTINCT FROM (CASE WHEN TG_OP = 'INSERT' THEN 'pending' ELSE OLD.review_state END)
          OR NEW.reviewed_at IS DISTINCT FROM (CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.reviewed_at END)
          OR NEW.review_note IS DISTINCT FROM (CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.review_note END)
          OR (TG_OP = 'UPDATE' AND NEW.category IS DISTINCT FROM OLD.category)) THEN
    RAISE EXCEPTION 'only the DSM or a Platform Administrator can review or sort photos'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_photos_review_guard BEFORE INSERT OR UPDATE ON photos FOR EACH ROW EXECUTE FUNCTION rp_photos_review_guard();

-- ---------- turn row security on for all 22 tables
ALTER TABLE users                       ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_organizations        ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinics                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinic_profiles             ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinic_stage_changes        ENABLE ROW LEVEL SECURITY;
ALTER TABLE practitioners               ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinic_practitioners        ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinic_members              ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_allocations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinic_online_profiles      ENABLE ROW LEVEL SECURITY;
ALTER TABLE digital_presence_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE improvement_work_items      ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events                ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications               ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_preferences    ENABLE ROW LEVEL SECURITY;
ALTER TABLE collaboration_messages      ENABLE ROW LEVEL SECURITY;
ALTER TABLE connected_accounts          ENABLE ROW LEVEL SECURITY;
ALTER TABLE connected_account_resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_states                ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform_settings           ENABLE ROW LEVEL SECURITY;
ALTER TABLE photos                      ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_samples               ENABLE ROW LEVEL SECURITY;

-- ---------- rules for the app (radial_app). "system" = trusted background job.
-- users
CREATE POLICY users_select ON users FOR SELECT TO radial_app USING (rp_is_system() OR rp_can_see_user(id));
CREATE POLICY users_insert ON users FOR INSERT TO radial_app WITH CHECK (    -- invites
  rp_is_system() OR rp_is_admin()
  OR ((rp_is_any_dsm() OR EXISTS (SELECT 1 FROM clinic_members m WHERE m.user_id = rp_uid() AND m.role = 'clinic_administrator' AND m.is_active))
      AND platform_role IN ('clinic_member','practitioner')));
CREATE POLICY users_update ON users FOR UPDATE TO radial_app USING (rp_is_system() OR rp_is_admin() OR id = rp_uid());
CREATE POLICY users_delete ON users FOR DELETE TO radial_app USING (rp_is_admin());

-- client_organizations
CREATE POLICY orgs_select ON client_organizations FOR SELECT TO radial_app USING (
  rp_is_system() OR rp_is_admin() OR rp_is_dsm_of_org(id)
  OR EXISTS (SELECT 1 FROM clinics c WHERE c.client_organization_id = client_organizations.id AND rp_can_see(c.id)));
CREATE POLICY orgs_insert ON client_organizations FOR INSERT TO radial_app WITH CHECK (rp_is_admin());
CREATE POLICY orgs_update ON client_organizations FOR UPDATE TO radial_app USING (rp_is_admin());
CREATE POLICY orgs_delete ON client_organizations FOR DELETE TO radial_app USING (rp_is_admin());

-- clinics: new leads are added and seen only by the Platform Administrator until a DSM is allocated
CREATE POLICY clinics_select ON clinics FOR SELECT TO radial_app USING (rp_is_system() OR rp_can_see(id));
CREATE POLICY clinics_insert ON clinics FOR INSERT TO radial_app WITH CHECK (rp_is_admin());
CREATE POLICY clinics_update ON clinics FOR UPDATE TO radial_app USING (rp_is_system() OR rp_can_manage(id));
CREATE POLICY clinics_delete ON clinics FOR DELETE TO radial_app USING (rp_is_admin());

-- clinic_profiles
CREATE POLICY profiles_select ON clinic_profiles FOR SELECT TO radial_app USING (rp_is_system() OR rp_can_see(clinic_id));
CREATE POLICY profiles_write  ON clinic_profiles FOR ALL    TO radial_app USING (rp_can_manage(clinic_id)) WITH CHECK (rp_can_manage(clinic_id));

-- clinic_stage_changes: read by staff; rows are written only by the stage trigger
CREATE POLICY stage_select ON clinic_stage_changes FOR SELECT TO radial_app USING (rp_is_staff(clinic_id));

-- practitioners (H5)
CREATE POLICY prac_select ON practitioners FOR SELECT TO radial_app USING (rp_is_system() OR rp_can_see_practitioner(id));
CREATE POLICY prac_insert ON practitioners FOR INSERT TO radial_app WITH CHECK (
  rp_is_admin() OR rp_is_any_dsm()
  OR EXISTS (SELECT 1 FROM clinic_members m WHERE m.user_id = rp_uid() AND m.role = 'clinic_administrator' AND m.is_active));
CREATE POLICY prac_update ON practitioners FOR UPDATE TO radial_app USING (rp_is_system() OR rp_can_edit_practitioner(id));
CREATE POLICY prac_delete ON practitioners FOR DELETE TO radial_app USING (rp_is_admin());

-- clinic_practitioners (designation, hours, main practitioner at THIS clinic)
CREATE POLICY cprac_select ON clinic_practitioners FOR SELECT TO radial_app USING (rp_is_system() OR rp_can_see(clinic_id));
CREATE POLICY cprac_write  ON clinic_practitioners FOR ALL    TO radial_app USING (rp_can_manage(clinic_id)) WITH CHECK (rp_can_manage(clinic_id));

-- clinic_members (practitioners don't see the team list)
CREATE POLICY members_select ON clinic_members FOR SELECT TO radial_app USING (rp_is_system() OR rp_is_team(clinic_id) OR user_id = rp_uid());
CREATE POLICY members_write  ON clinic_members FOR ALL    TO radial_app USING (rp_can_manage(clinic_id)) WITH CHECK (rp_can_manage(clinic_id));

-- portfolio_allocations: only a Platform Administrator allocates
CREATE POLICY alloc_select ON portfolio_allocations FOR SELECT TO radial_app USING (
  rp_is_system() OR rp_is_admin() OR user_id = rp_uid()
  OR EXISTS (SELECT 1 FROM clinics c WHERE c.client_organization_id = portfolio_allocations.client_organization_id AND rp_is_team(c.id)));
CREATE POLICY alloc_write ON portfolio_allocations FOR ALL TO radial_app USING (rp_is_admin()) WITH CHECK (rp_is_admin());

-- clinic_online_profiles: a clinic admin may add; only staff confirm / remove
CREATE POLICY online_select ON clinic_online_profiles FOR SELECT TO radial_app USING (rp_is_system() OR rp_can_see(clinic_id));
CREATE POLICY online_insert ON clinic_online_profiles FOR INSERT TO radial_app WITH CHECK (rp_is_system() OR rp_can_manage(clinic_id));
CREATE POLICY online_update ON clinic_online_profiles FOR UPDATE TO radial_app USING (rp_is_system() OR rp_is_staff(clinic_id));
CREATE POLICY online_delete ON clinic_online_profiles FOR DELETE TO radial_app USING (rp_is_staff(clinic_id));

-- digital_presence_assessments: staff see all; clinic people and practitioners see only PUBLISHED reports
CREATE POLICY dpa_select ON digital_presence_assessments FOR SELECT TO radial_app USING (
  rp_is_system() OR rp_is_staff(clinic_id) OR (publication_state = 'published' AND rp_can_see(clinic_id)));
CREATE POLICY dpa_write ON digital_presence_assessments FOR ALL TO radial_app
  USING (rp_is_system() OR rp_is_staff(clinic_id)) WITH CHECK (rp_is_system() OR rp_is_staff(clinic_id));

-- improvement_work_items: team sees; the assignee sees his own; staff change
CREATE POLICY work_select ON improvement_work_items FOR SELECT TO radial_app USING (
  rp_is_system() OR rp_is_team(clinic_id) OR assignee_user_id = rp_uid());
CREATE POLICY work_write ON improvement_work_items FOR ALL TO radial_app
  USING (rp_is_staff(clinic_id)) WITH CHECK (rp_is_staff(clinic_id));

-- audit_events: anyone signed in (or a job) may ADD; staff and the clinic admin may read the clinic's log
CREATE POLICY audit_select ON audit_events FOR SELECT TO radial_app USING (
  rp_is_admin() OR (clinic_id IS NOT NULL AND (rp_is_dsm_of_clinic(clinic_id) OR rp_member_role(clinic_id) = 'clinic_administrator')));
CREATE POLICY audit_insert ON audit_events FOR INSERT TO radial_app WITH CHECK (rp_is_system() OR rp_uid() IS NOT NULL);

-- notifications: each person sees and marks only his own; the app/jobs create them for others
CREATE POLICY notif_select ON notifications FOR SELECT TO radial_app USING (user_id = rp_uid());
CREATE POLICY notif_insert ON notifications FOR INSERT TO radial_app WITH CHECK (rp_is_system() OR rp_uid() IS NOT NULL);
CREATE POLICY notif_update ON notifications FOR UPDATE TO radial_app USING (user_id = rp_uid());
CREATE POLICY notif_delete ON notifications FOR DELETE TO radial_app USING (user_id = rp_uid());

-- notification_preferences: own only
CREATE POLICY prefs_all ON notification_preferences FOR ALL TO radial_app USING (user_id = rp_uid()) WITH CHECK (user_id = rp_uid());

-- collaboration_messages: everyone who sees the clinic reads; team members are read-only;
-- you can only send as yourself; messages are not edited (an admin may delete)
CREATE POLICY msg_select ON collaboration_messages FOR SELECT TO radial_app USING (rp_can_see(clinic_id));
CREATE POLICY msg_insert ON collaboration_messages FOR INSERT TO radial_app WITH CHECK (
  sender_user_id = rp_uid() AND (rp_can_manage(clinic_id) OR rp_is_linked_practitioner(clinic_id)));
CREATE POLICY msg_delete ON collaboration_messages FOR DELETE TO radial_app USING (rp_is_admin());

-- connected accounts (practitioners don't see them)
CREATE POLICY ca_select ON connected_accounts FOR SELECT TO radial_app USING (rp_is_system() OR rp_is_team(clinic_id));
CREATE POLICY ca_write  ON connected_accounts FOR ALL    TO radial_app
  USING (rp_is_system() OR rp_can_manage(clinic_id)) WITH CHECK (rp_is_system() OR rp_can_manage(clinic_id));
CREATE POLICY car_select ON connected_account_resources FOR SELECT TO radial_app USING (rp_is_system() OR rp_is_team(clinic_id));
CREATE POLICY car_write  ON connected_account_resources FOR ALL    TO radial_app
  USING (rp_is_system() OR rp_can_manage(clinic_id)) WITH CHECK (rp_is_system() OR rp_can_manage(clinic_id));

-- oauth_states: only the person who clicked "Connect"
CREATE POLICY oauth_all ON oauth_states FOR ALL TO radial_app
  USING (started_by_user_id = rp_uid()) WITH CHECK (started_by_user_id = rp_uid() AND rp_can_manage(clinic_id));

-- platform_settings: everyone signed in reads; admin changes
CREATE POLICY settings_select ON platform_settings FOR SELECT TO radial_app USING (rp_is_system() OR rp_uid() IS NOT NULL);
CREATE POLICY settings_update ON platform_settings FOR UPDATE TO radial_app USING (rp_is_admin());

-- photos: all who see the clinic view; upload/delete by the clinic admin, or the practitioner for his OWN photos
-- (the DSM and team members can't upload); review by staff (enforced by tr_photos_review_guard)
CREATE POLICY photos_select ON photos FOR SELECT TO radial_app USING (rp_is_system() OR rp_can_see(clinic_id));
CREATE POLICY photos_insert ON photos FOR INSERT TO radial_app WITH CHECK (
  rp_member_role(clinic_id) = 'clinic_administrator'
  OR (practitioner_id = rp_my_practitioner_id() AND rp_is_linked_practitioner(clinic_id)));
CREATE POLICY photos_update ON photos FOR UPDATE TO radial_app USING (
  rp_is_system() OR rp_is_staff(clinic_id) OR rp_member_role(clinic_id) = 'clinic_administrator'
  OR (practitioner_id = rp_my_practitioner_id() AND rp_is_linked_practitioner(clinic_id)));
CREATE POLICY photos_delete ON photos FOR DELETE TO radial_app USING (
  rp_member_role(clinic_id) = 'clinic_administrator'
  OR (practitioner_id = rp_my_practitioner_id() AND rp_is_linked_practitioner(clinic_id)));

-- voice_samples: staff, the clinic admin and the practitioner himself (team members don't see voice)
CREATE POLICY voice_select ON voice_samples FOR SELECT TO radial_app USING (
  rp_is_system() OR rp_is_staff(clinic_id) OR rp_member_role(clinic_id) = 'clinic_administrator'
  OR practitioner_id = rp_my_practitioner_id());
CREATE POLICY voice_write ON voice_samples FOR ALL TO radial_app
  USING (rp_is_system() OR rp_member_role(clinic_id) = 'clinic_administrator'
         OR (practitioner_id = rp_my_practitioner_id() AND rp_is_linked_practitioner(clinic_id)))
  WITH CHECK (rp_is_system() OR rp_member_role(clinic_id) = 'clinic_administrator'
         OR (practitioner_id = rp_my_practitioner_id() AND rp_is_linked_practitioner(clinic_id)));

-- ---------- rules for backend services (radial_service): READ ONLY, what the internal API serves
CREATE POLICY svc_read ON client_organizations   FOR SELECT TO radial_service USING (true);
CREATE POLICY svc_read ON clinics                FOR SELECT TO radial_service USING (true);
CREATE POLICY svc_read ON clinic_profiles        FOR SELECT TO radial_service USING (true);
CREATE POLICY svc_read ON practitioners          FOR SELECT TO radial_service USING (true);
CREATE POLICY svc_read ON clinic_practitioners   FOR SELECT TO radial_service USING (true);
CREATE POLICY svc_read ON clinic_online_profiles FOR SELECT TO radial_service USING (true);
CREATE POLICY svc_read ON photos                 FOR SELECT TO radial_service USING (review_state = 'approved');
CREATE POLICY svc_read ON connected_accounts     FOR SELECT TO radial_service USING (true);
CREATE POLICY svc_read ON connected_account_resources FOR SELECT TO radial_service USING (true);

-- ---------- table permissions
GRANT USAGE ON SCHEMA public TO radial_app, radial_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO radial_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM radial_app;                 -- append-only (also a trigger)
REVOKE INSERT, UPDATE, DELETE ON clinic_stage_changes FROM radial_app;          -- written by the stage trigger only
REVOKE INSERT, DELETE ON platform_settings FROM radial_app;                     -- exactly one row
GRANT SELECT ON client_organizations, clinics, clinic_profiles, practitioners, clinic_practitioners,
                clinic_online_profiles, photos, connected_account_resources TO radial_service;
GRANT SELECT (id, clinic_id, provider, status, external_account_id, external_account_name, scopes,
              token_expires_at, last_refreshed_at, last_error, connected_at, disconnected_at, created_at, updated_at)
  ON connected_accounts TO radial_service;                                      -- never secret_ref
REVOKE EXECUTE ON FUNCTION rp_user_for_login(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rp_user_for_login(text, text) TO radial_app;
