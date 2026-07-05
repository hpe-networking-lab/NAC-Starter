#!/usr/bin/env python3
"""reconcile_status.py - guard the hand-maintained roadmap prose against live truth.

The reconcile_inventory/engagements guards cover machine data (devices, VMs, users,
engagement grounding). The narrative docs (known-issues, backlog) are hand-written and
have no guard - so they silently go stale (e.g. still citing ClearPass .8, DEVICE-3 at
.40, or the retired Legacy-Repo repo). This script catches that class of drift.

Truth source: current-state/INVENTORY.md (auto-generated from Mist/ESXi/AD).
Checks the forward-looking hand docs (NOT STATUS.md history), in their ACTIVE section
only (everything above a '## Resolved' or '## Done' heading), for:
  1. a powered-off / decommissioned VM described as if it were live,
  2. a device name immediately paired with an IP that disagrees with live inventory,
  3. a curated retired token (Legacy-Repo repo, ClearPass .8),
  4. a missing/old 'reconciled:' freshness stamp.

Deliberately conservative (low false-positive): only flags a wrong IP when it directly
follows the device name, and only flags an off-VM when a state word directly follows the
VM name (so 'live EAP' near a VM name does not trip it). Exit nonzero on any finding.
Standard library only.
"""
import os
import re
import sys
import datetime

ROOT = "/lab/github/lab-roadmap"
INVENTORY = os.path.join(ROOT, "current-state", "INVENTORY.md")
HAND_DOCS = [
    os.path.join(ROOT, "known-issues", "known-issues.md"),
    os.path.join(ROOT, "backlog", "backlog.md"),
]
MAX_STAMP_AGE_DAYS = 21
IP_RE = re.compile(r"192\.168\.86\.\d{1,3}")
STAMP_RE = re.compile(r"reconciled:\s*(\d{4}-\d{2}-\d{2})")
VM_ACTIVE = re.compile(r"\b(on|up|healthy|running|serving|live|active|powered\s+on)\b")
RETIRED_TOKENS = ("legacy-repo", "CLEARPASS_IP")
RESOLVED_MARK = re.compile(r"retir|resolv|done|~~|decommission", re.I)


def parse_inventory(text):
    device_ips = {}   # device name (lower) -> set of live IPs
    off_vms = set()
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## Network devices"):
            section = "dev"; continue
        if s.startswith("## VMs"):
            section = "vm"; continue
        if s.startswith("## ") and section:
            section = None; continue
        if not s.startswith("|") or set(s) <= set("|-: "):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if section == "dev" and len(cells) >= 4:
            name = cells[0].lower()
            if name and name != "name":
                device_ips.setdefault(name, set()).update(IP_RE.findall(" ".join(cells)))
        elif section == "vm" and len(cells) >= 2:
            name, state = cells[0].lower(), cells[1].lower()
            if name and name != "name" and state == "off":
                off_vms.add(name)
    return {k: v for k, v in device_ips.items() if k}, off_vms


def active_zone(text):
    return re.split(r"^##\s+(Resolved|Done)", text, flags=re.M | re.I)[0]


def main():
    if not os.path.exists(INVENTORY):
        print("reconcile_status: INVENTORY.md missing - run reconcile_inventory first")
        return 2
    device_ips, off_vms = parse_inventory(open(INVENTORY, encoding="utf-8").read())
    today = datetime.date.today()
    findings = []

    for path in HAND_DOCS:
        name = os.path.basename(path)
        if not os.path.exists(path):
            findings.append(f"{name}: missing"); continue
        text = open(path, encoding="utf-8").read()
        zone = active_zone(text)

        m = STAMP_RE.search(text)
        if not m:
            findings.append(f"{name}: no 'reconciled:' stamp")
        else:
            try:
                age = (today - datetime.date.fromisoformat(m.group(1))).days
                if age > MAX_STAMP_AGE_DAYS:
                    findings.append(f"{name}: reconciled stamp {age}d old (>{MAX_STAMP_AGE_DAYS})")
            except ValueError:
                findings.append(f"{name}: bad reconciled date '{m.group(1)}'")

        for tok in RETIRED_TOKENS:
            for ln in zone.splitlines():
                if tok in ln.lower() and not RESOLVED_MARK.search(ln):
                    findings.append(f"{name}: retired token '{tok}' in active text: {ln.strip()[:70]}")

        for ln in zone.splitlines():
            low = ln.lower()
            for vm in off_vms:
                i = low.find(vm)
                if i != -1 and VM_ACTIVE.search(low[i + len(vm): i + len(vm) + 22]):
                    findings.append(f"{name}: powered-off VM '{vm}' described as active: {ln.strip()[:70]}")
            for dname, live_ips in device_ips.items():
                if not live_ips:
                    continue
                i = low.find(dname)
                if i == -1:
                    continue
                near = IP_RE.findall(ln[i + len(dname): i + len(dname) + 40])
                if near and not (set(near) & live_ips):
                    findings.append(f"{name}: '{dname}' paired with {near} but live={sorted(live_ips)}")

    if findings:
        print("STATUS DRIFT - hand docs disagree with live inventory:")
        for f in findings:
            print("  - " + f)
        return 1
    print("reconcile_status: OK - known-issues + backlog match live inventory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
