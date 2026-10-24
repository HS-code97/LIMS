"""혈통: 원소재 로트, 공정런, 시편, 공정 이벤트."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String,
                        Text, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType, Num
from .master import Project, ProcessPreset, User

# SQLite는 BIGINT PRIMARY KEY를 자동 증가로 다루지 않으므로 INTEGER로 변형
BigId = BigInteger().with_variant(Integer(), "sqlite")


class Material(Base):
    """현장 코일. coil_no는 채취위치를 뺀 현장 코일번호(CQV3141T → CQV3141), coil_code는 각인용 3자리."""
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coil_no: Mapped[str] = mapped_column(String(50), unique=True)   # 'CQV3141'
    coil_code: Mapped[str | None] = mapped_column(String(3), unique=True)   # 'QV3' (시편번호 체계 3.5절)
    steel_grade: Mapped[str | None] = mapped_column(String(50))
    thickness_mm: Mapped[float | None] = mapped_column(Num)
    composition: Mapped[dict | None] = mapped_column(JSONType)
    received_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)

    @property
    def label(self) -> str:
        t = f" {self.thickness_mm:g}T" if self.thickness_mm else ""
        code = f"[{self.coil_code}] " if self.coil_code else ""
        return f"{code}{self.coil_no} {self.steel_grade or ''}{t}".strip()


class ProcessRun(Base):
    __tablename__ = "process_runs"
    __table_args__ = (Index("idx_pr_recipe", "recipe", postgresql_using="gin"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    run_no: Mapped[str] = mapped_column(String(20), unique=True)      # 'PR-26-0137'
    run_date: Mapped[date] = mapped_column(Date)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    project_code: Mapped[str | None] = mapped_column(ForeignKey("projects.project_code"))
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"))
    preset_id: Mapped[int | None] = mapped_column(ForeignKey("process_presets.id"))
    source: Mapped[str] = mapped_column(String(10), default="manual")
    dict_version: Mapped[str] = mapped_column(String(20))
    recipe: Mapped[dict] = mapped_column(JSONType)
    changed_from_preset: Mapped[list | None] = mapped_column(JSONType)
    coating_weight_target: Mapped[float | None] = mapped_column(Num)
    base_condition_code: Mapped[str] = mapped_column(String(5))
    pv_log_path: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    # 저장 당시 점검 경고 (설계서 6.3 페이로드의 warnings, 기록용)
    warnings: Mapped[list | None] = mapped_column(JSONType)
    coating_system: Mapped[str | None] = mapped_column(String(1))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    operator: Mapped[User | None] = relationship()
    project: Mapped[Project | None] = relationship()
    material: Mapped[Material | None] = relationship()
    preset: Mapped[ProcessPreset | None] = relationship()
    # 이 공정런에서 도금한 시편(원판). 원판을 자른 실험편도 process_run_id를 물려받으므로 is_panel로 가립니다.
    panels: Mapped[list["Specimen"]] = relationship(
        primaryjoin="and_(Specimen.process_run_id == ProcessRun.id, Specimen.is_panel == True, Specimen.is_deleted == False)",
        order_by="Specimen.short_id", viewonly=True)


class Specimen(Base):
    """물리적 시편 1개 = 레코드 1개 (시편번호 체계 3.1절).
    short_id = 각인번호(QV3-A02-A-3): 평생 불변인 유일키. 도금·열처리·전처리·도장은 같은 레코드의
    단계(stage)·거친 공정(steps)을 바꾸고 이력(SpecimenEvent)을 남깁니다. 자르면 자식 레코드가 생깁니다."""
    __tablename__ = "specimens"
    __table_args__ = (
        CheckConstraint("stage IN ('A','B','C','D','E')", name="ck_stage"),
        CheckConstraint("length(coil_code) = 3", name="ck_coil_code_len"),
        CheckConstraint("length(branch) IN (1, 3)", name="ck_branch_len"),
        Index("idx_spec_parent", "parent_id"),
        Index("idx_spec_run", "process_run_id"),
        Index("idx_spec_owner", "owner_id"),
        Index("idx_spec_coil", "coil_code"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    project_code: Mapped[str] = mapped_column(ForeignKey("projects.project_code"))   # 지금 쓰는 과제
    stage: Mapped[str] = mapped_column(String(1))
    coil_code: Mapped[str] = mapped_column(String(3))
    branch: Mapped[str] = mapped_column(String(3))           # 전폭 '1' / 조각 '102'
    cut_no: Mapped[str | None] = mapped_column(String(2))    # 후절단(실험편) '01'
    piece_no: Mapped[str | None] = mapped_column(String(1))  # 분석조각 '3'
    short_id: Mapped[str] = mapped_column(String(16), unique=True)   # 각인번호
    coil_position: Mapped[str | None] = mapped_column(String(2))     # 현장 채취위치 (CQV3141T의 T)
    steps: Mapped[list | None] = mapped_column(JSONType)     # 거친 공정 [{"k": "PLATE"}, {"k": "PAINT", "code": "12"}]
    is_panel: Mapped[bool] = mapped_column(Boolean, default=False)   # 공정런에서 직접 도금한 시편
    legacy_id: Mapped[str | None] = mapped_column(String(20), index=True)   # v2.3 약식번호(26P4-P0101) — 이관 시편 조회용
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"))
    process_run_id: Mapped[int | None] = mapped_column(ForeignKey("process_runs.id", ondelete="RESTRICT"))
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    target_overrides: Mapped[dict | None] = mapped_column(JSONType)
    condition_code: Mapped[str | None] = mapped_column(String(5))
    sample_position: Mapped[str | None] = mapped_column(String(10))
    rolling_direction: Mapped[str | None] = mapped_column(String(5))
    surface_side: Mapped[str | None] = mapped_column(String(10))
    size_text: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12), default="AVAILABLE")
    storage_location: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    parent: Mapped["Specimen | None"] = relationship(remote_side="Specimen.id", back_populates="children")
    children: Mapped[list["Specimen"]] = relationship(back_populates="parent", order_by="Specimen.short_id")
    process_run: Mapped[ProcessRun | None] = relationship()
    material: Mapped[Material | None] = relationship()
    owner: Mapped[User | None] = relationship()
    project: Mapped[Project] = relationship()

    def set_mark(self) -> None:
        from ..services.marking import mark_id
        self.short_id = mark_id(self.coil_code, self.branch, self.cut_no, self.piece_no)

    @property
    def tail(self) -> list[str]:
        from ..services.marking import tail_blocks
        return tail_blocks(self.steps, self.condition_code)

    @property
    def display_id(self) -> str:
        """전체번호 = 코일-과제-단계-가지[-후절단][-조각][-꼬리…] (DB·화면·라벨용, 각인하지 않음)."""
        from ..services.marking import full_id
        return full_id(self.coil_code, self.project_code, self.stage, self.branch, self.cut_no, self.piece_no,
                       self.tail)

    @property
    def engraved_label(self) -> str:
        """각인하는 글자 = 각인번호 (꼬리·과제·단계는 각인하지 않음, 시편번호 체계 3.2절)."""
        return self.short_id

    @property
    def stage_name(self) -> str:
        from ..services.marking import STAGES
        return STAGES.get(self.stage, self.stage)

    @property
    def kind_name(self) -> str:
        """모양 이름: 전폭시편 / 블랭크(도금 전) · 판(도금 등 이후) / 실험편 / 분석조각."""
        if self.piece_no:
            return "분석조각"
        if self.cut_no:
            return "실험편"
        if len(self.branch or "") == 1:
            return "전폭시편"
        return "블랭크" if self.stage == "B" else "판"

    def has_step(self, kind: str) -> bool:
        return any(s.get("k") == kind for s in self.steps or [])


class SpecimenEvent(Base):
    __tablename__ = "specimen_events"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id"))
    # PLATE / HEAT / PRETREAT / PAINT (단계·꼬리 변화) · USE (다른 과제·사람이 씀) / MOVE / SCRAP / NOTE
    event_type: Mapped[str] = mapped_column(String(20))
    params: Mapped[dict | None] = mapped_column(JSONType)
    event_date: Mapped[date] = mapped_column(Date)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User | None] = relationship()
    specimen: Mapped[Specimen] = relationship()
