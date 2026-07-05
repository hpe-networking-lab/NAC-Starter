#!/usr/bin/env python3
"""
snapshot_esxi.py - Read-only ESXi inventory export.

Connects to the ESXi host defined in inventory/devices.yml (esxi_hosts
section) via the vSphere API (pyVmomi) and exports:
  - VM inventory (name, power state, guest OS, CPU/mem config, IPs, datastore)
  - Datastore usage (capacity, free space, type)
  - Host resource usage (CPU/memory totals and usage)

READ-ONLY: does not power on/off VMs, create/revert snapshots, or modify
anything. Snapshot create/revert tooling is a future, explicitly-approved
addition per the project's safety requirements.

Credentials resolution order (credential_ref "esxi_admin"):
  1. inventory/credentials.yml (gitignored) -> esxi.esxi_admin.{username,password,govc_url,govc_insecure}
  2. Environment variables:
       ESXI_HOST, ESXI_USER, ESXI_PASSWORD, ESXI_INSECURE (1/0)

Usage:
  python3 snapshot_esxi.py
  python3 snapshot_esxi.py --dry-run

Output:
  exports/esxi/<timestamp>/inventory.json
  exports/esxi/<timestamp>/datastores.json
  exports/esxi/<timestamp>/host.json
  exports/esxi/latest -> <timestamp>  (symlink, best-effort)

Always exits 0; failures are reported in the JSON summary on stdout so this
script can be used inside create_milestone.sh without aborting the milestone.
"""

import argparse
import json
import os
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required (pip3 install --break-system-packages pyyaml)", file=sys.stderr)
    sys.exit(1)

LAB_ROOT = Path(os.environ.get("LAB_ROOT", "/lab"))
REPO_ROOT = LAB_ROOT / "lab-version-control"
INVENTORY_FILE = REPO_ROOT / "inventory" / "devices.yml"
CREDENTIALS_FILE = REPO_ROOT / "inventory" / "credentials.yml"
EXPORTS_ROOT = REPO_ROOT / "exports" / "esxi"


def load_esxi_host():
    if not INVENTORY_FILE.exists():
        return None
    with open(INVENTORY_FILE) as f:
        data = yaml.safe_load(f) or {}
    hosts = data.get("esxi_hosts") or []
    return hosts[0] if hosts else None


def load_credentials_file():
    if not CREDENTIALS_FILE.exists():
        return {}
    with open(CREDENTIALS_FILE) as f:
        return yaml.safe_load(f) or {}


def resolve_credentials(host_entry, creds_file):
    credential_ref = (host_entry.get("management_access") or {}).get("credential_ref") if host_entry else None
    esxi_creds = (creds_file or {}).get("esxi", {})
    entry = esxi_creds.get(credential_ref) if credential_ref else None

    host = (host_entry.get("management_access") or {}).get("host") if host_entry else None
    insecure = True

    if entry and entry.get("username"):
        return {
            "host": host or entry.get("govc_url", "").replace("https://", "").rstrip("/"),
            "username": entry.get("username"),
            "password": entry.get("password"),
            "insecure": entry.get("govc_insecure", insecure),
        }

    env_host = os.environ.get("ESXI_HOST", host)
    env_user = os.environ.get("ESXI_USER")
    env_pass = os.environ.get("ESXI_PASSWORD")
    env_insecure = os.environ.get("ESXI_INSECURE", "1") == "1"
    if env_user and env_pass and env_host:
        return {"host": env_host, "username": env_user, "password": env_pass, "insecure": env_insecure}

    return None


def bytes_to_gb(value):
    return round(value / (1024 ** 3), 2) if value is not None else None


def collect_inventory(si):
    from pyVmomi import vim  # type: ignore

    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    vms = []
    for vm in container.view:
        summary = vm.summary
        config = summary.config
        runtime = summary.runtime
        guest = summary.guest
        storage = summary.storage

        datastores = []
        try:
            datastores = [ds.name for ds in vm.datastore]
        except Exception:  # noqa: BLE001
            pass

        ip_addresses = []
        try:
            if guest and guest.ipAddress:
                ip_addresses.append(guest.ipAddress)
        except Exception:  # noqa: BLE001
            pass

        vms.append({
            "name": config.name,
            "power_state": str(runtime.powerState),
            "guest_full_name": config.guestFullName,
            "num_cpu": config.numCpu,
            "memory_mb": config.memorySizeMB,
            "ip_addresses": ip_addresses,
            "datastores": datastores,
            "committed_gb": bytes_to_gb(storage.committed) if storage else None,
            "uncommitted_gb": bytes_to_gb(storage.uncommitted) if storage else None,
            "uuid": config.uuid if config else None,
            "annotation": config.annotation if config else "",
        })
    container.Destroy()
    return vms


