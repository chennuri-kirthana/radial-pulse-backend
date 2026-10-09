# radial-central-client

A small Python SDK for **backend services** that call the Radial Pulse Central API's internal
routes (`/api/v1/internal/...`). It is never used by people or browsers.

It **signs every request with your service's own AWS IAM role** (Signature Version 4, service
`execute-api`). There is no client secret and no token. (Changed 9 Oct 2026 in 0.3.0: Cognito
client credentials are gone.)

## Rules

- Each service calls with its **own** IAM role (its Lambda / ECS role). Never share a role between services.
- The Central team (Person 3) allows your role in two places: an `execute-api:Invoke` permission
  on your role for the routes you need, and Central's resource policy on the internal REST API.
  The Central backend also gives your role its scopes (`INTERNAL_SERVICE_ROLES`).
- Send us the role's **exact ARN** (with any path, e.g. `role/service-role/...`).
- Never use a person's Cognito token on these routes: it gets 401.

The internal routes are **read only** (changed 8 Oct: other teams read Central data here).

| Method | Route | Scope (given to your IAM role) |
|---|---|---|
| `list_active_clinics(limit=, offset=)` | `GET /internal/active-clinics` | `clinics.read` |
| `get_clinic_nap(clinic_id)` | `GET /internal/clinic-nap/{id}` | `clinics.read` |
| `list_clinics(limit=, offset=)` | `GET /internal/clinics` | `clinics.read` |
| `get_clinic(clinic_id)` | `GET /internal/clinics/{id}` | `clinics.read` |
| `get_clinic_profile(clinic_id)` | `GET /internal/clinics/{id}/clinic-profile` | `clinics.read` |
| `list_clinic_practitioners(clinic_id)` | `GET /internal/clinics/{id}/clinic-practitioners` | `clinics.read` |
| `list_clinic_online_profiles(clinic_id)` | `GET /internal/clinics/{id}/clinic-online-profiles` | `clinics.read` |
| `list_approved_photos(clinic_id)` | `GET /internal/clinics/{id}/photos` | `clinics.read` |
| `list_connected_accounts(clinic_id)` | `GET /internal/clinics/{id}/connected-accounts` | `connected_accounts.read` |
| `list_connected_account_resources(clinic_id)` | `GET /internal/clinics/{id}/connected-account-resources` | `connected_accounts.read` |

Version 0.2.0 removed the old write methods (`ingest_snapshots`, `create_report`) and renamed
`get_profile` → `get_clinic_profile`, `list_presence_profiles` → `list_clinic_online_profiles`.

## Install

From the team's CodeArtifact repository (see `docs/infrastructure/manual-aws-setup.md` in the backend repo):

```bash
aws codeartifact login --tool pip --domain <domain> --domain-owner <account id> --repository <repository>
pip install "radial-central-client[aws]==0.3.0"   # the "aws" extra brings botocore for signing
```

## Settings

| Variable | Value |
|---|---|
| `CENTRAL_API_BASE_URL` | the internal REST API's invoke URL + `/api/v1`, e.g. `https://<api id>.execute-api.ap-south-1.amazonaws.com/<stage>/api/v1` |
| `CENTRAL_AWS_REGION` | optional; default `AWS_REGION`, then `ap-south-1` |
| `CENTRAL_TIMEOUT_SECONDS` | optional, default `10` |

AWS credentials come from the normal AWS chain (your Lambda / ECS role in AWS, an SSO profile
locally). Temporary credentials are fine: the signature then carries `X-Amz-Security-Token`.

## Use

```python
from radial_central_client import CentralApiError, CentralClient, CentralClientConfig

client = CentralClient(CentralClientConfig.from_env())  # create once per process and reuse it

try:
    page = client.list_active_clinics(limit=50, offset=0)  # {"items": [...], "total": N, ...}
    nap = client.get_clinic_nap(page["items"][0]["clinic_id"])
except CentralApiError as exc:
    # 401/403 from API Gateway: not signed / role not allowed (no request_id from Central)
    # 401 from Central: role not in INTERNAL_SERVICE_ROLES; 403: missing scope
    # 404: not an active client clinic; 400: bad input
    log.warning("central call failed", extra={"status": exc.status_code, "request_id": exc.request_id})
```

Errors: `CentralApiError` (with the API's problem `type` and the `request_id` when Central
answered), `SigningError` (no AWS credentials, etc.; nothing was sent) or `ConfigurationError`.
Calls are not retried.

## Develop

```bash
uv run --directory sdk/central-client pytest
uv run --directory sdk/central-client mypy
```

Release: bump `version` in `pyproject.toml` and `__version__`, merge, then push the tag
`sdk-v<version>`. The `Publish SDK` workflow tests, builds and publishes it to CodeArtifact.
