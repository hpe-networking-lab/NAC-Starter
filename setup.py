#!/usr/bin/env python3
"""
Guided setup wizard for the Claude + Juniper Mist (+ optional ClearPass NAC) starter kit.

Run this FIRST:  python3 setup.py

It walks you through every value the kit needs, explains where to find each one,
VALIDATES it live (tests your Mist token and, if you set up ClearPass, your ClearPass
API client), and writes inventory/credentials.yml for you.

- Standard-library only: works before any `pip install`.
- Secrets are typed hidden and never printed or logged.
- credentials.yml is gitignored, so it never gets committed.
"""
import os, sys, json, ssl, getpass, urllib.request, urllib.parse, urllib.error, time

HERE = os.path.dirname(os.path.abspath(__file__))
INV  = os.path.join(HERE, "inventory")
CRED = os.path.join(INV, "credentials.yml")

def line(): print("-" * 68)
def hdr(t): print("\n" + "=" * 68 + "\n  " + t + "\n" + "=" * 68)

def ask(prompt, default=None, secret=False, allow_empty=False):
    """Prompt until a value is given (or default/empty allowed). Secrets are hidden."""
    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            v = getpass.getpass(
                f"{prompt}{suffix}\n"
                "  >> hidden input: you will NOT see anything as you type or paste "
                "(no dots, no cursor) -- that is normal. Paste, then press Enter: "
            ).strip()
        else:
            v = input(f"{prompt}{suffix}: ").strip()
        if not v and default is not None:
            return default
        if not v and allow_empty:
            return ""
        if v:
            return v
        print("  (required — please enter a value)")

def yn(prompt, default=False):
    d = "Y/n" if default else "y/N"
    v = input(f"{prompt} [{d}]: ").strip().lower()
    if not v:
        return default
    return v in ("y", "yes")

def http(method, url, headers=None, data=None, verify=True, timeout=20):
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        r = urllib.request.urlopen(req, context=ctx, timeout=timeout)
        body = r.read().decode("utf-8", "ignore")
        return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return None, str(e)

def validate_mist(api_base, token):
    status, body = http("GET", api_base.rstrip("/") + "/self",
                        headers={"Authorization": f"Token {token}", "Accept": "application/json"})
    if status == 200:
        try:
            who = json.loads(body); email = who.get("email") or who.get("first_name") or "ok"
            return True, f"token valid (account: {email})", who
        except Exception:
            return True, "token valid", {}
    if status == 401:
        return False, "401 Unauthorized — token wrong, or wrong regional cloud (api_base)", {}
    return False, f"could not validate (status={status}: {str(body)[:80]})", {}

def validate_clearpass(base_url, cid, secret):
    data = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "client_id": cid, "client_secret": secret}).encode()
    status, body = http("POST", base_url.rstrip("/") + "/api/oauth",
                        headers={"Accept": "application/json"}, data=data, verify=False)
    if status == 200 and "access_token" in body:
        return True, "API client valid — ClearPass issued a token"
    if status in (400, 401):
        return False, "auth rejected — check client_id / client_secret / grant type"
    return False, f"could not reach/validate (status={status}: {str(body)[:80]})"

def classify_privs(who):
    """Best-effort: is this Mist token read-only or read-write? From /self privileges[].role."""
    privs = who.get("privileges") or []
    roles = sorted({(p.get("role") or "").lower() for p in privs if isinstance(p, dict)})
    roles = [r for r in roles if r]
    if not roles:
        return "UNKNOWN", "couldn't read the role from the token -- proceed and test a read"
    rw = {"admin", "write", "superuser", "super_user"}
    ro = {"read", "observer"}
    if any(r in rw for r in roles):
        return "READ-WRITE", "this token CAN make changes (use it for management)"
    if all(r in ro for r in roles):
        return "READ-ONLY", "safe for testing -- it cannot change anything"
    return "LIMITED", "roles: " + ", ".join(roles)

