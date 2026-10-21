"""번호 발급·조건부·파일명 파서 단위 테스트 (4.3절 '필수')."""
from datetime import date

import pytest

from app.models import Specimen
from app.services import condition_code as cc
from app.services import file_ingest as fi
from app.services import numbering
from app.services import param_dict as pdict
from app.services.templates_engine import MetricsError, validate_metrics


def test_round_half_up():
    assert cc.round_half_up(4.5) == 5
    assert cc.round_half_up(6.0) == 6
    assert cc.round_half_up(5.4) == 5
    assert cc.round_half_up(2.5) == 3      # 은행가 반올림이 아님


@pytest.mark.parametrize("gpm,code", [(30, "03"), (45, "05"), (50, "05"), (60, "06"), (90, "09"), (120, "12"), (140, "14")])
def test_cw_code_appendix_c(db, gpm, code):
    codes = cc.CodeBook.load(db)
    rcp = pdict.preset_recipe({"pot": {"Al": 70.5, "Mg": 0.5, "Si": 3.0}})
    rcp["out"]["cw"] = gpm
    assert cc.code_from_recipe(codes, "M", rcp, "2")[2:4] == code


def test_condition_code_presets(db):
    codes = cc.CodeBook.load(db)
    import json
    from app.config import SEED_DIR
    presets = {p["name"]: p for p in json.load(open(SEED_DIR / "presets.json", encoding="utf-8"))["presets"]}
    expect = {"M2": "M206K", "M1": "M106K", "ZAM": "Z106K", "GI": "G106K", "GA": "A106K", "AZ": "Y106K", "AS": "L106K"}
    for name, code in expect.items():
        p = presets[name]
        rcp = pdict.preset_recipe(p["overrides"])
        rcp["out"]["cw"] = 60
        assert cc.code_from_recipe(codes, p["coating_system"], rcp, p["bath_code"]) == code, name


def test_condition_code_nonstandard(db):
    codes = cc.CodeBook.load(db)
    rcp = pdict.preset_recipe({"pot": {"Al": 60, "Mg": 0.5, "Si": 3}})   # 조성 이탈 → X
    rcp["out"]["cw"] = 45
    rcp["rth"]["DP"] = -20                                               # 소둔 비표준 → X
    assert cc.code_from_recipe(codes, "M", rcp, "2") == "MX05X"
    rcp["rth"]["DP"] = -10
    assert cc.code_from_recipe(codes, "M", rcp, "2")[-1] == "L"
    rcp["rth"]["T"] = 650
    assert cc.code_from_recipe(codes, "M", rcp, "2")[-1] == "X"


def test_parse_filename():
    p = fi.parse_filename("26P4-C0102_W03_front.jpg")
    assert (p.short_id, p.cycle) == ("26P4-C0102", 3)
    p = fi.parse_filename("26p4-s0102_SEM_x5000_bse.tif")
    assert p.short_id == "26P4-S0102" and p.cycle is None
    assert fi.kind_of("26P4-S0102_SEM_x5000_bse.tif", p.tags) == "SEM"
    assert fi.parse_filename("IMG_2031.jpg").short_id is None
    assert fi.parse_filename("26PA-P0001_C12.png").cycle == 12
    assert fi.parse_filename("26P4-C0102_W3_x.jpg").cycle == 3


def test_numbering(db, user_id):
    db.add_all([Specimen(project_code="26X0", stage="C", serial_no=f"{n:04d}") for n in (101, 102, 104)])
    db.flush()
    assert numbering.conflicts(db, "26X0", "C", 100, 6) == ["26X0-C0101", "26X0-C0102", "26X0-C0104"]
    assert numbering.next_free(db, "26X0", "C", 1) == 105
    assert numbering.next_free(db, "26X0", "C", 2, prefer=102) == 105
    assert numbering.next_free(db, "26X0", "C", 1, prefer=103) == 103
    with pytest.raises(numbering.NumberingError):
        numbering.conflicts(db, "26X0", "C", 9999, 2)


def test_run_numbers(db):
    assert numbering.next_run_no(db, date(2026, 10, 21)).startswith("PR-26-")
    assert numbering.next_test_run_no(db, "CCT", date(2026, 10, 23)) == "TR-CCT-26001"


def test_metrics_validation(db):
    from sqlalchemy import select
    from app.models import TestTemplate
    tpl = db.scalar(select(TestTemplate).where(TestTemplate.code == "CCT_STD"))
    clean, warn = validate_metrics(tpl, {"red_rust_pct": "1", "redrust": 3, "note": ""})
    assert clean == {"red_rust_pct": 1} and warn
    with pytest.raises(MetricsError):
        validate_metrics(tpl, {"red_rust_pct": 120})


def test_param_dict_range():
    rcp = pdict.defaults()
    assert pdict.out_of_range(rcp) == []
    rcp["pot"]["T"] = 900
    assert any("욕온" in e for e in pdict.out_of_range(rcp))
