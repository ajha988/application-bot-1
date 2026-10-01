# Deploy on your existing VPS

This deployment has not yet been executed. It needs your server hostname, SSH access and domain. No cloud account has been created, no paid service ordered, and no real application submitted.

## Prerequisites

- A Linux VPS with Docker Engine and Docker Compose installed. Reserve at least 2 GB RAM for the app plus visible Chromium (more for multiple concurrent browsers).
- A domain/subdomain whose DNS points to this VPS, with ports 80/443 reachable. Caddy handles HTTPS certificates. Keep existing sites/port ownership in mind; adapt the gateway if you already have a reverse proxy.
- Only the HTTPS gateway is public. FastAPI, VNC and WebSocket bridge bind internally; do not expose ports 5900, 6080 or 8000.

## First deployment

Upload the project source to a dedicated directory on the VPS. Runtime databases, vault records, personal profile, browser state and `.env` must not be uploaded from an existing local test workspace.

```sh
cp .env.example .env
chmod 600 .env
```

Set a new, random `API_TOKEN` of at least 32 characters in `.env` (a 64-character hex value is suitable). Generate it on the server with `openssl rand -hex 32`; do not paste it into chat or commit it. Add `BOT_DOMAIN=applications.your-domain.example` using your real domain. Keep `BROWSER_ENABLED=false` until you save a verified profile and allowed hosts through Setup. The container ignores the example token and fails closed in production.

```sh
docker compose up -d --build
docker compose logs --tail=100 bot
```

Open `https://YOUR_DOMAIN`, expand **Connection settings**, and enter the private API token you set on the VPS. The public portal shell does not grant access to application data. This remains a single-user bearer-token app; keep the token private. Automatic jobs require your configured hosts and verified facts.

## First real application

1. Save your verified master profile through **Setup & profile**. Experience is structured JSON in this MVP; use actual resume facts.
2. Add the job URL plus full JD via JSON import. Scheduled-task ingestion uses the same hosted `/api/jobs/ingest` endpoint with the private Bearer token.
3. Set the exact career/ATS hosts in Setup and enable browser preparation. The container already installs Chromium.
4. Match the job, generate its resume, then prepare the application. The server keeps up to three job browsers open.
5. Press **Enable browser view**, then **Open job browser**. A short-lived HttpOnly cookie grants access to the server desktop. Manually handle MFA/CAPTCHA/login if needed. Retry preparation to continue using the same open page.
6. Review the actual form. Mark ready, approve, then manually click Submit in the browser. Record the confirmation evidence in the portal. Automation has no final-submit action.
7. Close the job browser after completing/rejecting the application. Updating browser configuration closes all active job browsers. Restarting the server closes sessions and locks the vault.

The remote desktop is a single-user shared desktop for all job sessions. Its auth cookie expires after 30 minutes; already-connected WebSocket viewers may remain active until disconnected, so close viewer tabs when finished. Vault Lock prevents new decryptions but does not sign out an already-open career website; close job browsers to discard their active cookies. Browser cookies remain ephemeral and are not stored in the vault.

## Integrations

WhatsApp webhook URL: `https://YOUR_DOMAIN/webhooks/whatsapp`. Configure official Meta credentials as private environment values; approval nonce and signed webhook handling are implemented. Outbound notifications still require manually triggering Send and an appropriate Meta service window/template. Gmail OAuth values and normalized email hooks remain scaffolds; automatic Gmail polling is not active.

## Persistence, maintenance and limits

SQLite, encrypted credentials, verified profile, browser settings and job resumes live on the named `application-data` volume. Do not use `docker compose down -v`: it removes the volume. Back up the volume before updates and keep the vault master password separately. Application timelines and the master profile are not encrypted; restrict VPS and backup access.

To update: copy the new source into the dedicated deployment directory, preserve the server's `.env`, and run `docker compose up -d --build`. The VPS package was prepared and Python/frontend checks passed; Docker/noVNC integration cannot be verified on this Windows environment because Docker is unavailable. A live server smoke test is required before declaring it operational.

References: [Docker Compose configuration](https://docs.docker.com/compose/), [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https), [noVNC embedding](https://novnc.com/noVNC/docs/EMBEDDING.html), [nginx auth subrequests](https://nginx.org/en/docs/http/ngx_http_auth_request_module.html).

`render.yaml` is an optional alternative deployment blueprint, using a paid persistent service. Review provider charges before using it; the chosen target for this conversation is your existing VPS.
