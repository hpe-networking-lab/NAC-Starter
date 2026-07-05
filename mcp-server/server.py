#!/usr/bin/env python3
"""
NAC-Starter local executor MCP
==============================

A small MCP server that gives your Claude project controlled access to THIS
folder on your own machine (the NAC-Starter checkout) — so Claude can read and
write files, run the kit's scripts, and commit to git, all confined to the
repo directory.

It talks to Claude Desktop over **stdio** (Claude launches it for you via the
config you add in the guide — no ports, no background service, no firewall).

Scope / safety:
  - Every file / command / script path is confined to EXECUTOR_ROOT (this
    repo). Anything that would escape it is rejected.
  - run_command blocks catastrophic patterns always (fork bombs, mkfs, dd to a
    block device, rm -rf /, reboot/shutdown) and soft-blocks destructive ones
    (recursive rm/chmod/chown, git reset --hard, git push --force, ...) unless
    authorize_destructive=True is explicitly passed.
  - run_script only runs scripts that already exist under EXECUTOR_ROOT/scripts.
  - Every call is appended as a JSON line to EXECUTOR_ROOT/.executor-mcp.log.

Configure the root with the EXECUTOR_ROOT env var; by default it is the repo
that contains this file (../ from mcp-server/).
"""

import json
import os
import re
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default root = the repo that contains this file (mcp-server/ -> repo root).
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("EXECUTOR_ROOT", str(_DEFAULT_ROOT))).resolve()
SCRIPTS_DIR = ROOT / "scripts"
LOG_FILE = Path(os.environ.get("EXECUTOR_LOG_FILE", str(ROOT / ".executor-mcp.log")))

DEFAULT_COMMAND_TIMEOUT = int(os.environ.get("EXECUTOR_COMMAND_TIMEOUT", "60"))
DEFAULT_SCRIPT_TIMEOUT = int(os.environ.get("EXECUTOR_SCRIPT_TIMEOUT", "600"))
MAX_READ_BYTES = int(os.environ.get("EXECUTOR_MAX_READ_BYTES", "200000"))

# Always blocked, even with authorize_destructive=True.
HARD_BLOCK_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*-?-no-preserve-root",
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+.*\bof=/dev/(sd|nvme|vd|hd)",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
    r">\s*/dev/(sd|nvme|vd|hd)[a-z0-9]*\b",
    r"\bshred\b.*-[a-zA-Z]*u",
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/\s*$",
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/\*",
    r"\breboot\b", r"\bshutdown\b", r"\bpoweroff\b", r"\bhalt\b",
    r"\binit\s+0\b", r"\binit\s+6\b",
]

# Require authorize_destructive=True.
SOFT_BLOCK_PATTERNS = [
    r"\brm\s+-[a-zA-Z]*r",
    r"\brm\s+--recursive",
    r"\bfind\b.*-delete",
    r"\bgit\s+reset\s+--hard",
    r"\bgit\s+clean\s+-[a-zA-Z]*f",
    r"\bgit\s+push\b.*--force",
    r"\bchmod\s+-R\b",
    r"\bchown\s+-R\b",
    r"\btruncate\b",
    r">\s*.*\.git\b",
    r"\bdrop\s+(table|database)\b",
    r"\bsystemctl\s+(stop|disable|mask)\b",
    r"\bkill(all)?\s+-9\b",
]

HARD_BLOCK_RE = [re.compile(p, re.IGNORECASE) for p in HARD_BLOCK_PATTERNS]
SOFT_BLOCK_RE = [re.compile(p, re.IGNORECASE) for p in SOFT_BLOCK_PATTERNS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_in_root(path: str, base: Path = ROOT) -> Path:
    p = Path(path)
    candidate = p if p.is_absolute() else (base / p)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves to '{resolved}', which is outside "
            f"the allowed root '{base}'."
        )
    return resolved


def _log(action: str, detail: dict) -> None:
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "action": action, **detail}
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass


def _check_command_safety(command: str, authorize_destructive: bool) -> None:
    for rx in HARD_BLOCK_RE:
        if rx.search(command):
            raise ValueError(
                f"Command rejected: matches a permanently-blocked pattern "
                f"({rx.pattern}). Not permitted under any circumstances."
            )
    for rx in SOFT_BLOCK_RE:
        if rx.search(command) and not authorize_destructive:
            raise ValueError(
                f"Command rejected: matches a potentially destructive pattern "
                f"({rx.pattern}) and was called without authorize_destructive=True. "
                f"Re-run with that flag if this was intentional and approved."
            )


def _run_subprocess(args_or_cmd, cwd: Path, timeout: int, shell: bool):
    try:
        proc = subprocess.run(args_or_cmd, cwd=str(cwd), shell=shell,
                              capture_output=True, text=True, timeout=timeout)
        return {"returncode": proc.returncode,
                "stdout": proc.stdout[-MAX_READ_BYTES:],
                "stderr": proc.stderr[-MAX_READ_BYTES:], "timed_out": False}
    except subprocess.TimeoutExpired as e:
        return {"returncode": None,
                "stdout": (e.stdout or "")[-MAX_READ_BYTES:] if e.stdout else "",
                "stderr": (e.stderr or "")[-MAX_READ_BYTES:] if e.stderr else "",
                "timed_out": True, "error": f"Command timed out after {timeout}s"}


