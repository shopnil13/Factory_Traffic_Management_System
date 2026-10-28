-- Factory Traffic Management System Schema
-- SQLite WAL mode production schema

CREATE TABLE IF NOT EXISTS junctions (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS junction_state (
  junction_id TEXT PRIMARY KEY REFERENCES junctions(id),
  version INTEGER NOT NULL,
  mode TEXT NOT NULL,
  suspended_mode TEXT,
  stage TEXT NOT NULL,
  stage_status TEXT NOT NULL,
  active_phase TEXT,
  target_phase TEXT,
  stage_started_at TEXT,
  stage_timer_started_at TEXT,
  desired_signals_json TEXT NOT NULL,
  actual_signals_json TEXT NOT NULL,
  controller_status TEXT NOT NULL,
  device_status_json TEXT NOT NULL,
  manual_owner TEXT,
  manual_direction TEXT,
  manual_expires_at TEXT,
  phase_last_green_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
  junction_id TEXT NOT NULL,
  vehicle_id TEXT NOT NULL,
  direction TEXT NOT NULL,
  vehicle_type TEXT,
  status TEXT NOT NULL,               -- WAITING | CLEARED | EXPIRED
  received_at TEXT,
  sensor_ts TEXT,
  last_sequence_no INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (junction_id, vehicle_id)
);

CREATE TABLE IF NOT EXISTS processed_events (
  junction_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  outcome TEXT NOT NULL,
  received_at TEXT NOT NULL,
  PRIMARY KEY (junction_id, event_id)
);

CREATE TABLE IF NOT EXISTS pending_commands (
  command_id TEXT PRIMARY KEY,
  junction_id TEXT NOT NULL,
  direction TEXT NOT NULL,
  requested_state TEXT NOT NULL,
  stage TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 1,
  sent_at TEXT,
  status TEXT NOT NULL               -- PENDING | ACKED | FAILED | SUPERSEDED
);

CREATE TABLE IF NOT EXISTS emergencies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  junction_id TEXT NOT NULL,
  direction TEXT NOT NULL,
  vehicle_id TEXT NOT NULL,
  status TEXT NOT NULL,               -- ACTIVE | SERVING | CLEARED | EXPIRED
  detected_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  serving_since TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  junction_id TEXT NOT NULL,
  server_ts TEXT NOT NULL,
  sensor_ts TEXT,
  event_type TEXT NOT NULL,
  direction TEXT,
  previous_state TEXT,
  new_state TEXT,
  command_id TEXT,
  correlation_id TEXT,
  mode TEXT,
  message TEXT NOT NULL,
  details_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_audit_junction_id_id ON audit_log(junction_id, id DESC);
