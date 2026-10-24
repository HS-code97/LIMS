"""Pydantic v2 입출력 스키마."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict, Field, field_validator


class BaseModel(_BaseModel):
    # JSON의 NaN·Infinity 숫자를 받지 않습니다(pydantic 기본은 허용 → min/max 비교를 모두 통과).
    model_config = ConfigDict(allow_inf_nan=False)


class SeriesSpec(BaseModel):
    key: str                                  # 'ak.P'
    values: list[float]


def _project_code(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip().upper()
    if not re.fullmatch(r"[A-Z]\d", v):
        raise ValueError("과제코드는 영문 1자리 + 숫자 1자리입니다 (예: A6)")
    return v


class ProcessRunIn(BaseModel):
    """POST /api/process-runs (6.3절). 도금할 시편(블랭크 등)의 각인번호를 받아 같은 레코드를 도금 단계로 올립니다
    (시편번호 체계 3.1절 — 도금은 번호를 새로 만들지 않음)."""
    source: str = "manual"
    dict_version: str
    preset_id: int | None = None
    coating_system: str | None = None         # 프리셋 없이 저장할 때(복제 등) 계열 코드
    project_code: str
    material_id: int | None = None
    run_date: date
    coating_weight_target: float = Field(gt=0, le=300)
    specimens: list[str] = Field(min_length=1, max_length=200)   # 각인번호 'QV3-A01' …
    recipe: dict[str, dict[str, Any]]
    series: SeriesSpec | list[SeriesSpec] | None = None
    changed_from_preset: list[str] = []
    warnings: list[str] = []
    note: str = ""
    confirm_out_of_range: bool = False       # 허용 범위 밖 값 저장 전 확인(5.2절)

    @field_validator("project_code")
    @classmethod
    def _proj(cls, v: str) -> str:
        return _project_code(v) or ""

    @field_validator("specimens")
    @classmethod
    def _marks(cls, v: list[str]) -> list[str]:
        out = [s.strip().upper() for s in v if s and s.strip()]
        if len(set(out)) != len(out):
            raise ValueError("같은 시편이 두 번 들어 있습니다.")
        return out

    @property
    def panel_count(self) -> int:
        return len(self.specimens)

    def series_list(self) -> list[SeriesSpec]:
        if self.series is None:
            return []
        return self.series if isinstance(self.series, list) else [self.series]


class TargetChange(BaseModel):
    key: str                                  # 'out.cw'
    value: float
    specimen: str | None = None               # 원판 각인번호 (없으면 공정런 기본 레시피)


class TargetCorrectionIn(BaseModel):
    """POST /api/process-runs/{run_no}/targets — 저장한 목표값 정정."""
    changes: list[TargetChange] = Field(min_length=1)
    reason: str
    confirm_out_of_range: bool = False


class ActualRow(BaseModel):
    key: str                                  # 'pot.T'
    value: float | str | None = None
    specimen: str | None = None               # 각인번호, 없으면 세션 공통
    method: str | None = None
    points: list[float] | None = None
    measured_at: datetime | None = None
    note: str | None = None
    mode: str = "set"                         # set = 셀 덮어쓰기(실측 탭), add = 측정 행 추가


class ActualsIn(BaseModel):
    rows: list[ActualRow]
    source: str = "manual"


class PasteIn(BaseModel):
    text: str
    dry_run: bool = False


class BathAnalysisIn(BaseModel):
    pot: str
    sampled_at: datetime
    method: str | None = None
    composition: dict[str, float | str]
    note: str | None = None


class ApplyIn(BaseModel):
    run_nos: list[str]


class SplitIn(BaseModel):
    """자르기: 전폭 → 블랭크(조각 번호 01~99), 그 뒤는 후절단(1~21번째 = A~Y) → 분석조각(1~9).
    start는 n번째 번호이며 영문 자리는 marking.letter_of로 바꿉니다. 자리별 상한은 numbering.LEVELS가 검사."""
    count: int = Field(ge=1, le=99)
    start: int = Field(ge=1, le=99)            # 새 자리의 시작 번호
    project_code: str | None = None            # 자식이 쓸 과제 (없으면 부모 과제)
    sample_position: str | None = None
    rolling_direction: str | None = None
    surface_side: str | None = None
    size_text: str | None = None
    storage_location: str | None = None
    mark_parent_consumed: bool = False

    @field_validator("project_code")
    @classmethod
    def _proj(cls, v: str | None) -> str | None:
        return _project_code(v)


class IntakeIn(BaseModel):
    """전폭시편 입고 (A 단계). 현장 코일번호 CQV3141T → 코일코드 QV3, 전폭 1~21번째(A~Y)."""
    coil_no: str
    coil_code: str | None = None               # 비우면 제안값
    project_code: str
    count: int = Field(ge=1, le=21)
    sheet_start: int | None = Field(default=None, ge=1, le=21)
    coil_position: str | None = None           # 비우면 코일번호 끝자리(채취위치)
    steel_grade: str | None = None
    thickness_mm: float | None = Field(default=None, gt=0, le=20)
    size_text: str | None = "1200x600"
    storage_location: str | None = None
    received_date: date | None = None
    note: str | None = None

    @field_validator("project_code")
    @classmethod
    def _proj(cls, v: str | None) -> str | None:
        return _project_code(v)


class TreatIn(BaseModel):
    """자르지 않는 공정: 열처리(HEAT → D) · 전처리(PRETREAT, 단계 유지) · 도장(PAINT → E). code = 코드표 2자리."""
    kind: str
    code: str
    event_date: date
    project_code: str | None = None
    params: dict[str, Any] = {}

    @field_validator("project_code")
    @classmethod
    def _proj(cls, v: str | None) -> str | None:
        return _project_code(v)


class EventIn(BaseModel):
    event_type: str
    event_date: date
    params: dict[str, Any] = {}
    code: str | None = None                    # HEAT·PRETREAT·PAINT 이벤트의 코드표 2자리


class Boarding(BaseModel):
    short_id: str
    slot: str | None = None


class TestRunIn(BaseModel):
    template_id: int
    equipment: str | None = None
    conditions: dict[str, Any] = {}
    start_date: date
    specimens: list[Boarding] = []
    note: str | None = None


class ResultIn(BaseModel):
    metrics: dict[str, Any]
    eval_date: date | None = None


class PresetIn(BaseModel):
    name: str
    scope: str = "PERSONAL"                   # TEAM / PERSONAL (PUBLIC은 관리자)
    coating_system: str
    bath_code: str
    recipe: dict[str, dict[str, Any]]


class LinkIn(BaseModel):
    short_id: str
    test_run_no: str | None = None
    cycle_no: int | None = None
