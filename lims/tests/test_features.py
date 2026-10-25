"""4단계 회귀 테스트: 장비 API 키, PV 재전송 대체, 목표 정정(꼬리만 재계산), 첨부·시편 되살리기,
각인 CSV의 삭제 시편 제외, 로그인 리다이렉트·실패 제한, API 문서 노출."""
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import SessionLocal
from app.main import app
from app.models import ApiKey, Attachment, ParamActual, ProcessPreset, ProcessRun, Specimen, User
from app.services import param_dict as pdict
from helpers import api_blanks


def _login(emp_no: str) -> TestClient:
    c = TestClient(app)
    c.__enter__()
    assert c.post("/login", data={"emp_no": emp_no, "password": "lims1234"}, follow_redirects=False).status_code == 303
    return c


@pytest.fixture(scope="module")
def hhs():
    c = _login("hhs")
    yield c
    c.__exit__(None, None, None)


@pytest.fixture(scope="module")
def kim():
    c = _login("kim")
    yield c
    c.__exit__(None, None, None)


def _make_run(client, n: int = 2) -> dict:
    with SessionLocal() as db:
        m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
        pid, over = m2.id, m2.overrides
    r = client.post("/api/process-runs", json={
        "dict_version": pdict.version(), "preset_id": pid, "project_code": "A6", "run_date": "2026-10-23",
        "coating_weight_target": 60, "specimens": api_blanks(client, n), "recipe": pdict.preset_recipe(over)})
    assert r.status_code == 200, r.text
    return r.json()


def _uid(emp_no: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.emp_no == emp_no))


# ── 장비 API 키 ──────────────────────────────────────────────────────
def test_api_key_lifecycle(hhs, kim):
    r = hhs.post("/admin/api-keys", data={"name": "EQ-PC-1", "user_id": _uid("kim"), "scopes": ["files"]})
    assert r.status_code == 200
    raw = re.search(r'value="(lims_[A-Za-z0-9_-]+)"', r.text).group(1)
    with SessionLocal() as db:
        key = db.scalar(select(ApiKey).where(ApiKey.name == "EQ-PC-1"))
        assert key.key_hash != raw and raw not in str(key.prefix) + key.key_hash     # 원문은 저장하지 않음
        kid = key.id
    assert kim.post("/admin/api-keys", data={"name": "x", "user_id": _uid("kim"), "scopes": ["files"]}).status_code == 403

    with TestClient(app) as machine:                                    # 쿠키 없는 장비
        hdr = {"X-API-Key": raw}
        r = machine.post("/api/files", headers=hdr, files={"files": (f"eq_{uuid.uuid4().hex}.txt", b"from eq")})
        assert r.status_code == 200, r.text
        with SessionLocal() as db:
            att = db.get(Attachment, r.json()["results"][0]["attachment_id"])
            assert att.uploaded_by == _uid("kim")                      # 키의 처리 계정으로 기록
            assert db.get(ApiKey, kid).last_used_at is not None
        assert machine.get("/api/presets", headers=hdr).status_code == 403          # 범위 밖 주소
        assert machine.post("/api/files", headers={"X-API-Key": raw + "x"},
                            files={"files": ("a.txt", b"x")}).status_code == 401
        assert hhs.post(f"/admin/api-keys/{kid}/revoke", follow_redirects=False).status_code == 303
        assert machine.post("/api/files", headers=hdr, files={"files": ("b.txt", b"y")}).status_code == 401


# ── PV: 같은 파일 재전송은 대체, 다른 파일은 누적 ─────────────────────────────
def _pv_csv(pot: int) -> bytes:
    return ("t,segment,POT.TT01\n" + "\n".join(f"{t},pot,{pot}" for t in range(20))).encode()


