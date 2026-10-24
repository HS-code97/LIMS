# 도금강판 R&D LIMS v2.3

`lims_master_design_v2.3.md`(마스터 설계서) 11.1 로드맵의 **1단계 MVP + 2단계 확장 + 3단계 고도화**를 구현한 코드입니다.
FastAPI + SQLAlchemy 2.0 + Jinja2/HTMX/Alpine.js, 빌드 도구 없음(D-17, D-18).

## 빠른 실행 (Windows 개발 PC)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd lims
..\.venv\Scripts\python.exe -m scripts.demo      # 기준 시나리오(11.2) 데모 데이터 + 시드
cd ..
.\run_dev.ps1                                     # http://localhost:8610
```

개발용 계정(`--demo` 시드 전용, `lims/scripts/seed.py`): `hhs` / `lims1234`(관리자), `kim` / `lims1234`, `admin` / `admin1234`.
이 계정은 개발용 SQLite에서만 만들어지고, 운영 시드(`--demo` 없이)는 만들지 않습니다.

개발 DB는 `lims/var/lims.db`(SQLite)이며, 파일은 `lims/var/files/{yyyy}/{각인번호}/`에 저장됩니다(이관 전에 올린 파일은 옛 번호 폴더에 그대로 있고, DB가 경로를 기억합니다).

## 테스트

```powershell
cd lims
..\.venv\Scripts\python.exe -m pytest
```

| 파일 | 내용 |
| :--- | :--- |
| `tests/test_units.py` | 번호 발급·조건부·파일명 파서·템플릿 검증 (4.3절 "필수" 단위 테스트) |
| `tests/test_scenario.py` | **11.2 기준 시나리오 1~7단계**, 시리즈 실험, 욕 분석 적용 |
| `tests/test_web.py` | 로그인, 26개 화면 렌더링, 10장 API 흐름(409·422 포함), Excel·CSV·PDF |
| `tests/test_phase23.py` | 템플릿 편집(버전), 엑셀 가져오기(미리보기·저장·충돌), 허용편차 편집, PV CSV 수신, X-cut 연동, PPT, 산점도·뷰어, 폴더 감시 |
| `tests/test_pg_dialect.py` | PostgreSQL 방언 DDL·재귀 CTE·검색 질의 컴파일 |
| `tests/test_deploy.py` | 배포 전 점검: 테스트 격리, requirements 누락, 비밀키·운영 시드 계정, 첨부 내려받기 헤더, 감사 로그(사용자·행 번호) |
| `tests/test_integrity.py` | 데이터 정확성: 시리즈 기준값, 번호 999 이후, 폐기·소진 상태 규칙, NaN·길이 거부, 409/422 응답, 대상별 권한, 대표값 = 가장 최근 측정(D-37) |
| `tests/test_ops.py` | 운영: 폴더 감시 장애 격리·크기 안정 판정, 수집 실패 시 고아 파일 정리, Alembic 마이그레이션 = 모델 |
| `tests/test_features.py` | 장비 API 키(범위·중지), PV 재전송 대체, 목표 정정(각인 ≠ 현재), 첨부·시편 되살리기, 로그인 리다이렉트·실패 제한 |

PostgreSQL에서 같은 테스트를 돌리려면 빈 테스트 DB를 만들고 `LIMS_TEST_DATABASE_URL=postgresql+psycopg://…/lims_test`를 준 뒤 `pytest`를 실행합니다.
이 개발 PC에는 PostgreSQL이 없어(설치하지 않기로 함) SQLite 실행 + PostgreSQL 방언 컴파일 + 오프라인 마이그레이션 SQL(`lims/db/migration_0001_postgres.sql`)까지 확인했습니다.

## 운영 배포 (회사 Docker 컨테이너, PostgreSQL 15+)

