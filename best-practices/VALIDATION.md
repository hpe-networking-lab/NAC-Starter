# Payload Validation — Reconciled Against Live Mist API

Templates are validated, not guessed. The Mist API JSON skeletons in this library are
reconciled against **real, working objects** read (read-only) from a live Mist org
(`example_Lab`) via the HPE-networking connector.

- **Date:** 2026-07-02
- **Method:** read live `wlans`, `templates`, `rftemplates`, `networktemplates` and compared
  field sets to each skeleton. Read-only — nothing written to any org.

## Corrections applied this pass
- **CoA (corp-dot1x):** `coa_server{enabled,port}` → real fields **`coa_enabled`** +
  **`coa_port`**.
- **MPSK (iot-mpsk):** `multi_psk_only` → real field **`dynamic_psk{enabled}`** (with
  `auth.type: "psk"`).
- **RF template:** removed `country_code` — that's a **site/site-template** field, not an
  `rftemplate` field. (2.4 GHz enable/disable is `band_24_usage`.)

## Confirmed correct
- WLAN: `auth`, `auth_servers`/`acct_servers`, `vlan_enabled`/`vlan_id`/`dynamic_vlan`,
  `band_steer`, `arp_filter`, `limit_bcast`, `isolation`, `enable_mac_auth`, `mist_nac`,
  `portal`, `hide_ssid`.
- Switch/network template: `port_usages`, `networks`, `radius_config`, `dns_servers`,
  `ntp_servers`, `switch_mgmt` — all real top-level fields.
- RF template: `band_24`/`band_5`/`band_6`, `band_24_usage`, `ant_gain_*`, `model_specific`.

## Standing rule
Before applying any template to an org, confirm exact field-level shape against a live object
or `get_schema` for that endpoint — Mist adds fields over releases. Skeletons here are
validated design references, not release-pinned payloads.

## Live apply → verify → teardown proof (2026-07-02)

Beyond field reconciliation, the `corp-dot1x` payload was **created against the live Mist API**
in the `example_Lab` org and accepted end-to-end:

- Created an unassigned WLAN template + a **disabled** WLAN from the corp-dot1x skeleton.
- Mist **accepted and stored** every field — including the corrected `coa_enabled` / `coa_port`,
  plus `dynamic_vlan`, `vlan_id`, `band_steer`. No validation error.
- **Deleted** the WLAN and template; re-listed and confirmed **nothing left behind**.

Write path (lab only): `mist_invoke_tool(<create_tool>, {"org_id": ..., "body": {...}})` — the
payload is nested under `body`; there is no `authorize` param (writes are enabled at the
connector). All non-lab orgs (e.g. customer orgs) remain **read-only**. Test objects use a
`ZZ_..._DELETE_ME` name and are always torn down.

---

## Verifying config writes — a write succeeding proves nothing (2026-07-03)

Engineering Office standard, formalized from the Love Field operate chat (also belongs in
ACEM `docs/standards`). **Verify against the object the platform actually *consumes* — not the
field you just wrote.** APIs (Mist included) accept unknown/misplaced fields without error;
reading the same field back only confirms your input echoed, not that the platform will act on it.

**Failure mode:** PUT returns 200 and echoes your fields → a field is on the wrong object or has
the wrong name → the platform silently ignores it → read-back of that same field looks fine (false
positive) → the defect hides until a device / the UI / variable substitution fails to resolve,
usually at bring-up (the worst time to find it).

**Verification layers (do all that apply, in order):**
1. **Docs/spec first** — confirm the correct object + field name in the API reference
   (`api.<cloud>.mist.com/api/v1/docs`) or OpenAPI (`github.com/mistsys/mist_openapi`) BEFORE
   writing. Don't infer field names.
2. **Per-object read-back** — necessary, not sufficient.
3. **Authoritative consumer** — verify against what the platform reads: the derived/effective
   config, the downstream object, or the UI panel — never the object you wrote to. (Mist site
   variables live on the *Site Setting* object and render in the Site Variables UI panel, not the
   Site object.)
4. **Schema field-validation** — validate EVERY field of EVERY payload against the object's
   OpenAPI schema. This is the layer that catches the silently-accepted / wrong-field class across
   all parameters. Recurse `$ref`/`allOf`; maps (`vars`, `port_usages`, `networks`) use
   `additionalProperties` (validate values, not the arbitrary keys); sanity-check a known-good
   field (`wlan.ssid`) passes so you don't get a false "everything unknown".
5. **Bring-up checks** — some things only hardware confirms (variable substitution on a live
   device, LACP/STP/native-VLAN interop). Flag explicitly; don't mark "done" early.

