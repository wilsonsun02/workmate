-- 011 知识库分享记录表
-- 支持员工之间分享知识库文件，分享粒度为文件级

CREATE TABLE IF NOT EXISTS kb_shares (
    id             VARCHAR(36)   PRIMARY KEY COMMENT '分享记录UUID',
    file_id        VARCHAR(36)   NOT NULL    COMMENT '被分享的文件ID（kb_files.id）',
    owner_username VARCHAR(100)  NOT NULL    COMMENT '分享人（文件所有者）',
    target_username VARCHAR(100) NOT NULL    COMMENT '被分享人',
    category_name  VARCHAR(100)  NOT NULL    COMMENT '文件所属分类名（冗余，便于展示）',
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '分享时间',
    updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_file_target (file_id, target_username),
    INDEX idx_owner (owner_username),
    INDEX idx_target (target_username),
    FOREIGN KEY (file_id) REFERENCES kb_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='知识库分享记录表';