1. `/opt/lims`에 이 폴더(저장소 루트)를 두고 `/opt/lims/.venv`에 가상환경과 `requirements.txt`를 설치합니다. 앱 패키지는 `/opt/lims/lims/app`입니다.
2. `lims/deploy/lims.env.example`을 `/opt/lims/.env`로 복사해 DB 비밀번호·`LIMS_SECRET_KEY`·백업 경로를 채웁니다.
   `LIMS_SECRET_KEY`는 `python -c "import secrets; print(secrets.token_urlsafe(48))"`로 만듭니다.
   PostgreSQL에서는 키가 없거나 32자 미만이거나 예시 값이면 앱이 기동을 거부합니다(세션 쿠키 위조 방지).
3. 스키마: `cd lims && alembic upgrade head` (검토용 DDL은 `lims/db/schema_postgres.sql`, `python -m scripts.dump_ddl`로 다시 생성).
   마이그레이션별 SQL은 `lims/db/migration_000N_postgres.sql`입니다. `0002`는 관리 화면 실측 설정 테이블(`param_actual_cfg`)과 `serial_no` 숫자 검사를, `0003`은 장비 API 키(`api_keys`)를 더하고, `0004`는 시편번호 체계 v3.0(각인번호·단계 A~E·과제 `A6`·코일코드)으로 바꾸며 기존 데이터를 이관합니다(옛 번호는 `legacy_id`로 계속 조회). `0005`는 각인번호를 v3.1(`QV3-102-01-3` → `QV3-A02-A-3`, 구간 경계마다 영문·숫자 교대)로, 분석런 번호를 `TR-` → `AR-`로 바꿉니다(옛 `TR-` 번호도 검색·주소에서 찾힘). `0004`·`0005`의 데이터 이관은 온라인 `alembic upgrade head`에서만 돕니다.
   **업그레이드 순서:** 코드를 바꾼 뒤 서버를 다시 띄우기 전에 `alembic upgrade head`를 실행하세요. 테이블이 없으면 모든 요청이 실패합니다.
   DB 시간대: `ALTER DATABASE lims SET timezone = 'Asia/Seoul';` (기록 시각 기본값 `now()`가 KST가 되도록)
4. 기준 정보: `python -m scripts.seed` — 관리자가 아직 없으면 첫 관리자 사번·비밀번호(10자 이상)를 묻습니다.
   터미널이 아니면 `LIMS_ADMIN_EMP_NO`·`LIMS_ADMIN_PASSWORD`를 이 명령에만 넘기고 `.env`에는 남기지 마세요.
   개발 계정을 만드는 `--demo`는 SQLite가 아니면 거부합니다.
5. 상시 구동: `lims/deploy/supervisord.conf` (`.env`를 export한 셸에서 supervisord 실행).
   백업: `0 2 * * * /opt/lims/lims/scripts/backup.sh >> /data/backup/backup.log 2>&1` (7장 P8).
   - 스크립트가 `.env`에서 백업 위치·DB 비밀번호를 직접 읽습니다.
   - 백업 위치가 없거나 덤프가 깨졌거나 원본 파일 폴더가 비어 있으면 실패(exit 1)합니다. cron 메일이나 로그로 확인하세요.
   - 마지막 성공 시각은 `/data/backup/db/last_success`에 남습니다.
   - 컨테이너에 cron이 없으면 호스트(컨테이너 밖) 스케줄러에서 `docker exec`로 같은 명령을 부릅니다.
   - 복원 연습(월 1회 권장): `lims/scripts/restore_check.sh`. 최신 덤프를 임시 DB에 복원해 행 수를 보여 주고 지웁니다.
   - 관리 화면에서 고친 허용편차·대표값 계산법은 DB에 저장되므로, DB 덤프에 함께 백업됩니다.
6. 사내망이 CDN을 막으면 `htmx.min.js`(1.9.12), `alpine.min.js`(3.14.1)를 `lims/app/static/vendor/`에 두면 그 파일을 씁니다. 글꼴은 없으면 맑은 고딕·Consolas로 대체됩니다.

## 설계서 대응

