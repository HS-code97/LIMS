-- 도금강판 R&D LIMS v2.3 (시편번호 v3.2) — PostgreSQL 15+ DDL (app/models에서 자동 생성, 직접 고치지 마세요)
-- 운영 적용은 Alembic(alembic upgrade head)을 쓰고, 이 파일은 검토·대조용입니다.

CREATE TABLE master_codes (
	category VARCHAR(20) NOT NULL, 
	code VARCHAR(4) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	spec JSONB, 
	description TEXT, 
	is_active BOOLEAN NOT NULL, 
	PRIMARY KEY (category, code)
);

CREATE TABLE materials (
	id SERIAL NOT NULL, 
	coil_no VARCHAR(50) NOT NULL, 
	coil_code VARCHAR(3), 
	steel_grade VARCHAR(50), 
	thickness_mm NUMERIC, 
	composition JSONB, 
	received_date DATE, 
	note TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (coil_no), 
	UNIQUE (coil_code)
);

CREATE TABLE teams (
	id SERIAL NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE test_templates (
	id SERIAL NOT NULL, 
	code VARCHAR(30) NOT NULL, 
	version INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	test_type VARCHAR(20) NOT NULL, 
	field_schema JSONB NOT NULL, 
	condition_schema JSONB, 
	default_cycles INTEGER, 
	default_interval_days INTEGER, 
	team_id INTEGER, 
	is_active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code, version), 
	FOREIGN KEY(team_id) REFERENCES teams (id)
);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	emp_no VARCHAR(20) NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	team_id INTEGER, 
	role VARCHAR(10) NOT NULL, 
	pw_hash TEXT NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (emp_no), 
	FOREIGN KEY(team_id) REFERENCES teams (id)
);

