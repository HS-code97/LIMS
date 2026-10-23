"""2단계 회귀 테스트: 데이터 정확성 (시리즈 기준값, 번호 overflow·경합, 상태 규칙, NaN·길이 검사,
오류 → 409/422, §8 대상별 권한, 대표값 = 가장 최근 측정(D-37))."""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Material, ParamActual, ProcessPreset, TestRun, TestTemplate
from app.schemas import ProcessRunIn, SeriesSpec, SplitIn
from app.services import actuals, numbering, workflow
from app.services import param_dict as pdict
from helpers import api_blanks, blanks


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


@pytest.fixture(scope="module")
def m2():
    with SessionLocal() as db:
        p = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
        return {"id": p.id, "recipe": pdict.preset_recipe(p.overrides)}


def _run_body(m2, marks: list[str], **kw) -> dict:
    return {"dict_version": pdict.version(), "preset_id": m2["id"], "project_code": "A6", "run_date": "2026-10-22",
            "coating_weight_target": 60, "specimens": marks, "recipe": m2["recipe"], **kw}


def _make_run(client, m2, n: int = 2) -> dict:
    r = client.post("/api/process-runs", json=_run_body(m2, api_blanks(client, n)))
    assert r.status_code == 200, r.text
    return r.json()


def _tpl_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(TestTemplate.id).where(TestTemplate.code == "BEND_0T"))


# ── 시리즈: 비교 기준은 목표 부착량까지 합친 레시피 ─────────────────────────
def test_series_base_is_merged_recipe(db, user_id, m2):
    recipe = pdict.merge(m2["recipe"], {"out.cw": 60})          # 화면 원본은 60, 목표 부착량 칸은 45
    run = workflow.create_process_run(db, ProcessRunIn(
        dict_version=pdict.version(), preset_id=m2["id"], project_code="A6", run_date=date(2026, 10, 22),
        coating_weight_target=45, specimens=[b.short_id for b in blanks(db, user_id, 3)], recipe=recipe,
        series=SeriesSpec(key="out.cw", values=[90, 60, 30])), user_id)
    panels = sorted(run.panels, key=lambda p: p.short_id)
    assert [p.target_overrides for p in panels] == [{"out.cw": 90}, {"out.cw": 60}, {"out.cw": 30}]
    assert [p.condition_code[2:4] for p in panels] == ["09", "06", "03"]


# ── 번호: 999·9999 뒤에도 같은 번호를 다시 내지 않음 ───────────────────────
def test_test_run_number_past_999(db, user_id):
    tpl = db.scalar(select(TestTemplate).where(TestTemplate.code == "BEND_0T"))
    db.add(TestRun(test_run_no="TR-ZZQ-26999", test_type="ZZQ", template_id=tpl.id, start_date=date(2026, 1, 5),
                   owner_id=user_id))
    db.flush()
    nxt = numbering.next_test_run_no(db, "ZZQ", date(2026, 3, 1))
    assert nxt == "TR-ZZQ-261000"
    db.add(TestRun(test_run_no=nxt, test_type="ZZQ", template_id=tpl.id, start_date=date(2026, 3, 1), owner_id=user_id))
    db.flush()
    assert numbering.next_test_run_no(db, "ZZQ", date(2026, 3, 1)) == "TR-ZZQ-261001"


# ── 상태 규칙: 폐기는 탑승·자르기·도금 금지, 소진은 자르기만 ─────────────────────
def test_scrap_and_consumed_rules(db, user_id, m2):
    marks = [b.short_id for b in blanks(db, user_id, 3)]
    workflow.find_specimen(db, marks[2]).status = "SCRAP"
    with pytest.raises(workflow.Invalid):                       # 폐기 블랭크는 도금 못 함
        workflow.create_process_run(db, ProcessRunIn(**{**_run_body(m2, marks), "run_date": date(2026, 10, 22)}),
                                    user_id)
    run = workflow.create_process_run(db, ProcessRunIn(**{**_run_body(m2, marks[:2]), "run_date": date(2026, 10, 22)}),
                                      user_id)
    p1, p2 = sorted(run.panels, key=lambda p: p.short_id)
    tpl = db.scalar(select(TestTemplate).where(TestTemplate.code == "BEND_0T"))
    tr = TestRun(test_run_no="TR-ZZS-26001", test_type="ZZS", template_id=tpl.id, start_date=date(2026, 10, 22),
                 owner_id=user_id)
    db.add(tr)
    db.flush()

    p1.status = "SCRAP"
    with pytest.raises(workflow.Invalid):
        workflow.board(db, tr, p1, None)
    with pytest.raises(workflow.Invalid):
        workflow.split(db, p1, SplitIn(count=1, start=1), user_id)

    workflow.split(db, p2, SplitIn(count=1, start=1, mark_parent_consumed=True), user_id)
    assert p2.status == "CONSUMED"
    with pytest.raises(workflow.Invalid):
        workflow.board(db, tr, p2, None)
    workflow.split(db, p2, SplitIn(count=1, start=2), user_id)   # 남은 조각은 허용
    assert p2.status == "CONSUMED"


