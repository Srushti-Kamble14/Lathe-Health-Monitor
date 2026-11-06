CREATE UNIQUE INDEX IF NOT EXISTS anomaly_results_machine_timestamp_unique_idx
  ON anomaly_results (machine_id, timestamp);
