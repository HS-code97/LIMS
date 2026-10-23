"""테스트 도우미: 테스트마다 겹치지 않는 현장 코일 → 전폭시편 입고 → 블랭크 전단 (시편번호 체계 v3.0)."""
from __future__ import annotations

import itertools

from app.schemas import IntakeIn, SplitIn
from app.services import marking, workflow

_seq = itertools.count(1)


def new_coil() -> str:
    """'KAB0001' 꼴 현장 코일번호. 영문 뒤 2자리가 매번 달라 코일코드(AB0 …)가 겹치지 않습니다."""
    n = next(_seq)
    L = marking.LETTERS
    return f"K{L[n % 24]}{L[(n // 24) % 24]}{n % 10}{n:03d}"[:7]


def blanks(db, user_id, n: int = 2, project: str = "A6") -> list:
    """서비스 계층: 전폭 1장 입고 → 블랭크 n장 (QV3-101 …)."""
    sheet = workflow.intake(db, IntakeIn(coil_no=new_coil(), project_code=project, count=1), user_id)[0]
    return workflow.split(db, sheet, SplitIn(count=n, start=1, size_text="200x300"), user_id)


def api_blanks(client, n: int = 2, project: str = "A6") -> list[str]:
    """HTTP: 입고 → 전단, 블랭크 각인번호 목록."""
    r = client.post("/api/specimens/intake", json={"coil_no": new_coil(), "project_code": project, "count": 1})
    assert r.status_code == 200, r.text
    sheet = r.json()["specimens"][0]["short_id"]
    r = client.post(f"/api/specimens/{sheet}/split", json={"count": n, "start": 1})
    assert r.status_code == 200, r.text
    return [c["short_id"] for c in r.json()["children"]]
