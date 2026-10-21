"""기준 정보 시드: 팀·사용자·공통 과제·코드표·공용 프리셋·시험 템플릿.

사용:  python -m scripts.seed            (lims 폴더에서)
       python -m scripts.seed --demo     (+ 기준 시나리오용 원소재·과제)
다시 실행해도 이미 있는 행은 건너뜁니다(코드표·템플릿은 갱신).
"""
from __future__ import annotations

import json
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
# 개발·시연용 계정. 운영에서는 관리 화면에서 비밀번호를 바꾸세요.
USERS = [
    {"emp_no": "admin", "name": "관리자", "team": "표면연구", "role": "ADMIN", "pw": "admin1234"},
    {"emp_no": "hhs", "name": "황현석", "team": "표면연구", "role": "ADMIN", "pw": "lims1234"},
    {"emp_no": "kim", "name": "김연구", "team": "부식", "role": "USER", "pw": "lims1234"},
]


def seed(db, demo: bool = False) -> None:
    teams = {}
    for n in TEAMS:
        t = db.scalar(select(Team).where(Team.name == n)) or Team(name=n)
        db.add(t)
        teams[n] = t
    db.flush()
    users = {}
    for u in USERS:
        obj = db.scalar(select(User).where(User.emp_no == u["emp_no"]))
        if obj is None:
            obj = User(emp_no=u["emp_no"], name=u["name"], team_id=teams[u["team"]].id, role=u["role"],
                       pw_hash=hash_password(u["pw"]))
            db.add(obj)
        users[u["emp_no"]] = obj
    db.flush()

    yy = f"{date.today():%y}"
    for code, name in ((f"{yy}X0", "팀 공통 실험·기초 데이터"), (f"{yy}X1", "탐색 실험(과제 착수 전)"),
                       (f"{yy}X9", "고객 클레임·현장 문제 분석")):
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
            obj = ProcessPreset(name=p["name"], scope="PUBLIC", owner_id=users["admin"].id)
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
        if db.get(Project, "26P4") is None:
            db.add(Project(project_code="26P4", company_project_no="2026P1234",
                           project_name="M계 Al-Zn-Si-Mg 도금강판 내식성 향상", manager_id=users["hhs"].id))
        if db.scalar(select(Material).where(Material.coil_no == "POS-26-8891")) is None:
            db.add(Material(coil_no="POS-26-8891", steel_grade="SPCC", thickness_mm=0.8,
                            received_date=date(2026, 10, 1), note="기준 시나리오 원소재"))
    db.commit()


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db, demo="--demo" in sys.argv)
    print("seed 완료")


if __name__ == "__main__":
    main()
