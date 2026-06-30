# Deploying Hot Death Uno to hdu.ospdy.com

Self-hosted on the cloud Ubuntu box: the app runs in Docker bound to
`127.0.0.1:8126`, and the host's **nginx** reverse-proxies `hdu.ospdy.com`
(TLS + WebSocket) to it. v1 is a single uvicorn worker with in-memory game
sessions — fine for user testing; games are lost on restart.

## Prerequisites
- DNS: an **A/AAAA record for `hdu.ospdy.com`** pointing at the server's public IP.
- Docker Engine + the Compose plugin (`docker compose version` should work).
- nginx + certbot (`python3-certbot-nginx`) already on the host.

## 0. Get the code onto the host

The build needs only these paths (the `.venv`, `tests/`, and editor cruft are
**not** required, and `.dockerignore` keeps them out of the image regardless):

```
Dockerfile  .dockerignore  requirements.txt  docker-compose.yml  hdu/  server/  deploy/
```

### Option A — GitHub (recommended; repeatable updates)
From this dev machine, one-time:
```bash
git init && git add -A && git commit -m "Hot Death Uno: engine + web app"
gh repo create hot-death-uno --private --source=. --remote=origin --push
```
On the Ubuntu host (needs git access to the private repo — add an SSH deploy key,
a PAT, or run `gh auth login` on the host). `/srv` is root-owned, so either take
ownership first or clone with sudo:
```bash
sudo mkdir -p /srv/HotDeathUno && sudo chown "$USER" /srv/HotDeathUno
git clone git@github.com:<you>/hot-death-uno.git /srv/HotDeathUno
cd /srv/HotDeathUno
```
Updates later: `git pull && docker compose up -d --build`.

### Option B — Manual transfer (no GitHub)
From this dev machine (copies just the needed paths; skips `.venv`/tests):
First make the target writable: `sudo mkdir -p /srv/HotDeathUno && sudo chown "$USER" /srv/HotDeathUno` (on the host).
```bash
rsync -av --exclude='__pycache__' \
  Dockerfile .dockerignore requirements.txt docker-compose.yml hdu server deploy \
  <user>@<host>:/srv/HotDeathUno/
```
…or as a tarball:
```bash
tar czf hdu.tgz Dockerfile .dockerignore requirements.txt docker-compose.yml hdu server deploy
scp hdu.tgz <user>@<host>:/srv/HotDeathUno/   # on host: cd /srv/HotDeathUno && tar xzf hdu.tgz
```
Updates later: re-run the rsync/scp, then `docker compose up -d --build`.

## 1. Build & run the container
```bash
cd /srv/HotDeathUno
docker compose up -d --build
curl -s localhost:8126/ | head -c 60   # sanity: should return the SPA HTML
```

## 2. Wire up nginx
```bash
sudo cp deploy/nginx/hdu.ospdy.com.conf /etc/nginx/sites-available/hdu.ospdy.com
sudo ln -s /etc/nginx/sites-available/hdu.ospdy.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
If nginx complains that `$connection_upgrade` is already defined, delete the
`map { ... }` block at the top of the conf (you have one elsewhere already).

## 3. Issue the TLS certificate
```bash
sudo certbot --nginx -d hdu.ospdy.com
```
certbot fills in the `ssl_certificate*` lines and the http→https redirect, then
reloads nginx. Auto-renewal is handled by the certbot systemd timer.

## 4. Verify
Open **https://hdu.ospdy.com** — click *New game* and play. The header should
read **connected** (the WebSocket is up through `wss://`).

## Updating
```bash
git pull && docker compose up -d --build
```

## Operating
- Logs: `docker compose logs -f`
- Restart: `docker compose restart`
- Stop: `docker compose down`
- Change the host port: edit the `ports:` line in `docker-compose.yml` (and the
  `proxy_pass` in the nginx conf to match).

## Notes / v1 limits
- **In-memory sessions, single worker.** Restarting the container drops live
  games. Scaling to multiple workers would need a shared session store (the
  `SessionManager` is kept behind one interface to make that swap clean).
- The published Docker port is bound to `127.0.0.1`, so the app is reachable
  **only** via nginx, never directly from the internet.
- **Gating testers:** only *game creation* is gated (existing games are reached
  via their unguessable id). Two options, which can be combined:
  - **One shared code** — `cp .env.example .env`, set `HDU_PASSCODE=yourcode`,
    `docker compose up -d`.
  - **Many codes, hand-out/revoke live** — `cp tokens.txt.example tokens.txt`
    (one code per line; `code` or `code: label`), uncomment the `HDU_TOKENS_FILE`
    env and the `tokens.txt` volume in `docker-compose.yml`, `docker compose up -d`.
    The file is bind-mounted and read on every check, so adding or removing a
    line takes effect **immediately, no restart**, and revoking one code doesn't
    affect the others. `tokens.txt` is gitignored.

  The SPA prompts for a code whenever the gate is active; empty leaves it open.

## Google sign-in (optional)

Lets players sign in with Google so their **verified first name** is used at the
table (instead of typing one). Identity only — it does **not** replace the
passcode gate unless you set `HDU_REQUIRE_LOGIN`. Leave the client id/secret
blank to disable sign-in entirely (the app runs exactly as before).

1. **Create an OAuth client** in [Google Cloud Console](https://console.cloud.google.com/)
   → *APIs & Services* → *Credentials* → *Create credentials* → *OAuth client ID*:
   - Application type: **Web application**
   - Authorized redirect URI: **`https://hdu.ospdy.com/auth/callback`**
   - (Configure the OAuth consent screen first if prompted; "External" + your
     own email as a test user is enough for a private game.)
2. **Set the env** in `.env` (next to `docker-compose.yml`):
   ```ini
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   HDU_BASE_URL=https://hdu.ospdy.com
   HDU_SESSION_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(32))">
   # optional:
   HDU_REQUIRE_LOGIN=1                  # force sign-in to create/join a game
   HDU_ALLOWED_EMAILS=a@x.com,b@x.com   # restrict who may sign in
   ```
   `HDU_SESSION_SECRET` must be a **stable** value, or every deploy logs everyone
   out. `HDU_BASE_URL` is what makes the callback URL correct behind the nginx
   proxy. All OAuth vars are already wired into `docker-compose.yml`.
3. `docker compose up -d --build`. A **Sign in with Google** button appears in the
   header; once signed in, the name field is replaced by the Google first name.
