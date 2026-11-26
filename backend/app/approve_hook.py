#!/usr/bin/env python3
"""PreToolUse hook for file-modifying tools and shell write operations.

- File tools (Write/Edit/MultiEdit/NotebookEdit): always ask the workbench.
- Bash: only ask when the command looks like it writes/modifies something;
  read-only inspection commands (ls/cat/grep/...) pass straight through.

The workbench backend surfaces a review modal in the browser and blocks until
the user decides. Exit 0 = allow, exit 2 = block (stderr is fed to the model).
"""
import json
import os
import re
import sys
import urllib.request

# --- heuristic: does a Bash command write / modify anything? -----------------
_WRITE_CMDS = {
    "rm", "mv", "cp", "mkdir", "rmdir", "touch", "chmod", "chown", "ln",
    "truncate", "dd", "tee", "mkfifo", "mknod", "unzip", "zip", "tar",
    "gzip", "gunzip", "install", "patch", "rsync",
}
_INTERP = {
    "python", "python3", "node", "nodejs", "ruby", "perl", "php", "sh", "bash",
    "zsh", "dash", "source", "eval", "make", "go", "cargo", "gradle", "mvn",
    "pytest", "black", "isort", "prettier",
}
_PKG = {"pip", "pip3", "npm", "yarn", "pnpm", "apt", "apt-get", "apk", "brew", "poetry", "conda", "uv"}
_SEP = re.compile(r"\|\||&&|\||;|\n")
_REDIR = re.compile(r"(?<![-=])>>?\s*([^\s;&|<>]+)")


def _redirect_writes(cmd: str) -> bool:
    for m in _REDIR.finditer(cmd):
        tgt = m.group(1)
        if tgt.startswith("&") or tgt == "/dev/null":
            continue
        return True
    return False


def _segments(cmd: str):
    return [p.strip() for p in _SEP.split(cmd) if p.strip()]


def _first_word(seg: str) -> str:
    toks = seg.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t) or t in ("sudo", "env", "time", "nohup", "command", "nice"):
            i += 1
            continue
        break
    return os.path.basename(toks[i]) if i < len(toks) else ""


def bash_is_write(cmd: str) -> bool:
    if not cmd:
        return False
    if _redirect_writes(cmd):
        return True
    for seg in _segments(cmd):
        w = _first_word(seg)
        if not w:
            continue
        if w in _WRITE_CMDS or w in _INTERP:
            return True
        if w == "sed" and re.search(r"\s-[A-Za-z]*i", seg):
            return True
        if w == "git" and re.search(
            r"\bgit\b.*\s(add|commit|mv|rm|reset|checkout|restore|clean|apply|stash|pull|clone|merge|rebase|init|push|tag|switch|am)\b",
            seg,
        ):
            return True
        if w in _PKG and re.search(r"\b(install|add|remove|uninstall|update|upgrade|sync|get)\b", seg):
            return True
        if w in ("curl", "wget") and re.search(r"\s(-o|-O)\b", seg):
            return True
        if w == "find" and re.search(r"\s-(exec|execdir|delete)\b", seg):
            return True
        if w == "xargs":
            return True
        if w in ("ruff", "eslint") and re.search(r"(--fix|--write)\b", seg):
            return True
    return False


def ask_backend(data: dict) -> tuple:
    base = os.environ.get("WORKBENCH_INTERNAL_URL", "http://127.0.0.1:8000")
    payload = {
        "session_id": data.get("session_id"),
        "tool_name": data.get("tool_name"),
        "tool_input": data.get("tool_input") or {},
        "cwd": data.get("cwd") or "",
    }
    try:
        req = urllib.request.Request(
            base + "/internal/approval",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1800) as resp:
            out = json.load(resp)
            return out.get("decision", "deny"), out.get("reason", "")
    except Exception as e:  # fail safe
        return "deny", f"审批服务异常，已拒绝: {e}"


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on malformed payload

    if data.get("tool_name") == "Bash":
        cmd = (data.get("tool_input") or {}).get("command", "")
        if not bash_is_write(cmd):
            sys.exit(0)  # read-only shell command, allow

    decision, reason = ask_backend(data)
    if decision == "allow":
        sys.exit(0)
    sys.stderr.write(reason or "用户拒绝了本次操作")
    sys.exit(2)


if __name__ == "__main__":
    main()
