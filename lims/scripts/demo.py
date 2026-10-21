"""11.2 기준 시나리오를 데모 데이터로 재현 (시연·교육용).

사용:  python -m scripts.demo        (lims 폴더에서, 빈 DB 권장)
원소재 POS-26-8891 → PR(M2, 60 g/m², 원판 5매) → 실측 → CW_MEASURE → 분기 → CCT 8주 사진 → SEM.
"""
from __future__ import annotations

import io
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import TMP_DIR  # noqa: E402
from app.db import Base, SessionLocal, current_user_id, engine  # noqa: E402
from app.models import BathAnalysis, Material, ProcessPreset, ProcessRun, TestTemplate, User  # noqa: E402
from app.schemas import ProcessRunIn, SplitIn, TestRunIn  # noqa: E402
from app.services import actuals, file_ingest, workflow  # noqa: E402
from app.services import param_dict as pdict  # noqa: E402
from scripts.seed import seed  # noqa: E402


def panel_photo(seed_: int, rust: float, label: str) -> Path:
    """부식 진행을 흉내 낸 시편 사진(합성)."""
    rnd = random.Random(seed_)
    im = Image.new("RGB", (900, 600), (196, 200, 204))
    d = ImageDraw.Draw(im)
    for _ in range(2500):
        x, y = rnd.randrange(900), rnd.randrange(600)
        g = rnd.randrange(170, 225)
        d.point((x, y), fill=(g, g + 2, g + 5))
    for _ in range(int(rust * 60)):
        x, y, r = rnd.randrange(60, 840), rnd.randrange(60, 540), rnd.randrange(3, 14)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(rnd.randrange(140, 180), rnd.randrange(70, 100), 40))
    im = im.filter(ImageFilter.GaussianBlur(0.8))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 900, 40), fill=(30, 34, 40))
    d.text((14, 12), label, fill=(255, 255, 255))
    p = TMP_DIR / f"demo_{seed_}.jpg"
    im.save(p, "JPEG", quality=85)
    return p


