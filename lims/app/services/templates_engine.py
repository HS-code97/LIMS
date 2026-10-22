"""시험 템플릿 → 입력 폼 정의·검증 (9장, D-27: 모든 필드 선택 입력, 템플릿 외 키는 저장 거부)."""
from __future__ import annotations

import math

from ..models import TestTemplate


class MetricsError(ValueError):
    def __init__(self, errors: list[str], unknown: list[str] | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.unknown = unknown or []


def validate_metrics(tpl: TestTemplate, raw: dict) -> tuple[dict, list[str]]:
    """(정리된 metrics, 경고 목록). 템플릿 외 키는 버리고 경고, 형식 오류는 MetricsError."""
    fields = {f["key"]: f for f in tpl.field_schema}
    clean: dict = {}
    warnings: list[str] = []
    errors: list[str] = []
    for k, v in (raw or {}).items():
        f = fields.get(k)
        if f is None:
            warnings.append(f"템플릿 {tpl.code} v{tpl.version}에 없는 항목 '{k}'은 저장하지 않았습니다.")
            continue
        if v is None or (isinstance(v, str) and v.strip() == ""):
            continue
        t = f.get("type", "text")
        if t == "number":
            try:
                fv = float(str(v).replace(",", "").replace("%", "").strip())
            except ValueError:
                errors.append(f"{f['label']}: 숫자가 아닙니다 ({v!r})")
                continue
            if not math.isfinite(fv):          # 'nan'·'inf'는 float()가 받아 주지만 모든 min/max 비교를 통과함
                errors.append(f"{f['label']}: 숫자가 아닙니다 ({v!r})")
                continue
            if "min" in f and f["min"] is not None and fv < f["min"]:
                errors.append(f"{f['label']}: {fv:g} < 최소 {f['min']}")
                continue
            if "max" in f and f["max"] is not None and fv > f["max"]:
                errors.append(f"{f['label']}: {fv:g} > 최대 {f['max']}")
                continue
            clean[k] = int(fv) if fv.is_integer() else fv
        elif t == "select":
            sv = str(v).strip()
            if f.get("options") and sv not in f["options"]:
                errors.append(f"{f['label']}: '{sv}'은 선택지({', '.join(f['options'])})에 없습니다")
                continue
            clean[k] = sv
        elif t == "bool":
            clean[k] = str(v).lower() in ("1", "true", "y", "yes", "on", "o", "예")
        else:
            clean[k] = str(v).strip()
    if errors:
        raise MetricsError(errors)
    return clean, warnings


def condition_defaults(tpl: TestTemplate) -> dict:
    return {c["key"]: c.get("default") for c in (tpl.condition_schema or []) if c.get("default") is not None}


def cell_text(tpl: TestTemplate, metrics: dict | None) -> str:
    """그리드 셀 표시 문자열 (grid:true 필드)."""
    if not metrics:
        return ""
    parts = []
    for f in tpl.grid_fields:
        v = metrics.get(f["key"])
        if v is None:
            continue
        unit = f.get("unit", "")
        parts.append(f"{v:g}{unit}" if isinstance(v, (int, float)) else str(v))
    return " · ".join(parts)