# ── NaN·무한대·길이 → 422, 저장된 값이 남지 않음 ───────────────────────────
def test_nan_and_length_rejected(hhs, m2):
    run = _make_run(hhs, m2)
    run_no, p1 = run["run_no"], run["panels"][0]["short_id"]
    tr = hhs.post("/api/test-runs", json={"template_id": _tpl_id(), "start_date": "2026-10-22",
                                          "specimens": [{"short_id": p1}]}).json()["test_run_no"]
    for bad in ("nan", "inf", "-Infinity"):
        r = hhs.put(f"/api/test-runs/{tr}/results/{p1}/1", json={"metrics": {"peel_grade": bad}})
        assert r.status_code == 422, (bad, r.text)
    assert hhs.get(f"/api/specimens/{p1}").status_code == 200        # 이전에는 NaN이 커밋돼 계속 500

    assert hhs.post(f"/api/process-runs/{run_no}/actuals",
                    json={"rows": [{"key": "pot.T", "value": "nan"}]}).status_code == 422
    raw = '{"rows": [{"key": "pot.T", "value": NaN}]}'               # JSON 숫자 NaN (Python json은 받아 줌)
    assert hhs.post(f"/api/process-runs/{run_no}/actuals", content=raw,
                    headers={"content-type": "application/json"}).status_code == 422

    r = hhs.post(f"/api/specimens/{p1}/split", json={"count": 1, "start": 1, "rolling_direction": "TOO-LONG"})
    assert r.status_code == 422 and any("rolling_direction" in x for x in r.json()["items"]), r.text
    assert hhs.get(f"/api/specimens/{p1}-01").status_code == 404


# ── 오류 응답: 범위·FK·경합·손상 파일 → 422/409 (이전에는 500) ──────────────
def test_errors_map_to_4xx(hhs, m2, monkeypatch):
    marks = api_blanks(hhs, 3)
    sheet = marks[0].rsplit("-", 1)[0] + "-" + marks[0].split("-")[1][0]
    assert hhs.post(f"/api/specimens/{sheet}/split", json={"count": 2, "start": 99}).status_code == 422   # 99 넘음
    assert hhs.post("/api/process-runs", json=_run_body(m2, ["QV3-1"], project_code="A66")).status_code == 422
    assert hhs.post("/api/process-runs", json=_run_body(m2, marks[:1], material_id=987654)).status_code == 422
    first = _make_run(hhs, m2, 1)
    # 두 사람이 동시에 저장해 같은 공정런 번호를 받은 상황 → UNIQUE 위반 → 409
    monkeypatch.setattr(numbering, "next_run_no", lambda db, d: first["run_no"])
    r = hhs.post("/api/process-runs", json=_run_body(m2, marks[1:2]))
    assert r.status_code == 409, r.text
    monkeypatch.undo()
    r = hhs.post("/api/import/excel", files={"file": ("broken.xlsx", b"not a zip")}, data={"dry_run": "true"})
    assert r.status_code == 422 and "엑셀" in r.json()["detail"]


