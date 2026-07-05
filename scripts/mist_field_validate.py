#!/usr/bin/env python3
"""
Mist config field-validator — VALIDATION.md "schema field-validation" layer.

Reads live org config objects (READ-ONLY) and validates every field of every
object against the Mist OpenAPI schema for that object type. Flags fields that
are not present on the object's schema — the silently-accepted / wrong-field
class (e.g. site.vars, coa_servers[].host). Reusable across orgs/clouds.

Usage:
  python3 mist_field_validate.py \
      --spec /lab/github/mist_openapi/mist.openapi.json \
      --host api.gc4.mist.com --org <org_id> \
      --token-file /path/to/your-mist-token \
      [--allow coa_enabled,coa_port] [--only wlan,network_template]

Notes:
- Read-only: GETs only, no writes.
- The Mist OpenAPI is doc-only and lags releases; genuine but undocumented
  fields (e.g. wlan.coa_enabled/coa_port, live-validated per VALIDATION.md) are
  allow-listed by default and via --allow. Remaining unknowns need investigation.
- Exit 0 if no unexplained unknowns, else 1.
"""
import argparse, json, sys, urllib.request

# object type -> (schema name, org-level list endpoint)
TYPES = {
    "wlan":             ("wlan",             "/orgs/{org}/wlans"),
    "wlan_template":    ("template",         "/orgs/{org}/templates"),
    "network_template": ("network_template", "/orgs/{org}/networktemplates"),
    "rf_template":      ("rf_template",      "/orgs/{org}/rftemplates"),
    "sitegroup":        ("sitegroup",        "/orgs/{org}/sitegroups"),
    "site":             ("site",             "/orgs/{org}/sites"),
}
# genuine-but-undocumented fields (OpenAPI lag), verified live per VALIDATION.md
DEFAULT_ALLOW = {"coa_enabled", "coa_port"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--org", required=True)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--allow", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    spec = json.load(open(a.spec))
    SCH = spec["components"]["schemas"]
    token = open(a.token_file).read().strip()
    allow = set(DEFAULT_ALLOW) | {x for x in a.allow.split(",") if x}
    only = {x for x in a.only.split(",") if x}

    def deref(s):
        if isinstance(s, str): s = SCH.get(s, {})
        n = 0
        while isinstance(s, dict) and "$ref" in s and n < 12:
            s = SCH.get(s["$ref"].split("/")[-1], {}); n += 1
        return s

    def merged(schema):
        schema = deref(schema); props = {}; addl = None; stack = [schema]
        while stack:
            node = deref(stack.pop())
            if not isinstance(node, dict): continue
            stack.extend(node.get("allOf", []))
            props.update(node.get("properties", {}) or {})
            ap_ = node.get("additionalProperties")
            if isinstance(ap_, dict): addl = ap_
        return props, addl

    def check(schema, data, path, out):
        props, addl = merged(schema)
        for k, v in (data.items() if isinstance(data, dict) else []):
            if k in props:
                sub = props[k]
                if isinstance(v, dict):
                    check(sub, v, f"{path}.{k}", out)
                elif isinstance(v, list) and v and isinstance(v[0], dict):
                    items = deref(sub).get("items", {})
                    for i, el in enumerate(v):
                        if isinstance(el, dict): check(items, el, f"{path}.{k}[{i}]", out)
            elif addl is not None:
                if isinstance(v, dict): check(addl, v, f"{path}.{{}}", out)
            elif k not in allow:
                out.append(f"{path}.{k}")

    def get(path):
        req = urllib.request.Request(f"https://{a.host}/api/v1{path}",
                                     headers={"Authorization": f"Token {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    total_unknown = 0
    for typ, (schema, ep) in TYPES.items():
        if only and typ not in only: continue
        try:
            objs = get(ep.format(org=a.org))
        except Exception as e:
            print(f"[{typ}] fetch error: {e}"); continue
        for o in objs:
            name = o.get("name") or o.get("ssid") or o.get("id", "?")
            out = []; check(schema, o, typ, out)
            if out:
                total_unknown += len(out)
                print(f"!! {typ}: {name}")
                for u in out: print("     UNKNOWN:", u)
        # per-site settings when sweeping sites
        if typ == "site":
            for o in objs:
                try:
                    st = get(f"/sites/{o['id']}/setting")
                except Exception as e:
                    print(f"[site_setting {o.get('name')}] error: {e}"); continue
                out = []; check("site_setting", st, "site_setting", out)
                if out:
                    total_unknown += len(out)
                    print(f"!! site_setting: {o.get('name')}")
                    for u in out: print("     UNKNOWN:", u)
    print(f"\nUNEXPLAINED UNKNOWN FIELDS: {total_unknown}  (allow-listed: {sorted(allow)})")
    return 0 if total_unknown == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
