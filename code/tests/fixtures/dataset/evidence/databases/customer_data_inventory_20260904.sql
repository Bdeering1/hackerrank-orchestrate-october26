BEGIN TRANSACTION;
CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
INSERT INTO snapshot_scope VALUES ('account_service', '2026-09-04T07:43:27Z');
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO customer_profiles VALUES ('account_1111', NULL, NULL, 'DANIEL.M47291@OUTLOOK.COM', NULL, NULL, 'DELETION_PENDING', '2026-09-04T07:43:27Z');
INSERT INTO customer_profiles VALUES ('account_1414', 'user_14', 'Tariq Bakr', 'tariq.bakr@gmail.com', NULL, NULL, 'ACTIVE', '2026-09-04T07:43:27Z');
COMMIT;
