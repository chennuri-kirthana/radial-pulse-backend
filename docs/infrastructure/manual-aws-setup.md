# Manual AWS setup: Cognito, API Gateway, IAM, CodeArtifact

The backend code for **email/password sign-in** and **service-to-service authentication** is in
this repository. The AWS side is **not**: nothing below has been created or checked by this
repository, and none of it is done by Terraform in this change. Do each step in the AWS console
(or with the AWS CLI) per environment (DEV first, then PROD), then run the checks in section 7.

**Status: NOT VERIFIED.** No step here has been confirmed against a real AWS account.

Placeholders are written like `<this>`. Never put a client secret in a file, a ticket or a chat.

---

## 1. Cognito user pool (people: email + password)

The existing pool may have been created for Google sign-in. Check each item.

| Setting | Value | Why |
|---|---|---|
| Sign-in identifier | **email** | People sign in with their email. The API creates users with the email as the username. |
| Username case sensitivity | **not** case sensitive | `Asha@x.com` and `asha@x.com` must be the same person. This can only be chosen when a pool is **created**; if the current pool is case sensitive, decide whether to create a new pool. |
| Self-registration | **off** ("Only allow administrators to create users") | Invite-only. |
| Password policy | your choice (e.g. 12+ characters) | Cognito enforces it; the API never sees passwords. |
| MFA | your choice (optional TOTP is a good start for staff) | |
| Account recovery | email only | "Forgot password" in Managed Login. |
| Invitation message (temporary password email) | Subject + body with `{username}` and `{####}` and the **web sign-in link** | The API calls `AdminCreateUser`; Cognito sends this email. The API no longer sends its own invite email. |
| Email sending | Cognito default, or SES for real volume | The Cognito default has a low daily limit. |
| Google identity provider | **remove** / do not use | Google sign-in is out of scope. |
| Managed Login domain | keep the existing one | `COGNITO_DOMAIN` = `https://<domain>` |

## 2. User app clients (web, mobile)

One **public** client per app (no client secret).

| Setting | Value |
|---|---|
| Client secret | **none** |
| Identity providers | **Cognito user pool** only (not Google) |
| OAuth grant | **Authorization code** (the app uses PKCE) — no implicit grant |
| OAuth scopes | `openid`, `email`, `profile` (add `aws.cognito.signin.user.admin` only if the app will change passwords itself) |
| Callback / sign-out URLs | the apps' own addresses (`https://<web>/auth/callback`, `<app scheme>://auth/callback`, local ones for DEV) |
| Authentication flows | Refresh-token sign-in. **Check in DEV** that Managed Login password sign-in works with the flows you enable. This could not be verified from the repository. |
| Token revocation | on |
| Prevent user existence errors | on |

`COGNITO_APP_CLIENT_IDS` = the web and mobile client ids (comma-separated).

## 3. Service-to-service (backend services: AWS IAM) — changed 9 Oct 2026

Backend services no longer use Cognito (no resource server, no service app clients, no client
secrets). They sign each request with their **own IAM role** (SigV4). Person 3 does this part.
Full guide with screenshots: `central-internal-phase1-workflow.pdf` (Central team docs).
✅ = checked in the official AWS docs · ⚠️ = check in DEV.

### 3a. A separate REST API for `/api/v1/internal`

- API Gateway → **REST API** (Regional), e.g. `radial-pulse-central-internal`.
  Resource policies are a REST API feature; the people's HTTP API cannot have one ✅.
- Resources `/api/v1/internal/{proxy+}` (or one resource per route), method **GET**,
  **Lambda proxy integration** → the Central backend Lambda.
