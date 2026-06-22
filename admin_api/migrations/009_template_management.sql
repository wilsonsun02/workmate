-- 009: 模板管理系统 - 数据库迁移
-- 创建模板分类表和模板表，支持报告/图片/视频三类模板的动态管理

CREATE TABLE IF NOT EXISTS tpl_categories (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    category_key  VARCHAR(50)  NOT NULL UNIQUE  COMMENT '分类标识: report / image / video',
    category_name VARCHAR(100) NOT NULL          COMMENT '分类名称: 报告模板 / 图片模板 / 视频模板',
    description   VARCHAR(500) NULL              COMMENT '分类描述',
    sort_order    INT          NOT NULL DEFAULT 0 COMMENT '排序权重',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='模板分类表';

CREATE TABLE IF NOT EXISTS tpl_templates (
    id            VARCHAR(36)  PRIMARY KEY           COMMENT 'UUID主键',
    category_id   INT          NOT NULL             COMMENT '分类ID',
    template_key  VARCHAR(100) NOT NULL UNIQUE       COMMENT '模板唯一标识(如: report-jiaoyi-zhongxin)',
    template_name VARCHAR(200) NOT NULL              COMMENT '模板名称(如: 广西铝产品仓储交易中心模板)',
    template_type VARCHAR(50)  NOT NULL DEFAULT ''   COMMENT '兼容旧type编号(如: 0,1,2)',
    description   VARCHAR(500) NULL                  COMMENT '模板描述',
    cover_url     VARCHAR(2000) NULL                 COMMENT '模板封面图URL',

    file_url      VARCHAR(2000) NULL                 COMMENT '模板文件存储路径(OSS object_key或本地相对路径)',
    file_name     VARCHAR(500)  NULL                 COMMENT '原始文件名',
    file_size     BIGINT        NOT NULL DEFAULT 0   COMMENT '文件大小(字节)',
    file_type     VARCHAR(20)   NOT NULL DEFAULT ''  COMMENT '文件类型: docx/png/mp4等',

    style_config  LONGTEXT      NULL                 COMMENT '样式配置JSON(仅报告模板, 含DOCX_STYLE/TABLE_STYLE/IMG_STYLE)',

    version       INT           NOT NULL DEFAULT 1   COMMENT '模板版本号，每次更新+1',
    is_active     TINYINT       NOT NULL DEFAULT 1   COMMENT '是否启用: 1=启用, 0=禁用',
    sort_order    INT           NOT NULL DEFAULT 0   COMMENT '排序权重',
    created_by    VARCHAR(100)  NOT NULL DEFAULT ''  COMMENT '创建人',
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at    DATETIME      NULL                  COMMENT '软删除时间，NULL表示未删除',

    INDEX idx_category (category_id),
    INDEX idx_template_key (template_key),
    INDEX idx_template_type (template_type),
    INDEX idx_active (is_active),
    INDEX idx_deleted (deleted_at),
    FOREIGN KEY (category_id) REFERENCES tpl_categories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='模板表';

-- 预置分类数据
INSERT IGNORE INTO tpl_categories (category_key, category_name, description, sort_order) VALUES
('report', '报告模板', 'Word/PDF 报告文档模板，包含 .docx 模板文件和样式配置', 1),
('image',  '图片模板', 'PPT/宣传图等图片生成模板，包含 .png 模板图片', 2),
('video',  '视频模板', '数字人视频生成模板，包含主播形象图片', 3);
