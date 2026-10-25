"""공정 계열·변형번호 (시편번호 체계 3.3절·D-23 ~ D-26, 설계서 D-50·D-51): 꼬리 M206K03 = 조건부 + 계열 안의 조건 카드."""
from datetime import date

from sqlalchemy import select

from app.models import MasterCode, ProcessPreset, ProcessVariant
from app.schemas import ProcessRunIn
from app.services import condition_code as cc
from app.services import marking, search, workflow
from app.services import param_dict as pdict
from helpers import blanks


def _zam(db) -> ProcessPreset:
    return db.scalar(select(ProcessPreset).where(ProcessPreset.name == "ZAM"))


def _rcp(preset, cw=60, **changes) -> dict:
    r = pdict.preset_recipe(preset.overrides)
    r["out"]["cw"] = cw
    for k, v in changes.items():
        sec, pk = k.split("__")
        r[sec][pk] = v
    return r


def test_plate_label_and_parse():
    assert marking.plate_label("M206K", None) == "M206K" and marking.plate_label("M206K", 0) == "M206K"
    assert marking.plate_label("M206K", 3) == "M206K03" and marking.plate_label("MX06K", 112) == "MX06K112"
    assert marking.parse_plate("m206k03") == ("M206K", 3) and marking.parse_plate("M206K") == ("M206K", None)
    assert marking.parse_plate("M206K00") == ("M206K", 0) and marking.parse_plate("MX05X01") == ("MX05X", 1)
    assert marking.parse_plate("QV3-A02") is None
    assert marking.tail_blocks([{"k": "PLATE"}, {"k": "PAINT", "code": "12"}], "M206K", 3) == ["M206K03", "P12"]
    # 변형번호가 붙어도 전체번호에서 각인번호를 읽음 (꼬리는 무시)
    assert marking.find_mark("QV3-A6-C-A02-A-M206K03-P12") == "QV3-A02-A"


def test_fingerprint_normalizes():
    a = cc.process_values(pdict.preset_recipe({"pot": {"Mg": 0.5, "T": 590}}))
    b = cc.process_values(pdict.preset_recipe({"pot": {"Mg": 0.50, "T": 590.0}}))
    assert cc.fingerprint(a) == cc.fingerprint(b)
    assert not any(k.startswith("out.") for k in a)                     # 부착량은 지문에서 뺌
    off1 = cc.process_values(pdict.merge(pdict.defaults(), {"ga": {"on": False, "T": 520}}))
    off2 = cc.process_values(pdict.merge(pdict.defaults(), {"ga": {"on": False, "T": 560}}))
    assert off1 == off2 and off1["ga.on"] is False and "ga.T" not in off1   # 꺼진 구간의 값은 조건이 아님


def test_public_presets_are_family_standards(db):
    for p in db.scalars(select(ProcessPreset).where(ProcessPreset.scope == "PUBLIC")):
        assert p.variant_seq == 0, p.name
        assert p.variant_id == f"{p.coating_system}{p.bath_code}-00"
    std = cc.standard_of(db, "Z1")
    assert std.name == "ZAM" and std.origin == "PUBLIC"


def test_assign_variant_rules(db):
    zam, codes = _zam(db), cc.CodeBook.load(db)
    code = lambda r: cc.code_from_recipe(codes, "Z", r, "1")  # noqa: E731
    std = _rcp(zam)
    assert code(std) == "Z106K" and cc.assign_variant(db, code(std), std) == 0          # 프리셋 그대로 = 00
    dp = _rcp(zam, rth__DP=-42.0)
    assert code(dp) == "Z106K"                                    # 허용오차 안: 조건부는 같음
    s_dp = cc.assign_variant(db, code(dp), dp)
    assert s_dp >= 1 and cc.assign_variant(db, code(dp), _rcp(zam, rth__DP=-42)) == s_dp   # 같은 조건 = 같은 번호
    s_t = cc.assign_variant(db, "Z106K", _rcp(zam, pot__T=445))   # 코드에 없는 값(욕온)도 가름
    assert s_t not in (0, s_dp)
    # 번호는 부착량을 넘어 유지: 같은 공정의 부착량 시리즈는 같은 번호 (M209K02 · M206K02처럼)
    dp90 = _rcp(zam, cw=90, rth__DP=-42.0)
    assert code(dp90) == "Z109K" and cc.assign_variant(db, code(dp90), dp90) == s_dp
    # 부착량 겹침 예외: 같은 조건부(05)에 다른 목표 부착량(45 → 50)이면 새 번호
    s45 = cc.assign_variant(db, "Z105K", _rcp(zam, cw=45, rth__DP=-42.0))
    s50 = cc.assign_variant(db, "Z105K", _rcp(zam, cw=50, rth__DP=-42.0))
    assert s45 == s_dp and s50 not in (s_dp, 0)
    assert cc.assign_variant(db, "Z105K", _rcp(zam, cw=50, rth__DP=-42.0)) == s50
    card = db.scalar(select(ProcessVariant).where(ProcessVariant.family == "Z1", ProcessVariant.seq == s_dp))
    assert card.origin == "RUN" and "이슬점" in card.name and "-42" in card.name


