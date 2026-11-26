"""Spawn the Claude Code CLI headless for a single turn and normalize its
stream-json output into simple events the web layer can persist + broadcast.

Process model: one `claude -p` process per user turn. The first turn creates the
session with --session-id <uuid>; later turns continue it with --resume <uuid>.
"""
import asyncio
import json
import os
import shlex
import shutil
import sys
from typing import AsyncIterator, Optional

# Resolve the CLI binary once. On Windows the global install is a `.cmd` shim,
# which must be launched through cmd.exe; on Linux (Docker) it's a plain binary.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"

# --- Human-in-the-loop: gate file-modifying tools through a PreToolUse hook ---
_HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_SCRIPT = os.path.join(_HERE, "approve_hook.py")
if os.name == "nt":
    _HOOK_CMD = f'"{sys.executable}" "{HOOK_SCRIPT}"'
else:
    _HOOK_CMD = f"{shlex.quote(sys.executable)} {shlex.quote(HOOK_SCRIPT)}"

_HOOK_SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                "hooks": [
                    {"type": "command", "command": _HOOK_CMD, "timeout": 1800}
                ],
            }
        ]
    }
}


def _flatten(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif "text" in b:
                    parts.append(str(b["text"]))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    return json.dumps(content, ensure_ascii=False)


def _normalize(obj: dict) -> list:
    """Turn one stream-json object into zero or more normalized events."""
    t = obj.get("type")
    out: list = []

    if t == "stream_event":
        ev = obj.get("event") or {}
        if ev.get("type") == "content_block_delta":
            d = ev.get("delta") or {}
            if d.get("type") == "text_delta" and d.get("text"):
                out.append({"type": "delta", "text": d["text"]})

    elif t == "assistant":
        msg = obj.get("message") or {}
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                out.append({"type": "assistant_text", "text": block["text"]})
            elif block.get("type") == "tool_use":
                out.append({
                    "type": "tool",
                    "uid": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input"),
                })

    elif t == "user":
        msg = obj.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out.append({
                        "type": "tool_result",
                        "uid": block.get("tool_use_id"),
                        "output": _flatten(block.get("content")),
                        "status": "error" if block.get("is_error") else "done",
                    })

    elif t == "result":
        out.append({
            "type": "result",
            "ok": not obj.get("is_error"),
            "text": obj.get("result") or "",
            "duration_ms": obj.get("duration_ms"),
            "num_turns": obj.get("num_turns"),
        })

    return out


async def run_turn(
    workdir: str,
    sid: str,
    prompt: str,
    resume: bool,
    model: Optional[str] = None,
    run=None,
) -> AsyncIterator[dict]:
    args = [
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--dangerously-skip-permissions",
    ]
    if resume:
        args += ["--resume", sid]
    else:
        args += ["--session-id", sid]
    if model:
        args += ["--model", model]
    # Load the approval hook for this turn.
    args += ["--settings", json.dumps(_HOOK_SETTINGS)]

    if os.name == "nt" and CLAUDE_BIN.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", CLAUDE_BIN, *args]
    else:
        argv = [CLAUDE_BIN, *args]

    env = os.environ.copy()
    env.setdefault("WORKBENCH_INTERNAL_URL", "http://127.0.0.1:8000")

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=workdir,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield {"type": "error", "message": "claude CLI not found on PATH"}
        return

    if run is not None:
        run.proc = proc

    # Feed the prompt via stdin (avoids shell quoting / argument length limits).
    try:
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
    except Exception:
        pass

    stderr_task = asyncio.create_task(proc.stderr.read())
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                # Non-JSON diagnostic lines (e.g. warnings) are ignored.
                continue
            for ev in _normalize(obj):
                yield ev
    finally:
        rc = await proc.wait()
        err = b""
        try:
            err = await asyncio.wait_for(stderr_task, timeout=5)
        except Exception:
            pass
        if run is not None:
            run.proc = None
        if rc != 0:
            msg = (err or b"").decode("utf-8", "replace").strip()[-2000:] or f"claude exited with code {rc}"
            yield {"type": "error", "message": msg}
