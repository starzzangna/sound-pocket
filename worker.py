"""Isolated downloader + encoder. stdout is a small JSON event stream."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

import yt_dlp

MAX_SOURCE_BYTES = 160 * 1024 * 1024


def diagnostic(message):
    # Keep the upstream reason, but never log signed media URLs or credentials.
    message = re.sub(r'https?://\S+', '[URL]', str(message))
    message = re.sub(r'(?i)(cookie|authorization|po_token|visitor_data)\s*[:=]\s*\S+', r'\1=[REDACTED]', message)
    message = re.sub(r'\x1b\[[0-9;]*m', '', message)
    print('[downloader] ' + message.replace('\n', ' ').replace('\r', ' ')[:3000], file=sys.stderr, flush=True)


def download_error(message):
    message = message.lower()
    if 'confirm' in message and 'bot' in message:
        return 'bot_check', 'YouTube가 서버에 봇 확인을 요구했습니다. 운영자의 다운로드 환경 점검이 필요합니다.'
    if '429' in message or 'rate limit' in message:
        return 'rate_limit', 'YouTube 요청 횟수 제한에 도달했습니다. 반복 요청을 멈추고 나중에 다시 시도해 주세요.'
    if 'po token' in message or 'po_token' in message:
        return 'po_token', 'YouTube 다운로드 검증 설정을 업데이트해야 합니다. 운영자에게 알려 주세요.'
    if '403' in message:
        return 'forbidden', 'YouTube가 다운로드 접근을 거부했습니다. 운영자의 원인 확인이 필요합니다.'
    if any(term in message for term in ('private', 'unavailable', 'sign in', 'age-restricted', 'age restricted', 'confirm your age')):
        return 'unavailable', '이 영상에 접근할 수 없습니다. 로그인 없이 볼 수 있는 공개 영상을 선택해 주세요.'
    return 'download_failed', 'YouTube에서 영상을 받지 못했습니다. 주소를 확인하거나 운영자에게 알려 주세요.'


def emit(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def run(url, folder, bitrate, max_seconds):
    folder = Path(folder)
    ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("변환 도구가 설치되어 있지 않습니다. 운영자에게 알려 주세요.")
    last = [0.0]

    def progress(info):
        if info.get("downloaded_bytes", 0) > MAX_SOURCE_BYTES:
            raise ValueError("파일이 너무 큽니다. 더 짧은 영상으로 시도해 주세요.")
        now = time.monotonic()
        if now - last[0] < 1 and info["status"] != "finished":
            return
        last[0] = now
        total = info.get("total_bytes") or info.get("total_bytes_estimate")
        percent = min(100, round(info.get("downloaded_bytes", 0) / total * 100)) if total else None
        emit(status="downloading", progress=percent)

    def filter_video(info, *, incomplete=False):
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            return "실시간 방송은 변환할 수 없습니다."
        duration = info.get("duration")
        if duration is None and not incomplete:
            return "영상 길이를 확인할 수 없습니다. 다른 영상을 선택해 주세요."
        if duration is not None and duration > max_seconds:
            return "30분 이하 영상만 변환할 수 있습니다."
        return None

    class QuietLogger:
        def debug(self, message): pass
        def warning(self, message): diagnostic(message)
        def error(self, message): diagnostic(message)

    options = dict(format="bestaudio/best[height<=360]", outtmpl=str(folder / "source.%(ext)s"),
                   noplaylist=True, quiet=True, logger=QuietLogger(),
                   socket_timeout=20, retries=2, fragment_retries=2, concurrent_fragment_downloads=1,
                   max_filesize=MAX_SOURCE_BYTES, match_filter=filter_video, progress_hooks=[progress],
                   cachedir=False, restrictfilenames=True, js_runtimes={"node": {}},
                   sleep_interval=5, max_sleep_interval=10, sleep_interval_requests=1,
                   skip_unavailable_fragments=False)
    diagnostic('yt-dlp=' + yt_dlp.version.__version__ + ' node=' + str(bool(shutil.which('node'))))
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
        if not info:
            raise ValueError("영상 정보를 가져오지 못했습니다.")
        rejected = filter_video(info)
        if rejected:
            raise ValueError(rejected)
        emit(status="downloading", title=str(info.get("title") or "audio")[:200], progress=None)
        downloader.process_info(info)
        source = Path(downloader.prepare_filename(info))
        if not source.is_file():
            raise ValueError("원본 파일을 받지 못했습니다. 파일 크기 제한 또는 영상의 공개 상태를 확인해 주세요.")
    emit(status="converting", progress=None)
    result = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                             "-vn", "-map_metadata", "-1", "-threads", "1", "-c:a", "libmp3lame",
                             "-b:a", f"{bitrate}k", "-t", str(max_seconds), str(folder / "audio.mp3")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=780)
    if result.returncode:
        raise ValueError("MP3 인코딩에 실패했습니다. 다른 영상으로 다시 시도해 주세요.")


def main():
    try:
        run(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    except ValueError as exc:
        emit(status="error", message=str(exc))
        return 1
    except subprocess.TimeoutExpired:
        emit(status="error", message="변환 시간이 너무 길어 중지했습니다. 더 짧은 영상으로 시도해 주세요.")
        return 1
    except yt_dlp.utils.DownloadError as exc:
        code, readable = download_error(str(exc))
        diagnostic('category=' + code + ' ' + str(exc))
        emit(status="error", message=readable)
        return 1
    except Exception as exc:
        diagnostic(type(exc).__name__ + ': ' + str(exc))
        emit(status="error", message="변환 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
