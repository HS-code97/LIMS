BEGIN;

-- Running upgrade 0004 -> 0005

-- 데이터 이관(각인번호·분석런 번호)은 온라인 'alembic upgrade head'에서만 실행됩니다. 기존 시편이 있는 DB는 이 SQL만으로 올리지 마세요.;

ALTER TABLE specimens DROP CONSTRAINT IF EXISTS ck_short_id_format;

ALTER TABLE specimens ADD CONSTRAINT ck_short_id_format CHECK (short_id ~ '^[A-Z]{2}[0-9]-[ABCDEFGHJKLMNPRTUVWXY]([0-9]{2})?(-[ABCDEFGHJKLMNPRTUVWXY](-[1-9])?)?$');

UPDATE alembic_version SET version_num='0005' WHERE alembic_version.version_num = '0004';

COMMIT;

