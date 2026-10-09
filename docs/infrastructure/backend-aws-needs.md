# What the backend needs from AWS

A short list to share with the DevOps owner. **How** to set these up is their decision.

## Permissions for the API

| Feature | Needs |
|---|---|
| Profile photos (Settings → My Profile) | read/write/delete files under `users/*` in the assets bucket (today only `clinics/*`) |
| Connected accounts (Instagram, Google, …) | create, update, restore and delete secrets named `radial-pulse/<env>/connections/*` in Secrets Manager, encrypted with the environment KMS key |

Later, the data-sync jobs (worker) will only need to **read** those secrets.

## Cognito and API Gateway (the frontend's Phase 7 needs these)

Email/password sign-in, the service clients, the IAM permissions and CodeArtifact are listed step by
step in [manual-aws-setup.md](manual-aws-setup.md) (not verified by this repository).

| Item | What the backend expects |
|---|---|
| `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_DOMAIN` | the DEV user pool and its Managed Login domain (`https://…`). Public ids, not secrets. Please share the values with the frontend team too |
| `COGNITO_APP_CLIENT_IDS` | **both** user app clients, web and mobile, comma-separated. Public clients (PKCE, no secret), Cognito user pool as the only identity provider |
| `INTERNAL_SERVICE_ROLES`, `INTERNAL_API_ID`, `INTERNAL_TRUST_LAMBDA_CONTEXT` | other teams' IAM roles allowed on `/api/v1/internal` with their scopes (`{"<role ARN>": {"name": "<service name>", "scopes": [...]}}`), the internal REST API's id, and `true` on the Lambda only (D33, 9 Oct; replaces the Cognito service clients) |
| `IDENTITY_DIRECTORY_BACKEND` | `cognito` (invites create Cognito users; needs the `cognito-idp:Admin*` permissions in manual-aws-setup.md) |
| API Gateway JWT authorizer | issuer `https://cognito-idp.<region>.amazonaws.com/<pool-id>`; audience = the web **and** mobile client ids (Cognito access tokens carry `client_id`, not `aud`, and the authorizer accepts either). The API checks the same again and refuses ID tokens |
| Cognito callback URLs (per app client) | web: `https://<dev-web>/auth/callback` and `http://localhost:4200/auth/callback`; mobile: `radialpulse-local://auth/callback`, `radialpulse-dev://auth/callback` (PROD: `radialpulse://auth/callback`). These are Cognito's, the API never sees them |
| CORS at API Gateway | if the gateway answers browser preflights, allow the same origins as `CORS_ALLOWED_ORIGINS` below |
| DEV test accounts | three email addresses the frontend will test with: a Platform Administrator, a DSM with clinics, a Clinic Administrator of two clinics. The `create-admin` task and the API create them **and** their Cognito users; Cognito emails each a temporary password |

## Settings for the API

| Setting | What it is |
|---|---|
| `OAUTH_REDIRECT_URIS` | "Connect Your Accounts" return addresses (comma-separated, exact match). **DEV:** `https://<dev-web>/connect/callback`, `http://localhost:4200/connect/callback`, `radialpulse-local://connect/callback`, `radialpulse-dev://connect/callback`. **PROD:** `https://<prod-web>/connect/callback`, `radialpulse://connect/callback`. Each must also be registered with Google / Meta / LinkedIn / X. Not the Cognito sign-in callback |
| `CONNECTION_SECRETS_KMS_KEY_ID` | the KMS key for the connected-account secrets |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET`, `META_APP_ID` / `_SECRET`, `LINKEDIN_CLIENT_ID` / `_SECRET`, `X_CLIENT_ID` / `_SECRET` | each platform's app credentials (the `_SECRET` ones are secrets) |
| `CORS_ALLOWED_ORIGINS` | browser addresses allowed to call the API (comma-separated). **DEV:** the deployed web app **plus the developers' local servers** `http://localhost:4200` (web) and `http://localhost:8081` (mobile). **PROD:** https addresses only (the API refuses to start otherwise) |

A platform without its credentials shows "not set up yet" in the app; nothing breaks.

## Database

The next deploy runs migration **0010** (chat, connected accounts, settings).
