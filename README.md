# Sound Pocket

> 2026-09-13: Render 웹 서비스를 삭제하고 GitHub 앱/계정 권한과 Google 로그인 연결을 해제했습니다. 현재는 PC 앱으로 사용합니다. 아래 Render 배포 내용은 과거 기록입니다.

## Windows PC 앱 (권장)

각 사용자의 PC에서 직접 YouTube 다운로드와 MP3 변환을 처리하는 Windows 10/11 x64 앱입니다. Render로 영상·오디오를 전송하지 않으며 각자 PC의 인터넷을 사용합니다. Python, Node.js, FFmpeg는 실행 패키지에 포함됩니다. Microsoft Edge WebView2 Runtime이 필요합니다.

1. `SoundPocket-Windows-x64.zip` 전체를 압축 해제합니다.
2. `SoundPocket/SoundPocket.exe`를 실행합니다. `_internal` 폴더를 함께 두세요.
3. 영상 주소를 입력하고 변환 후 **MP3 다운로드**를 눌러 저장 위치를 선택합니다.

앱을 닫으면 진행 중 작업이 취소되고 정상 종료 시 임시 파일을 정리합니다. 사용자가 따로 저장한 MP3는 삭제하지 않습니다. 앱이 실행되는 동안 임시 완료 파일은 15분 보관됩니다. 강제 종료 시에는 `%LOCALAPPDATA%\\SoundPocket`에 임시 파일이 남을 수 있습니다. 서버 비용과 앱 로그인은 없습니다. YouTube의 접근 제한을 영구적으로 해제하는 기능은 아닙니다.

**실행 파일 검증:** 패키지에 포함된 Node.js와 FFmpeg를 사용해 공개 테스트 영상 `YE7VzlLtp-4`를 192kbps MP3(14,317,100바이트)로 변환하고, 로컬 HTTP 다운로드 및 전체 오디오 디코딩에 성공했습니다. 임시 작업 정리와 로컬 Host 검증·CSRF 거부도 확인했습니다.

