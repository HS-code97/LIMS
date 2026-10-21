"""기준 정보: 팀, 사용자, 과제, 마스터 코드, 공정 프리셋, 시험 템플릿."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emp_no: Mapped[str] = mapped_column(String(20), unique=True)     # 사번 (로그인 ID)
    name: Mapped[str] = mapped_column(String(50))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    role: Mapped[str] = mapped_column(String(10), default="USER")    # USER / ADMIN
    pw_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    team: Mapped[Team | None] = relationship()

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


class Project(Base):
    __tablename__ = "projects"
    project_code: Mapped[str] = mapped_column(String(4), primary_key=True)   # '26P4', '26X0'
    company_project_no: Mapped[str | None] = mapped_column(String(20))      # '2026P1234'
    project_name: Mapped[str] = mapped_column(String(150))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_common: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    manager: Mapped[User | None] = relationship()

    @property
    def label(self) -> str:
        return f"{self.project_code} = {self.company_project_no}" if self.company_project_no else self.project_code


class MasterCode(Base):
    __tablename__ = "master_codes"
    category: Mapped[str] = mapped_column(String(20), primary_key=True)  # COATING_SYS / BATH / ANNEALING
    code: Mapped[str] = mapped_column(String(4), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    spec: Mapped[dict | None] = mapped_column(JSONType)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProcessPreset(Base):
    __tablename__ = "process_presets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    scope: Mapped[str] = mapped_column(String(10))           # PUBLIC / TEAM / PERSONAL
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    coating_system: Mapped[str] = mapped_column(String(1))
    bath_code: Mapped[str] = mapped_column(String(1))
    overrides: Mapped[dict] = mapped_column(JSONType)        # 사전 기본값과 다른 값만
    dict_version: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    owner: Mapped[User | None] = relationship()


class TestTemplate(Base):
    __tablename__ = "test_templates"
    __table_args__ = (UniqueConstraint("code", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    test_type: Mapped[str] = mapped_column(String(20))
    field_schema: Mapped[list] = mapped_column(JSONType)
    condition_schema: Mapped[list | None] = mapped_column(JSONType)
    default_cycles: Mapped[int | None] = mapped_column(Integer)
    default_interval_days: Mapped[int | None] = mapped_column(Integer)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    team: Mapped[Team | None] = relationship()

    @property
    def grid_fields(self) -> list[dict]:
        g = [f for f in self.field_schema if f.get("grid")]
        return g or [f for f in self.field_schema if f.get("type") == "number"][:1]
