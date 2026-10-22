"""파라미터 사전(단일 원본) 로딩과 레시피 계산 도우미.

키 표기는 '구간.파라미터'(예: 'pot.T', 'out.cw_top'). 레시피는 {구간: {파라미터: 값}} 중첩 dict.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import SEED_DIR
from ..models import ParamActualCfg


# 관리 화면에서 고친 실측 설정 (param_actual_cfg 테이블). rev가 바뀌면 다시 읽습니다.
_db_cfg: dict = {"rev": None, "overrides": {}}


@lru_cache
def load() -> dict:
    """시드 사전(코드와 함께 배포) 위에 DB의 실측 설정을 덮어쓴 사전."""
    with open(SEED_DIR / "param_dictionary.json", encoding="utf-8") as f:
        d = json.load(f)
    for s in d["sections"]:
        for p in s["p"]:
            key = f"{s['id']}.{p['k']}"
            if key in _db_cfg["overrides"]:
                cfg = _db_cfg["overrides"][key]
                if cfg:
                    p["actual"] = cfg
                else:
                    p.pop("actual", None)
    return d


def reload() -> None:
    load.cache_clear()
    params.cache_clear()


def sync(db: Session) -> None:
    """DB의 실측 설정이 바뀌었으면(다른 worker에서 고친 것 포함) 다시 읽습니다. 요청마다 get_db가 부릅니다(쿼리 1회)."""
    rev = db.scalar(select(func.max(ParamActualCfg.rev)))
    if rev == _db_cfg["rev"]:
        return
    _db_cfg["overrides"] = {r.param_key: r.cfg for r in db.scalars(select(ParamActualCfg))}
    _db_cfg["rev"] = rev
    reload()


def update_actual_cfg(db: Session, key: str, cfg: dict, user_id: int | None) -> dict:
    """키의 actual 블록(수준·허용편차·대표값 계산·빠른 입력·방법)을 DB에 저장 (감사 로그는 자동).
    키·구간 구조는 바꾸지 않으므로 dict_version은 그대로 둡니다(과거 공정런 해석에 영향 없음)."""
    p = param(key)
    if p is None:
        raise KeyError(key)
    before = p.get("actual")
    new = {k: v for k, v in cfg.items() if v not in (None, "", [])} or None
    row = db.get(ParamActualCfg, key) or ParamActualCfg(param_key=key)
    row.cfg, row.updated_by, row.updated_at = new, user_id, datetime.now()
    row.rev = (db.scalar(select(func.max(ParamActualCfg.rev))) or 0) + 1
    db.add(row)
    db.flush()
    sync(db)
    return {"before": before, "after": new}


def version() -> str:
    return load()["dict_version"]


def sections() -> list[dict]:
    return load()["sections"]


@lru_cache
def params() -> dict[str, dict]:
    """'pot.T' → 파라미터 정의 (+ section 정보)."""
    out = {}
    for s in sections():
        for p in s["p"]:
            out[f"{s['id']}.{p['k']}"] = {**p, "section": s["id"], "section_nm": s["nm"],
                                          "section_opt": bool(s.get("opt")),
                                          "setpoint": s.get("setpoint", True)}
    return out


def param(key: str) -> dict | None:
    return params().get(key)


def label(key: str) -> str:
    p = param(key)
    return p["l"] if p else key


def is_numeric(key: str) -> bool:
    p = param(key)
    return bool(p) and p.get("type") != "sel"


def actual_cfg(key: str) -> dict:
    """키의 실측 설정. actual 블록이 없는 키도 '원판 수준, 허용편차 없음'으로 입력은 받습니다."""
    p = param(key) or {}
    cfg = {"level": "panel", "agg": "mean", "methods": []}
    cfg.update(p.get("actual") or {})
    return cfg


def quick_keys() -> list[str]:
    return [k for k, p in params().items() if (p.get("actual") or {}).get("quick")]


def numeric_keys() -> list[str]:
    return [k for k in params() if is_numeric(k)]


def defaults() -> dict:
    rcp: dict = {}
    for s in sections():
        d = rcp.setdefault(s["id"], {})
        if s.get("opt"):
            d["on"] = True
        for p in s["p"]:
            if "v" in p:
                d[p["k"]] = p["v"]
    return rcp


def merge(base: dict, overrides: dict | None) -> dict:
    """중첩 overrides({"pot":{"T":450}}) 또는 점 표기({"pot.T":450}) 모두 적용."""
    out = copy.deepcopy(base)
    for k, v in (overrides or {}).items():
        if isinstance(v, dict):
            out.setdefault(k, {}).update(v)
        elif "." in k:
            sec, pk = k.split(".", 1)
            out.setdefault(sec, {})[pk] = v
    return out


def preset_recipe(preset_overrides: dict | None) -> dict:
    r = merge(defaults(), preset_overrides)
    # HMI applyPreset과 동일: NOF는 프리셋 적용 시 기본 OFF
    if "nof" in r and "on" not in (preset_overrides or {}).get("nof", {}):
        r["nof"]["on"] = False
    return r


def get(recipe: dict, key: str):
    sec, pk = key.split(".", 1)
    return (recipe.get(sec) or {}).get(pk)


def section_on(recipe: dict, sec: str) -> bool:
    s = next((x for x in sections() if x["id"] == sec), None)
    if not s or not s.get("opt"):
        return True
    return bool((recipe.get(sec) or {}).get("on"))


def target_value(recipe: dict, key: str):
    """키의 목표값. target_from(부착량 윗면·아랫면 ← 목표 부착량)을 따라갑니다."""
    p = param(key)
    if not p:
        return None
    if not section_on(recipe, p["section"]):
        return None
    if p.get("only_if"):
        sec, pk = p["only_if"].split(".")
        if not (recipe.get(sec) or {}).get(pk):
            return None
    if p.get("target_from"):
        return get(recipe, f"{p['section']}.{p['target_from']}")
    return get(recipe, key)


def diff_keys(a: dict, b: dict) -> list[str]:
    """두 레시피에서 값이 다른 키 목록 (프리셋 대비 변경 표시용)."""
    out = []
    for s in sections():
        sa, sb = a.get(s["id"]) or {}, b.get(s["id"]) or {}
        if s.get("opt") and sa.get("on") != sb.get("on"):
            out.append(f"{s['id']}.on")
        for p in s["p"]:
            if sa.get(p["k"]) != sb.get(p["k"]):
                out.append(f"{s['id']}.{p['k']}")
    return out


def out_of_range(recipe: dict) -> list[str]:
    """사전 min/max 밖 값 (서버 재검증 — 브라우저 검증은 신뢰하지 않음, 6.4절)."""
    errs = []
    for key, p in params().items():
        if p.get("type") == "sel" or "min" not in p:
            continue
        if not section_on(recipe, p["section"]):
            continue
        v = get(recipe, key)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            errs.append(f"{p['section_nm']} {p['l']} 값이 숫자가 아닙니다: {v!r}")
            continue
        if not (p["min"] <= fv <= p["max"]):
            errs.append(f"{p['section_nm']} {p['l']} {fv:g}{p['u']} — 허용 범위 {p['min']}~{p['max']}{p['u']} 밖")
    return errs


def checks(recipe: dict, coating_system: str | None = None) -> list[dict]:
    """HMI checks()의 서버판. 경고만 반환하고 저장을 막지 않습니다(5.2절)."""
    r = recipe
    out = [{"lv": "err", "msg": m} for m in out_of_range(r)]
    g = lambda k: get(r, k)  # noqa: E731
    try:
        if g("sjc.T") > g("rth.T"):
            out.append({"lv": "err", "msg": "서냉 종료 판온이 최고 판온보다 높습니다."})
        if g("rjc.T") > g("sjc.T"):
            out.append({"lv": "err", "msg": "급냉 종료 판온이 서냉 종료 판온보다 높습니다."})
        d = g("snout.SET") - g("pot.T")
        if d < 0 or d > 25:
            out.append({"lv": "warn", "msg": f"SET − 욕온 = {d:+g} °C. 권장 0~+25 °C"})
        ga_on = section_on(r, "ga")
        if ga_on and g("pot.Al") > 0.135:
            out.append({"lv": "warn", "msg": f"GA 운전인데 욕 Al {g('pot.Al')}% — GA는 통상 0.11~0.13%"})
        if not ga_on and coating_system == "A":
            out.append({"lv": "warn", "msg": "GA 프리셋인데 합금화로가 OFF입니다."})
        if g("rth.DP") > -30:
            out.append({"lv": "warn", "msg": f"이슬점 {g('rth.DP')} °C — 통상 −30 °C 이하로 관리"})
        if g("apc.T") > g("pot.T"):
            out.append({"lv": "err", "msg": "탑롤 판온이 욕온보다 높습니다."})
    except TypeError:
        pass
    return out
