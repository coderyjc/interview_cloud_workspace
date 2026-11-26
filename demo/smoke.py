#!/usr/bin/env python3
"""Headless smoke test: exercises the whole workbench API without a browser.

Usage:
    python3 demo/smoke.py            # against http://localhost:8000
    BASE=http://localhost:8000 python3 demo/smoke.py

It creates a code-dev session and a daily-task session, uploads a sample
material, waits for the agent to finish each turn, and prints the transcript
and the files produced in each workspace.
"""
import json
import os
import sys
import time
import urllib.request
import uuid

BASE = os.environ.get("BASE", "http://localhost:8000")


def req(method, path, data=None, headers=None):
    body = None
    h = dict(headers or {})
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        else:
            body = json.dumps(data).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace"))
        raise


def multipart(path, filename, content):
    boundary = "----wb" + uuid.uuid4().hex
    data = content.encode("utf-8") if isinstance(content, str) else content
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/plain\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return req("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def wait_idle(sid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = req("GET", f"/api/sessions/{sid}")
        if s.get("status") != "running":
            return s
        time.sleep(2)
    return req("GET", f"/api/sessions/{sid}")


def dump(sid):
    s = req("GET", f"/api/sessions/{sid}")
    print(f"\n=== transcript {sid} (status={s['status']}) ===")
    for m in s["messages"]:
        if m["type"] == "text":
            txt = (m.get("text") or "").replace("\n", " ")
            print(f"[{m['role']}] {txt[:300]}")
        elif m["type"] == "tool":
            t = m["tool"]
            print(f"[tool] {t['name']} -> {t['status']}")
    files = req("GET", f"/api/sessions/{sid}/files")
    print("=== files ===")
    for f in files:
        print(f"  - {f['path']} ({f['size']} bytes)")
    if not files:
        print("  (none)")


def main():
    print("health:", req("GET", "/api/health"))

    # ---- scenario A: code development ----
    dev = req("POST", "/api/sessions", {"kind": "dev"})
    print("\n[dev] created session", dev["id"])
    req("POST", f"/api/sessions/{dev['id']}/messages", {"content": (
        "在当前目录写一个 Python 小工具 csv2md.py，把 CSV 文件转换成 Markdown 表格；"
        "另外写一个测试 test_csv2md.py，写完后用 python 运行测试并确认通过。"
    )})
    wait_idle(dev["id"])
    dump(dev["id"])

    # ---- scenario B: daily task with uploaded material ----
    daily = req("POST", "/api/sessions", {"kind": "daily"})
    print("\n[daily] created session", daily["id"])
    multipart(
        f"/api/sessions/{daily['id']}/files",
        "meeting.txt",
        "会议记录\n- 项目 A 延期两周\n- 预算增加 10%\n- 下周五安排评审\n- 负责人：张三、李四\n",
    )
    req("POST", f"/api/sessions/{daily['id']}/messages", {"content": (
        "阅读当前目录下的 meeting.txt，整理成一份结构化的中文报告 report.md，"
        "包含：概述、关键结论、待办事项。写完后确认文件已生成。"
    )})
    wait_idle(daily["id"])
    dump(daily["id"])

    print("\nSmoke test finished.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
