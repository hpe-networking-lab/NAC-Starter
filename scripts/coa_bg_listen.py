#!/usr/bin/env python3
"""Background: create a synthetic MAC-auth session correlated to Lab-PC's IP, then listen on
udp/3799 for a CoA and log it. Used to validate the WEBAUTH CoA fix by driving the real browser
through the guest portal (ClearPass correlates the web-login to this session by source IP)."""
import ssl,time,socket,struct,hashlib,yaml,sys
from pyrad.client import Client
from pyrad.dictionary import Dictionary
from pyrad import packet
LAB_PC_IP="TEST_PC_IP"; NAS_IP="EXECUTOR_IP"; MAC="AA:BB:CC:15:15:15"
CSID="aabbcc151515:GUEST-SPON-CP"; SID="coworkBROWSER01"; LOG="/tmp/coa_bg.log"
def log(m):
    open(LOG,"a").write("%s %s\n"%(time.strftime("%H:%M:%S"),m)); print(m,flush=True)
open(LOG,"w").write(""); 
cr=yaml.safe_load(open("~/lab/lab-version-control/inventory/credentials.yml"))["radius"]
HOST=cr["clearpass_host"]; SECRET=cr["clearpass_shared_secret"].encode()
cli=Client(server=HOST,secret=SECRET,dict=Dictionary("/tmp/cptest/dict")); cli.timeout=6; cli.retries=2
req=cli.CreateAuthPacket(code=packet.AccessRequest,User_Name=MAC); req["User-Password"]=req.PwCrypt(MAC)
req["NAS-IP-Address"]=NAS_IP; req["Calling-Station-Id"]=MAC; req["Called-Station-Id"]=CSID
req["Service-Type"]="Call-Check"; req["NAS-Port-Type"]="Wireless-802.11"; req["NAS-Identifier"]="test-nad"
if hasattr(req,"add_message_authenticator"): req.add_message_authenticator()
log("auth=%s"%{2:"Accept",3:"Reject"}.get(cli.SendPacket(req).code,"?"))
p=cli.CreateAcctPacket(User_Name=MAC); p["Acct-Status-Type"]="Start"; p["Acct-Session-Id"]=SID
p["NAS-IP-Address"]=NAS_IP; p["Framed-IP-Address"]=LAB_PC_IP; p["Calling-Station-Id"]=MAC
p["Called-Station-Id"]=CSID; p["NAS-Identifier"]="test-nad"; p["NAS-Port-Type"]="Wireless-802.11"
cli.SendPacket(p); log("session up MAC=%s framed=%s nas=%s"%(MAC,LAB_PC_IP,NAS_IP))
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("0.0.0.0",3799)); s.settimeout(1.0)
log("listening on udp/3799 ...")
end=time.time()+360
while time.time()<end:
    try: d,a=s.recvfrom(4096)
    except socket.timeout: continue
    except OSError: break
    if len(d)<20: continue
    code=d[0]; ident=d[1]; ra=d[4:20]
    log("*** CoA/DM RECEIVED: %s (code %d) from %s ***"%({40:"Disconnect-Request",43:"CoA-Request"}.get(code,"code%d"%code),code,a[0]))
    hdr=struct.pack("!BBH",{40:41,43:44}.get(code,44),ident,20); s.sendto(hdr+hashlib.md5(hdr+ra+SECRET).digest(),a)
log("done")
