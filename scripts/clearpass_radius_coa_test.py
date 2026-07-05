#!/usr/bin/env python3
"""Unattended ClearPass RADIUS + CoA/Disconnect transport test (simulated NAD).

Runs from the executor host (EXECUTOR_IP), registered in ClearPass as a Network Device
(coa_capable, coa_port 3799, RADIUS shared secret). Requires Insight enabled (session API).
Steps: 1) Access-Request (MAB) w/ Message-Authenticator -> Accept/Reject; 2) Acct-Start to
open a live session; 3) listen on udp/3799 as the NAD, trigger a disconnect via the REST API,
report whether a Disconnect/CoA-Request arrives (and ACK it); 4) Acct-Stop.

Isolates whether ClearPass CoA/Disconnect *transport* works when NAD context is present.
Does NOT reproduce the WEBAUTH captive-portal context path (separate test). No secrets printed.
"""
import os, sys, json, ssl, time, socket, struct, hashlib, threading, random
import urllib.request, urllib.error, urllib.parse, yaml
from pyrad.client import Client
from pyrad.dictionary import Dictionary
from pyrad import packet

CRED="~/lab/lab-version-control/inventory/credentials.yml"; DICT="/tmp/cptest/dict"; NAS_IP="EXECUTOR_IP"
TEST_MAC="AA:BB:CC:%02X:%02X:%02X"%(random.randint(0,255),random.randint(0,255),random.randint(0,255))
FRAMED_IP="10.10.30.201"
RESULT={"radius":None,"session_found":False,"disconnect_api":None,"coa_received":False,"coa_code":None}

c=yaml.safe_load(open(CRED)); RAD=c["radius"]; CP=c["clearpass"]["clearpass_api"]
HOST=RAD["clearpass_host"]; SECRET=RAD["clearpass_shared_secret"].encode(); BASE=CP["base_url"].rstrip("/")
CTX=ssl.create_default_context()
if not CP.get("verify_tls",True): CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
def log(m): print(m,flush=True)

def token():
    b=json.dumps({"grant_type":"client_credentials","client_id":CP["client_id"],"client_secret":CP["client_secret"]}).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(BASE+"/api/oauth",data=b,headers={"Content-Type":"application/json"}),timeout=12,context=CTX).read())["access_token"]
