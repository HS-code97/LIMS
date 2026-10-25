BEGIN;

-- Running upgrade 0005 -> 0006

CREATE TABLE process_variants (
    id SERIAL NOT NULL, 
    family VARCHAR(2) NOT NULL, 
    seq INTEGER NOT NULL, 
    fingerprint VARCHAR(40) NOT NULL, 
    proc_values JSONB NOT NULL, 
    cw_claims JSONB, 
    name VARCHAR(120) NOT NULL, 
    origin VARCHAR(10) NOT NULL, 
    preset_id INTEGER, 
    first_run_id BIGINT, 
    created_by INTEGER, 
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    FOREIGN KEY(first_run_id) REFERENCES process_runs (id), 
    FOREIGN KEY(preset_id) REFERENCES process_presets (id), 
    UNIQUE (family, seq)
);

CREATE INDEX idx_pv_fp ON process_variants (family, fingerprint);

ALTER TABLE specimens ADD COLUMN variant_seq INTEGER;

ALTER TABLE process_presets ADD COLUMN variant_seq INTEGER;

-- 변형번호 백필은 온라인 'alembic upgrade head'에서만 실행됩니다.;

UPDATE alembic_version SET version_num='0006' WHERE alembic_version.version_num = '0005';

COMMIT;

