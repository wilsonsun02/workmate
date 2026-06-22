ALTER TABLE sys_users
  ADD COLUMN title VARCHAR(100) NULL COMMENT '职位' AFTER name,
  ADD COLUMN is_special TINYINT DEFAULT 0 COMMENT '是否特殊员工' AFTER status,
  ADD COLUMN special_type VARCHAR(50) NULL COMMENT '特殊员工类型' AFTER is_special,
  ADD COLUMN external_agent_base_url VARCHAR(255) NULL COMMENT '外部Agent地址' AFTER special_type,
  ADD COLUMN external_agent_token TEXT NULL COMMENT '外部Agent Token(加密存储)' AFTER external_agent_base_url;

CREATE INDEX idx_users_title ON sys_users (title);

CREATE TABLE IF NOT EXISTS user_preferences (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id VARCHAR(36) NOT NULL,
  pref_key VARCHAR(100) NOT NULL,
  pref_value TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_pref (user_id, pref_key),
  KEY idx_user_pref_user (user_id)
);

