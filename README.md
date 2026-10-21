# 도금강판 R&D LIMS v2.2

`lims_master_design_v2.2.md`(마스터 설계서) 11.1 로드맵의 **1단계 MVP + 2단계 확장 + 3단계 고도화**를 구현한 코드입니다.
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

개발용 계정(시드, `lims/scripts/seed.py`): `hhs` / `lims1234`(관리자), `kim` / `lims1234`, `admin` / `admin1234`.
운영에서는 관리 > 사용자에서 바로 바꾸세요. 빈 DB로 시작하려면 `python -m scripts.seed`(기준 정보만)를 실행합니다.

개발 DB는 `lims/var/lims.db`(SQLite)이며, 파일은 `lims/var/files/{yyyy}/{약식번호}/`에 저장됩니다.

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

PostgreSQL에서 같은 테스트를 돌리려면 빈 테스트 DB를 만들고 `LIMS_TEST_DATABASE_URL=postgresql+psycopg://…/lims_test`를 준 뒤 `pytest`를 실행합니다.
이 개발 PC에는 PostgreSQL이 없어(설치하지 않기로 함) SQLite 실행 + PostgreSQL 방언 컴파일 + 오프라인 마이그레이션 SQL(`lims/db/migration_0001_postgres.sql`)까지 확인했습니다.

## 운영 배포 (회사 Docker 컨테이너, PostgreSQL 15+)

1. `/opt/lims`에 이 폴더를 두고 가상환경과 `requirements.txt`를 설치합니다.
2. `deploy/lims.env.example`을 `.env`로 복사해 DB 비밀번호·`LIMS_SECRET_KEY`·백업 경로를 채웁니다.
3. 스키마: `cd lims && alembic upgrade head` (검토용 DDL은 `lims/db/schema_postgres.sql`, `python -m scripts.dump_ddl`로 다시 생성)
4. 기준 정보: `python -m scripts.seed`
5. 상시 구동: `deploy/supervisord.conf`, 백업: `scripts/backup.sh`를 cron 02:00에 등록 (7장 P8)
6. 사내망이 CDN을 막으면 `htmx.min.js`(1.9.12), `alpine.min.js`(3.14.1)를 `lims/app/static/vendor/`에 두면 그 파일을 씁니다. 글꼴은 없으면 맑은 고딕·Consolas로 대체됩니다.

## 설계서 대응

| 설계서 | 구현 위치 |
| :--- | :--- |
| 3장 시편번호 (약식 10자 유일, 정식 16자, 숫자 4자리 자율 + 다음 빈 번호 제안, 일괄 발번 충돌 검사) | `services/numbering.py`, `models/lineage.py` (`short_id` 생성 컬럼, `uq_short`) |
| 3.2 조건부 5자 (원판 단위·목표 기준, 실측 기준은 표시만) | `services/condition_code.py`, `services/actuals.actual_condition_code` |
| 3.3 과제코드 압축 (`2026P1234 → 26P4`, 겹치면 `26PA`…), 공통 `26X0/X1/X9` | `routers/admin.project_code_for`, `scripts/seed.py` |
| 3.6 각인 CSV·라벨 PDF (DataMatrix = 약식번호) | `services/export.py`, `/api/labels/engrave.csv`, `/api/labels/print.pdf` |
| 5장 화면 6개 | `templates/home · process_run_new/detail · specimen_detail · test_run_detail · search · admin` |
| 6.1 HMI 재사용 (사전 단일 원본, cycle/checks/drawMimic 공통 모듈) | `data/seed/param_dictionary.json`, `static/hmi/hmi-core.js`, `static/hmi/hmi-lims.js` |
| 6.2 프리셋 3단계·지난 공정런 복제 | `routers/presets.py`, 공정런 등록 화면 |
| 6.3~6.4 저장 페이로드·서버 처리 순서 (범위 재검증 → 시리즈 → 조건부 → 409 → 한 트랜잭션) | `services/workflow.create_process_run` |
| 6.6~6.8 목표·실측 이중 기록, 대표값 규칙, 4경로(수기·욕 분석·시험 `maps_to`·PV API) | `services/actuals.py`, `param_actuals`, `effective_params` |
| 6.9 시리즈 실험 (원판별 `target_overrides`, ◆/● 구분) | `workflow.series_overrides`, 시리즈 설정 대화상자 |
| 7장 P1~P8 | `services/workflow.py`, `file_ingest.py`, `lineage.py`, `search.py`, `export.py`, `scripts/backup.sh` |
| 8장 DDL·운영 규칙 (논리 삭제, RESTRICT, 감사 로그 after_flush, 권한) | `models/`, `models/audit.py`, `auth.py`, `alembic/versions/0001_*` |
| 9장 시험 템플릿 8종 (JSON 시드, 템플릿 외 키 저장 거부) | `data/seed/test_templates/*.json`, `services/templates_engine.py` |
| 10장 API | `routers/*.py` (`/docs`에서 확인) |

