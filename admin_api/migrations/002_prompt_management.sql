-- Prompt management tables (Admin MySQL).
-- Run once against WORKMATE_DB_DATABASE before using prompt admin management.

CREATE TABLE IF NOT EXISTS sys_prompt_files (
    id VARCHAR(64) NOT NULL,
    file_name VARCHAR(191) NOT NULL,
    target_file VARCHAR(512) NOT NULL,
    version VARCHAR(32) NOT NULL,
    content LONGTEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    operator_user_id VARCHAR(64) NULL,
    operator_username VARCHAR(255) NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uniq_prompt_file_name (file_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_prompt_change_logs (
    id VARCHAR(64) NOT NULL,
    file_name VARCHAR(191) NOT NULL,
    target_file VARCHAR(512) NOT NULL,
    operator_user_id VARCHAR(64) NULL,
    operator_username VARCHAR(255) NULL,
    source_ip VARCHAR(64) NULL,
    before_version VARCHAR(32) NOT NULL,
    after_version VARCHAR(32) NOT NULL,
    before_sha256 VARCHAR(64) NOT NULL,
    after_sha256 VARCHAR(64) NOT NULL,
    before_content LONGTEXT NOT NULL,
    after_content LONGTEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_prompt_change_logs_file_created (file_name, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