def main():
    hdr("Claude + Juniper Mist starter — guided setup")
    print("This wizard writes inventory/credentials.yml. Press Ctrl-C any time to abort.\n"
          "Nothing is committed to git — credentials.yml is gitignored.")

    if os.path.exists(CRED):
        if not yn(f"\n{CRED} already exists. Overwrite (a timestamped backup is kept)?", False):
            print("Aborted — existing credentials.yml left untouched."); return 1

    # ---------------- Phase 1: Mist ----------------
    hdr("Phase 1 — Juniper Mist  (required)")
    print("Where to find these: log in to the Mist dashboard.\n"
          "  - org_id : Organization > Settings  (shown as 'Organization ID'), or it's in the\n"
          "             dashboard URL after /org/.\n"
          "  - API token: My Account > API Tokens (or Organization > Settings > API Token) >\n"
          "               Create Token. Copy it once — it isn't shown again.\n"
          "  - API base: the regional cloud your org lives in. Global 01 is the default; if your\n"
          "               dashboard URL is manage.eu.mist.com use https://api.eu.mist.com, etc.")
    print("\n  TIP: create a READ-ONLY token first (role: Observer) to test safely; mint a\n"
          "       read-write token later when you want to push changes.")
    org_id   = ask("\nMist org_id")
    api_base = ask("Mist API base URL", default="https://api.mist.com/api/v1")
    while True:
        token = ask("Mist API token", secret=True)
        print("  validating against Mist ...")
        ok, msg, who = validate_mist(api_base, token)
        print(("  OK  - " if ok else "  X   - ") + msg)
        if ok:
            lvl, detail = classify_privs(who)
            print(f"  token privilege: {lvl}  ({detail})")
            break
        if not yn("  Try again? (No = save anyway, unvalidated)", True):
            break

    # ---------------- Phase 2: ClearPass (optional) ----------------
    cp = None
    hdr("Phase 2 — Aruba ClearPass NAC  (optional)")
    if yn("Set up ClearPass now? (You can re-run this wizard later to add it.)", False):
        print("\nWhere to find these:\n"
              "  - Deploy ClearPass (see the guide, Phase 2). On the ClearPass GUI create a REST\n"
              "    API client: Guest > Administration > API Services > API Clients >\n"
              "    Grant type = Client Credentials. Copy the client_secret.\n"
              "  - Hypervisor (ESXi) details are only needed if you'll deploy the OVA from here.")
        hyp_ip   = ask("Hypervisor (ESXi) IP or host", allow_empty=True)
        hyp_user = ask("Hypervisor username", default="root")
        hyp_pw   = ask("Hypervisor root password (hidden, blank to skip)", secret=True, allow_empty=True)
        cp_ip    = ask("ClearPass IP or host")
        cp_cid   = ask("ClearPass API client_id")
        while True:
            cp_sec = ask("ClearPass API client_secret", secret=True)
            base_url = f"https://{cp_ip}"
            print("  validating against ClearPass ...")
            ok, msg = validate_clearpass(base_url, cp_cid, cp_sec)
            print(("  OK  - " if ok else "  X   - ") + msg)
            if ok:
                break
            if not yn("  Try again? (No = save anyway, unvalidated)", True):
                break
        rad_sec = ask("Mist<->ClearPass RADIUS shared secret", secret=True)
        cp = dict(hyp_ip=hyp_ip, hyp_user=hyp_user, hyp_pw=hyp_pw, cp_ip=cp_ip,
                  cp_cid=cp_cid, cp_sec=cp_sec, rad_sec=rad_sec)

    # ---------------- Write credentials.yml ----------------
    if os.path.exists(CRED):
        bak = CRED + ".bak." + time.strftime("%Y%m%dT%H%M%S")
        os.rename(CRED, bak); print(f"\nBacked up existing file to {os.path.basename(bak)}")
    os.makedirs(INV, exist_ok=True)

    def q(s): return json.dumps(s)  # safe-quote a scalar for YAML
    out = []
    out.append("# Generated by setup.py. NEVER commit this file (it is gitignored).")
    out.append("# Re-run `python3 setup.py` to regenerate.\n")
    out.append("mist:")
    out.append("  mist_api_token:")
    out.append(f"    api_token: {q(token)}")
    out.append(f"    org_id: {q(org_id)}")
    out.append(f"    api_base: {q(api_base)}")
    if cp:
        out.append("\nesxi:")
        out.append("  esxi_admin:")
        out.append(f"    username: {q(cp['hyp_user'])}")
        out.append(f"    password: {q(cp['hyp_pw'])}")
        out.append(f"    govc_url: {q('https://' + cp['hyp_ip']) if cp['hyp_ip'] else q('')}")
        out.append("    govc_insecure: true")
        out.append("\nclearpass:")
        out.append("  clearpass_api:")
        out.append(f"    client_id: {q(cp['cp_cid'])}")
        out.append(f"    client_secret: {q(cp['cp_sec'])}")
        out.append(f"    base_url: {q('https://' + cp['cp_ip'])}")
        out.append("    verify_tls: false")
        out.append("  radius:")
        out.append(f"    clearpass_host: {q(cp['cp_ip'])}")
        out.append(f"    clearpass_shared_secret: {q(cp['rad_sec'])}")
    with open(CRED, "w") as f:
        f.write("\n".join(out) + "\n")
    try:
        os.chmod(CRED, 0o600)
    except Exception:
        pass

    hdr("Done")
    print(f"Wrote {CRED} (permissions 600, gitignored).")
    print("Filled: Mist" + (" + ClearPass" if cp else " only (re-run to add ClearPass)"))
    print("\nNext: open docs/Claude-Mist-ClearPass-Deployment-Guide.md and continue from section 1.3\n"
          "(create the Claude project and connect this folder).")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted."); sys.exit(1)
