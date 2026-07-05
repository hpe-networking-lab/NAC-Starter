# NAC-Starter local executor MCP

A tiny MCP server that lets your Claude project act on **this repo folder** on
your own machine — read/write files, run the kit's `scripts/`, and commit to
git — all confined to the repo directory. It talks to Claude Desktop over
**stdio** (Claude launches it; no ports, no service, no firewall).

## Tools
`list_directory`, `read_file`, `write_file`, `run_command` (destructive-pattern
guardrails), `run_script` (only `scripts/*`), `git_status`, `git_commit`.

## Install (in WSL / Ubuntu, from the repo root)
```
python3 -m venv mcp-server/.venv
mcp-server/.venv/bin/pip install -r mcp-server/requirements.txt -r requirements.txt
```

## Register with Claude Desktop
See the deployment guide, section 1.2 (step 4) — it gives the exact
`claude_desktop_config.json` block that launches this server via `wsl.exe`.

## Scope
Root defaults to the repo containing this file; override with `EXECUTOR_ROOT`.
Every call is logged to `.executor-mcp.log` (gitignored).
