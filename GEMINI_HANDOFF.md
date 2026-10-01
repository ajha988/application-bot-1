# Continue Application Bot in Gemini

## User's goal

Build a working job-application bot with Python FastAPI, React and SQLite. Import jobs from scheduled-job-search JSON/API output. Parse JD text, match against a verified master profile, generate and store job-specific resumes without inventing experience, prepare forms with Playwright, and stop before submission. Require explicit approval via portal or signed official WhatsApp Cloud API webhook. Track application history, metrics, interviews, next actions, email confirmations/recruiter messages/rejections/follow-ups. CAPTCHA and MFA require manual intervention. Final submission currently remains manual after approval.

Latest requirements: private GitHub repository first, full hosting/domain later; user-account login; up to FOUR personas per user (e.g. Audit and Developer); separate profiles, job queues, artifacts, credentials and all application workflows per persona. A user must never access another user's or persona's data. GitHub Pages cannot execute FastAPI or Playwright, so do not claim a Pages-only deployment runs the full app. GitHub account/repository identity has NOT been supplied.

## Status — important

The single-user MVP and credential vault previously built successfully and passed nine backend tests. Live employer/browser execution, Docker/noVNC and external integrations were not verified. No real application or WhatsApp message was submitted. No GitHub repo or public deployment exists.

MULTI-USER DEVELOPMENT WAS STOPPED MID-IMPLEMENTATION at the user's request. Current source is incomplete and has NOT passed tests since these changes. Do not present this ZIP as a finished multi-user release. The old React portal still uses the demo API token while the newly changed backend now requires account sessions/persona ownership, so frontend/backend currently need reconciliation.

## Included files and implementation

- `backend/main.py`: state machine, scoped database operations, resume generation, job endpoints, approvals, email hooks, WhatsApp signature handling. Recently changed to persona filesystem isolation using `accounts.CURRENT_USER` and `CURRENT_PERSONA` context variables installed by middleware. Workspaces: `data/users/<user-id>/personas/<persona-id>/`.
- `backend/accounts.py`: newly added account registration/login/logout, salted PBKDF2 password hashes, hashed opaque session tokens, HttpOnly session cookie, CSRF checks for cookie-authenticated mutations, persona ownership, atomic four-persona limit, per-persona ingestion keys. Accounts metadata resides in `data/accounts.sqlite`. Registration initializes an Audit persona with sample jobs; added personas start empty.
- `backend/vault.py`: encrypted career-site usernames/passwords, master-password-derived key, 30-minute in-memory unlock, exact host/path scoping. Recently binds unlock tokens to user/persona scope. Passwords must never enter timelines, notifications or logs.
- `backend/automation.py`: basic Generic/Greenhouse/Lever/Workday preparation scaffold, allowlisted HTTPS requests, saved login reuse, CAPTCHA/MFA pause, screenshots, retained job browsers. Recently accepts persona-specific allowed hosts and uses headless Chromium in production. No final-submit action exists.
- `backend/desktop.py`, `deploy/`, Dockerfile and compose config: earlier SINGLE-USER noVNC desktop deployment scaffold. The main multi-user app DISABLES shared desktop access because sharing a display would expose other users' sessions. Build isolated browser workers/per-user review before restoring interactive remote access; never re-enable one shared public desktop.
- `frontend/src/Account.jsx`, `Personas.jsx`, `accounts.css`: NEW, not yet connected to the main React app. Login/register view, persona creation and scoped ingestion-key UI.
- `frontend/src/main.jsx`: earlier portal with jobs, workflow controls, metrics, timelines, credentials, setup/profile editor. Still uses shared demo bearer token. Needs account bootstrap, persona selection, session/CSRF headers and state reset on persona/account change.
- `frontend/src/Setup.jsx`: persona profile and allowed-host editing needs WhatsApp recipient-number field, profile changes per persona and wording review.
- `frontend/src/Vault.jsx`: UI exists, ensure unlock session and all sensitive state clear when persona changes/logout.
- `backend/test_workflow.py`, `test_vault.py`, `test_setup.py`, `test_desktop.py`: older tests target single-user bearer-token flow and must be updated. `test_desktop.py` refers to the retired shared desktop.
- `scripts/multiuser_upgrade.py`: one-off transformation ALREADY executed against main.py. DO NOT rerun; inspect final source directly. Remove this temporary transformation script once implementation is completed.
- `README.md`, `DEPLOYMENT.md`, `VERIFICATION.md`: refer mainly to the older single-user version; reconcile after completing multi-user changes. The 'nine passed' statement applies ONLY to the earlier source, not current code.