def test_pv_resend_replaces(hhs):
    run = _make_run(hhs, 1)
    no = run["run_no"]
    for pot in (590, 600):
        assert hhs.post(f"/api/process-runs/{no}/pv", files={"file": ("cycle1.csv", _pv_csv(pot))}).status_code == 200
    assert hhs.post(f"/api/process-runs/{no}/pv", files={"file": ("cycle2.csv", _pv_csv(610))}).status_code == 200
    with SessionLocal() as db:
        run_id = db.scalar(select(ProcessRun.id).where(ProcessRun.run_no == no))
        rows = db.scalars(select(ParamActual).where(ParamActual.process_run_id == run_id, ParamActual.source == "pv",
                                                    ParamActual.param_key == "pot.T",
                                                    ParamActual.is_deleted.is_(False))).all()
    assert sorted((r.note, r.value) for r in rows) == [("cycle1.csv", 600), ("cycle2.csv", 610)]


# ── 목표 정정: 전체번호 꼬리(조건부)만 바뀌고 각인번호는 그대로 ─────────────────
def test_target_correction(hhs, kim):
    run = _make_run(hhs, 2)
    no, p1, p2 = run["run_no"], run["panels"][0]["short_id"], run["panels"][1]["short_id"]
    body = {"changes": [{"key": "out.cw", "value": 45}], "reason": "목표 부착량 오입력"}
    assert kim.post(f"/api/process-runs/{no}/targets", json=body).status_code == 403          # 작성자·관리자만
    assert hhs.post(f"/api/process-runs/{no}/targets", json={**body, "reason": " "}).status_code == 422
    r = hhs.post(f"/api/process-runs/{no}/targets", json=body)
    assert r.status_code == 200 and r.json()["codes_changed"] == 2, r.text
    r = hhs.post(f"/api/process-runs/{no}/targets", json={"changes": [{"key": "out.cw", "value": 90, "specimen": p2}],
                                                         "reason": "P2만 시리즈"})
    assert r.status_code == 200
    with SessionLocal() as db:
        s1 = db.scalar(select(Specimen).where(Specimen.short_id == p1))
        s2 = db.scalar(select(Specimen).where(Specimen.short_id == p2))
        pr = db.scalar(select(ProcessRun).where(ProcessRun.run_no == no))
        assert s1.condition_code[2:4] == "05" and s1.engraved_label == p1 and s1.display_id.endswith("-M205K")
        assert s2.condition_code[2:4] == "09" and s2.target_overrides == {"out.cw": 90}
        assert pr.coating_weight_target == 45 and "목표 부착량 오입력" in pr.note
    assert hhs.get(f"/api/specimens/{p1}/params").json()["out.cw_top"]["target"] == 45
    assert "M205K" in hhs.get(f"/process-runs/{no}").text


