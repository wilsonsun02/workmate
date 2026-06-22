CREATE INDEX idx_user_online_heartbeat
ON sys_client_user_sessions (user_id, is_online, last_heartbeat);

