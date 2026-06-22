-- Per-user unread/read state for collaboration chains (Admin MySQL).
-- Run once against WORKMATE_DB_DATABASE before enabling collab notifications.

CREATE TABLE IF NOT EXISTS collab_user_chain_state (
    user_id VARCHAR(64) NOT NULL,
    chain_id VARCHAR(64) NOT NULL,
    unread_at DATETIME NULL,
    read_at DATETIME NULL,
    PRIMARY KEY (user_id, chain_id),
    INDEX idx_collab_ucs_user_unread (user_id, unread_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