def api(method,path,tok,body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(BASE+path,data=data,method=method,
        headers={"Authorization":"Bearer "+tok,"Content-Type":"application/json","Accept":"application/json"})
    try:
        r=urllib.request.urlopen(req,timeout=15,context=CTX); return r.status,(json.loads(r.read() or b"{}"))
    except urllib.error.HTTPError as e:
        try: return e.code,json.loads(e.read() or b"{}")
        except Exception: return e.code,{}

class DynAuthListener(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.sock.bind(("0.0.0.0",3799)); self.sock.settimeout(1.0); self.stop=False
    def run(self):
        while not self.stop:
            try: data,addr=self.sock.recvfrom(4096)
            except socket.timeout: continue
            except OSError: break
            if len(data)<20: continue
            code=data[0]; ident=data[1]; reqauth=data[4:20]
            RESULT["coa_received"]=True; RESULT["coa_code"]=code
            log("  <<< received %s (code=%d) from %s on udp/3799"%(
                {40:"Disconnect-Request",43:"CoA-Request"}.get(code,"code%d"%code),code,addr[0]))
            ack={40:41,43:44}.get(code,44); length=20; hdr=struct.pack("!BBH",ack,ident,length)
            respauth=hashlib.md5(hdr+reqauth+SECRET).digest()
            self.sock.sendto(hdr+respauth,addr)
            log("  >>> replied %s"%({41:"Disconnect-ACK",44:"CoA-ACK"}.get(ack)))
    def close(self):
        self.stop=True
        try: self.sock.close()
        except Exception: pass

def radius_auth():
    cli=Client(server=HOST,secret=SECRET,dict=Dictionary(DICT)); cli.timeout=6; cli.retries=2
    req=cli.CreateAuthPacket(code=packet.AccessRequest,User_Name=TEST_MAC)
    req["User-Password"]=req.PwCrypt(TEST_MAC); req["NAS-IP-Address"]=NAS_IP
    req["Calling-Station-Id"]=TEST_MAC; req["Called-Station-Id"]="0011223344ff:GUEST-SPON-CP"
    req["Service-Type"]="Call-Check"; req["NAS-Port-Type"]="Wireless-802.11"; req["NAS-Identifier"]="test-nad"
    if hasattr(req,"add_message_authenticator"): req.add_message_authenticator()
    try:
        rep=cli.SendPacket(req); return {2:"Access-Accept",3:"Access-Reject",11:"Access-Challenge"}.get(rep.code,rep.code)
    except Exception as e: return "NO-REPLY(%s)"%type(e).__name__

def acct(status,sid):
    cli=Client(server=HOST,secret=SECRET,dict=Dictionary(DICT)); cli.timeout=6; cli.retries=2
    p=cli.CreateAcctPacket(User_Name=TEST_MAC)
    p["Acct-Status-Type"]=status; p["Acct-Session-Id"]=sid; p["NAS-IP-Address"]=NAS_IP
    p["Framed-IP-Address"]=FRAMED_IP; p["Calling-Station-Id"]=TEST_MAC; p["NAS-Identifier"]="test-nad"; p["NAS-Port-Type"]="Wireless-802.11"
    try: cli.SendPacket(p); return True
    except Exception as e: log("  acct %s error: %s"%(status,e)); return False

def find_session(tok,sid):
    for _ in range(10):
        st,d=api("GET","/api/session?limit=30&calculate_count=false",tok)
        items=(d.get("_embedded",{}) or {}).get("items",[]) if isinstance(d,dict) else []
        for it in items:
            if it.get("acctsessionid")==sid or sid in str(it.get("id","")):
                return it
        time.sleep(2)
    return None

def main():
    log("=== ClearPass RADIUS + CoA transport test  (test MAC %s) ==="%TEST_MAC)
    tok=token()
    RESULT["radius"]=radius_auth(); log("1) RADIUS Access-Request  -> %s"%RESULT["radius"])
    lis=DynAuthListener(); lis.start(); log("2) NAD listener up on udp/3799")
    sid="cowork%08d"%random.randint(0,99999999)
    acct("Start",sid); log("3) Acct-Start sent (Acct-Session-Id %s)"%sid); time.sleep(3)
    sess=find_session(tok,sid)
    if sess:
        RESULT["session_found"]=True; sess_id=sess.get("id")
        log("4) session in ClearPass: id=%s state=%s mac=%s"%(sess_id,sess.get("state"),sess.get("mac_address")))
        ok=False
        for ep,body in [("/api/session/%s/disconnect"%urllib.parse.quote(sess_id,safe=''),{"confirm_disconnect":True}),
                        ("/api/session/%s/disconnect"%urllib.parse.quote(sess_id,safe=''),{}),
                        ("/api/session-action/disconnect",{"id":sess_id})]:
            st,d=api("POST",ep,tok,body); log("   POST %s -> %s %s"%(ep,st,(d.get("detail") if isinstance(d,dict) and d.get("detail") else "")))
            RESULT["disconnect_api"]=st
            if st in (200,204): ok=True; break
        if not ok: log("   (disconnect API did not 200; still watching 3799 briefly)")
    else:
        log("4) session NOT found via API; still watching 3799")
    for _ in range(12):
        if RESULT["coa_received"]: break
        time.sleep(1)
    acct("Stop",sid); log("5) Acct-Stop sent")
    lis.close(); return summarize()

def summarize():
    log("\n=== RESULT ===")
    log("RADIUS auth reply     : %s"%RESULT["radius"])
    log("Session seen via API  : %s"%RESULT["session_found"])
    log("Disconnect API status : %s"%RESULT["disconnect_api"])
    log("CoA/Disconnect rx'd   : %s%s"%(RESULT["coa_received"],(" (code %s)"%RESULT["coa_code"]) if RESULT["coa_received"] else ""))
    log("VERDICT: "+("PASS - CoA/Disconnect transport works with NAD context present"
                     if RESULT["coa_received"] else "INCONCLUSIVE - no CoA/Disconnect arrived"))
    return 0 if RESULT["coa_received"] else 1

if __name__=="__main__":
    sys.exit(main())
