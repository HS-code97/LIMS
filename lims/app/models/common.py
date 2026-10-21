"""공통: 첨부 파일, 감사 로그."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType
from .activity import TestResult
from .lineage import BigId, ProcessRun, Specimen
from .master import User


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("idx_att_unmatched", "uploaded_by",
              postgresql_where=text("specimen_id IS NULL"), sqlite_where=text("specimen_id IS NULL")),
        Index("idx_att_spec", "specimen_id"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    specimen_id: Mapped[int | None] = mapped_column(ForeignKey("specimens.id"))     # NULL = 미분류
    result_id: Mapped[int | None] = mapped_column(ForeignKey("test_results.id"))
    process_run_id: Mapped[int | None] = mapped_column(ForeignKey("process_runs.id"))
    kind: Mapped[str | None] = mapped_column(String(10))       # PHOTO / SEM / RAW / DOC
    path: Mapped[str] = mapped_column(Text)
    thumb_path: Mapped[str | None] = mapped_column(Text)
    original_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(10), default="upload")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    specimen: Mapped[Specimen | None] = relationship()
    result: Mapped[TestResult | None] = relationship()
    process_run: Mapped[ProcessRun | None] = relationship()
    uploader: Mapped[User | None] = relationship()

    @property
    def is_image(self) -> bool:
        return bool(self.thumb_path)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(40))
    row_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(10))     # INSERT / UPDATE / DELETE(논리)
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
