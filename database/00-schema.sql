-- 主数据库 schema (runs against POSTGRES_DB = main_db)
-- TIMESTAMPTZ used to avoid silent UTC/local drift on container restarts.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    tenant_db_name VARCHAR(63) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- email/username UNIQUE constraints already create implicit indexes;
-- only add the tenant lookup index here (extras are pruned).
CREATE INDEX IF NOT EXISTS idx_users_tenant_db ON users(tenant_db_name);

-- Durable backing store for the app-level rate limiter (app/middleware/
-- rate_limiter.py writes/reads this against the MAIN pool). It is ALSO created
-- by alembic migration 002 (main_db branch), but the active docker-entrypoint
-- deploy path runs these *.sql files against main_db without necessarily
-- running alembic, so we create it here too to guarantee it exists in prod
-- (audit F08). Both definitions are IF NOT EXISTS and identical, so they are
-- mutually idempotent regardless of run order.
CREATE TABLE IF NOT EXISTS rate_limit_counters (
    client_id TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (client_id, window_start)
);

CREATE INDEX IF NOT EXISTS ix_rate_limit_counters_window_start
    ON rate_limit_counters (window_start);

-- Email verification codes for registration / password reset (app/services/
-- email_verification.py writes/reads this against the MAIN pool). Same
-- intentional duplication as rate_limit_counters above: alembic migration 003
-- (main_db branch) creates it too, but the docker-entrypoint deploy path runs
-- these *.sql files without necessarily running alembic. Both definitions are
-- IF NOT EXISTS and identical, so they are mutually idempotent in any order.
--
-- PRIMARY KEY (email, scene) is deliberate: a resend UPSERTs over the previous
-- code, which bounds rows per address and invalidates the old code.
CREATE TABLE IF NOT EXISTS email_verification_codes (
    email VARCHAR(255) NOT NULL,
    scene VARCHAR(32) NOT NULL,
    code_hash CHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (email, scene)
);

CREATE INDEX IF NOT EXISTS ix_email_verification_codes_expires_at
    ON email_verification_codes (expires_at);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
