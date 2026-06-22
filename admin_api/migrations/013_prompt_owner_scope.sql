-- Prompt owner scope tables upgrade.
-- Each owner maintains independent prompt files:
-- - root: rich.md
-- - dept: department.md
-- - user: identity.md

ALTER TABLE sys_prompt_files
    ADD COLUMN owner_type VARCHAR(32) NOT NULL DEFAULT 'root' AFTER id,
    ADD COLUMN owner_id VARCHAR(64) NOT NULL DEFAULT 'root' AFTER owner_type;

UPDATE sys_prompt_files
SET owner_type = 'root', owner_id = 'root'
WHERE owner_type IS NULL OR owner_type = '' OR owner_id IS NULL OR owner_id = '';

ALTER TABLE sys_prompt_files
    DROP INDEX uniq_prompt_file_name,
    ADD UNIQUE KEY uk_prompt_owner_file (owner_type, owner_id, file_name);

ALTER TABLE sys_prompt_change_logs
    ADD COLUMN owner_type VARCHAR(32) NOT NULL DEFAULT 'root' AFTER id,
    ADD COLUMN owner_id VARCHAR(64) NOT NULL DEFAULT 'root' AFTER owner_type;

UPDATE sys_prompt_change_logs
SET owner_type = 'root', owner_id = 'root'
WHERE owner_type IS NULL OR owner_type = '' OR owner_id IS NULL OR owner_id = '';

ALTER TABLE sys_prompt_change_logs
    ADD INDEX idx_prompt_change_logs_owner_file_created (owner_type, owner_id, file_name, created_at);