화면 디자인은 Stitch로 만든 디자인 시스템("Plated Steel LIMS — Lab Instrument")과 화면 시안(`design/stitch/`: 01 시편 상세, 03 시험런 그리드, 04 공정런 등록)을 기준으로 합니다. 공정런 등록은 설계서 6.1절대로 원본 HMI 미믹·열사이클을 유지하고 그 주변 배치(상단 한 줄, 구간 요약 칩, 변경 행 강조, 하단 확정 패널)를 시안에서 가져왔습니다. Stitch 출력은 Tailwind CDN 기반이라, 빌드 도구 없이(D-18) 사내망에서 돌도록 같은 토큰·배치를 `static/css/lims.css`로 옮겼습니다.

## 설계서와 다르게 정한 점 (0단계 확정 필요)

- **소둔 코드 K의 이슬점 기준을 −30 → −40 °C로 맞춤.** 부록 D 초안(K = DP −30 ±5)으로는 11.2 시나리오(이슬점 목표 −40·실측 −36에서 `M206K` → `M205K`)가 나오지 않습니다. 그래서 부록 D 마지막 문장의 선택지("HMI 기본값에 맞춤")를 따랐습니다. M(극저이슬점)은 K와 겹치지 않도록 −55로 두었습니다. `data/seed/master_codes.json` 또는 관리 > 코드표에서 바꿀 수 있습니다.
- **실측 기준 단면 부착량 = 윗면·아랫면 실측 중 작은 값.** 11.2의 `M205K`(윗면 54·아랫면 58)와 맞추려고 정한 규칙입니다. `condition_code.specimen_code`에서 바꿀 수 있습니다.
- M1·M2 프리셋의 욕 조성(Al 잔부 71/70.5, Si 3, Mg 0/0.5)과 욕온 590 °C는 부록 B를 근거로 한 추정값입니다.
- 설계서 DDL에 없지만 화면 구현에 필요해 추가한 컬럼: `process_runs.warnings`·`coating_system`, `specimens.note`, `test_runs.cycles`(그리드 열 수).
- 사전에 `aka`(별칭) 필드를 추가했습니다. 예: `ak.P` = "나이프 압력". 엑셀 붙여넣기 머리글을 인식하는 데 씁니다.

## 2·3단계 (설계서 11.1)

| 단계 | 기능 | 위치 |
| :--- | :--- | :--- |
| 2 | 시험 템플릿 편집 화면 (새 버전 생성, 키·maps_to 검증) | 관리 > 시험 템플릿 > 편집 · `routers/templates_admin.py` |
| 2 | 장비 PC 폴더 감시 (안정 대기, 중복 방지, 진행 중 시험런 회차 자동 연결) | `app/workers/watcher.py`, supervisord `lims-watcher` |
| 2 | 과거 엑셀 일괄 가져오기 (공정런·분기·실측·시험결과, 한 트랜잭션, 미리보기) | 관리 > 엑셀 가져오기 · `scripts/import_excel.py` |
| 2 | 태블릿 화면 (터치 44px, 셀 편집기 세로 배치, 카메라 촬영 → 셀 자동 첨부) | `static/css/lims.css` `pointer:coarse`, 셀 편집기 |
| 3 | HMI PV 실행기록 수신 (CSV → pv_tag로 구간 평균·최소·최대, 원본 보관) | `POST /api/process-runs/{run_no}/pv` · `services/pv.py` |
| 3 | 목표–실측 산점도 (허용편차 띠) | `/analysis/scatter` |
| 3 | 좌우 동기화 사진 뷰어 (회차 슬라이더, 확대·이동 동기화) | `/viewer?a=…&b=…` |
| 3 | PPT 자동 생성 (A4 가로, 회사 템플릿 지정 가능) | 시험런·시편 화면 [PPT] · `services/ppt.py` |
| 3 | X-cut 블리스터 측정 앱 결과 연동 | `POST /api/integrations/xcut` · 템플릿 `XCUT_BLISTER` |

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

1. **PostgreSQL 실행 검증** — 빈 테스트 DB를 만들고 `LIMS_TEST_DATABASE_URL=postgresql+psycopg://lims:…@localhost:5432/lims_test`를 준 뒤 `cd lims && pytest`를 실행합니다(테스트 28개). 이어서 운영 DB에 `alembic upgrade head` → `python -m scripts.seed`.
2. **11.3 확정 값 입력** — 정해지면 `deploy/lims.env.example`의 해당 환경변수, 관리 > 코드표·실측 항목·허용편차에 넣고 서버를 다시 시작합니다. 관리 > 시스템 설정 탭에서 모든 항목이 "확정"인지 확인합니다.
