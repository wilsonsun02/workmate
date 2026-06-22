ALTER TABLE sys_users
    ADD COLUMN IF NOT EXISTS deleted_at DATETIME NULL COMMENT '软删除时间，NULL表示未删除' AFTER external_agent_token;

CREATE INDEX idx_users_deleted_at ON sys_users (deleted_at);
