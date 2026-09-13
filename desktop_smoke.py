"""Run meaningful smoke checks inside the shipped executable, without opening a window."""
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import wave

import requests


def verify(report_path, data_dir, test_video=None):
    from desktop import start_service, stop_service
    result = {'ok': False}
    app, server, session_dir, base = start_service(data_dir)
    try:
        node = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        result['node'] = node.stdout.strip()
        with requests.Session() as client:
            client.trust_env = False
            assert client.get(base, timeout=10).status_code == 200
            assert client.get(base, headers={'Host': 'evil.example'}, timeout=10).status_code == 403
            session = client.get(base + '/api/session', timeout=10).json()
            assert session['desktop'] is True
            assert client.post(base + '/api/jobs', json={}, timeout=10).status_code == 403
            result['loopback_and_csrf'] = True
            # Actual encoder bundled in ZIP, without requiring YouTube availability.
            source = session_dir / 'tone.wav'
            audio = session_dir / 'tone.mp3'
            with wave.open(str(source), 'wb') as wav:
                wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                wav.writeframes(b''.join(struct.pack('<h', int(7000 * math.sin(2 * math.pi * 440 * n / 44100))) for n in range(44100)))
            subprocess.run([os.environ['FFMPEG_BINARY'], '-v', 'error', '-i', str(source), '-b:a', '192k', str(audio)],
                           capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            assert audio.stat().st_size > 1000
            result['encoded_bytes'] = audio.stat().st_size
            if test_video:
                response = client.post(base + '/api/jobs', json={'url': test_video, 'bitrate': 192},
                                       headers={'X-CSRF-Token': session['csrf']}, timeout=10)
                response.raise_for_status()
                job = response.json()['job']
                for _ in range(300):
                    time.sleep(2)
                    job = client.get(base + '/api/jobs/' + job['id'], timeout=10).json()['job']
                    if job['status'] in ('ready', 'error', 'cancelled'):
                        break
                result['video_job'] = job
                assert job['status'] == 'ready', job['message']
                response = client.get(base + '/api/jobs/' + job['id'] + '/download', timeout=60)
                response.raise_for_status()
                saved = report_path.with_suffix('.mp3')
                saved.write_bytes(response.content)
                assert len(response.content) == job['size']
                subprocess.run([os.environ['FFMPEG_BINARY'], '-v', 'error', '-i', str(saved), '-f', 'null', '-'],
                               capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                result['download_and_decode'] = True
        result['ok'] = True
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        stop_service(app, server, session_dir, data_dir)
        result['session_cleaned'] = not session_dir.exists()
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
