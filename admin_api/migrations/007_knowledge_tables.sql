-- 007 知识库表（kb_categories + kb_files）
-- 将知识库数据从本地文件系统（index.json + .md文件）迁移到 MySQL 数据库存储

CREATE TABLE IF NOT EXISTS kb_categories (
    id           VARCHAR(36)   PRIMARY KEY COMMENT '分类UUID',
    username     VARCHAR(100)  NOT NULL    COMMENT '所属用户（AGENT_USERNAME）',
    name         VARCHAR(100)  NOT NULL    COMMENT '分类安全名称（原目录名）',
    display_name VARCHAR(200)  NOT NULL    COMMENT '分类显示名称',
    created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_user_category (username, name),
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='知识库分类表';

CREATE TABLE IF NOT EXISTS kb_files (
    id                VARCHAR(36)   PRIMARY KEY COMMENT '文件UUID',
    username          VARCHAR(100)  NOT NULL    COMMENT '所属用户（AGENT_USERNAME）',
    category_id       VARCHAR(36)   NOT NULL    COMMENT '所属分类ID',
    category_name     VARCHAR(100)  NOT NULL    COMMENT '所属分类安全名称（冗余，便于查询）',
    original_filename VARCHAR(500)  NOT NULL    COMMENT '原始文件名',
    md_filename       VARCHAR(500)  NOT NULL    COMMENT 'Markdown文件名',
    file_type         VARCHAR(20)   NOT NULL    COMMENT '文件类型（docx/pdf/url等）',
    file_size         BIGINT        NOT NULL DEFAULT 0 COMMENT '文件大小（字节）',
    summary           LONGTEXT      NULL        COMMENT 'LLM生成的结构化摘要',
    md_content        LONGTEXT      NOT NULL    COMMENT 'Markdown正文内容（原.md文件内容）',
    source_url        VARCHAR(2000) NULL        COMMENT 'URL来源（仅url类型文件）',
    created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    INDEX idx_username (username),
    INDEX idx_user_category (username, category_name),
    FOREIGN KEY (category_id) REFERENCES kb_categories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='知识库文件表';
