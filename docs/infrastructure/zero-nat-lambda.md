# Zero-NAT design for the API Lambda (Central DEV)

Written 10 Oct 2026. Status: **code and templates ready and tested locally; nothing deployed.**

## The problem

The database is private (Aurora in `rp-central-db-{a,b}-dev`). To reach it, the API Lambda must run
inside the VPC. The VPC has **no NAT gateway** (about 45 USD/month saved). A Lambda inside it has no
internet. The code needed the internet for three Cognito things:

| # | Code path | When | Without internet |
|---|---|---|---|
| 1 | `JwksSigningKeyResolver` (`app/core/security.py`): GET `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_0BlsS6OwM/.well-known/jwks.json` | first token after every cold start, then hourly | **every token refused (401)**: the API cannot check signatures |
| 2 | `CognitoUserInfoClient` (`app/integrations/cognito.py`): GET `https://rp-central-rp-dev.auth.ap-south-1.amazoncognito.com/oauth2/userInfo` | first sign-in of a person whose row has no `cognito_sub` yet | that sign-in fails (401 "Could not confirm your identity") |
| 3 | `CognitoIdentityDirectory` (`app/integrations/identity_directory.py`): `cognito-idp:AdminCreateUser`, `AdminGetUser`, `AdminDisableUser`, `AdminEnableUser`, `AdminUserGlobalSignOut` | invites, resend, switch a person off/on, when `IDENTITY_DIRECTORY_BACKEND=cognito` | those requests fail (502 upstream) |

Everything else the Lambda talks to works without internet: Aurora (same VPC; the IAM token is
signed locally, no network call), S3 (free gateway endpoint, presigned URLs are signed locally).
Secrets Manager (only "disconnect" of a connected account) would need an interface endpoint
(about 9.5 USD/month per AZ); that feature is not live, so none is planned.

**Why a Cognito VPC endpoint is not the answer.** Cognito user pools support AWS PrivateLink, but
the AWS documentation says a user pool **with a domain assigned is incompatible with it**: "The
existence of a user pool domain prevents completion of any user pool requests that transit a VPC
endpoint", and "VPC private DNS doesn't route requests for user pool domains to your VPC endpoint".
Our pool has the Managed Login domain `rp-central-rp-dev`, which the web app uses to sign people in.
So a `cognito-idp` endpoint would serve neither the JWKS, nor the admin API, nor `userInfo`.

## Options compared

| Option | Monthly cost | Code change | Security | Operations | Verdict |
|---|---|---|---|---|---|
| A. NAT gateway (original plan) | ~41 + 3.65 EIP + data | none | unchanged | none | rejected for cost (your decision) |
| B. NAT instance (EC2 t4g.nano + fck-nat or similar) | ~4 + EIP | none | unchanged; one more server exposed to the internet | patching, monitoring, single AZ | viable fallback; not chosen |
| C. Cognito PrivateLink endpoint | ~9.5 per AZ | none | — | — | **does not work** for a pool with a domain (see above) |
| D. Lambda outside the VPC + public database | 0 | none | **database on the internet**: rejected by design | — | rejected |
| **E. Zero-NAT: JWKS copy in S3 + no `userInfo` + Cognito admin done outside the Lambda** | **~0** (720 tiny invocations/month, one S3 object) | small, opt-in (this release) | unchanged token checks; one more trusted component (the sync Lambda + bucket policy) | one scheduled Lambda; a documented manual step to link new accounts | **chosen** |

## The design (option E)

```
                 (public internet)                                   (private VPC, no NAT)
 Cognito JWKS  <-- GET hourly --  rp-central-jwks-sync-dev   -- PutObject -->  S3 rp-central-jwks-dev-<acct>
 (public doc)                     (Lambda OUTSIDE the VPC,                     cognito/<pool>/jwks.json
                                   EventBridge rate(1 hour))                          |
                                                                              GetObject (S3 gateway endpoint)
                                                                                      v
 Browser --token--> API Gateway (JWT authorizer) --> rp-central-api-dev (in app subnets) --> Aurora
                                                     COGNITO_JWKS_S3_URI=s3://...
```

### 1. JWKS from S3 (`S3JwksSigningKeyResolver`, `COGNITO_JWKS_S3_URI`)

- `infra/cloudformation/central-jwks-sync-dev.yaml`: private bucket (block public access, SSE-S3,
  TLS-only), Lambda `rp-central-jwks-sync-dev` (Python 3.12, inline code, no VPC, 128 MB, 30 s),
  EventBridge rule every hour, role limited to its log group and the one object. The Lambda reads the
  public JWKS, **refuses anything that is not a set of RS256 RSA keys**, and writes the object only
  when it changed. Output `JwksS3Uri` is the API setting; `ApiLambdaRoleArn` adds a bucket policy
  that lets exactly the API role read the object.
