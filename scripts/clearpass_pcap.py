#!/usr/bin/env python3
"""Run a ClearPass-side packet capture via appadmin CLI (dump logs PacketCapture).
Background-friendly: writes progress/status JSON so the caller can poll instead of
holding a long foreground SSH session open.

Usage: clearpass_pcap.py <name> <duration_sec> <zip_password> [proto]
Reads appadmin creds from ~/lab/lab-version-control/inventory/credentials.yml -> clearpass.clearpass_cli
"""
import sys, os, time, json, yaml, paramiko

NAME = sys.argv[1] if len(sys.argv) > 1 else "coa_capture"
DUR  = int(sys.argv[2]) if len(sys.argv) > 2 else 200
ZIPW = sys.argv[3] if len(sys.argv) > 3 else "YOUR_ZIP_PASSWORD"
PROTO = sys.argv[4] if len(sys.argv) > 4 else "udp"
STATUS = "/tmp/clearpass_pcap_status.json"

def put(d):
    d["ts"] = time.time()
    json.dump(d, open(STATUS, "w"))

cfg = yaml.safe_load(open("~/lab/lab-version-control/inventory/credentials.yml"))
cli = cfg["clearpass"]["clearpass_cli"]
host, user, pw = cli["host"], cli["username"], cli["password"]

put({"state": "starting", "name": NAME, "duration": DUR})
try:
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw, timeout=15, look_for_keys=False, allow_agent=False)
    sh = c.invoke_shell(); time.sleep(2); sh.recv(9000)
    cmd = f"dump logs -f {NAME} -t PacketCapture -d {DUR} -p {PROTO} -c {ZIPW}"
    sh.send(cmd + "\n")
    put({"state": "capturing", "name": NAME, "duration": DUR, "cmd": cmd})
    buf = ""; deadline = time.time() + DUR + 90
    while time.time() < deadline:
        if sh.recv_ready():
            buf += sh.recv(65000).decode(errors="replace")
            if "Created Policy Manager log dump" in buf:
                put({"state": "done", "name": NAME, "output": buf[-1500:]}); break
            if "Collecting logs failed" in buf or "ERROR" in buf:
                put({"state": "error", "name": NAME, "output": buf[-1500:]}); break
        else:
            time.sleep(2)
    else:
        put({"state": "timeout", "name": NAME, "output": buf[-1500:]})
    c.close()
except Exception as e:
    put({"state": "exception", "error": f"{type(e).__name__}: {e}"})
