# Claude + Juniper Mist (with optional ClearPass NAC) — Starter Kit

A sanitized starter for standing up a **Claude Desktop (Cowork) project** that automates
**Juniper Mist** (Phase 1) and, optionally, adds **Aruba ClearPass NAC** (Phase 2).

## Quick start (guided — do this first)

Run the setup wizard. It asks for each value, tells you **where to find it**, **validates it live**
(tests your Mist token, and ClearPass if you add it), and writes `inventory/credentials.yml` for you:

```
python3 setup.py
```

**To get running you need only 2 values** (Phase 1 / Mist): your **Mist `org_id`** and a **Mist API
token**. That's it — Claude can then connect and start auditing/managing Mist. ClearPass (Phase 2) is
**optional**; the wizard skips it unless you opt in.

Tip: start with a **read-only** Mist token (Observer role) to test safely, then swap to a
**read-write** token when you want to push changes — the wizard tells you which kind you pasted.

You enter these at the wizard's **terminal prompts** — **not in the Claude chat.** Heads-up on the
token: it's a **hidden** prompt, so **nothing appears as you paste it** — no characters, no dots, no
cursor movement. That's normal; just paste and press Enter (the wizard then validates it, so you'll
know it worked). Secrets stay on your machine in `credentials.yml`; Claude reads them from that file,
so you never paste your token into a conversation.

Then open **`docs/Claude-Mist-ClearPass-Deployment-Guide.md`** and continue from §1.3 (create the
Claude project and connect this folder).

## What's inside
- `setup.py` — the guided setup wizard (standard-library only; run before anything else).
- `docs/` — the full deployment guide (Phase 1 Mist, Phase 2 optional ClearPass).
- `scripts/` — the automation the project runs (Mist WLAN/template mgmt, reconcile; ClearPass
  deploy/backup/CoA validation).
- `inventory/credentials.example.yml` — reference scaffold (the wizard writes the real
  `credentials.yml` for you; that file is gitignored).
- `best-practices/` — the binding engineering standards the project follows.

## About the placeholders
This kit contains **no secrets and no real network data**. The `CAPS`/`<...>` placeholders you'll see
(`HYPERVISOR_IP`, `CLEARPASS_IP`, `YOUR_SITE_ID`, `YOUR_ZIP_PASSWORD`, `/path/to/keys/...`) are **not**
setup values — most are Phase 2 (ClearPass) or **per-command arguments** you pass when you run a
specific action (e.g. a site ID when managing a WLAN). To get Mist operational you only supply the two
values above, via `setup.py`.

## Security
Real secrets go **only** in `inventory/credentials.yml`, which `.gitignore` keeps out of git. Never
commit a filled-in copy or any key. Verify a secret's *presence*, not its value. See the guide's
"Secrets & Safety" section.
