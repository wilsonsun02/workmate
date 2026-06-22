-- Admin API performance indexes
-- Safe for repeated execution on MySQL by checking information_schema first.

SET @schema_name = DATABASE();

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'sys_users'
      AND index_name = 'idx_users_tenant_created'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE sys_users ADD INDEX idx_users_tenant_created (tenant_id, created_at)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'sys_users'
      AND index_name = 'idx_users_dept_status_created'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE sys_users ADD INDEX idx_users_dept_status_created (dept_id, status, created_at)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'sys_users'
      AND index_name = 'idx_users_role_status_created'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE sys_users ADD INDEX idx_users_role_status_created (role_id, status, created_at)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'sys_skill_packages'
      AND index_name = 'idx_skill_package_skill_created'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE sys_skill_packages ADD INDEX idx_skill_package_skill_created (skill_name, created_at)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'collab_chains'
      AND index_name = 'idx_initiator_updated'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE collab_chains ADD INDEX idx_initiator_updated (initiator_user_id, updated_at)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'collab_chains'
      AND index_name = 'idx_status_updated'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE collab_chains ADD INDEX idx_status_updated (status, updated_at)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'collab_steps'
      AND index_name = 'idx_assignee_chain'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE collab_steps ADD INDEX idx_assignee_chain (assignee_user_id, chain_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'conversation_summaries'
      AND index_name = 'idx_username_created_id'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE conversation_summaries ADD INDEX idx_username_created_id (username, created_at, id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'conversation_summaries'
      AND index_name = 'idx_thread_created_id'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE conversation_summaries ADD INDEX idx_thread_created_id (thread_id(191), created_at, id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = @schema_name
      AND table_name = 'conversation_summaries'
      AND index_name = 'ft_summary'
);
SET @sql = IF(
    @idx_exists = 0,
    'ALTER TABLE conversation_summaries ADD FULLTEXT INDEX ft_summary (summary)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
