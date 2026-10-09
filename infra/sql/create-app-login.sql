-- Create the API's database login on Aurora: radial_api_iam (IAM auth, no password).
-- Run ONCE, AFTER the v15 baseline migration, as the master/owner login, on database radial_pulse:
--   psql "host=<endpoint> dbname=radial_pulse user=radial sslmode=require" -v ON_ERROR_STOP=1 -f infra/sql/create-app-login.sql
-- Safe to run again. Runbook: docs/infrastructure/central-dev-db-setup.md
--
-- radial_api_iam must NOT own tables and must never be the master user (CLAUDE.md rule 4):
-- the table owner skips all access rules.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radial_app') THEN
    RAISE EXCEPTION 'role radial_app is missing: run the v15 baseline migration first';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam') THEN
    RAISE EXCEPTION 'role rds_iam is missing: this is not RDS/Aurora, or IAM auth is off';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radial_api_iam') THEN
    CREATE ROLE radial_api_iam LOGIN;  -- defaults: NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  END IF;
END $$;

GRANT radial_app TO radial_api_iam;      -- user requests: SET LOCAL ROLE radial_app
GRANT radial_service TO radial_api_iam;  -- /api/v1/internal (other teams, read only): SET LOCAL ROLE radial_service
GRANT rds_iam TO radial_api_iam;         -- log in with an IAM token instead of a password

-- Checks: every value in the "ok" column must be true.
SELECT 'can log in'                    AS check_name, rolcanlogin             AS ok FROM pg_roles WHERE rolname = 'radial_api_iam'
UNION ALL
SELECT 'not superuser',                NOT rolsuper                                FROM pg_roles WHERE rolname = 'radial_api_iam'
UNION ALL
SELECT 'does not bypass access rules', NOT rolbypassrls                            FROM pg_roles WHERE rolname = 'radial_api_iam'
UNION ALL
SELECT 'member of radial_app',         pg_has_role('radial_api_iam', 'radial_app', 'MEMBER')
UNION ALL
SELECT 'member of radial_service',     pg_has_role('radial_api_iam', 'radial_service', 'MEMBER')
UNION ALL
SELECT 'has rds_iam',                 pg_has_role('radial_api_iam', 'rds_iam', 'MEMBER')
UNION ALL
SELECT 'not rds_superuser',            NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_superuser'
                                                     AND pg_has_role('radial_api_iam', 'rds_superuser', 'MEMBER'))
UNION ALL
SELECT 'owns no tables',               NOT EXISTS (SELECT 1 FROM pg_tables WHERE tableowner = 'radial_api_iam');