빌드 PC에서 재생성:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements-desktop.lock
.\\.venv\\Scripts\\python.exe build_desktop.py
```

빌드 PC에는 Node.js가 필요합니다. 결과는 `dist/SoundPocket` 및 상위 `output/SoundPocket-Windows-x64.zip`입니다. 앱은 코드 서명되지 않았습니다. 구성요소 고지와 라이선스는 ZIP의 `licenses` 폴더에 포함합니다. 자세한 사용법은 `DESKTOP_README.txt`를 확인하세요.

아래는 기존 Render 웹 서비스의 설정과 진단 기록입니다. 이 웹 주소에 접속하는 것만으로 PC 앱이 실행되지는 않습니다.

비밀번호 없이 접속하는 YouTube → MP3 웹 도구입니다. 웹 화면과 변환 처리를 같은 Render 무료 서버 하나에서 실행합니다.

## 접속 URL

| 용도 | URL / 상태 |
| --- | --- |
| 기존 웹사이트 | 서비스 종료 — Render 서비스 삭제 완료 |
| 로컬 미리보기 | http://127.0.0.1:8765/ (이 PC에서만 접속 가능) |
| Render 연동 | 해제 완료 — 현재 배포 서비스 없음 |
| 비공개 소스 저장소 | [starzzangna/sound-pocket](https://github.com/starzzangna/sound-pocket) |

## 현재 배포 상태 (2026-09-13)

Render Singapore의 **Free** 웹 서비스로 배포했습니다. 비밀번호 없이 접속되며 페이지, 상태 확인, API, 정적 파일에서 HTTP 200 및 검색 제외 헤더를 확인했습니다.

**현재 Render 서버에서는 YouTube 다운로드가 제한되어 실제 변환 테스트가 실패했습니다.** 공개 테스트 영상 `YE7VzlLtp-4`는 로컬에서 192kbps MP3 생성과 다운로드에 성공했지만, Render에서는 YouTube 요청 제한 오류가 발생했습니다. 사이트 배포는 완료되었으나 온라인 변환 기능의 정상 사용은 확인되지 않았습니다. 재시도만으로 해결된다고 보장할 수 없으며, 지속되면 변환 작업을 개인 PC에서 실행하는 등 실행 환경 변경이 필요합니다. 유료 프록시나 추가 유료 서비스는 연결하지 않았습니다.

현재 서비스는 GitHub `main` 브랜치의 Dockerfile로 자동 배포됩니다. `/healthz` 상태 확인과 Render에서 생성한 `SECRET_KEY`를 사용합니다. README만 수정할 때 커밋 메시지에 `[skip render]`를 넣으면 불필요한 재배포를 건너뜁니다.

### 원인 진단 결과 (2026-09-13 20:46 KST)

진단 수정본을 배포하고 같은 공개 영상을 한 번 재검증했습니다. Render 관리 로그에서 영상 정보 API의 `HTTP Error 403: Forbidden`과 최종 `Sign in to confirm you’re not a bot` 오류를 확인했습니다. 해당 실행에는 PO Token 누락 오류가 기록되지 않았습니다. 이는 봇 확인/인증 요구를 확인한 것이며 IP 평판만이 유일한 원인이라고 확정한 것은 아닙니다. 설치된 yt-dlp `2026.08.19`는 점검 시 공식 최신 안정 버전이며 Node.js도 인식됩니다.

다운로드 도구의 원본 경고·오류는 URL 및 인증정보를 가린 뒤 Render의 비공개 Application logs에 기록합니다. 방문자에게는 봇 확인, 요청량 제한, PO Token, HTTP 403, 영상 접근 불가를 구분한 안내를 표시합니다. 요청 사이 1초, 다운로드 시작 전 5~10초 간격을 추가했지만 이번 봇 확인 오류는 해소되지 않았습니다. 자동 테스트 13개가 통과했으며 온라인 MP3 변환은 여전히 실패 상태입니다. 기존 접속 주소와 무료 플랜은 유지합니다.

## 검색 노출 제외

HTML의 `robots` 메타 태그와 모든 응답(페이지, API, MP3 파일, 오류 응답)의 `X-Robots-Tag` 헤더에 `noindex, nofollow, nosnippet, noarchive`를 적용합니다. `robots.txt`는 크롤러가 `noindex`를 읽을 수 있도록 접근을 허용합니다. 사이트맵이나 검색엔진 등록은 사용하지 않습니다.

로그인 없이 URL을 전달받아 사용하는 방식입니다. 검색 제외 지침은 이를 준수하는 검색엔진에 적용되며, 접속 권한을 인증하거나 URL의 재공유를 막지는 않습니다. README에 공유 주소를 기록하므로 GitHub 저장소는 **Private**으로 유지하세요.

참고: [Google의 noindex 안내](https://developers.google.com/search/docs/crawling-indexing/block-indexing).

## 기능

- 로그인 없이 바로 주소 입력과 변환
- 일반 YouTube / youtu.be / Shorts / YouTube Music 영상 주소 지원
- 128 / 192kbps MP3, 최대 30분, 동시에 한 작업
- 실제 다운로드 진행률, 인코딩 상태, 작업 취소, 새로고침 후 작업 복구
- 완료 파일 15분 보관, 최대 3개 완료 파일 유지. 새 작업을 만들면 가장 오래된 완료 파일이 먼저 삭제될 수 있습니다.
- 원본 최대 160MiB, 작업 폴더 최대 약 220MiB, 작업 최대 15분
- 비공개·로그인 필요 영상, 진행 중인 실시간 방송, 재생목록 전체 변환 미지원

자신이 제작했거나 다운로드·변환 권한이 있는 영상에 사용하세요. YouTube 공식 API를 사용하는 서비스는 아닙니다. YouTube 요청 제한 및 서비스 변경으로 일부 또는 전체 영상 다운로드가 실패할 수 있습니다. 우회 프록시, 사용자 쿠키 업로드 또는 로그인 정보 수집 기능은 없습니다.

## Render에 배포

1. 이 폴더의 소스 파일을 새 **비공개 GitHub 저장소**에 올립니다. `.venv`, `.runtime`, `.local.json`, `.env`는 올리지 않습니다.
2. [Render 대시보드](https://dashboard.render.com/)에서 **New → Blueprint**를 선택하고 해당 저장소를 연결합니다.
3. `render.yaml`의 웹 서비스가 **Free**, 지역이 Singapore인지 확인합니다. 유료 데이터베이스나 디스크는 만들지 않습니다.
4. 요청 위조 방지용 세션 서명 키는 자동 생성됩니다. 접속 비밀번호는 설정하지 않습니다.
5. 배포 후 표시되는 `https://…onrender.com` 주소에 접속합니다. 이 주소를 전달하면 비밀번호 없이 사용할 수 있습니다.
6. 실제 서버에서 권한이 있는 짧은 영상을 먼저 변환해 MP3 다운로드까지 확인합니다. 로컬 성공만으로 Render의 YouTube 접근 성공을 보장할 수 없습니다.

