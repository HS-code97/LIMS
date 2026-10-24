"""HTTP 수준 점검: 로그인 → 모든 화면 렌더링 → 주요 API (10장)."""
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Material, ProcessPreset, TestTemplate
from app.services import param_dict as pdict
from helpers import api_blanks


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/login", data={"emp_no": "hhs", "password": "lims1234", "next": "/"}, follow_redirects=False)
        assert r.status_code == 303
        yield c


def _jpg(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "JPEG")
    return buf.getvalue()


def test_login_required():
    with TestClient(app) as c:
        assert c.get("/", follow_redirects=False).status_code == 303
        assert c.get("/api/presets").status_code == 401
        assert c.post("/login", data={"emp_no": "hhs", "password": "x"}).status_code == 401


def test_full_flow(client):
    with SessionLocal() as db:
        m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
        mat = db.scalar(select(Material).where(Material.coil_no == "CQV3141"))
        cct = db.scalar(select(TestTemplate).where(TestTemplate.code == "CCT_STD"))
        m2_id, mat_id, cct_id, m2_over = m2.id, mat.id, cct.id, m2.overrides

    assert client.get("/api/param-dictionary").json()["dict_version"] == pdict.version()
    assert any(p["name"] == "M2" for p in client.get("/api/presets").json())
    # 입고 화면·제안: 등록된 코일이면 같은 코드, 다음 전폭번호
    sug = client.get("/api/coils/suggest?coil_no=CQV3141H&count=2").json()
    assert sug["coil_code"] == "QV3" and sug["existing"] and sug["position"] == "H"
    r = client.post("/api/specimens/intake", json={"coil_no": "CQV3141H", "project_code": "A6", "count": 1,
                                                   "sheet_start": sug["sheet_start"], "coil_code": "ZZ9"})
    assert r.status_code == 422                                          # 같은 코일은 같은 코드
    r = client.post("/api/specimens/intake", json={"coil_no": "CQV3141H", "project_code": "A6", "count": 1})
    assert r.status_code == 200, r.text
    sheet = r.json()["specimens"][0]["short_id"]
    nxt = client.get(f"/api/specimens/{sheet}/next?count=3").json()
    assert nxt["first"] == f"{sheet}{nxt['suggest']:02d}"                 # 전폭 QV3-C → 블랭크 QV3-C01
    r = client.post(f"/api/specimens/{sheet}/split", json={"count": 3, "start": nxt["suggest"]})
    assert r.status_code == 200, r.text
    marks = [c["short_id"] for c in r.json()["children"]]
    cands = {c["short_id"] for c in client.get("/api/plating/candidates?coil=QV3").json()}
    assert set(marks) <= cands and sheet not in cands                    # 자른 전폭은 후보 아님

    recipe = pdict.preset_recipe(m2_over)
    body = {"dict_version": pdict.version(), "preset_id": m2_id, "project_code": "A6", "material_id": mat_id,
            "run_date": "2026-10-21", "coating_weight_target": 60, "specimens": marks,
            "recipe": recipe, "changed_from_preset": [], "warnings": [], "note": "web test"}
    # 범위 밖 값은 확인 요구(422)
    bad = {**body, "recipe": pdict.merge(recipe, {"pot.T": 900})}
    r = client.post("/api/process-runs", json=bad)
    assert r.status_code == 422 and r.json()["items"]
    r = client.post("/api/process-runs", json=body)
    assert r.status_code == 200, r.text
    run = r.json()
    run_no, p1 = run["run_no"], run["panels"][0]["short_id"]
    assert p1 == marks[0] and run["panels"][0]["display_id"] == p1.replace("QV3-", "QV3-A6-C-") + "-M206K"
    # 이미 도금한 시편 다시 → 422
    assert client.post("/api/process-runs", json=body).status_code == 422

    preview = client.post("/api/process-runs/preview-code", json={"recipe": recipe, "preset_id": m2_id,
                                                                  "coating_weight_target": 45}).json()
    assert preview["code"] == "M205K"

    r = client.post(f"/api/process-runs/{run_no}/actuals", json={"rows": [
        {"key": "pot.T", "value": 458.5, "method": "열전대"}, {"key": "rth.DP", "value": -36},
        {"key": "out.cw_top", "value": 54, "specimen": p1}, {"key": "rth.T", "value": 802, "specimen": p1}]})
    assert r.status_code == 200 and r.json()["saved"] == 4
    params = client.get(f"/api/specimens/{p1}/params").json()
    assert params["out.cw_top"]["actual"] == 54 and params["out.cw_top"]["badge"] == "실측"
    assert params["pot.T"]["badge"] == "세션"
    r = client.post(f"/api/process-runs/{run_no}/actuals/paste",
                    json={"text": f"원판\t나이프 압력\n{p1}\t31", "dry_run": True})
    assert r.json()["items"] and not r.json()["errors"]

    ba = client.post("/api/bath-analyses", json={"pot": "POT-1", "sampled_at": "2026-10-21T09:00:00", "method": "ICP",
                                                 "composition": {"Zn": 25.1, "Si": 2.9, "Mg": 0.46, "Al": "bal."}}).json()
    assert any(c["run_no"] == run_no for c in ba["candidates"])
    assert client.post(f"/api/bath-analyses/{ba['id']}/apply", json={"run_nos": [run_no]}).json()["applied_rows"] == 3

    # 자르기 → 실험편
    r = client.post(f"/api/specimens/{p1}/split", json={"count": 2, "start": 1})
    assert r.status_code == 200, r.text
    kids = [k["short_id"] for k in r.json()["children"]]
    assert kids == [f"{p1}-A", f"{p1}-B"]
    assert client.post(f"/api/specimens/{p1}/split", json={"count": 1, "start": 1}).status_code == 409
    r = client.post(f"/api/specimens/{kids[0]}/events", json={"event_type": "PRETREAT", "event_date": "2026-10-22",
                                                              "code": "01", "params": {"type": "Cr-free"}})
    assert r.status_code == 200 and r.json()["specimen"]["tail"] == ["M206K", "T01"], r.text
    assert client.post(f"/api/specimens/{kids[0]}/events", json={"event_type": "NOTE", "event_date": "2026-10-22",
                                                                 "params": {"memo": "x"}}).status_code == 200

    # 분석런 + 결과 + 붙여넣기 + 사진
    r = client.post("/api/test-runs", json={"template_id": cct_id, "equipment": "CCT-01", "conditions": {"salt_conc": 5},
                                            "start_date": "2026-10-23",
                                            "specimens": [{"short_id": kids[0], "slot": "A-01"}, {"short_id": kids[1]}]})
    assert r.status_code == 200, r.text
    tr = r.json()["test_run_no"]
    assert tr.startswith("AR-CCT-26")
    r = client.put(f"/api/test-runs/{tr}/results/{kids[0]}/1", json={"metrics": {"red_rust_pct": 2, "junk": 1}})
    assert r.status_code == 200 and r.json()["warnings"]
    assert client.put(f"/api/test-runs/{tr}/results/{kids[0]}/2", json={"metrics": {"red_rust_pct": 200}}).status_code == 422
    r = client.post(f"/api/test-runs/{tr}/paste", json={"text": f"시편\tW00\tW01\n{kids[1]}\t0\t1\n"})
    assert r.json()["saved"] == 2, r.json()
    files = [("files", (f"{kids[0]}_W03_front.jpg", _jpg("red"), "image/jpeg")),
             ("files", ("random.jpg", _jpg("blue"), "image/jpeg")),
             ("files", ("dup.jpg", _jpg("red"), "image/jpeg"))]
    up = client.post("/api/files", files=files, data={"test_run_no": tr}).json()
    assert up["summary"] == {"matched": 1, "unmatched": 1, "duplicate": 1, "error": 0}, up
    unmatched_id = next(x["attachment_id"] for x in up["results"] if x["status"] == "unmatched")
    assert client.patch(f"/api/files/{unmatched_id}", json={"short_id": kids[1]}).status_code == 200
    att = next(x["attachment_id"] for x in up["results"] if x["status"] == "matched")
    assert client.get(f"/files/{att}/thumb").headers["content-type"] == "image/webp"
    assert client.post(f"/api/test-runs/{tr}/cycles", json={"delta": 1}).json()["cycles"] == 10

    # 화면 렌더링
    for url in ["/", "/process-runs", "/process-runs/new", f"/process-runs/new?clone={run_no}", f"/process-runs/{run_no}",
                f"/process-runs/{run_no}?tab=actuals&add=rth.H2", "/specimens", f"/specimens/{p1}", f"/specimens/{kids[0]}",
                "/specimens/intake", f"/specimens/{sheet}", "/specimens?coil=QV3&plated=0&stage=B",
                f"/process-runs/new?specimens={marks[1]}",
                "/test-runs", "/test-runs/new", f"/test-runs/new?specimens={kids[0]}", f"/test-runs/{tr}",
                f"/test-runs/{tr}/cell/{kids[0]}/1", "/search",
                "/search?k1=out.cw_top&lo1=50&hi1=55&basis=effective", f"/search?q=QV3&cmp={p1}&cmp={kids[0]}",
                "/search/suggest?q=QV3"] + [f"/admin?tab={t}" for t in
                                             ("projects", "materials", "bath", "codes", "presets", "templates", "users")]:
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code, r.text[:500])
    assert client.get(f"/go?q={kids[0]}", follow_redirects=False).headers["location"] == f"/specimens/{kids[0]}"
    full = client.get(f"/api/specimens/{kids[0]}").json()["display_id"]          # 전체번호로 스캔해도
    assert client.get(f"/go?q={full}", follow_redirects=False).headers["location"] == f"/specimens/{kids[0]}"

    found = client.get("/api/search?k1=out.cw_top&lo1=50&hi1=55").json()
    assert {p1, *kids} <= {x["short_id"] for x in found["items"]}

    # 내보내기·라벨
    assert client.get("/api/export/xlsx?k1=out.cw_top&lo1=50&hi1=55").content[:2] == b"PK"
    assert client.get(f"/api/test-runs/{tr}/export.xlsx").content[:2] == b"PK"
    csv = client.get(f"/api/labels/engrave.csv?run={run_no}").text
    assert csv.lstrip("﻿").startswith("short_id,datamatrix_text") and f"{p1},{p1}" in csv and "M206K" not in csv   # 꼬리는 각인 안 함
    assert client.get(f"/api/labels/print.pdf?test_run={tr}").content[:4] == b"%PDF"

    assert client.post(f"/api/test-runs/{tr}/finish").json()["status"] == "DONE"
    assert client.get(f"/api/specimens/{kids[0]}").json()["status"] == "AVAILABLE"


def test_admin_project_code(client):
    r = client.post("/admin/projects", data={"company_project_no": "2026P999", "project_name": "테스트 과제"},
                    follow_redirects=False)
    assert r.status_code == 303 and "C6" in r.headers["location"]       # A6·B6가 있어 다음 등록 순서 C6
