-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-09-03T06:00:00Z
-- Database topology: reporting_replica
-- Compare the primary and any replica tables for replication drift.

BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
INSERT INTO "customer_data_primary" VALUES('search_4618','search_service','customer_search_documents','{"resource_id":"search_4618","index_name":"customer_directory_v3","document":{"display_name":"Lucía Herrera","email":"lucia.herrera@zoho.com","customer_reference":"user_15"}}','2026-09-03T06:00:00Z');
INSERT INTO "customer_data_primary" VALUES('account_1313','account_service','customer_profiles','{"resource_id":"account_1313","customer_reference":null,"full_name":"Rafael Costa","email":null,"phone":null,"account_status":"ACTIVE","signup_channel":"web"}','2026-09-03T06:00:00Z');
CREATE TABLE customer_data_reporting_replica (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
INSERT INTO "customer_data_reporting_replica" VALUES('account_1515','account_service','customer_profiles','{"resource_id":"account_1515","customer_reference":"user_15","full_name":"Lucía Herrera","email":"lucia.herrera@zoho.com","phone":"+52 55 4821 9376","account_status":"ACTIVE","signup_channel":"mobile_app"}','2026-09-03T06:00:00Z');
COMMIT;
