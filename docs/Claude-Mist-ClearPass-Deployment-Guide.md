# Claude + Juniper Mist Deployment Guide — with optional ClearPass NAC (Phase 2)

> **What this is:** a blueprint for standing up a **Claude Desktop (Cowork) project on one PC** that
> integrates with and automates **Juniper Mist (Phase 1)**, and — optionally — adds **Aruba ClearPass
> as a NAC layer (Phase 2)**. Self-contained: the executor MCP, git repo, and scripts run locally on
> the PC (WSL2 or native Windows). No separate utility server.
>
> **Two phases:**
> - **Phase 1 — Claude + Mist (cloud).** Stand up the project + local executor, connect Mist, and let
>   Claude audit, manage, and validate Mist. This is standalone value and needs only internet access.
> - **Phase 2 (optional) — Claude + ClearPass (NAC).** Deploy ClearPass as a VM, connect Claude, and
>   configure guest onboarding + CoA using the **Juniper-native (Cisco-free)** method. This phase
>   needs the executor **on the lab LAN** (it acts as a RADIUS NAD on udp/3799 for validation).
>
> **Source of truth is git.** The repo is a local clone on the PC, backed by GitHub. Cowork projects
> don't sync between machines — recreate them from the git-versioned Instructions block + connected
> folder. Written 2026-07-05.

---

## Overview

| | Phase 1 — Claude + Mist | Phase 2 (optional) — Claude + ClearPass |
|---|---|---|
| Purpose | Automate/manage Juniper Mist (WLAN, RF, templates, inventory) | Add enterprise NAC: guest onboarding, 802.1X, CoA |
| What it talks to | Mist cloud API (`mist_*`) | ClearPass VM REST API (`clearpass_*`) + RADIUS/CoA |
| Where the PC must sit | Anywhere with internet (Mist is cloud) | **On the lab LAN** (RADIUS NAD role, udp/3799) |
| New infra | none | a ClearPass VM on a hypervisor |
| CoA method | n/a | **Vendor = Juniper + `[Juniper Terminate Session]`** (no Cisco) |

---

## Before you begin — Claude Desktop and Cowork

This workflow runs in **Cowork**, so install the app first and know which mode you are in.

**1. Install Claude Desktop and sign in.** Download the Claude desktop app from <https://claude.com/download> (Windows or Mac), install it, and sign in. Cowork requires a **paid Claude plan** and is a **research preview** rolling out gradually, so it may not appear for every eligible account immediately.

**2. Know the three ways to use Claude — this guide uses Cowork:**

| | What it is | Used here? |
|---|---|---|
| **Claude Chat** | The normal conversational assistant (web / mobile / desktop) — questions, writing, analysis. Does not touch your files or run tools. | No |
| **Cowork** | An agentic mode **in the desktop app** that works on your computer: reads/writes files in folders you connect, runs local tools via MCP, drives a browser, completes multi-step tasks. | **Yes — this guide** |
| **Claude Code** | A command-line tool for developers to delegate coding from the terminal. | No |

In **Cowork** you will create a **project**, connect the NAC-Starter folder to it, register the local executor (the `nac-executor` MCP), and Claude acts as the operator that runs the kit. Everything in §1.2–§1.3 below is done in the Claude **desktop app**.

---

# PHASE 1 — Claude + Juniper Mist

## 1.1 What you're building

```
        +------------------- YOUR PC -------------------+
        | Claude Desktop project ("Mist Automation")    |
        |    | operator                                 |
        |    +-- local executor MCP (files/git/scripts) |         Mist cloud
        |    +-- hpe-networking MCP (mist_*) -----------------+---> org / sites / WLANs
        |    +-- Claude-in-Chrome (dashboards, downloads)|    |    RF / device config
        |    +-- local git clone (scripts, inventory) ---+    |    templates
        +-----------------------------------------------+
```

Mist is a cloud service, so Phase 1 needs only internet — the PC does not have to be on the lab LAN.
The project's job: read and reconcile Mist config, manage WLANs/templates safely, and keep the repo
as the source of intent.