def test_new_bath_gets_numbers_not_one_x(db):
    """코드표에 없는 욕은 계열 X로 모이지만 조성마다 번호가 달라 섞이지 않음."""
    zam, codes = _zam(db), cc.CodeBook.load(db)
    a = _rcp(zam, pot__Al=9.0, pot__Mg=5.0)
    b = _rcp(zam, pot__Al=13.0, pot__Mg=5.0)
    ca, cb = cc.code_from_recipe(codes, "Z", a, "1"), cc.code_from_recipe(codes, "Z", b, "1")
    assert ca == cb == "ZX06K"
    sa, sb = cc.assign_variant(db, ca, a), cc.assign_variant(db, cb, b)
    assert sa >= 1 and sb >= 1 and sa != sb                       # X 계열엔 공용 표준이 없어 00이 없음


def test_preview_predicts_numbers(db):
    zam, codes = _zam(db), cc.CodeBook.load(db)
    items = [(cc.code_from_recipe(codes, "Z", r, "1"), r) for r in
             (_rcp(zam), _rcp(zam, ak__P=21), _rcp(zam, ak__P=22), _rcp(zam, ak__P=21))]
    pv = cc.preview_variants(db, items)
    assert pv[0]["seq"] == 0 and pv[0]["label"] == "Z106K" and not pv[0]["is_new"]
    assert pv[1]["is_new"] and pv[2]["seq"] == pv[1]["seq"] + 1 and pv[3]["seq"] == pv[1]["seq"]
    assert db.scalar(select(ProcessVariant).where(ProcessVariant.family == "Z1",
                                                  ProcessVariant.seq == pv[1]["seq"])) is None   # 저장 안 함


def test_run_tail_search_and_promotion(db, user_id):
    """공정런 저장 → 꼬리에 변형번호, 검색(꼬리·카드 ID), 코드표 등록(X 해소) 뒤 새 계열로 옮겨감."""
    zam = _zam(db)
    recipe = _rcp(zam, pot__Al=8.0, pot__Mg=4.0)                   # 코드표에 없는 Zn-8Al-4Mg
    marks = [b.short_id for b in blanks(db, user_id, 2)]
    run = workflow.create_process_run(db, ProcessRunIn(
        dict_version=pdict.version(), preset_id=zam.id, project_code="A6", run_date=date(2026, 10, 25),
        coating_weight_target=60, specimens=marks, recipe=recipe), user_id)
    p = run.panels[0]
    assert p.condition_code == "ZX06K" and p.variant_seq >= 1
    assert p.display_id.endswith(f"-ZX06K{p.variant_seq:02d}") and run.base_condition_label == p.condition_label
    found = {s.short_id for s in search.run(db, search.Query(code=p.condition_label))}
    assert set(marks) <= found
    assert set(marks) <= {s.short_id for s in search.run(db, search.Query(code=f"ZX-{p.variant_seq:02d}"))}
    assert not set(marks) & {s.short_id for s in search.run(db, search.Query(code="ZX06K00"))}
    # 관리 › 코드표에 Z5 = Zn-8Al-4Mg 등록 → 재계산하면 Z5 계열로 (공용 표준이 없어 01부터)
    db.add(MasterCode(category="BATH", code="Z5", name="Zn-8Al-4Mg",
                      spec={"el": {"Al": [8.0, 1.0], "Mg": [4.0, 1.0], "Si": [0, 0.05]}}))
    db.flush()
    assert workflow.refresh_condition_codes(db, run) == 2
    assert p.condition_code == "Z506K" and p.variant_seq == 1 and p.condition_label == "Z506K01"
    old = db.scalar(select(ProcessVariant).where(ProcessVariant.family == "ZX", ProcessVariant.fingerprint ==
                                                 cc.fingerprint(cc.process_values(recipe))))
    assert old is not None                                         # 옛 카드는 남고 번호는 다시 쓰지 않음


def test_team_preset_gets_card(db, user_id):
    zam = _zam(db)
    team = ProcessPreset(name="ZAM 저압 와이핑", scope="TEAM", owner_id=user_id, coating_system="Z", bath_code="1",
                         overrides={**zam.overrides, "ak": {"gas": "N₂", "P": 18}}, dict_version=pdict.version())
    db.add(team)
    db.flush()
    seq = cc.register_preset(db, team, user_id)
    assert seq >= 1 and team.variant_id == f"Z1-{seq:02d}"
    card = db.scalar(select(ProcessVariant).where(ProcessVariant.family == "Z1", ProcessVariant.seq == seq))
    assert card.name == "ZAM 저압 와이핑" and card.origin == "TEAM"
    # 그 프리셋을 그대로 쓴 공정런은 같은 번호
    r = pdict.preset_recipe(team.overrides)
    r["out"]["cw"] = 75
    assert cc.assign_variant(db, "Z108K", r) == seq
