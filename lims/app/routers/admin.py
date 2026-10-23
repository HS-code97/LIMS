"""관리: 과제·원소재·코드표·프리셋·시험 템플릿·사용자·욕 분석 (5.1 #6)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import API_SCOPES, hash_api_key, hash_password, new_api_key, require_admin, require_user
from ..db import get_db
from ..models import (ApiKey, BathAnalysis, Material, MasterCode, ProcessPreset, ProcessRun, Project, Team,
                      TestTemplate, User)
from ..services import actuals, marking, workflow
from ..services.condition_code import CodeBook
from ..web import render

router = APIRouter()

TABS = [("projects", "과제"), ("materials", "코일"), ("bath", "욕 분석"), ("codes", "코드표"),
        ("presets", "프리셋"), ("templates", "시험 템플릿"), ("dictionary", "실측 항목·허용편차"),
        ("import", "엑셀 가져오기"), ("users", "사용자"), ("apikeys", "API 키"),
        ("settings", "시스템 설정")]
API_SCOPE_NAMES = {"pv": "HMI PV 실행기록", "xcut": "X-cut 앱 결과", "files": "파일 업로드"}
PROJECT_NO = re.compile(r"^(?P<y>\d{4})(?P<k>[A-Z])(?P<n>\d+)$")


def project_code_for(db: Session, company_no: str) -> str:
    """사내 과제번호 2026P1234 → 그해 등록 순서 영문 + 연도 끝자리 (A6, B6, …). 사내 번호는 DB에 연결
    (시편번호 체계 3.3절, D-13). X·Y·Z는 공용 코드로 예약."""
    m = PROJECT_NO.match(company_no.strip().upper())
    if not m:
        raise HTTPException(422, "사내 과제번호 형식: 2026P1234 (연도4 + 성격1 + 일련번호)")
    try:
        return marking.next_project_code(db, int(m["y"]))
    except marking.MarkingError as e:
        raise HTTPException(409, str(e))


def _back(tab: str, msg: str = "") -> RedirectResponse:
    return RedirectResponse(f"/admin?tab={tab}" + (f"&msg={msg}" if msg else ""), 303)


@router.get("/admin")
def admin_page(request: Request, tab: str = "projects", msg: str = "", user: User = Depends(require_user),
               db: Session = Depends(get_db), new_key: str | None = None):
    ctx = {"tab": tab, "tabs": TABS, "msg": msg, "new_key": new_key}
    if tab == "projects":
        ctx["projects"] = db.scalars(select(Project).order_by(Project.is_common, Project.project_code.desc())).all()
        ctx["users"] = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    elif tab == "materials":
        ctx["materials"] = db.scalars(select(Material).order_by(Material.id.desc())).all()
    elif tab == "bath":
        ctx["analyses"] = db.scalars(select(BathAnalysis).order_by(BathAnalysis.sampled_at.desc()).limit(100)).all()
        ctx["bath_values"] = actuals.bath_values
    elif tab == "codes":
        ctx["codes"] = db.scalars(select(MasterCode).order_by(MasterCode.category, MasterCode.code)).all()
    elif tab == "presets":
        ctx["presets"] = db.scalars(select(ProcessPreset).order_by(ProcessPreset.scope, ProcessPreset.id)).all()
    elif tab == "templates":
        ctx["tpls"] = db.scalars(select(TestTemplate).order_by(TestTemplate.test_type, TestTemplate.code,
                                                               TestTemplate.version.desc())).all()
    elif tab == "dictionary":
        from ..services import param_dict as pdict
        ctx["dict_rows"] = [(k, p, pdict.actual_cfg(k)) for k, p in pdict.params().items() if pdict.is_numeric(k)]
        ctx["dict_version"] = pdict.version()
    elif tab == "settings":
        ctx["items"] = settings_items(request, db)
    elif tab == "users":
        ctx["users_all"] = db.scalars(select(User).order_by(User.is_active.desc(), User.name)).all()
        ctx["teams"] = db.scalars(select(Team).order_by(Team.name)).all()
    elif tab == "apikeys" and user.is_admin:
        ctx["keys"] = db.scalars(select(ApiKey).order_by(ApiKey.is_active.desc(), ApiKey.id.desc())).all()
        ctx["users_all"] = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
        ctx["scope_names"] = API_SCOPE_NAMES
    return render(request, "admin.html", nav="admin", **ctx)


def settings_items(request: Request, db: Session) -> list[dict]:
    """11.3 확인 필요 사항 — 현재 설정값과 확정 여부."""
    import shutil

    from sqlalchemy import func

    from .. import config as C
    from ..models import Attachment
    n_files, size = db.execute(select(func.count(Attachment.id), func.coalesce(func.sum(Attachment.size_bytes), 0))).one()
    try:
        du = shutil.disk_usage(C.FILES_DIR)
        disk = f"여유 {du.free / 1e9:,.0f} GB / 전체 {du.total / 1e9:,.0f} GB"
    except OSError:
        disk = "확인 불가"
    avg = (size / n_files) if n_files else 4e6
    pg = engine_name()
    return [
        {"k": "서버 포트", "env": "LIMS_PORT", "v": str(C.PORT), "ok": C.PORT != 8610 or None,
         "note": "웹 VS Code(10553) 외에 LIMS용 포트 개방 여부 (IT)"},
        {"k": "PostgreSQL", "env": "LIMS_DATABASE_URL", "v": pg, "ok": pg == "postgresql",
         "note": "컨테이너 안 PostgreSQL 15+ 상시 구동 · alembic upgrade head"},
        {"k": "백업 위치", "env": "LIMS_BACKUP_TARGET", "v": C.BACKUP_TARGET or "(미설정)", "ok": bool(C.BACKUP_TARGET),
         "note": "컨테이너 밖 사내 NAS·백업 서버 경로 — scripts/backup.sh가 rsync"},
        {"k": "저장 용량", "env": "LIMS_FILES_DIR", "v": f"파일 {n_files:,}개 · {size / 1e9:,.2f} GB · {disk}", "ok": None,
         "note": f"평균 {avg / 1e6:,.1f} MB/파일 기준 1만 장당 약 {avg * 1e4 * 1.05 / 1e9:,.0f} GB(썸네일 포함)"},
        {"k": "장비 파일 경로", "env": "LIMS_WATCH_DIRS", "v": C.WATCH_DIRS or "(미설정)", "ok": bool(C.WATCH_DIRS),
         "note": "SEM·XRD·GDS PC 공유 폴더 — 확보되면 supervisord lims-watcher autostart"},
        {"k": "태블릿 카메라", "env": "(HTTPS)", "v": request.url.scheme.upper(), "ok": request.url.scheme == "https" or None,
         "note": "셀 편집기의 [사진] 촬영은 HTTP에서도 동작. 브라우저 QR 스캔만 HTTPS 필요 — 없으면 USB·블루투스 스캐너"},
        {"k": "각인기 CSV", "env": "LIMS_ENGRAVE_*", "v": f"열 {','.join(C.ENGRAVE_COLUMNS)} · 구분자 {C.ENGRAVE_DELIMITER!r} · {C.ENGRAVE_ENCODING}",
         "ok": None, "note": "레이저 각인기 CSV 입력 형식에 맞춰 열·구분자·인코딩 조정"},
        {"k": "라벨프린터", "env": "LIMS_LABEL_SIZE_MM / LIMS_LABEL_CODE",
         "v": f"{C.LABEL_SIZE_MM[0]:g}×{C.LABEL_SIZE_MM[1]:g} mm · {C.LABEL_CODE}", "ok": None, "note": "라벨프린터 모델·라벨 규격"},
        {"k": "PPT 템플릿", "env": "LIMS_PPT_TEMPLATE", "v": C.PPT_TEMPLATE or "(기본 서식)", "ok": bool(C.PPT_TEMPLATE) or None,
         "note": "회사 표준 A4 가로 .pptx 경로"},
        {"k": "코드표", "env": "관리 > 코드표", "v": "부록 A~D 초안 (K 이슬점 −40 °C)", "ok": None, "href": "/admin?tab=codes",
         "note": "M계 조성, 소둔 코드 이슬점 기준 확정"},
        {"k": "실측 항목·허용편차", "env": "관리 > 실측 항목", "v": "사전 초안", "ok": None, "href": "/admin?tab=dictionary",
         "note": "재는 항목·방법·측정점 수, 키별 허용편차"},
        {"k": "욕 분석", "env": "관리 > 욕 분석", "v": "등록 → 공정런 적용", "ok": None, "href": "/admin?tab=bath",
         "note": "채취 주기, 분석 방법, 결과 회신 형식"},
    ]


def engine_name() -> str:
    from ..db import engine
    return engine.dialect.name


@router.post("/admin/projects")
def add_project(company_project_no: str = Form(""), project_name: str = Form(...), manager_id: int | None = Form(None),
                common_code: str = Form(""), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if common_code:
        code = common_code.strip().upper()
        if not re.fullmatch(r"[XYZ]\d", code):
            raise HTTPException(422, "공용 과제코드 형식: X6(공통)·Y6(선행)·Z6(기타) — 영문 + 연도 끝자리")
        if db.get(Project, code):
            return _back("projects", f"{code} 이미 있음")
        db.add(Project(project_code=code, project_name=project_name, is_common=True, manager_id=manager_id))
    else:
        code = project_code_for(db, company_project_no)
        db.add(Project(project_code=code, company_project_no=company_project_no.strip().upper(),
                       project_name=project_name, manager_id=manager_id))
    db.commit()
    return _back("projects", f"과제코드 {code} 배정")


@router.post("/admin/materials")
def add_material(coil_no: str = Form(...), steel_grade: str = Form(""), thickness_mm: float | None = Form(None),
                 received_date: date | None = Form(None), note: str = Form(""), user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    """코일만 등록(시편 없이). 전폭시편까지 함께 등록하려면 시편 > 입고를 씁니다."""
    coil, _ = marking.split_field_coil(coil_no)
    if db.scalar(select(Material).where(Material.coil_no == coil)):
        return _back("materials", f"{coil} 이미 있음")
    code, _ = marking.suggest_coil_code(db, coil)
    db.add(Material(coil_no=coil, coil_code=code, steel_grade=steel_grade or None, thickness_mm=thickness_mm,
                    received_date=received_date, note=note or None))
    db.commit()
    return _back("materials", f"{coil} 등록 (코일코드 {code})")


@router.post("/admin/bath")
def add_bath(pot: str = Form(...), sampled_at: datetime = Form(...), method: str = Form(""),
             composition: str = Form(...), note: str = Form(""), user: User = Depends(require_user),
             db: Session = Depends(get_db)):
    """조성 입력 예: Zn 25.1, Si 2.9, Mg 0.46, Fe 0.4, Al bal."""
    comp = {}
    for part in re.split(r"[,;\n]+", composition):
        m = re.match(r"\s*([A-Z][a-z]?)\s*[:=]?\s*([\d.]+|bal\.?)\s*$", part.strip(), re.I)
        if m:
            v = m.group(2)
            comp[m.group(1)] = "bal." if v.lower().startswith("bal") else float(v)
    if not comp:
        raise HTTPException(422, "조성을 읽지 못했습니다. 예: Zn 25.1, Si 2.9, Mg 0.46, Al bal.")
    db.add(BathAnalysis(pot=pot, sampled_at=sampled_at, method=method or None, composition=comp, user_id=user.id,
                        note=note or None))
    db.commit()
    return _back("bath", "욕 분석 등록 — 공정런 [실측] 탭에서 적용하세요")


@router.post("/admin/codes")
def edit_code(category: str = Form(...), code: str = Form(...), name: str = Form(...), spec: str = Form(""),
              description: str = Form(""), is_active: str = Form("on"), user: User = Depends(require_admin),
              db: Session = Depends(get_db)):
    code = code.strip().upper()
    if category in ("HEAT", "PRETREAT", "PAINT") and not re.fullmatch(r"\d{2}", code):
        raise HTTPException(422, "열처리(H)·전처리(T)·도장(P) 코드는 숫자 2자리입니다 (예: 03 → 꼬리 H03).")
    obj = db.get(MasterCode, (category, code)) or MasterCode(category=category, code=code)
    try:
        obj.spec = json.loads(spec) if spec.strip() else None
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"spec JSON 오류: {e}")
    obj.name, obj.description, obj.is_active = name, description or None, is_active == "on"
    db.add(obj)
    db.flush()
    # 코드표가 바뀌면 전체번호 꼬리의 조건부를 다시 만듭니다. 각인번호는 그대로(시편번호 체계 3.3절)
    codes = CodeBook.load(db)
    n = sum(workflow.refresh_condition_codes(db, run, codes) for run in db.scalars(select(ProcessRun)))
    db.commit()
    return _back("codes", f"{category} {obj.code} 저장" + (f" — 현재 조건부가 바뀐 시편 {n}개" if n else ""))


@router.post("/admin/presets/{pid}/toggle")
def toggle_preset(pid: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(ProcessPreset, pid)
    if p is None:
        raise HTTPException(404)
    p.is_active = not p.is_active
    db.commit()
    return _back("presets")


@router.post("/admin/users")
def add_user(emp_no: str = Form(...), name: str = Form(...), team_id: int | None = Form(None), role: str = Form("USER"),
             password: str = Form(...), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.emp_no == emp_no.strip())):
        return _back("users", f"사번 {emp_no} 이미 있음")
    if len(password) < 6:
        raise HTTPException(422, "비밀번호는 6자 이상")
    db.add(User(emp_no=emp_no.strip(), name=name, team_id=team_id, role="ADMIN" if role == "ADMIN" else "USER",
                pw_hash=hash_password(password)))
    db.commit()
    return _back("users", f"{name} 추가")


@router.post("/admin/users/{uid}")
def edit_user(uid: int, action: str = Form(...), password: str = Form(""), user: User = Depends(require_admin),
              db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404)
    if action == "toggle":
        if u.id == user.id:
            raise HTTPException(422, "본인 계정은 비활성화할 수 없습니다.")
        u.is_active = not u.is_active
    elif action == "password":
        if len(password) < 6:
            raise HTTPException(422, "비밀번호는 6자 이상")
        u.pw_hash = hash_password(password)
    elif action == "role":
        u.role = "USER" if u.role == "ADMIN" else "ADMIN"
    db.commit()
    return _back("users", f"{u.name} 변경")


@router.post("/admin/api-keys")
def add_api_key(request: Request, name: str = Form(...), user_id: int = Form(...), scopes: list[str] = Form([]),
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """장비·외부 앱 키 발급. 원문은 이 응답 화면에서 한 번만 보여 주고 저장하지 않습니다(리다이렉트 URL에 싣지 않음)."""
    scopes = [s for s in scopes if s in API_SCOPES]
    owner = db.get(User, user_id)
    if not name.strip() or not scopes or owner is None or not owner.is_active:
        raise HTTPException(422, "이름, 처리 계정(사용 중), 범위를 하나 이상 고르세요.")
    raw = new_api_key()
    db.add(ApiKey(name=name.strip(), prefix=raw[:12], key_hash=hash_api_key(raw), user_id=owner.id, scopes=scopes,
                  created_by=user.id))
    db.commit()
    return admin_page(request, tab="apikeys", msg=f"{name} 발급 — 키는 지금만 보입니다", user=user, db=db,
                      new_key=raw)


@router.post("/admin/api-keys/{kid}/revoke")
def revoke_api_key(kid: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    key = db.get(ApiKey, kid)
    if key is None:
        raise HTTPException(404)
    key.is_active = False
    db.commit()
    return _back("apikeys", f"{key.name} 중지")


@router.post("/admin/dictionary")
def edit_actual_cfg(key: str = Form(...), level: str = Form("panel"), tol: str = Form(""), tol_pct: str = Form(""),
                    agg: str = Form("mean"), quick: str = Form(""), methods: str = Form(""),
                    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """실측 항목·허용편차 (11.3 '키별 허용편차 초안' 확정용). 편차는 색 표시에만 쓰입니다(D-36)."""
    from ..services import param_dict as pdict
    if pdict.param(key) is None:
        raise HTTPException(404)

    def num(v):
        try:
            return float(v) if v.strip() else None
        except ValueError:
            raise HTTPException(422, f"숫자가 아닙니다: {v}")
    cfg = {"level": level if level in ("run", "panel") else "panel", "tol": num(tol), "tol_pct": num(tol_pct),
           "agg": agg if agg in ("mean", "last", "median") else "mean", "quick": quick == "on" or None,
           "methods": [m.strip() for m in methods.split(",") if m.strip()]}
    if cfg["tol"] is not None:
        cfg.pop("tol_pct")
    pk = pdict.param(key)
    for k in ("pv_tag",):
        if (pk.get("actual") or {}).get(k):
            cfg[k] = pk["actual"][k]
    pdict.update_actual_cfg(db, key, cfg, user.id)      # param_actual_cfg 행 변경은 감사 로그에 자동 기록
    # 허용편차가 바뀌면 대표값 캐시의 편차 표시를 다시 계산
    for run in db.scalars(select(ProcessRun)):
        actuals.recompute_run(db, run)
    db.commit()
    return _back("dictionary", f"{key} 실측 설정 저장")


@router.get("/api/import/template.xlsx")
def import_template(user: User = Depends(require_user)):
    from fastapi.responses import Response
    from ..services.excel_import import template_workbook
    return Response(template_workbook(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="lims_import_template.xlsx"'})


@router.post("/api/import/excel")
async def import_excel(file: UploadFile = File(...), dry_run: bool = Form(True), user: User = Depends(require_user),
                       db: Session = Depends(get_db)):
    """과거 엑셀 일괄 가져오기 (2단계). dry_run=true면 검증만 하고 저장하지 않습니다."""
    from ..services.excel_import import run_import
    return run_import(db, await file.read(), user.id, dry_run=dry_run)


@router.post("/account/password")
def change_own_password(current: str = Form(...), new: str = Form(...), user: User = Depends(require_user),
                        db: Session = Depends(get_db)):
    from ..auth import verify_password
    u = db.get(User, user.id)
    if not verify_password(current, u.pw_hash):
        raise HTTPException(422, "현재 비밀번호가 맞지 않습니다.")
    if len(new) < 6:
        raise HTTPException(422, "비밀번호는 6자 이상")
    u.pw_hash = hash_password(new)
    db.commit()
    return RedirectResponse("/", 303)
