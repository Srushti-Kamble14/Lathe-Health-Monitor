"""Configuration for database-backed Phase 3 feature preparation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_ENV = ROOT.parent / "backend" / ".env"
REPORT_DIR = ROOT / "reports"
FIGURE_DIR = REPORT_DIR / "figures" / "feature_analysis"
FEATURE_OUTPUT_DIR = ROOT / "artifacts" / "features"
INGESTION_VALIDATION_PATH = REPORT_DIR / "ingestion_validation.json"

MACHINE_CODE = "LATHE-001"
SENSOR_COLUMNS = (
    "current_l1",
    "current_l2",
    "current_l3",
    "voltage_l1",
    "voltage_l2",
    "voltage_l3",
    "vibration_x",
    "vibration_y",
    "vibration_z",
    "tool_temperature",
    "ambient_temperature",
)
CURRENT_COLUMNS = ("current_l1", "current_l2", "current_l3")
VOLTAGE_COLUMNS = ("voltage_l1", "voltage_l2", "voltage_l3")
VIBRATION_COLUMNS = ("vibration_x", "vibration_y", "vibration_z")

CANDIDATE_WINDOW_SECONDS = (30, 60, 120, 300)
MINIMUM_COMPLETENESS = 0.80
MINIMUM_STABLE_WINDOW_SAMPLES = 20
MINIMUM_WINDOWS_FOR_SELECTION = 100
CONTIGUOUS_GAP_FACTOR = 1.5
CORRELATION_REVIEW_THRESHOLD = 0.90
NEAR_ZERO_CV_THRESHOLD = 0.001

# The selection order is also the tie-break order during correlation pruning.
PREFERRED_FEATURES = (
    "current_mean",
    "current_std",
    "current_imbalance",
    "voltage_mean",
    "voltage_imbalance",
    "vibration_rms",
    "vibration_magnitude_std",
    "temperature_delta",
    "temperature_rate",
)

METADATA_COLUMNS = (
    "machine_id",
    "session_id",
    "session_number",
    "window_start",
    "window_end",
    "data_completeness",
    "valid_sample_count",
    "expected_sample_count",
    "window_duration_seconds",
    "split",
)
