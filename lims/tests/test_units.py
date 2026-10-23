"""번호 발급·조건부·파일명 파서 단위 테스트 (4.3절 '필수')."""
from datetime import date

import pytest

from app.services import condition_code as cc
from app.services import file_ingest as fi
from app.services import marking, numbering
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
    p = fi.parse_filename("QV3-102-01_W03_front.jpg")
    assert (p.short_id, p.cycle) == ("QV3-102-01", 3)
    p = fi.parse_filename("qv3-102-01-3_SEM_x5000_bse.tif")
    assert p.short_id == "QV3-102-01-3" and p.cycle is None
    assert fi.kind_of("QV3-102-01-3_SEM_x5000_bse.tif", p.tags) == "SEM"
    assert fi.parse_filename("IMG_2031.jpg").short_id is None
    assert fi.parse_filename("QV3-1_C12.png").cycle == 12
    assert fi.parse_filename("QV3-102-01_W3_x.jpg").cycle == 3
    # 전체번호로 지어도 각인번호로
    assert fi.parse_filename("QV3-A6-C-102-01-M206K-P12_W02.jpg").short_id == "QV3-102-01"


def test_marking_formats():
    assert marking.mark_id("QV3", "102", "01", "3") == "QV3-102-01-3"
    assert marking.find_mark("QV3-A6-C-102-M206K") == "QV3-102"
    assert marking.find_mark("QV3-A6-C-102-01-M206K-H03-T02-P12") == "QV3-102-01"   # 꼬리 블록을 조각으로 읽지 않음
    assert marking.find_mark("QV3-B6-E-105-P12") == "QV3-105"
    assert marking.find_mark("QV3-A6-A-1") == "QV3-1"
    assert marking.find_mark("qv3-102-01-a") == "QV3-102-01-A"
    assert marking.find_mark("QV3-10") is None and marking.find_mark("26P4-C0102") is None
    assert marking.tail_blocks([{"k": "PLATE"}, {"k": "HEAT", "code": "03"}, {"k": "PAINT", "code": "12"}],
                               "M206K") == ["M206K", "H03", "P12"]
    assert marking.full_id("QV3", "A6", "E", "105", None, None, ["T02", "P12"]) == "QV3-A6-E-105-T02-P12"
    assert marking.piece_char(9) == "9" and marking.piece_char(10) == "A" and "I" not in marking.PIECE_CHARS


def test_coil_code_candidates():
    assert marking.split_field_coil("CQV3141T") == ("CQV3141", "T")
    c = marking.coil_code_candidates("CQV3141T")
    assert c[:5] == ["QV3", "QV1", "QV4", "CV3", "CQ3"]       # 첫 숫자 → 나머지 숫자 → 다른 영문 조합
    assert all(marking.COIL_CODE_RE.match(x) for x in c)


def test_numbering(db, user_id):
    from helpers import blanks
    b1, b2, b3 = blanks(db, user_id, 3)
    sheet = b1.parent
    assert numbering.child_level(sheet) == "branch" and numbering.child_level(b1) == "cut"
    assert numbering.child_conflicts(db, sheet, 2, 3) == [b2.short_id, b3.short_id]
    assert numbering.next_child(db, sheet, 1) == 4
    assert numbering.next_child(db, sheet, 2, prefer=2) == 4
    assert numbering.next_child(db, sheet, 1, prefer=50) == 50
    assert numbering.next_sheet(db, sheet.coil_code) == 2
    assert numbering.label_of(b1, 1) == f"{b1.short_id}-01"
    with pytest.raises(numbering.NumberingError):
        numbering.child_conflicts(db, sheet, 99, 2)            # 조각 번호는 01~99


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
