-- Runs once when the local postgres container is first created (docker-entrypoint-initdb.d).
--
-- Roles (same model as AWS, see docs/architecture/multi-tenancy.md):
--   radial            owner / migrator (POSTGRES_USER). Runs Alembic. Not restricted by RLS.
--   radial_app        NOLOGIN group role. Migration 0004 grants it DML + applies RLS policies.
--   radial_app_local  what the LOCAL API and worker log in as (member of radial_app).
-- Passwords here are for a throwaway local container only.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radial_app') THEN
    CREATE ROLE radial_app NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radial_app_local') THEN
    CREATE ROLE radial_app_local LOGIN PASSWORD 'radial_app_local_only' IN ROLE radial_app;
  END IF;
END $$;

-- A separate database for the PostgreSQL test suite (nx run api:integration-test).
CREATE DATABASE radial_pulse_test OWNER radial;
