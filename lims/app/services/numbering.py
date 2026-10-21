"""번호 발급: 다음 빈 일련번호 제안, 일괄 발번 충돌 검사, 공정런·시험런 번호 (3.4절, D-04, D-21)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ProcessRun, Specimen, TestRun


class NumberingError(ValueError):
    pass


def used_serials(db: Session, project: str, stage: str) -> set[int]:
    rows = db.scalars(select(Specimen.serial_no).where(
        Specimen.project_code == project, Specimen.stage == stage)).all()
    return {int(s) for s in rows}


def conflicts(db: Session, project: str, stage: str, start: int, count: int) -> list[str]:
    """[start, start+count) 중 이미 쓰인 약식번호 목록. 논리 삭제된 번호도 재사용하지 않습니다."""
    if start < 0 or count < 1 or start + count - 1 > 9999:
        raise NumberingError("일련번호는 0000~9999 범위의 숫자 4자리입니다.")
    used = used_serials(db, project, stage)
    return [f"{project}-{stage}{n:04d}" for n in range(start, start + count) if n in used]


def next_free(db: Session, project: str, stage: str, count: int = 1, prefer: int | None = None) -> int:
    """연속 count개가 비어 있는 시작 번호를 제안. prefer(예: 부모 원판 번호)가 비어 있으면 그것을 우선."""
    used = used_serials(db, project, stage)

    def free_from(n: int) -> bool:
        return n + count - 1 <= 9999 and all(i not in used for i in range(n, n + count))

    if prefer is not None and free_from(prefer):
        return prefer
    n = (max(used) + 1) if used else 1
    while n <= 9999 and not free_from(n):
        n += 1
    if n > 9999:
        n = 1
        while n <= 9999 and not free_from(n):
            n += 1
    if n > 9999:
        raise NumberingError("빈 번호가 없습니다.")
    return n


def serial_str(n: int) -> str:
    return f"{n:04d}"


def next_run_no(db: Session, run_date: date) -> str:
    """공정런 번호 PR-YY-NNNN (연도별 순번)."""
    prefix = f"PR-{run_date:%y}-"
    last = db.scalar(select(func.max(ProcessRun.run_no)).where(ProcessRun.run_no.like(prefix + "%")))
    n = int(last[len(prefix):]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def next_test_run_no(db: Session, test_type: str, start: date) -> str:
    """시험런 번호 TR-{시험종류}-{YY}{순번3} (D-21)."""
    prefix = f"TR-{test_type}-{start:%y}"
    last = db.scalar(select(func.max(TestRun.test_run_no)).where(TestRun.test_run_no.like(prefix + "%")))
    n = int(last[len(prefix):]) + 1 if last else 1
    return f"{prefix}{n:03d}"
