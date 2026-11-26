"""FastAPI web layer for the cloud Agent workbench.

- REST for sessions / files
- One WebSocket per open session for live streaming + subscribe replay
- SQLite (stdlib) is the source of truth for the transcript shown in the UI
"""
import asyncio
import json
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .runner import run_turn

# ----------------------------------------------------------------------------
# Config / paths
# ----------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
WORKSPACES = DATA_DIR / "workspaces"
CLAUDE_DIR = DATA_DIR / "claude"
DB_PATH = DATA_DIR / "app.db"
MODEL = os.environ.get("ANTHROPIC_MODEL") or None
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_RUNS", "4"))
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT_SECONDS", "1800"))
STATIC_DIR = Path(os.environ.get("STATIC_DIR", "./static")).resolve()

WORKSPACES.mkdir(parents=True, exist_ok=True)
CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
# Keep Claude's own session store (used for --resume) inside the data volume.
if "CLAUDE_CONFIG_DIR" not in os.environ:
    os.environ["CLAUDE_CONFIG_DIR"] = str(CLAUDE_DIR)

# ----------------------------------------------------------------------------
# SQLite helpers (single-user demo: one connection per call + a global lock)
# ----------------------------------------------------------------------------
_db_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _db_lock:
        conn = _connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions(
              id TEXT PRIMARY KEY,
              title TEXT,
              kind TEXT,
              status TEXT DEFAULT 'idle',
              claude_started INTEGER DEFAULT 0,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS messages(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT,
              seq INTEGER,
              role TEXT,
              type TEXT,
              tool_uid TEXT,
              payload TEXT,
              created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msg ON messages(session_id, seq);
            CREATE INDEX IF NOT EXISTS idx_tool ON messages(session_id, tool_uid);
            """
        )
        conn.commit()
        conn.close()


init_db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_session(sid: str) -> Optional[dict]:
    with _db_lock:
        conn = _connect()
        row = conn.execute("select * from sessions where id=?", (sid,)).fetchone()
        conn.close()
        return dict(row) if row else None


def _preview(row) -> str:
    if not row:
        return ""
    p = json.loads(row["payload"] or "{}")
    if row["type"] == "text":
        return p.get("text", "")[:120]
    if row["type"] == "tool":
        return f"[tool] {p.get('name', '')}"
    return ""


def list_sessions() -> list:
    with _db_lock:
        conn = _connect()
        rows = conn.execute("select * from sessions order by updated_at desc").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            last = conn.execute(
                "select payload, type from messages where session_id=? order by seq desc limit 1",
                (d["id"],),
            ).fetchone()
            d["last"] = _preview(last)
            out.append(d)
        conn.close()
        return out


def _msg_row(r) -> dict:
    p = json.loads(r["payload"] or "{}")
    m = {"seq": r["seq"], "role": r["role"], "type": r["type"]}
    if r["type"] == "text":
        m["text"] = p.get("text", "")
    elif r["type"] == "tool":
        m["tool"] = {
            "id": p.get("id"),
            "name": p.get("name"),
            "input": p.get("input"),
            "status": p.get("status"),
            "output": p.get("output"),
        }
    return m


def fetch_messages(sid: str, after: int = 0) -> list:
    with _db_lock:
        conn = _connect()
        rows = conn.execute(
            "select * from messages where session_id=? and seq>? order by seq",
            (sid, after),
        ).fetchall()
        conn.close()
        return [_msg_row(r) for r in rows]


def insert_message(sid: str, role: str, type_: str, payload: dict, tool_uid: Optional[str] = None) -> int:
    with _db_lock:
        conn = _connect()
        seq = conn.execute(
            "select coalesce(max(seq),0)+1 from messages where session_id=?", (sid,)
        ).fetchone()[0]
        conn.execute(
            "insert into messages(session_id,seq,role,type,tool_uid,payload,created_at) values(?,?,?,?,?,?,?)",
            (sid, seq, role, type_, tool_uid, json.dumps(payload, ensure_ascii=False), _now()),
        )
        conn.execute("update sessions set updated_at=? where id=?", (_now(), sid))
        conn.commit()
        conn.close()
        return seq


def update_tool(sid: str, tool_uid: str, output: str, status: str):
    with _db_lock:
        conn = _connect()
        row = conn.execute(
            "select seq,payload from messages where session_id=? and tool_uid=? order by seq desc limit 1",
            (sid, tool_uid),
        ).fetchone()
        if not row:
            conn.close()
            return None
        p = json.loads(row["payload"] or "{}")
        p["output"] = output
        p["status"] = status
        conn.execute(
            "update messages set payload=? where session_id=? and seq=?",
            (json.dumps(p, ensure_ascii=False), sid, row["seq"]),
        )
        conn.commit()
        seq = row["seq"]
        conn.close()
        return seq, p


def set_status(sid: str, status: str) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute("update sessions set status=? where id=?", (status, sid))
        conn.commit()
        conn.close()


# ----------------------------------------------------------------------------
# Run registry + WebSocket subscribers
# ----------------------------------------------------------------------------
class Conn:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.q: asyncio.Queue = asyncio.Queue()
        self.task: Optional[asyncio.Task] = None

    async def send_loop(self):
        while True:
            ev = await self.q.get()
            if ev is None:
                break
            try:
                await self.ws.send_json(ev)
            except Exception:
                break


class Run:
    def __init__(self, sid: str, prompt: str):
        self.sid = sid
        self.prompt = prompt
        self.proc = None
        self.cancelled = False
        self.task: Optional[asyncio.Task] = None


runs: dict[str, Run] = {}
subs: dict[str, set[Conn]] = {}


async def broadcast(sid: str, event: dict) -> None:
    for conn in list(subs.get(sid, ())):
        conn.q.put_nowait(event)


async def execute_turn(run: Run) -> None:
    sid = run.sid
    sess = get_session(sid) or {}
    workdir = str(WORKSPACES / sid)
    resume = bool(sess.get("claude_started"))

    timeout_task = None
    if RUN_TIMEOUT > 0:
        async def _timeout():
            await asyncio.sleep(RUN_TIMEOUT)
            if run.proc is not None:
                run.cancelled = True
                try:
                    run.proc.terminate()
                except ProcessLookupError:
                    pass
        timeout_task = asyncio.create_task(_timeout())

    try:
        async for ev in run_turn(workdir, sid, run.prompt, resume, MODEL, run=run):
            t = ev["type"]
            if t == "delta":
                await broadcast(sid, {"type": "delta", "text": ev["text"]})
            elif t == "assistant_text":
                seq = insert_message(sid, "assistant", "text", {"text": ev["text"]})
                await broadcast(sid, {"type": "message", "message": {
                    "seq": seq, "role": "assistant", "type": "text", "text": ev["text"]}})
            elif t == "tool":
                tf = {"id": ev["uid"], "name": ev["name"], "input": ev["input"],
                      "status": "running", "output": None}
                seq = insert_message(sid, "assistant", "tool", tf, tool_uid=ev["uid"])
                await broadcast(sid, {"type": "message", "message": {
                    "seq": seq, "role": "assistant", "type": "tool", "tool": tf}})
            elif t == "tool_result":
                res = update_tool(sid, ev["uid"], ev["output"], ev["status"])
                if res:
                    seq, p = res
                    await broadcast(sid, {"type": "tool_update", "seq": seq, "tool": {
                        "id": p.get("id"), "name": p.get("name"), "input": p.get("input"),
                        "status": p.get("status"), "output": p.get("output")}})
            elif t == "result":
                await broadcast(sid, {"type": "result", "result": {
                    "ok": ev.get("ok"), "duration_ms": ev.get("duration_ms"),
                    "num_turns": ev.get("num_turns")}})
            elif t == "error":
                if not run.cancelled:
                    await broadcast(sid, {"type": "error", "error": ev["message"]})
    except Exception as e:  # never leave the session stuck in "running"
        if not run.cancelled:
            await broadcast(sid, {"type": "error", "error": f"internal error: {e}"})
    finally:
        if timeout_task:
            timeout_task.cancel()
        with _db_lock:
            conn = _connect()
            conn.execute(
                "update sessions set claude_started=1, status='idle', updated_at=? where id=?",
                (_now(), sid),
            )
            conn.commit()
            conn.close()
        runs.pop(sid, None)
        await broadcast(sid, {"type": "session_status", "status": "idle",
                              "cancelled": run.cancelled})


# ----------------------------------------------------------------------------
# FastAPI app + REST
# ----------------------------------------------------------------------------
app = FastAPI(title="Cloud Agent Workbench")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class NewSession(BaseModel):
    kind: str = "dev"
    title: Optional[str] = None


class NewMessage(BaseModel):
    content: str


@app.get("/api/health")
def health():
    return {"ok": True, "model": MODEL, "runs": len(runs)}


@app.post("/api/sessions")
def create_session(body: NewSession):
    sid = str(uuid.uuid4())
    (WORKSPACES / sid).mkdir(parents=True, exist_ok=True)
    title = body.title or ("代码开发会话" if body.kind == "dev" else "日常任务会话")
    with _db_lock:
        conn = _connect()
        conn.execute(
            "insert into sessions(id,title,kind,status,claude_started,created_at,updated_at) "
            "values(?,?,?,?,?,?,?)",
            (sid, title, body.kind, "idle", 0, _now(), _now()),
        )
        conn.commit()
        conn.close()
    return get_session(sid)


@app.get("/api/sessions")
def get_sessions():
    out = list_sessions()
    for s in out:
        if s["id"] in runs:
            s["status"] = "running"
    return out


@app.get("/api/sessions/{sid}")
def get_session_detail(sid: str):
    s = get_session(sid)
    if not s:
        raise HTTPException(404, "session not found")
    if sid in runs:
        s["status"] = "running"
    s["messages"] = fetch_messages(sid, 0)
    return s


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str):
    run = runs.get(sid)
    if run and run.proc is not None:
        run.cancelled = True
        try:
            run.proc.terminate()
        except ProcessLookupError:
            pass
    with _db_lock:
        conn = _connect()
        conn.execute("delete from messages where session_id=?", (sid,))
        conn.execute("delete from sessions where id=?", (sid,))
        conn.commit()
        conn.close()
    shutil.rmtree(WORKSPACES / sid, ignore_errors=True)
    return {"ok": True}


@app.get("/api/sessions/{sid}/messages")
def get_messages(sid: str, after: int = Query(0)):
    return fetch_messages(sid, after)


@app.post("/api/sessions/{sid}/messages")
async def post_message(sid: str, body: NewMessage):
    if not get_session(sid):
        raise HTTPException(404, "session not found")
    if sid in runs:
        raise HTTPException(409, "session is busy; cancel or wait")
    if len(runs) >= MAX_CONCURRENT:
        raise HTTPException(429, "too many concurrent runs")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, "empty message")

    seq = insert_message(sid, "user", "text", {"text": content})
    await broadcast(sid, {"type": "message", "message": {
        "seq": seq, "role": "user", "type": "text", "text": content}})

    set_status(sid, "running")
    await broadcast(sid, {"type": "session_status", "status": "running"})

    run = Run(sid, content)
    runs[sid] = run
    run.task = asyncio.create_task(execute_turn(run))
    return {"ok": True, "seq": seq}


@app.post("/api/sessions/{sid}/cancel")
async def cancel_run(sid: str):
    run = runs.get(sid)
    if run and run.proc is not None:
        run.cancelled = True
        try:
            run.proc.terminate()
        except ProcessLookupError:
            pass
    return {"ok": True}


# ----------------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------------
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".claude", ".mypy_cache"}


@app.get("/api/sessions/{sid}/files")
def list_files(sid: str):
    base = WORKSPACES / sid
    if not base.exists():
        return []
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            fp = Path(root) / f
            rel = str(fp.relative_to(base)).replace("\\", "/")
            try:
                size = fp.stat().st_size
            except OSError:
                size = 0
            out.append({"path": rel, "name": f, "size": size})
    out.sort(key=lambda x: x["path"])
    return out


@app.post("/api/sessions/{sid}/files")
async def upload_file(sid: str, file: UploadFile = File(...)):
    if not get_session(sid):
        raise HTTPException(404, "session not found")
    base = WORKSPACES / sid
    base.mkdir(parents=True, exist_ok=True)
    name = os.path.basename(file.filename or "upload.bin")
    dest = base / name
    data = await file.read()
    dest.write_bytes(data)
    return {"path": name, "name": name, "size": len(data)}


@app.get("/api/sessions/{sid}/files/download")
def download_file(sid: str, path: str = Query(...)):
    base = (WORKSPACES / sid).resolve()
    target = (base / path).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(403, "path not allowed")
    if not target.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(str(target), filename=target.name)


# ----------------------------------------------------------------------------
# WebSocket per session
# ----------------------------------------------------------------------------
@app.websocket("/ws/{sid}")
async def ws_endpoint(ws: WebSocket, sid: str):
    await ws.accept()
    conn = Conn(ws)
    conn.task = asyncio.create_task(conn.send_loop())
    subs.setdefault(sid, set()).add(conn)
    try:
        sess = get_session(sid)
        status = "running" if sid in runs else (sess["status"] if sess else "idle")
        conn.q.put_nowait({"type": "session_status", "status": status})
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "subscribe":
                after = int(msg.get("after_seq") or 0)
                for m in fetch_messages(sid, after):
                    conn.q.put_nowait({"type": "message", "message": m})
            elif mtype == "cancel":
                run = runs.get(sid)
                if run and run.proc is not None:
                    run.cancelled = True
                    try:
                        run.proc.terminate()
                    except ProcessLookupError:
                        pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        subs.get(sid, set()).discard(conn)
        conn.q.put_nowait(None)
        try:
            await conn.task
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Static frontend (production build). Mounted last so /api and /ws win.
# ----------------------------------------------------------------------------
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
