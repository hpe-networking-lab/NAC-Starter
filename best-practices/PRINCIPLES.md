# Mist Best-Practice Principles

The rules every template in this library follows. Anchored on the Juniper Mist
best-practices doc + Wired/Wireless Assurance guides. These are the same checks the
`mist-scope-audit` skill enforces, so a deployment built from this library audits clean.

## Configuration hierarchy
- **Template everything; override nothing unless you must.** Assign templates at **org** or
  **site-group** scope — never at the device level, and never create a bare site-level WLAN.
- Hierarchy is org template > site config > device config; the narrower wins. Keep
  site/device overrides to genuine site-specific values (gateway IP, timezone, country,
  unique VLANs) and push everything else from the template.
- Use **site variables** (`{{var}}`) for per-site values (RADIUS IPs, VLANs) so one template
  serves many sites.

## WLAN
- Organize WLAN templates by **function**: Corporate/Dot1X, Guest, IoT/MPSK, Onboarding.
- **Never VLAN 1** in a production WLAN. Auth-server IPs come from **variables**, not
  hardcoded. **WPA3** preferred (WPA2 for legacy); **never WEP/WPA1**.
- **802.11r** only on WPA2/WPA3-**Enterprise** (it won't function on personal SSIDs).
- Prefer **Cloud PSK / MPSK** over a single static PSK. **Band steering** on for dual/tri-band.
- Open SSID **only** with a captive portal. Scope mDNS to `same_site`/`same_ap`, not `all`.

## RF
- Start with **Mist AI RRM** — do not pin channels or TX power without a documented reason.
- **2.4 GHz: 20 MHz only, channels 1/6/11.** 5 GHz: 40/80 MHz. 6 GHz: 80/160 MHz + PSC.
- One small set of RF templates (baseline + outdoor + high-density) — **not one per site**.
  Separate **indoor vs outdoor**.

## Switch / AP ports
- Manage switches **through Mist, not the CLI**. AP access ports: simple config, PoE on,
  **no port security** unless all WLANs are bridged, native VLAN **not** 1.
- **PoE off** on switch-to-switch uplinks. Don't MAC-match on 802.1X-enabled ports. Provide a
  **restricted profile** for unknown devices on dynamic ports.
- 802.1X **reauth interval 6–12 h** (21600–43200 s) — distinct from accounting interim.

## Site / firmware / PSK
- A **standard site template** sets timezone, country, auto-upgrade, and default RF+WLAN refs
  at new-site creation.
- **Org-level firmware auto-upgrade** with an **off-hours** maintenance window; pilot on a
  site group before fleet-wide; track LSR/SSR.
- PSK/MPSK records carry **expiration** (guests), **VLAN assignment**, and are never reused
  across records.
