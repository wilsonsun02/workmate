-- 008 公司知识库支持：kb_categories / kb_files 增加 kb_type 字段
-- 公司知识库通过 kb_type='company' 区分，username 统一使用 '__company__'

ALTER TABLE kb_categories
  ADD COLUMN kb_type VARCHAR(20) NOT NULL DEFAULT 'personal'
  COMMENT '知识库类型：personal-个人, company-公司'
  AFTER username;

ALTER TABLE kb_categories
  DROP INDEX uk_user_category,
  ADD UNIQUE KEY uk_user_type_category (username, kb_type, name);

ALTER TABLE kb_files
  ADD COLUMN kb_type VARCHAR(20) NOT NULL DEFAULT 'personal'
  COMMENT '知识库类型：personal-个人, company-公司'
  AFTER username;

ALTER TABLE kb_files
  DROP INDEX idx_user_category,
  ADD INDEX idx_user_type_category (username, kb_type, category_name);