별도 도메인 구매는 필요하지 않습니다. 결제수단을 등록하지 않고 무료 플랜을 유지하면 한도 초과 시 서비스 중지 방식으로 운영할 수 있습니다. 결제수단이 이미 연결된 계정은 초과 과금 정책을 먼저 확인하세요. 이 앱은 Render의 월간 계정 사용량을 조회하거나 과금을 강제로 차단하지 않습니다.

무료 서버는 15분간 요청이 없으면 절전하며 첫 접속에 약 1분이 걸릴 수 있습니다. 절전·재시작 시 파일과 작업 상태가 사라집니다. 진행 중일 때는 화면을 열어 두세요. 무료 서버의 실제 성능·메모리 한도에서 변환 성공 여부는 배포 후 확인해야 합니다.

## Windows 로컬 실행

Python 3.12 이상과 Node.js 22 이상을 설치한 뒤 이 폴더에서:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install imageio-ffmpeg==0.6.0
.\.venv\Scripts\python.exe start_local.py
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다. 비밀번호 없이 바로 변환 화면이 열립니다. `.local.json`에는 요청 위조 방지용 서명 키가 저장되므로 공유하지 마세요. 로컬 서버는 본인 컴퓨터에서만 접속할 수 있습니다.

Linux에서는 FFmpeg와 Node.js를 설치하고 `SECRET_KEY`를 환경변수로 설정한 뒤 `python serve.py`로 실행합니다. 기본 쿠키는 HTTPS 전용입니다. 로컬 HTTP에서만 `COOKIE_SECURE=false`를 사용하세요.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/app.js
```

자동 검증은 비밀번호 없는 접근, CSRF 방어, URL 검증, 동시 작업 제한, 취소·시간초과, 스트리밍 다운로드 및 만료를 확인합니다. 오디오 테스트는 자체 생성한 테스트 톤을 실제 FFmpeg로 MP3 인코딩합니다. 이 테스트는 YouTube 네트워크 다운로드를 대신 검증하지 않습니다.

## 유지보수

서버는 반드시 **하나의 Python 프로세스**로 실행하세요. 작업 상태는 메모리에 저장되므로 여러 프로세스로 늘리면 안 됩니다. Waitress의 스레드 4개는 하나의 프로세스에서 동작합니다. 재시작 전의 오래된 임시 디렉터리도 정리합니다.

`requirements.lock`은 검증 당시 버전입니다. YouTube 변경으로 실패하기 시작하면 `yt-dlp[default]`를 업데이트한 후 검증하고 잠금 파일을 다시 생성해 재배포하세요. 임의의 외부 변환 API나 유료 프록시는 연결하지 않았습니다.

참고: [Render 무료 한도](https://render.com/docs/free), [Blueprint 설정](https://render.com/docs/blueprint-spec), [yt-dlp](https://github.com/yt-dlp/yt-dlp).
