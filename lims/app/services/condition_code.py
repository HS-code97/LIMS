"""조건부 5자 자동 생성 (3.2절, D-11~D-13, D-31, D-32).

자리: 1 도금 계열 · 2 욕 조성 숫자(허용오차 밖이면 X) · 3~4 단면 부착량 round_half_up(g/m²÷10) · 5 소둔 코드
전체번호 꼬리의 도금 블록(시편번호 체계 3.3절)으로 목표 기준(basis="target")을 씁니다. 각인하지 않습니다.
실측 기준은 시편 상세 표시용입니다.

변형번호(시편번호 체계 3.3절): 조건부는 코드표 기준의 분류라 허용오차 안의 차이(DP −42/−40)나 코드에 없는 값
(욕온·나이프 압력)을 가르지 못합니다. 그래서 공정 계열(조건부 앞 2자 'M2') 안에서 부착량을 뺀 목표 공정값의
지문마다 번호를 줍니다. 00 = 공용 표준 프리셋 그대로(표기 생략), 01~ = 변형. 'M206K03', 'MX06K01'.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MasterCode, ProcessPreset, ProcessVariant, Specimen
from . import param_dict as pdict

BATH_KEYS = ("Al", "Mg", "Si")


def round_half_up(x: float) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class CodeBook:
    bath: dict[str, dict] = field(default_factory=dict)        # 'M2' → spec
    annealing: dict[str, dict] = field(default_factory=dict)   # 'K' → spec

    @classmethod
    def load(cls, db: Session) -> "CodeBook":
        cb = cls()
        for mc in db.scalars(select(MasterCode).where(MasterCode.is_active.is_(True))):
            if mc.category == "BATH" and mc.spec:
                cb.bath[mc.code] = mc.spec
            elif mc.category == "ANNEALING" and mc.spec:
                cb.annealing[mc.code] = mc.spec
        return cb

    def match_bath(self, sys_code: str, pot: dict, preferred: str | None = None) -> str:
        """계열 글자로 시작하는 욕 코드 중 모든 원소가 허용오차 안인 것. 여럿이면 프리셋 코드 → 가장 가까운 것."""
        hits = []
        for code, spec in self.bath.items():
            if code[0] != sys_code:
                continue
            dist, ok = 0.0, True
            for el, (target, tol) in spec.get("el", {}).items():
                v = pot.get(el)
                if v is None:
                    v = 0.0
                try:
                    dv = abs(float(v) - target)
                except (TypeError, ValueError):
                    ok = False
                    break
                if dv > tol + 1e-9:
                    ok = False
                    break
                dist += dv / tol
            if ok:
                hits.append((dist, code))
        if not hits:
            return "X"
        codes = [c for _, c in sorted(hits)]
        if preferred and f"{sys_code}{preferred}" in codes:
            return preferred
        return codes[0][1:]

    def match_annealing(self, peak_T, soak_t, dp) -> str:
        hits = []
        for code, spec in self.annealing.items():
            if "T_lt" in spec:
                if peak_T is not None and peak_T < spec["T_lt"]:
                    hits.append((0.0, code))
                continue
            tol = spec.get("tol", {})
            vals = {"T": peak_T, "t": soak_t, "DP": dp}
            dist, ok = 0.0, True
            for k in ("T", "t", "DP"):
                if vals[k] is None:
                    ok = False
                    break
                dv = abs(float(vals[k]) - spec[k])
                if dv > tol.get(k, 0) + 1e-9:
                    ok = False
                    break
                dist += dv / (tol.get(k) or 1)
            if ok:
                hits.append((dist, code))
        return sorted(hits)[0][1] if hits else "X"


def build_code(codes: CodeBook, sys_code: str | None, values: dict, preferred_bath: str | None = None) -> str:
    """values: {'pot.Al','pot.Mg','pot.Si','out.cw','rth.T','rts.t','rth.DP'} → 'M206K'."""
    sys_code = sys_code or "X"
    pot = {el: values.get(f"pot.{el}") for el in BATH_KEYS}
    bath = codes.match_bath(sys_code, pot, preferred_bath) if sys_code != "X" else "X"
    cw = values.get("out.cw")
    cw_code = f"{min(round_half_up(float(cw) / 10), 99):02d}" if cw is not None else "XX"
    ann = codes.match_annealing(values.get("rth.T"), values.get("rts.t"), values.get("rth.DP"))
    return f"{sys_code}{bath}{cw_code}{ann}"


CODE_KEYS = ("pot.Al", "pot.Mg", "pot.Si", "out.cw", "rth.T", "rts.t", "rth.DP")


def code_from_recipe(codes: CodeBook, sys_code: str | None, recipe: dict, preferred_bath: str | None = None) -> str:
    return build_code(codes, sys_code, {k: pdict.get(recipe, k) for k in CODE_KEYS}, preferred_bath)


def panel_of(spec: Specimen) -> Specimen | None:
    """도금한 원판(자신 또는 조상). 원판을 자른 실험편·조각은 원판의 목표를 물려받습니다."""
    node = spec
    while node is not None and not node.is_panel:
        node = node.parent
    return node


def target_recipe(spec: Specimen) -> dict:
    """원판의 목표 = 공정런 기본 레시피 + 원판별 target_overrides (쿠폰·조각은 부모 원판 것을 물려받음)."""
    run = spec.process_run
    base = run.recipe if run else pdict.defaults()
    panel = panel_of(spec)
    return pdict.merge(base, panel.target_overrides if panel else None)


def specimen_code(db: Session, spec: Specimen, basis: str = "target",
                  actual_lookup: Callable[[Specimen, str], float | None] | None = None,
                  codes: CodeBook | None = None) -> str:
    """시편의 조건부. basis='actual'이면 각 키의 대표 실측값(없으면 목표)을 씁니다."""
    codes = codes or CodeBook.load(db)
    run = spec.process_run
    sys_code = run.coating_system if run else None
    preferred = run.preset.bath_code if run and run.preset else None
    rcp = target_recipe(spec)
    values = {k: pdict.get(rcp, k) for k in CODE_KEYS}
    if basis == "actual" and actual_lookup:
        for k in CODE_KEYS:
            if k == "out.cw":
                # 실측 단면 부착량 = 윗면·아랫면 실측 중 작은 값 (단면 최소 부착량 기준)
                sides = [v for v in (actual_lookup(spec, "out.cw_top"), actual_lookup(spec, "out.cw_bottom"))
                         if v is not None]
                if sides:
                    values[k] = min(sides)
                continue
            v = actual_lookup(spec, k)
            if v is not None:
                values[k] = v
    return build_code(codes, sys_code, values, preferred)


# ── 공정 계열·변형번호 ──────────────────────────────────────────────
def family_of(code: str) -> str:
    """공정 계열 = 조건부 앞 2자(계열·욕). 프리셋이 가리키는 단위와 같습니다."""
    return code[:2]


def _norm(v):
    """지문용 값: 숫자는 소수 4자리(0.5 = 0.50 = 1/2), 문자·참거짓은 그대로."""
    if v is None or isinstance(v, (bool, str)):
        return v
    try:
        f = round(float(v), 4)
    except (TypeError, ValueError):
        return str(v)
    return 0.0 if f == 0 else f


def process_values(recipe: dict) -> dict:
    """지문을 만드는 목표 공정값 {'pot.T': 590.0, 'ga.on': False, …}: 설정값 구간 전부, 부착량(out)은 뺌.
    레시피에 없는 키는 지금 사전 기본값으로 채웁니다(사전 운용 원칙: 새 키의 기본값 = 기존 운전값).
    선택 구간(NOF·GA)이 꺼져 있으면 그 구간의 값은 조건이 아니므로 뺍니다."""
    r = pdict.merge(pdict.defaults(), recipe)
    out: dict = {}
    for s in pdict.sections():
        if not s.get("setpoint", True):
            continue
        sec = r.get(s["id"]) or {}
        if s.get("opt"):
            on = bool(sec.get("on"))
            out[f"{s['id']}.on"] = on
            if not on:
                continue
        for p in s["p"]:
            v = _norm(sec.get(p["k"]))
            if v is not None:
                out[f"{s['id']}.{p['k']}"] = v
    return out


def fingerprint(values: dict) -> str:
    return hashlib.sha1(json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                        .encode("utf-8")).hexdigest()


def _key_label(key: str) -> str:
    p = pdict.param(key)
    if key.endswith(".on"):
        sec = next((s for s in pdict.sections() if s["id"] == key[:-3]), None)
        return sec["nm"] if sec else key
    return f"{p['section_nm']} {p['l']}" if p else key


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "켬" if v else "끔"
    if isinstance(v, float):
        return f"{v:g}"
    return "–" if v is None else str(v)


def describe_changes(values: dict, base: dict | None, limit: int = 120) -> str:
    """기준 대비 바뀐 값 'RTH 이슬점 -40→-42 · POT 욕온 590→610' (조건 카드 이름)."""
    if not base:
        return "기준 없음"
    parts = [f"{_key_label(k)} {_fmt(base.get(k))}→{_fmt(v)}" for k, v in values.items() if base.get(k) != v]
    parts += [f"{_key_label(k)} {_fmt(v)}→–" for k, v in base.items() if k not in values]
    text = " · ".join(parts) or "기준과 같음"
    return text if len(text) <= limit else text[:limit - 1] + "…"


def standard_of(db: Session, family: str) -> ProcessVariant | None:
    return db.scalar(select(ProcessVariant).where(ProcessVariant.family == family, ProcessVariant.seq == 0))


def _claim_ok(row: ProcessVariant, cw_code: str | None, cw) -> bool:
    """부착량 겹침 예외: 같은 번호가 같은 부착량 코드에서 다른 목표 부착량(45·50 → 05)으로 쓰였으면 이 번호는 못 씀."""
    have = (row.cw_claims or {}).get(cw_code) if cw_code else None
    return have is None or cw is None or _norm(have) == _norm(cw)


def find_variant(db: Session, family: str, fp: str, cw_code: str | None = None, cw=None) -> ProcessVariant | None:
    rows = db.scalars(select(ProcessVariant).where(ProcessVariant.family == family, ProcessVariant.fingerprint == fp)
                      .order_by(ProcessVariant.seq))
    return next((r for r in rows if _claim_ok(r, cw_code, cw)), None)


def next_seq(db: Session, family: str) -> int:
    """계열의 다음 변형번호(1~). 쓴 번호는 다시 쓰지 않으므로 가장 큰 번호 + 1."""
    return (db.scalar(select(func.max(ProcessVariant.seq)).where(ProcessVariant.family == family)) or 0) + 1


def _base_values(db: Session, family: str, fallback: dict | None) -> dict | None:
    std = standard_of(db, family)
    return std.proc_values if std else fallback


def assign_variant(db: Session, code: str, recipe: dict, *, base: dict | None = None, origin: str = "RUN",
                   run_id: int | None = None, user_id: int | None = None) -> int:
    """원판 목표 레시피 → 변형번호. 같은 계열에 같은 지문이 있으면 그 번호, 없으면 새 번호(조건 카드)를 만듭니다.
    base: 계열에 공용 표준이 없을 때 카드 이름(바뀐 값)의 비교 기준 — 보통 출발한 프리셋의 공정값."""
    family, vals = family_of(code), process_values(recipe)
    fp, cw, cw_code = fingerprint(vals), pdict.get(recipe, "out.cw"), code[2:4]
    row = find_variant(db, family, fp, cw_code, cw)
    if row is None:
        row = ProcessVariant(family=family, seq=next_seq(db, family), fingerprint=fp, proc_values=vals, cw_claims={},
                             name=describe_changes(vals, _base_values(db, family, base)), origin=origin,
                             first_run_id=run_id, created_by=user_id)
        db.add(row)
    if cw is not None and cw_code not in (row.cw_claims or {}):
        row.cw_claims = {**(row.cw_claims or {}), cw_code: _norm(cw)}
    db.flush()
    return row.seq


def preview_variants(db: Session, items: list[tuple[str, dict]], base: dict | None = None) -> list[dict]:
    """저장하지 않고 원판별 변형번호를 미리 봅니다. 새 조건은 저장 때 받을 번호를 차례로 예상합니다."""
    planned: dict[tuple[str, str, str, object], int] = {}
    nxt: dict[str, int] = {}
    out = []
    for code, recipe in items:
        family, vals = family_of(code), process_values(recipe)
        fp, cw, cw_code = fingerprint(vals), pdict.get(recipe, "out.cw"), code[2:4]
        row = find_variant(db, family, fp, cw_code, cw)
        if row is not None:
            seq, name, is_new = row.seq, row.name, False
        else:
            k = (family, fp, cw_code, _norm(cw))
            if k not in planned:
                nxt.setdefault(family, next_seq(db, family))
                planned[k], nxt[family] = nxt[family], nxt[family] + 1
            seq, name, is_new = planned[k], describe_changes(vals, _base_values(db, family, base)), True
        out.append({"code": code, "seq": seq, "label": f"{code}{seq:02d}" if seq else code,
                    "variant_id": f"{family}-{seq:02d}", "name": name, "is_new": is_new})
    return out


def register_preset(db: Session, preset: ProcessPreset, user_id: int | None = None) -> int:
    """프리셋 → 조건 카드. 계열에 공용 표준이 아직 없으면 공용 프리셋이 00(표준)이 됩니다.
    프리셋에는 부착량이 없어 저장 시점에 지문이 완성되므로 저장하면서 번호를 받습니다. 프리셋은 고치지 않고
    새로 저장하는 방식이라(6.2절) 프리셋의 번호는 바뀌지 않습니다."""
    family = f"{preset.coating_system}{preset.bath_code}"
    vals = process_values(pdict.preset_recipe(preset.overrides))
    fp = fingerprint(vals)
    row = find_variant(db, family, fp)
    if row is None:
        std = preset.scope == "PUBLIC" and standard_of(db, family) is None
        row = ProcessVariant(family=family, seq=0 if std else next_seq(db, family), fingerprint=fp, proc_values=vals,
                             cw_claims={}, name=preset.name[:120], origin=preset.scope, preset_id=preset.id,
                             created_by=user_id)
        db.add(row)
        db.flush()
    preset.variant_seq = row.seq
    return row.seq