def collect_datastores(si):
    from pyVmomi import vim  # type: ignore

    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(content.rootFolder, [vim.Datastore], True)
    datastores = []
    for ds in container.view:
        summary = ds.summary
        datastores.append({
            "name": summary.name,
            "type": summary.type,
            "capacity_gb": bytes_to_gb(summary.capacity),
            "free_space_gb": bytes_to_gb(summary.freeSpace),
            "accessible": summary.accessible,
            "url": summary.url,
        })
    container.Destroy()
    return datastores


def collect_host_info(si):
    from pyVmomi import vim  # type: ignore

    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    hosts = []
    for host in container.view:
        summary = host.summary
        hw = summary.hardware
        qs = summary.quickStats
        hosts.append({
            "name": summary.config.name if summary.config else host.name,
            "vendor": hw.vendor if hw else None,
            "model": hw.model if hw else None,
            "cpu_model": hw.cpuModel if hw else None,
            "num_cpu_cores": hw.numCpuCores if hw else None,
            "num_cpu_threads": hw.numCpuThreads if hw else None,
            "memory_size_gb": bytes_to_gb(hw.memorySize) if hw else None,
            "cpu_usage_mhz": qs.overallCpuUsage,
            "memory_usage_mb": qs.overallMemoryUsage,
            "uptime_seconds": qs.uptime,
            "esxi_version": summary.config.product.fullName if summary.config and summary.config.product else None,
        })
    container.Destroy()
    return hosts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without connecting")
    args = parser.parse_args()

    host_entry = load_esxi_host()
    creds_file = load_credentials_file()
    creds = resolve_credentials(host_entry, creds_file)

    summary = {
        "script": "snapshot_esxi.py",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "skipped",
        "reason": None,
        "export_dir": None,
    }

    if not creds:
        summary["reason"] = (
            "no credentials resolved (set inventory/credentials.yml esxi.esxi_admin, "
            "or ESXI_HOST/ESXI_USER/ESXI_PASSWORD env vars)"
        )
        print(json.dumps(summary, indent=2))
        return

    if args.dry_run:
        summary["status"] = "dry-run"
        summary["reason"] = f"would connect to {creds['username']}@{creds['host']} via vSphere API"
        print(json.dumps(summary, indent=2))
        return

    try:
        from pyVim.connect import SmartConnect, Disconnect
    except ImportError:
        summary["status"] = "error"
        summary["reason"] = "pyVmomi not installed (pip3 install --break-system-packages pyvmomi)"
        print(json.dumps(summary, indent=2))
        return

    context = None
    if creds.get("insecure", True):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        si = SmartConnect(
            host=creds["host"],
            user=creds["username"],
            pwd=creds["password"],
            sslContext=context,
        )
    except Exception as exc:  # noqa: BLE001
        summary["status"] = "error"
        summary["reason"] = f"connection failed: {exc}"
        print(json.dumps(summary, indent=2))
        return

    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = EXPORTS_ROOT / timestamp
        out_dir.mkdir(parents=True, exist_ok=True)

        vms = collect_inventory(si)
        datastores = collect_datastores(si)
        hosts = collect_host_info(si)

        (out_dir / "inventory.json").write_text(json.dumps(vms, indent=2))
        (out_dir / "datastores.json").write_text(json.dumps(datastores, indent=2))
        (out_dir / "host.json").write_text(json.dumps(hosts, indent=2))

        latest_link = EXPORTS_ROOT / "latest"
        try:
            if latest_link.exists() or latest_link.is_symlink():
                latest_link.unlink()
            latest_link.symlink_to(timestamp)
        except OSError:
            pass

        summary["status"] = "ok"
        summary["export_dir"] = str(out_dir.relative_to(REPO_ROOT))
        summary["vm_count"] = len(vms)
        summary["datastore_count"] = len(datastores)
        summary["host_count"] = len(hosts)
    finally:
        Disconnect(si)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
