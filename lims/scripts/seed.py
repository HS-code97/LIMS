"""기준 정보 시드: 팀·사용자·공통 과제·코드표·공용 프리셋·분석 템플릿.

사용:  python -m scripts.seed            (lims 폴더에서, 운영)
       python -m scripts.seed --demo     (개발용 SQLite만: 개발 계정 + 기준 시나리오용 원소재·과제)
운영 시드는 개발 계정을 만들지 않습니다. 관리자가 아직 없으면 LIMS_ADMIN_EMP_NO·LIMS_ADMIN_PASSWORD
(없으면 터미널에서 입력)로 첫 관리자 1명을 만듭니다.
다시 실행해도 이미 있는 행은 건너뜁니다(코드표·템플릿은 갱신).
"""
from __future__ import annotations

import getpass
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.config import SEED_DIR  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (Material, MasterCode, ProcessPreset, Project, Team, TestTemplate,  # noqa: E402
                        User)
from app.services import param_dict as pdict  # noqa: E402

TEAMS = ["부식", "표면·전기화학", "가공", "도금 품질", "표면연구"]
# 개발·시연용 계정 (--demo에서만 생성). 비밀번호가 공개돼 있으므로 운영 DB에는 만들지 않습니다.
USERS = [
    {"emp_no": "admin", "name": "관리자", "team": "표면연구", "role": "ADMIN", "pw": "admin1234"},
    {"emp_no": "hhs", "name": "황현석", "team": "표면연구", "role": "ADMIN", "pw": "lims1234"},
    {"emp_no": "kim", "name": "김연구", "team": "부식", "role": "USER", "pw": "lims1234"},
]
MIN_ADMIN_PW = 10


class SeedError(Exception):
    pass


def check_demo_allowed(dialect: str) -> None:
    if dialect != "sqlite":
        raise SeedError("--demo는 개발용 SQLite에서만 씁니다(공개된 개발 계정을 만듭니다).")


def check_admin_password(pw: str) -> None:
    if len(pw) < MIN_ADMIN_PW or pw in {u["pw"] for u in USERS}:
        raise SeedError(f"관리자 비밀번호는 {MIN_ADMIN_PW}자 이상이고 개발 계정 비밀번호와 달라야 합니다.")


def first_admin(db) -> User | None:
    return db.scalar(select(User).where(User.role == "ADMIN", User.is_active.is_(True)).order_by(User.id))


