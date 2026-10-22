"""관리 화면 실측 설정을 DB로 (param_actual_cfg), serial_no 숫자 4자리 검사

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('param_actual_cfg',
    sa.Column('param_key', sa.String(length=40), nullable=False),
    sa.Column('cfg', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('rev', sa.Integer(), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('param_key')
    )
    # 0001에는 없고 검토용 schema_postgres.sql에만 있던 검사 (PostgreSQL 정규식 전용)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("ALTER TABLE specimens ADD CONSTRAINT ck_serial_digits CHECK (serial_no ~ '^[0-9]{4}$')")


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("ALTER TABLE specimens DROP CONSTRAINT ck_serial_digits")
    op.drop_table('param_actual_cfg')
