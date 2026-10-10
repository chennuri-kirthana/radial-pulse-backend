# Decisions — made, and still needing approval

## Made (non-negotiable inputs)

Nx · pnpm · React + TypeScript (web) · React Native + TypeScript with Expo (mobile) ·
Python + FastAPI · PostgreSQL / Aurora PostgreSQL · SQLAlchemy 2 · Alembic · Pydantic ·
pytest · AWS · Terraform · GitHub Actions · Docker · Cognito (email + password, PKCE) + API Gateway JWT.

## Made during scaffolding (reversible, explained)

| Decision                                                                                             | Why                                                                              |
| ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Vite for the web app                                                                                 | Fast, standard for React SPAs; no SSR needed for an authenticated dashboard      |
| React Router 7, TanStack Query                                                                       | Mainstream, typed; keeps server state out of components                          |
| `openapi-typescript` + `openapi-fetch` for the client                                                | Backend stays the source of truth; types regenerate from OpenAPI                 |
| uv for Python                                                                                        | Fast, lockfile-based, works on Windows/macOS/Linux                               |
| Sync SQLAlchemy + psycopg 3                                                                          | Simpler than async; FastAPI runs sync routes in a thread pool; revisit if needed |
| Enums stored as VARCHAR + CHECK                                                                      | Adding a value never needs `ALTER TYPE`                                          |
| Lefthook for git hooks                                                                               | Single binary via npm, cross-platform, fast, parallel                            |
| ECS Fargate + internal ALB behind API Gateway (VPC link)                                             | Long-running FastAPI with a DB pool; no servers to patch                         |
| Aurora Serverless v2, scale-to-zero in DEV                                                           | Lowest cost for a small dev load                                                 |
| S3 + CloudFront for the web app                                                                      | Needed to host the SPA; cheapest managed option                                  |
| Single NAT in DEV, one per AZ in PROD                                                                | Cost vs. resilience. **DEV revised 10 Oct 2026: no NAT at all** (`infra/cloudformation/central-network-dev.yaml`); the Lambda's internet egress is open blocker B8 in `docs/infrastructure/dev-lambda-plan.md`                                                              |
| Region `ap-south-1` (Mumbai)                                                                         | India-only target market                                                         |
| Invite-only users, linked on first sign-in by verified email                                         | Outbound sales model: nobody self-registers                                      |
| 404 (not 403) when a user has no access to a clinic                                                  | Do not reveal which clinics exist                                                |
| Role names: Platform Administrator / Digital Success Manager / Clinic Administrator (review 2026-09) | Business terminology; migrated with a data mapping (0002), not a rename          |
| PostgreSQL row-level security + non-owner `radial_app` role                                          | Second isolation net under the application gate (0004)                           |
| IAM DB auth for api/worker; master secret only in migrate                                            | No long-lived DB password in running services                                    |
| One SQS queue + DLQ + one worker service                                                             | Enough for assessments; add job types, not queues                                |
| One unified Digital Presence Assessment (6 fixed sections)                                           | Product decision; engines are domain-owned plugins                               |
| One generic `presence_profiles` table with a `platform` column                                       | No per-platform tables                                                           |

## Milestone 1 product decisions (26 Sep 2026)

Full detail: [database-schema.md](database-schema.md), section 0.

