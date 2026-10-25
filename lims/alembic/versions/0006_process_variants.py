"""공정 계열·변형번호 (시편번호 체계 3.3절·D-23 ~ D-26, 설계서 D-50·D-51): 꼬리 M206K → M206K03

조건부 5자는 코드표 기준 분류라 허용오차 안의 차이(DP −42/−40)나 코드에 없는 값(욕온·나이프 압력)을 가르지 못하고,
코드표에 없는 욕은 모두 X로 묶였습니다. 공정 계열(조건부 앞 2자 'M2') 안에서 부착량을 뺀 목표 공정값의 지문마다
번호(조건 카드)를 줍니다. 00 = 공용 표준 프리셋 그대로(꼬리에 안 씀).

이관: 프리셋(공용 먼저, id 순) → 공정런(run_date·run_no 순)의 시편에 번호를 매깁니다. 조건부 5자는 저장된 값을
그대로 쓰고 다시 계산하지 않습니다. 지문·카드 이름은 앱 함수(condition_code.process_values 등, DB를 쓰지 않는
순수 함수)를 쓰고, 표 읽기·쓰기는 이 파일의 Core 문으로 합니다(이후 모델이 바뀌어도 이 이관은 그대로 돌게).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 개발 SQLite는 앱 시작 때 create_all이 새 표(빈 process_variants)를 먼저 만들 수 있어, 있는 것은 건너뜁니다.
    # (create_all은 기존 표에 열을 더하지 않으므로 variant_seq 열은 여기서 붙습니다.)
    insp = sa.inspect(op.get_bind()) if not context.is_offline_mode() else None
    has_table = insp is not None and insp.has_table('process_variants')
    cols = {t: {c['name'] for c in insp.get_columns(t)} for t in ('specimens', 'process_presets')} if insp else {}
    if not has_table:
        _create_table()
    if not (insp and any(i['name'] == 'idx_pv_fp' for i in insp.get_indexes('process_variants'))):
        op.create_index('idx_pv_fp', 'process_variants', ['family', 'fingerprint'])
    for t in ('specimens', 'process_presets'):
        if 'variant_seq' not in cols.get(t, set()):
            with op.batch_alter_table(t) as b:
                b.add_column(sa.Column('variant_seq', sa.Integer(), nullable=True))
    if context.is_offline_mode():
        op.execute("-- 변형번호 백필은 온라인 'alembic upgrade head'에서만 실행됩니다.")
    else:
        _backfill(op.get_bind())


def _create_table() -> None:
    op.create_table(
        'process_variants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('family', sa.String(length=2), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('fingerprint', sa.String(length=40), nullable=False),
        sa.Column('proc_values', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('cw_claims', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('origin', sa.String(length=10), nullable=False),
        sa.Column('preset_id', sa.Integer(), nullable=True),
        sa.Column('first_run_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['first_run_id'], ['process_runs.id']),
        sa.ForeignKeyConstraint(['preset_id'], ['process_presets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('family', 'seq'),
    )


def _backfill(bind) -> None:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.services import condition_code as cc
    from app.services import param_dict as pdict

    pv = sa.table('process_variants', sa.column('id'), sa.column('family'), sa.column('seq'), sa.column('fingerprint'),
                  sa.column('proc_values', sa.JSON), sa.column('cw_claims', sa.JSON), sa.column('name'),
                  sa.column('origin'), sa.column('preset_id'), sa.column('first_run_id'))
    presets = sa.table('process_presets', sa.column('id'), sa.column('name'), sa.column('scope'),
                       sa.column('coating_system'), sa.column('bath_code'), sa.column('overrides', sa.JSON),
                       sa.column('variant_seq'))
    runs = sa.table('process_runs', sa.column('id'), sa.column('run_no'), sa.column('run_date'),
                    sa.column('recipe', sa.JSON), sa.column('preset_id'))
    specs = sa.table('specimens', sa.column('id'), sa.column('parent_id'), sa.column('process_run_id'),
                     sa.column('is_panel'), sa.column('target_overrides', sa.JSON), sa.column('condition_code'),
                     sa.column('variant_seq'))
    bind.execute(pv.delete())                  # create_all이 만든 빈 표거나, 처음부터 다시 매김
    cards: dict[str, list[dict]] = {}          # family → [{family, seq, fp, values, claims}]

    def find(family, fp, cw_code=None, cw=None):
        for c in sorted(cards.get(family, []), key=lambda c: c['seq']):
            have = c['claims'].get(cw_code) if cw_code else None
            if c['fp'] == fp and (have is None or cw is None or cc._norm(have) == cc._norm(cw)):
                return c
        return None

    def add(family, seq, fp, vals, name, origin, preset_id=None, run_id=None):
        bind.execute(pv.insert().values(family=family, seq=seq, fingerprint=fp, proc_values=vals, cw_claims={},
                                            name=name[:120], origin=origin, preset_id=preset_id, first_run_id=run_id))
        c = {'family': family, 'seq': seq, 'fp': fp, 'values': vals, 'claims': {}}
        cards.setdefault(family, []).append(c)
        return c

    def next_seq(family):
        return max([c['seq'] for c in cards.get(family, [])] + [0]) + 1

    def std_values(family):
        return next((c['values'] for c in cards.get(family, []) if c['seq'] == 0), None)

    # 1. 프리셋: 공용을 먼저 (계열의 첫 공용 프리셋 = 표준 00)
    preset_vals = {}
    rows = bind.execute(sa.select(presets)).mappings().all()
    for p in sorted(rows, key=lambda p: (p['scope'] != 'PUBLIC', p['id'])):
        family = f"{p['coating_system']}{p['bath_code']}"
        vals = cc.process_values(pdict.preset_recipe(p['overrides']))
        preset_vals[p['id']] = vals
        fp = cc.fingerprint(vals)
        c = find(family, fp)
        if c is None:
            std = p['scope'] == 'PUBLIC' and std_values(family) is None
            c = add(family, 0 if std else next_seq(family), fp, vals, p['name'], p['scope'], preset_id=p['id'])
        bind.execute(presets.update().where(presets.c.id == p['id']).values(variant_seq=c['seq']))

    # 2. 공정런 순서대로 시편(원판·자른 실험편): 목표 = 공정런 레시피 + 원판 target_overrides
    allspecs = {s['id']: s for s in bind.execute(sa.select(specs)).mappings().all()}

    def panel_of(s):
        while s is not None and not s['is_panel']:
            s = allspecs.get(s['parent_id'])
        return s

    for run in bind.execute(sa.select(runs).order_by(runs.c.run_date, runs.c.run_no)).mappings().all():
        base = preset_vals.get(run['preset_id'])
        for s in sorted((s for s in allspecs.values() if s['process_run_id'] == run['id'] and s['condition_code']),
                        key=lambda s: s['id']):
            panel = panel_of(s)
            target = pdict.merge(run['recipe'], panel['target_overrides'] if panel else None)
            code = s['condition_code']
            family, vals = code[:2], cc.process_values(target)
            fp, cw, cw_code = cc.fingerprint(vals), pdict.get(target, 'out.cw'), code[2:4]
            c = find(family, fp, cw_code, cw)
            if c is None:
                c = add(family, next_seq(family), fp, vals, cc.describe_changes(vals, std_values(family) or base),
                        'RUN', run_id=run['id'])
            if cw is not None and cw_code not in c['claims']:
                c['claims'][cw_code] = cc._norm(cw)
                bind.execute(pv.update().where(pv.c.family == family, pv.c.seq == c['seq'])
                             .values(cw_claims=dict(c['claims'])))
            bind.execute(specs.update().where(specs.c.id == s['id']).values(variant_seq=c['seq']))


def downgrade() -> None:
    with op.batch_alter_table('process_presets') as b:
        b.drop_column('variant_seq')
    with op.batch_alter_table('specimens') as b:
        b.drop_column('variant_seq')
    op.drop_index('idx_pv_fp', table_name='process_variants')
    op.drop_table('process_variants')
