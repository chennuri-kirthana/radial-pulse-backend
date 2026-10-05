## What changed (plain words)

## Checklist
- [ ] Tests for the new behaviour (and a line in `tests/api/test_tenant_isolation.py` for a new clinic route)
- [ ] `make check` passes; `make integration-test` if models/migrations/SQL changed
- [ ] New table with `clinic_id` (or any new table) has row-level security in its migration
- [ ] API changed? `make openapi`, bumped `CONTRACT_VERSION`, added a `## vX.Y.Z` line to `openapi/CHANGELOG.md`
- [ ] Docs updated (schema / permissions / env vars / decisions)
- [ ] No secrets, tokens or real clinic data
