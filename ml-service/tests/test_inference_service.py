import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from anomaly_config import FEATURE_NAMES
from service.main import app
from service.model_runtime import load_runtime, score_to_status


ROOT = Path(__file__).resolve().parents[1]


class InferenceServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frame = pd.read_csv(ROOT / "artifacts" / "features" / "ml_ready_features.csv")
        cls.features = {
            name: float(frame.loc[0, name])
            for name in FEATURE_NAMES
        }

    def setUp(self):
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def test_health_and_readiness(self):
        health = self.client.get("/health")
        ready = self.client.get("/ready")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "running")
        self.assertEqual(ready.status_code, 200)
        self.assertTrue(ready.json()["model_loaded"])

    def test_model_loads_once_and_isolation_forest_ready(self):
        runtime = load_runtime()
        self.assertEqual(runtime.model_name, "IsolationForest")
        self.assertEqual(runtime.model_version, "isolation-forest-v1")
        self.assertEqual(runtime.estimator.n_features_in_, len(FEATURE_NAMES))

    def test_missing_model_artifact_fails_instead_of_fitting_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("service.model_runtime.ARTIFACT_ROOT", Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "artifacts are missing or invalid"):
                    load_runtime()

    def test_valid_feature_vector_returns_finite_score_and_status(self):
        response = self.client.post(
            "/api/v1/anomaly/score",
            json=self.features,
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["data"]
        self.assertTrue(math.isfinite(result["anomaly_score"]))
        self.assertIn(result["anomaly_status"], {"NORMAL", "WARNING", "ANOMALOUS"})
        self.assertEqual(result["features_used"], list(FEATURE_NAMES))
        self.assertEqual(result["model_name"], "IsolationForest")

    def test_missing_and_unexpected_features_are_rejected(self):
        missing = dict(self.features)
        missing.pop("current_mean")
        extra = {**self.features, "unapproved_sensor": 1.0}
        self.assertEqual(
            self.client.post("/api/v1/anomaly/score", json=missing).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/v1/anomaly/score", json=extra).status_code,
            422,
        )

    def test_non_numeric_boolean_nan_and_infinity_are_rejected(self):
        invalid_values = ["not-a-number", True, float("nan"), float("inf")]
        for value in invalid_values:
            with self.subTest(value=value):
                payload = dict(self.features)
                payload["current_mean"] = value
                response = self.client.post(
                    "/api/v1/anomaly/score",
                    content=json.dumps(payload),
                    headers={"content-type": "application/json"},
                )
                self.assertEqual(response.status_code, 422)

    def test_higher_scores_map_to_more_severe_statuses(self):
        runtime = load_runtime()
        self.assertEqual(
            score_to_status(runtime.warning_threshold - 1e-8, runtime.warning_threshold, runtime.anomaly_threshold),
            "NORMAL",
        )
        self.assertEqual(
            score_to_status(runtime.warning_threshold, runtime.warning_threshold, runtime.anomaly_threshold),
            "WARNING",
        )
        self.assertEqual(
            score_to_status(runtime.anomaly_threshold, runtime.warning_threshold, runtime.anomaly_threshold),
            "ANOMALOUS",
        )


if __name__ == "__main__":
    unittest.main()
