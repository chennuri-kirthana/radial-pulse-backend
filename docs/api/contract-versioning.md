# API contract: versions and releases

The **contract** is `openapi/openapi.json`: every route, every field, every error the API has.
The frontend generates its TypeScript types from it, so it must never change by surprise.

## Where the version lives

| Place | Value |
|---|---|
| `app/core/contract.py` → `CONTRACT_VERSION` | e.g. `0.1.0` (the source) |
| `openapi.json` → `info.version` | the same (generated) |
| `GET /health` → `contract_version` | what is running in DEV/PROD right now |
| git tag + GitHub Release | `v0.1.0` → release "API contract v0.1.0" with `openapi.json` attached |

## Which number to bump

While we are before the first production launch (0.x):

| Change | Example | Bump |
|---|---|---|
| Fix or addition that cannot break a screen | new optional field, new route, new enum value in a response | **patch** 0.1.0 → 0.1.1 |
| Anything that can break a screen | removed/renamed field or route, new **required** input, changed meaning, removed enum value | **minor** 0.1.0 → 0.2.0 |

From 1.0.0 on: normal semantic versioning (major = breaking).

A new value in an enum the frontend READS (e.g. a new status) can break a `switch` in the
app. Treat it as a patch, but write it in the changelog so Person 2 can handle it.

## How to release a contract (Person 1)

```bash
# 1. in your pull request
make openapi                                   # regenerate openapi/openapi.json
# edit app/core/contract.py → CONTRACT_VERSION = "0.1.1"
# edit openapi/CHANGELOG.md  → add "## v0.1.1 — <date>" with what changed for the screens
# 2. after the PR is merged to main
git checkout main && git pull
git tag v0.1.1 && git push origin v0.1.1
```

GitHub Actions (`release.yml`) then checks that the tag is on `main`, that the tag equals
`CONTRACT_VERSION`, that `openapi.json` is exactly what the code produces, and creates the release.

## What CI enforces on every pull request

- `openapi/openapi.json` matches the code (`make contract-check`).
- If `openapi.json` changed: `CONTRACT_VERSION` changed too and `openapi/CHANGELOG.md` has a
  section for it.
- A breaking-changes report (oasdiff) is printed for the reviewer.

## Deprecating instead of breaking

Prefer: add the new field/route → release → frontend moves → remove the old one in a later
**minor** version, listed under "Removed" in the changelog.