| 설계서 | 구현 위치 |
| :--- | :--- |
| 3장 시편번호 → **v3.1 [`시편번호 체계.md`](시편번호%20체계.md)**: 각인번호 `QV3-A02-A-3`(유일키 `short_id`, 구간 경계마다 영문·숫자 교대), 전체번호 `QV3-A6-C-A02-A-M206K`, 단계 A~E, 입고·자르기·도금·공정, 다음 빈 번호 제안·충돌 검사 | `services/marking.py`, `services/numbering.py`, `services/workflow.py`, `models/lineage.py`, `alembic/versions/0004`·`0005` |
| 3.2 조건부 5자 (원판 단위·목표 기준, 실측 기준은 표시만) — v3.0에서 전체번호 꼬리의 도금 블록 | `services/condition_code.py`, `services/actuals.actual_condition_code` |
| 3.3 과제코드 → v3.0: 그해 등록 순서 영문 + 연도 끝자리 (`A6`, `B6` …), 공용 `X6/Y6/Z6` | `services/marking.next_project_code`, `routers/admin.project_code_for`, `scripts/seed.py` |
| 3.6 각인 CSV·라벨 PDF (각인·DataMatrix = 각인번호, 라벨에 전체번호) | `services/export.py`, `/api/labels/engrave.csv`, `/api/labels/print.pdf` |
| 5장 화면 6개 | `templates/home · process_run_new/detail · specimen_detail · test_run_detail · search · admin` |
| 6.1 HMI 재사용 (사전 단일 원본, cycle/checks/drawMimic 공통 모듈) | `data/seed/param_dictionary.json`, `static/hmi/hmi-core.js`, `static/hmi/hmi-lims.js` |
| 6.2 프리셋 3단계·지난 공정런 복제 | `routers/presets.py`, 공정런 등록 화면 |
| 6.3~6.4 저장 페이로드·서버 처리 순서 (범위 재검증 → 시리즈 → 조건부 → 409 → 한 트랜잭션) | `services/workflow.create_process_run` |
| 6.6~6.8 목표·실측 이중 기록, 대표값 규칙, 4경로(수기·욕 분석·분석런 `maps_to`·PV API) | `services/actuals.py`, `param_actuals`, `effective_params` |
| 6.9 시리즈 실험 (원판별 `target_overrides`, ◆/● 구분) | `workflow.series_overrides`, 시리즈 설정 대화상자 |
| 6.10 목표 정정 (사유 필수, 전체번호 꼬리의 조건부 재생성, 각인번호 유지) | `workflow.correct_targets`, `refresh_condition_codes`, 공정런 화면 [목표 정정] |
| 7장 P1~P8 | `services/workflow.py`, `file_ingest.py`, `lineage.py`, `search.py`, `export.py`, `workers/watcher.py`, `scripts/backup.sh`, `scripts/restore_check.sh` |
| 8장 DDL·운영 규칙 (논리 삭제·되살리기, RESTRICT, 감사 로그, 저장 직전 값 검사, 대상별 권한표, API 키, 배포 기본값) | `models/`, `models/audit.py`, `models/guards.py`, `auth.py`, `config.py`, `alembic/versions/0001~0004` |
| 9장 분석 템플릿 9종 (JSON 시드, 템플릿 외 키 저장 거부) | `data/seed/test_templates/*.json`, `services/templates_engine.py` |
| 10장 API | `routers/*.py` (개발 서버 `/docs`에서 확인, 운영은 `LIMS_API_DOCS=1`일 때만) |

화면 디자인은 Stitch로 만든 디자인 시스템("Plated Steel LIMS — Lab Instrument")과 화면 시안(`design/stitch/`: 01 시편 상세, 03 분석런(옛 시험런) 그리드, 04 공정런 등록)을 기준으로 합니다. 공정런 등록은 설계서 6.1절대로 원본 HMI 미믹·열사이클을 유지하고 그 주변 배치(상단 한 줄, 구간 요약 칩, 변경 행 강조, 하단 확정 패널)를 시안에서 가져왔습니다. Stitch 출력은 Tailwind CDN 기반이라, 빌드 도구 없이(D-18) 사내망에서 돌도록 같은 토큰·배치를 `static/css/lims.css`로 옮겼습니다.

