import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app import create_app, video_url

URL = "https://www.youtube.com/watch?v=BaW_jenozKc"


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "s" * 48,
                               "SESSION_COOKIE_SECURE": False, "JOB_ROOT": self.temp.name})
        self.client = self.app.test_client()
        self.manager = self.app.extensions["conversions"]
        self.csrf = self.client.get("/api/session").json["csrf"]

    def tearDown(self):
        self.manager.stop.set()
        self.manager.cleaner.join(timeout=2)
        self.temp.cleanup()

    def post(self, path, data):
        return self.client.post(path, json=data, headers={"X-CSRF-Token": self.csrf})

    def make_ready(self):
        ident = "a" * 32
        folder = Path(self.temp.name) / ident
        folder.mkdir()
        content = b"ID3" + b"test audio" * 10000
        (folder / "audio.mp3").write_bytes(content)
        job = dict(id=ident, status="ready", title="테스트 / 오디오", progress=100, message="",
                   size=len(content), expires_at=time.time() + 900, bitrate=192, readers=0,
                   cancel=threading.Event())
        self.manager.jobs[ident] = job
        return job, content

    def test_works_without_password_and_preserves_csrf(self):
        self.assertEqual(self.client.get("/api/jobs").status_code, 200)
        self.assertEqual(self.client.post("/api/jobs", json={"url": URL}).status_code, 403)
        with patch.object(self.manager, "_run"):
            self.assertEqual(self.post("/api/jobs", {"url": URL}).status_code, 202)
        job, content = self.make_ready()
        response = self.app.test_client().get(f'/api/jobs/{job["id"]}/download')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, content)
        response.close()
        with self.client.get("/") as page:
            self.assertNotIn(b'type="password"', page.data)

    def test_untrusted_urls_and_invalid_quality_rejected(self):
        for url in ("http://127.0.0.1", "https://youtube.com.evil.example/watch?v=BaW_jenozKc", "file:///etc/passwd", "https://youtube.com@evil.example/watch?v=BaW_jenozKc", "https://youtube.com:443/watch?v=BaW_jenozKc", "https://youtube.com/playlist?list=abc", "--exec calc", None):
            with self.subTest(url=url):
                self.assertEqual(self.post("/api/jobs", {"url": url}).status_code, 400)
        self.assertEqual(self.post("/api/jobs", {"url": URL, "bitrate": "192;whoami"}).status_code, 400)

    def test_url_canonicalization_discards_playlists_and_other_options(self):
        for url in (URL + "&list=abc&t=20", "youtu.be/BaW_jenozKc?si=abc", "https://m.youtube.com/shorts/BaW_jenozKc", "https://music.youtube.com/watch?v=BaW_jenozKc"):
            self.assertEqual(video_url(url), URL)

    def test_only_one_conversion_at_a_time_and_cancellation(self):
        with patch.object(self.manager, "_run"):
            first = self.post("/api/jobs", {"url": URL, "bitrate": 128})
            self.assertEqual(first.status_code, 202)
            self.assertEqual(self.post("/api/jobs", {"url": URL}).status_code, 409)
            ident = first.json["job"]["id"]
            self.assertEqual(self.post(f"/api/jobs/{ident}/cancel", {}).status_code, 200)
            self.assertTrue(self.manager.jobs[ident]["cancel"].is_set())

    def test_download_stream_filename_and_expiry(self):
        job, content = self.make_ready()
        response = self.client.get(f'/api/jobs/{job["id"]}/download', buffered=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "audio/mpeg")
        self.assertIn("filename*=UTF-8''", response.headers["Content-Disposition"])
        self.assertEqual(job["readers"], 1)
        job["expires_at"] = 0
        self.manager.prune()
        self.assertIn(job["id"], self.manager.jobs, "Do not delete a file while streaming it")
        self.assertEqual(response.data, content)
        response.close()
        self.assertEqual(job["readers"], 0)
        self.manager.prune()
        self.assertNotIn(job["id"], self.manager.jobs)
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/download').status_code, 404)

    def test_unknown_job_does_not_expose_files(self):
        self.assertEqual(self.client.get("/api/jobs/not-a-real-id/download").status_code, 404)
        self.assertEqual(self.client.get("/.local.json").status_code, 404)
        self.assertEqual(self.client.get("/static/../.local.json").status_code, 404)

    def test_bad_payload_and_security_headers(self):
        self.assertEqual(self.post("/api/jobs", []).status_code, 400)
        self.assertEqual(self.post("/api/jobs", {"url": "x" * 5000}).status_code, 413)
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        response.close()

    def test_process_timeout_releases_queue_and_cleans_partial_file(self):
        with patch.object(self.manager, "_run"):
            job_data = self.manager.create(URL, 192)
        job = self.manager.jobs[job_data["id"]]
        (Path(self.temp.name) / job["id"] / "source.part").write_bytes(b"partial")
        self.manager.timeout = -1
        with patch("app.subprocess.Popen") as fake, patch.object(self.manager, "terminate") as terminate:
            self.manager._run(job, URL)
            terminate.assert_called_once_with(fake.return_value)
        self.assertIsNone(self.manager.active)
        self.assertEqual(job["status"], "error")
        self.assertIn("15분", job["message"])
        self.assertEqual(list((Path(self.temp.name) / job["id"]).iterdir()), [])

    def test_missing_configuration_fails_closed(self):
        with self.assertRaises(RuntimeError):
            create_app({"SECRET_KEY": "short"})


if __name__ == "__main__":
    unittest.main()
