"""시편번호 체계 v3.0 (`시편번호 체계.md`): 각인번호(short_id) = 코일-가지-후절단-조각, 단계 A~E,
과제코드 영문1+숫자1, 코일코드, 거친 공정(steps), 탑승 당시 전체번호

기존 데이터 이관(온라인 upgrade에서만 실행):
  과제   26P4 → 그해 등록 순서 영문 + 연도 끝자리(A6 …), 26X0/26X1/26X9 → X6/Y6/Z6
  코일   materials.coil_code를 코일번호에서 제안(겹치면 변형). 코일이 없는 시편은 '이관-{과제}' 코일을 만듦
  시편   P(원판) → 가지 3자리(1번 전폭부터 01~99 차례로), 단계 C, is_panel, 거친 공정 PLATE
         C(시험편)·S(분석 조각) → 부모 아래 후절단 01~ / 분석조각 1~9·A~Z (부모 단계·공정 상속)
         옛 약식번호는 legacy_id에 남겨 v2.3 번호가 각인된 시편도 조회됩니다(+ NOTE 이력).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23
"""
import re
from datetime import date

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

JSONT = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
PIECE_CHARS = "123456789" + LETTERS


def upgrade() -> None:
    with op.batch_alter_table('materials') as b:
        b.add_column(sa.Column('coil_code', sa.String(length=3), nullable=True))
        b.create_unique_constraint('uq_materials_coil_code', ['coil_code'])
    with op.batch_alter_table('run_specimens') as b:
        b.add_column(sa.Column('display_at', sa.String(length=60), nullable=True))
    with op.batch_alter_table('specimens') as b:
        b.add_column(sa.Column('coil_code', sa.String(length=3), nullable=True))
        b.add_column(sa.Column('branch', sa.String(length=3), nullable=True))
        b.add_column(sa.Column('cut_no', sa.String(length=2), nullable=True))
        b.add_column(sa.Column('piece_no', sa.String(length=1), nullable=True))
        b.add_column(sa.Column('mark', sa.String(length=16), nullable=True))
        b.add_column(sa.Column('coil_position', sa.String(length=2), nullable=True))
        b.add_column(sa.Column('steps', JSONT, nullable=True))
        b.add_column(sa.Column('is_panel', sa.Boolean(), nullable=True))
        b.add_column(sa.Column('legacy_id', sa.String(length=20), nullable=True))
        # 옛 short_id는 project_code·stage로 계산되는 열이라, 이관 중에는 새 단계를 임시 열에 둡니다(UNIQUE 충돌 방지)
        b.add_column(sa.Column('stage_new', sa.String(length=1), nullable=True))

    if context.is_offline_mode():
        op.execute("-- 데이터 이관(과제코드·코일코드·각인번호)은 온라인 'alembic upgrade head'에서만 실행됩니다. "
                   "기존 시편이 있는 DB는 이 SQL만으로 올리지 마세요.")
    else:
        _migrate_data(op.get_bind())

    if op.get_bind().dialect.name == 'postgresql':
        op.execute("ALTER TABLE specimens DROP CONSTRAINT IF EXISTS ck_serial_digits")
    with op.batch_alter_table('specimens') as b:
        b.drop_constraint('uq_short', type_='unique')
        b.drop_constraint('ck_stage', type_='check')
        b.drop_constraint('ck_serial_len', type_='check')
        b.drop_column('short_id')
        b.drop_column('serial_no')
        b.drop_column('engraved_label')
    op.execute("UPDATE specimens SET stage = stage_new WHERE stage_new IS NOT NULL")
    with op.batch_alter_table('specimens') as b:
        b.drop_column('stage_new')
        b.alter_column('mark', new_column_name='short_id', existing_type=sa.String(length=16), nullable=False)
        b.alter_column('coil_code', existing_type=sa.String(length=3), nullable=False)
        b.alter_column('branch', existing_type=sa.String(length=3), nullable=False)
        b.alter_column('is_panel', existing_type=sa.Boolean(), nullable=False)
    with op.batch_alter_table('specimens') as b:      # 이름을 바꾼 뒤에야 새 이름으로 제약을 걸 수 있음
        b.create_unique_constraint('uq_specimens_short_id', ['short_id'])
        b.create_check_constraint('ck_stage', "stage IN ('A','B','C','D','E')")
        b.create_check_constraint('ck_coil_code_len', 'length(coil_code) = 3')
        b.create_check_constraint('ck_branch_len', 'length(branch) IN (1, 3)')
        b.create_index('idx_spec_coil', ['coil_code'], unique=False)
        b.create_index('ix_specimens_legacy_id', ['legacy_id'], unique=False)
    if op.get_bind().dialect.name == 'postgresql':     # scripts/dump_ddl.py와 같은 정규식
        op.execute("ALTER TABLE specimens ADD CONSTRAINT ck_short_id_format "
                   "CHECK (short_id ~ '^[A-Z]{2}[0-9]-[0-9]([0-9]{2})?(-[0-9]{2}(-[1-9A-Z])?)?$')")


