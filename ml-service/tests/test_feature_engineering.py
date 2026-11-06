import unittest

import numpy as np
import pandas as pd

import feature_engineering as pipeline
import feature_config as config


class FeatureEngineeringTests(unittest.TestCase):
    def test_feature_formulas_use_the_documented_sensor_math(self):
        samples = np.zeros((20, len(config.SENSOR_COLUMNS)), dtype=float)
        samples[:, 0:3] = [1.0, 2.0, 3.0]
        samples[:, 3:6] = [230.0, 230.0, 230.0]
        samples[:, 6:9] = [3.0, 4.0, 0.0]
        samples[:, 9] = 30.0 + np.arange(20)
        samples[:, 10] = 25.0
        times = np.arange(20, dtype=float) * 3.0

        features = pipeline.feature_values(samples, times, gap_threshold=4.5)

        self.assertAlmostEqual(features["current_mean"], 2.0)
        self.assertAlmostEqual(features["current_imbalance"], 50.0)
        self.assertAlmostEqual(features["voltage_imbalance"], 0.0)
        self.assertAlmostEqual(features["vibration_magnitude"], 5.0)
        self.assertAlmostEqual(features["vibration_magnitude_mean"], 5.0)
        self.assertAlmostEqual(features["vibration_rms"], 5.0)
        self.assertAlmostEqual(features["temperature_delta"], 14.5)
        self.assertAlmostEqual(features["temperature_rate"], 20.0)

    def test_windows_do_not_cross_discontinuous_regions(self):
        timestamps = pd.to_datetime(
            [*range(0, 30, 3), *range(60, 90, 3)],
            unit="s",
            utc=True,
        )
        data = pd.DataFrame(
            {
                "machine_id": ["machine"] * 20,
                "session_id": ["session"] * 20,
                "session_number": [1] * 20,
                "timestamp": timestamps,
                "_segment_id": [1] * 10 + [2] * 10,
                **{
                    column: np.ones(20, dtype=float)
                    for column in config.SENSOR_COLUMNS
                },
            }
        )

        windows, _metrics = pipeline.evaluate_window_size(
            data,
            window_seconds=30,
            nominal_interval=3.0,
            gap_threshold=4.5,
        )

        self.assertEqual(len(windows), 2)
        self.assertEqual(windows["_segment_id"].nunique(), 2)
        self.assertTrue((windows["valid_sample_count"] == 10).all())

    def test_report_formatter_handles_list_metadata(self):
        result = pipeline.markdown_table(pd.DataFrame({"sessions": [[1, 2]]}))
        self.assertIn("[1, 2]", result)


if __name__ == "__main__":
    unittest.main()
