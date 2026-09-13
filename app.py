"""Single-process, password-free MP3 conversion service."""
from __future__ import annotations

import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

from flask import Flask, jsonify, request, session, send_from_directory, Response
from werkzeug.http import dump_options_header

BASE = Path(__file__).resolve().parent
TERMINAL = {"ready", "error", "cancelled"}


def video_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("YouTube 영상 주소를 입력해 주세요.")
    value = value.strip()
    if not value.startswith(("https://", "http://")):
        value = "https://" + value
    try:
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or url.username or url.password or url.port:
            raise ValueError()
        host = (url.hostname or "").lower()
        if host == "youtu.be":
            ident = url.path.strip("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if url.path == "/watch":
                ident = parse_qs(url.query).get("v", [""])[0]
            else:
                match = re.fullmatch(r"/(?:shorts|live|embed)/([\w-]{11})/?", url.path)
                ident = match[1] if match else ""
        else:
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", ident):
            raise ValueError()
        return "https://www.youtube.com/watch?v=" + ident
    except ValueError:
        raise ValueError("재생목록이 아닌 YouTube 영상 한 개의 주소를 입력해 주세요.") from None


class ConversionManager:
    def __init__(self, root, max_seconds=1800, ttl=900, timeout=900):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_seconds, self.ttl, self.timeout = max_seconds, ttl, timeout
        self.jobs = {}
        self.active = None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.runners = set()
        self.cleaner = threading.Thread(target=self._clean_loop, daemon=True)
        self.cleaner.start()

    def _remove(self, ident):
        # IDs are generated here; never accept a client-supplied filesystem path.
        target = self.root / ident
        if target.parent != self.root or not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise ValueError("Invalid job directory")
        shutil.rmtree(target, ignore_errors=True)
        self.jobs.pop(ident, None)

    def prune(self):
        with self.lock:
            for ident, job in list(self.jobs.items()):
                if job["status"] in TERMINAL and not job["readers"] and time.time() >= job["expires_at"]:
                    self._remove(ident)
            # Remove abandoned job directories left by a process restart.
            for target in self.root.iterdir():
                if target.is_dir() and re.fullmatch(r"[a-f0-9]{32}", target.name) and target.name not in self.jobs:
                    if time.time() - target.stat().st_mtime > self.ttl:
                        self._remove(target.name)

    def _clean_loop(self):
        while not self.stop.wait(30):
            self.prune()

    def public(self, job):
        return {key: job[key] for key in ("id", "status", "progress", "title", "message", "size", "expires_at", "bitrate")}

    def latest(self):
        self.prune()
        with self.lock:
            return self.public(next(reversed(self.jobs.values()))) if self.jobs else None

    def create(self, url, bitrate):
        self.prune()
        with self.lock:
            if self.stop.is_set():
                raise ValueError("앱을 종료하고 있습니다.")
            if self.active:
                raise ValueError("이미 변환 중입니다. 현재 작업이 끝난 뒤 다시 시도해 주세요.")
            # At most three completed MP3s plus a single active job.
            finished = [j for j in self.jobs.values() if j["status"] in TERMINAL]
            while len(finished) >= 3:
                candidate = next((j for j in finished if not j["readers"]), None)
                if candidate is None:
                    raise ValueError("다운로드가 끝난 뒤 다시 시도해 주세요.")
                self._remove(candidate["id"])
                finished.remove(candidate)
            ident = secrets.token_hex(16)
            job = dict(id=ident, status="checking", progress=None, title="YouTube 영상", message="", size=0,
                       expires_at=None, bitrate=bitrate, cancel=threading.Event(), readers=0)
            self.jobs[ident] = job
            self.active = ident
            (self.root / ident).mkdir()
            runner = threading.Thread(target=self._run, args=(job, url), daemon=True)
            self.runners.add(runner)
            runner.start()
            return self.public(job)

    def shutdown(self):
        self.stop.set()
        with self.lock:
            for job in self.jobs.values():
                if job['status'] not in TERMINAL:
                    job['cancel'].set()
            runners = list(self.runners)
        for runner in runners:
            runner.join(timeout=15)
        return not any(runner.is_alive() for runner in runners)

    @staticmethod
    def terminate(proc):
        if proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=10)

    def _run(self, job, url):
        folder = self.root / job["id"]
        proc = None
        error = None
        try:
            command = [sys.executable, str(BASE / "worker.py"), url, str(folder), str(job["bitrate"]), str(self.max_seconds)]
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--worker', url, str(folder), str(job['bitrate']), str(self.max_seconds)]
            with (folder / "events.ndjson").open("w", encoding="utf-8") as events:
                worker_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
                # Sanitized worker diagnostics go to Render's private service logs.
                proc = subprocess.Popen(command, stdout=events, stderr=None, env=worker_env, start_new_session=os.name != "nt",
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                start, offset = time.monotonic(), 0
                while True:
                    if job["cancel"].is_set():
                        self.terminate(proc)
                        break
                    if time.monotonic() - start > self.timeout:
                        error = "처리 시간이 15분을 넘었습니다. 더 짧은 영상으로 다시 시도해 주세요."
                        self.terminate(proc)
                        break
                    disk_bytes = 0
                    for path in folder.iterdir():
                        try:
                            if path.is_file():
                                disk_bytes += path.stat().st_size
                        except FileNotFoundError:
                            pass  # Downloader can atomically rename a .part file.
                    if disk_bytes > 220 * 1024 * 1024:
                        error = "파일이 너무 큽니다. 더 짧은 영상으로 다시 시도해 주세요."
                        self.terminate(proc)
                        break
                    with (folder / "events.ndjson").open(encoding="utf-8") as reader:
                        reader.seek(offset)
                        while True:
                            line = reader.readline()
                            if not line or not line.endswith("\n"):
                                break
                            offset = reader.tell()
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            with self.lock:
                                for key in ("title", "progress", "message"):
                                    if key in event:
                                        job[key] = event[key]
                                if event.get("status") in {"checking", "downloading", "converting"}:
                                    job["status"] = event["status"]
                                if event.get("status") == "error":
                                    error = event["message"]
                    if proc.poll() is not None:
                        break
                    time.sleep(0.4)
            output = folder / "audio.mp3"
            with self.lock:
                job["expires_at"] = time.time() + self.ttl
                if job["cancel"].is_set():
                    job.update(status="cancelled", message="변환을 취소했습니다.")
                elif error or proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
                    job.update(status="error", message=error or "변환에 실패했습니다. 잠시 후 다른 영상으로 시도해 주세요.")
                else:
                    job.update(status="ready", progress=100, size=output.stat().st_size, message="MP3 파일을 저장해 주세요.")
        except Exception:
            logging.getLogger(__name__).exception("Conversion supervisor failed")
            if proc is not None:
                self.terminate(proc)
            with self.lock:
                job["expires_at"] = time.time() + self.ttl
                job.update(status="error", message="변환을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        finally:
            with self.lock:
                job["expires_at"] = time.time() + self.ttl
                self.active = None
            for path in folder.iterdir():
                if path.is_file() and (path.name != "audio.mp3" or job["status"] != "ready"):
                    path.unlink(missing_ok=True)
            with self.lock:
                self.runners.discard(threading.current_thread())


def create_app(config=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY"),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() != "false",
                      MAX_CONTENT_LENGTH=4096,
                      JOB_ROOT=os.environ.get("JOB_ROOT", str(BASE / ".runtime" / "jobs")))
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("Set SECRET_KEY to a random secret of at least 32 characters.")
    manager = ConversionManager(app.config["JOB_ROOT"])
    app.extensions["conversions"] = manager

    def payload():
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else {}

    @app.before_request
    def protect():
        if app.config.get('DESKTOP_MODE') and request.host.split(':')[0] != '127.0.0.1':
            return jsonify(error='허용되지 않은 주소입니다.'), 403
        if not request.path.startswith("/api/"):
            return None
        if request.method == "POST":
            token = request.headers.get("X-CSRF-Token", "")
            if not token or not hmac.compare_digest(token, session.get("csrf", "")):
                return jsonify(error="페이지를 새로고침한 뒤 다시 시도해 주세요."), 403

    @app.after_request
    def headers(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, nosnippet, noarchive"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/robots.txt")
    def robots():
        # Crawlers must be able to read noindex; Disallow: / can hide that rule.
        return Response("User-agent: *\nAllow: /\n", mimetype="text/plain")

    @app.get("/api/session")
    def session_info():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return jsonify(csrf=session["csrf"],
                       max_minutes=manager.max_seconds // 60, retention_minutes=manager.ttl // 60,
                       desktop=bool(app.config.get('DESKTOP_MODE')))

    @app.get("/api/jobs")
    def latest():
        return jsonify(job=manager.latest())

    @app.post("/api/jobs")
    def convert():
        data = payload()
        try:
            url = video_url(data.get("url"))
            bitrate = data.get("bitrate", 192)
            if type(bitrate) is not int or bitrate not in {128, 192}:
                raise ValueError("128 또는 192kbps를 선택해 주세요.")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        try:
            return jsonify(job=manager.create(url, bitrate)), 202
        except ValueError as exc:
            return jsonify(error=str(exc)), 409

    @app.get("/api/jobs/<ident>")
    def status(ident):
        manager.prune()
        with manager.lock:
            job = manager.jobs.get(ident)
            if not job:
                return jsonify(error="파일 보관 시간이 지났거나 서버가 다시 시작되었습니다. 다시 변환해 주세요."), 404
            return jsonify(job=manager.public(job))

    @app.post("/api/jobs/<ident>/cancel")
    def cancel(ident):
        with manager.lock:
            job = manager.jobs.get(ident)
            if not job:
                return jsonify(error="작업을 찾을 수 없습니다."), 404
            if job["status"] not in TERMINAL:
                job["cancel"].set()
            return {"ok": True}

    @app.get("/api/jobs/<ident>/download")
    def download(ident):
        manager.prune()
        with manager.lock:
            job = manager.jobs.get(ident)
            if not job or job["status"] != "ready":
                return jsonify(error="다운로드할 파일이 없습니다. 다시 변환해 주세요."), 404
            try:
                handle = (manager.root / ident / "audio.mp3").open("rb")
            except FileNotFoundError:
                return jsonify(error="파일이 만료되었습니다. 다시 변환해 주세요."), 404
            job["readers"] += 1
            name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "", job["title"]).strip(" .")[:100] or "audio"
            size = job["size"]
        closed = False

        def close():
            nonlocal closed
            if not closed:
                closed = True
                handle.close()
                with manager.lock:
                    job["readers"] -= 1

        def chunks():
            try:
                while chunk := handle.read(64 * 1024):
                    yield chunk
            finally:
                close()

        from urllib.parse import quote
        response = Response(chunks(), mimetype="audio/mpeg")
        response.content_length = size
        response.headers["Content-Disposition"] = dump_options_header("attachment", {"filename": "audio.mp3", "filename*": "UTF-8''" + quote(name + ".mp3")})
        response.call_on_close(close)
        return response

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="입력 내용이 너무 깁니다."), 413

    return app