| # | Decision |
|---|---|
| D1 | **5 clinic stages**: prospective_client → profile_enriched → assessment_completed → client_discussion → active_client. Leads are given to us. A clinic that says no is **archived** with a required reason (no extra stage). |
| D2 | **Exactly one active DSM per clinic** (database rule). "Update Assignment" swaps them; old rows are kept as history. |
| D3 | "Client Organization" = the business (`organizations`) that owns one or more clinics. |
| D4 | Doctor → **Practitioner** everywhere (table, API, permissions). `clinic_id` is not renamed. |
| D5 | Admin tabs: Prospects = stages 1–2 · In Progress = 3–4 · Active = 5 · archived hidden behind a filter. |
| D6 | Stage moves are **manual** (Admin or the clinic's DSM) in Milestone 1. |
| D7 | A clinic can become **Customer** only with at least one active Clinic Administrator. |
| D8 | Improvement Opportunity = an **assessment finding**. D9: its work status lives on the **work item** (one open item per finding code). |
| D10 | No hard deletes: deactivate / archive. |
| D12 | ~~Login: Google only~~ — **replaced by D26** (6 Oct 2026). |
| D13 | **Invites** are sent automatically. Since D26 Cognito sends them (temporary password); the API no longer sends its own email. |
| D14 | A Clinic Administrator may add **other Clinic Administrators** to their own clinic. A Customer clinic cannot lose its last one. |
| D15 | The clinic's **DSM alone** reviews and publishes an assessment. Clinic users can never approve, reject or retract an assessment. |

## V1 media decisions (5 Oct 2026, migration 0013, contract v0.2.0)

| # | Decision |
|---|---|
| D20 | **Clinic media** (hospital/clinic photos, doctor photos, voice samples): only the Clinic Administrator uploads; only the DSM and Platform Administrator approve, reject or request a retake. Clinic Team Members have no part in it (future scope). |
| D21 | **Confirming an upload submits it for review.** A retake is a new upload linked with `previous_version_id`. |
| D22 | **Two kinds of review text:** an internal note (staff only) and a message for the clinic. |
| D23 | **Media labels live in `media_taxonomy`**, not in code. V1 values: 6 clinic photo categories, apron (2), angle (5), outfit (2), voice sample `clinic_greeting`. |
| D24 | **Every review decision is Radial Pulse staff work.** Clinic Administrators have no `approvals:*` permission: they never approve, reject, redo, publish or hand off anything (assessments, report outputs, clinic media). Their only review step is the automatic submit of their own media. |
| D25 | **Review activity stays internal.** Clinic people do not see `approval.*` events or assessment events in the activity log. |

## Authentication decisions (6 Oct 2026)

Details: [authentication.md](authentication.md). AWS side (manual, not verified here):
[manual-aws-setup.md](../infrastructure/manual-aws-setup.md).

| # | Decision |
|---|---|
| D26 | **People sign in with email + password** through Cognito **Managed Login** (Authorization Code + PKCE, public clients). No Google sign-in. Invites create the Cognito user (`AdminCreateUser`); Cognito emails the temporary password; the API stores the `sub` at once. Deactivation disables the Cognito user and signs them out. |
| D27 | **Replaced by D33 (9 Oct 2026).** ~~**Backend services use Cognito OAuth 2.0 client credentials**, one confidential app client and secret per service, on `/api/v1/internal` only, with least-privilege scopes (`snapshots.write`, `reports.write`, `profile.read`, `presence.read`). Service and user tokens are never accepted on each other's routes.~~ |
| D28 | **Internal SDK** `radial-central-client` (`sdk/central-client`) for those services, published to **AWS CodeArtifact** by a tag-triggered GitHub workflow (OIDC, no stored keys). Since D33 (SDK 0.3.0) it signs requests with the service's IAM role instead of fetching Cognito tokens. |

## Practitioner Profile (8 Oct 2026, migration 0014, contract v0.3.1)

| # | Decision |
|---|---|
| D29 | **Practitioner Profile = a view, not a new store.** `GET/PUT /clinics/{id}/profile` has a `practitioner_profile` object for the clinic's **main** practitioner. Its fields are stored where they already belong: the practitioner (person), the practitioner's link to this clinic (consultation), the clinic (name, year, address) and the profile's `services`. Nothing is stored twice. |
| D30 | **Consultation details are per clinic.** Schedule, weekly holiday and fee live on `clinic_practitioners`, because one doctor can have different timings and fees at different branches. |
| D31 | **Money = integer minor units + ISO 4217 currency** (`{"amount_minor": 50000, "currency": "INR"}` = ₹500.00). No floats, no formatted strings. Used for the consultation fee; reuse it for any later amount. |
| D32 | **Consultation schedule** uses the same shape as the clinic opening hours (`{opens, closes}` per weekday), plus rules: opens before closes, no overlaps, at most 6 windows per day, a known timezone, and a weekly holiday cannot have timings. |

## Service authentication (9 Oct 2026, contract v0.5.0)

| # | Decision |
|---|---|
| D33 | **Backend services use AWS IAM on `/api/v1/internal`, not Cognito** (replaces D27). Each service signs with its own IAM role (SigV4). `/api/v1/internal` is served by a **separate API Gateway REST API** with `AWS_IAM` on every method and Central's resource policy (allow the listed roles, deny everyone else). The backend reads the caller from the Lambda Web Adapter's `x-amzn-request-context` header, checks the API id, the role (`INTERNAL_SERVICE_ROLES`) and the route's scope, and runs the request as the read-only database role `radial_service`. People keep Cognito on every other route. Person 3 owns the IAM / API Gateway setup. **Limit:** anyone with `lambda:InvokeFunction` on the Central function can skip API Gateway and act as any listed role, so that permission is kept to Central's deploy role only (function policy: `apigateway.amazonaws.com` with our API ARNs as `SourceArn`; CloudTrail alert on other direct invokes). |

## Need team / mentor approval

1. **Assessment scoring** — today the overall score is an equal-weight mean of completed
   sections (`methodology_version 2026.09-v0`). The product owner must approve weights,
   section list and what a "partial" assessment shows to clinics.
2. **Role → permission table** (`app/core/rbac.py`, [multi-tenancy.md](multi-tenancy.md)).
   Open points: may a Digital Success Manager read the user list (today: no)?
   May a Digital Success Manager create clinics (today: yes, and is auto-assigned)?
   (Decided in D14: a Clinic Administrator may add other Clinic Administrators and
   Clinic Team Members to their own clinic.)
3. **Clinic Team Member** — DECIDED (Sep 2026): view-only in their own clinic plus uploading
   photos/files; granted by the Admin, the clinic's DSM or a Clinic Administrator.
4. **Four-eyes rule** — should the person who submits an assessment be blocked from approving it?
5. **One practitioner, many clinics** — DECIDED (Sep 2026): a doctor belongs to the business
   (`practitioners.organization_id`) and is linked to each branch through `clinic_practitioners`.
   Only branches of the same business can share a doctor (migration 0008).
6. **Separate AWS accounts for DEV and PROD** (recommended; Terraform supports both).
7. **HTTP service-to-service auth** — DECIDED (D33, 9 Oct 2026; replaces D27): AWS IAM roles
   (SigV4) on a separate REST API for `/api/v1/internal`. Open: which other services exist and
   their scopes (Phase 1: only the SEO team, `clinics.read`).
8. **Engine packaging and deployment** — how domain teams ship engines (same image via
   entry points today; a separate crawler image with Playwright if needed).
9. **Scheduled re-assessments** (every 1–2 weeks?) — EventBridge Scheduler → job. Needs a product decision.
10. **RLS on identity tables** — DONE (Sep 2026, migration 0007): every table is under RLS.
11. **Cognito pre-sign-up trigger** — no longer needed: no Google sign-in (D26) and self-registration
    is off, so only invited (admin-created) users exist in Cognito.
12. **Production image promotion** — PROD currently rebuilds from the released commit.
    Promote the exact DEV image digest instead (needs cross-account ECR access).
13. **Custom domains** (app/api/auth) and ACM certificates.
14. **Chat** — BUILT (Sep 2026, migration 0010, contract v0.1.0): one conversation per clinic,
    PostgreSQL history, S3 attachments, polling (WebSocket push later, delivery only).
    Open for the mentor: **D18** may Clinic Team Members send (today: read only)?
    **D19** confirm the rule "no patient health information in chat" (the app shows a notice).
15. **Health information** — if patient data is ever stored, a formal compliance assessment
    is required first (no HIPAA or similar claim is made).
16. **Nx Cloud / remote cache** — off (`NX_NO_CLOUD`). Enable if CI gets slow.
17. **Internal ALB hop is plain HTTP inside the VPC** (TLS ends at API Gateway). Acceptable
    for now; end-to-end TLS needs a private certificate.
18. **Worker autoscaling** on queue depth — not needed at one task; revisit with real load.
19. **Archive retention** — old `metric_snapshots` (>180 days) and `audit_events` (>365 days) move
    to an S3 archive monthly (built). Open: how long the archive is kept (suggested 7 years) and
    whether audit files use S3 Object Lock. Needs a business/legal decision before PROD.
20. **Separate backend repo** — DECIDED (Sep 2026): the frontend has its own repo, so the API
    moved to `radial-pulse-backend` (history kept). The contract is published as GitHub Releases
    (`vX.Y.Z` with `openapi.json`). Deployment workflows are left to DevOps. The monorepo's
    `services/api` stops being used once the team switches.
21. **Connected accounts** — BUILT (migration 0010): OAuth for Google (GBP, YouTube), Meta
    (Instagram, Facebook), LinkedIn and X, read-only scopes; tokens only in Secrets Manager (one
    secret per connection, ~USD 0.40/month each). Open: Meta/LinkedIn app reviews; who builds the
    data-sync jobs (with the domain teams).
22. **Settings** — BUILT (migration 0010): platform settings (one row, Admin), notification
    switches per person (in-app used now; email saved for later), profile photo.
23. **Keys** — DECIDED (Sep 2026, migration 0011): every table keeps a single `id` primary key;
    natural identity is a composite unique key next to it; links inside one clinic are composite
    foreign keys on (parent id, clinic_id). See `database-relationships.md`.
24. **Schema review** — DONE (Sep 2026, migration 0012): indexes for every link, 10 duplicate
    indexes removed, one running assessment per clinic, 21 CHECK rules (ranges, lower-case email,
    upper-case country, done ⇔ completed_at). Open recommendations R1–R6 (updated_at trigger, id
    defaults, worker job lease, …). See `schema-review-2026-09.md`.
