-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-09-03T09:00:00Z
-- Database topology: read_replica

BEGIN TRANSACTION;
CREATE TABLE customer_profiles_primary (resource_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE customer_profiles_read_replica (resource_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_profiles_read_replica" VALUES('account_1313','Rafael Costa','ACTIVE','2026-09-03T08:45:00Z');
COMMIT;
