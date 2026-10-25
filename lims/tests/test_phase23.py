"""2·3단계: 템플릿 편집, 폴더 감시, 엑셀 가져오기, 허용편차 편집, PV 수신, 산점도, 뷰어, PPT, X-cut 연동, 설정."""
import io
import json
import shutil

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import delete, select

from app.config import SEED_DIR, VAR_DIR
from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, ParamActualCfg, ProcessPreset
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
    from helpers import api_blanks
    r = client.post("/api/process-runs", json={
        "dict_version": pdict.version(), "preset_id": pid, "project_code": "X6", "run_date": "2026-10-25",
        "coating_weight_target": 60, "specimens": api_blanks(client, 2, project="X6"), "recipe": pdict.preset_recipe(over)})
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
    # 양식 예시 그대로(CQV3141T → QV3)는 기준 시나리오와 겹치므로 새 코일 CXM5123 → XM5로 바꿈
    wb["입고"]["A2"], wb["입고"]["B2"] = "CXM5123T", "Y6"
    wb["전단"]["A2"] = "XM5-A"
    wb["공정런"]["B2"], wb["공정런"]["F2"], wb["공정런"]["G2"] = "Y6", "XM5-A01~A03", "CXM5123"
    wb["분기"]["A2"] = "XM5-A01"
    wb["실측"]["B3"] = "XM5-A01"
    wb["분석결과"]["E2"] = wb["분석결과"]["E3"] = "XM5-A01-A"
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("imp.xlsx", buf.getvalue())}
    dry = client.post("/api/import/excel", files=files, data={"dry_run": "true"}).json()
    assert not dry["errors"], dry["errors"]
    assert not dry["saved"] and client.get("/api/specimens/XM5-A01").status_code == 404
    real = client.post("/api/import/excel", files=files, data={"dry_run": "false"}).json()
    assert real["saved"] and real["created"]["results"] == 2, real
    assert client.get("/api/specimens/XM5-A01-A").json()["display_id"] == "XM5-Y6-C-A01-A-M206K"
    p = client.get("/api/specimens/XM5-A01/params").json()
    assert p["out.cw_top"]["actual"] == 57 and p["pot.T"]["badge"] == "세션"
    again = client.post("/api/import/excel", files=files, data={"dry_run": "true"}).json()
    assert any("이미 쓰인" in e for e in again["errors"])


def test_dictionary_edit(client):
    """허용편차 편집은 DB(param_actual_cfg)에 저장되고, 다른 worker도 다음 요청에서 반영합니다."""
    seed_file = SEED_DIR / "param_dictionary.json"
    mtime = seed_file.stat().st_mtime_ns
    try:
        r = client.post("/admin/dictionary", data={"key": "ak.P", "level": "panel", "tol": "5", "agg": "mean",
                                                   "quick": "on", "methods": "압력계, PV"}, follow_redirects=False)
        assert r.status_code == 303
        assert pdict.actual_cfg("ak.P")["tol"] == 5.0
        with SessionLocal() as db:
            assert db.get(ParamActualCfg, "ak.P").cfg["tol"] == 5.0
            assert db.scalar(select(AuditLog.id).where(AuditLog.table_name == "param_actual_cfg"))
        # 다른 worker에서 고친 상황: 이 프로세스의 캐시는 그대로인데 DB rev만 오름 → 다음 sync에서 반영
        with SessionLocal() as db:
            row = db.get(ParamActualCfg, "ak.P")
            row.cfg, row.rev = {**row.cfg, "tol": 7.0}, row.rev + 1
            db.commit()
        assert pdict.actual_cfg("ak.P")["tol"] == 5.0
        assert client.get("/admin?tab=dictionary").status_code == 200       # 요청마다 get_db가 sync
        assert pdict.actual_cfg("ak.P")["tol"] == 7.0
        assert pdict.version() == json.loads(seed_file.read_text(encoding="utf-8"))["dict_version"]
    finally:
        with SessionLocal() as db:
            db.execute(delete(ParamActualCfg))
            db.commit()
            pdict.sync(db)
    assert seed_file.stat().st_mtime_ns == mtime                         # 시드 파일은 더 이상 쓰지 않음


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
    assert tr.startswith("AR-XCUT-")
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