# ── 데이터 이관 ──────────────────────────────────────────────────────
def _migrate_data(bind) -> None:
    projects = sa.table('projects', sa.column('project_code'), sa.column('company_project_no'),
                        sa.column('project_name'), sa.column('manager_id'), sa.column('is_common'),
                        sa.column('created_at'))
    runs = sa.table('process_runs', sa.column('id'), sa.column('run_no'), sa.column('project_code'))
    mats = sa.table('materials', sa.column('id'), sa.column('coil_no'), sa.column('coil_code'), sa.column('note'))
    specs = sa.table('specimens', sa.column('id'), sa.column('project_code'), sa.column('stage'),
                     sa.column('serial_no'), sa.column('short_id'), sa.column('engraved_label'),
                     sa.column('parent_id'), sa.column('process_run_id'), sa.column('material_id'),
                     sa.column('coil_code'), sa.column('branch'), sa.column('cut_no'), sa.column('piece_no'),
                     sa.column('mark'), sa.column('steps', sa.JSON), sa.column('is_panel'), sa.column('legacy_id'),
                     sa.column('stage_new'), sa.column('created_at'))
    events = sa.table('specimen_events', sa.column('specimen_id'), sa.column('event_type'),
                      sa.column('params', sa.JSON), sa.column('event_date'))

    # 0. 옛 약식번호는 과제코드를 바꾸기 전에 읽어 둠 (계산 열이라 과제가 바뀌면 함께 바뀜)
    legacy = dict(bind.execute(sa.select(specs.c.id, specs.c.short_id)).all())

    # 1. 과제코드: 26P4 → A6 … (등록 순서), 26X0/X1/X9 → X6/Y6/Z6
    rows = bind.execute(sa.select(projects).order_by(projects.c.created_at, projects.c.project_code)).mappings().all()
    used = {r['project_code'] for r in rows if re.fullmatch(r'[A-Z]\d', r['project_code'])}
    remap = {}
    for r in rows:
        old = r['project_code']
        if old in used:
            continue
        m = re.match(r'^(\d{4})', r['company_project_no'] or '')
        d = m.group(1)[-1] if m else (old[1] if re.match(r'^\d{2}', old) else str(date.today().year % 10))
        new = None
        if r['is_common'] and re.fullmatch(r'\d{2}X\d', old):
            pref = {'0': 'X', '1': 'Y', '9': 'Z'}.get(old[-1])
            if pref and pref + d not in used:
                new = pref + d
        if new is None:
            new = next(ch + d for ch in LETTERS if ch not in 'XYZ' and ch + d not in used)
        used.add(new)
        remap[old] = new
    for old, new in remap.items():
        r = next(x for x in rows if x['project_code'] == old)
        bind.execute(projects.insert().values(project_code=new, company_project_no=r['company_project_no'],
                                              project_name=r['project_name'], manager_id=r['manager_id'],
                                              is_common=r['is_common'], created_at=r['created_at']))
        bind.execute(runs.update().where(runs.c.project_code == old).values(project_code=new))
        bind.execute(specs.update().where(specs.c.project_code == old).values(project_code=new))
        bind.execute(projects.delete().where(projects.c.project_code == old))

    # 2. 코일코드
    used_codes = {c for c in bind.execute(sa.select(mats.c.coil_code)).scalars() if c}

    def take(cands):
        for c in cands:
            if c not in used_codes:
                used_codes.add(c)
                return c
        for a in LETTERS:
            for b in LETTERS:
                for dd in '0123456789':
                    if a + b + dd not in used_codes:
                        used_codes.add(a + b + dd)
                        return a + b + dd
        raise RuntimeError('빈 코일코드가 없습니다.')

    for m in bind.execute(sa.select(mats).order_by(mats.c.id)).mappings().all():
        if not m['coil_code']:
            bind.execute(mats.update().where(mats.c.id == m['id']).values(coil_code=take(_candidates(m['coil_no']))))
    coil_of = dict(bind.execute(sa.select(mats.c.id, mats.c.coil_code)).all())

    # 3. 시편 → 각인번호
    all_specs = sorted(bind.execute(sa.select(specs)).mappings().all(), key=lambda r: legacy[r['id']] or '')
    if not all_specs:
        return
    run_no = dict(bind.execute(sa.select(runs.c.id, runs.c.run_no)).all())
    kids: dict = {}
    for s in all_specs:
        kids.setdefault(s['parent_id'], []).append(s)
    by_id = {s['id']: s for s in all_specs}

    def root_material(s):
        while s['material_id'] is None and s['parent_id'] is not None:
            s = by_id[s['parent_id']]
        return s['material_id']

    orphan_mat: dict = {}
    roots_by_coil: dict = {}
    for s in kids.get(None, []):
        mid = root_material(s)
        if mid is None:
            proj = (legacy[s['id']] or 'X').split('-')[0]
            if proj not in orphan_mat:
                code = take(_candidates(proj))
                bind.execute(mats.insert().values(coil_no=f'이관-{proj}', coil_code=code,
                                                  note='v3.0 이관: 코일이 없던 시편'))
                new_id = bind.execute(sa.select(mats.c.id).where(mats.c.coil_code == code)).scalar_one()
                orphan_mat[proj] = (new_id, code)
            mid, code = orphan_mat[proj]
        else:
            code = coil_of[mid]
        roots_by_coil.setdefault(code, []).append((s, mid))

    today = date.today()

    def write(s, code, mid, stage, steps, branch, cut, piece, is_panel):
        mark = '-'.join(x for x in (code, branch, cut, piece) if x)
        old = legacy[s['id']]
        bind.execute(specs.update().where(specs.c.id == s['id']).values(
            coil_code=code, branch=branch, cut_no=cut, piece_no=piece, mark=mark, stage_new=stage, steps=steps,
            is_panel=is_panel, legacy_id=old, material_id=s['material_id'] or mid))
        bind.execute(events.insert().values(specimen_id=s['id'], event_type='NOTE', event_date=today,
                                            params={'migrated': 'v2.3 → v3.0', 'old_id': old,
                                                    'old_label': s['engraved_label']}))
        for j, k in enumerate(kids.get(s['id'], []), start=1):
            if cut is None:
                write(k, code, mid, stage, list(steps), branch, f'{j:02d}', None, False)
            elif piece is None:
                if j > len(PIECE_CHARS):
                    raise RuntimeError(f"{old}의 자식이 {len(PIECE_CHARS)}개를 넘습니다.")
                write(k, code, mid, stage, list(steps), branch, cut, PIECE_CHARS[j - 1], False)
            else:
                raise RuntimeError(f"{legacy[k['id']]}: 분석 조각 아래 시편은 이관할 수 없습니다.")

    for code, roots in roots_by_coil.items():
        for i, (s, mid) in enumerate(roots):
            sheet, nn = 1 + i // 99, i % 99 + 1
            if sheet > 9:
                raise RuntimeError(f'코일 {code}의 원판이 891장을 넘습니다.')
            plated = s['process_run_id'] is not None
            steps = [{'k': 'PLATE', 'run': run_no.get(s['process_run_id'])}] if plated else []
            write(s, code, mid, 'C' if plated else 'B', steps, f'{sheet}{nn:02d}', None, None, plated)


def _candidates(coil_no: str) -> list[str]:
    """app.services.marking.coil_code_candidates와 같은 규칙 (마이그레이션은 앱 코드에 기대지 않음)."""
    up = re.sub(r'\s+', '', (coil_no or '').upper())
    m = re.match(r'^([A-Z]{3})(\d{4})[A-Z0-9]?$', up)
    if m:
        letters, digits = m.group(1), m.group(2)
    else:
        letters = ''.join(ch for ch in up if 'A' <= ch <= 'Z') or 'XX'
        digits = ''.join(ch for ch in up if ch.isdigit()) or '0'
        letters = (letters * 3)[:3] if len(letters) < 3 else letters[-3:]
    main = letters[1:3]
    out = [main + digits[0], *[main + x for x in digits[1:]], letters[0] + letters[2] + digits[0],
           letters[0] + letters[1] + digits[0], *[main + str(x) for x in range(10)]]
    return [c for i, c in enumerate(out) if c not in out[:i] and re.fullmatch(r'[A-Z]{2}\d', c)]


def downgrade() -> None:
    raise NotImplementedError("시편번호 v3.0 → v2.3 되돌리기는 지원하지 않습니다. 업그레이드 전 백업으로 복원하세요.")
