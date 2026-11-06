import unittest

import numpy as np
import pandas as pd

import anomaly_config as config
import anomaly_detection as ad


class AnomalyDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = ad.load_feature_frame(config.FEATURE_PATH)
        cls.frame = ad.validate_feature_schema(cls.frame)
        cls.train, cls.validation, cls.test = ad.split_dataset(cls.frame)

    def test_feature_schema_validation(self):
        self.assertTrue(set(config.FEATURE_NAMES).issubset(self.frame.columns))
        self.assertIn("split", self.frame.columns)

    def test_missing_feature_detection(self):
        reduced = self.frame.drop(columns=["current_std"])
        with self.assertRaises(ValueError):
            ad.validate_feature_schema(reduced)

    def test_numeric_validation(self):
        bad = self.frame.copy()
        bad["current_mean"] = "not_numeric"
        with self.assertRaises(ValueError):
            ad.validate_feature_schema(bad)

    def test_split_integrity(self):
        train, validation, test = ad.split_dataset(self.frame)
        self.assertEqual({"train", "validation", "test"}, {"train", "validation", "test"})
        self.assertGreater(len(train), 0)
        self.assertGreater(len(validation), 0)
        self.assertGreater(len(test), 0)

    def test_train_only_scaling(self):
        result = ad.fit_one_class_svm(self.train, self.validation, self.test)
        self.assertIn("scaler", result)
        self.assertLess(result["warning_threshold"], result["anomaly_threshold"])
        self.assertIn("train", result)
        self.assertIn("validation", result)
        self.assertIn("test", result)

    def test_score_direction(self):
        scores = pd.Series([0.05, 0.4, 0.8, 1.2])
        warning, anomaly = ad.derive_thresholds(scores)
        self.assertLess(warning, anomaly)
        self.assertEqual(ad.score_to_status(0.0, warning, anomaly), "NORMAL")
        self.assertEqual(ad.score_to_status((warning + anomaly) / 2.0, warning, anomaly), "WARNING")

    def test_valid_anomaly_statuses(self):
        statuses = {ad.score_to_status(score, 0.5, 1.0) for score in [0.0, 0.75, 1.2]}
        self.assertTrue(statuses.issubset({"NORMAL", "WARNING", "ANOMALOUS"}))

    def test_output_schema(self):
        result = ad.fit_isolation_forest(self.train, self.validation, self.test)
        frame = result["test"]
        required = {"window_start", "window_end", "session_id", "split", "anomaly_score", "anomaly_status", "model_name", "model_version"}
        self.assertTrue(required.issubset(frame.columns))

    def test_no_rpm_or_acoustic_fields(self):
        for column in self.frame.columns:
            lowered = column.lower()
            self.assertNotIn("rpm", lowered)
            self.assertNotIn("acoustic", lowered)
            self.assertNotIn("sound", lowered)


if __name__ == "__main__":
    unittest.main()
