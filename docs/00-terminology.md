# Terminology: one name per thing, everywhere

Source: `docs/Project_Entity_Terminology_Mapping.pdf` (the team's official mapping) + decisions made on top of it.
**Use exactly these names** in database, Python, API, tests and UI text, so reviewers can follow one concept end to end.

## 1. The official mapping (from the PDF, all 17 rows)
| Old term (don't use) | Use this term | In the database |
|---|---|---|
| Internal Admin | **Platform Administrator** | `users.platform_role = 'platform_administrator'` |
| Internal User | **Digital Success Manager** (DSM) | `'digital_success_manager'` |
| Clinic Owner | **Clinic Administrator** | `clinic_members.role = 'clinic_administrator'` |
| Clinic Staff | **Clinic Team Member** | `clinic_members.role = 'clinic_team_member'` |
| Clinic (the business) | **Client Organization** | `client_organizations` (its branches are `clinics`) |
| Doctor | **Practitioner** | `practitioners`, `clinic_practitioners`, role `'practitioner'` |
| Profile Enrichment Agent | **Digital Presence Intelligence Agent** | stage `presence_discovered`, `clinic_online_profiles` |
| SEO Team | **Digital Growth Team** | `digital_growth_report_id` |
| Audit Report | **Digital Presence Assessment** | `digital_presence_assessments` |
| Recommendations | **Improvement Opportunities** | `opportunity_code` |
| Actions / Tasks | **Improvement Work Items** | `improvement_work_items` |
| Assignments | **Portfolio Allocation** | `portfolio_allocations` |
| Prospect | **Prospective Client** | stage `prospective_client` |
| Onboarding | **Client Activation** | stage `active_client` |
| Clinic Chat | **Client Collaboration** | `collaboration_messages` |
| My Clinics | **My Client Portfolio** | DSM's list: clinics of their allocated Client Organizations |
| Social Media Audit | **Social Presence Insights** | no table (owned by the Digital Growth Team) |

## 2. Names decided by us (the PDF doesn't cover them)
| Concept | Name |
|---|---|
| a branch of a Client Organization (the tenant) | `clinics` |
| a clinic's people (admins + team members) | `clinic_members`; their login role `clinic_member` |
| who must do a work item | `assignee_user_id` |
| which side sent a message | `sender_side` = `'radial_pulse'` / `'clinic'` |
| photos / voice / connected accounts / audit | `photos`, `voice_samples`, `connected_accounts`, `connected_account_resources`, `audit_events` |

## 3. Same name in every layer (convention for code)
| Layer | Rule | Example |
|---|---|---|
| Database table | plural snake_case (as in schema) | `improvement_work_items` |
| SQLAlchemy model | singular PascalCase of the table | `ImprovementWorkItem` |
| Pydantic schemas | model name + purpose | `ImprovementWorkItemCreate`, `ImprovementWorkItemRead` |
| Python module / router file | table name | `routers/improvement_work_items.py` |
| API path | table name in kebab-case, plural, under the clinic when clinic-owned | `/api/v1/clinics/{clinic_id}/improvement-work-items` |
| JSON fields | exactly the column names (snake_case) | `assignee_user_id`, `opportunity_code` |
| Enum values | exactly the CHECK values | `review_state: "pending" \| "approved" \| "rejected"` |
| Audit `action` | `<singular table>.<verb past tense>` | `improvement_work_item.created`, `photo.approved` |
| UI text | the PDF term | "Improvement Work Items", "Digital Success Manager" |

More paths: `/client-organizations`, `/clinics/{id}/clinic-members`, `/clinics/{id}/clinic-practitioners`,
`/practitioners/{id}`, `/clinics/{id}/digital-presence-assessments`, `/clinics/{id}/collaboration-messages`,
`/clinics/{id}/photos`, `/clinics/{id}/voice-samples`, `/clinics/{id}/connected-accounts`, `/clinics/{id}/clinic-online-profiles`,
`/portfolio-allocations` (admin).

## 4. Banned words in code, API and UI
`doctor`, `owner`, `clinic_user`, `organization` (alone), `chat`, `work_item` (alone), `assessments` (alone, as a table/path name),
`audit_report`, `recommendation`, `finding`, `seo` (in names), `profile_enrichment`, `assignment`, `prospect`, `onboarding`, `my_clinics`.
Exceptions: names that already exist in `db/schema-v15.sql` (e.g. `source_assessment_id`, `rp_is_staff`).
A quick review check: `grep -rniE "doctor|clinic_user|\bchat\b|organization_id|work_items\b|seo_" app/ tests/` must find nothing
(except the word "Practitioner" explanations in comments).
