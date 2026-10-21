"""11.2 기준 시나리오 (1단계 완료 검증용)를 서비스 계층에서 재현."""
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from app.config import TMP_DIR
from app.models import Material, ParamActual, ProcessPreset, TestTemplate
from app.schemas import ProcessRunIn, SplitIn, TestRunIn
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
    mat = db.scalar(select(Material).where(Material.coil_no == "POS-26-8891"))
    recipe = pdict.preset_recipe(m2.overrides)
    recipe["rth"]["DP"] = -42                                  # 1. 이슬점만 수정
    run = workflow.create_process_run(db, ProcessRunIn(
        dict_version=pdict.version(), preset_id=m2.id, project_code="26P4", material_id=mat.id,
        run_date=date(2026, 10, 21), coating_weight_target=60, panel_count=5, serial_start=101,
        recipe=recipe, changed_from_preset=["rth.DP"]), user_id)
    panels = run.panels
    assert [p.display_id for p in panels] == [f"M206K-26P4-P010{i}" for i in range(1, 6)]
    assert run.base_condition_code == "M206K"

    # 번호 충돌 → Conflict
    try:
        workflow.create_process_run(db, ProcessRunIn(
            dict_version=pdict.version(), preset_id=m2.id, project_code="26P4", run_date=date(2026, 10, 21),
            coating_weight_target=60, panel_count=2, serial_start=105, recipe=recipe), user_id)
        raise AssertionError("충돌이 나야 합니다")
    except workflow.Conflict as e:
        assert e.items == ["26P4-P0105"]

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
                                                   specimens=[{"short_id": "26P4-P0102"}]), user_id)
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

    # 2. P0101 → S0101 분기, SEM 시험런 탑승
    s0101 = workflow.split(db, p0101, SplitIn(stage="S", count=1, serial_start=101), user_id)[0]
    assert s0101.short_id == "26P4-S0101" and s0101.condition_code == "M206K"
    tr_sem1 = workflow.create_test_run(db, TestRunIn(template_id=_tpl(db, "SEM_SECTION").id,
                                                     start_date=date(2026, 10, 22),
                                                     specimens=[{"short_id": "26P4-S0101"}]), user_id)
    assert tr_sem1.test_run_no == "TR-SEM-26001"

    # 3. SEM 파일 자동 연결
    r = file_ingest.ingest(db, _tmpfile("a.tif", b"fake-sem-1"), "26P4-S0101_SEM_init.tif", user_id=user_id)
    assert r.status == "matched" and r.short_id == "26P4-S0101"

    # 4. P0102, P0103 → C0102, C0103 (부착량 실측은 '시험·P0102'로 상속)
    c0102 = workflow.split(db, p0102, SplitIn(stage="C", count=1, serial_start=102), user_id)[0]
    c0103 = workflow.split(db, p0103, SplitIn(stage="C", count=1, serial_start=103), user_id)[0]
    ra = actuals.RunActuals(db, run)
    e = ra.effective(c0102, "out.cw_top")
    assert e.actual == 54 and e.inherited_from == "26P4-P0102" and e.badge == "시험·P0102"
    assert c0102.material_id == mat.id and c0102.process_run_id == run.id

    # 5. CCT 8주: 탑승 → 주간 사진(_W01…) → 적청률
    tr_cct = workflow.create_test_run(db, TestRunIn(template_id=_tpl(db, "CCT_STD").id,
                                                    start_date=date(2026, 10, 23), equipment="CCT-01",
                                                    specimens=[{"short_id": "26P4-C0102", "slot": "A-03"},
                                                               {"short_id": "26P4-C0103", "slot": "A-04"}]), user_id)
    assert tr_cct.test_run_no == "TR-CCT-26001" and c0102.status == "IN_TEST"
    for w in range(0, 9):
        res = file_ingest.ingest(db, _tmpfile(f"w{w}.jpg", f"img{w}".encode()), f"26P4-C0102_W{w:02d}_front.jpg",
                                 user_id=user_id, test_run=tr_cct)
        assert res.status == "matched" and res.cycle == w
        workflow.save_result(db, tr_cct, c0102, w, {"red_rust_pct": min(w, 5)}, user_id)
    dup = file_ingest.ingest(db, _tmpfile("dup.jpg", b"img3"), "copy.jpg", user_id=user_id)
    assert dup.status == "duplicate"
    un = file_ingest.ingest(db, _tmpfile("x.jpg", b"unknown"), "IMG_0001.jpg", user_id=user_id)
    assert un.status == "unmatched"

    # 6. C0102 → S0102 → TR-SEM-26002
    workflow.finish_test_run(db, tr_cct, date(2026, 12, 18))
    assert c0102.status == "AVAILABLE"
    s0102 = workflow.split(db, c0102, SplitIn(stage="S", count=1, serial_start=102), user_id)[0]
    tr_sem2 = workflow.create_test_run(db, TestRunIn(template_id=_tpl(db, "SEM_SECTION").id,
                                                     start_date=date(2026, 12, 19),
                                                     specimens=[{"short_id": "26P4-S0102"}]), user_id)
    assert tr_sem2.test_run_no == "TR-SEM-26002"

    # 7. 계보 + 검색 '부착량 50~55 g/m²(대표값)'
    chain = [n["label"] for n in lineage.chain(s0102)]
    assert chain == ["POS-26-8891", run.run_no, "26P4-P0102", "26P4-C0102", "26P4-S0102"]
    found = search.run(db, search.Query(params=[search.ParamFilter("out.cw_top", 50, 55)]))
    ids = {s.short_id for s in found}
    assert {"26P4-P0102", "26P4-C0102", "26P4-S0102"} <= ids and "26P4-C0103" not in ids
    found_t = search.run(db, search.Query(basis="target", params=[search.ParamFilter("out.cw_top", 50, 55)]))
    assert "26P4-C0102" not in {s.short_id for s in found_t}

    # 붙여넣기: 실측 탭
    items, errs = workflow.parse_actuals_paste(run, "원판\t최고 판온\tak.P\n26P4-P0103\t799\t31\n세션\t\t")
    assert not errs and {"specimen": "26P4-P0103", "key": "rth.T", "value": "799"} in items


def test_series_and_bath(db, user_id):
    m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
    recipe = pdict.preset_recipe(m2.overrides)
    run = workflow.create_process_run(db, ProcessRunIn(
        dict_version=pdict.version(), preset_id=m2.id, project_code="26X1", run_date=date(2026, 10, 22),
        coating_weight_target=60, panel_count=5, serial_start=1, recipe=recipe,
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