- The API: when `COGNITO_JWKS_S3_URI` is set, `get_token_verifier` uses `S3JwksSigningKeyResolver`
  instead of the URL resolver. **Every other check is untouched**: RS256 only, signature, `iss`,
  `exp`/`iat` with 30 s leeway, `token_use == access`, `client_id` in `COGNITO_APP_CLIENT_IDS`,
  then the database decides what the person may do. A wrong, old or empty copy can only make
  valid tokens fail; it can never make a forged token pass (the keys are still Cognito's).
- Freshness: cached for `JWKS_CACHE_SECONDS` (3600). A token with an unknown `kid` triggers one
  re-read of S3 (at most once a minute): this is how a rotated key is picked up within minutes of
  the hourly sync. If S3 is unreadable, the last good set is kept and a warning is logged; with no
  cached set, tokens are refused (fail closed).
- Cognito does not rotate user-pool signing keys on a schedule; they change when the pool is
  recreated. The hourly sync is more than enough.

### 2. First sign-in without `userInfo`

Leave `COGNITO_DOMAIN` unset in zero-NAT mode. A person signs in when their `users` row already has
their Cognito `sub` (`rp_user_for_login(sub, '')`). Rows get a `sub`:

- Platform Administrators: `python -m app.cli create-platform-admin --email … --cognito-sub <sub>`
  (new in this release). Create the person in the Cognito console first, copy the `sub` from the
  user's details page. Runs from the CloudShell VPC environment with the offline toolkit; no
  Cognito call. Also links an existing unlinked admin row.
- **Limitation:** clinic members and other users invited through the API get a row **without** a
  `sub` (`IDENTITY_DIRECTORY_BACKEND=log`). Their Cognito account must be created in the console,
  and the row linked by an operator. There is no API for that today; the `--cognito-sub` CLI only
  handles Platform Administrators. For DEV demo accounts this is acceptable; for real onboarding at
  scale it is not, and would need either a NAT/NAT instance or a small "link account" operator
  command (follow-up, not in this release).

### 3. Cognito admin operations

`IDENTITY_DIRECTORY_BACKEND=log` in zero-NAT mode: the API does not call Cognito. Creating,
disabling and enabling Cognito accounts is done in the console (or from a laptop/CloudShell with
the AWS CLI, outside the VPC). The API's own disable/enable of the database row keeps working.

### 4. Network dependencies of the API in the app subnets

| Dependency | Path | Status |
|---|---|---|
| Aurora 5432 | VPC, `rp-central-api-lambda-sg-dev` → `rp-central-db-sg-dev` | OK (stack `rp-central-db-dev`) |
| S3 (JWKS copy, photos, voice, avatars) | S3 gateway endpoint on `rp-central-rt-app-dev` | OK (stack `rp-central-network-dev`) |
| Cognito JWKS | replaced by the S3 copy | OK with `COGNITO_JWKS_S3_URI` |
| Cognito `userInfo`, admin API | not reachable | by design (above) |
| Secrets Manager | not reachable | only "disconnect" uses it: not live. Interface endpoint if ever needed |
| STS / IAM | not needed: Lambda credentials come from the environment | OK |
| DNS | VPC DNS (`enableDnsSupport`/`Hostnames` on) resolves the Aurora endpoint to a private IP | OK |

### 5. Database connections

One Lambda instance serves one request at a time: `DB_POOL_SIZE=1`, `DB_MAX_OVERFLOW=0`, so the
number of connections equals the number of concurrent instances. Cap with reserved concurrency 10
(10 connections; Aurora at 2 ACU allows far more). `DB_POOL_RECYCLE_SECONDS=600` stays under the
15-minute IAM token life; `pool_pre_ping` drops dead connections after a pause. Connect timeout is
5 s; a paused Aurora (0 ACU) takes about 15 s to resume, so the first request after idle can get
**503 `service_unavailable`** (new in this release; it was 500) and a retry works.

## Deployment order (nothing done yet; each step needs your approval)

1. `aws cloudformation deploy --stack-name rp-central-jwks-sync-dev --template-file infra/cloudformation/central-jwks-sync-dev.yaml --capabilities CAPABILITY_NAMED_IAM --parameter-overrides UserPoolId=ap-south-1_0BlsS6OwM ApiLambdaRoleArn=arn:aws:iam::243894881176:role/rp-central-lambda-execution-dev --region ap-south-1`
   then run it once: `aws lambda invoke --function-name rp-central-jwks-sync-dev --region ap-south-1 /dev/stdout` → `{"changed": true, "keys": 2}`.
2. Check the object exists: `aws s3api head-object --bucket rp-central-jwks-dev-243894881176 --key cognito/ap-south-1_0BlsS6OwM/jwks.json`.
3. Deploy the new API ZIP (same code path works with or without the setting).
4. **One** `update-function-configuration` that sets, together: the VPC (app subnets +
   `rp-central-api-lambda-sg-dev`), `COGNITO_JWKS_S3_URI`, `DB_*` (IAM auth), unset
   `COGNITO_DOMAIN`, `IDENTITY_DIRECTORY_BACKEND=log`. Doing the VPC change without the JWKS setting
   breaks every sign-in.
5. Smoke: `/health` 200, `/ready` 200 (retry once if Aurora was paused), `/api/v1/auth/me` with a
   real token 200 for a linked admin; CloudWatch shows no "JWKS refresh from S3 failed".
6. Create the first admin: Cognito console user → copy `sub` → from the CloudShell VPC environment
   with the toolkit: `uv run --offline --no-sync python -m app.cli create-platform-admin --email <email> --cognito-sub <sub>`
   (needs `DATABASE_URL`/`DB_*` for the **owner** login or the app login; the CLI runs as the
   `system` actor through `radial_app`).

## Rollback

Set `COGNITO_JWKS_S3_URI` empty and remove the VPC settings in one update: the function is back to
the public-internet mode. Delete stack `rp-central-jwks-sync-dev` (the bucket must be emptied first).
