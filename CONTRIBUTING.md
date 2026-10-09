# Contributing

Three developers, three repos, clear ownership. Keep [AGENTS.md](AGENTS.md) handy — the rules
there apply to humans too.

| Person | Role | Owns |
|---|---|---|
| 1 | Backend / Database | **this repo**: schema, migrations, API + contract, auth, RBAC, tenant isolation |
| 2 | Frontend / Mobile | the frontend repo (web + mobile); consumes the contract |
| 3 | AWS / DevOps | infrastructure (Terraform), GitHub settings, environments |

## How work flows

1. Branch from `main` (`feature/…`, `fix/…`, `chore/…`, `docs/…`).
2. Make the change, add tests, run `make check` (+ `make integration-test` for DB changes).
3. API changed? `make openapi`, bump `CONTRACT_VERSION`, add a line to `openapi/CHANGELOG.md`.
4. Open a PR. CI must pass (`CI passed`). One review. Squash-merge.
5. Contract ready for the frontend? Tag it: `git tag v0.2.0 && git push origin v0.2.0`.

## Naming

| Thing | Convention | Example |
|---|---|---|
| Python modules | snake_case | `work_items.py` |
| DB tables | plural snake_case | `chat_messages` |
| API paths | plural kebab-case nouns | `/clinics/{clinic_id}/work-items` |
| Permissions | `resource:action` | `chat:write` |
| Audit actions | `resource.verb` | `connection.connected` |
| Roles | code = snake_case; UI shows the label | `digital_success_manager` → "Digital Success Manager" |
| Env vars | UPPER_SNAKE | `OAUTH_REDIRECT_URIS` |

## Definition of done

- Tests for the new behaviour (and a tenant-isolation line for new clinic routes).
- `make check` passes; integration tests pass for DB changes.
- Contract regenerated and versioned if the API changed; migration added if models changed.
- Docs updated if you changed architecture, permissions, env vars or workflows.
- No secrets, no fake data, no TODOs without an owner.
