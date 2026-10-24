"""시편번호 체계 v3.1 (`시편번호 체계.md`): 각인번호 구간 경계마다 영문·숫자 교대, 시험런 → 분석런(AR-)

각인번호  QV3-102-01-3 → QV3-A02-A-3
  전폭번호 1~9 → 영문 A~(I·O·Q·S·Z 제외), 후절단 01~ → 영문 A~, 분석조각 1~9 그대로(A~Z였던 10번째 이후는 이관 불가)
  탑승 당시 전체번호(run_specimens.display_at)도 같은 규칙으로 바꾸고, 시편마다 NOTE 이력(옛 번호)을 남깁니다.
  v3.0 번호는 실물에 새긴 적이 없어(2026-10-24 확인) 조회 별칭(legacy_id)은 두지 않습니다 — legacy_id는 v2.3 번호 그대로.
분석런 번호  TR-CCT-26001 → AR-CCT-26001 (옛 번호는 검색·주소에서 AR-로 바꿔 찾음)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-24
"""
import re
from datetime import date

from alembic import context, op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

MARK_LETTERS = "ABCDEFGHJKLMNPRTUVWXY"     # app.services.marking.MARK_LETTERS와 같음
SHORT_ID_PG_RE = "^[A-Z]{2}[0-9]-[ABCDEFGHJKLMNPRTUVWXY]([0-9]{2})?(-[ABCDEFGHJKLMNPRTUVWXY](-[1-9])?)?$"
# v3.0 전체번호 안의 각인 부분: 코일-과제-단계-가지[-후절단[-조각]] (꼬리는 그대로)
OLD_FULL = re.compile(r"^(?P<head>[A-Z]{2}\d-[A-Z]\d-[A-E]-)(?P<b>\d(?:\d{2})?)(?:-(?P<c>\d{2})(?:-(?P<p>[1-9A-Z]))?)?(?P<rest>-.*)?$")


def _letter(n: int, what: str) -> str:
    if not 1 <= n <= len(MARK_LETTERS):
        raise RuntimeError(f"{what} {n}번째는 v3.1 범위(1~{len(MARK_LETTERS)})를 넘어 이관할 수 없습니다.")
    return MARK_LETTERS[n - 1]


def _parts(branch: str, cut: str | None, piece: str | None, where: str) -> tuple[str, str | None, str | None]:
    if not branch.isdigit():           # 이미 v3.1
        return branch, cut, piece
    nb = _letter(int(branch[0]), f"{where} 전폭번호") + branch[1:]
    nc = _letter(int(cut), f"{where} 후절단") if cut else None
    if piece and not piece.isdigit():
        raise RuntimeError(f"{where}: 분석조각 '{piece}'(10번째 이후)는 v3.1(1~9)로 이관할 수 없습니다.")
    return nb, nc, piece


def upgrade() -> None:
    if context.is_offline_mode():
        op.execute("-- 데이터 이관(각인번호·분석런 번호)은 온라인 'alembic upgrade head'에서만 실행됩니다. "
                   "기존 시편이 있는 DB는 이 SQL만으로 올리지 마세요.")
    else:
        _migrate_data(op.get_bind())
    if op.get_bind().dialect.name == 'postgresql':     # scripts/dump_ddl.py와 같은 정규식
        op.execute("ALTER TABLE specimens DROP CONSTRAINT IF EXISTS ck_short_id_format")
        op.execute(f"ALTER TABLE specimens ADD CONSTRAINT ck_short_id_format CHECK (short_id ~ '{SHORT_ID_PG_RE}')")


def _migrate_data(bind) -> None:
    specs = sa.table('specimens', sa.column('id'), sa.column('coil_code'), sa.column('branch'), sa.column('cut_no'),
                     sa.column('piece_no'), sa.column('short_id'))
    boards = sa.table('run_specimens', sa.column('test_run_id'), sa.column('specimen_id'), sa.column('display_at'))
    runs = sa.table('test_runs', sa.column('id'), sa.column('test_run_no'))
    events = sa.table('specimen_events', sa.column('specimen_id'), sa.column('event_type'),
                      sa.column('params', sa.JSON), sa.column('event_date'))
    today = date.today()

    # 1. 각인번호 — 옛 값은 모두 숫자 가지라 새 값(영문 가지)과 겹치지 않아 한 줄씩 바꿔도 UNIQUE 충돌이 없음
    for s in bind.execute(sa.select(specs)).mappings().all():
        b, c, p = _parts(s['branch'], s['cut_no'], s['piece_no'], s['short_id'])
        if (b, c, p) == (s['branch'], s['cut_no'], s['piece_no']):
            continue
        mark = '-'.join(x for x in (s['coil_code'], b, c, p) if x)
        bind.execute(specs.update().where(specs.c.id == s['id']).values(branch=b, cut_no=c, piece_no=p, short_id=mark))
        bind.execute(events.insert().values(specimen_id=s['id'], event_type='NOTE', event_date=today,
                                            params={'migrated': 'v3.0 → v3.1', 'old_id': s['short_id']}))

    # 2. 탑승 당시 전체번호
    for r in bind.execute(sa.select(boards).where(boards.c.display_at.is_not(None))).mappings().all():
        m = OLD_FULL.match(r['display_at'])
        if not m:
            continue
        b, c, p = _parts(m['b'], m['c'], m['p'], r['display_at'])
        new = m['head'] + '-'.join(x for x in (b, c, p) if x) + (m['rest'] or '')
        bind.execute(boards.update().where(boards.c.test_run_id == r['test_run_id'],
                                           boards.c.specimen_id == r['specimen_id']).values(display_at=new))

    # 3. 분석런 번호 TR- → AR-
    for r in bind.execute(sa.select(runs).where(runs.c.test_run_no.like('TR-%'))).mappings().all():
        bind.execute(runs.update().where(runs.c.id == r['id']).values(test_run_no='AR-' + r['test_run_no'][3:]))


def downgrade() -> None:
    raise NotImplementedError("시편번호 v3.1 → v3.0 되돌리기는 지원하지 않습니다. 업그레이드 전 백업으로 복원하세요.")
