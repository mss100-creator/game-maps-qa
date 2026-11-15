CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  ip TEXT, country TEXT, region TEXT, city TEXT, asn TEXT,
  profile TEXT, kind TEXT, total INTEGER, ok INTEGER, seconds REAL
);
CREATE TABLE IF NOT EXISTS clicks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  site TEXT, color TEXT, x INTEGER, y INTEGER,
  ok INTEGER, url TEXT, status INTEGER, reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_clicks_run ON clicks(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_time ON runs(created_at);