## 설계서와 다르게 정한 점 (0단계 확정 필요)

- **소둔 코드 K의 이슬점 기준을 −30 → −40 °C로 맞춤.** 부록 D 초안(K = DP −30 ±5)으로는 11.2 시나리오(이슬점 목표 −40·실측 −36에서 `M206K` → `M205K`)가 나오지 않습니다. 그래서 부록 D 마지막 문장의 선택지("HMI 기본값에 맞춤")를 따랐습니다. M(극저이슬점)은 K와 겹치지 않도록 −55로 두었습니다. `data/seed/master_codes.json` 또는 관리 > 코드표에서 바꿀 수 있습니다.
- **실측 기준 단면 부착량 = 윗면·아랫면 실측 중 작은 값.** 11.2의 `M205K`(윗면 54·아랫면 58)와 맞추려고 정한 규칙입니다. `condition_code.specimen_code`에서 바꿀 수 있습니다.
- M1·M2 프리셋의 욕 조성(Al 잔부 71/70.5, Si 3, Mg 0/0.5)과 욕온 590 °C는 부록 B를 근거로 한 추정값입니다.
- 설계서 DDL에 없지만 화면 구현에 필요해 추가한 컬럼: `process_runs.warnings`·`coating_system`, `specimens.note`, `test_runs.cycles`(그리드 열 수).
- 사전에 `aka`(별칭) 필드를 추가했습니다. 예: `ak.P` = "나이프 압력". 엑셀 붙여넣기 머리글을 인식하는 데 씁니다.

2026-10-23 리뷰에서 정한 권한표, 폐기·소진 상태 규칙, 번호 발급, 대표값 규칙 등은 설계서 v2.3 본문(6.4·6.10·7·8장)과 결정 이력 D-37~D-49에 반영했으므로 여기서는 다루지 않습니다.

## 2·3단계 (설계서 11.1)

| 단계 | 기능 | 위치 |
| :--- | :--- | :--- |
| 2 | 분석 템플릿 편집 화면 (새 버전 생성, 키·maps_to 검증) | 관리 > 분석 템플릿 > 편집 · `routers/templates_admin.py` |
| 2 | 장비 PC 폴더 감시 (안정 대기, 중복 방지, 진행 중 분석런 회차 자동 연결) | `app/workers/watcher.py`, supervisord `lims-watcher` |
| 2 | 과거 엑셀 일괄 가져오기 (입고·전단·공정런·분기·실측·분석결과, 한 트랜잭션, 미리보기) | 관리 > 엑셀 가져오기 · `scripts/import_excel.py` |
| 2 | 태블릿 화면 (터치 44px, 셀 편집기 세로 배치, 카메라 촬영 → 셀 자동 첨부) | `static/css/lims.css` `pointer:coarse`, 셀 편집기 |
| 3 | HMI PV 실행기록 수신 (CSV → pv_tag로 구간 평균·최소·최대, 원본 보관) | `POST /api/process-runs/{run_no}/pv` · `services/pv.py` |
| 3 | 목표–실측 산점도 (허용편차 띠) | `/analysis/scatter` |
| 3 | 좌우 동기화 사진 뷰어 (회차 슬라이더, 확대·이동 동기화) | `/viewer?a=…&b=…` |
| 3 | PPT 자동 생성 (A4 가로, 회사 템플릿 지정 가능) | 분석런·시편 화면 [PPT] · `services/ppt.py` |
| 3 | X-cut 블리스터 측정 앱 결과 연동 | `POST /api/integrations/xcut` · 템플릿 `XCUT_BLISTER` |

## 운영 보강 (2026-10-23 리뷰 반영, 설계서 v2.3)

설계 근거와 기각한 안은 설계서 12.2절 D-38~D-49에 있습니다.

