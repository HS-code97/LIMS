"""혈통: 원소재 로트, 공정런, 시편, 공정 이벤트."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType, Num
from .master import Project, ProcessPreset, User

# SQLite는 BIGINT PRIMARY KEY를 자동 증가로 다루지 않으므로 INTEGER로 변형
BigId = BigInteger().with_variant(Integer(), "sqlite")


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coil_no: Mapped[str] = mapped_column(String(50), unique=True)   # 'POS-26-8891'
    steel_grade: Mapped[str | None] = mapped_column(String(50))
    thickness_mm: Mapped[float | None] = mapped_column(Num)
    composition: Mapped[dict | None] = mapped_column(JSONType)
    received_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)

    @property
    def label(self) -> str:
        t = f" {self.thickness_mm:g}T" if self.thickness_mm else ""
        return f"{self.coil_no} {self.steel_grade or ''}{t}".strip()


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
    panels: Mapped[list["Specimen"]] = relationship(
        primaryjoin="and_(Specimen.process_run_id == ProcessRun.id, Specimen.stage == 'P', Specimen.is_deleted == False)",
        order_by="Specimen.serial_no", viewonly=True)


class Specimen(Base):
    __tablename__ = "specimens"
    __table_args__ = (
        UniqueConstraint("project_code", "stage", "serial_no", name="uq_short"),
        CheckConstraint("stage IN ('P','C','S')", name="ck_stage"),
        CheckConstraint("length(serial_no) = 4", name="ck_serial_len"),
        Index("idx_spec_parent", "parent_id"),
        Index("idx_spec_run", "process_run_id"),
        Index("idx_spec_owner", "owner_id"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    project_code: Mapped[str] = mapped_column(ForeignKey("projects.project_code"))
    stage: Mapped[str] = mapped_column(String(1))
    serial_no: Mapped[str] = mapped_column(String(4))
    short_id: Mapped[str] = mapped_column(
        String(10), Computed("project_code || '-' || stage || serial_no", persisted=True), unique=True)
    engraved_label: Mapped[str | None] = mapped_column(String(16))
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
    children: Mapped[list["Specimen"]] = relationship(back_populates="parent", order_by="Specimen.serial_no")
    process_run: Mapped[ProcessRun | None] = relationship()
    material: Mapped[Material | None] = relationship()
    owner: Mapped[User | None] = relationship()
    project: Mapped[Project] = relationship()

    STAGE_NAMES = {"P": "도금원판", "C": "시험편", "S": "분석 조각"}

    @property
    def display_id(self) -> str:
        """정식번호 16자 = 조건부 + 약식번호 (표시용 라벨)."""
        return f"{self.condition_code or 'XXXXX'}-{self.short_id}"

    @property
    def stage_name(self) -> str:
        return self.STAGE_NAMES.get(self.stage, self.stage)

    @property
    def label_mismatch(self) -> bool:
        return bool(self.engraved_label) and self.engraved_label != self.display_id


class SpecimenEvent(Base):
    __tablename__ = "specimen_events"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id"))
    event_type: Mapped[str] = mapped_column(String(20))   # POST_TREAT / PAINT / HEAT / MOVE / SCRAP / NOTE
    params: Mapped[dict | None] = mapped_column(JSONType)
    event_date: Mapped[date] = mapped_column(Date)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User | None] = relationship()
    specimen: Mapped[Specimen] = relationship()
