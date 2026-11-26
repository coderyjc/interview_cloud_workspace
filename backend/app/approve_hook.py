#!/usr/bin/env python3
"""PreToolUse hook for file-modifying tools.

Claude Code invokes this script before running Write/Edit/MultiEdit/NotebookEdit.
We forward the tool call to the workbench backend, which surfaces a review modal
in the browser and blocks until the user decides. Exit 0 = allow, exit 2 = block
(stderr is fed back to the model).
"""
import json
import os
import sys
import urllib.request


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        # Never block on a malformed payload.
        sys.exit(0)

    base = os.environ.get("WORKBENCH_INTERNAL_URL", "http://127.0.0.1:8000")
    payload = {
        "session_id": data.get("session_id"),
        "tool_name": data.get("tool_name"),
        "tool_input": data.get("tool_input") or {},
        "cwd": data.get("cwd") or "",
    }

    decision = "deny"
    reason = "审批服务不可达，已拒绝本次修改"
    try:
        req = urllib.request.Request(
            base + "/internal/approval",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1800) as resp:
            out = json.load(resp)
            decision = out.get("decision", "deny")
            reason = out.get("reason", "")
    except Exception as e:  # fail safe
        decision, reason = "deny", f"审批服务异常，已拒绝本次修改: {e}"

    if decision == "allow":
        sys.exit(0)

    sys.stderr.write(reason or "用户拒绝了本次文件修改")
    sys.exit(2)


if __name__ == "__main__":
    main()
