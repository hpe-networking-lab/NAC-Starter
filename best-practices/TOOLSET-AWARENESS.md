# Toolset Awareness (binding)

*Facts before assumptions applies to your own toolset.*

**Rule:** Before telling the Human Authority that a capability or tool does not
exist — or that you "can't" perform an infra/automation action — enumerate what is
actually available. Do not assert from memory.

**Check, in order:**
1. **Your live MCP tool surface** — use tool discovery/search (e.g. hpe-networking
   `list_tools` / `search`) rather than assuming a tool is absent because you don't recall it.
2. **The lab capabilities index** — `lab-version-control/scripts/README.md`
   (automation scripts), `mcp-project/docs/mcp-catalog.md` (running MCP servers),
   `lab-version-control/inventory/` (hosts / VMs / creds / endpoints).
3. **The repo you're working in** — `scripts/`, `tools/`, docs — before concluding tooling is missing.

**Why:** the capability usually already exists. Asserting "no path" without checking
wastes the Human Authority's time, erodes trust, and violates *facts before assumptions*.
Origin: 2026-07-04 — a chat wrongly claimed it could not power off a VM when
`manage_esxi_vm.py`, an `esxi-mcp` server, and the MCP catalog all provided the path.

**Anti-rot:** any new capability (script or MCP) must be added to the capabilities
index; the daily drift-check flags `scripts/*.py` missing from `scripts/README.md`.
