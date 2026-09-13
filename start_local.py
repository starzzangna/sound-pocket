"""Local preview only. Generates a private ignored configuration on first run."""
import json
import os
from pathlib import Path
import secrets
from waitress import serve
from app import create_app

if __name__ == "__main__":
    config_path = Path(__file__).with_name(".local.json")
    if not config_path.exists():
        config_path.write_text(json.dumps({"SECRET_KEY": secrets.token_urlsafe(48)}), encoding="utf-8")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.pop("APP_PASSWORD", None) is not None:
        config_path.write_text(json.dumps(config), encoding="utf-8")
    config["SESSION_COOKIE_SECURE"] = False
    if not os.environ.get("FFMPEG_BINARY"):
        try:
            import imageio_ffmpeg
            os.environ["FFMPEG_BINARY"] = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    print("Sound Pocket: http://127.0.0.1:8765", flush=True)
    serve(create_app(config), host="127.0.0.1", port=8765, threads=4)