## 1.2 Set up the machine + the local executor

Pick **one** path. **Option A (WSL) is recommended** — it matches how the kit was built and tested.
**Option B (native Windows)** skips WSL and is a bit simpler for Phase 2's on-LAN CoA test (no NAT in
the way). Both end the same way: register the executor in Claude Desktop.

### Option A — WSL (recommended)

**A1 · PowerShell (Windows):**
```powershell
wsl --install -d Ubuntu
```
Restart Windows if prompted, then open **Ubuntu** from the Start menu and set a username + password.

**A2 · Ubuntu (WSL) terminal:**
```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/hpe-networking-lab/NAC-Starter.git
cd NAC-Starter
python3 -m venv mcp-server/.venv
mcp-server/.venv/bin/pip install -r mcp-server/requirements.txt -r requirements.txt
python3 setup.py
echo "python: $PWD/mcp-server/.venv/bin/python"
echo "server: $PWD/mcp-server/server.py"
```
(Note your username with `whoami`; the paths look like `/home/<username>/NAC-Starter/mcp-server/...`.)

**A3 · Claude Desktop config.** In the Claude desktop app open **Settings → Developer → Edit
Config** — that button opens (and creates, if it does not exist yet) the config file
`claude_desktop_config.json` (on Windows it lives at `%APPDATA%\\Claude\\claude_desktop_config.json`).
There is no separate installer — you just edit this JSON file. Paste this block, replacing the two
paths and the distro name:
```json
{
  "mcpServers": {
    "nac-executor": {
      "command": "wsl.exe",
      "args": [
        "-d", "Ubuntu",
        "/home/<username>/NAC-Starter/mcp-server/.venv/bin/python",
        "/home/<username>/NAC-Starter/mcp-server/server.py"
      ]
    }
  }
}
```

### Option B — native Windows (no WSL)

**B1 · PowerShell (Windows)** — install Python + Git, then close and reopen PowerShell so PATH updates:
```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
```
```powershell
git clone https://github.com/hpe-networking-lab/NAC-Starter.git
cd NAC-Starter
python -m venv mcp-server\.venv
mcp-server\.venv\Scripts\pip install -r mcp-server\requirements.txt -r requirements.txt
python setup.py
(Resolve-Path mcp-server\.venv\Scripts\python.exe).Path
(Resolve-Path mcp-server\server.py).Path
```

**B2 · Claude Desktop config.** Open the same config file — in the Claude desktop app,
**Settings → Developer → Edit Config** opens (and creates if needed)
`claude_desktop_config.json` (`%APPDATA%\\Claude\\` on Windows). Paste this block, using the two
paths from `Resolve-Path` above (JSON needs **double** backslashes):
```json
{
  "mcpServers": {
    "nac-executor": {
      "command": "C:\\Users\\<you>\\NAC-Starter\\mcp-server\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\<you>\\NAC-Starter\\mcp-server\\server.py"]
    }
  }
}
```
*Phase 2 only:* allow the RADIUS/CoA ports through Windows Firewall (udp 1812, 1813, 3799).

### After either option

Merge the block into any existing `mcpServers`, **save**, then **fully quit and reopen Claude
Desktop**. Under **Settings → Developer** you should see **nac-executor** connected, exposing
`list_directory`, `read_file`, `write_file`, `run_command`, `run_script`, `git_status`, `git_commit`.
It is confined to the NAC-Starter folder and blocks destructive commands (see `mcp-server/README.md`);
it talks to Claude over **stdio** — no ports, no service.

## 1.3 Create the Claude project

1. In the Claude desktop app (Cowork), create a **new project** and name it e.g. **"Mist Automation"**.
2. **Connect the folder** = your `NAC-Starter` checkout — the WSL path
   `\\wsl$\Ubuntu\home\<username>\NAC-Starter` (Option A) or `C:\Users\<you>\NAC-Starter` (Option B).