# ---------------------------------------------------------------------------
# MCP server (stdio)
# ---------------------------------------------------------------------------

mcp = FastMCP("nac-executor")


@mcp.tool()
def list_directory(path: str = ".") -> dict:
    """List files and directories under a path inside the repo."""
    target = _resolve_in_root(path)
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {target}")
    entries = []
    for entry in sorted(target.iterdir()):
        try:
            st = entry.stat()
            entries.append({"name": entry.name,
                            "type": "directory" if entry.is_dir() else "file",
                            "size_bytes": st.st_size,
                            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()})
        except OSError:
            entries.append({"name": entry.name, "type": "unknown"})
    _log("list_directory", {"path": str(target)})
    return {"path": str(target), "entries": entries}


@mcp.tool()
def read_file(path: str, max_bytes: int = MAX_READ_BYTES) -> dict:
    """Read a text file from inside the repo."""
    target = _resolve_in_root(path)
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {target}")
    if not target.is_file():
        raise IsADirectoryError(f"Path is not a file: {target}")
    max_bytes = min(max_bytes, MAX_READ_BYTES)
    data = target.read_bytes()
    truncated = len(data) > max_bytes
    content = data[:max_bytes].decode("utf-8", errors="replace")
    _log("read_file", {"path": str(target), "bytes": len(data), "truncated": truncated})
    return {"path": str(target), "content": content, "truncated": truncated, "total_bytes": len(data)}


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> dict:
    """Write (or append to) a text file inside the repo. Creates parent dirs."""
    target = _resolve_in_root(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a" if append else "w") as f:
        f.write(content)
    _log("write_file", {"path": str(target), "bytes": len(content), "append": append})
    return {"path": str(target), "bytes_written": len(content), "append": append}


@mcp.tool()
def run_command(command: str, cwd: str = ".", timeout: int = DEFAULT_COMMAND_TIMEOUT,
                authorize_destructive: bool = False) -> dict:
    """Run a shell command with cwd inside the repo. Destructive patterns are
    blocked unless authorize_destructive=True; catastrophic ones always."""
    _check_command_safety(command, authorize_destructive)
    work_dir = _resolve_in_root(cwd)
    if not work_dir.is_dir():
        raise NotADirectoryError(f"cwd is not a directory: {work_dir}")
    result = _run_subprocess(command, cwd=work_dir, timeout=timeout, shell=True)
    _log("run_command", {"command": command, "cwd": str(work_dir),
                         "authorize_destructive": authorize_destructive,
                         "returncode": result["returncode"]})
    return result


@mcp.tool()
def run_script(script_path: str, args: list[str] | None = None,
               timeout: int = DEFAULT_SCRIPT_TIMEOUT) -> dict:
    """Run a script that lives under the repo's scripts/ folder (.py -> python3,
    .sh -> bash, or an executable)."""
    target = _resolve_in_root(script_path, base=SCRIPTS_DIR)
    if not target.exists():
        raise FileNotFoundError(f"Script does not exist: {target}")
    args = args or []
    suffix = target.suffix.lower()
    if suffix == ".py":
        cmd = [sys.executable, str(target), *args]
    elif suffix == ".sh":
        cmd = ["bash", str(target), *args]
    elif os.access(target, os.X_OK):
        cmd = [str(target), *args]
    else:
        raise PermissionError(f"Script {target} is not executable and has no .py/.sh mapping.")
    result = _run_subprocess(cmd, cwd=SCRIPTS_DIR, timeout=timeout, shell=False)
    _log("run_script", {"script": str(target), "args": args, "returncode": result["returncode"]})
    return result


@mcp.tool()
def git_status(repo_path: str = ".") -> dict:
    """git status --porcelain=v1 -b for the repo (defaults to the root)."""
    repo = _resolve_in_root(repo_path)
    if not (repo / ".git").exists():
        raise FileNotFoundError(f"No .git directory found at {repo}")
    result = _run_subprocess(["git", "status", "--porcelain=v1", "-b"],
                            cwd=repo, timeout=DEFAULT_COMMAND_TIMEOUT, shell=False)
    _log("git_status", {"repo": str(repo)})
    return {"repo": str(repo), **result}


@mcp.tool()
def git_commit(repo_path: str = ".", message: str = "", add_all: bool = True) -> dict:
    """Stage (git add -A) and commit changes in the repo (defaults to the root)."""
    if not message.strip():
        raise ValueError("A non-empty commit message is required.")
    repo = _resolve_in_root(repo_path)
    if not (repo / ".git").exists():
        raise FileNotFoundError(f"No .git directory found at {repo}")
    results = {}
    if add_all:
        results["add"] = _run_subprocess(["git", "add", "-A"], cwd=repo,
                                         timeout=DEFAULT_COMMAND_TIMEOUT, shell=False)
    results["commit"] = _run_subprocess(["git", "commit", "-m", message], cwd=repo,
                                        timeout=DEFAULT_COMMAND_TIMEOUT, shell=False)
    _log("git_commit", {"repo": str(repo), "message": message, "add_all": add_all})
    return {"repo": str(repo), **results}


if __name__ == "__main__":
    mcp.run()  # stdio transport
