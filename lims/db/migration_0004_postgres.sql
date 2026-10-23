BEGIN;

-- Running upgrade 0003 -> 0004

ALTER TABLE materials ADD COLUMN coil_code VARCHAR(3);

ALTER TABLE materials ADD CONSTRAINT uq_materials_coil_code UNIQUE (coil_code);

ALTER TABLE run_specimens ADD COLUMN display_at VARCHAR(60);

ALTER TABLE specimens ADD COLUMN coil_code VARCHAR(3);

ALTER TABLE specimens ADD COLUMN branch VARCHAR(3);

ALTER TABLE specimens ADD COLUMN cut_no VARCHAR(2);

ALTER TABLE specimens ADD COLUMN piece_no VARCHAR(1);

ALTER TABLE specimens ADD COLUMN mark VARCHAR(16);

ALTER TABLE specimens ADD COLUMN coil_position VARCHAR(2);

ALTER TABLE specimens ADD COLUMN steps JSONB;

ALTER TABLE specimens ADD COLUMN is_panel BOOLEAN;

ALTER TABLE specimens ADD COLUMN legacy_id VARCHAR(20);

ALTER TABLE specimens ADD COLUMN stage_new VARCHAR(1);

-- 데이터 이관(과제코드·코일코드·각인번호)은 온라인 'alembic upgrade head'에서만 실행됩니다. 기존 시편이 있는 DB는 이 SQL만으로 올리지 마세요.;

ALTER TABLE specimens DROP CONSTRAINT IF EXISTS ck_serial_digits;

ALTER TABLE specimens DROP CONSTRAINT uq_short;

ALTER TABLE specimens DROP CONSTRAINT ck_stage;

ALTER TABLE specimens DROP CONSTRAINT ck_serial_len;

ALTER TABLE specimens DROP COLUMN short_id;

ALTER TABLE specimens DROP COLUMN serial_no;

ALTER TABLE specimens DROP COLUMN engraved_label;

UPDATE specimens SET stage = stage_new WHERE stage_new IS NOT NULL;

ALTER TABLE specimens DROP COLUMN stage_new;

ALTER TABLE specimens ALTER COLUMN mark SET NOT NULL;

ALTER TABLE specimens RENAME mark TO short_id;

ALTER TABLE specimens ALTER COLUMN coil_code SET NOT NULL;

ALTER TABLE specimens ALTER COLUMN branch SET NOT NULL;

ALTER TABLE specimens ALTER COLUMN is_panel SET NOT NULL;

ALTER TABLE specimens ADD CONSTRAINT uq_specimens_short_id UNIQUE (short_id);

ALTER TABLE specimens ADD CONSTRAINT ck_stage CHECK (stage IN ('A','B','C','D','E'));

ALTER TABLE specimens ADD CONSTRAINT ck_coil_code_len CHECK (length(coil_code) = 3);

ALTER TABLE specimens ADD CONSTRAINT ck_branch_len CHECK (length(branch) IN (1, 3));

CREATE INDEX idx_spec_coil ON specimens (coil_code);

CREATE INDEX ix_specimens_legacy_id ON specimens (legacy_id);

ALTER TABLE specimens ADD CONSTRAINT ck_short_id_format CHECK (short_id ~ '^[A-Z]{2}[0-9]-[0-9]([0-9]{2})?(-[0-9]{2}(-[1-9A-Z])?)?$');

UPDATE alembic_version SET version_num='0004' WHERE alembic_version.version_num = '0003';

COMMIT;