3. Paste the **Instructions block** (Appendix A) into the project's custom instructions.
4. Confirm the project's tools: **nac-executor** (from §1.2), the account-level **hpe-networking**
   MCP (`mist_*`), and **Claude-in-Chrome**. For any browser choice, use the **switch_browser connect popup**.

## 1.4 Connect Mist

**Easiest — run the guided wizard:** `python3 setup.py`. It prompts for each value, tells you
where to find it, validates it live, and writes `inventory/credentials.yml`. **Only two values
are required to be operational: the Mist `org_id` and an API token** (ClearPass in Phase 2 is
optional and the wizard skips it unless you opt in).

**Getting the two values from the Mist portal:**

1. **org_id** — left menu → **Organization > Admin > Settings**; the **Organization ID** is
   shown on that page (it is also in the dashboard URL after `/org/`).
2. **API token** — same page (**Organization > Admin > Settings**), scroll to the **API Token**
   section → **Create Token** → pick an **Access Level** (choose a **read-only** level to test
   safely) → **Generate** → click **copy** next to the **Key** (it is shown only once) →
   **Done** → **Save** (top-right of the page).

*Manual alternative:* put the Mist **org_id** and a **scoped API token** in
`inventory/credentials.yml` (gitignored; scaffold in Appendix B). Verify with a read, e.g. list sites/WLANs via `mist_*` (`search` →
`get_schema` → `execute`). Secrets rule: scripts read from `credentials.yml`; never hardcode, print,
or commit — verify a secret's *presence*, not its value.

**Read-only first (recommended).** Create your Mist token at a **read-only Access Level** to
test safely — all of Phase 1's read / audit / reconcile works with it and it *cannot change
anything*. When you're ready to push changes (WLAN / template management), mint a **read-write**
token and re-run `setup.py`. The wizard reports which kind you gave it after it validates.

## 1.5 What Claude does with Mist (the automation surface)

- **Audit & report** — pull org/site/WLAN/RF/device config; produce best-practice audits and drift
  reports; reconcile the repo's intent (`reconcile_inventory.py`) against live Mist.
- **WLAN & template management** — follow the Mist template playbook on every change:
  **golden object → lint → inert deploy → render gate → verify against the consuming object**
  (`manage_mist_wlan.py`, `manage_mist_device_config.py`, `mist_field_validate.py`). Use site/org
  variables; don't hardcode values.
- **Standards** — read and follow `best-practices/`; be an opinionated guardian
  of the reference designs, not just an implementer.

## 1.6 Validate (Phase 1) — acceptance checklist

- [ ] PC executor up; Python deps installed; repo cloned locally.
- [ ] Mist `org_id` + scoped token in `credentials.yml`; a `mist_*` read returns live data.
- [ ] Template changes pass the render gate; verified against the consuming object.
- [ ] `reconcile_inventory.py` clean (repo intent matches live Mist).
- [ ] Changes committed as logical units to git.

---

# PHASE 2 (OPTIONAL) — Claude + Aruba ClearPass NAC

Add this only if you want enterprise NAC (guest onboarding, 802.1X, posture, CoA) beyond Mist's
built-in Access Assurance. ClearPass runs as a VM; Claude integrates via `clearpass_*`.

> **Phase 2 needs the executor on the lab LAN.** For CoA validation the PC acts as a RADIUS NAD
> (binds udp/3799) and ClearPass correlates guest logins by **on-LAN source IP**. So enable **WSL2
> mirrored networking** (or run natively on Windows), and if you use Tailscale, **exit it onsite** —
> its subnet routing will otherwise tunnel your lab traffic and ClearPass will see the wrong source IP.

## 2.1 What you're adding

```
   Mist (cloud) ---- RADIUS 1812/1813 + CoA 3799 ----> ClearPass VM (+Insight)
   AP/WLAN                                              guest WEBAUTH policy + [Juniper Terminate Session]
      ^ NAS/NAD = the Mist AP, ClearPass Vendor = JUNIPER
```

## 2.2 Deploy the ClearPass VM

First, install the Phase 2 script dependencies into the executor venv (in WSL, from the repo root):
`mcp-server/.venv/bin/pip install -r requirements-phase2.txt` (adds pyrad, paramiko, pyVmomi).

