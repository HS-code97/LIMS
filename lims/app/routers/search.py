"""검색·비교·Excel 내보내기, 상단 검색창 자동완성 (5.1 #5, 7장 P6·P7)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Project, Specimen, TestTemplate, User
from ..services import actuals, export, search, workflow
from ..services import param_dict as pdict
from ..web import is_htmx, render

router = APIRouter()


@router.get("/go")
def go(q: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """스캐너·검색창 Enter: 각인번호(또는 전체번호)가 맞으면 바로 시편 상세로."""
    q = q.strip().upper()
    spec = workflow.find_specimen(db, q)             # v2.3 번호(이관 시편)도 찾음
    if spec is not None:
        return RedirectResponse(f"/specimens/{spec.short_id}", 303)
    hits = search.autocomplete(db, q, 2)
    if len(hits) == 1:
        return RedirectResponse(hits[0]["href"], 303)
    return RedirectResponse(f"/search?q={q}", 303)


@router.get("/search/suggest")
def suggest(request: Request, q: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    items = search.autocomplete(db, q)
    if is_htmx(request):
        return render(request, "partials/suggest.html", items=items, q=q)
    return items


def _keys_for(qy: search.Query) -> list[str]:
    keys = [f.key for f in qy.params]
    for k in pdict.quick_keys():
        if k not in keys:
            keys.append(k)
    return keys


@router.get("/search")
def search_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    qy = search.parse_query(request.query_params)
    searched = bool(request.query_params)
    specs = search.run(db, qy) if searched else []
    keys = _keys_for(qy)
    emap = search.effective_map(db, [s.id for s in specs], keys)
    compare = [c for c in request.query_params.getlist("cmp") if c][:5]
    cmp_specs = [s for s in (workflow.find_specimen(db, c) for c in compare) if s]
    cmp_params = {}
    for s in cmp_specs:
        if s.process_run:
            cmp_params[s.id] = actuals.RunActuals(db, s.process_run).all_for(s)
    projects = db.scalars(select(Project).order_by(Project.project_code.desc())).all()
    types = sorted({t.test_type for t in db.scalars(select(TestTemplate))})
    qs = str(request.url.query)
    return render(request, "search.html", nav="search", qy=qy, qy_params=[vars(f) for f in qy.params], specs=specs, keys=keys, emap=emap, searched=searched,
                  projects=projects, types=types, basis_labels=search.BASIS, cmp_specs=cmp_specs,
                  cmp_params=cmp_params, numeric_keys=pdict.numeric_keys(), qs=qs)


@router.get("/api/search")
def search_api(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    qy = search.parse_query(request.query_params)
    specs = search.run(db, qy)
    keys = _keys_for(qy)
    emap = search.effective_map(db, [s.id for s in specs], keys)
    out = []
    for s in specs:
        row = {"short_id": s.short_id, "display_id": s.display_id, "stage": s.stage, "status": s.status, "params": {}}
        for k in keys:
            e = emap.get((s.id, k))
            if e:
                row["params"][k] = {"target": e.target, "actual": e.actual, "effective": e.effective,
                                    "badge": actuals.badge_text(e.source, e.level, e.inherited_from),
                                    "out_of_tol": e.out_of_tol}
        out.append(row)
    return {"basis": qy.basis, "count": len(out), "items": out}


@router.get("/api/export/xlsx")
def export_xlsx(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    qy = search.parse_query(request.query_params)
    ids = [i for i in request.query_params.get("ids", "").split(",") if i]
    if ids:
        specs = [s for s in (workflow.find_specimen(db, i) for i in ids) if s]
    else:
        specs = search.run(db, qy)
    data = export.specimens_xlsx(db, specs, _keys_for(qy), qy.basis, str(request.base_url).rstrip("/"))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="lims_search.xlsx"'})
