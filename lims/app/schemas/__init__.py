"""Pydantic v2 입출력 스키마."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SeriesSpec(BaseModel):
    key: str                                  # 'ak.P'
    values: list[float]


class ProcessRunIn(BaseModel):
    """POST /api/process-runs (6.3절)."""
    source: str = "manual"
    dict_version: str
    preset_id: int | None = None
    coating_system: str | None = None         # 프리셋 없이 저장할 때(복제 등) 계열 코드
    project_code: str
    material_id: int | None = None
    run_date: date
    coating_weight_target: float = Field(gt=0, le=300)
    panel_count: int = Field(ge=1, le=200)
    serial_start: int = Field(ge=0, le=9999)
    recipe: dict[str, dict[str, Any]]
    series: SeriesSpec | list[SeriesSpec] | None = None
    changed_from_preset: list[str] = []
    warnings: list[str] = []
    note: str = ""
    confirm_out_of_range: bool = False       # 허용 범위 밖 값 저장 전 확인(5.2절)

    @field_validator("project_code")
    @classmethod
    def _proj(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 4:
            raise ValueError("과제코드는 4자입니다 (예: 26P4)")
        return v

    def series_list(self) -> list[SeriesSpec]:
        if self.series is None:
            return []
        return self.series if isinstance(self.series, list) else [self.series]


class ActualRow(BaseModel):
    key: str                                  # 'pot.T'
    value: float | str | None = None
    specimen: str | None = None               # 약식번호, 없으면 세션 공통
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
    stage: str                                # C / S
    count: int = Field(ge=1, le=200)
    serial_start: int = Field(ge=0, le=9999)
    sample_position: str | None = None
    rolling_direction: str | None = None
    surface_side: str | None = None
    size_text: str | None = None
    storage_location: str | None = None
    mark_parent_consumed: bool = False


class EventIn(BaseModel):
    event_type: str
    event_date: date
    params: dict[str, Any] = {}


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
