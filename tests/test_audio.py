"""Network-independent: synthetic WAV input, real FFmpeg MP3 encoder."""
import contextlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import worker


def ffmpeg_path():
    found = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not found:
        try:
            import imageio_ffmpeg
            found = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    return found


class AudioTests(unittest.TestCase):
    def test_upstream_errors_are_distinguished(self):
        for message, code in [("Sign in to confirm you're not a bot", 'bot_check'),
                              ('HTTP Error 429', 'rate_limit'), ('missing PO Token', 'po_token'),
                              ('HTTP Error 403', 'forbidden'), ('Video unavailable', 'unavailable')]:
            self.assertEqual(worker.download_error(message)[0], code)

    def test_diagnostics_redact_signed_urls_and_credentials(self):
        with contextlib.redirect_stderr(io.StringIO()) as output:
            worker.diagnostic('HTTP 403 https://example.com/audio?sig=secret cookie=secret po_token=secret')
        self.assertIn('HTTP 403', output.getvalue())
        self.assertNotIn('secret', output.getvalue())
        self.assertNotIn('example.com', output.getvalue())

    @unittest.skipUnless(ffmpeg_path(), "FFmpeg is required for actual MP3 encoding")
    def test_synthetic_audio_is_encoded_and_decodable(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "source.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                wav.writeframes(b"".join(struct.pack("<h", int(7000 * math.sin(2 * math.pi * 440 * n / 44100))) for n in range(44100)))
            with patch.dict(os.environ, {"FFMPEG_BINARY": ffmpeg_path()}), patch("worker.yt_dlp.YoutubeDL") as downloader, contextlib.redirect_stdout(io.StringIO()) as events:
                instance = downloader.return_value.__enter__.return_value
                instance.extract_info.return_value = {"title": "직접 생성한 테스트 톤", "duration": 1}
                instance.prepare_filename.return_value = str(source)
                worker.run("https://www.youtube.com/watch?v=BaW_jenozKc", folder, 192, 1800)
            output = folder / "audio.mp3"
            self.assertGreater(output.stat().st_size, 1000)
            result = subprocess.run([ffmpeg_path(), "-v", "error", "-i", str(output), "-f", "null", "-"], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("converting", [json.loads(line).get("status") for line in events.getvalue().splitlines()])

    def test_long_or_live_video_rejected_before_download(self):
        for info in ({"duration": 1801}, {"duration": 10, "is_live": True}, {"title": "no duration"}):
            with self.subTest(info=info), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"FFMPEG_BINARY": "test-ffmpeg"}), patch("worker.yt_dlp.YoutubeDL") as downloader:
                instance = downloader.return_value.__enter__.return_value
                instance.extract_info.return_value = info
                with self.assertRaises(ValueError):
                    worker.run("unused", directory, 192, 1800)
                instance.process_info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
