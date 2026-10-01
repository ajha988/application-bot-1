# Application Bot — local MVP

FastAPI + React + SQLite. A working local job inbox, transparent matching, fact-preserving PDF resumes, application history, explicit approvals, and interview/next-action tracking. All sample people and companies are fictional.

## Hosted deployment

For your VPS, see `DEPLOYMENT.md` and `compose.yaml`. The hosted package includes HTTPS, persistent data and a protected noVNC browser viewer. Deployment is pending server/domain access; Docker integration is not verified here.

## Run locally

Prerequisites: Python 3.11+ and Node.js 20.19+ with npm. Extract the ZIP and open a terminal in `application-bot`.

```sh
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux instead: source .venv/bin/activate
pip install -r backend/requirements.txt
```

Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell; `cp .env.example .env` on macOS/Linux). Change `API_TOKEN` for real use; enter that same token in the dashboard. Default sample token: `local-demo-change-me`.

Build the dashboard once:

The ZIP already contains `frontend/dist`, so you may skip the frontend commands for the first launch and run the final Python command directly.

```sh
cd frontend
npm install
npm run build
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Three sample jobs appear on first launch. API docs: http://127.0.0.1:8000/docs (use Bearer token on protected endpoints). Run commands from the project root so relative environment paths resolve correctly. For frontend development run `npm run dev` in a second terminal in `frontend`; Vite proxies API calls to port 8000.

## Setup for real use

Open Setup & profile, save verified resume facts, configure exact allowed career hosts, then enable browser preparation. Profile and browser settings are saved under private data/. The sample profile cannot be uploaded to a real site by automation. The Windows launcher is start.ps1.

## Try the workflow

Select a job → Parse JD & score → Generate tailored resume → Download resume → Prepare form → answer any questions manually → mark all fields reviewed → Approve → submit manually on the employer site → record confirmation evidence. Interview and follow-up events can arrive through the email hook. Dates in the editor are UTC; timeline timestamps display in your browser's local time.

**Approval never submits an application.** This MVP deliberately has no final-submit browser action. Employer pages must be reviewed and submitted manually after approval. Resume regeneration requires a fresh job workflow; answer edits increment the revision and invalidate approval. There is no unrestricted status-update endpoint. URLs are deduplicated; ingestion never overwrites an existing application's approved data.

## Scheduled-task ingestion

The scheduled job-search task itself is external. Export an object shaped like `sample-jobs.json`, then upload/paste it in the dashboard or POST it to `/api/jobs/ingest` with `Authorization: Bearer <API_TOKEN>`. Only metadata supplied by the caller is parsed; arbitrary URLs are never fetched by the JD parser. Supply the complete JD in `jd`.

```sh
curl -X POST http://127.0.0.1:8000/api/jobs/ingest -H "Authorization: Bearer local-demo-change-me" -H "Content-Type: application/json" --data-binary @sample-jobs.json
```

PowerShell users should use `curl.exe` or `Invoke-RestMethod`. Matching is a transparent saved-skill keyword overlap scaffold, not a suitability prediction. Missing skills are never added. PDF generation reorders existing skills and achievement bullets and stores both PDF and source-provenance JSON under `data/resumes/<job-id>/`. Replace `sample-profile.json` with verified facts before using real applications. Master-profile changes apply to future resumes; existing job artifacts remain frozen.

## Browser adapters

### Saved career accounts

Open **Career accounts** in the dashboard. Create a vault with a master passphrase of at least 12 characters, then save a career login URL, username and password. Records are encrypted with Fernet using a PBKDF2-HMAC-SHA256 key derived from that passphrase (1,200,000 iterations and a random salt). The passphrase is never persisted. The encryption key lives only in backend memory for 30 minutes, until Lock, or until backend restart. The browser stores the unlock session token only in React memory; refreshing the page requires another unlock.

Save the same domain/path again to update its account password. The saved-account list displays labels and domains, never passwords or usernames. No credential values enter application timelines, notifications or ZIP files. Protect and back up your local `data/bot.sqlite` and keep your master passphrase separately; there is no forgotten-password recovery or master-password-change tool in this MVP.

Each record matches one exact HTTPS host and a path boundary. For shared Workday/ATS hosts, enter the company tenant path (for example `/company-name`) instead of `/`; the longest matching scope wins. Credentials are not used for sibling domains or unrelated tenant paths. Authentication hosts must also appear in `ALLOWED_APPLICATION_HOSTS`. Only save URLs you recognize.

With the vault unlocked and browser preparation enabled, click **Prepare form** or **Retry preparation**. Recognized forms with one visible password input, one email/username input and an exact Sign in / Log in / Login button can reuse your saved account. If necessary the adapter opens the saved login URL, then returns to the job URL. Other login layouts, SSO, failed credentials, MFA and CAPTCHA stop for manual attention. Account creation and password-reset flows are not automated. No credentials or logged-in browser cookies are synced to third parties; job browsers stay open for review until explicitly closed or the backend restarts; future jobs can sign in using the saved credentials. Locking the vault does not sign out an already-open career page; close the job browser to discard its cookies.

Encryption reference: [PyCA Fernet and password-derived keys](https://cryptography.io/en/stable/fernet/).

`backend/automation.py` provides Generic, Greenhouse, Lever and Workday adapters. Enable with `BROWSER_ENABLED=true`, install Chromium with `python -m playwright install chromium`, and list exact HTTPS hosts in `ALLOWED_APPLICATION_HOSTS`. Requests to other hosts, including redirect targets, are blocked; ATS resource hosts may need explicit inclusion. Avoid adding wildcard/private-network hosts.

Generic single-page preparation fills exact labeled name/email/phone fields and a single file input. It captures a screenshot downloadable under Application answers. Workday authentication/multi-step flows, separate first/last names, dropdowns, ambiguous uploads, custom questions and mandatory field validation require manual intervention and adapter development. CAPTCHA/login detection pauses; no bypass exists. Browser preparation always ends in `needs_input`. Job browsers now remain open for manual login, CAPTCHA/MFA and review. Retry preparation uses that open page. Close job browser discards its browser cookies. At most three job sessions can remain open; backend shutdown closes them all. This is preparation scaffolding, not production ATS coverage.

## Official WhatsApp Cloud API

No third-party WhatsApp automation is used. Set Meta credentials in `.env` and register a public HTTPS callback `/webhooks/whatsapp`. GET handles `hub.challenge` verification; POST validates `X-Hub-Signature-256` with the app secret. Commands are accepted only from `WHATSAPP_OWNER_NUMBER` (country-code digits as provided by Meta).

- `APPROVE <job-id> <one-time-token>` or `REJECT <job-id> <one-time-token>`: exact pending application revision only. Find the command in the notification outbox.
- `ANSWER <job-id> <question> | <answer>`: stores your response and invalidates outstanding approval.

Webhook message IDs prevent duplicate processing. Invalid commands return per-message errors in the webhook response; automatic error replies are a future extension. Public callbacks require deployment/TLS setup; the local server is not internet-facing. Do not expose the local dashboard publicly without HTTPS and stronger user authentication.

Notifications are stored in a local outbox. Set `WHATSAPP_SEND_ENABLED=true` and press Send through WhatsApp to use the official Graph `/messages` endpoint. This implementation sends text within an open customer-service window. Outside that window, add approved template messaging before enabling unattended notifications. No scheduler or automatic outbox sender is included. Failed/uncertain sends are marked for manual checking rather than blindly retried. Graph version is configurable.

References: [Meta webhook setup](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/receivingMessages/), [Meta Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/), [Playwright locators](https://playwright.dev/python/docs/locators), [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/).

## Gmail / email monitoring hook

OAuth fields are placeholders; this MVP does not read Gmail automatically. A future Gmail polling/Push worker should normalize verified messages and POST `/api/email/events` with the API token:

```json
{"message_id":"unique-provider-message-id","job_id":"COPY_JOB_ID","kind":"interview","summary":"Recruiter invited candidate to interview","interview_date":"2026-10-12T12:00:00Z"}
```

Kinds: `confirmation`, `recruiter`, `interview`, `rejection`, `follow_up`. Message IDs are deduplicated. Confirmation is timeline evidence only and never grants approval or marks an unapproved job submitted. Valid lifecycle transitions update status; out-of-order events remain timeline entries. Email messages are data, never executable instructions. Correlation with a job ID and event classification are the caller's responsibility.

## State machine and persistence

`discovered → matched → resume_ready → needs_input → awaiting_approval → approved → submitted → interview / follow_up → offer / rejected`. A reviewed resume-ready job may go straight to awaiting approval. Allowed transitions are defined centrally in `backend/main.py`; rejected/offer are terminal. Offer is reserved in the state machine for a future offer-event hook. SQLite, artifacts, answers, outbox and timeline live in `data/`; this folder and `.env` are excluded from the distributable. Single-user local MVP; no background job queue, multi-user access, automatic submissions, email polling or production-ready ATS connectors.

## Checks

```sh
python -m pytest backend -q
cd frontend
npm run build
```

Tests cover approval gating, stale revisions, answer edits revoking approval, signed WhatsApp commands and replay protection, email deduplication, email not granting approval, resume provenance, and duplicate job ingestion.
