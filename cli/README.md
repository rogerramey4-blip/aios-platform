# AIOS CLI (`aios`)

Command-line client for a **Client Builder** to configure their assigned client's
AIOS over the REST API. Standard library only — no `pip install` required.

## What a builder can do

A builder is an implementer assigned to **one** client. Their token is bound to
that client server-side, so every command only ever touches that client's AIOS:

- Build and configure per-client **agents** (create/edit/enable/disable/delete)
- Connect / test / disconnect platform **integrations**
- Upload and list **documents**
- Add and verify custom **domains**
- Provision the client's own **staff users** (member/admin)
- Read and update tenant **settings**

A builder can **never** reach another client or the super-admin panel.

## Install

```bash
# from the repo root
chmod +x cli/aios.py
sudo ln -s "$(pwd)/cli/aios.py" /usr/local/bin/aios     # optional: put it on PATH
# or just run it directly:  python3 cli/aios.py whoami
```

Requires Python 3.8+.

## Authenticate

A super-admin issues you a token in **Admin → open your client → Builders &
Access → Issue CLI Token**. It is shown once. Then:

```bash
aios login                      # paste the token when prompted (input hidden)
aios login --url https://your-aios-host            # if not the default host
aios whoami                     # confirm identity, client, and scopes
```

The token is stored at `~/.aios/config` with `0600` permissions. CI/scripts can
skip the file and set `AIOS_TOKEN` (and optionally `AIOS_URL`) as env vars.

## Usage

```bash
# Integrations
aios integrations list
aios integrations list --industry restaurant
aios integrations connect toast_pos --field client_id=ABC --field client_secret=XYZ
aios integrations test toast_pos
aios integrations disconnect toast_pos

# Documents
aios docs list
aios docs upload ./employee-handbook.pdf

# Domains
aios domains list
aios domains add app.theclient.com
aios domains verify <domain_id>

# Client staff users (never builders/super-admins)
aios users list
aios users add jane@theclient.com --name "Jane Doe" --role member

# Agents (build & configure per-client agents)
aios agents list
aios agents create --field name="Overdue Invoice Chaser" --field agent_type=Composer \
                   --field status=draft --config instructions="Chase invoices >30d overdue" \
                   --config schedule="daily 8am" --config model=claude-opus-4-8
aios agents get <agent_id>
aios agents update <agent_id> --field description="Now also escalates at 60d"
aios agents enable <agent_id>
aios agents disable <agent_id>
aios agents delete <agent_id>

# Settings
aios settings get
aios settings set --field contact_email=ops@theclient.com --field notes="Phase 2"

aios logout
```

## Security notes

- The token carries **scopes** (e.g. `integrations:write`). A call needing a
  scope your token lacks returns `403`. Ask for a broader token if needed.
- Tokens **expire after 90 days** by default and can be **revoked instantly** by
  a super-admin. A revoked or expired token returns `401` — run `aios login`
  with a fresh one.
- Disabling your builder account disables **all** your tokens at once.
- Treat the token like a password. If it leaks, ask for it to be revoked.