# ── §8 대상별 권한 ───────────────────────────────────────────────────
def test_permissions_by_target(hhs, kim, m2):
    run = _make_run(hhs, m2, 3)                                         # hhs의 공정런·원판
    run_no, p1, p2, p3 = (run["run_no"], *[p["short_id"] for p in run["panels"]])
    tr = hhs.post("/api/test-runs", json={"template_id": _tpl_id(), "start_date": "2026-10-22",
                                          "specimens": [{"short_id": p1}]}).json()["test_run_no"]
    ev = {"event_type": "SCRAP", "event_date": "2026-10-22"}
    # 다른 연구원도 남의 시편을 잘라 자기 과제로 쓸 수 있음 (시편번호 체계 3.6절) — 부모 상태·위치는 못 바꿈
    r = kim.post(f"/api/specimens/{p3}/split", json={"count": 1, "start": 1, "project_code": "B6"})
    assert r.status_code == 200 and r.json()["children"][0]["display_id"].split("-")[1] == "B6", r.text
    assert kim.post(f"/api/specimens/{p1}/events", json=ev).status_code == 403
    assert kim.patch(f"/api/specimens/{p1}", json={"storage_location": "x"}).status_code == 403
    assert kim.post(f"/api/test-runs/{tr}/board", json=[{"short_id": p2}]).status_code == 403
    assert kim.post(f"/api/test-runs/{tr}/unload", json={"short_id": p1}).status_code == 403
    assert kim.post(f"/api/test-runs/{tr}/cycles", json={"delta": 1}).status_code == 403
    ba = kim.post("/api/bath-analyses", json={"pot": "POT-9", "sampled_at": "2026-10-22T09:00:00",
                                              "composition": {"Zn": 25, "Al": "bal."}}).json()
    assert kim.post(f"/api/bath-analyses/{ba['id']}/apply", json={"run_nos": [run_no]}).status_code == 403
    # 결과 입력은 누구나 (§8)
    assert kim.put(f"/api/test-runs/{tr}/results/{p1}/1", json={"metrics": {"peel_grade": 1}}).status_code == 200
    # 파일: 미분류는 누구나 붙이고, 이미 붙은 파일은 올린 사람·시편 소유자·관리자만 옮김
    own = hhs.post("/api/files", files={"files": (f"{p1}_note.txt", b"hhs file")}).json()["results"][0]
    assert own["status"] == "matched"
    assert kim.patch(f"/api/files/{own['attachment_id']}", json={"short_id": p2}).status_code == 403
    loose = kim.post("/api/files", files={"files": ("loose_kim.txt", b"kim file")}).json()["results"][0]
    assert loose["status"] == "unmatched"
    assert kim.patch(f"/api/files/{loose['attachment_id']}", json={"short_id": p2}).status_code == 200
    assert hhs.post(f"/api/specimens/{p2}/events", json=ev).status_code == 200      # 소유자는 가능


# ── 대표값: 가장 최근 측정의 출처 (D-37) ───────────────────────────────────
def test_latest_measurement_wins(db, user_id, m2):
    marks = [b.short_id for b in blanks(db, user_id, 1)]
    run = workflow.create_process_run(db, ProcessRunIn(**{**_run_body(m2, marks), "run_date": date(2026, 10, 22)}),
                                      user_id)
    panel = run.panels[0]
    t0 = datetime(2026, 10, 22, 9, 0)
    actuals.add_actual(db, run, "out.cw_top", 54, specimen=panel, source="test", measured_at=t0)
    actuals.add_actual(db, run, "out.cw_top", 57, specimen=panel, source="manual", measured_at=t0 + timedelta(hours=1))
    actuals.recompute_run(db, run)
    e = actuals.RunActuals(db, run).effective(panel, "out.cw_top")
    assert (e.actual, e.source) == (57, "manual")                       # 나중 수기 정정이 대표값
    actuals.add_actual(db, run, "out.cw_top", 55, specimen=panel, source="test", measured_at=t0 + timedelta(hours=1))
    db.flush()
    e = actuals.RunActuals(db, run).effective(panel, "out.cw_top")
    assert (e.actual, e.source) == (54.5, "test")                       # 같은 시각이면 출처 순위, 그 출처 행 평균
    assert db.scalar(select(ParamActual.id).where(ParamActual.value.is_(None),
                                                  ParamActual.process_run_id == run.id)) is None


def test_material_fixture_present():
    with SessionLocal() as db:
        assert db.scalar(select(Material.coil_code).where(Material.coil_no == "CQV3141")) == "QV3"
