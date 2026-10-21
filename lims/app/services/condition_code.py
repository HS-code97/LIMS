"""조건부 5자 자동 생성 (3.2절, D-11~D-13, D-31, D-32).

자리: 1 도금 계열 · 2 욕 조성 숫자(허용오차 밖이면 X) · 3~4 단면 부착량 round_half_up(g/m²÷10) · 5 소둔 코드
각인·라벨에는 목표 기준(basis="target")만 씁니다. 실측 기준은 시편 상세 표시용입니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MasterCode, Specimen
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
    node = spec
    while node is not None and node.stage != "P":
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
