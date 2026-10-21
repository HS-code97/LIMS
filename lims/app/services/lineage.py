"""계보 조회 (7장 P6). 재귀 CTE는 PostgreSQL·SQLite 모두 지원합니다."""
from __future__ import annotations

from sqlalchemy import literal, select
from sqlalchemy.orm import Session, aliased

from ..models import Specimen


def ancestors(spec: Specimen) -> list[Specimen]:
    """루트(원판) → … → 부모 순서 (자신 제외)."""
    out, node = [], spec.parent
    while node is not None:
        out.append(node)
        node = node.parent
    return list(reversed(out))


def descendants_stmt(spec_id: int):
    """자손 재귀 CTE (7장 P6)."""
    base = select(Specimen.id, literal(0).label("depth")).where(Specimen.id == spec_id).cte("down", recursive=True)
    s = aliased(Specimen)
    cte = base.union_all(select(s.id, (base.c.depth + 1).label("depth")).where(s.parent_id == base.c.id))
    return select(cte.c.id, cte.c.depth).where(cte.c.depth > 0).order_by(cte.c.depth)


def descendant_ids(db: Session, spec_id: int) -> list[tuple[int, int]]:
    """(id, depth) 목록. 자신 제외."""
    rows = db.execute(descendants_stmt(spec_id)).all()
    return [(r[0], r[1]) for r in rows]


def descendants_tree(spec: Specimen) -> list[dict]:
    """[{spec, children:[...]}] 트리 (논리 삭제 제외)."""
    return [{"spec": c, "children": descendants_tree(c)} for c in spec.children if not c.is_deleted]


def chain(spec: Specimen) -> list[dict]:
    """계보 타임라인: 원소재 → 공정런 → 원판 → … → 자신."""
    nodes: list[dict] = []
    if spec.material:
        nodes.append({"kind": "material", "label": spec.material.coil_no,
                      "sub": spec.material.label.replace(spec.material.coil_no, "").strip() or "원소재",
                      "href": None})
    if spec.process_run:
        r = spec.process_run
        nodes.append({"kind": "run", "label": r.run_no, "sub": f"공정런 {r.run_date:%Y-%m-%d}",
                      "href": f"/process-runs/{r.run_no}"})
    for a in ancestors(spec):
        nodes.append({"kind": "specimen", "label": a.short_id, "sub": a.stage_name,
                      "href": f"/specimens/{a.short_id}"})
    nodes.append({"kind": "self", "label": spec.short_id, "sub": spec.stage_name,
                  "href": f"/specimens/{spec.short_id}"})
    return nodes