def test_target_correction_keeps_series_values(hhs):
    """시리즈 키의 기본값을 고쳐도, 기본값과 같아 원판별 값이 없던 원판의 시리즈 값은 유지됩니다."""
    with SessionLocal() as db:
        m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
        pid, over = m2.id, m2.overrides
    run = hhs.post("/api/process-runs", json={
        "dict_version": pdict.version(), "preset_id": pid, "project_code": "A6", "run_date": "2026-10-23",
        "coating_weight_target": 60, "specimens": api_blanks(hhs, 3), "recipe": pdict.preset_recipe(over),
        "series": {"key": "out.cw", "values": [90, 60, 30]}}).json()
    p = [x["short_id"] for x in run["panels"]]
    r = hhs.post(f"/api/process-runs/{run['run_no']}/targets",
                 json={"changes": [{"key": "out.cw", "value": 55}], "reason": "기본값 정정"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        ovs = [db.scalar(select(Specimen.target_overrides).where(Specimen.short_id == s)) for s in p]
    assert ovs == [{"out.cw": 90}, {"out.cw": 60}, {"out.cw": 30}]


# ── 되살리기 ─────────────────────────────────────────────────────────
def test_reupload_restores_deleted_attachment(kim):
    body = uuid.uuid4().hex.encode()
    first = kim.post("/api/files", files={"files": ("lost.txt", body)}).json()["results"][0]
    assert kim.delete(f"/api/files/{first['attachment_id']}").status_code == 200
    again = kim.post("/api/files", files={"files": ("lost.txt", body)}).json()["results"][0]
    assert again["attachment_id"] == first["attachment_id"] and "되살렸" in again["message"]
    with SessionLocal() as db:
        assert db.get(Attachment, first["attachment_id"]).is_deleted is False


def test_specimen_restore_and_engrave_csv(hhs, kim):
    run = _make_run(hhs, 1)
    p1 = run["panels"][0]["short_id"]
    kid = hhs.post(f"/api/specimens/{p1}/split", json={"count": 1, "start": 1}).json()["children"][0]["short_id"]
    assert hhs.patch(f"/api/specimens/{kid}", json={"is_deleted": True}).status_code == 200
    assert kid not in hhs.get(f"/api/labels/engrave.csv?ids={p1},{kid}").text                 # 삭제 시편은 각인 안 함
    assert kid in hhs.get("/specimens?deleted=1").text
    assert kid not in kim.get("/specimens?deleted=1").text                                     # 관리자만 봄
    assert kim.post(f"/api/specimens/{kid}/restore").status_code == 403
    assert hhs.post(f"/api/specimens/{kid}/restore").status_code == 200
    assert hhs.get(f"/api/specimens/{kid}").status_code == 200


def test_specimen_detail_actual_edit(hhs, kim):
    """시편 상세 실측 수정: 자른 실험편 자신의 수기 실측 저장·삭제, 시편 소유자 권한(세션 행·남의 원판은 403)."""
    run = _make_run(hhs, 1)
    panel = run["panels"][0]["short_id"]
    kid = kim.post(f"/api/specimens/{panel}/split", json={"count": 1, "start": 1}).json()["children"][0]["short_id"]
    no = run["run_no"]

    page = kim.get(f"/specimens/{kid}").text
    assert "실측 수정" in page and "공정런 공통" in page          # kim은 실험편 소유자 → 수정 가능, 세션 키는 링크

    r = kim.post(f"/api/process-runs/{no}/actuals", json={"source": "manual", "rows": [
        {"key": "out.cw_top", "value": 57.5, "specimen": kid, "mode": "set"}]})
    assert r.status_code == 200, r.text
    p = kim.get(f"/api/specimens/{kid}/params").json()["out.cw_top"]
    assert p["effective"] == 57.5 and p["source"] == "manual" and p["inherited_from"] is None
    assert hhs.get(f"/api/specimens/{panel}/params").json()["out.cw_top"]["source"] == "target"   # 원판은 그대로
    assert 'value="57.5"' in kim.get(f"/specimens/{kid}").text                                     # 입력칸에 미리 채움

    deny = [{"key": "rth.DP", "value": -40, "specimen": None, "mode": "set"},                       # 세션 행
            {"key": "out.cw_top", "value": 61, "specimen": panel, "mode": "set"}]                    # hhs 소유 원판
    for row in deny:
        assert kim.post(f"/api/process-runs/{no}/actuals", json={"source": "manual", "rows": [row]}).status_code == 403

    r = kim.post(f"/api/process-runs/{no}/actuals", json={"source": "manual", "rows": [
        {"key": "out.cw_top", "value": None, "specimen": kid, "mode": "set"}]})                     # 비우면 삭제
    assert r.status_code == 200
    assert kim.get(f"/api/specimens/{kid}/params").json()["out.cw_top"]["source"] == "target"


# ── 로그인 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("nxt", ["//evil.example.com/x", "https://evil.example.com", "/\\evil.example.com"])
def test_login_redirect_stays_on_site(hhs, nxt):
    assert hhs.get("/login", params={"next": nxt}, follow_redirects=False).headers["location"] == "/"
    with TestClient(app) as c:
        r = c.post("/login", data={"emp_no": "kim", "password": "lims1234", "next": nxt}, follow_redirects=False)
        assert r.headers["location"] == "/"
    assert hhs.get("/login", params={"next": "/specimens"}, follow_redirects=False).headers["location"] == "/specimens"


def test_login_failures_are_limited():
    with TestClient(app) as c:
        for _ in range(5):
            assert c.post("/login", data={"emp_no": "brute", "password": "x"}).status_code == 401
        assert c.post("/login", data={"emp_no": "brute", "password": "x"}).status_code == 429


def test_api_docs_only_in_dev():
    assert config.API_DOCS is True and app.docs_url == "/docs"          # 테스트(SQLite)는 개발 모드
    assert config.os.getenv("LIMS_API_DOCS") in (None, "1")
