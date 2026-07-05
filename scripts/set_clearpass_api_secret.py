#!/usr/bin/env python3
"""Store the ClearPass API client_secret into credentials.yml. ONE prompt (the key).

The client_id is fixed to 'cowork-lab-automation' (the client you created), so you only
paste the secret. Run ON the executor host so the key never appears in chat:
    python3 ~/lab/lab-version-control/scripts/set_clearpass_api_secret.py

Sanitizes the pasted key (trims whitespace, quotes, and stray terminal/bracketed-paste
escape sequences), backs up credentials.yml, rewrites the two clearpass_api lines, then
validates against ClearPass and prints OK/FAIL only (never the key or token).
"""
import os, re, sys, json, ssl, getpass, datetime, urllib.request, urllib.error

CRED = "~/lab/lab-version-control/inventory/credentials.yml"
CLIENT_ID = "cowork-lab-automation"

def clean(s):
    s = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", s)   # ANSI / bracketed-paste escapes
    s = s.replace("\x1b", "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s

def main():
    if not os.path.exists(CRED):
        print("credentials.yml not found:", CRED); return 2
    print("Client ID is fixed to:", CLIENT_ID)
    sec = clean(getpass.getpass("Paste the ClearPass API client_secret (hidden), then Enter: "))
    if not sec or " " in sec or "\t" in sec:
        print("That doesn't look like a clean key (empty or contains spaces). Nothing written."); return 1
    print("Got a key of length", len(sec), "- storing and validating...")

    text = open(CRED, encoding="utf-8").read()
    bak = CRED + ".bak." + datetime.datetime.now().strftime("%Y%m%dT%H%M%SZ")
    open(bak, "w", encoding="utf-8").write(text)
    new, n1 = re.subn(r"(?m)^(\s*client_id:\s*).*$",     lambda m: m.group(1)+CLIENT_ID, text, count=1)
    new, n2 = re.subn(r"(?m)^(\s*client_secret:\s*).*$", lambda m: m.group(1)+sec,       new,  count=1)
    if n1 != 1 or n2 != 1:
        print("Could not locate client_id/client_secret lines (n1=%s n2=%s). No change." % (n1, n2)); return 1
    open(CRED, "w", encoding="utf-8").write(new)

    import yaml
    cp = yaml.safe_load(open(CRED))["clearpass"]["clearpass_api"]
    base = cp["base_url"].rstrip("/"); ctx = ssl.create_default_context()
    if not cp.get("verify_tls", True):
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    body = json.dumps({"grant_type": "client_credentials",
                       "client_id": cp["client_id"], "client_secret": cp["client_secret"]}).encode()
    try:
        r = urllib.request.urlopen(urllib.request.Request(base + "/api/oauth", data=body,
                                   headers={"Content-Type": "application/json"}), timeout=12, context=ctx)
        t = json.loads(r.read())
        print("VALIDATION OK - ClearPass issued a token (expires_in=%s). Done." % t.get("expires_in")); return 0
    except urllib.error.HTTPError as e:
        print("VALIDATION FAILED - HTTP %s: %s" % (e.code, e.read()[:160]))
        print("The key was likely copied incomplete. Regenerate the secret in ClearPass and re-run."); return 1
    except Exception as e:
        print("VALIDATION FAILED -", type(e).__name__, str(e)[:160]); return 1

if __name__ == "__main__":
    sys.exit(main())
