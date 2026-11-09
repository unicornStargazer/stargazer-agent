-- 只保存请求状态和成功重放结果，不作为通用工作流引擎或工具副作用日志。
CREATE TABLE IF NOT EXISTS agent_requests (
    session_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'interrupted')),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    profile_id TEXT NOT NULL,
    response_json TEXT,
    error_code TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, request_id),
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE,
    CHECK (
        (status = 'succeeded' AND response_json IS NOT NULL AND error_code IS NULL)
        OR (status != 'succeeded' AND response_json IS NULL)
    )
);

-- 启动恢复只扫描 running，避免随着历史增长反复全表扫描。
CREATE INDEX IF NOT EXISTS idx_agent_requests_running
    ON agent_requests(status) WHERE status = 'running';
