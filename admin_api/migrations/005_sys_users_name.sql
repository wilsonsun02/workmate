-- Add display name column for employee users and clarify username as the login account.
-- Run once on existing WORKMATE_DB_DATABASE databases before enabling user display names in admin pages.

ALTER TABLE sys_users
    ADD COLUMN IF NOT EXISTS name VARCHAR(100) NULL COMMENT '页面显示名称' AFTER username;

ALTER TABLE sys_users
    MODIFY COLUMN username VARCHAR(50) NOT NULL COMMENT '登录账号';

UPDATE sys_users
SET name = username
WHERE name IS NULL OR TRIM(name) = '';