1. **Stage the OVA** — human sources the Policy Manager OVA (entitlement download) onto the hypervisor
   datastore.
2. **Register + power on** — on a **free-licensed** hypervisor `ovftool`/`govc`/pyVmomi can't deploy;
   use `scripts/deploy_clearpass_ova.py --ova "<path>" --dry-run` then `--commit --poweron` (SSH +
   `vim-cmd`), or the hypervisor **web client**.
3. **First-boot** (console, GUI-only): passwords, mgmt IP/DNS, hostname, **make it a Publisher**,
   licenses, **NTP**.
4. **Enable Insight** — the session/CoA REST API used for validation depends on it.
5. **Create the REST API client** (GUI-only): **Guest > Administration > API Services > API Clients**
   → Client ID `cowork-lab-automation`, grant **Client Credentials**. Store the secret with
   `scripts/set_clearpass_api_secret.py`.
6. **Snapshot** the VM (`scripts/snapshot_esxi.py`) before policy work.

## 2.3 Connect Claude to ClearPass

Add the `clearpass_api` block to `credentials.yml` (Appendix B). Confirm the `clearpass_*` MCP tools
respond and verify the API client with `backup_clearpass.py --max-events 10` (`status: ok`).

## 2.4 Integrate Mist ↔ ClearPass

- **Mist side** (`mist_*` / `manage_mist_wlan.py`): point the WLAN's RADIUS auth+acct servers at the
  ClearPass IP with a shared secret; **enable CoA / Dynamic Authorization** on the WLAN so Mist accepts
  inbound CoA on udp/3799. Use a site/org variable for the ClearPass IP.
- **Ports:** 1812/1813 (auth/acct) and **3799 (CoA)** open both ways.
- **Message-Authenticator:** modern ClearPass requires it (Blast-RADIUS hardening) — don't disable it.

## 2.5 Guest onboarding + CoA — the Juniper method

1. **Register the Mist AP as a Network Device (NAD):** its NAS IP + shared secret; enable CoA
   (`coa_capable`, `coa_port 3799`); **Vendor = Juniper** (its real vendor — no Cisco).
2. **Guest re-auth is delivered as a Disconnect.** On the guest WEBAUTH enforcement policy's `[Guest]`
   rule, use **`[Juniper Terminate Session]`** (attributes: `Calling-Station-Id`, `Acct-Session-Id`)
   alongside the MAC-caching profile. On successful guest login, ClearPass sends a **Disconnect-Request
   (code 40)** to the AP on udp/3799; the client briefly re-associates and lands in its
   post-registration role.
3. **Wire-proven (lab, 2026-07-05):** NAD **Vendor=Juniper** + `[Juniper Terminate Session]` + a real
   guest self-registration/login produced a **Disconnect-Request (code 40) on udp/3799** from ClearPass.

> **Why Disconnect and not in-place reauthenticate?** ClearPass ships an in-place *Reauthenticate-Session*
> CoA action only for **Cisco** and **Tellabs** vendors; there is no Juniper/HPE/Aruba reauthenticate
> template. To keep the deployment **all-Juniper**, we use the **Disconnect** (Terminate-Session), which
> every Juniper/Mist NAD supports and Mist honors. The only trade-off is a brief client re-associate
> instead of a seamless in-place reauth.

## 2.6 Validate (Phase 2) — prove CoA on the wire

Run from the on-LAN PC executor. **Validate to the observable effect (a packet on udp/3799), not to
doc-conformance.**

- `scripts/coa_bg_listen.py` — creates a synthetic MAC-auth session correlated to the test PC's LAN IP
  and listens on udp/3799; drive the guest portal (register + Log In) from that PC → expect a
  **Disconnect-Request (code 40)**.
- `scripts/clearpass_radius_coa_test.py` — headless RADIUS + accounting harness (note: the
  `/api/session/{id}/disconnect` path returns 400 for a synthetic session regardless of vendor — the
  real guest-portal login is the working trigger).
