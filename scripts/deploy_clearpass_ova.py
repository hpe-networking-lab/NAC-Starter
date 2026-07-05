#!/usr/bin/env python3
"""
deploy_clearpass_ova.py  — register + power on a ClearPass OVA on the free-licensed
ESXi host (HYPERVISOR_IP) via SSH + vim-cmd / vmkfstools. Avoids the vSphere API
(RestrictedVersion on free license) and ovftool (not installed / API-bound).

PREP NOTE (2026-06-27): written before the 6.14 OVA was on the datastore. Run with
--dry-run FIRST once the OVA is uploaded to review the parsed hardware spec, THEN
re-run with --commit. ESXi root creds come from inventory/credentials.yml (esxi.esxi_admin).

Usage:
  # 1) review what will be built (no changes):
  python3 deploy_clearpass_ova.py --ova "/vmfs/volumes/DL560G9/clearpass-6.14.ova" --dry-run
  # 2) deploy (register only):
  python3 deploy_clearpass_ova.py --ova "/vmfs/volumes/DL560G9/clearpass-6.14.ova" --commit
  # 3) deploy + power on:
  python3 deploy_clearpass_ova.py --ova "/vmfs/volumes/DL560G9/clearpass-6.14.ova" --commit --poweron
"""
import argparse, sys, os, re, xml.etree.ElementTree as ET
import yaml, paramiko

ESXI_HOST = "HYPERVISOR_IP"
INV = "~/lab/lab-version-control/inventory/credentials.yml"

def ssh_connect():
    c = yaml.safe_load(open(INV))["esxi"]["esxi_admin"]
    cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(ESXI_HOST, username=c.get("username","root"), password=c["password"],
                timeout=15, look_for_keys=False, allow_agent=False)
    return cli

def run(cli, cmd, check=True):
    i,o,e = cli.exec_command(cmd)
    out = o.read().decode(errors="replace"); err = e.read().decode(errors="replace")
    rc = o.channel.recv_exit_status()
    if check and rc != 0:
        raise RuntimeError(f"cmd failed ({rc}): {cmd}\n{err or out}")
    return out, err, rc

NS = {"ovf":"http://schemas.dmtf.org/ovf/envelope/1",
      "rasd":"http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"}

