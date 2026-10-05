# Authentication

**Cognito + Google sign-in + PKCE + API Gateway JWT validation.**
There is no username/password form of our own and no fake login anywhere.

## Sign-in flow (web and mobile)

```mermaid
sequenceDiagram
  autonumber
  participant U as Person
  participant App as Web / Mobile app
  participant Cog as Cognito Hosted UI
  participant G as Google
  participant API as Radial Pulse API
  App->>App: make code_verifier + code_challenge (PKCE)
  App->>Cog: /oauth2/authorize?identity_provider=Google&code_challenge=…
  Cog->>G: redirect to Google
  U->>G: choose account, consent
  G->>Cog: Google identity
  Cog->>App: redirect back with ?code=…
  App->>Cog: /oauth2/token (code + code_verifier)
  Cog->>App: access token + id token + refresh token
  App->>API: GET /api/v1/auth/me  (Authorization: Bearer <access token>)
  API->>API: verify token, find User by sub (first time: link by verified email)
  API->>App: user, platform role, permissions, clinics
```

- **PKCE** replaces a client secret. Both app clients in Cognito are _public_ (no secret).
- The apps may use any OIDC library. The frontend team uses **AWS Amplify** on web and mobile.
  Whatever the library, the API only needs: the Cognito **access token** (not the ID token) as
  `Authorization: Bearer …`, from one of our two app clients (web, mobile).
- Cognito's own sign-in callback (`https://<web>/auth/callback`, `<app scheme>://auth/callback`)
  is registered in Cognito by DevOps. The API never sees it. It is a different address from the
  "Connect Your Accounts" callback (`…/connect/callback`), which the API does check
  (`OAUTH_REDIRECT_URIS`). Never mix the two.

## Token flow on every API call

```mermaid
flowchart LR
  A[App] -- "Bearer access token" --> B[API Gateway<br/>JWT authorizer]
  B -- "invalid → 401" --> A
  B -- valid --> C[FastAPI<br/>verify again]
  C --> D[Load user, memberships,<br/>assignments from DB]
  D --> E[clinic_access gate]
```

What the API checks (`app/core/security.py`):

| Check      | Rule                                                 |
| ---------- | ---------------------------------------------------- |
| Signature  | RS256 only, key from the user pool's JWKS (cached)   |
| Issuer     | Must be our user pool                                |
| Expiry     | `exp`/`iat` with 30 s leeway                         |
| Token type | `token_use` must be `access` (ID tokens are refused) |
| Client     | `client_id` must be our web or mobile app client     |

Why check twice? API Gateway protects the edge; the API must never trust the network
hop, and local/dev traffic may bypass the gateway.

## Invite-only accounts

Radial Pulse is sold outbound: nobody signs themselves up.

0. The **first** Platform Administrator is created once from the command line:
   `make create-admin --email=… --name=…` (in AWS: a one-off ECS task).
1. A **Platform Administrator** pre-creates Digital Success Managers (`POST /api/v1/users`)
   and assigns them to clinics.
2. A **Digital Success Manager** onboards a clinic and adds its Clinic Administrator(s)
   or Clinic Team Members (`POST /clinics/{id}/team`).
3. On a person's **first** Google sign-in, the API sees an unknown `sub`, calls Cognito's
   `/oauth2/userInfo` for the **verified** email, and links it to the pre-created user.
4. Unknown or unverified emails, and disabled accounts, get **403** with `type`
   `not_provisioned` (the app shows "This account isn't set up for Radial Pulse"). An email
   already linked to a different Google identity is also refused. A bad or expired token is
   **401** `unauthorized`; an API without Cognito settings answers **503**.

(Cognito itself may create a user record on first Google sign-in; that grants nothing
in Radial Pulse. A Cognito pre-sign-up trigger to block unknown emails is listed in
[decisions.md](decisions.md).)

## Authorization

Authentication says **who** you are. Authorization — **what** you may do — is decided
only by the API from the database: see [multi-tenancy.md](multi-tenancy.md).

| Role                    | Stored as                                         | Access                                        |
| ----------------------- | ------------------------------------------------- | --------------------------------------------- |
| Platform Administrator  | `platform_administrator`                          | Everything, every clinic                      |
| Digital Success Manager | `digital_success_manager` + assignment            | Assigned clinics only (+ onboard new clinics) |
| Clinic Administrator    | `clinic_user` + membership `clinic_administrator` | Only their own clinic(s)                      |
| Clinic Team Member      | `clinic_user` + membership `clinic_team_member`   | Own clinic(s), view-only + uploads            |

## Human identity vs service identity

People authenticate with Cognito (above). The background **worker** is not a person: AWS
authenticates it through its own ECS task role, it logs in to the database with its own
IAM-authenticated user, and it acts as a `ServicePrincipal` limited to one clinic per job.
It never uses or impersonates a human's token. Details:
[background-jobs.md](background-jobs.md#service-identity).

## Local development

Point the apps and API at the **DEV** Cognito user pool (values are public ids, not
secrets). Without them, the web/mobile apps run in an "auth not configured" mode for
layout work and every protected API endpoint answers **503** — never a bypass.
Automated tests sign real JWTs with a throwaway RSA key and use the production verifier.
