"""Windows desktop entry point; bundled worker runs in an isolated child process."""
import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import threading


def configure_tools():
    import imageio_ffmpeg
    os.environ['FFMPEG_BINARY'] = imageio_ffmpeg.get_ffmpeg_exe()
    bundled = Path(__file__).resolve().parent / 'tools' / 'node.exe'
    if bundled.is_file():
        os.environ['PATH'] = str(bundled.parent) + os.pathsep + os.environ.get('PATH', '')
    if not shutil.which('node'):
        raise RuntimeError('Node.js가 없습니다. 배포 ZIP 전체를 다시 압축 해제해 주세요.')


def worker_entry():
    # Windowed executables do not have stdout/stderr, even when redirected.
    folder = Path(sys.argv[3])
    sys.stdout = (folder / 'events.ndjson').open('w', encoding='utf-8', buffering=1)
    sys.stderr = (folder / 'errors.log').open('w', encoding='utf-8', buffering=1)
    configure_tools()
    sys.argv = ['worker.py', *sys.argv[2:]]
    import worker
    return worker.main()


def start_service(data_dir):
    from app import create_app
    from waitress import create_server
    data_dir.mkdir(parents=True, exist_ok=True)
    # Each app instance owns an isolated job directory and random session key.
    session_dir = Path(tempfile.mkdtemp(prefix='session-', dir=data_dir))
    app = create_app({'SECRET_KEY': secrets.token_urlsafe(48), 'SESSION_COOKIE_SECURE': False,
                      'DESKTOP_MODE': True, 'JOB_ROOT': str(session_dir / 'jobs')})
    server = create_server(app, host='127.0.0.1', port=0, threads=4, max_request_body_size=4096)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return app, server, session_dir, f'http://127.0.0.1:{server.effective_port}'


def stop_service(app, server, session_dir, data_dir):
    stopped = app.extensions['conversions'].shutdown()
    server.close()
    # Never delete a supplied directory: only our own generated child session.
    if stopped and session_dir.resolve().parent == data_dir.resolve() and session_dir.name.startswith('session-'):
        shutil.rmtree(session_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--smoke-test', type=Path, help='Write packaged runtime verification JSON and exit')
    parser.add_argument('--test-video', help='Optional public test video URL for smoke test')
    args = parser.parse_args()
    data_dir = args.data_dir or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SoundPocket'
    data_dir.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = (data_dir / 'app.log').open('w', encoding='utf-8', buffering=1)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    configure_tools()
    if args.smoke_test:
        from desktop_smoke import verify
        verify(args.smoke_test, data_dir, args.test_video)
        return
    import webview
    app, server, session_dir, url = start_service(data_dir)
    try:
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['ALLOW_FILE_URLS'] = False
        webview.create_window('Sound Pocket · 내 PC에서 MP3 변환', url, width=960, height=920,
                              min_size=(520, 720), background_color='#f6f7fb', text_select=True)
        webview.start(gui='edgechromium', private_mode=True)
    finally:
        stop_service(app, server, session_dir, data_dir)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        raise SystemExit(worker_entry())
    try:
        main()
    except Exception as exc:
        logging.exception('Desktop startup failed')
        if '--smoke-test' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,
                '앱을 시작하지 못했습니다. ZIP 전체를 압축 해제했는지 확인해 주세요.\n'
                'Microsoft Edge WebView2 Runtime이 필요합니다.\n\n' + str(exc), 'Sound Pocket', 0x10)
        raise SystemExit(1)