- **Tailscale note:** exit Tailscale onsite so the login's source IP is your real LAN IP; otherwise
  ClearPass sees a tunneled/subnet-routed address and the correlation fails.

## 2.7 Phase 2 acceptance checklist

- [ ] ClearPass VM deployed, Publisher, licensed, NTP correct, **Insight enabled**.
- [ ] REST API client created; `backup_clearpass.py` returns `status: ok`.
- [ ] Mist AP registered as a NAD, **Vendor = Juniper**, CoA enabled (`coa_port 3799`).
- [ ] Mist WLAN RADIUS → ClearPass; **CoA/Dynamic Authorization enabled** on the WLAN.
- [ ] Guest WEBAUTH policy `[Guest]` rule uses **`[Juniper Terminate Session]`**.
- [ ] Guest login produces a **Disconnect-Request (code 40) on udp/3799**.
- [ ] VM snapshot taken; changes committed.

---

# Reference (both phases)

## Lessons baked in

1. **Guest CoA the Juniper way.** Register the Mist AP as **Vendor=Juniper** and deliver re-auth as a
   **`[Juniper Terminate Session]`** Disconnect — wire-proven (code 40 on udp/3799). ClearPass only
   offers in-place *reauthenticate* for Cisco/Tellabs, so staying all-Juniper means using Disconnect.
2. **Insight is a dependency** for the session/CoA REST API — enable it.
3. **Message-Authenticator is mandatory** (Blast-RADIUS); don't disable it.
4. **Free-licensed hypervisor blocks the write API** — deploy OVAs via `vim-cmd`/web client, not
   ovftool/govc/pyVmomi.
5. **On-LAN source IP matters for CoA validation** — the guest login must reach ClearPass from the real
   LAN IP; WSL2 mirrored networking on, Tailscale off onsite.
6. **appadmin log dump:** `dump logs -t PolicyManagerLogs -w SCP` (space-separated, UPPERCASE `-w SCP`;
   extract with Python `zipfile`).
7. **NTP correctness** underpins RADIUS/cert timing.
8. **Validate to the wire, not the doc.** Reproduced-symptom ≠ root cause; and if a finding implies a
   mature product is broadly broken, suspect your own setup first.

## Automation inventory (`scripts/`)

| Script | Phase | Purpose |
|---|---|---|
| `manage_mist_wlan.py` / `manage_mist_device_config.py` | 1 | Mist WLAN / device config changes. |
| `mist_field_validate.py` | 1 | Validate Mist config fields before write (render gate). |
| `reconcile_inventory.py` / `reconcile_status.py` | 1 | Reconcile repo intent + guard docs against live. |
| `deploy_clearpass_ova.py` | 2 | Register + power on the ClearPass OVA on a free-licensed hypervisor. |
| `set_clearpass_api_secret.py` | 2 | Store the ClearPass API client_secret into credentials.yml. |
| `backup_clearpass.py` | 2 | Export ClearPass config/events via REST (verifies the API client). |
| `coa_bg_listen.py` | 2 | Synthetic session + udp/3799 listener for the guest-portal CoA proof. |
| `clearpass_radius_coa_test.py` / `clearpass_pcap.py` | 2 | RADIUS harness / packet capture. |
| `snapshot_esxi.py` | 2 | VM snapshots for revert-between-iterations. |

## Human-in-the-loop points

- Source the ClearPass OVA (entitlement download) and stage it on the datastore.
- ClearPass first-boot console config + Publisher + licensing; **GUI-only** REST API client creation.
- Enter any secrets (never via the operator/chat).
- **Human Authority** for any production/customer org write, destructive hypervisor op, or repo creation.

## Appendix A — Ready-to-paste project Instructions block