def parse_ovf(text):
    root = ET.fromstring(text)
    spec = {"cpus":None,"mem_mb":None,"guest":None,"disks":[],"nics":0,"refs":{}}
    for f in root.iter("{%s}File" % NS["ovf"]):
        spec["refs"][f.get("{%s}id"%NS["ovf"])] = f.get("{%s}href"%NS["ovf"])
    # capacity per disk (ovf:Disk -> capacity * units)
    diskcap = {}
    for d in root.iter("{%s}Disk" % NS["ovf"]):
        diskcap[d.get("{%s}diskId"%NS["ovf"])] = (d.get("{%s}capacity"%NS["ovf"]),
                                                  d.get("{%s}capacityAllocationUnits"%NS["ovf"]))
        fr = d.get("{%s}fileRef"%NS["ovf"])
        if fr: diskcap[d.get("{%s}diskId"%NS["ovf"])] += (spec["refs"].get(fr),)
    for it in root.iter("{%s}Item" % NS["rasd"].replace("rasd","ovf")) if False else root.iter("{%s}Item"%NS["ovf"]):
        rt = it.findtext("{%s}ResourceType"%NS["rasd"])
        if rt == "3":  # CPU
            spec["cpus"] = it.findtext("{%s}VirtualQuantity"%NS["rasd"])
        elif rt == "4":  # Memory
            spec["mem_mb"] = it.findtext("{%s}VirtualQuantity"%NS["rasd"])
        elif rt == "10":  # NIC
            spec["nics"] += 1
    os_el = root.find(".//{%s}OperatingSystemSection"%NS["ovf"])
    if os_el is not None:
        spec["guest"] = os_el.findtext("{%s}Description"%NS["ovf"]) or os_el.get("{%s}id"%NS["ovf"])
    spec["disks"] = [v for v in diskcap.values()]
    return spec

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ova", required=True, help="datastore path to the .ova on ESXi")
    ap.add_argument("--name", default="ClearPass-6.14")
    ap.add_argument("--network", default="VM Network", help="ESXi portgroup for the mgmt NIC")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--poweron", action="store_true")
    a = ap.parse_args()
    if not (a.dry_run or a.commit):
        print("Specify --dry-run or --commit"); sys.exit(2)

    cli = ssh_connect()
    out,_,_ = run(cli, "vmware -v"); print("Host:", out.strip())
    # OVA must exist
    run(cli, f"test -f '{a.ova}'")
    dsdir = os.path.dirname(a.ova)
    work = f"{dsdir}/{a.name}"
    # peek the OVF inside the OVA without extracting everything
    ovf_name,_,_ = run(cli, f"tar -tf '{a.ova}' | grep -m1 '\\.ovf$'")
    ovf_name = ovf_name.strip()
    ovf_text,_,_ = run(cli, f"tar -xO -f '{a.ova}' '{ovf_name}'")
    spec = parse_ovf(ovf_text)
    print("\n=== Parsed OVF spec ===")
    print(f"  vCPUs : {spec['cpus']}")
    print(f"  Memory: {spec['mem_mb']} MB")
    print(f"  Guest : {spec['guest']}")
    print(f"  NICs  : {spec['nics']} (will attach to portgroup '{a.network}', vmxnet3)")
    print(f"  Disks :")
    for d in spec["disks"]:
        print(f"    - {d}")
    print(f"  Target: {work}/{a.name}.vmx")
    print("\nNOTE: confirm vCPU/RAM meet ClearPass 6.14 CP-VA minimums before --commit.")

    if a.dry_run:
        print("\n[dry-run] no changes made."); cli.close(); return

    # --- commit path ---
    run(cli, f"mkdir -p '{work}'")
    run(cli, f"tar -xf '{a.ova}' -C '{work}'")
    # convert each stream-optimized vmdk -> thin
    vmdks,_,_ = run(cli, f"ls '{work}'/*.vmdk 2>/dev/null", check=False)
    attached = []
    for i, src in enumerate([v for v in vmdks.split() if v]):
        dst = f"{work}/{a.name}-disk{i}.vmdk"
        print(f"Converting {os.path.basename(src)} -> {os.path.basename(dst)} (thin)")
        run(cli, f"vmkfstools -i '{src}' '{dst}' -d thin")
        attached.append(dst)
    # build a minimal VMX from the parsed spec
    guest = "other4xlinux64Guest"  # ClearPass = RHEL8 64; adjust if OVF differs
    vmx = [
        '.encoding = "UTF-8"', 'config.version = "8"', 'virtualHW.version = "19"',
        f'displayName = "{a.name}"', f'guestOS = "{guest}"',
        f'numvcpus = "{spec["cpus"] or 8}"', f'memSize = "{spec["mem_mb"] or 8192}"',
        'scsi0.present = "TRUE"', 'scsi0.virtualDev = "lsilogic"',
        'ethernet0.present = "TRUE"', 'ethernet0.virtualDev = "vmxnet3"',
        f'ethernet0.networkName = "{a.network}"', 'ethernet0.addressType = "generated"',
        'pciBridge0.present = "TRUE"', 'firmware = "bios"',
    ]
    for i, d in enumerate(attached):
        vmx += [f'scsi0:{i}.present = "TRUE"', f'scsi0:{i}.fileName = "{os.path.basename(d)}"']
    vmxpath = f"{work}/{a.name}.vmx"
    heredoc = "\n".join(vmx).replace('"','\\"')
    run(cli, f'printf "%s\\n" "{heredoc}" > "{vmxpath}"')
    out,_,_ = run(cli, f"vim-cmd solo/registervm '{vmxpath}'")
    vmid = out.strip().split()[-1] if out.strip() else None
    print(f"Registered VM, vmid={vmid}")
    if a.poweron and vmid:
        run(cli, f"vim-cmd vmsvc/power.on {vmid}")
        print(f"Powered on vmid={vmid}. Open the ESXi web console for first-boot (EULA + admin pw + mgmt IP).")
    cli.close()

if __name__ == "__main__":
    main()
