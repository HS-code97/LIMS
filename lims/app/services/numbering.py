"""번호 발급 (시편번호 체계 3.2·3.6절): 전폭·조각·후절단·분석조각의 다음 빈 번호 제안, 일괄 발번 충돌 검사,
공정런·시험런 번호 (D-21).

번호는 시스템이 다음 빈 번호를 제안하고 사람이 고칠 수 있습니다(D-04). 유일성은 각인번호(Specimen.short_id)의
UNIQUE 제약이 최종 보장합니다 — 동시 저장 경합은 409 (main.py)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from ..errors import Invalid
from ..models import ProcessRun, Specimen, TestRun
from . import marking

# 단계별 번호 범위: (이름, 최솟값, 최댓값)
LEVELS = {"sheet": ("전폭번호", 1, 9), "branch": ("조각 번호", 1, 99), "cut": ("후절단 번호", 1, 99),
          "piece": ("분석조각 번호", 1, len(marking.PIECE_CHARS))}


class NumberingError(Invalid):
    """번호 범위 오류 (422)."""


def child_level(parent: Specimen) -> str | None:
    """parent를 자르면 생기는 번호 자리. 분석조각은 더 자를 수 없음(None)."""
    if len(parent.branch) == 1:
        return "branch"
    if parent.cut_no is None:
        return "cut"
    if parent.piece_no is None:
        return "piece"
    return None


def child_parts(parent: Specimen, n: int) -> dict:
    level = child_level(parent)
    if level == "branch":
        return {"branch": f"{parent.branch}{n:02d}", "cut_no": None, "piece_no": None}
    if level == "cut":
        return {"branch": parent.branch, "cut_no": f"{n:02d}", "piece_no": None}
    if level == "piece":
        return {"branch": parent.branch, "cut_no": parent.cut_no, "piece_no": marking.piece_char(n)}
    raise NumberingError(f"{parent.short_id}은 분석조각이라 더 자를 수 없습니다.")


def _rows(db: Session, coil: str):
    return db.execute(select(Specimen.branch, Specimen.cut_no, Specimen.piece_no)
                      .where(Specimen.coil_code == coil)).all()


def used_sheets(db: Session, coil: str) -> set[int]:
    """이 코일에서 쓴 전폭번호 (논리 삭제된 번호도 다시 쓰지 않음)."""
    return {int(branch[0]) for branch, _, _ in _rows(db, coil) if branch}


def used_child_nos(db: Session, parent: Specimen) -> set[int]:
    level = child_level(parent)
    out = set()
    for branch, cut, piece in _rows(db, parent.coil_code):
        if level == "branch" and len(branch) == 3 and branch[0] == parent.branch:
            out.add(int(branch[1:]))
        elif level == "cut" and branch == parent.branch and cut is not None:
            out.add(int(cut))
        elif level == "piece" and branch == parent.branch and cut == parent.cut_no and piece is not None:
            out.add(marking.piece_index(piece))
    return out


def _check_range(level: str, start: int, count: int) -> None:
    name, lo, hi = LEVELS[level]
    if count < 1 or start < lo or start + count - 1 > hi:
        raise NumberingError(f"{name}는 {lo}~{hi} 범위입니다 (시작 {start}, {count}개).")


def _next(used: set[int], level: str, count: int, prefer: int | None) -> int:
    _, lo, hi = LEVELS[level]

    def free_from(n: int) -> bool:
        return lo <= n and n + count - 1 <= hi and all(i not in used for i in range(n, n + count))

    if prefer is not None and free_from(prefer):
        return prefer
    n = (max(used) + 1) if used else lo
    while n <= hi and not free_from(n):
        n += 1
    if n > hi:
        n = lo
        while n <= hi and not free_from(n):
            n += 1
    if n > hi:
        raise NumberingError(f"빈 {LEVELS[level][0]}가 {count}개 연속으로 없습니다.")
    return n


def sheet_conflicts(db: Session, coil: str, start: int, count: int) -> list[str]:
    _check_range("sheet", start, count)
    used = used_sheets(db, coil)
    return [marking.mark_id(coil, str(n)) for n in range(start, start + count) if n in used]


def next_sheet(db: Session, coil: str, count: int = 1) -> int:
    return _next(used_sheets(db, coil), "sheet", count, None)


def child_conflicts(db: Session, parent: Specimen, start: int, count: int) -> list[str]:
    level = child_level(parent)
    if level is None:
        raise NumberingError(f"{parent.short_id}은 분석조각이라 더 자를 수 없습니다.")
    _check_range(level, start, count)
    used = used_child_nos(db, parent)
    out = []
    for n in range(start, start + count):
        if n in used:
            p = child_parts(parent, n)
            out.append(marking.mark_id(parent.coil_code, p["branch"], p["cut_no"], p["piece_no"]))
    return out


def next_child(db: Session, parent: Specimen, count: int = 1, prefer: int | None = None) -> int:
    level = child_level(parent)
    if level is None:
        raise NumberingError(f"{parent.short_id}은 분석조각이라 더 자를 수 없습니다.")
    return _next(used_child_nos(db, parent), level, count, prefer)


def label_of(parent: Specimen, n: int) -> str:
    p = child_parts(parent, n)
    return marking.mark_id(parent.coil_code, p["branch"], p["cut_no"], p["piece_no"])


def _next_seq(db: Session, col, prefix: str) -> int:
    """prefix 뒤 순번의 숫자 최댓값 + 1. 문자열 max는 'TR-SEM-26999' > 'TR-SEM-261000'이라 999·9999 뒤에
    같은 번호를 다시 내므로 숫자로 비교합니다. 동시 저장 경합은 UNIQUE 위반 → 409로 처리됩니다(main.py)."""
    seq = cast(func.substr(col, len(prefix) + 1), Integer)
    last = db.scalar(select(func.max(seq)).where(col.startswith(prefix, autoescape=True)))
    return (last or 0) + 1


def next_run_no(db: Session, run_date: date) -> str:
    """공정런 번호 PR-YY-NNNN (연도별 순번, 9999 뒤는 5자리)."""
    prefix = f"PR-{run_date:%y}-"
    return f"{prefix}{_next_seq(db, ProcessRun.run_no, prefix):04d}"


def next_test_run_no(db: Session, test_type: str, start: date) -> str:
    """시험런 번호 TR-{시험종류}-{YY}{순번3} (D-21, 999 뒤는 4자리)."""
    prefix = f"TR-{test_type}-{start:%y}"
    return f"{prefix}{_next_seq(db, TestRun.test_run_no, prefix):03d}"
