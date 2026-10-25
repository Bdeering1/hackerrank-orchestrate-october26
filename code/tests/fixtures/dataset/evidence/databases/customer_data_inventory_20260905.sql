CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
INSERT INTO snapshot_scope VALUES ('integration_service', '2026-09-05T06:00:00Z');
INSERT INTO snapshot_scope VALUES ('backup_service', '2026-09-05T06:00:00Z');
CREATE TABLE connector_subscriptions (resource_id TEXT PRIMARY KEY, subject_reference TEXT, enabled INTEGER NOT NULL);
CREATE TABLE backup_restore_entries (resource_id TEXT PRIMARY KEY, subject_reference TEXT, restore_allowed INTEGER NOT NULL);
