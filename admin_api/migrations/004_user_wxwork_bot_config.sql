-- Add user-level WeCom bot config columns.
-- Run once on existing WORKMATE_DB_DATABASE databases before enabling per-user bot configuration.

ALTER TABLE sys_users
    ADD COLUMN wxwork_bot_name VARCHAR(100) NULL COMMENT '企业微信机器人名称' AFTER wechat_work_id,
    ADD COLUMN wxwork_bot_id TEXT NULL COMMENT '企业微信机器人ID(加密存储)' AFTER wxwork_bot_name,
    ADD COLUMN wxwork_secret TEXT NULL COMMENT '企业微信机器人密钥(加密存储)' AFTER wxwork_bot_id;
