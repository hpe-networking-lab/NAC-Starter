#!/usr/bin/env python3
"""
backup_clearpass.py - Read-only Aruba ClearPass inventory/policy export.

Exports server status, RADIUS/cluster service status, recent system events,
active sessions, endpoints, network devices, and policy configuration
(services, enforcement policies/profiles, role mappings, roles, auth
sources/methods, certificate trust list, onboarded devices) from the
ClearPass Policy Manager REST API to JSON files for Git-based lab
versioning.

READ-ONLY: only issues GET requests (plus an OAuth2 token request). No
configuration changes are made. No policy/endpoint write or delete tools
are implemented here (per project Phase 2/6 safety requirements).

Credentials resolution order:
  1. inventory/credentials.yml (gitignored) -> clearpass.clearpass_api:
       client_id, client_secret, base_url, verify_tls (optional, default false)
  2. Environment variables:
       CLEARPASS_CLIENT_ID, CLEARPASS_CLIENT_SECRET, CLEARPASS_BASE_URL,
       CLEARPASS_VERIFY_TLS (1/true to enable TLS verification)

The API client must be created once, manually, in the ClearPass GUI:
  Guest > Administration > API Services > API Clients
    Client ID:         lab-automation-ro
    Operating Profile: Read-only Administrator
    Grant Type:        Client Credentials
    Client Secret:     (see inventory/credentials.yml)

The client secret is never written to logs or export files.

Usage:
  python3 backup_clearpass.py
  python3 backup_clearpass.py --dry-run
  python3 backup_clearpass.py --max-events 50 --max-items 500

Output:
  exports/clearpass/<timestamp>/server_status.json
  exports/clearpass/<timestamp>/system_events.json
  exports/clearpass/<timestamp>/sessions.json
  exports/clearpass/<timestamp>/endpoints.json
  exports/clearpass/<timestamp>/network_devices.json
  exports/clearpass/<timestamp>/device_groups.json
  exports/clearpass/<timestamp>/onboard_devices.json
  exports/clearpass/<timestamp>/policy_services.json
  exports/clearpass/<timestamp>/enforcement_policies.json
  exports/clearpass/<timestamp>/enforcement_profiles.json
  exports/clearpass/<timestamp>/role_mappings.json
  exports/clearpass/<timestamp>/roles.json
  exports/clearpass/<timestamp>/auth_sources.json
  exports/clearpass/<timestamp>/auth_methods.json
  exports/clearpass/<timestamp>/cert_trust_list.json
  exports/clearpass/latest -> <timestamp>  (symlink, best-effort)

Always exits 0; failures are reported per-section in the JSON summary on
stdout so this script can be used inside create_milestone.sh without
aborting the milestone.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required (pip3 install --break-system-packages pyyaml)", file=sys.stderr)
    sys.exit(1)

try:
    import requests
    from urllib3.exceptions import InsecureRequestWarning
    import urllib3
except ImportError:
    requests = None

LAB_ROOT = Path(os.environ.get("LAB_ROOT", "/lab"))
REPO_ROOT = LAB_ROOT / "lab-version-control"
CREDENTIALS_FILE = REPO_ROOT / "inventory" / "credentials.yml"
EXPORTS_ROOT = REPO_ROOT / "exports" / "clearpass"

# Simple GET-only sections: name -> (path, params)
SIMPLE_SECTIONS = {
    "endpoints": ("/api/endpoint", {"limit": "{max_items}"}),
    "network_devices": ("/api/network-device", {"limit": "{max_items}"}),
    "device_groups": ("/api/network-device-group", {"limit": "{max_items}"}),
    "onboard_devices": ("/api/onboard/device", {"limit": "{max_items}"}),
    "policy_services": ("/api/config/service", {"limit": "{max_items}"}),
    "enforcement_policies": ("/api/enforcement-policy", {"limit": "{max_items}"}),
    "enforcement_profiles": ("/api/enforcement-profile", {"limit": "{max_items}"}),
    "role_mappings": ("/api/role-mapping", {"limit": "{max_items}"}),
    "roles": ("/api/role", {"limit": "{max_items}"}),
    "auth_sources": ("/api/auth-source", {"limit": "{max_items}"}),
    "auth_methods": ("/api/auth-method", {"limit": "{max_items}"}),
    "cert_trust_list": ("/api/cert-trust-list", {"limit": "{max_items}"}),
}


def load_credentials_file():
    if not CREDENTIALS_FILE.exists():
        return {}
    with open(CREDENTIALS_FILE) as f:
        return yaml.safe_load(f) or {}


def resolve_credentials(creds_file):
    cp_creds = (creds_file or {}).get("clearpass", {})
    entry = cp_creds.get("clearpass_api")

    if entry and entry.get("client_id") and entry.get("client_secret") not in (None, "REPLACE_ME") \
            and entry.get("client_id") != "REPLACE_ME":
        return {
            "client_id": entry.get("client_id"),
            "client_secret": entry.get("client_secret"),
            "base_url": entry.get("base_url", "").rstrip("/"),
            "verify_tls": bool(entry.get("verify_tls", False)),
        }

    client_id = os.environ.get("CLEARPASS_CLIENT_ID")
    client_secret = os.environ.get("CLEARPASS_CLIENT_SECRET")
    base_url = os.environ.get("CLEARPASS_BASE_URL", "").rstrip("/")
    verify_tls = os.environ.get("CLEARPASS_VERIFY_TLS", "").lower() in ("1", "true", "yes")
    if client_id and client_secret and base_url:
        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "base_url": base_url,
            "verify_tls": verify_tls,
        }

    return None


def get_token(creds):
    url = f"{creds['base_url']}/api/oauth"
    resp = requests.post(
        url,
        json={
            "grant_type": "client_credentials",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        },
        verify=creds["verify_tls"],
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def api_get(creds, token, path, params=None):
    url = f"{creds['base_url']}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params=params, verify=creds["verify_tls"], timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without calling the API")
    parser.add_argument("--max-events", type=int, default=50, help="Number of recent system events to fetch")
    parser.add_argument("--max-items", type=int, default=200, help="Page size for list endpoints")
    args = parser.parse_args()

    creds_file = load_credentials_file()
    creds = resolve_credentials(creds_file)

    summary = {
        "script": "backup_clearpass.py",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "skipped",
        "reason": None,
        "export_dir": None,
    }

    if not creds:
        summary["reason"] = (
            "no credentials resolved (set inventory/credentials.yml clearpass.clearpass_api, "
            "or CLEARPASS_CLIENT_ID/CLEARPASS_CLIENT_SECRET/CLEARPASS_BASE_URL env vars)"
        )
        print(json.dumps(summary, indent=2))
        return

    if args.dry_run:
        summary["status"] = "dry-run"
        summary["reason"] = f"would query {creds['base_url']} as client {creds['client_id']}"
        print(json.dumps(summary, indent=2))
        return

    if requests is None:
        summary["status"] = "error"
        summary["reason"] = "requests not installed (pip3 install --break-system-packages requests)"
        print(json.dumps(summary, indent=2))
        return

    if not creds["verify_tls"]:
        urllib3.disable_warnings(InsecureRequestWarning)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = EXPORTS_ROOT / timestamp

    try:
        token = get_token(creds)
    except Exception as exc:  # noqa: BLE001
        summary["status"] = "error"
        summary["reason"] = f"OAuth2 token request failed: {exc}"
        print(json.dumps(summary, indent=2))
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    section_results = {}

    # server_status: version + cluster + per-server service status
    try:
        version = api_get(creds, token, "/api/server/version")
        cluster = api_get(creds, token, "/api/cluster/server")
        server_status = {"version": version, "cluster": cluster, "services": {}}
        for srv in cluster.get("_embedded", {}).get("items", []):
            uuid = srv.get("server_uuid")
            name = srv.get("name", uuid)
            try:
                server_status["services"][name] = api_get(
                    creds, token, f"/api/server/service/{uuid}"
                )
            except Exception as exc:  # noqa: BLE001
                server_status["services"][name] = f"error: {exc}"
        (out_dir / "server_status.json").write_text(json.dumps(server_status, indent=2))
        section_results["server_status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        section_results["server_status"] = f"error: {exc}"

    # system_events (recent, used as the auth/system event feed)
    try:
        events = api_get(
            creds, token, "/api/system-event",
            params={"sort": "-timestamp", "limit": args.max_events},
        )
        (out_dir / "system_events.json").write_text(json.dumps(events, indent=2))
        section_results["system_events"] = "ok"
    except Exception as exc:  # noqa: BLE001
        section_results["system_events"] = f"error: {exc}"

    # active sessions (requires Insight enabled on at least one cluster node;
    # reported as "skipped" rather than "error" if Insight is not enabled)
    try:
        sessions = api_get(
            creds, token, "/api/session",
            params={"limit": args.max_items},
        )
        (out_dir / "sessions.json").write_text(json.dumps(sessions, indent=2))
        section_results["sessions"] = "ok"
    except Exception as exc:  # noqa: BLE001
        body = getattr(getattr(exc, "response", None), "text", "") or ""
        if "Insight" in str(exc) or "Insight" in body:
            section_results["sessions"] = "skipped: Insight not enabled on this ClearPass cluster"
        else:
            section_results["sessions"] = f"error: {exc}"

    # remaining simple GET sections
    for name, (path, param_template) in SIMPLE_SECTIONS.items():
        try:
            params = {k: (v.format(max_items=args.max_items) if isinstance(v, str) else v)
                      for k, v in (param_template or {}).items()}
            data = api_get(creds, token, path, params=params)
            (out_dir / f"{name}.json").write_text(json.dumps(data, indent=2))
            section_results[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            section_results[name] = f"error: {exc}"

    latest_link = EXPORTS_ROOT / "latest"
    try:
        if latest_link.exists() or latest_link.is_symlink():
            latest_link.unlink()
        latest_link.symlink_to(timestamp)
    except OSError:
        pass

    overall_ok = all(v == "ok" or v.startswith("skipped") for v in section_results.values())
    summary["status"] = "ok" if overall_ok else "partial"
    summary["export_dir"] = str(out_dir.relative_to(REPO_ROOT))
    summary["base_url"] = creds["base_url"]
    summary["sections"] = section_results
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
