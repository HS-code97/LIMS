"""시편번호 체계 v3.1 (`시편번호 체계.md`): 각인번호·전체번호 형식, 단계, 코일코드·과제코드 제안.

각인번호 (시편에 새김, 평생 불변, 유일키 = Specimen.short_id)
    QV3 - A02 - K - 3
    코일   가지   후절단 분석조각
    코일 = 영문2+숫자1 · 가지 = 전폭 영문1(A~) [+ 전폭을 자른 조각 숫자2(01~99)]
    후절단 = 영문1(A~) · 분석조각 = 숫자1(1~9)
    구간 경계마다 영문·숫자가 바뀌어 하이픈이 지워져도 끊어 읽힙니다(QV3A02K3).
전체번호 (DB·화면·라벨)
    QV3 - A6 - C - A02 - K - M206K-H03-T02-P12
    코일   과제  단계 가지  후절단 조건부 꼬리(거친 공정 블록을 거친 순서대로)
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

# I·O는 숫자 1·0과 헷갈려 쓰지 않습니다.
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
# 각인 영문(전폭·후절단): 각인에서 숫자와 헷갈리는 Q(0)·S(5)·Z(2)도 뺍니다 — 21자
MARK_LETTERS = "ABCDEFGHJKLMNPRTUVWXY"
_L = f"[{MARK_LETTERS}]"

STAGES = {"A": "전폭시편", "B": "전단 블랭크", "C": "도금", "D": "열처리", "E": "도장"}
STAGE_ORDER = "ABCDE"

# 자르지 않는 공정: 단계(올리기만), 꼬리 블록 머리글자, 이벤트·코드표 종류
TREATMENTS = {
    "PLATE": {"name": "도금", "stage": "C", "prefix": None},
    "HEAT": {"name": "열처리", "stage": "D", "prefix": "H"},
    "PRETREAT": {"name": "전처리(화성 등)", "stage": None, "prefix": "T"},
    "PAINT": {"name": "도장", "stage": "E", "prefix": "P"},
}

COIL_CODE_RE = re.compile(r"^[A-Z]{2}\d$")
PROJECT_CODE_RE = re.compile(r"^[A-Z]\d$")
# 각인번호: 앞뒤가 영숫자가 아닌 자리에서만 (파일명 'QV3-A02-K_W03_front.jpg'에서도 찾음)
_TAIL = rf"(?P<branch>{_L}(?:\d{{2}})?)(?:-(?P<cut>{_L})(?:-(?P<piece>[1-9]))?)?"
# 뒤에 '-영숫자'가 이어지면 각인번호가 아님 (QV3-A02-01처럼 잘못 친 번호를 부모 QV3-A02로 읽지 않게)
MARK_RE = re.compile(rf"(?<![A-Z0-9])(?P<coil>[A-Z]{{2}}\d)-{_TAIL}(?![A-Z0-9]|-[A-Z0-9])")
# 전체번호: 코일-과제-단계-가지… (꼬리는 무시)
FULL_RE = re.compile(rf"(?<![A-Z0-9])(?P<coil>[A-Z]{{2}}\d)-[A-Z]\d-[A-E]-{_TAIL}(?![A-Z0-9])")
# 하이픈이 지워진 각인을 읽은 대로 친 번호(QV3A02K3, 'QV3 A02K3'): 영문·숫자 교대라 끊는 자리가 하나뿐입니다.
# 글 속에서 찾지 않고 입력 전체가 이 모양일 때만 씁니다(파일명 등에서 엉뚱한 번호를 잡지 않게).
_SEP = re.compile(r"[\s\-/]+")
COMPACT_RE = re.compile(rf"(?P<coil>[A-Z]{{2}}\d)(?P<branch>{_L}(?:\d{{2}})?)(?:(?P<cut>{_L})(?P<piece>[1-9])?)?")


class MarkingError(ValueError):
    pass


def stage_rank(stage: str) -> int:
    return STAGE_ORDER.index(stage)


def mark_id(coil: str, branch: str, cut: str | None = None, piece: str | None = None) -> str:
    return "-".join(p for p in (coil, branch, cut, piece) if p)


def _mark_of(m: re.Match) -> str:
    return mark_id(m["coil"], m["branch"], m["cut"], m["piece"])


def find_mark(text: str) -> str | None:
    """글 속의 각인번호를 찾습니다. 전체번호(QV3-A6-C-A02-M206K)나 하이픈 없이 친 각인번호(QV3A02K3,
    'QV3 A02K3')를 넣어도 각인번호로 바꿔 줍니다."""
    up = (text or "").upper()
    m = FULL_RE.search(up)
    if m:
        return _mark_of(m)
    m = MARK_RE.search(up)
    if m:
        return _mark_of(m)
    m = COMPACT_RE.fullmatch(_SEP.sub("", up))
    return _mark_of(m) if m else None


def parse_mark(text: str) -> dict:
    m = MARK_RE.fullmatch((text or "").strip().upper())
    if not m:
        raise MarkingError(f"각인번호 형식이 아닙니다: {text} (예: QV3-A02, QV3-A02-K-3)")
    return {k: m[k] for k in ("coil", "branch", "cut", "piece")}


def tail_blocks(steps: list[dict] | None, condition_code: str | None) -> list[str]:
    """거친 공정 → 꼬리 블록. 도금은 현재 조건부(목표 정정 시 다시 계산), 나머지는 머리글자 + 코드 2자리."""
    out = []
    for st in steps or []:
        t = TREATMENTS.get(st.get("k"))
        if t is None:
            continue
        if st["k"] == "PLATE":
            out.append(condition_code or "XXXXX")
        else:
            out.append(f"{t['prefix']}{st.get('code') or '00'}")
    return out


def full_id(coil: str, project: str, stage: str, branch: str, cut: str | None, piece: str | None,
            tail: list[str]) -> str:
    return "-".join(p for p in (coil, project, stage, branch, cut, piece, *tail) if p)


def letter_of(n: int) -> str:
    """전폭·후절단 n번째 → 각인 영문 (1 → A, 21 → Y)."""
    if not 1 <= n <= len(MARK_LETTERS):
        raise MarkingError(f"전폭·후절단 번호는 1~{len(MARK_LETTERS)}번째(A~Y, I·O·Q·S·Z 제외)까지입니다.")
    return MARK_LETTERS[n - 1]


def letter_index(c: str) -> int:
    return MARK_LETTERS.index(c) + 1


# ── 현장 코일번호 → 코일코드 (3.5절) ─────────────────────────────────
FIELD_COIL_RE = re.compile(r"^(?P<letters>[A-Z]{3})(?P<digits>\d{4})(?P<pos>[A-Z0-9])?$")


def split_field_coil(coil_no: str) -> tuple[str, str | None]:
    """'CQV3141T' → ('CQV3141', 'T'). 형식이 다르면 (전체, None)."""
    up = re.sub(r"\s+", "", (coil_no or "").upper())
    m = FIELD_COIL_RE.match(up)
    if not m:
        return up, None
    return m["letters"] + m["digits"], m["pos"]


def coil_code_candidates(coil_no: str) -> list[str]:
    """제안 순서: 영문 뒤 2자리+일련 첫 숫자 → 나머지 숫자 → 다른 영문 조합 → 남은 숫자 0~9."""
    base, _ = split_field_coil(coil_no)
    m = FIELD_COIL_RE.match(base)
    if m:
        letters, digits = m["letters"], m["digits"]
    else:   # 형식이 다른 코일번호: 영문·숫자를 골라 씀
        letters = "".join(ch for ch in base if ch.isalpha()) or "XX"
        digits = "".join(ch for ch in base if ch.isdigit()) or "0"
        letters = (letters * 3)[:3] if len(letters) < 3 else letters[-3:]
    main = letters[1:3]
    out = [main + digits[0]]
    out += [main + d for d in digits[1:]]
    out += [letters[0] + letters[2] + digits[0], letters[0] + letters[1] + digits[0]]
    out += [main + str(d) for d in range(10)]
    seen, uniq = set(), []
    for c in out:
        if c not in seen and COIL_CODE_RE.match(c):
            seen.add(c)
            uniq.append(c)
    return uniq


def suggest_coil_code(db: Session, coil_no: str) -> tuple[str, bool]:
    """(제안 코드, 현장 번호에서 유도했는지). 같은 코일이 이미 있으면 그 코드."""
    from ..models import Material
    base, _ = split_field_coil(coil_no)
    mat = db.scalar(select(Material).where(Material.coil_no == base))
    if mat is not None and mat.coil_code:
        return mat.coil_code, True
    used = set(db.scalars(select(Material.coil_code).where(Material.coil_code.is_not(None))))
    for c in coil_code_candidates(coil_no):
        if c not in used:
            return c, True
    for a in LETTERS:
        for b in LETTERS:
            for d in "0123456789":
                if a + b + d not in used:
                    return a + b + d, False
    raise MarkingError("빈 코일코드가 없습니다.")


# ── 과제코드 (3.3절) ─────────────────────────────────────────────
COMMON_LETTERS = {"X": "공통", "Y": "선행", "Z": "기타"}


def next_project_code(db: Session, year: int) -> str:
    """그해 등록 순서 영문(I·O·X·Y·Z 제외) + 연도 끝자리. 10년 전 같은 코드가 남아 있으면 다음 영문."""
    from ..models import Project
    d = str(year % 10)
    for ch in LETTERS:
        if ch in COMMON_LETTERS:
            continue
        if db.get(Project, ch + d) is None:
            return ch + d
    raise MarkingError(f"{year}년 과제코드를 모두 썼습니다.")