def seed(db, demo: bool = False, admin: tuple[str, str] | None = None) -> None:
    """admin: 운영 시드에서 관리자가 아직 없을 때 만들 (사번, 비밀번호)."""
    teams = {}
    for n in TEAMS:
        t = db.scalar(select(Team).where(Team.name == n)) or Team(name=n)
        db.add(t)
        teams[n] = t
    db.flush()
    users = {}
    if demo:
        for u in USERS:
            obj = db.scalar(select(User).where(User.emp_no == u["emp_no"]))
            if obj is None:
                obj = User(emp_no=u["emp_no"], name=u["name"], team_id=teams[u["team"]].id, role=u["role"],
                           pw_hash=hash_password(u["pw"]))
                db.add(obj)
            users[u["emp_no"]] = obj
        owner = users["admin"]
    else:
        owner = first_admin(db)
        if owner is None:
            if admin is None:
                raise SeedError("관리자 계정이 없습니다. LIMS_ADMIN_EMP_NO·LIMS_ADMIN_PASSWORD를 주고 다시 실행하세요.")
            emp_no, pw = admin
            check_admin_password(pw)
            owner = User(emp_no=emp_no, name="관리자", role="ADMIN", pw_hash=hash_password(pw))
            db.add(owner)
    db.flush()

    y = f"{date.today().year % 10}"       # 공용 과제코드: X 공통 · Y 선행 · Z 기타 + 연도 끝자리 (시편번호 체계 3.3절)
    for code, name in ((f"X{y}", "팀 공통 실험·기초 데이터"), (f"Y{y}", "선행·탐색 실험(과제 착수 전)"),
                       (f"Z{y}", "기타 (고객 클레임·현장 문제 분석 등)")):
        if db.get(Project, code) is None:
            db.add(Project(project_code=code, project_name=name, is_common=True))

    with open(SEED_DIR / "master_codes.json", encoding="utf-8") as f:
        mc = json.load(f)
    for cat in ("COATING_SYS", "BATH", "ANNEALING"):
        for row in mc[cat]:
            obj = db.get(MasterCode, (cat, row["code"])) or MasterCode(category=cat, code=row["code"])
            obj.name, obj.spec, obj.description = row["name"], row.get("spec"), row.get("description")
            db.add(obj)

    with open(SEED_DIR / "presets.json", encoding="utf-8") as f:
        presets = json.load(f)["presets"]
    for p in presets:
        obj = db.scalar(select(ProcessPreset).where(ProcessPreset.name == p["name"], ProcessPreset.scope == "PUBLIC"))
        if obj is None:
            obj = ProcessPreset(name=p["name"], scope="PUBLIC", owner_id=owner.id)
            db.add(obj)
        obj.coating_system, obj.bath_code, obj.overrides = p["coating_system"], p["bath_code"], p["overrides"]
        obj.dict_version = pdict.version()

    for fp in sorted((SEED_DIR / "test_templates").glob("*.json")):
        with open(fp, encoding="utf-8") as f:
            t = json.load(f)
        obj = db.scalar(select(TestTemplate).where(TestTemplate.code == t["code"],
                                                   TestTemplate.version == t["version"]))
        if obj is None:
            obj = TestTemplate(code=t["code"], version=t["version"])
            db.add(obj)
        obj.name, obj.test_type = t["name"], t["test_type"]
        obj.field_schema, obj.condition_schema = t["field_schema"], t.get("condition_schema") or []
        obj.default_cycles, obj.default_interval_days = t.get("default_cycles"), t.get("default_interval_days")
        obj.team_id = teams[t["team"]].id if t.get("team") in teams else None

    if demo:
        if db.get(Project, "A6") is None:
            db.add(Project(project_code="A6", company_project_no="2026P123",
                           project_name="M계 Al-Zn-Si-Mg 도금강판 내식성 향상", manager_id=users["hhs"].id))
        if db.get(Project, "B6") is None:
            db.add(Project(project_code="B6", company_project_no="2026P567",
                           project_name="도장 후 내식성 평가", manager_id=users["kim"].id))
        if db.scalar(select(Material).where(Material.coil_no == "CQV3141")) is None:
            db.add(Material(coil_no="CQV3141", coil_code="QV3", steel_grade="SPCC", thickness_mm=0.8,
                            received_date=date(2026, 10, 1), note="기준 시나리오 코일"))
        # 열처리(H)·전처리(T)·도장(P) 코드표 예시 — 운영 항목은 관리 > 코드표에서 정합니다(미결 3)
        for cat, code, name in (("HEAT", "01", "열처리 예시 (조건 미정)"), ("PRETREAT", "01", "화성처리 예시 (조건 미정)"),
                                ("PAINT", "01", "도장 예시 (조건 미정)")):
            if db.get(MasterCode, (cat, code)) is None:
                db.add(MasterCode(category=cat, code=code, name=name))
    db.commit()


def _admin_from_env_or_prompt() -> tuple[str, str] | None:
    emp_no, pw = os.getenv("LIMS_ADMIN_EMP_NO", ""), os.getenv("LIMS_ADMIN_PASSWORD", "")
    if emp_no and pw:
        return emp_no, pw
    if not sys.stdin.isatty():
        return None
    try:            # Windows는 NUL 입력도 터미널로 보므로 EOF까지 처리
        emp_no = emp_no or input("첫 관리자 사번: ").strip()
        pw = pw or getpass.getpass("첫 관리자 비밀번호: ")
        if pw != getpass.getpass("비밀번호 확인: "):
            raise SeedError("비밀번호가 서로 다릅니다.")
    except EOFError:
        return None
    return emp_no, pw


def main() -> None:
    demo = "--demo" in sys.argv
    try:
        if demo:
            check_demo_allowed(engine.dialect.name)
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            admin = None if demo or first_admin(db) else _admin_from_env_or_prompt()
            seed(db, demo=demo, admin=admin)
    except SeedError as e:
        sys.exit(f"seed 중단: {e}")
    print("seed 완료")


if __name__ == "__main__":
    main()
