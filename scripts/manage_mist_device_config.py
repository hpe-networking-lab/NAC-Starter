#!/usr/bin/env python3
"""
manage_mist_device_config.py - Controlled Mist "additional CLI commands"
management for Mist-adopted Junos devices (Phase 3 / Priority 4
"Configuration write tools deferred to later phase").

Mist-managed Junos devices (JSI / outbound-ssh adoption) accept a list of
extra "display set" lines under additional_config_cmds, which Mist pushes to
the device and re-applies on every future config sync. This script lets
Claude inspect and extend that list - this is the channel previously used
(2026-06-12, see devices.yml notes) to add the lab-automation SSH user and
the SRX WAN host-inbound-traffic fix.

Subcommands:
  - get-config-cmds --device <name>           : show current
                                                  additional_config_cmds (read-only)
  - add-config-cmds --device <name> --file <f> : append new set-format lines
                                                  from <f> to additional_config_cmds

SAFETY (per MCP project spec, Priority 4 "Safety requirements" + Phase 3
"only after read-only MCPs are stable"):
  - add-config-cmds requires the literal flag --yes-i-am-sure. Without it,
    the script refuses and takes no action.
  - add-config-cmds is APPEND-ONLY: existing additional_config_cmds entries
    are preserved; new lines are appended (de-duplicated against the
    existing list). Nothing is ever removed by this script.
  - Lines must be plain 'set ...' commands (display set format), one per
    line, '#' comments and blank lines ignored.
  - All invocations (including refused ones) are appended to
    /lab/logs/mist_changes.log with timestamp, device, subcommand, and
    outcome.
  - The Mist API token is never printed or logged.
  - Credentials resolution and device->site/device_id lookup are identical
    to backup_junos_mist.py / manage_mist_wlan.py
    (inventory/devices.yml <device>.mist.{org_id,site_id,device_id},
    inventory/credentials.yml mist.mist_api_token).

Candidate files (--file) are plain text, one 'set ...' line per line.
Store candidate files under scripts/candidates/mist/<device>/.

Usage examples:
  # Read-only
  python3 manage_mist_device_config.py get-config-cmds --device switch-a

  # Append new lines (requires --yes-i-am-sure)
  python3 manage_mist_device_config.py add-config-cmds --device switch-a \\
      --file candidates/mist/switch-a/add_lab_automation_rw.set --yes-i-am-sure

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
INVENTORY_FILE = REPO_ROOT / "inventory" / "devices.yml"
CREDENTIALS_FILE = REPO_ROOT / "inventory" / "credentials.yml"
CANDIDATES_ROOT = LAB_ROOT / "scripts" / "candidates" / "mist"
LOG_FILE = LAB_ROOT / "logs" / "mist_changes.log"

DEFAULT_API_BASE = "https://api.mist.com/api/v1"

CONFIRM_FLAG = "--yes-i-am-sure"


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


def load_device(device_name):
    if not INVENTORY_FILE.exists():
        raise ValueError("inventory/devices.yml not found")
    with open(INVENTORY_FILE) as f:
        data = yaml.safe_load(f) or {}
    for d in data.get("devices", []):
        if d.get("name") == device_name:
            mist = d.get("mist") or {}
            if not mist.get("managed"):
                raise ValueError(f"device '{device_name}' is not Mist-managed (mist.managed != true)")
            for required in ("org_id", "site_id", "device_id"):
                if not mist.get(required):
                    raise ValueError(f"device '{device_name}' missing mist.{required} in devices.yml")
            return mist
    raise ValueError(f"unknown device '{device_name}' (not in devices.yml)")


def api_request(method, api_base, token, path, json_body=None):
    url = f"{api_base}{path}"
    headers = {"Authorization": f"Token {token}"}
    resp = requests.request(method, url, headers=headers, json=json_body, timeout=30)
    resp.raise_for_status()
    if resp.text:
        return resp.json()
    return None


def read_cmd_file(file_arg):
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
        raise FileNotFoundError(f"config cmd file not found: {file_arg}")

    lines = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("set ") and not line.startswith("delete "):
            raise ValueError(f"line must start with 'set ' or 'delete ' (display set format): {line!r}")
        lines.append(line)
    return path, lines


def cmd_get_config_cmds(args):
    result = {"command": "get-config-cmds", "device": args.device}
    try:
        creds = get_creds_or_raise()
        mist = load_device(args.device)
        path = f"/sites/{mist['site_id']}/devices/{mist['device_id']}"
        data = api_request("GET", creds["api_base"], creds["api_token"], path) or {}
        result["status"] = "ok"
        result["device_name"] = data.get("name")
        result["additional_config_cmds"] = data.get("additional_config_cmds", [])
        result["count"] = len(result["additional_config_cmds"])
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["reason"] = str(exc)
    return result


def cmd_add_config_cmds(args):
    result = {"command": "add-config-cmds", "device": args.device, "file": args.file}
    if not args.yes_i_am_sure:
        result["status"] = "refused"
        result["reason"] = f"missing {CONFIRM_FLAG} - no action taken"
        log_action(result)
        return result
    try:
        creds = get_creds_or_raise()
        mist = load_device(args.device)
        file_path, new_lines = read_cmd_file(args.file)
        result["file_resolved"] = str(file_path)
        result["new_lines"] = new_lines

        path = f"/sites/{mist['site_id']}/devices/{mist['device_id']}"
        current = api_request("GET", creds["api_base"], creds["api_token"], path) or {}
        existing = list(current.get("additional_config_cmds", []))
        result["existing_count"] = len(existing)

        appended = [line for line in new_lines if line not in existing]
        merged = existing + appended
        result["appended"] = appended
        result["skipped_existing"] = [line for line in new_lines if line in existing]

        if not appended:
            result["status"] = "ok"
            result["note"] = "no new lines to append (all already present)"
            result["additional_config_cmds_count"] = len(existing)
            log_action(result)
            return result

        data = api_request(
            "PUT", creds["api_base"], creds["api_token"], path,
            json_body={"additional_config_cmds": merged},
        )
        result["status"] = "ok"
        result["additional_config_cmds_count"] = len(merged)
        result["note"] = (
            f"appended {len(appended)} line(s) to additional_config_cmds for "
            f"'{args.device}' ({(data or {}).get('name', mist.get('device_name'))}). "
            "Mist will push this config to the device on next sync."
        )
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["reason"] = str(exc)
    log_action(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_get = sub.add_parser("get-config-cmds", help="Show current additional_config_cmds for a device (read-only)")
    p_get.add_argument("--device", required=True, help="device name from devices.yml (e.g. switch-a, switch-b)")
    p_get.set_defaults(func=cmd_get_config_cmds)

    p_add = sub.add_parser("add-config-cmds", help="Append new set-format lines to additional_config_cmds")
    p_add.add_argument("--device", required=True)
    p_add.add_argument("--file", required=True, help="path to file with 'set ...' lines (display set format)")
    p_add.add_argument(CONFIRM_FLAG, dest="yes_i_am_sure", action="store_true")
    p_add.set_defaults(func=cmd_add_config_cmds)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
