# Audit Alignment — Templates ↔ `mist-scope-audit` checks

This library and the `mist-scope-audit` skill share one best-practice source, so a deployment
built from these templates **audits clean**. This maps each template to the specific audit
findings it prevents (REGRESSION = must-fix, DRIFT = should-fix).

## Templating discipline (all templates)
Prevents: **bare site-level WLAN** (REGRESSION), **device-level config overrides**
(REGRESSION), **per-site assignment that should be site-group** (DRIFT), **monolithic
template** (DRIFT), **hardcoded value in a VAR-labeled field** (DRIFT).
→ Because every block is org/site-group-scoped, function-split, and variable-driven.

## `templates/wlan/corp-dot1x.md`
Prevents: **hardcoded RADIUS IPs** (uses `{{auth_srv1/2}}`), **VLAN 1 in production**,
**WEP/WPA1** (WPA3/2-Enterprise), **band steering disabled** — all REGRESSION/DRIFT. 11r is
valid here (Enterprise), avoiding the **11r-on-personal** REGRESSION.

## `templates/wlan/guest.md`
Prevents: **open SSID without captive portal** (REGRESSION), **broadcast limit disabled on
guest** (DRIFT), missing isolation/ARP controls.

## `templates/wlan/iot-mpsk.md`
Prevents: **static shared PSK where MPSK fits** (DRIFT), **11r on non-Enterprise SSID**
(REGRESSION — kept off), **ARP filter disabled on IoT** (DRIFT), **PSK without VLAN** (DRIFT).

## `templates/rf/rf-templates.md`
Prevents: **channel width > 20 MHz on 2.4 GHz** (REGRESSION), **2.4 GHz channels other than
1/6/11** (REGRESSION), **fixed TX power** / **fixed channels on 5/6 GHz** (DRIFT — AI RRM
manages), **RF template proliferation** (DRIFT), **no org/site-group baseline RF template**
(DRIFT), **same template indoor+outdoor** (DRIFT).

## `templates/switch/switch-and-ap-ports.md`
Prevents: **switch managed via CLI** (REGRESSION), **port security on AP ports** (REGRESSION),
**MAC-based match on 802.1X port** (REGRESSION), **PoE on switch-to-switch uplink** (DRIFT),
**VLAN 1 as native** (DRIFT), **802.1X reauth outside 6–12 h** (DRIFT), **no restricted
profile for unknown devices** (DRIFT).

## `templates/site/standard-site-template.md`
Prevents: **no site templates** (DRIFT), **site template missing timezone/country code**
(DRIFT), inconsistent new-site baseline.

## `templates/ops/firmware-and-psk.md`
Prevents: **no org firmware auto-upgrade** (REGRESSION), **maintenance window during business
hours** (DRIFT), **no pilot site group** (DRIFT), **guest PSK with no expiration** (DRIFT),
**PSK without VLAN** (DRIFT), **reused PSK passphrase** (DRIFT).

## How to use
After applying templates to an org, run `mist-scope-audit` scoped to that org/site. A clean
result confirms the deployment matches this library. Any finding points back to the template
row above.
