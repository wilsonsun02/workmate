-- 010: 安全拦截日志表 - 数据库迁移
-- 记录桌面端安全拦截事件（关键词扫描/LLM审查拦截），供管理端安全合规页面展示

CREATE TABLE IF NOT EXISTS security_intercept_log (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(100)  NOT NULL DEFAULT ''  COMMENT '操作用户（桌面端登录用户名）',
    channel         VARCHAR(50)   NOT NULL DEFAULT ''  COMMENT '拦截渠道: wechat / wxwork / unknown',
    intercept_type  VARCHAR(50)   NOT NULL DEFAULT ''  COMMENT '拦截类型: keyword / llm_review',
    tool_name       VARCHAR(200)  NOT NULL DEFAULT ''  COMMENT '触发的工具名',
    violations      TEXT          NULL                  COMMENT '违规项列表（JSON数组）',
    raw_content     TEXT          NULL                  COMMENT '原始内容（脱敏后截取前500字）',
    block_message   TEXT          NULL                  COMMENT '拦截提示消息',
    mate_name       VARCHAR(100)  NOT NULL DEFAULT ''  COMMENT '工作伙伴名称',
    created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_channel (channel),
    INDEX idx_created_at (created_at),
    INDEX idx_intercept_type (intercept_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='安全拦截日志表';
