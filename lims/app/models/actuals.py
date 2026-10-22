"""실측: 욕 분석, 실측값(1측정 1행), 대표값 캐시."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType, Num
from .lineage import BigId, ProcessRun, Specimen
from .master import User


class BathAnalysis(Base):
    __tablename__ = "bath_analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pot: Mapped[str] = mapped_column(String(20))              # 'POT-1'
    sampled_at: Mapped[datetime] = mapped_column(DateTime)
    method: Mapped[str | None] = mapped_column(String(20))    # 'ICP', '습식'
    composition: Mapped[dict] = mapped_column(JSONType)      # {"Zn":25.1,"Si":2.9,"Mg":0.46,"Al":"bal."}
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User | None] = relationship()


class ParamActual(Base):
    __tablename__ = "param_actuals"
    __table_args__ = (
        Index("idx_act_spec_key", "specimen_id", "param_key",
              postgresql_where=text("NOT is_deleted"), sqlite_where=text("is_deleted = 0")),
        Index("idx_act_run_key", "process_run_id", "param_key",
              postgresql_where=text("NOT is_deleted"), sqlite_where=text("is_deleted = 0")),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    process_run_id: Mapped[int] = mapped_column(ForeignKey("process_runs.id", ondelete="RESTRICT"))
    specimen_id: Mapped[int | None] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"))  # NULL=세션
    param_key: Mapped[str] = mapped_column(String(40))       # 'pot.T', 'out.cw_top'
    value: Mapped[float | None] = mapped_column(Num)
    value_text: Mapped[str | None] = mapped_column(String(50))
    stats: Mapped[dict | None] = mapped_column(JSONType)     # {"points":[...],"min":..,"max":..,"n":3}
    source: Mapped[str] = mapped_column(String(10))          # manual / lab / test / pv
    method: Mapped[str | None] = mapped_column(String(30))
    ref_result_id: Mapped[int | None] = mapped_column(ForeignKey("test_results.id"))
    ref_analysis_id: Mapped[int | None] = mapped_column(ForeignKey("bath_analyses.id"))
    measured_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    process_run: Mapped[ProcessRun] = relationship()
    specimen: Mapped[Specimen | None] = relationship()
    user: Mapped[User | None] = relationship()


class EffectiveParam(Base):
    """대표값 캐시 (services/actuals.py가 갱신). 검색·비교는 이 테이블을 씁니다."""
    __tablename__ = "effective_params"
    __table_args__ = (
        Index("idx_eff_key_val", "param_key", "effective"),
        Index("idx_eff_key_tgt", "param_key", "target"),
    )
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id"), primary_key=True)
    param_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    target: Mapped[float | None] = mapped_column(Num)
    actual: Mapped[float | None] = mapped_column(Num)
    effective: Mapped[float] = mapped_column(Num)
    source: Mapped[str] = mapped_column(String(10))          # target / manual / lab / test / pv
    level: Mapped[str] = mapped_column(String(6))            # target / run / P / C / S
    inherited_from: Mapped[str | None] = mapped_column(String(10))
    deviation: Mapped[float | None] = mapped_column(Num)
    out_of_tol: Mapped[bool] = mapped_column(Boolean, default=False)


class ParamActualCfg(Base):
    """관리 화면에서 고친 실측 설정(수준·허용편차·대표값 계산·방법). 시드 사전의 actual 블록 위에 덮어씁니다.
    코드 폴더의 JSON에 쓰면 재배포로 사라지고 백업·다중 worker에 반영되지 않아 DB에 둡니다.
    rev는 전체에서 증가하는 번호로, 각 worker가 요청마다 바뀌었는지 확인합니다(param_dict.sync)."""
    __tablename__ = "param_actual_cfg"
    param_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    cfg: Mapped[dict | None] = mapped_column(JSONType)       # None = actual 블록 없음
    rev: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
