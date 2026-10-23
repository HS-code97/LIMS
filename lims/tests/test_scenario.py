"""11.2 기준 시나리오 (1단계 완료 검증용)를 서비스 계층에서 재현 — 시편번호 체계 v3.0 (입고 → 전단 → 도금 …)."""
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from app.config import TMP_DIR
import pytest

from app.models import MasterCode, ParamActual, ProcessPreset, SpecimenEvent, TestTemplate, User
from app.schemas import IntakeIn, ProcessRunIn, SplitIn, TestRunIn, TreatIn
from app.services import actuals, file_ingest, lineage, search, workflow
from app.services import param_dict as pdict


def _tpl(db, code):
    return db.scalar(select(TestTemplate).where(TestTemplate.code == code))


def _tmpfile(name: str, content: bytes) -> Path:
    p = TMP_DIR / name
    p.write_bytes(content)
    return p


def test_reference_scenario(db, user_id):
    m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
    # 0. 입고: 현장 코일 CQV3141T (시드에 코일만 등록돼 있음 → 같은 코드 QV3, 전폭번호 1부터)
    sheets = workflow.intake(db, IntakeIn(coil_no="CQV3141T", project_code="A6", count=2,
                                          storage_location="보관함 A-3"), user_id)
    assert [s.short_id for s in sheets] == ["QV3-1", "QV3-2"] and sheets[0].display_id == "QV3-A6-A-1"
    assert sheets[0].coil_position == "T" and sheets[0].material.coil_no == "CQV3141"
    with pytest.raises(workflow.Conflict):                     # 같은 전폭번호 다시
        workflow.intake(db, IntakeIn(coil_no="CQV3141H", project_code="A6", count=1, sheet_start=2), user_id)
    # 0b. 전단: 전폭 1 → 블랭크 101~105 (단계 A → B)
    blanks = workflow.split(db, sheets[0], SplitIn(count=5, start=1), user_id)
    assert [b.short_id for b in blanks] == [f"QV3-10{i}" for i in range(1, 6)]
    assert blanks[0].display_id == "QV3-A6-B-101" and blanks[0].kind_name == "블랭크"
    with pytest.raises(workflow.Conflict) as e:
        workflow.split(db, sheets[0], SplitIn(count=2, start=5), user_id)
    assert e.value.items == ["QV3-105"]

    recipe = pdict.preset_recipe(m2.overrides)
    recipe["rth"]["DP"] = -42                                  # 1. 이슬점만 수정
    run = workflow.create_process_run(db, ProcessRunIn(
        dict_version=pdict.version(), preset_id=m2.id, project_code="A6",
        run_date=date(2026, 10, 21), coating_weight_target=60, specimens=[b.short_id for b in blanks],
        recipe=recipe, changed_from_preset=["rth.DP"]), user_id)
    panels = run.panels
    # 도금해도 각인번호는 그대로, 단계 C + 꼬리 M206K
    assert [p.short_id for p in panels] == [f"QV3-10{i}" for i in range(1, 6)]
    assert [p.display_id for p in panels] == [f"QV3-A6-C-10{i}-M206K" for i in range(1, 6)]
    assert run.base_condition_code == "M206K" and run.material.coil_code == "QV3"

    # 이미 도금한 시편·없는 시편은 도금 못 함
    with pytest.raises(workflow.Invalid) as e:
        workflow.create_process_run(db, ProcessRunIn(
            dict_version=pdict.version(), preset_id=m2.id, project_code="A6", run_date=date(2026, 10, 21),
            coating_weight_target=60, specimens=["QV3-105", "QV3-999"], recipe=recipe), user_id)
    assert any("이미 도금" in x for x in e.value.items) and any("없는 시편" in x for x in e.value.items)

    p0101, p0102, p0103 = panels[0], panels[1], panels[2]
    # 1b. 세션 욕온·이슬점, 원판별 최고판온
    actuals.set_manual_cell(db, run, "pot.T", 458.5, specimen=None, user_id=user_id, method="열전대")
    actuals.set_manual_cell(db, run, "rth.DP", -36, specimen=None, user_id=user_id, method="노점계")
    actuals.set_manual_cell(db, run, "rth.T", 796, specimen=p0101, user_id=user_id)
    actuals.set_manual_cell(db, run, "rth.T", 802, specimen=p0102, user_id=user_id)
    actuals.recompute_run(db, run)

    # 1c. P0102 부착량 CW_MEASURE → 실측 자동 반영, 실측 기준 M205K
    tr_cw = workflow.create_test_run(db, TestRunIn(template_id=_tpl(db, "CW_MEASURE").id,
                                                   start_date=date(2026, 10, 21),
                                                   specimens=[{"short_id": "QV3-102"}]), user_id)
    workflow.save_result(db, tr_cw, p0102, 0, {"cw_top": 54, "cw_bottom": 58, "method": "중량법"}, user_id)
    rows = db.scalars(select(ParamActual).where(ParamActual.specimen_id == p0102.id,
                                                ParamActual.param_key == "out.cw_top")).all()
    assert rows and rows[0].source == "test" and rows[0].value == 54
    assert p0102.condition_code == "M206K"
    assert actuals.actual_condition_code(db, p0102) == "M205K"

    ra = actuals.RunActuals(db, run)
    e = ra.effective(p0102, "out.cw_top")
    assert (e.actual, e.badge, e.out_of_tol) == (54, "시험", False)   # −10% = 허용편차 경계 안
    assert ra.effective(p0102, "rth.DP").badge == "세션"
    assert ra.effective(p0103, "ak.P").badge == "목표"

    # 2. QV3-101 → 단면 시편 QV3-101-01, SEM 시험런 탑승 (단계·꼬리 상속)
    s0101 = workflow.split(db, p0101, SplitIn(count=1, start=1), user_id)[0]
    assert s0101.short_id == "QV3-101-01" and s0101.display_id == "QV3-A6-C-101-01-M206K"
    tr_sem1 = workflow.create_test_run(db, TestRunIn(template_id=_tpl(db, "SEM_SECTION").id,
                                                     start_date=date(2026, 10, 22),
                                                     specimens=[{"short_id": "QV3-101-01"}]), user_id)
    assert tr_sem1.test_run_no == "TR-SEM-26001"
    assert tr_sem1.boardings[0].display_at == "QV3-A6-C-101-01-M206K"     # 탑승 당시 전체번호

    # 3. SEM 파일 자동 연결 (전체번호로 지은 파일명도 각인번호로)
    r = file_ingest.ingest(db, _tmpfile("a.tif", b"fake-sem-1"), "QV3-A6-C-101-01-M206K_SEM_init.tif", user_id=user_id)
    assert r.status == "matched" and r.short_id == "QV3-101-01"

    # 4. QV3-102, 103 → 실험편 102-01, 103-01 (부착량 실측은 '시험·102'로 상속)
    c0102 = workflow.split(db, p0102, SplitIn(count=1, start=1), user_id)[0]
    c0103 = workflow.split(db, p0103, SplitIn(count=1, start=1), user_id)[0]
    ra = actuals.RunActuals(db, run)
    e = ra.effective(c0102, "out.cw_top")
    assert e.actual == 54 and e.inherited_from == "QV3-102" and e.badge == "시험·102"
    assert c0102.material_id == run.material_id and c0102.process_run_id == run.id and c0102.kind_name == "실험편"

    # 5. CCT 8주: 탑승 → 주간 사진(_W01…) → 적청률
    tr_cct = workflow.create_test_run(db, TestRunIn(template_id=_tpl(db, "CCT_STD").id,
                                                    start_date=date(2026, 10, 23), equipment="CCT-01",
                                                    specimens=[{"short_id": "QV3-102-01", "slot": "A-03"},
                                                               {"short_id": "QV3-103-01", "slot": "A-04"}]), user_id)
    assert tr_cct.test_run_no == "TR-CCT-26001" and c0102.status == "IN_TEST"
    for w in range(0, 9):
        res = file_ingest.ingest(db, _tmpfile(f"w{w}.jpg", f"img{w}".encode()), f"QV3-102-01_W{w:02d}_front.jpg",
                                 user_id=user_id, test_run=tr_cct)
        assert res.status == "matched" and res.cycle == w
        workflow.save_result(db, tr_cct, c0102, w, {"red_rust_pct": min(w, 5)}, user_id)
    dup = file_ingest.ingest(db, _tmpfile("dup.jpg", b"img3"), "copy.jpg", user_id=user_id)
    assert dup.status == "duplicate"
    un = file_ingest.ingest(db, _tmpfile("x.jpg", b"unknown"), "IMG_0001.jpg", user_id=user_id)
    assert un.status == "unmatched"

    # 6. 102-01 → 분석조각 102-01-1 → TR-SEM-26002
    workflow.finish_test_run(db, tr_cct, date(2026, 12, 18))
    assert c0102.status == "AVAILABLE"
    s0102 = workflow.split(db, c0102, SplitIn(count=1, start=1), user_id)[0]
    assert s0102.short_id == "QV3-102-01-1" and s0102.kind_name == "분석조각"
    with pytest.raises(workflow.Invalid):                      # 분석조각은 더 자르지 않음
        workflow.split(db, s0102, SplitIn(count=1, start=1), user_id)
    tr_sem2 = workflow.create_test_run(db, TestRunIn(template_id=_tpl(db, "SEM_SECTION").id,
                                                     start_date=date(2026, 12, 19),
                                                     specimens=[{"short_id": "QV3-102-01-1"}]), user_id)
    assert tr_sem2.test_run_no == "TR-SEM-26002"

    # 7. 계보 (C 단계 번호로 A·B까지) + 검색 '부착량 50~55 g/m²(대표값)'
    chain = [n["label"] for n in lineage.chain(s0102)]
    assert chain == ["CQV3141", "QV3-1", run.run_no, "QV3-102", "QV3-102-01", "QV3-102-01-1"]
    assert [p["done"] for p in lineage.processes(s0102)] == [True, True, False, False, False]
    found = search.run(db, search.Query(params=[search.ParamFilter("out.cw_top", 50, 55)]))
    ids = {s.short_id for s in found}
    assert {"QV3-102", "QV3-102-01", "QV3-102-01-1"} <= ids and "QV3-103-01" not in ids
    found_t = search.run(db, search.Query(basis="target", params=[search.ParamFilter("out.cw_top", 50, 55)]))
    assert "QV3-102-01" not in {s.short_id for s in found_t}
    assert "QV3-102-01" in {s.short_id for s in search.run(db, search.Query(q="QV3-A6-C-102-01-M206K"))}

    # 붙여넣기: 실측 탭
    items, errs = workflow.parse_actuals_paste(run, "원판\t최고 판온\tak.P\nQV3-103\t799\t31\n세션\t\t")
    assert not errs and {"specimen": "QV3-103", "key": "rth.T", "value": "799"} in items


