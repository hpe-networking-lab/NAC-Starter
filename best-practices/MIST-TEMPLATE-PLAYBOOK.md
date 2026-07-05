# Mist template build & deploy — playbook

**Read this before creating or changing any Mist template (WLAN, switch/network, RF, site).** It is the
ordered, safe path that prevents the two failure classes we keep hitting: (a) a write that "succeeds"
but the config never takes effect, and (b) a schema-valid payload that **crashes the Mist UI** so the
customer can't see it. Follow the steps in order; don't skip the lint or the render gate.

Companion standards (all binding, in this folder): `VALIDATION.md` (verify against the consuming
object), `RENDER-CHECK.md` (render smoke-test runbook), `REVIEW-POSTURE.md` (defend the reference
architecture). Scripts: `scripts/mist_template_lint.py`, `scripts/list_template_urls.py`.

---

## 0. Golden rules (non-negotiable)
- **Never write a customer org without Human Authority approval.** Customer access is read-only until
  approved. Never use the lab connector against a customer org.
- **Inert first.** New WLANs `enabled:false`; templates unassigned (no site bindings). Activate only on
  HA approval, **site-by-site, with a tested revert path**.
- **Record every created object (name + id)** for a clean revert, in `engagement/deploy/`.
- **Secrets out-of-band only** — RADIUS/ISE secret, OSPF key, SNMPv3, Wi-Fi PSKs, claim codes never go
  in chat or git. Verify **presence, never value**.
- **Check org alarms before and after** any write; expect **0 new alarms**.
- Copy/paste you hand the operator = a **single clean fenced code block**.

## 1. Build — start from a "golden" object, never sparse hand-authored JSON
The root cause of UI-render crashes is minimal API payloads that omit sub-objects the UI later assumes
exist. Avoid the whole class:
1. Create one object of each kind **in the Mist UI** (or **clone** a known-good template), then `GET` it.
2. Use that as the canonical payload; swap concrete values for `{{variables}}`.
3. The UI-made object carries every sub-structure it will render (`dynamic_vlan.vlans`, ratesets, portal
   bodies, `port_usages`, `networks`) — your API object inherits the complete shape.

Design intent lives in the engagement `DESIGN.md`; the payloads are variable-driven and reusable.

## 2. Pre-deploy lint — catch what schemas can't
Run **both** checks on every payload and fix all ERRORs before writing:
```
python3 best-practices/scripts/mist_template_lint.py payload.json \
    --openapi /lab/openapi/mist_openapi/mist.openapi.json
```
It runs OpenAPI field-validation (unknown + deprecated fields) **and** flag-implies-sibling consistency
rules. Known rules (grow the table in VALIDATION.md when you find a new one):

| If … | Require … | Else the failure is |
|---|---|---|
| `wlan.dynamic_vlan.enabled` | non-empty `vlans` **or** `default_vlan_ids` | UI `Object.keys(undefined)` → **template page crash** |
| `wlan.dynamic_psk.enabled` | `wlan.auth_servers` | dynamic PSK is RADIUS-sourced → invalid |
| `wlan.auth.type == eap` | `wlan.auth_servers` | 802.1X with no RADIUS server |
| `wlan.portal.enabled` | a portal body | empty portal editor faults |
| any field | not `deprecated` in OpenAPI | UI may read only the successor field |

**Field gotchas confirmed the hard way (check these explicitly):**
- `coa_servers[]` uses **`ip`**, not `host` (auth/acct servers use `host`). Wrong key → CoA silently
  non-functional.
- Site **variables** live on the **Site Setting** object `/sites/{id}/setting` `vars`, **not** the Site
  object — the Site object accepts them silently and the UI shows 0 variables.
- `dynamic_vlan.default_vlan_id` is **deprecated** → use `default_vlan_ids` (array).
- Maps (`vars`, `port_usages`, `networks`) validate on **values**, not their arbitrary keys.

## 3. Deploy inert
- WLANs `enabled:false`; do not bind templates to sites.
- Capture org alarms first, POST/PUT, capture alarms again → expect **0 → 0**.
- Write the revert manifest (object names + ids, placeholder notes) to `engagement/deploy/`.

## 4. Render gate — a template isn't "done" until its page renders
The definitive catch, and cheap. Verify in the **actual consumer** (the UI), not just read-back:
1. `scripts/list_template_urls.py --org <id> --base <api> --token-file <f>` lists every template's page.
2. For each: open it in the Mist UI (Claude-in-Chrome MCP `navigate`), click the row, then
   `read_console_messages{onlyErrors:true}`.
3. Clean pass = **no** `TypeError` / `Cannot convert undefined or null to object` / "unexpected error".
   On a hit, the JS stack names the renderer + field — fix **that** field, don't guess. `ctrl+r` between
   fixes so cached JS state doesn't mask a change.
- For a **render** bug, stop inferring from the payload after the first miss — reproduce in the browser
  and read the error. Schema validation can't see a renderer assuming a sub-object exists.
- Route note: deep hashes are unreliable (plural `#!switchTemplates` shows a permissions page). Reach
  switch/site pages from the **Organization** menu; the helper emits the forms that work.

## 5. Verify against the consuming object
Read back from the object the system actually uses (Site Setting for vars; the WLAN the UI renders),
not the same field you wrote. A write succeeding proves nothing; a read of your own echo is a false
positive. Hardware-only items (variable substitution on a live device, LACP/STP/native VLAN) are
**deferred to bring-up** — flag them, don't mark done.

## 6. Activate (only on HA approval)
Site-by-site, in a maintenance window, with the revert manifest ready. Enable WLANs / bind templates one
site at a time; re-run the render gate and alarm check after each.

---

### Pre-flight checklist (copy into the engagement deploy record)
- [ ] Payloads built from a UI-golden/cloned object (not sparse hand-authored JSON).
- [ ] `mist_template_lint.py` passes — 0 ERRORs (no flag-without-sibling, no deprecated/unknown fields).
- [ ] `coa_servers.ip`, Site-Setting `vars`, `default_vlan_ids` verified.
- [ ] Deployed inert (WLANs disabled, templates unassigned); alarms 0 → 0; revert manifest written.
- [ ] Render gate: every affected template page opens with a clean console.
- [ ] Read-back verified against the consuming object; hardware-only checks deferred to bring-up.
- [ ] Secrets out-of-band; no secrets in chat or git.
- [ ] Activation only on HA approval, site-by-site, revert path ready.
