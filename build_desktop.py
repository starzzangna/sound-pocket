"""Build the Windows x64 portable app using the active build virtualenv."""
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent


def main():
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js is required on the build machine')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir',
                    '--name', 'SoundPocket', '--add-data', str(ROOT / 'static') + ':static',
                    '--add-binary', node + ':tools', '--collect-all', 'yt_dlp',
                    '--collect-all', 'yt_dlp_ejs', '--collect-all', 'imageio_ffmpeg',
                    '--hidden-import', 'webview.platforms.edgechromium',
                    '--exclude-module', 'pytest', '--exclude-module', 'tkinter',
                    str(ROOT / 'desktop.py')], cwd=ROOT, check=True)
    bundle = ROOT / 'dist' / 'SoundPocket'
    shutil.copy2(ROOT / 'DESKTOP_README.txt', bundle / '사용방법.txt')
    notices = bundle / 'licenses'
    notices.mkdir(exist_ok=True)
    # Include license texts shipped by Python dependencies and Node.
    import importlib.metadata as metadata
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        for file in dist.files or []:
            if any(term in file.name.lower() for term in ('license', 'copying', 'notice')) and '.dist-info' in str(file):
                origin = Path(dist.locate_file(file))
                if origin.is_file():
                    target = notices / name / file.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, target)
    node_license = Path(node).parent / 'LICENSE'
    if node_license.exists():
        shutil.copy2(node_license, notices / 'NODE_LICENSE.txt')
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.md', notices / 'THIRD_PARTY_NOTICES.md')
    for name in ('NODE_LICENSE.txt', 'FFMPEG_GPLv3.txt', 'PYTHON_LICENSE.txt'):
        shutil.copy2(ROOT / name, notices / name)
    archive = ROOT.parent / 'output' / 'SoundPocket-Windows-x64.zip'
    archive.parent.mkdir(exist_ok=True)
    with ZipFile(archive, 'w', ZIP_DEFLATED) as z:
        for file in bundle.rglob('*'):
            if file.is_file():
                z.write(file, 'SoundPocket/' + file.relative_to(bundle).as_posix())
    print(archive, flush=True)


if __name__ == '__main__':
    main()
