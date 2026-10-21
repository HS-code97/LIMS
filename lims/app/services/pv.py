"""HMI 실행기록(PV) 수신 (6.5절, 3단계).

HMI가 원판 1매의 사이클이 끝날 때마다 PV 시계열 CSV를 보냅니다.
  CSV 열: t(초) | segment(선택, 구간 id: rth, rts, pot …) | 태그 열(RTH.TT01, POT.TT01 …)
파라미터 사전의 actual.pv_tag로 태그 → 키를 찾고, segment 열이 있으면 그 키의 구간 행만,
없으면 '유지 구간'(최댓값 근처 평탄부: 값이 max − 허용편차 이상인 행)으로 평균·최소·최대를 계산해
param_actuals에 출처 pv로 넣습니다. 원본 CSV는 공정런 첨부(RAW)로 보관합니다.
"""
from __future__ import annotations

import csv
import io
import statistics

from . import param_dict as pdict


def tag_map() -> dict[str, str]:
    return {(p.get("actual") or {}).get("pv_tag"): k for k, p in pdict.params().items()
            if (p.get("actual") or {}).get("pv_tag")}


def summarize(text: str) -> tuple[dict[str, dict], list[str]]:
    """CSV 본문 → {키: {mean,min,max,n}}, 경고 목록."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return {}, ["PV 파일에 데이터 행이 없습니다."]
    tags = tag_map()
    cols = {c.strip(): c for c in rows[0].keys() if c}
    seg_col = next((cols[c] for c in cols if c.lower() == "segment"), None)
    out, warns = {}, []
    for tag, key in tags.items():
        col = cols.get(tag)
        if col is None:
            continue
        sec = key.split(".")[0]
        vals = []
        for r in rows:
            if seg_col and (r.get(seg_col) or "").strip().lower() != sec:
                continue
            try:
                vals.append(float(r[col]))
            except (TypeError, ValueError):
                pass
        if not seg_col and vals:
            cfg = pdict.actual_cfg(key)
            band = cfg.get("tol", 5)
            hi = max(vals) if not key.endswith(".DP") else None
            vals = [v for v in vals if hi is None or v >= hi - band]
        if not vals:
            warns.append(f"{tag}: 유효한 값이 없습니다.")
            continue
        out[key] = {"mean": round(statistics.fmean(vals), 3), "min": min(vals), "max": max(vals), "n": len(vals)}
    unknown = [c for c in cols if c.lower() not in ("t", "time", "segment") and c not in tags]
    if unknown:
        warns.append("사전 pv_tag에 없는 열은 무시: " + ", ".join(unknown))
    return out, warns
