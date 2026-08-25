r"""AutoMM 非侵入式实时监测服务（只读，localhost）。

只读观测 harness 状态、任务、资产与日志；绝不写任何文件、不 import automm、不抢锁。
启动：<venv>\Scripts\python.exe monitor\monitor.py
浏览：http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(os.environ.get("AUTOMM_ROOT", Path(__file__).resolve().parents[1])).resolve()
MONITOR_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765

IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
TEXT_EXT = {".md", ".yaml", ".yml", ".json", ".txt", ".py", ".csv", ".log"}


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _read_yaml(path: Path, default=None):
    if yaml is None or not path.exists():
        return default if default is not None else {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return default if default is not None else {}


def _tail(path: Path, n: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


def _state():
    return _read_json(ROOT / "runtime" / "workflow_state.json")


def api_state() -> dict:
    state = _state()
    compute = _read_yaml(ROOT / "config" / "compute.yaml")
    runtime = _read_yaml(ROOT / "config" / "agent_runtime.yaml")
    workflow = _read_yaml(ROOT / "config" / "workflow.yaml")
    tasks = api_tasks()
    backends = {t.get("backend") for t in tasks if t.get("backend")}
    default_backend = str(compute.get("default_backend", "local")).lower()
    compute_mode = "remote" if (default_backend in {"ssh", "kaggle"} or "ssh" in backends or "kaggle" in backends) else "local"
    return {
        "control": state.get("control", "?"),
        "recovery_status": state.get("recovery_status", "normal"),
        "problem_id": state.get("active_problem"),
        "question": state.get("current_question"),
        "stage": state.get("current_stage"),
        "mode": {"compute": compute_mode, "llm": str(runtime.get("provider", "unknown"))},
        "stages": list(workflow.get("stages", [])),
        "warnings": state.get("warnings", []),
        "blocking": state.get("blocking", []),
        "last_action": state.get("last_action"),
        "updated_at": state.get("updated_at"),
    }


def api_tasks() -> list[dict]:
    root = ROOT / "runtime" / "tasks"
    out: list[dict] = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        spec = _read_json(d / "task.json")
        status = _read_json(d / "status.json")
        out.append({
            "task_id": d.name,
            "problem_id": spec.get("problem_id") or status.get("problem_id"),
            "question_id": spec.get("question_id") or status.get("question_id"),
            "stage": status.get("stage") or spec.get("stage"),
            "backend": status.get("backend") or spec.get("backend", "local"),
            "status": status.get("status", "?"),
            "attempt": status.get("attempt", 1),
        })
    return out


def api_tree() -> dict:
    state = _state()
    pid = state.get("active_problem")
    problems = ROOT / "problems"
    base = problems / pid if pid else problems
    IGNORE = {"__pycache__", ".ruff_cache", ".venv"}

    def walk(p: Path, depth: int = 0):
        if depth > 8:
            return None
        if p.is_dir():
            children = []
            for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if c.name in IGNORE or c.name.endswith(".pyc"):
                    continue
                node = walk(c, depth + 1)
                if node is not None:
                    children.append(node)
            return {"name": p.name, "type": "dir", "path": str(p.relative_to(ROOT).as_posix()), "children": children}
        ext = p.suffix.lower()
        return {"name": p.name, "type": "file", "path": str(p.relative_to(ROOT).as_posix()),
                "ext": ext, "children": None}

    if not base.exists():
        return {"name": pid or "problems", "type": "dir", "path": "problems", "children": []}
    return walk(base)


def api_file(rel: str) -> dict | None:
    try:
        target = (ROOT / rel).resolve()
    except Exception:
        return None
    if ROOT != target and ROOT not in target.parents:
        return None
    if not target.is_file():
        return None
    ext = target.suffix.lower()
    if ext in IMAGE_EXT:
        return {"path": rel, "name": target.name, "type": "image", "ext": ext}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return {"path": rel, "name": target.name, "type": "text", "ext": ext, "content": content}


def api_events(n: int) -> list[dict]:
    out: list[dict] = []
    for line in _tail(ROOT / "runtime" / "events.jsonl", n):
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"raw": line})
    return out


def api_log(n: int) -> list[str]:
    return _tail(ROOT / "runtime" / "daemon" / "daemon.log", n)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

    def _file(self, path: Path, ctype: str):
        self._send(path.read_bytes(), ctype)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/":
                return self._file(MONITOR_DIR / "index.html", "text/html; charset=utf-8")
            if path == "/ascii-art-text.png":
                return self._file(MONITOR_DIR / "ascii-art-text.png", "image/png")
            if path == "/api/state":
                return self._json(api_state())
            if path == "/api/tasks":
                return self._json(api_tasks())
            if path == "/api/tree":
                return self._json(api_tree())
            if path == "/api/file":
                rel = (qs.get("path") or [""])[0]
                data = api_file(rel)
                return self._json({"error": "not found or forbidden"}, 404) if data is None else self._json(data)
            if path == "/raw":
                rel = (qs.get("path") or [""])[0]
                try:
                    target = (ROOT / rel).resolve()
                except Exception:
                    return self._json({"error": "bad path"}, 400)
                if ROOT != target and ROOT not in target.parents:
                    return self._json({"error": "forbidden"}, 403)
                if not target.is_file():
                    return self._json({"error": "not found"}, 404)
                ext = target.suffix.lower()
                return self._file(target, IMAGE_EXT.get(ext, "application/octet-stream"))
            if path == "/api/events":
                return self._json(api_events(int((qs.get("n") or ["50"])[0])))
            if path == "/api/log":
                return self._json(api_log(int((qs.get("n") or ["50"])[0])))
            return self._json({"error": "not found"}, 404)
        except Exception as exc:  # pragma: no cover
            return self._json({"error": str(exc)}, 500)

    def log_message(self, *args):  # 静默，不刷屏
        pass


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AutoMM monitor running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()