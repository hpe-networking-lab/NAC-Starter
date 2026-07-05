#!/usr/bin/env python3
"""
manage_mist_wlan.py - Controlled Mist WLAN configuration management
(Phase 3 / Priority 4 "Configuration write tools deferred to later phase").

Subcommands:
  - list-wlans  --site <site_id>                 : list WLANs (read-only)
  - get-wlan    --site <site_id> --wlan-id <id>  : show one WLAN's config (read-only)
  - create-wlan --site <site_id> --file <json>   : create a new WLAN
  - update-wlan --site <site_id> --wlan-id <id> --file <json>
                                                  : update an existing WLAN
  - delete-wlan --site <site_id> --wlan-id <id>  : delete a WLAN

SAFETY (per MCP project spec, Priority 4 "Safety requirements" +
Phase 3 "Mist WLAN changes ... only after read-only MCPs are stable"):
  - create-wlan and update-wlan require the literal flag --yes-i-am-sure.
    Without it, the script refuses and takes no action.
  - delete-wlan additionally requires a second distinct flag,
    --confirm-delete, mirroring the ESXi revert-snapshot double-confirmation
    pattern, since deleting a WLAN is destructive and not reversible via
    this tool.
  - All invocations (including refused ones) are appended to
    /lab/logs/mist_changes.log with timestamp, site, subcommand, and outcome.
  - The Mist API token is never printed or logged.
  - Credentials resolution is identical to backup_mist.py
    (inventory/credentials.yml mist.mist_api_token, or
    MIST_API_TOKEN/MIST_ORG_ID/MIST_API_BASE env vars).

WLAN config files (--file) are plain JSON matching the Mist WLAN object
schema (see https://api.mist.com/api/v1/docs/ -> Site WLANs). Store
candidate files under scripts/candidates/mist/<site_name>/.

Usage examples:
  # Read-only
  python3 manage_mist_wlan.py list-wlans --site YOUR_SITE_ID
  python3 manage_mist_wlan.py get-wlan --site YOUR_SITE_ID \\
      --wlan-id <wlan_id>

  # Create a new WLAN from a candidate JSON file
  python3 manage_mist_wlan.py create-wlan \\
      --site YOUR_SITE_ID \\
      --file candidates/mist/lab/example_wlan.json --yes-i-am-sure

  # Update an existing WLAN
  python3 manage_mist_wlan.py update-wlan \\
      --site YOUR_SITE_ID --wlan-id <wlan_id> \\
      --file candidates/mist/lab/example_wlan.json --yes-i-am-sure

  # Delete a WLAN (double confirmation required)
  python3 manage_mist_wlan.py delete-wlan \\
      --site YOUR_SITE_ID --wlan-id <wlan_id> \\
      --yes-i-am-sure --confirm-delete

Always exits 0; result is reported as JSON on stdout (status: ok / error / refused).
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
except ImportError:
    requests = None

LAB_ROOT = Path(os.environ.get("LAB_ROOT", "/lab"))
REPO_ROOT = LAB_ROOT / "lab-version-control"
CREDENTIALS_FILE = REPO_ROOT / "inventory" / "credentials.yml"
CANDIDATES_ROOT = LAB_ROOT / "scripts" / "candidates" / "mist"
LOG_FILE = LAB_ROOT / "logs" / "mist_changes.log"

DEFAULT_API_BASE = "https://api.mist.com/api/v1"

CONFIRM_FLAG = "--yes-i-am-sure"
DELETE_CONFIRM_FLAG = "--confirm-delete"


def log_action(record: dict):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = dict(record)
    record["logged_at"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def load_credentials_file():
    if not CREDENTIALS_FILE.exists():
        return {}
    with open(CREDENTIALS_FILE) as f:
        return yaml.safe_load(f) or {}


def resolve_credentials(creds_file):
    mist_creds = (creds_file or {}).get("mist", {})
    entry = mist_creds.get("mist_api_token")

    if entry and entry.get("api_token") and entry.get("api_token") != "REPLACE_ME":
        return {
            "api_token": entry.get("api_token"),
            "org_id": entry.get("org_id"),
            "api_base": entry.get("api_base", DEFAULT_API_BASE),
        }

    token = os.environ.get("MIST_API_TOKEN")
    org_id = os.environ.get("MIST_ORG_ID")
    api_base = os.environ.get("MIST_API_BASE", DEFAULT_API_BASE)
    if token and org_id:
        return {"api_token": token, "org_id": org_id, "api_base": api_base}

    return None


def api_request(method, api_base, token, path, json_body=None):
    url = f"{api_base}{path}"
    headers = {"Authorization": f"Token {token}"}
    resp = requests.request(method, url, headers=headers, json=json_body, timeout=30)
    resp.raise_for_status()
    if resp.text:
        return resp.json()
    return None


def read_wlan_file(file_arg):
    path = Path(file_arg)
    if not path.is_absolute():
        candidate = LAB_ROOT / "scripts" / file_arg
        if candidate.exists():
            path = candidate
        else:
            alt = CANDIDATES_ROOT / file_arg
            if alt.exists():
                path = alt
            else:
                path = candidate
    if not path.exists():
        raise FileNotFoundError(f"WLAN config file not found: {file_arg}")
    with open(path) as f:
        return path, json.load(f)


def get_creds_or_raise():
    creds_file = load_credentials_file()
    creds = resolve_credentials(creds_file)
    if not creds:
        raise ValueError(
            "no credentials resolved (set inventory/credentials.yml mist.mist_api_token, "
            "or MIST_API_TOKEN/MIST_ORG_ID env vars)"
        )
    if requests is None:
        raise ValueError("requests not installed (pip3 install --break-system-packages requests)")
    return creds


def cmd_list_wlans(args):
    result = {"command": "list-wlans", "site": args.site}
    try:
        creds = get_creds_or_raise()
        data = api_request("GET", creds["api_base"], creds["api_token"], f"/sites/{args.site}/wlans")
        result["status"] = "ok"
        result["wlans"] = [
            {"id": w.get("id"), "ssid": w.get("ssid"), "enabled": w.get("enabled")} for w in (data or [])
        ]
        result["count"] = len(result["wlans"])
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["reason"] = str(exc)
    return result


def cmd_get_wlan(args):
    result = {"command": "get-wlan", "site": args.site, "wlan_id": args.wlan_id}
    try:
        creds = get_creds_or_raise()
        data = api_request(
            "GET", creds["api_base"], creds["api_token"], f"/sites/{args.site}/wlans/{args.wlan_id}"
        )
        result["status"] = "ok"
        result["wlan"] = data
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["reason"] = str(exc)
    return result


def cmd_create_wlan(args):
    result = {"command": "create-wlan", "site": args.site, "file": args.file}
    if not args.yes_i_am_sure:
        result["status"] = "refused"
        result["reason"] = f"missing {CONFIRM_FLAG} - no action taken"
        log_action(result)
        return result
    try:
        creds = get_creds_or_raise()
        path, body = read_wlan_file(args.file)
        result["file_resolved"] = str(path)
        data = api_request("POST", creds["api_base"], creds["api_token"], f"/sites/{args.site}/wlans", json_body=body)
        result["status"] = "ok"
        result["wlan_id"] = (data or {}).get("id")
        result["ssid"] = (data or {}).get("ssid")
        result["note"] = "WLAN created"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["reason"] = str(exc)
    log_action(result)
    return result


def cmd_update_wlan(args):
    result = {"command": "update-wlan", "site": args.site, "wlan_id": args.wlan_id, "file": args.file}
    if not args.yes_i_am_sure:
        result["status"] = "refused"
        result["reason"] = f"missing {CONFIRM_FLAG} - no action taken"
        log_action(result)
        return result
    try:
        creds = get_creds_or_raise()
        path, body = read_wlan_file(args.file)
        result["file_resolved"] = str(path)
        data = api_request(
            "PUT",
            creds["api_base"],
            creds["api_token"],
            f"/sites/{args.site}/wlans/{args.wlan_id}",
            json_body=body,
        )
        result["status"] = "ok"
        result["wlan_id"] = (data or {}).get("id", args.wlan_id)
        result["ssid"] = (data or {}).get("ssid")
        result["note"] = "WLAN updated"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["reason"] = str(exc)
    log_action(result)
    return result


def cmd_delete_wlan(args):
    result = {"command": "delete-wlan", "site": args.site, "wlan_id": args.wlan_id}
    if not args.yes_i_am_sure or not args.confirm_delete:
        result["status"] = "refused"
        missing = []
        if not args.yes_i_am_sure:
            missing.append(CONFIRM_FLAG)
        if not args.confirm_delete:
            missing.append(DELETE_CONFIRM_FLAG)
        result["reason"] = f"missing {', '.join(missing)} - no action taken"
        log_action(result)
        return result
    try:
        creds = get_creds_or_raise()
        api_request("DELETE", creds["api_base"], creds["api_token"], f"/sites/{args.site}/wlans/{args.wlan_id}")
        result["status"] = "ok"
        result["note"] = f"WLAN '{args.wlan_id}' deleted from site '{args.site}'"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["reason"] = str(exc)
    log_action(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_list = sub.add_parser("list-wlans", help="List WLANs for a site (read-only)")
    p_list.add_argument("--site", required=True, help="Mist site_id")
    p_list.set_defaults(func=cmd_list_wlans)

    p_get = sub.add_parser("get-wlan", help="Show full config for one WLAN (read-only)")
    p_get.add_argument("--site", required=True)
    p_get.add_argument("--wlan-id", required=True)
    p_get.set_defaults(func=cmd_get_wlan)

    p_create = sub.add_parser("create-wlan", help="Create a new WLAN from a JSON config file")
    p_create.add_argument("--site", required=True)
    p_create.add_argument("--file", required=True, help="path to WLAN config JSON")
    p_create.add_argument(CONFIRM_FLAG, dest="yes_i_am_sure", action="store_true")
    p_create.set_defaults(func=cmd_create_wlan)

    p_update = sub.add_parser("update-wlan", help="Update an existing WLAN from a JSON config file")
    p_update.add_argument("--site", required=True)
    p_update.add_argument("--wlan-id", required=True)
    p_update.add_argument("--file", required=True, help="path to WLAN config JSON")
    p_update.add_argument(CONFIRM_FLAG, dest="yes_i_am_sure", action="store_true")
    p_update.set_defaults(func=cmd_update_wlan)

    p_delete = sub.add_parser("delete-wlan", help="Delete a WLAN (destructive, double confirmation required)")
    p_delete.add_argument("--site", required=True)
    p_delete.add_argument("--wlan-id", required=True)
    p_delete.add_argument(CONFIRM_FLAG, dest="yes_i_am_sure", action="store_true")
    p_delete.add_argument(DELETE_CONFIRM_FLAG, dest="confirm_delete", action="store_true")
    p_delete.set_defaults(func=cmd_delete_wlan)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
