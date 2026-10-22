BEGIN;

-- Running upgrade 0002 -> 0003

CREATE TABLE api_keys (
    id SERIAL NOT NULL, 
    name VARCHAR(50) NOT NULL, 
    prefix VARCHAR(12) NOT NULL, 
    key_hash VARCHAR(64) NOT NULL, 
    user_id INTEGER NOT NULL, 
    scopes JSONB NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_by INTEGER, 
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    last_used_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (key_hash)
);

UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002';

COMMIT;