**Worked examples (both missed by read-back alone):**
- `site.vars` written to the *Site* object; Mist uses the *Site Setting* `vars` for `{{}}`
  substitution. Read-back echoed; the UI Site Variables panel showed 0. Fix: `/sites/{id}/setting`.
- `coa_servers[].host` — the schema field is `ip`. Mist stored junk `host` and resolved CoA off the
  empty `ip` → silently non-functional; read-back "looked" populated. Found only by schema
  field-validation.

**Secrets:** shared secrets (RADIUS/ISE secret, Wi-Fi PSK, tokens) are set out-of-band by the
Human Authority / customer — never written from a chat or committed. Verify **presence only,
never value**.

**Pre-bring-up checklist:**
- [ ] Every written field schema-validated against OpenAPI — zero unknowns.
- [ ] Scoping/inheritance confirmed via derived/effective config, not echo.
- [ ] Variable placement confirmed on the consuming object (Site Setting) + UI panel.
- [ ] Out-of-band secrets (RADIUS secret, PSKs) listed as customer tasks; presence to be verified.
- [ ] Hardware-only checks (variable substitution, LACP/STP/native VLAN) explicitly deferred to
      bring-up, not marked done.

---

## Consumer-render safety (prevent template UI crashes)

A payload can be **100% schema-valid field-by-field and still crash the consumer.** The Mist API
accepts a minimal, valid object, but the UI renderer assumes a **sub-object exists whenever a sibling
flag is set** — an assumption no schema encodes. Field-level OpenAPI validation (above) is necessary
but **cannot** catch this class. Three layers close it:

### 1. Build from a UI-created "golden" object — not hand-authored minimal JSON
The root cause of this whole class is sparse API payloads. Create one object of each kind (WLAN,
network/switch template, site template, RF template) **in the Mist UI**, `GET` it, and use that as the
canonical payload — then swap in `{{variables}}`. The UI populates every sub-structure it will later
try to render (`dynamic_vlan.vlans`, ratesets, portal bodies, `port_usages`, …), so API-built objects
inherit the **complete** shape instead of an invented sparse one. Cloning a known-good template gives
the same guarantee. Prefer this over authoring payloads from the schema alone.

### 2. Render smoke-test gate — a template isn't "done" until its page renders
The definitive catch, and cheap. After ANY template write, open each affected template page in the real
Mist UI and confirm a **clean console** — no `TypeError`, no "An unexpected error occurred." Run it via
the Claude-in-Chrome MCP: `navigate` to the page, `read_console_messages{onlyErrors:true}` for the JS
stack, `read_network_requests` for the failing call. The stack names the exact renderer and field. See
`best-practices/scripts/RENDER-CHECK.md` for the runbook and page-URL patterns. **Gate rule: no
template is marked done, and no template is activated, until its page renders with a clean console.**

### 3. Consistency lint — flag ⇒ required sibling (pre-deploy, automatable)
Encode the "if this flag is on, that sibling object must be present/non-empty" rules that schemas can't.
Run `best-practices/scripts/mist_template_lint.py` on every payload before deploy. Current rule set
(grow it every time a new case is found):

| If … | Then require … | Else |
|---|---|---|
| `wlan.dynamic_vlan.enabled` | non-empty `dynamic_vlan.vlans` **or** `default_vlan_ids` | UI `Object.keys(undefined)` → template page crash |
| `wlan.dynamic_psk.enabled` | `wlan.auth_servers` present | dynamic PSK is RADIUS-sourced; invalid without it |
| `wlan.auth.type == eap` | `wlan.auth_servers` present | 802.1X with no RADIUS server |
| `wlan.portal.enabled` | a portal body (`auth`/`expire`/…) | empty portal editor may fault |
| any field | not `deprecated` in OpenAPI | successor field may be the only one the UI reads |

**Worked example (example, 2026-07-04):** WLAN-template page threw
`TypeError: Cannot convert undefined or null to object` at `Object.keys()` in the WLAN-table row
renderer. Cause: `dynamic_vlan.enabled=true` with no `vlans` map; the VLAN column keys over
`dynamic_vlan.vlans` only when enabled. Two schema-valid API-only fixes missed it; **reproducing in the
browser named the field in one read.** Lesson: for a *render* failure, stop inferring from the payload
after the first miss — reproduce in the actual consumer and read its error.

**Added to the pre-bring-up checklist:**
- [ ] Payloads built from a UI-golden/cloned object (not sparse hand-authored JSON).
- [ ] `mist_template_lint.py` passes — no flag-without-required-sibling, no deprecated fields.
- [ ] Render smoke-test: every affected template page opens with a clean console (no TypeError).
