BEGIN;

-- Running upgrade 0001 -> 0002

CREATE TABLE param_actual_cfg (
    param_key VARCHAR(40) NOT NULL, 
    cfg JSONB, 
    rev INTEGER NOT NULL, 
    updated_by INTEGER, 
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    PRIMARY KEY (param_key), 
    FOREIGN KEY(updated_by) REFERENCES users (id)
);

ALTER TABLE specimens ADD CONSTRAINT ck_serial_digits CHECK (serial_no ~ '^[0-9]{4}$');

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

COMMIT;

