-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-09-02T23:00:00Z
-- Database topology: failover_replica

BEGIN TRANSACTION;
CREATE TABLE customer_profiles_failover_replica (resource_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_profiles_failover_replica" VALUES('account_101','user_01','Leila Haddad','leila.haddad@yahoo.com','+212 6 48 27 15 93','ACTIVE','2026-09-02T22:45:00Z');
INSERT INTO "customer_profiles_failover_replica" VALUES('account_8741','user_8741','Karim El-Masri','karim.elmasri@gmail.com','+971 50 731 6284','ACTIVE','2026-09-02T22:45:00Z');
CREATE TABLE customer_profiles_primary (resource_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_profiles_primary" VALUES('account_8741','user_8741','Karim El-Masri','karim.elmasri@gmail.com','+971 50 731 6284','ACTIVE','2026-09-02T22:45:00Z');
COMMIT;