CREATE TABLE api_keys (
	id SERIAL NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	prefix VARCHAR(12) NOT NULL, 
	key_hash VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	scopes JSONB NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	last_used_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (key_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE TABLE audit_log (
	id BIGSERIAL NOT NULL, 
	table_name VARCHAR(40) NOT NULL, 
	row_id BIGINT NOT NULL, 
	action VARCHAR(10) NOT NULL, 
	before JSONB, 
	after JSONB, 
	user_id INTEGER, 
	at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE bath_analyses (
	id SERIAL NOT NULL, 
	pot VARCHAR(20) NOT NULL, 
	sampled_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	method VARCHAR(20), 
	composition JSONB NOT NULL, 
	user_id INTEGER, 
	note TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE param_actual_cfg (
	param_key VARCHAR(40) NOT NULL, 
	cfg JSONB, 
	rev INTEGER NOT NULL, 
	updated_by INTEGER, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (param_key), 
	FOREIGN KEY(updated_by) REFERENCES users (id)
);

CREATE TABLE process_presets (
	id SERIAL NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	scope VARCHAR(10) NOT NULL, 
	owner_id INTEGER, 
	team_id INTEGER, 
	coating_system VARCHAR(1) NOT NULL, 
	bath_code VARCHAR(1) NOT NULL, 
	overrides JSONB NOT NULL, 
	dict_version VARCHAR(20) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	variant_seq INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id)
);

CREATE TABLE projects (
	project_code VARCHAR(4) NOT NULL, 
	company_project_no VARCHAR(20), 
	project_name VARCHAR(150) NOT NULL, 
	manager_id INTEGER, 
	is_common BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (project_code), 
	FOREIGN KEY(manager_id) REFERENCES users (id)
);

CREATE TABLE test_runs (
	id BIGSERIAL NOT NULL, 
	test_run_no VARCHAR(20) NOT NULL, 
	test_type VARCHAR(20) NOT NULL, 
	template_id INTEGER NOT NULL, 
	equipment VARCHAR(50), 
	conditions JSONB, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	owner_id INTEGER, 
	status VARCHAR(10) NOT NULL, 
	cycles INTEGER, 
	note TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (test_run_no), 
	FOREIGN KEY(template_id) REFERENCES test_templates (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
);

CREATE TABLE process_runs (
	id BIGSERIAL NOT NULL, 
	run_no VARCHAR(20) NOT NULL, 
	run_date DATE NOT NULL, 
	operator_id INTEGER, 
	project_code VARCHAR(4), 
	material_id INTEGER, 
	preset_id INTEGER, 
	source VARCHAR(10) NOT NULL, 
	dict_version VARCHAR(20) NOT NULL, 
	recipe JSONB NOT NULL, 
	changed_from_preset JSONB, 
	coating_weight_target NUMERIC, 
	base_condition_code VARCHAR(5) NOT NULL, 
	pv_log_path TEXT, 
	note TEXT, 
	warnings JSONB, 
	coating_system VARCHAR(1), 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_no), 
	FOREIGN KEY(operator_id) REFERENCES users (id), 
	FOREIGN KEY(project_code) REFERENCES projects (project_code), 
	FOREIGN KEY(material_id) REFERENCES materials (id), 
	FOREIGN KEY(preset_id) REFERENCES process_presets (id)
);
CREATE INDEX idx_pr_recipe ON process_runs USING gin (recipe);

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
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (family, seq), 
	FOREIGN KEY(preset_id) REFERENCES process_presets (id), 
	FOREIGN KEY(first_run_id) REFERENCES process_runs (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);
CREATE INDEX idx_pv_fp ON process_variants (family, fingerprint);

CREATE TABLE specimens (
	id BIGSERIAL NOT NULL, 
	project_code VARCHAR(4) NOT NULL, 
	stage VARCHAR(1) NOT NULL, 
	coil_code VARCHAR(3) NOT NULL, 
	branch VARCHAR(3) NOT NULL, 
	cut_no VARCHAR(2), 
	piece_no VARCHAR(1), 
	short_id VARCHAR(16) NOT NULL, 
	coil_position VARCHAR(2), 
	steps JSONB, 
	is_panel BOOLEAN NOT NULL, 
	legacy_id VARCHAR(20), 
	parent_id BIGINT, 
	process_run_id BIGINT, 
	material_id INTEGER, 
	owner_id INTEGER, 
	target_overrides JSONB, 
	condition_code VARCHAR(5), 
	variant_seq INTEGER, 
	sample_position VARCHAR(10), 
	rolling_direction VARCHAR(5), 
	surface_side VARCHAR(10), 
	size_text VARCHAR(30), 
	status VARCHAR(12) NOT NULL, 
	storage_location VARCHAR(100), 
	note TEXT, 
	is_deleted BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_stage CHECK (stage IN ('A','B','C','D','E')), 
	CONSTRAINT ck_coil_code_len CHECK (length(coil_code) = 3), 
	CONSTRAINT ck_branch_len CHECK (length(branch) IN (1, 3)), 
	FOREIGN KEY(project_code) REFERENCES projects (project_code), 
	UNIQUE (short_id), 
	FOREIGN KEY(parent_id) REFERENCES specimens (id) ON DELETE RESTRICT, 
	FOREIGN KEY(process_run_id) REFERENCES process_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(material_id) REFERENCES materials (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
);
CREATE INDEX idx_spec_coil ON specimens (coil_code);
CREATE INDEX idx_spec_owner ON specimens (owner_id);
CREATE INDEX idx_spec_parent ON specimens (parent_id);
CREATE INDEX idx_spec_run ON specimens (process_run_id);
CREATE INDEX ix_specimens_legacy_id ON specimens (legacy_id);

CREATE TABLE effective_params (
	specimen_id BIGINT NOT NULL, 
	param_key VARCHAR(40) NOT NULL, 
	target NUMERIC, 
	actual NUMERIC, 
	effective NUMERIC NOT NULL, 
	source VARCHAR(10) NOT NULL, 
	level VARCHAR(6) NOT NULL, 
	inherited_from VARCHAR(10), 
	deviation NUMERIC, 
	out_of_tol BOOLEAN NOT NULL, 
	PRIMARY KEY (specimen_id, param_key), 
	FOREIGN KEY(specimen_id) REFERENCES specimens (id)
);
CREATE INDEX idx_eff_key_tgt ON effective_params (param_key, target);
CREATE INDEX idx_eff_key_val ON effective_params (param_key, effective);

CREATE TABLE run_specimens (
	test_run_id BIGINT NOT NULL, 
	specimen_id BIGINT NOT NULL, 
	slot VARCHAR(20), 
	loaded_at DATE, 
	unloaded_at DATE, 
	display_at VARCHAR(60), 
	PRIMARY KEY (test_run_id, specimen_id), 
	FOREIGN KEY(test_run_id) REFERENCES test_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(specimen_id) REFERENCES specimens (id) ON DELETE RESTRICT
);

CREATE TABLE specimen_events (
	id BIGSERIAL NOT NULL, 
	specimen_id BIGINT NOT NULL, 
	event_type VARCHAR(20) NOT NULL, 
	params JSONB, 
	event_date DATE NOT NULL, 
	user_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(specimen_id) REFERENCES specimens (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE test_results (
	id BIGSERIAL NOT NULL, 
	test_run_id BIGINT NOT NULL, 
	specimen_id BIGINT NOT NULL, 
	cycle_no INTEGER NOT NULL, 
	eval_date DATE, 
	inspector_id INTEGER, 
	template_id INTEGER NOT NULL, 
	metrics JSONB, 
	is_deleted BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (test_run_id, specimen_id, cycle_no), 
	FOREIGN KEY(test_run_id) REFERENCES test_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(specimen_id) REFERENCES specimens (id) ON DELETE RESTRICT, 
	FOREIGN KEY(inspector_id) REFERENCES users (id), 
	FOREIGN KEY(template_id) REFERENCES test_templates (id)
);
CREATE INDEX idx_res_metrics ON test_results USING gin (metrics);
CREATE INDEX idx_res_spec ON test_results (specimen_id);

CREATE TABLE attachments (
	id BIGSERIAL NOT NULL, 
	specimen_id BIGINT, 
	result_id BIGINT, 
	process_run_id BIGINT, 
	kind VARCHAR(10), 
	path TEXT NOT NULL, 
	thumb_path TEXT, 
	original_name TEXT NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	size_bytes BIGINT, 
	source VARCHAR(10) NOT NULL, 
	uploaded_by INTEGER, 
	uploaded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	is_deleted BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(specimen_id) REFERENCES specimens (id), 
	FOREIGN KEY(result_id) REFERENCES test_results (id), 
	FOREIGN KEY(process_run_id) REFERENCES process_runs (id), 
	UNIQUE (sha256), 
	FOREIGN KEY(uploaded_by) REFERENCES users (id)
);
CREATE INDEX idx_att_spec ON attachments (specimen_id);
CREATE INDEX idx_att_unmatched ON attachments (uploaded_by) WHERE specimen_id IS NULL;

CREATE TABLE param_actuals (
	id BIGSERIAL NOT NULL, 
	process_run_id BIGINT NOT NULL, 
	specimen_id BIGINT, 
	param_key VARCHAR(40) NOT NULL, 
	value NUMERIC, 
	value_text VARCHAR(50), 
	stats JSONB, 
	source VARCHAR(10) NOT NULL, 
	method VARCHAR(30), 
	ref_result_id BIGINT, 
	ref_analysis_id INTEGER, 
	measured_at TIMESTAMP WITHOUT TIME ZONE, 
	user_id INTEGER, 
	note TEXT, 
	is_deleted BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(process_run_id) REFERENCES process_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(specimen_id) REFERENCES specimens (id) ON DELETE RESTRICT, 
	FOREIGN KEY(ref_result_id) REFERENCES test_results (id), 
	FOREIGN KEY(ref_analysis_id) REFERENCES bath_analyses (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX idx_act_run_key ON param_actuals (process_run_id, param_key) WHERE NOT is_deleted;
CREATE INDEX idx_act_spec_key ON param_actuals (specimen_id, param_key) WHERE NOT is_deleted;

-- 각인번호 형식 (PostgreSQL 전용 정규식 검사, 시편번호 체계 3.2절)
ALTER TABLE specimens ADD CONSTRAINT ck_short_id_format CHECK (short_id ~ '^[A-Z]{2}[0-9]-[ABCDEFGHJKLMNPRTUVWXY]([0-9]{2})?(-[ABCDEFGHJKLMNPRTUVWXY](-[1-9])?)?$');