| 기능 | 내용 | 위치 |
| :--- | :--- | :--- |
| 장비·외부 앱 API 키 | HMI·X-cut 앱·장비 PC는 쿠키 로그인이 안 되므로 `X-API-Key` 머리글로 보냅니다. 관리 > API 키에서 발급(원문은 한 번만 보임)하고 중지합니다. 키마다 처리 계정(권한·감사 로그의 사용자, 전용 계정 권장)과 범위(`pv`·`xcut`·`files`)를 정하며, 범위 밖 주소는 403입니다 | `auth.API_SCOPES`, 마이그레이션 `0003` |
| PV 재전송 | 같은 파일 이름의 PV 로그를 다시 보내면 이전 값을 대체합니다(다른 파일 = 다른 사이클은 쌓임) | `POST /api/process-runs/{run_no}/pv` |
| 목표 정정 | 공정런 화면 [목표 정정]: 기본 레시피 또는 원판 하나의 목표값을 사유와 함께 고침(작성자·관리자). 현재 조건부를 다시 만들고, 각인 라벨은 그대로 두어 "각인 ≠ 현재"로 표시합니다(3.1절). 코드표를 바꿔도 같은 방식으로 다시 만듭니다 | `POST /api/process-runs/{run_no}/targets` |
| 되살리기 | 지운 첨부는 같은 파일을 다시 올리면 되살아남. 지운 시편은 관리자가 시편 목록 [삭제한 시편]에서 되살림 | `POST /api/specimens/{short_id}/restore` |
| 로그인 보호 | 로그인 뒤 이동 주소는 사이트 안 경로만, 같은 사번·주소로 10분에 5번 틀리면 10분 차단(worker마다 따로 셈) | `routers/home.py` |
| API 문서·쿠키 | `/docs`는 개발(SQLite)에서만 기본 공개(`LIMS_API_DOCS`), HTTPS면 `LIMS_COOKIE_SECURE=1` | `config.py` |

## 11.3 확인 필요 사항

사내에서 정해 줘야 하는 값은 코드에 박지 않고 환경변수로 뺐습니다(`deploy/lims.env.example`).
관리 > **시스템 설정** 탭에서 항목별 현재 값과 확정 여부를 봅니다.

| 항목 | 설정 |
| :--- | :--- |
| 서버 포트 | `LIMS_PORT` |
| PostgreSQL | `LIMS_DATABASE_URL` + `alembic upgrade head` |
| 백업 위치 | `LIMS_BACKUP_TARGET` (`scripts/backup.sh`) |
| 장비 공유 폴더 | `LIMS_WATCH_DIRS` |
| 레이저 각인기 CSV | `LIMS_ENGRAVE_COLUMNS` · `_DELIMITER` · `_ENCODING` · `_HEADER` |
| 라벨프린터 | `LIMS_LABEL_SIZE_MM` · `LIMS_LABEL_CODE` (datamatrix/qr) |
| 회사 PPT 템플릿 | `LIMS_PPT_TEMPLATE` |
| 코드표 · 실측 항목·허용편차 · 욕 분석 | 관리 화면에서 편집 (코드표, 실측 항목·허용편차, 욕 분석 탭) |

## 배포 전 남은 일 (사용자 결정, 2026-10-22)

이 개발 PC에서는 아래 두 가지를 하지 않기로 했습니다. 회사 컨테이너에서 진행합니다.

1. **PostgreSQL 실행 검증** — 빈 테스트 DB를 만들고 `LIMS_TEST_DATABASE_URL=postgresql+psycopg://lims:…@localhost:5432/lims_test`를 준 뒤 `cd lims && pytest`를 실행합니다(테스트 76개). 이어서 운영 DB에 `alembic upgrade head` → `python -m scripts.seed`.
2. **11.3 확정 값 입력** — 정해지면 `deploy/lims.env.example`의 해당 환경변수, 관리 > 코드표·실측 항목·허용편차에 넣고 서버를 다시 시작합니다. 관리 > 시스템 설정 탭에서 모든 항목이 "확정"인지 확인합니다.
