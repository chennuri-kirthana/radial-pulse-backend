# Open questions: don't guess these. Ask me when you reach them

| # | Question | Needed for |
|---|---|---|
| Q1 | ~~Data for other backends via `/internal`~~ **Answered 8 Oct (changed the same day):** other teams read through read-only `/api/v1/internal/*` routes in this backend, as database role `radial_service`. No separate MCP server. | internal API |
| Q2 | How do Digital Presence Assessment results arrive (they call us, or we fetch)? Which fields? | report import |
| Q3 | Which Google / Meta products and OAuth scopes for Milestone 1 (Business Profile, Search Console, Analytics, YouTube, Instagram)? | connected accounts |
| Q4 | Photo upload limits: max size, minimum resolution, allowed types (schema allows jpeg/png/webp/heic)? | upload endpoint |
| Q5 | Presigned link lifetimes (suggested: upload 10 min, view 5 min)? | uploads / viewing |
| Q6 | A practitioner leaves all his clinics: deactivate his login automatically? | practitioner lifecycle |
| Q7 | Email sending service and templates for invites and notifications? | invites, notifications |
| Q8 | Scheduled jobs (OAuth ticket cleanup, token refresh): Lambda or ECS scheduled task? | jobs |
| Q9 | Cognito details: user pool id, app client id(s), region, and whether to block sign-up of non-invited emails | login |
| Q10 | Allowed values for `notifications.category` (beyond the 4 preference categories) and `audit_events.actor_type` | notifications, audit |