```
ROLE
You are the Network Automation Engineer operating from this PC. You use a LOCAL executor MCP
(run_command / read_file / write_file / git_commit against the local repo; in Phase 2 it also binds
udp/3799 as a RADIUS NAD), the hpe-networking MCP (mist_*, and clearpass_* in Phase 2), and
Claude-in-Chrome. Git (the local clone, backed by GitHub) is the source of truth. No separate utility
server.

PHASE 1 — MIST (primary)
Connect Mist (org_id + scoped token in credentials.yml) and audit/manage/validate it: WLANs, RF,
templates, device config, inventory reconcile. On every Mist change follow the template playbook:
golden object -> lint -> inert deploy -> render gate -> verify against the consuming object. Use
site/org variables; never hardcode. Read and follow best-practices/ and be an
opinionated guardian of the reference designs.

PHASE 2 — CLEARPASS (optional NAC)
Only if asked. Deploy ClearPass (a VM), connect via clearpass_*, and configure guest onboarding + CoA
the JUNIPER way:
- Register the Mist AP as a NAD with Vendor = Juniper (NOT Cisco).
- Deliver guest re-auth as a Disconnect: use [Juniper Terminate Session] on the guest WEBAUTH policy's
  Guest rule. Wire-proven: a guest login yields a Disconnect-Request (code 40) on udp/3799.
- ClearPass offers in-place reauthenticate only for Cisco/Tellabs; staying all-Juniper means Disconnect.
- Enable Insight; keep RADIUS Message-Authenticator on. Free-licensed hypervisor blocks the write API
  (deploy OVAs via vim-cmd / web client). For CoA validation the executor must be on the lab LAN
  (WSL2 mirrored networking; exit Tailscale onsite so ClearPass sees the real LAN source IP).

SECRETS & SAFETY
- Secrets live only in inventory/credentials.yml (gitignored) on this PC. Scripts read them; never
  hardcode, print, or commit. Verify presence, not value.
- Never write a production/customer org, do a destructive hypervisor op, or create a repo without
  explicit Human Authority. For any browser choice use the switch_browser connect popup.

WORKING STYLE (binding)
- Follow best-practices/TENACITY-AND-RESOURCEFULNESS: drive to a validated root
  cause (to the wire, not doc-conformance); find a way rather than pushing work back; hand back only
  for genuine approvals, physical tasks, credentials, or hard blockers. Run continuously.
- Any copy/paste content must be a single clean fenced code block. Commit logical units; keep inventory
  reconciled to live truth.
```

## Appendix B — credentials.yml scaffold (gitignored, on the PC; never commit)

```
# Phase 1 (Mist)
mist:
  mist_api_token:
    api_token: <scoped-mist-token>
    org_id: <mist-org-id>

# Phase 2 (ClearPass) — add only when deploying NAC
esxi:
  esxi_admin:
    username: root
    password: <hypervisor-root-pw>
    govc_url: https://<hypervisor-ip>
    govc_insecure: true
clearpass:
  clearpass_api:
    client_id: cowork-lab-automation
    client_secret: <set via set_clearpass_api_secret.py>
    base_url: https://<clearpass-ip>      # append /api/oauth for tokens
    verify_tls: false
  radius:
    clearpass_host: <clearpass-ip>
    clearpass_shared_secret: <mist<->clearpass shared secret>
```

## Appendix C — Kickoff messages

```
# Phase 1
Read docs/Claude-Mist-ClearPass-Deployment-Guide.md (Phase 1) and the
best-practices/ standards, then stand up the Claude + Mist integration from this PC: connect Mist and
audit/manage/validate it per the template playbook. Git is source of truth.

# Phase 2 (only when adding NAC)
Now execute Phase 2: deploy ClearPass (a VM), connect via clearpass_*, and configure guest onboarding
+ CoA the Juniper way (NAD Vendor=Juniper + [Juniper Terminate Session] Disconnect; validate a
Disconnect-Request code 40 on udp/3799). Hand back only the human-in-the-loop items.
```

---

*Phase 1 = Claude + Mist (cloud, standalone). Phase 2 = optional Claude + ClearPass NAC. Guest CoA uses
the Juniper-native Disconnect (Vendor=Juniper + [Juniper Terminate Session]) — wire-proven 2026-07-05
(Disconnect code 40 on udp/3799); no Cisco. Grounded in the lab automation scripts in the repo.*
