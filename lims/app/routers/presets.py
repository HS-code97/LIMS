"""공정 프리셋 3단계(공용·팀·개인) API (6.2절)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import ProcessPreset, User
from ..schemas import PresetIn
from ..services import param_dict as pdict

router = APIRouter()


def visible_presets(db: Session, user: User) -> list[ProcessPreset]:
    q = select(ProcessPreset).where(ProcessPreset.is_active.is_(True), or_(
        ProcessPreset.scope == "PUBLIC",
        (ProcessPreset.scope == "TEAM") & (ProcessPreset.team_id == user.team_id),
        (ProcessPreset.scope == "PERSONAL") & (ProcessPreset.owner_id == user.id)))
    order = {"PUBLIC": 0, "TEAM": 1, "PERSONAL": 2}
    return sorted(db.scalars(q), key=lambda p: (order.get(p.scope, 9), p.id))


def preset_json(p: ProcessPreset) -> dict:
    return {"id": p.id, "name": p.name, "scope": p.scope, "coating_system": p.coating_system,
            "bath_code": p.bath_code, "overrides": p.overrides, "dict_version": p.dict_version,
            "owner": p.owner.name if p.owner else None}


@router.get("/api/presets")
def list_presets(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return [preset_json(p) for p in visible_presets(db, user)]


def _diff_only(recipe: dict) -> dict:
    """전체 레시피 → 사전 기본값과 다른 값만 (프리셋은 차이만 저장, 6.2절)."""
    base = pdict.defaults()
    out: dict = {}
    for sec, vals in recipe.items():
        if sec == "out":
            continue
        for k, v in (vals or {}).items():
            if (base.get(sec) or {}).get(k) != v:
                out.setdefault(sec, {})[k] = v
    return out


@router.post("/api/presets")
def save_preset(data: PresetIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    scope = data.scope.upper()
    if scope == "PUBLIC" and not user.is_admin:
        raise HTTPException(403, "공용 프리셋은 관리자만 만들 수 있습니다.")
    if scope not in ("PUBLIC", "TEAM", "PERSONAL"):
        raise HTTPException(422, "scope는 PUBLIC/TEAM/PERSONAL")
    p = ProcessPreset(name=data.name.strip()[:60], scope=scope, owner_id=user.id,
                      team_id=user.team_id if scope == "TEAM" else None,
                      coating_system=data.coating_system.upper()[:1], bath_code=data.bath_code[:1],
                      overrides=_diff_only(data.recipe), dict_version=pdict.version())
    db.add(p)
    db.commit()
    return preset_json(p)


@router.delete("/api/presets/{pid}")
def deactivate_preset(pid: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    p = db.get(ProcessPreset, pid)
    if p is None:
        raise HTTPException(404)
    if not (user.is_admin or p.owner_id == user.id):
        raise HTTPException(403, "만든 사람만 지울 수 있습니다.")
    p.is_active = False
    db.commit()
    return {"ok": True}
