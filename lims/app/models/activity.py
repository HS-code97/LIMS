"""활동: 시험런, 탑승(N:M), 시험 결과."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType
from .lineage import BigId, Specimen
from .master import TestTemplate, User


class TestRun(Base):
    __tablename__ = "test_runs"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    test_run_no: Mapped[str] = mapped_column(String(20), unique=True)   # 'TR-CCT-26001'
    test_type: Mapped[str] = mapped_column(String(20))
    template_id: Mapped[int] = mapped_column(ForeignKey("test_templates.id"))
    equipment: Mapped[str | None] = mapped_column(String(50))
    conditions: Mapped[dict | None] = mapped_column(JSONType)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), default="RUNNING")  # RUNNING / DONE
    # 그리드 열(회차) 수. 템플릿 기본값으로 시작하고 연구원이 [+열]로 늘립니다.
    cycles: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)

    template: Mapped[TestTemplate] = relationship()
    owner: Mapped[User | None] = relationship()
    boardings: Mapped[list["RunSpecimen"]] = relationship(back_populates="test_run")


class RunSpecimen(Base):
    __tablename__ = "run_specimens"
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), primary_key=True)
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"), primary_key=True)
    slot: Mapped[str | None] = mapped_column(String(20))
    loaded_at: Mapped[date | None] = mapped_column(Date)
    unloaded_at: Mapped[date | None] = mapped_column(Date)
    # 탑승 당시 전체번호(과제·단계·꼬리 포함). 시편은 나중에 도장 등으로 바뀌어도 시험 기록은 그때 상태를 남김.
    display_at: Mapped[str | None] = mapped_column(String(60))

    test_run: Mapped[TestRun] = relationship(back_populates="boardings")
    specimen: Mapped[Specimen] = relationship()


class TestResult(Base):
    __tablename__ = "test_results"
    __table_args__ = (
        UniqueConstraint("test_run_id", "specimen_id", "cycle_no"),
        Index("idx_res_spec", "specimen_id"),
        Index("idx_res_metrics", "metrics", postgresql_using="gin"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"))
    cycle_no: Mapped[int] = mapped_column(Integer, default=0)
    eval_date: Mapped[date | None] = mapped_column(Date)
    inspector_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("test_templates.id"))
    metrics: Mapped[dict | None] = mapped_column(JSONType)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    test_run: Mapped[TestRun] = relationship()
    specimen: Mapped[Specimen] = relationship()
    template: Mapped[TestTemplate] = relationship()
    inspector: Mapped[User | None] = relationship()
