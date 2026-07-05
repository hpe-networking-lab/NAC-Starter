#!/usr/bin/env python3
"""reconcile_inventory.py - regenerate live lab inventory from the sources of truth
(Mist / ESXi / AD) and flag drift vs the hand-maintained YAMLs.
Writes github/lab-roadmap/current-state/INVENTORY.md ; exit nonzero if drift found.
Secrets read from gitignored credentials.yml. Stdlib + paramiko + yaml only."""
import json, sys, subprocess, re, datetime, urllib.request
import yaml, paramiko

LAB="/lab"
CRED=f"{LAB}/lab-version-control/inventory/credentials.yml"
OUT=f"{LAB}/github/lab-roadmap/current-state/INVENTORY.md"
cfg=yaml.safe_load(open(CRED))
ORG=cfg['mist']['mist_api_token']['org_id']; TOKEN=cfg['mist']['mist_api_token']['api_token']

def mist_get(path):
    req=urllib.request.Request("https://api.mist.com/api/v1"+path, headers={"Authorization":"Token "+TOKEN})
    return json.load(urllib.request.urlopen(req, timeout=25))

# --- 1) Mist network devices (source of truth for switches/APs/gateways) ---
mist_devs=[]
try:
    for d in mist_get(f"/orgs/{ORG}/stats/devices?type=all&limit=1000"):
        mist_devs.append({"name":d.get("name"),"type":d.get("type"),"model":d.get("model"),
                          "ip":d.get("ip"),"mac":d.get("mac"),"version":d.get("version"),"status":d.get("status")})
except Exception as e:
    mist_devs=[{"error":str(e)[:120]}]

# --- 2) ESXi VMs (source of truth for VM power + guest IPs) ---
esxi=cfg['esxi']['esxi_admin']; vms=[]
try:
    host=str(esxi.get('govc_url','https://HYPERVISOR_IP')).replace('https://','').replace('http://','').strip('/')
    cli=paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(host, username=esxi.get('username','root'), password=esxi['password'], timeout=20, look_for_keys=False, allow_agent=False)
    def run(c):
        i,o,e=cli.exec_command(c); return o.read().decode(errors='replace')+e.read().decode(errors='replace')
    for line in run('vim-cmd vmsvc/getallvms').splitlines()[1:]:
        m=re.match(r'^(\d+)\s+(.*?)\s+\[', line)
        if not m: continue
        vid,name=m.group(1),m.group(2).strip()
        st='on' if 'Powered on' in run(f'vim-cmd vmsvc/power.getstate {vid}') else 'off'
        ips=sorted(set(re.findall(r'ipAddress = "([\d.]+)"', run(f'vim-cmd vmsvc/get.guest {vid}'))) - {'127.0.0.1','GATEWAY_IP'})
        vms.append({"name":name,"state":st,"ips":[i for i in ips if not i.startswith('172.')]})
    cli.close()
except Exception as e:
    vms=[{"error":str(e)[:120]}]

# --- 3) AD users (reuse the vetted read-only script) ---
ad=[]
try:
    o=subprocess.run(["python3",f"{LAB}/lab-version-control/scripts/manage_windows_ad.py","list-users"],capture_output=True,text=True,timeout=120).stdout
    for u in json.loads(re.search(r'\{.*\}',o,re.S).group(0)).get('users',[]):
        m=re.search(r'OU=([^,]+)',u['DistinguishedName'])
        ad.append({"sam":u['SamAccountName'],"enabled":u['Enabled'],"ou":(m.group(1) if m else 'Builtin')})
except Exception as e:
    ad=[{"error":str(e)[:120]}]

# --- 4) DRIFT vs hand YAMLs ---
drift=[]
live={d.get('name'):d for d in mist_devs if isinstance(d,dict) and d.get('name')}
namemap={'switch-a':'DEVICE-1','switch-b':'DEVICE-2','switch-c':'DEVICE-3'}
try:
    for d in (yaml.safe_load(open(f"{LAB}/lab-version-control/inventory/devices.yml")).get('devices') or []):
        yip=str((d.get('management_access') or {}).get('host') or '')
        L=live.get(namemap.get(d.get('name')),{})
        if L.get('ip') and yip and not yip.startswith(str(L['ip'])):
            drift.append(f"devices.yml `{d.get('name')}` host={yip} but Mist live ip={L['ip']} (model {L.get('model')})")
except Exception as e: drift.append(f"devices.yml parse err: {e}")
try:
    vmips={i for v in vms if isinstance(v,dict) for i in v.get('ips',[])}
    for v in (yaml.safe_load(open(f"{LAB}/lab-version-control/inventory/vms.yml")).get('vms') or []):
        cur=v.get('current_ip')
        if cur and str(v.get('status','')).startswith('deployed') and cur not in vmips:
            drift.append(f"vms.yml `{v.get('name')}` current_ip={cur} not seen live on ESXi")
except Exception as e: drift.append(f"vms.yml parse err: {e}")

# --- 5) write INVENTORY.md ---
ts=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
L=[f"# Lab Live Inventory (AUTO-GENERATED - do not hand-edit)\n",
   f"Generated **{ts}** by `reconcile_inventory.py` from Mist + ESXi + AD (live sources of truth).\n",
   "## Network devices (Mist)\n\n| Name | Type | Model | IP | Version | Status |\n|---|---|---|---|---|---|"]
for d in mist_devs:
    L.append(f"| _error_ | | | {d['error']} | | |" if 'error' in d else f"| {d['name']} | {d['type']} | {d['model']} | {d['ip']} | {d['version']} | {d['status']} |")
L+=["\n## VMs (ESXi)\n\n| Name | State | IP(s) |\n|---|---|---|"]
for v in vms:
    L.append(f"| _error_ | | {v['error']} |" if 'error' in v else f"| {v['name']} | {v['state']} | {', '.join(v['ips']) or '-'} |")
L+=["\n## AD users (mistlab.local)\n\n| User | Enabled | OU |\n|---|---|---|"]
for u in ad:
    L.append(f"| _error_ | | {u['error']} |" if 'error' in u else f"| {u['sam']} | {u['enabled']} | {u['ou']} |")
L+=["\n## Drift vs hand-maintained YAMLs\n"]
L += ([f"- [!] {d}" for d in drift] if drift else ["- None - YAMLs match live."])
open(OUT,'w').write("\n".join(L)+"\n")
print(f"reconcile: {len([d for d in mist_devs if 'error' not in d])} mist devs, {len([v for v in vms if 'error' not in v])} vms, {len([u for u in ad if 'error' not in u])} ad users; DRIFT={len(drift)}")
for d in drift: print("  DRIFT:", d)
sys.exit(1 if drift else 0)