def test_series_and_bath(db, user_id):
    m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
    recipe = pdict.preset_recipe(m2.overrides)
    from helpers import blanks
    marks = [b.short_id for b in blanks(db, user_id, 5, project="Y6")]
    run = workflow.create_process_run(db, ProcessRunIn(
        dict_version=pdict.version(), preset_id=m2.id, project_code="Y6", run_date=date(2026, 10, 22),
        coating_weight_target=60, specimens=marks, recipe=recipe,
        series=[{"key": "ak.P", "values": [20, 30, 40, 50, 60]}, {"key": "out.cw", "values": [90, 75, 60, 45, 30]}]),
        user_id)
    ps = run.panels
    assert ps[1].target_overrides == {"out.cw": 75}           # ak.P 30 = 기본값 → 바뀐 키만
    assert [p.condition_code for p in ps] == ["M209K", "M208K", "M206K", "M205K", "M203K"]
    e = actuals.RunActuals(db, run).effective(ps[0], "ak.P")
    assert e.target == 20 and e.is_override

    from app.models import BathAnalysis
    ba = BathAnalysis(pot="POT-1", sampled_at=datetime(2026, 10, 22, 9), method="ICP",
                      composition={"Zn": 25.1, "Si": 2.9, "Mg": 0.46, "Fe": 0.4, "Al": "bal."})
    db.add(ba)
    db.flush()
    assert actuals.bath_values(ba) == {"pot.Si": 2.9, "pot.Mg": 0.46, "pot.Al": 71.14}
    actuals.apply_bath_analysis(db, ba, [run], user_id)
    e = actuals.RunActuals(db, run).effective(ps[2], "pot.Mg")
    assert e.actual == 0.46 and e.badge == "세션·분석"
    assert actuals.actual_condition_code(db, ps[2]) == "M206K"


