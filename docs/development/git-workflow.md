# Git workflow

Simple trunk-based flow. No `develop` branch, no release branches.

```mermaid
flowchart LR
  B[feature/… branch] --> PR[Pull request] --> CI[CI: lint, tests, contract] --> R[Review<br/>CODEOWNERS] --> M[Merge to main]
  M --> T[Tag vX.Y.Z] --> C[Contract release<br/>for the frontend]
```

## Branches

| Prefix     | For                      | Example                        |
| ---------- | ------------------------ | ------------------------------ |
| `feature/` | New behaviour            | `feature/clinic-doctors-tab`   |
| `fix/`     | Bug fixes                | `fix/profile-version-conflict` |
| `chore/`   | Tooling, deps, refactors | `chore/bump-fastapi`           |
| `docs/`    | Documentation only       | `docs/auth-flow`               |

`main` is protected: no direct pushes, PR + passing `CI passed` check + 1 review
(CODEOWNERS for owned paths). Squash-merge.

## Commits

Conventional Commits, checked by the `commit-msg` hook:

```
feat(api): add doctors endpoint
fix(web): keep clinic filter on refresh
infra(dev): turn on budget alerts
```

Types: `feat fix chore docs refactor test perf build ci infra revert`.
Scopes: `api`, `db`, `contract`, `worker`, `ci`, `docs`, `repo`.

## Checks before you push

Run `make check` (lint, format, types, fast tests, contract). Heavy checks (PostgreSQL suite,
security scans, Docker build) run in CI.

## Releases

**Contract for the frontend:** after merging, `git tag vX.Y.Z && git push origin vX.Y.Z`
(the tag must equal `CONTRACT_VERSION`). GitHub creates the release with `openapi.json`.
See [contract-versioning](../api/contract-versioning.md).

Deploying to DEV/PROD is owned by DevOps and is not part of this repo yet.
