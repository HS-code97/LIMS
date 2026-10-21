"""2·3단계: 템플릿 편집, 폴더 감시, 엑셀 가져오기, 허용편차 편집, PV 수신, 산점도, 뷰어, PPT, X-cut 연동, 설정."""
import io
import json
import shutil

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import select

from app.config import SEED_DIR, VAR_DIR
from app.db import SessionLocal
from app.main import app
from app.models import ProcessPreset
from app.services import param_dict as pdict


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        assert c.post("/login", data={"emp_no": "hhs", "password": "lims1234"}, follow_redirects=False).status_code == 303
        yield c


@pytest.fixture(scope="module")
def run(client):
    with SessionLocal() as db:
        m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
        pid, over = m2.id, m2.overrides
    start = client.get("/api/numbering/next?project=26X0&stage=P&count=2").json()["suggest"]
    r = client.post("/api/process-runs", json={
        "dict_version": pdict.version(), "preset_id": pid, "project_code": "26X0", "run_date": "2026-10-25",
        "coating_weight_target": 60, "panel_count": 2, "serial_start": start, "recipe": pdict.preset_recipe(over)})
    assert r.status_code == 200, r.text
    return r.json()


def test_template_editor(client):
    assert client.get("/admin/templates/edit").status_code == 200
    bad = client.post("/api/test-templates", json={"code": "bad code", "name": "x", "test_type": "x", "field_schema": [
        {"key": "Red", "label": "적청", "type": "select"}]})
    assert bad.status_code == 422 and len(bad.json()["detail"]["errors"]) >= 3
    body = {"code": "HUMID_STD", "name": "항온항습", "test_type": "HUM", "default_cycles": 4, "default_interval_days": 7,
            "field_schema": [{"key": "red_rust_pct", "label": "적청률", "unit": "%", "type": "number", "min": 0, "max": 100, "grid": True},
                             {"key": "cw_top", "label": "부착량", "type": "number", "maps_to": "out.cw_top"}],
            "condition_schema": [{"key": "rh", "label": "습도", "unit": "%", "type": "number", "default": 95}]}
    r1 = client.post("/api/test-templates", json=body).json()
    r2 = client.post("/api/test-templates", json={**body, "name": "항온항습 v2"}).json()
    assert (r1["version"], r2["version"]) == (1, 2)
    assert client.get(f"/admin/templates/edit?id={r2['id']}").status_code == 200


def test_excel_import(client):
    wb_bytes = client.get("/api/import/template.xlsx").content
    wb = load_workbook(io.BytesIO(wb_bytes))
    ws = wb["공정런"]
    ws["B2"], ws["G2"], ws["H2"] = "26X1", 801, "POS-25-0001"
    wb["분기"]["A2"], wb["분기"]["D2"] = "26X1-P0801", 801
    wb["시험결과"]["E2"] = wb["시험결과"]["E3"] = "26X1-C0801"
    wb["실측"]["B3"] = "26X1-P0801"
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("imp.xlsx", buf.getvalue())}
    dry = client.post("/api/import/excel", files=files, data={"dry_run": "true"}).json()
    assert not dry["errors"], dry["errors"]
    assert not dry["saved"] and client.get("/api/specimens/26X1-P0801").status_code == 404
    real = client.post("/api/import/excel", files=files, data={"dry_run": "false"}).json()
    assert real["saved"] and real["created"]["results"] == 2, real
    p = client.get("/api/specimens/26X1-P0801/params").json()
    assert p["out.cw_top"]["actual"] == 57 and p["pot.T"]["badge"] == "세션"
    again = client.post("/api/import/excel", files=files, data={"dry_run": "true"}).json()
    assert any("이미 쓰인" in e for e in again["errors"])


def test_dictionary_edit(client):
    path = SEED_DIR / "param_dictionary.json"
    backup = path.read_text(encoding="utf-8")
    try:
        r = client.post("/admin/dictionary", data={"key": "ak.P", "level": "panel", "tol": "5", "agg": "mean",
                                                   "quick": "on", "methods": "압력계, PV"}, follow_redirects=False)
        assert r.status_code == 303
        assert pdict.actual_cfg("ak.P")["tol"] == 5.0
        assert json.loads(path.read_text(encoding="utf-8"))["dict_version"] == pdict.version()
    finally:
        path.write_text(backup, encoding="utf-8")
        pdict.reload()


def test_pv_receive(client, run):
    panel = run["panels"][0]["short_id"]
    csv = "t,segment,RTH.TT01,RTH.DP01,POT.TT01\n" + "\n".join(
        f"{t},{'rth' if t < 80 else ('rts' if t < 110 else 'pot')},{min(800, 25 + t * 10) + (t % 3) - 1},-38,{590 + (t % 2)}"
        for t in range(0, 140))
    r = client.post(f"/api/process-runs/{run['run_no']}/pv", files={"file": ("pv.csv", csv.encode())}, data={"specimen": panel})
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert set(s) >= {"rth.T", "rth.DP", "pot.T"}
    p = client.get(f"/api/specimens/{panel}/params").json()
    assert p["rth.T"]["source"] == "pv" and p["pot.T"]["level"] == "run"
    assert client.post(f"/api/process-runs/{run['run_no']}/pv", files={"file": ("x.csv", b"t,foo\n1,2\n")}).status_code == 422


def test_xcut_and_reports(client, run):
    panel = run["panels"][1]["short_id"]
    r = client.post("/api/integrations/xcut", json={"results": [
        {"short_id": panel, "cycle": 0, "blister_area_pct": 2.4, "blister_count": 17, "max_blister_mm": 1.2, "creep_mm": 0.8}]})
    assert r.status_code == 200, r.text
    tr = r.json()["test_run_no"]
    assert tr.startswith("TR-XCUT-")
    assert client.post("/api/integrations/xcut", json={"results": [{"short_id": panel, "blister_area_pct": 300}]}).status_code == 422
    img = io.BytesIO()
    Image.new("RGB", (80, 60), "gray").save(img, "JPEG")
    client.post("/api/files", files={"files": (f"{panel}_W00_front.jpg", img.getvalue(), "image/jpeg")}, data={"test_run_no": tr})
    for url in (f"/api/test-runs/{tr}/report.pptx", f"/api/specimens/{panel}/report.pptx"):
        res = client.get(url)
        assert res.status_code == 200 and res.content[:2] == b"PK", url
    for url in ("/analysis/scatter", "/analysis/scatter?key=rth.T", f"/viewer?a={panel}&b={run['panels'][0]['short_id']}",
                "/viewer", "/admin?tab=settings", "/admin?tab=dictionary", "/admin?tab=import"):
        assert client.get(url).status_code == 200, url


def test_watcher(tmp_path, monkeypatch, run):
    from app.workers import watcher
    d = tmp_path / "sem"
    d.mkdir()
    panel = run["panels"][0]["short_id"]
    Image.new("L", (40, 40), 120).save(d / f"{panel}_SEM_x1000.tif")
    (d / "random_note.txt").write_text("no id")
    state = {}
    out = watcher.scan_once([d], {".tif", ".txt"}, "hhs", stable=0, state=state)
    assert {o["status"] for o in out} == {"matched", "unmatched"}
    assert watcher.scan_once([d], {".tif", ".txt"}, "hhs", stable=0, state=state) == []    # 두 번 넣지 않음