## Resume/profile and chosen real job

User requested an audit-related job from their scheduled search. `selected-live-job.json` contains public AHEAD — Risk Analyst, Gurugram, hybrid, sourced from the user's 'Global IT Risk Job Watch' chat and employer page checked on 1 October 2026:

https://jobs.lever.co/thinkahead/059ea6d8-cc40-4982-b5dc-c7e9dc989b7d/apply

Its form requires availability, three technical skills, current salary and expected salary. These must come from the user; do not fabricate answers. The JD in that JSON is a paraphrased summary for the first test, not a verbatim full posting. Recheck the employer page before applying.

Only a fictional sample profile is bundled. The user's current audit resume has NOT been attached in this chat. Do not derive a real resume from earlier AI-generated claims or another candidate's resume. Ask for the verified source or have the user enter it in Setup.

## Hosting context

User initially mentioned GoDaddy but did not provide a VPS/server or domain. Later changed immediate priority to a PRIVATE GitHub repository and multi-user personas, with actual domain hosting later. Do not purchase hosting, expose data or claim deployment is done. Need GitHub username/repo and authenticated publishing access. Never include `.env`, databases, personal profiles, browser cookies, credentials or resumes in GitHub.

## Recommended next steps

1. Inspect current sources; finish account login/register bootstrap and persona navigation in React. Replace demo token login. On reload use `/api/auth/me`; use the returned CSRF token for cookie-authenticated mutations. Send `X-Persona-ID` on scoped endpoints. Ensure stale requests cannot repopulate another persona's screen.
2. Audit all filesystem/SQL accesses, vault sessions, screenshots/downloads, notification recipient routing, browser contexts and WhatsApp job routing. Confirm exact ownership checks. Remove global personal-profile fallback and shared-user credentials. Check API keys permit only ingestion/email hooks for their owner persona.
3. Update tests for registration/sign-in, logout/expiry/CSRF, four-persona limit, cross-account and cross-persona denial, profile/artifact isolation, vault token isolation, concurrent creation, duplicate URLs per persona, approval invalidation and webhook recipient isolation. Retain tests proving approval never submits.
4. Fix production browser review isolation and enforce safe target-host validation. Multi-user remote interactive review is NOT solved by exposing the old noVNC desktop.
5. Build React, run the updated tests, then smoke-test two accounts with Audit and Developer personas. Update all docs and verification claims to measured outcomes.
6. Prepare/push a private GitHub repo only once account/repo access is supplied. Full hosted backend needs an actual server/cloud runtime in addition to GitHub; original Docker stack must be verified before deployment.

## Local commands

From this extracted project directory, with Python 3.11+ and Node.js installed:

```sh
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend
npm install
npm run build
cd ..
python -m pytest backend -q
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Expect existing tests/UI to need the fixes above before these are all green. Sources and older built frontend are included; no runtime environment or private data is bundled. Do not assume the bundled built frontend reflects account/persona components.

## User preferences

User is nontechnical, wants action with few confirmations, and has limited tokens. Keep progress/final messages concise. Never claim unverified functionality, deployment, browser submission or integrations are working. Complete authorized reversible work autonomously and ask only for genuinely missing external access or verified personal information.