def sem_image(seed_: int, label: str) -> Path:
    rnd = random.Random(seed_)
    im = Image.new("L", (1024, 768), 30)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 420, 1024, 768), fill=110)            # 소지
    for x in range(0, 1024, 4):                            # 도금층
        top = 300 + rnd.randrange(-12, 12)
        d.line((x, top, x, 420), fill=rnd.randrange(170, 215))
    for _ in range(140):
        x, y = rnd.randrange(1024), rnd.randrange(310, 415)
        d.ellipse((x - 4, y - 2, x + 4, y + 2), fill=240)
    d.rectangle((0, 728, 1024, 768), fill=0)
    d.text((12, 740), label, fill=255)
    p = TMP_DIR / f"demo_sem_{seed_}.tif"
    im.save(p, "TIFF")
    return p


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db, demo=True)
        if db.scalar(select(ProcessRun).limit(1)):
            print("이미 데이터가 있습니다. 빈 DB에서 실행하세요.")
            return
        hhs = db.scalar(select(User).where(User.emp_no == "hhs"))
        current_user_id.set(hhs.id)
        uid = hhs.id
        m2 = db.scalar(select(ProcessPreset).where(ProcessPreset.name == "M2"))
        mat = db.scalar(select(Material).where(Material.coil_no == "POS-26-8891"))
        tpl = {t.code: t for t in db.scalars(select(TestTemplate))}

        # 1. 공정런: 프리셋 M2 → 이슬점만 수정 → 원판 5매 P0101~
        rcp = pdict.preset_recipe(m2.overrides)
        rcp["rth"]["DP"] = -42
        run = workflow.create_process_run(db, ProcessRunIn(
            dict_version=pdict.version(), preset_id=m2.id, project_code="26P4", material_id=mat.id,
            run_date=date(2026, 10, 21), coating_weight_target=60, panel_count=5, serial_start=101, recipe=rcp,
            changed_from_preset=["rth.DP"], note="M2 기준 시나리오 · 이슬점 −42 °C"), uid)
        p = {s.short_id[-5:]: s for s in run.panels}

        # 1b. 세션 욕온·이슬점, 원판별 최고판온·나이프 압력
        actuals.set_manual_cell(db, run, "pot.T", 588.5, specimen=None, user_id=uid, method="열전대")
        actuals.set_manual_cell(db, run, "rth.DP", -36, specimen=None, user_id=uid, method="노점계")
        for sid, t in (("P0101", 796), ("P0102", 802), ("P0103", 805)):
            actuals.set_manual_cell(db, run, "rth.T", t, specimen=p[sid], user_id=uid, method="열전대")
        actuals.set_manual_cell(db, run, "ak.P", 30, specimen=p["P0101"], user_id=uid)
        ba = BathAnalysis(pot="POT-1", sampled_at=datetime(2026, 10, 21, 9, 30), method="ICP", user_id=uid,
                          composition={"Zn": 25.1, "Si": 2.9, "Mg": 0.46, "Fe": 0.4, "Al": "bal."})
        db.add(ba)
        db.flush()
        actuals.apply_bath_analysis(db, ba, [run], uid)

        # 1c. P0102 부착량 CW_MEASURE → 실측 자동 반영 (실측 기준 M205K)
        tr_cw = workflow.create_test_run(db, TestRunIn(template_id=tpl["CW_MEASURE"].id, start_date=date(2026, 10, 21),
                                                       equipment="XRF-01", specimens=[{"short_id": "26P4-P0102"},
                                                                                      {"short_id": "26P4-P0103"}]), uid)
        workflow.save_result(db, tr_cw, p["P0102"], 0, {"cw_top": 54, "cw_bottom": 58, "method": "중량법", "n_points": 3}, uid)
        workflow.save_result(db, tr_cw, p["P0103"], 0, {"cw_top": 61, "cw_bottom": 59, "method": "중량법", "n_points": 3}, uid)
        workflow.finish_test_run(db, tr_cw, date(2026, 10, 21))

        # 2~3. P0101 → S0101 → TR-SEM → SEM 파일
        s0101 = workflow.split(db, p["P0101"], SplitIn(stage="S", count=1, serial_start=101, size_text="20x20"), uid)[0]
        tr_sem = workflow.create_test_run(db, TestRunIn(template_id=tpl["SEM_SECTION"].id, start_date=date(2026, 10, 22),
                                                        equipment="SEM-01", conditions={"kv": 15},
                                                        specimens=[{"short_id": s0101.short_id}]), uid)
        workflow.save_result(db, tr_sem, s0101, 0, {"magnification": 5000, "detector": "BSE", "layer_thickness_um": 21.4}, uid)
        file_ingest.ingest(db, sem_image(1, "26P4-S0101 BSE x5000"), "26P4-S0101_SEM_init.tif", user_id=uid)

        # 4. P0102, P0103 → C0102, C0103 (+ C0104~ 같은 원판에서)
        c0102 = workflow.split(db, p["P0102"], SplitIn(stage="C", count=1, serial_start=102, sample_position="C",
                                                       rolling_direction="RD", surface_side="TOP"), uid)[0]
        c0103 = workflow.split(db, p["P0103"], SplitIn(stage="C", count=1, serial_start=103, sample_position="C"), uid)[0]
        db.add_all([])
        # 5. CCT 8주 (W00~W08), 매주 사진 + 적청률
        start = date(2026, 10, 23)
        tr_cct = workflow.create_test_run(db, TestRunIn(
            template_id=tpl["CCT_STD"].id, start_date=start, equipment="CCT-01",
            conditions={"salt_conc": 5, "temp_dry": 60, "temp_wet": 50},
            specimens=[{"short_id": c0102.short_id, "slot": "A-03"}, {"short_id": c0103.short_id, "slot": "A-04"}]), uid)
        rust = {c0102.short_id: [0, 0, 0, 1, 1, 2, 3, 3, 4], c0103.short_id: [0, 0, 0, 0, 0, 1, 1, 1, 2]}
        for w in range(9):
            for c in (c0102, c0103):
                rr = rust[c.short_id][w]
                f = panel_photo(w * 10 + int(c.serial_no), rr, f"{c.short_id}  W{w:02d}  front")
                file_ingest.ingest(db, f, f"{c.short_id}_W{w:02d}_front.jpg", user_id=uid, test_run=tr_cct)
                workflow.save_result(db, tr_cct, c, w, {"red_rust_pct": rr, "white_rust_pct": min(5 + 3 * w, 40)}, uid,
                                     start + timedelta(days=7 * w))
        workflow.finish_test_run(db, tr_cct, start + timedelta(days=56))

        # 6. C0102 부식 단면 → S0102 → TR-SEM-26002
        s0102 = workflow.split(db, c0102, SplitIn(stage="S", count=1, serial_start=102, size_text="15x20"), uid)[0]
        tr_sem2 = workflow.create_test_run(db, TestRunIn(template_id=tpl["SEM_SECTION"].id,
                                                         start_date=start + timedelta(days=57), equipment="SEM-01",
                                                         specimens=[{"short_id": s0102.short_id}]), uid)
        workflow.save_result(db, tr_sem2, s0102, 0, {"magnification": 2000, "detector": "BSE", "region": "부식 단면"}, uid)
        file_ingest.ingest(db, sem_image(2, "26P4-S0102 corroded section"), "26P4-S0102_SEM_corrosion_x2000.tif", user_id=uid)

        # 진행 중 시험런 하나 (홈 화면 빈칸 표시용)
        more = workflow.split(db, p["P0104"], SplitIn(stage="C", count=4, serial_start=104), uid)
        tr_sst = workflow.create_test_run(db, TestRunIn(template_id=tpl["SST_STD"].id, start_date=date(2026, 10, 19),
                                                        equipment="SST-02", specimens=[{"short_id": k.short_id, "slot": f"B-{i+1:02d}"}
                                                                                       for i, k in enumerate(more)]), uid)
        for i, k in enumerate(more):
            for d in range(2 + i % 2):
                workflow.save_result(db, tr_sst, k, d, {"red_rust_pct": 0, "white_rust_pct": d * 3}, uid)
        # 미분류 파일 1개 (홈 화면 미분류함)
        file_ingest.ingest(db, panel_photo(999, 0.5, "IMG_2031"), "IMG_2031.jpg", user_id=uid)
        db.commit()
        print(f"데모 완료: {run.run_no}, {tr_cct.test_run_no}, {tr_sem.test_run_no}, {tr_sem2.test_run_no}, {tr_sst.test_run_no}")
        print(f"S0102 실측 기준 조건부(P0102): {actuals.actual_condition_code(db, p['P0102'])}")


if __name__ == "__main__":
    main()
