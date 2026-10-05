# Chat, connected accounts and settings (contract v0.1.0, migration 0010)

Owner: Person 1 · 27 Sep 2026 · Status: built, needs mentor review of the open points at the end.

## 1. Chat (Client Collaboration)

**What it is:** one conversation per clinic, between the clinic's people and Radial Pulse
(the clinic's DSM, and Platform Administrators when needed). Matches the "Clinic Chat" tab
(web) and "Chat with your Digital Growth Specialist" (mobile).

```
clinic ── chat_messages (one row per message, never edited or deleted)
      └── chat_read_states (one row per person: "I have read up to …")
attachment → assets (kind chat_attachment, normal S3 upload)
```

| Table | Columns | Rule |
|---|---|---|
| `chat_messages` | clinic_id, sender_user_id, **sender_name**, **sender_side** (`radial_pulse` / `clinic`), body, attachment_asset_id, created_at | text or attachment required; the app login can only read and add |
| `chat_read_states` | clinic_id, user_id, last_read_at | one per person per clinic; you only see your own |

- **Who:** read = everyone in the clinic (`chat:read`); send = Admin, DSM, Clinic Administrator
  (`chat:write`). Clinic Team Members read only (decision D18).
- **Unread** = messages from other people after my `last_read_at`. Sending moves my own mark.
- **Inbox** (`GET /chat/inbox`): DSM → assigned clinics; clinic people → their clinics;
  Platform Administrator → only the chats they opened or wrote in (otherwise all 128 clinics would
  show as unread).
- **Delivery:** polling for now. A WebSocket push can be added later; it would only deliver, history
  stays in PostgreSQL.
- **Privacy:** the audit log records *that* a message was sent, never its text. Messages must not
  contain patient health information (decision D19 — the app shows a notice).
- `sender_name` is copied at send time because row-level security may hide the sender's user row
  from the reader (e.g. a Platform Administrator is not linked to the clinic).

## 2. Connected accounts ("Connect Your Accounts")

**What it is:** the clinic signs in to Instagram / Facebook / Google Business Profile / YouTube /
LinkedIn / X and allows **read-only** access, so the data-sync jobs can pull real numbers
(insights, reviews, followers). The website needs no sign-in, so it is not here.

```
Connect → API start → platform sign-in page → back to the app with code+state
        → API complete → token swap (server to server) → tokens saved in AWS Secrets Manager
                                                       → platform_connections row = "connected"
```

| Column | Meaning |
|---|---|
| clinic_id, platform | one row per clinic + platform (reused on reconnect) |
| status | not_connected · pending · connected · needs_reconnect · disconnected |
| external_account_id / _name | which account on the platform (filled by the sync jobs) |
| scopes, token_expires_at | what was granted, until when |
| **secret_ref** | ARN of the Secrets Manager secret with the tokens — **never the token** |
| connected_by_user_id, connected_at, disconnected_at, last_synced_at, last_error | history for the screen |
| oauth_state_hash, oauth_code_verifier, oauth_redirect_uri, oauth_started_at/by | only while a sign-in is in progress, then cleared |

Safety:

- `state` is random and one-time; only its SHA-256 is stored; it is tied to one clinic, one
  platform and the person who pressed Connect, and expires after 10 minutes.
- PKCE (S256) for Google and X. Client secrets stay on the server.
- The return address must be on `OAUTH_REDIRECT_URIS`.
- Tokens: one Secrets Manager secret per connection, `radial-pulse/<env>/connections/<clinic>/<platform>`,
  encrypted with the environment's KMS key. Disconnect schedules deletion (7-day recovery).
- Who: see = everyone in the clinic; connect/disconnect = Admin, DSM, Clinic Administrator.

**Not built yet (next):** refreshing expired tokens and pulling the data (a worker job per
platform, owned with the domain teams), and the "Refresh Data" button that queues it.

## 3. Settings

| Screen | Stored in | Who |
|---|---|---|
| My Profile: name, phone | `users` | yourself |
| My Profile: photo | `users.avatar_key` (S3 `users/<id>/avatar/…`) | yourself |
| Notifications | `notification_preferences` (user, category, channel, enabled). No row = on | yourself |
| Security | nothing to store: sign-in is Google only; shows `last_login_at` | yourself |
| General (org name, support email/phone, timezone, date format) | `platform_settings` (exactly one row) | read: everyone signed in · change: Platform Administrator |
| Integrations | nothing stored: read from the server's configuration (never secrets) | Platform Administrator |
| User Management | existing `/users` | Platform Administrator |

Notification categories today: `clinic_assigned`, `work_item_assigned`, `approval_handoff`.
Channels: `in_app` (used now) and `email` (saved now, sending comes later). All in-app
notifications now go through `app.services.notify.send`, which checks the switch. Because the
switches are private (row-level security), the check uses the database function
`rp_notification_enabled()`, which answers only true/false.

## 4. Row-level security (all checked on PostgreSQL 16 as the app login)

| Table | Rule |
|---|---|
| chat_messages | clinic in scope; read + insert only (no update/delete for the app login) |
| chat_read_states | clinic in scope **and** your own row |
| platform_connections | clinic in scope; no delete |
| platform_settings | read: everyone; update: all-clinics scope only; no insert/delete |
| notification_preferences | your own rows only |

## 5. Open points for the mentor

1. **D18** — Should Clinic Team Members also send chat messages? (Now: read only.)
2. **D19** — Chat and health information: confirm "no patient health information" is the rule.
3. **Secrets cost** — one Secrets Manager secret per connected account (~USD 0.40/month each).
   Fine for the pilot; at scale, one secret per clinic would be cheaper.
4. Meta and LinkedIn need an **app review** before real clinics can grant these permissions.
   Start the reviews early.