- Every method: **Authorization = `AWS_IAM`** ✅ ("Failing to do so will make these API methods
  publicly accessible.").
- **Resource policy** (Central's lock): `Allow` `execute-api:Invoke` for each listed role on its
  routes, plus `Deny` for `Principal: "*"` with `ArnNotEquals aws:PrincipalArn` = the listed roles.
  In the same account an explicit Deny wins ✅. **Redeploy the stage after every policy change** ✅.
- Put the API's id in the backend setting `INTERNAL_API_ID`.

### 3b. Per service (Phase 1: the SEO team only)

1. Get the service's role ARN **exactly** from IAM (with any path, e.g. `role/service-role/...`).
2. On that role: an inline policy allowing `execute-api:Invoke` on only its routes, e.g.
   `arn:aws:execute-api:ap-south-1:<account id>:<api id>/*/GET/api/v1/internal/active-clinics` and
   `.../*/GET/api/v1/internal/clinic-nap/*`.
3. Add the role to the resource policy (3a) and redeploy.
4. Add the role to the backend setting `INTERNAL_SERVICE_ROLES` with its scopes:
   `{"arn:aws:iam::<account id>:role/<name>": {"name": "seo-agent", "scopes": ["clinics.read"]}}`.
5. Give the service team `CENTRAL_API_BASE_URL` = the REST API invoke URL + `/api/v1`
   (see `sdk/central-client/README.md`).

### 3c. Same-account safety

- `lambda:InvokeFunction` on the Central Lambda = full access to `/api/v1/internal` (a direct
  invoke skips API Gateway and can claim any role). Only Central's deploy role may have it; also
  check admin roles, and add a CloudTrail alert for direct `Invoke` by anyone else. The Lambda's resource policy should allow only `apigateway.amazonaws.com`
  from our APIs.
- Nobody outside Central may edit our API, Lambda, IAM roles or database secret. CloudTrail on.
- ⚠️ In DEV, check the Lambda event (CloudWatch) once: `requestContext.apiId` = `INTERNAL_API_ID` and
  `requestContext.identity.userArn` = `arn:aws:sts::<account>:assumed-role/<role>/<session>`.

## 4. API Gateway (HTTP API)

For **people only**: one route `ANY /api/v1/{proxy+}` with one JWT authorizer whose audience is
the **user** app clients. The `cognito-services` authorizer and the `/api/v1/internal` routes on
this HTTP API are **not used any more** (D33): remove them if they were created.

If `/api/v1/internal/...` reaches the backend through this HTTP API anyway, the backend answers
**401** (wrong API id, no IAM caller), so it fails closed.

## 5. IAM

**API task role** (the role the API's ECS task runs as) — add, scoped to the user pool ARN only:

```json
{
  "Effect": "Allow",
  "Action": [
    "cognito-idp:AdminCreateUser",
    "cognito-idp:AdminGetUser",
    "cognito-idp:AdminDisableUser",
    "cognito-idp:AdminEnableUser",
    "cognito-idp:AdminUserGlobalSignOut"
  ],
  "Resource": "arn:aws:cognito-idp:<region>:<account id>:userpool/<user pool id>"
}
```

The same statement is needed by the task that runs `python -m app.cli create-platform-admin`.

**API settings** (ECS task definition, per environment):

| Variable | Value |
|---|---|
| `IDENTITY_DIRECTORY_BACKEND` | `cognito` (required in PROD) |
| `INTERNAL_SERVICE_ROLES` | `{"<role ARN>": {"name": "<service-name>", "scopes": [...]}, …}` (§3b) |
| `INTERNAL_API_ID` | the internal REST API's id (§3a) |
| `INTERNAL_TRUST_LAMBDA_CONTEXT` | `true` **only** on the Lambda function |
| `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_IDS`, `COGNITO_DOMAIN` | as before |

`INVITE_EMAIL_BACKEND`, `INVITE_FROM_EMAIL` and `APP_SIGN_IN_URL` are no longer read and can be removed.
The API's `ses:SendEmail` permission is no longer used by the API.

## 6. CodeArtifact (the internal SDK)

Minimum setup for `.github/workflows/sdk-release.yml`:

1. A CodeArtifact **domain** `<domain>` and a **repository** `<repository>` (no upstream needed).
2. The GitHub **OIDC** identity provider in IAM (it may already exist for the deploy roles).
3. A **publish role** `<role>` trusted by GitHub OIDC with
   `token.actions.githubusercontent.com:sub` = `repo:<owner>/<backend repo>:environment:sdk-release`
   and `aud` = `sts.amazonaws.com`. Its policy:
   - `codeartifact:GetAuthorizationToken` on the domain,
   - `codeartifact:GetRepositoryEndpoint`, `codeartifact:PublishPackageVersion`,
     `codeartifact:PutPackageMetadata` on the repository and its packages,
   - `sts:GetServiceBearerToken` with condition `sts:AWSServiceName = codeartifact.amazonaws.com`.
4. In GitHub: create the environment **`sdk-release`** and the repository **variables**
   `AWS_REGION`, `CODEARTIFACT_DOMAIN`, `CODEARTIFACT_DOMAIN_OWNER` (account id),
   `CODEARTIFACT_REPOSITORY`, `CODEARTIFACT_PUBLISH_ROLE_ARN`.
5. Each **consuming** service's build role: `codeartifact:GetAuthorizationToken`,
   `codeartifact:GetRepositoryEndpoint`, `codeartifact:ReadFromRepository`, and
   `sts:GetServiceBearerToken` (same condition).

Release: bump the SDK version, merge, then `git tag sdk-v<version> && git push origin sdk-v<version>`.

## 7. Checks (do these before saying the setup works)

1. **Invite:** in DEV, `POST /api/v1/users` (as the Platform Administrator) → the person receives
   Cognito's email with a temporary password → they sign in through Managed Login and choose a
   password → `GET /api/v1/auth/me` returns 200 with `sign_in_method: "email_password"`.
2. **Deactivate:** `PATCH /api/v1/users/{id}` `{"is_active": false}` → their refresh fails and
   `GET /auth/me` returns 403. In Cognito the user shows as disabled.
3. **Service (IAM):** unsigned `curl` to the internal REST API → refused by API Gateway; a signed
   call as the SEO role (`curl --aws-sigv4 "aws:amz:ap-south-1:execute-api" ...`) to
   `GET /api/v1/internal/active-clinics` → 200; a signed call as another role → refused, and the
   SEO role still gets 200; the SEO role on a route it has no scope for → 403 from the backend.
4. **Logs:** the backend log line for that call names `service:seo-agent` (read-only routes write no
   audit row).
5. **CodeArtifact:** push a test tag in a non-production repository first; `pip install` the
   published version from a consuming service.