def test_other_project_and_skip_stages(db, user_id):
    """다른 연구원이 내 전폭을 잘라 자기 과제로 쓰고, 도금 없이 바로 도장(B → E). 문자는 앞 단계를 다 거쳤다는 뜻이 아님."""
    from helpers import blanks
    kim = db.scalar(select(User).where(User.emp_no == "kim"))
    b1, b2 = blanks(db, user_id, 2, project="A6")
    sheet = b1.parent
    kids = workflow.split(db, sheet, SplitIn(count=2, start=11, project_code="B6"), kim.id)
    assert [k.display_id for k in kids] == [f"{sheet.coil_code}-B6-B-{sheet.branch}{n}" for n in (11, 12)]
    use = db.scalar(select(SpecimenEvent).where(SpecimenEvent.specimen_id == sheet.id, SpecimenEvent.event_type == "USE"))
    assert use is not None and use.params["to_project"] == "B6"
    # 코드표에 없는 조건 → 거부, 있으면 도장 → E로 건너뜀, 꼬리 P01, 각인번호 그대로
    with pytest.raises(workflow.Invalid):
        workflow.treat(db, kids[0], TreatIn(kind="PAINT", code="77", event_date=date(2026, 10, 24)), kim.id)
    mark = kids[0].short_id
    workflow.treat(db, kids[0], TreatIn(kind="PRETREAT", code="01", event_date=date(2026, 10, 24)), kim.id)
    assert kids[0].stage == "B"                                 # 전처리는 단계를 바꾸지 않음
    workflow.treat(db, kids[0], TreatIn(kind="PAINT", code="01", event_date=date(2026, 10, 24)), kim.id)
    assert (kids[0].short_id, kids[0].stage) == (mark, "E")
    assert kids[0].display_id.endswith("-E-" + mark.split("-", 1)[1] + "-T01-P01")
    workflow.treat(db, kids[0], TreatIn(kind="HEAT", code="01", event_date=date(2026, 10, 25)), kim.id)
    assert kids[0].stage == "E" and kids[0].tail == ["T01", "P01", "H01"]      # 단계는 내려가지 않음
    # 내 블랭크를 김연구가 자기 과제로 도장 → 과제·담당이 넘어가고 이력이 남음
    workflow.treat(db, b2, TreatIn(kind="PAINT", code="01", event_date=date(2026, 10, 24), project_code="B6"), kim.id)
    assert (b2.project_code, b2.owner_id) == ("B6", kim.id)
    assert db.scalar(select(SpecimenEvent).where(SpecimenEvent.specimen_id == b2.id, SpecimenEvent.event_type == "USE"))
    assert db.get(MasterCode, ("PAINT", "01")) is not None
