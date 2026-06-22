-- Add current-version metadata for prompt management tables.
-- Run once on existing WORKMATE_DB_DATABASE databases that already executed 002_prompt_management.sql.
-- Current Prompt management only uses sys_prompt_files and sys_prompt_change_logs.

ALTER TABLE sys_prompt_files
    ADD COLUMN version VARCHAR(32) NOT NULL DEFAULT '0.0.1' AFTER target_file;

ALTER TABLE sys_prompt_change_logs
    ADD COLUMN before_version VARCHAR(32) NOT NULL DEFAULT '0.0.1' AFTER source_ip,
    ADD COLUMN after_version VARCHAR(32) NOT NULL DEFAULT '0.0.1' AFTER before_version;

UPDATE sys_prompt_files
SET version = '0.0.1'
WHERE version IS NULL OR version = '';
