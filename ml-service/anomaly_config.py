"""Configuration for the Phase 4 unsupervised anomaly-detection pipeline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEATURE_PATH = ROOT / "artifacts" / "features" / "ml_ready_features.csv"
ARTIFACT_DIR = ROOT / "artifacts" / "anomaly_detection"
REPORT_DIR = ROOT / "reports"
FIGURE_DIR = REPORT_DIR / "figures" / "anomaly_detection"

FEATURE_NAMES = (
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

REQUIRED_COLUMNS = (
    "machine_id",
    "session_id",
    "session_number",
    "window_start",
    "window_end",
    *FEATURE_NAMES,
    "split",
)

ALLOWED_SPLITS = ("train", "validation", "test")
STATUS_ORDER = ("NORMAL", "WARNING", "ANOMALOUS")
MODEL_VERSION = "phase4-isolation-forest-v1"
DEFAULT_RANDOM_STATE = 42
