# Phase 3 — Feature Engineering and ML Dataset Preparation

## 1. Objective

Create a reproducible, database-first feature pipeline from the persisted sensor readings. This phase validates the source, derives session-bounded time windows, reviews features, and writes a chronological ML-ready dataset. It does not fit an anomaly model, calculate production scores, or assign machine-health statuses.

## 2. Input Data

Primary source: Neon PostgreSQL `sensor_readings`, joined to `machines` and `machine_sessions` using persisted machine identity and timestamp boundaries. Only the eleven approved temperature, vibration, current, and voltage fields are selected. No CSV data is read by this pipeline.

- Machine code: `LATHE-001`
- Observed readings: **67,258**
- Persisted sessions: **6**; sessions with readings: **6**; empty sessions: **0**
- Reading timestamp parse failures: **0**
- Timestamp ordering: **chronological**
- Duplicate / multiply matched timestamps: **0**
- Within-session interval count: **67,252**
- Within-session interval counts (seconds: count): `{"3": 67252}`
- Sampling intervals (seconds): min **3.000**, median **3.000**, mode **3.000**, p95 **3.000**, max **3.000**
- Contiguous-gap threshold: **4.500 seconds** (1.5 × the greater of the modal and median within-session interval)
- Stored session sample-count mismatches: **[]**
- Missing fields by sensor: `{"ambient_temperature": 0, "current_l1": 0, "current_l2": 0, "current_l3": 0, "tool_temperature": 0, "vibration_x": 0, "vibration_y": 0, "vibration_z": 0, "voltage_l1": 0, "voltage_l2": 0, "voltage_l3": 0}`
- Invalid numeric values by sensor: `{"ambient_temperature": 0, "current_l1": 0, "current_l2": 0, "current_l3": 0, "tool_temperature": 0, "vibration_x": 0, "vibration_y": 0, "vibration_z": 0, "voltage_l1": 0, "voltage_l2": 0, "voltage_l3": 0}`
- Historical comparison: Historical ingestion snapshot: 67258 rows across 6 sessions. This is a comparison point, not a hard-coded pipeline requirement.
- Difference from historical snapshot: **0 readings**, **0 sessions**. Differences are reported for investigation; the historical totals do not gate processing.

Timestamp and sensor range checks are calculated from the database query at each run. Source timestamps stored as `TIMESTAMPTZ` are interpreted and displayed in UTC, consistent with the Phase 2 ingestion convention.

### Persisted session boundaries

| session | session_id | start_utc | end_utc | preceding_gap_seconds | duration_seconds | observed_records | database_session_sample_count | median_interval_seconds | maximum_interval_seconds | stored_count_matches |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 780fc743-2049-492f-a939-f1096faec6ac | 2026-11-01T09:03:01+00:00 | 2026-11-01T18:33:13+00:00 |  | 34212.0000 | 11405 | 11405 | 3.0000 | 3.0000 | yes |
| 2 | 6545563d-3c6d-488e-b566-f7f572af0a64 | 2026-11-03T09:04:10+00:00 | 2026-11-03T18:21:10+00:00 | 138657.0000 | 33420.0000 | 11141 | 11141 | 3.0000 | 3.0000 | yes |
| 3 | 06cb38d0-9ec5-4ae3-b51b-b27b1363cf2b | 2026-11-04T09:01:15+00:00 | 2026-11-04T18:15:21+00:00 | 52805.0000 | 33246.0000 | 11083 | 11083 | 3.0000 | 3.0000 | yes |
| 4 | 01697e8d-16b7-4a3c-9623-fd59b02c62ac | 2026-11-05T09:03:01+00:00 | 2026-11-05T18:33:13+00:00 | 53260.0000 | 34212.0000 | 11405 | 11405 | 3.0000 | 3.0000 | yes |
| 5 | 4e0f9da8-1bb7-47eb-b7d6-3a67c3a21926 | 2026-11-06T09:04:10+00:00 | 2026-11-06T18:21:10+00:00 | 52257.0000 | 33420.0000 | 11141 | 11141 | 3.0000 | 3.0000 | yes |
| 6 | 6eda8b68-6ae8-469c-89b7-f786da110934 | 2026-11-07T09:01:15+00:00 | 2026-11-07T18:15:21+00:00 | 52805.0000 | 33246.0000 | 11083 | 11083 | 3.0000 | 3.0000 | yes |

### Sensor value ranges

| sensor | minimum | maximum |
| --- | --- | --- |
| current_l1 | 0.0300 | 5.3400 |
| current_l2 | 0.0000 | 16.7700 |
| current_l3 | 0.1600 | 5.5800 |
| voltage_l1 | 231.5000 | 231.9400 |
| voltage_l2 | 231.5000 | 231.9400 |
| voltage_l3 | 231.5000 | 231.9400 |
| vibration_x | -1360.0000 | 2272.0000 |
| vibration_y | 12524.0000 | 19128.0000 |
| vibration_z | -4844.0000 | 1484.0000 |
| tool_temperature | 26.2000 | 45.9400 |
| ambient_temperature | 24.9500 | 27.5300 |

## 3. Windowing Analysis

Within each persisted session, rows are sorted by timestamp and then divided into contiguous regions. A gap larger than **4.500 seconds** starts a new region. A candidate window is anchored to the beginning of its region; no window can cross a persisted session or a detected gap.

For each candidate, expected samples are rounded from window seconds divided by the observed modal cadence. The minimum valid sample count is `ceil(expected samples × 80%)`. Windows below this minimum are dropped. Thus, for the selected 60-second window, at least **16** valid readings are required.

The within-window standard deviation columns summarize within-window sensor spread. The half-window change columns compare the first and second halves of each window for representative current, voltage, vibration RMS, and tool-temperature signals; they are median absolute level changes across accepted windows, so smaller changes indicate more internally consistent windows. These are diagnostic comparisons, not model targets. Temporal coverage credits one observed cadence interval after each window's last sample, capped at the candidate duration, and compares accepted coverage against persisted session spans.

| window_seconds | expected_samples_per_window | minimum_valid_samples | window_count | usable_records | usable_data_pct | temporal_coverage_pct | median_samples_per_window | p10_samples_per_window | p90_samples_per_window | median_within_window_std_current | median_within_window_std_voltage | median_within_window_std_vibration_magnitude | median_within_window_std_tool_temperature | median_half_window_change_current | median_half_window_change_voltage | median_half_window_change_vibration_rms | median_half_window_change_tool_temperature |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 10 | 8 | 6724 | 67240 | 99.9732 | 99.9732 | 10.0000 | 10.0000 | 10.0000 | 0.0118 | 0.0679 | 56.1912 | 0.0149 | 0.0067 | 0.0320 | 27.4639 | 0.0240 |
| 60 | 20 | 16 | 3362 | 67240 | 99.9732 | 99.9732 | 20.0000 | 20.0000 | 20.0000 | 0.0136 | 0.0707 | 58.3080 | 0.0412 | 0.0083 | 0.0227 | 17.1274 | 0.0590 |
| 120 | 40 | 32 | 1680 | 67200 | 99.9138 | 99.9138 | 40.0000 | 40.0000 | 40.0000 | 0.0659 | 0.0721 | 61.4129 | 0.1264 | 0.0310 | 0.0152 | 13.8115 | 0.1138 |
| 300 | 100 | 80 | 672 | 67166 | 99.8632 | 99.8632 | 100.0000 | 100.0000 | 100.0000 | 0.0699 | 0.0730 | 59.6515 | 0.2135 | 0.0173 | 0.0099 | 9.4755 | 0.2313 |

**Selection:** 60 seconds. The selection rule chooses the shortest candidate with at least 20 expected samples, 95% usable source records, and 100 windows. This supports stable window statistics while limiting monitoring delay. Candidate counts, record coverage, temporal coverage, per-window sample distributions, and within-window spread are retained above; larger windows trade responsiveness for additional aggregation. The window duration field in the artifact is the observed first-to-last sample span, while the expected sample count and completeness describe the nominal candidate duration.

## 4. Feature Definitions

Features below are computed independently for every accepted window. Standard deviations use population convention (`ddof=0`).

- **Current phase features:** for each phase `l1`, `l2`, `l3`, the mean, standard deviation, minimum, and maximum of that phase's window samples.
- **Current aggregate features:** mean, population standard deviation, minimum, and maximum over all current phase samples in the window. `current_imbalance` is the mean over timestamps of `100 × max_phase(abs(I_phase - mean_phase_current)) / abs(mean_phase_current)`. Timestamps whose phase mean is numerically zero do not contribute; if none are valid the value is zero.
- **Voltage phase and aggregate features:** same phase-wise and flattened-window statistics as current. `voltage_imbalance` uses the analogous per-timestamp maximum absolute phase deviation divided by absolute three-phase mean, expressed as percent.
- **Vibration axis features:** per-axis mean, population standard deviation, minimum, and maximum.
- **Vibration magnitude:** instantaneous vector magnitude is `sqrt(x² + y² + z²)`. `vibration_magnitude` is the Euclidean norm of the three window-axis means; `vibration_magnitude_mean` and `vibration_magnitude_std` are the mean and population standard deviation of instantaneous magnitude. `vibration_rms = sqrt(mean(x² + y² + z²))` over all timestamps in the window.
- **Temperature features:** tool and ambient mean, population standard deviation, minimum, and maximum. `temperature_delta = mean(tool_temperature - ambient_temperature)` for the window.
- **Temperature rate:** mean of adjacent tool-temperature differences divided by the actual elapsed seconds and multiplied by 60. Pair intervals must be positive and no longer than the contiguous-gap threshold; therefore no rate spans a session boundary or detected gap. A window with no valid adjacent pair receives zero.

No frequency-domain features are generated: this pipeline uses the observed time-domain channels and does not assume sampling resolution or units sufficient for spectral interpretation.

## 5. Feature Quality

### Group A — Candidate features

The 60 candidate sensor-derived features at the selected window size are listed below. Quality statistics include finite count, missing percentage, mean, median, standard deviation, variance, minimum/maximum, selected percentiles, unique-value count, skew, and IQR outlier percentage. The screening rule is the conventional 1.5 × IQR range; flagged points are retained because extreme observations may be useful for later anomaly work. Skewness with absolute value at least 2 is treated as a review cue, not a deletion criterion. Near-zero variance is flagged when a feature has at most five unique values or its coefficient of variation is at most 0.100%; it is a review flag, not an automatic exclusion. These statistics do not establish physical validity because source-unit and calibration documentation is incomplete.

| feature | count | missing_pct | mean | median | std | variance | minimum | maximum | p01 | p99 | unique_values | skew | iqr_outlier_pct | constant | near_zero_variance |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_l1_mean | 3362 | 0.0000 | 0.5377 | 0.0650 | 1.2469 | 1.5547 | 0.0395 | 5.1950 | 0.0425 | 4.7699 | 341 | 2.4666 | 21.1184 | no | no |
| current_l1_std | 3362 | 0.0000 | 0.1625 | 0.0077 | 0.4882 | 0.2383 | 0.0030 | 2.5878 | 0.0048 | 2.1944 | 472 | 3.3603 | 22.3081 | no | no |
| current_l1_min | 3362 | 0.0000 | 0.3226 | 0.0500 | 1.0414 | 1.0845 | 0.0300 | 5.1500 | 0.0300 | 4.7000 | 41 | 3.5955 | 6.5437 | no | no |
| current_l1_max | 3362 | 0.0000 | 0.7578 | 0.0800 | 1.5092 | 2.2777 | 0.0500 | 5.3400 | 0.0500 | 4.8600 | 57 | 2.0056 | 24.2713 | no | no |
| current_l2_mean | 3362 | 0.0000 | 0.8039 | 0.3340 | 1.2086 | 1.4606 | 0.3090 | 5.2580 | 0.3153 | 4.7224 | 440 | 2.4613 | 14.5152 | no | no |
| current_l2_std | 3362 | 0.0000 | 0.1902 | 0.0261 | 0.4739 | 0.2246 | 0.0071 | 3.0337 | 0.0162 | 2.1212 | 616 | 3.3406 | 8.3879 | no | no |
| current_l2_min | 3362 | 0.0000 | 0.5519 | 0.2900 | 1.0072 | 1.0144 | 0.0000 | 5.0100 | 0.2700 | 4.6400 | 50 | 3.5778 | 7.4360 | no | no |
| current_l2_max | 3362 | 0.0000 | 1.1053 | 0.3900 | 1.5617 | 2.4390 | 0.3300 | 16.7700 | 0.3500 | 5.0868 | 66 | 2.9249 | 14.5152 | no | no |
| current_l3_mean | 3362 | 0.0000 | 0.7908 | 0.3345 | 1.1812 | 1.3953 | 0.3085 | 5.0975 | 0.3105 | 4.5802 | 457 | 2.4571 | 14.4557 | no | no |
| current_l3_std | 3362 | 0.0000 | 0.1893 | 0.0271 | 0.4532 | 0.2054 | 0.0048 | 2.3678 | 0.0126 | 2.0549 | 620 | 3.2856 | 14.1582 | no | no |
| current_l3_min | 3362 | 0.0000 | 0.5424 | 0.2800 | 0.9897 | 0.9794 | 0.1600 | 4.9200 | 0.2600 | 4.5200 | 52 | 3.5736 | 7.9714 | no | no |
| current_l3_max | 3362 | 0.0000 | 1.1029 | 0.3900 | 1.4157 | 2.0042 | 0.3300 | 5.5800 | 0.3400 | 4.6800 | 62 | 1.9170 | 14.5152 | no | no |
| current_mean | 3362 | 0.0000 | 0.7108 | 0.2435 | 1.2117 | 1.4682 | 0.2213 | 5.1660 | 0.2233 | 4.5949 | 543 | 2.4583 | 14.5152 | no | no |
| current_std | 3362 | 0.0000 | 0.2737 | 0.1310 | 0.4446 | 0.1977 | 0.0723 | 2.4774 | 0.1007 | 2.1306 | 663 | 3.3654 | 8.5663 | no | no |
| current_min | 3362 | 0.0000 | 0.3172 | 0.0500 | 1.0191 | 1.0385 | 0.0000 | 4.8800 | 0.0300 | 4.4200 | 39 | 3.5762 | 6.6032 | no | no |
| current_max | 3362 | 0.0000 | 1.1569 | 0.3900 | 1.5766 | 2.4856 | 0.3500 | 16.7700 | 0.3600 | 5.0868 | 71 | 2.8219 | 14.5152 | no | no |
| current_imbalance | 3362 | 0.0000 | 67.1867 | 73.4385 | 21.0055 | 441.2299 | 2.0766 | 85.5509 | 2.8712 | 81.3008 | 662 | -2.3107 | 13.3849 | no | no |
| voltage_l1_mean | 3362 | 0.0000 | 231.7186 | 231.7195 | 0.0289 | 0.0008 | 231.6205 | 231.8205 | 231.6493 | 231.7824 | 546 | -0.0960 | 1.0708 | no | yes |
| voltage_l1_std | 3362 | 0.0000 | 0.1232 | 0.1235 | 0.0133 | 0.0002 | 0.0810 | 0.1598 | 0.0906 | 0.1538 | 1673 | -0.1810 | 0.7139 | no | no |
| voltage_l1_min | 3362 | 0.0000 | 231.5207 | 231.5200 | 0.0197 | 0.0004 | 231.5000 | 231.6300 | 231.5000 | 231.5900 | 14 | 1.4978 | 4.2832 | no | yes |
| voltage_l1_max | 3362 | 0.0000 | 231.9181 | 231.9200 | 0.0217 | 0.0005 | 231.8000 | 231.9400 | 231.8400 | 231.9400 | 15 | -1.5804 | 5.4134 | no | yes |
| voltage_l2_mean | 3362 | 0.0000 | 231.7200 | 231.7200 | 0.0281 | 0.0008 | 231.6220 | 231.8060 | 231.6530 | 231.7837 | 527 | -0.0382 | 0.8923 | no | yes |
| voltage_l2_std | 3362 | 0.0000 | 0.1231 | 0.1236 | 0.0134 | 0.0002 | 0.0748 | 0.1623 | 0.0909 | 0.1529 | 1675 | -0.1430 | 0.7139 | no | no |
| voltage_l2_min | 3362 | 0.0000 | 231.5207 | 231.5100 | 0.0195 | 0.0004 | 231.5000 | 231.6400 | 231.5000 | 231.5800 | 13 | 1.4292 | 3.8073 | no | yes |
| voltage_l2_max | 3362 | 0.0000 | 231.9187 | 231.9300 | 0.0213 | 0.0005 | 231.7900 | 231.9400 | 231.8400 | 231.9400 | 15 | -1.6309 | 4.9375 | no | yes |
| voltage_l3_mean | 3362 | 0.0000 | 231.7203 | 231.7205 | 0.0288 | 0.0008 | 231.6245 | 231.8340 | 231.6496 | 231.7871 | 537 | 0.0238 | 0.7733 | no | yes |
| voltage_l3_std | 3362 | 0.0000 | 0.1229 | 0.1237 | 0.0133 | 0.0002 | 0.0749 | 0.1627 | 0.0884 | 0.1508 | 1674 | -0.2723 | 0.7733 | no | no |
| voltage_l3_min | 3362 | 0.0000 | 231.5211 | 231.5200 | 0.0205 | 0.0004 | 231.5000 | 231.6500 | 231.5000 | 231.5900 | 15 | 1.6016 | 4.4021 | no | yes |
| voltage_l3_max | 3362 | 0.0000 | 231.9191 | 231.9200 | 0.0207 | 0.0004 | 231.8000 | 231.9400 | 231.8400 | 231.9400 | 14 | -1.6584 | 4.1047 | no | yes |
| voltage_mean | 3362 | 0.0000 | 231.7196 | 231.7197 | 0.0166 | 0.0003 | 231.6612 | 231.7733 | 231.6787 | 231.7575 | 849 | -0.0455 | 1.2493 | no | yes |
| voltage_std | 3362 | 0.0000 | 0.1257 | 0.1262 | 0.0076 | 0.0001 | 0.0947 | 0.1489 | 0.1065 | 0.1424 | 1675 | -0.2793 | 1.0708 | no | no |
| voltage_min | 3362 | 0.0000 | 231.5068 | 231.5100 | 0.0079 | 0.0001 | 231.5000 | 231.5600 | 231.5000 | 231.5300 | 7 | 1.3829 | 2.7960 | no | yes |
| voltage_max | 3362 | 0.0000 | 231.9330 | 231.9300 | 0.0086 | 0.0001 | 231.8700 | 231.9400 | 231.9000 | 231.9400 | 7 | -1.6202 | 3.5098 | no | yes |
| voltage_imbalance | 3362 | 0.0000 | 0.0554 | 0.0552 | 0.0058 | 0.0000 | 0.0350 | 0.0759 | 0.0419 | 0.0687 | 1675 | 0.0525 | 0.7139 | no | no |
| vibration_x_mean | 3362 | 0.0000 | 561.2461 | 548.6000 | 73.3783 | 5384.3697 | 293.8000 | 1601.0000 | 455.2010 | 843.2560 | 389 | 6.7215 | 11.3623 | no | no |
| vibration_x_std | 3362 | 0.0000 | 97.2278 | 53.7833 | 133.8353 | 17911.8813 | 13.9413 | 961.8219 | 32.1863 | 670.9148 | 656 | 3.1098 | 14.6936 | no | no |
| vibration_x_min | 3362 | 0.0000 | 353.8832 | 440.0000 | 293.4397 | 86106.8780 | -1360.0000 | 693.0000 | -1032.0000 | 496.0000 | 147 | -3.4248 | 12.8495 | no | no |
| vibration_x_max | 3362 | 0.0000 | 751.4373 | 660.0000 | 303.3386 | 92014.2875 | 560.0000 | 2272.0000 | 596.0000 | 1973.5600 | 180 | 2.9318 | 13.7418 | no | no |
| vibration_y_mean | 3362 | 0.0000 | 16062.3879 | 16059.4000 | 54.2587 | 2944.0049 | 15624.4000 | 16707.6000 | 15925.1860 | 16282.0680 | 393 | 2.8734 | 15.1695 | no | no |
| vibration_y_std | 3362 | 0.0000 | 109.0140 | 57.6042 | 156.8959 | 24616.3124 | 11.4175 | 1094.7507 | 30.5490 | 793.2439 | 652 | 3.3400 | 14.5747 | no | no |
| vibration_y_min | 3362 | 0.0000 | 15837.3392 | 15952.0000 | 389.4879 | 151700.8087 | 12524.0000 | 16256.2600 | 13884.0000 | 16004.0000 | 143 | -4.4687 | 12.6710 | no | no |
| vibration_y_max | 3362 | 0.0000 | 16294.5257 | 16152.0000 | 393.2689 | 154660.4084 | 16056.0000 | 19128.0000 | 16104.0000 | 18056.0000 | 150 | 3.3264 | 14.4557 | no | no |
| vibration_z_mean | 3362 | 0.0000 | -1664.7041 | -1659.4000 | 36.2439 | 1313.6205 | -1975.1000 | -1370.2675 | -1790.1933 | -1551.8000 | 414 | -0.4531 | 8.2689 | no | no |
| vibration_z_std | 3362 | 0.0000 | 109.3978 | 67.1607 | 131.2496 | 17226.4472 | 18.3041 | 1224.3322 | 44.9618 | 706.0885 | 654 | 3.6226 | 14.1582 | no | no |
| vibration_z_min | 3362 | 0.0000 | -1885.5606 | -1804.0000 | 298.5145 | 89110.9175 | -4844.0000 | -1704.0000 | -3227.8000 | -1716.0000 | 133 | -3.9431 | 12.8495 | no | no |
| vibration_z_max | 3362 | 0.0000 | -1437.5407 | -1528.0000 | 330.8103 | 109435.4397 | -1685.5000 | 1484.0000 | -1613.5600 | 421.1600 | 143 | 4.0426 | 13.3849 | no | no |
| vibration_magnitude | 3362 | 0.0000 | 16158.3739 | 16155.3232 | 56.0164 | 3137.8375 | 15722.5925 | 16796.0769 | 16023.6355 | 16394.7921 | 668 | 3.0154 | 14.1582 | no | no |
| vibration_magnitude_mean | 3362 | 0.0000 | 16160.0488 | 16155.6120 | 57.2722 | 3280.1032 | 15723.1668 | 16819.8314 | 16036.4369 | 16404.6964 | 668 | 3.3651 | 14.1582 | no | no |
| vibration_magnitude_std | 3362 | 0.0000 | 111.4251 | 58.3080 | 162.3972 | 26372.8486 | 10.8260 | 1162.7974 | 31.8755 | 816.5221 | 668 | 3.3454 | 14.6341 | no | no |
| vibration_rms | 3362 | 0.0000 | 16161.2464 | 16155.7108 | 57.9513 | 3358.3572 | 15732.0754 | 16834.0228 | 16054.1385 | 16417.0237 | 668 | 3.7334 | 14.5152 | no | no |
| tool_temperature_mean | 3362 | 0.0000 | 28.0182 | 26.6310 | 3.7973 | 14.4198 | 26.2205 | 45.5330 | 26.2215 | 41.4844 | 670 | 2.4644 | 16.2998 | no | no |
| tool_temperature_std | 3362 | 0.0000 | 0.3709 | 0.0412 | 0.9611 | 0.9237 | 0.0000 | 6.1525 | 0.0030 | 4.8180 | 710 | 3.4106 | 14.7531 | no | no |
| tool_temperature_min | 3362 | 0.0000 | 27.3889 | 26.5800 | 3.0662 | 9.4018 | 26.2000 | 44.6300 | 26.2100 | 41.2739 | 213 | 3.4423 | 12.0761 | no | no |
| tool_temperature_max | 3362 | 0.0000 | 28.5249 | 26.7100 | 4.5010 | 20.2591 | 26.2300 | 45.9400 | 26.2300 | 42.7451 | 265 | 2.1593 | 16.5378 | no | no |
| ambient_temperature_mean | 3362 | 0.0000 | 26.5048 | 26.5660 | 0.2457 | 0.0604 | 25.0210 | 27.4910 | 26.0196 | 27.0370 | 497 | -0.1397 | 0.7139 | no | no |
| ambient_temperature_std | 3362 | 0.0000 | 0.0809 | 0.0286 | 0.0980 | 0.0096 | 0.0060 | 0.6865 | 0.0114 | 0.4218 | 580 | 2.1098 | 6.0083 | no | no |
| ambient_temperature_min | 3362 | 0.0000 | 26.3926 | 26.2700 | 0.2308 | 0.0532 | 24.9500 | 27.4700 | 25.7900 | 26.8100 | 45 | -0.5548 | 0.5949 | no | no |
| ambient_temperature_max | 3362 | 0.0000 | 26.6449 | 26.6900 | 0.3075 | 0.0946 | 25.0300 | 27.5300 | 26.1700 | 27.1978 | 55 | 0.0947 | 1.0113 | no | no |
| temperature_delta | 3362 | 0.0000 | 1.5134 | 0.0010 | 3.8583 | 14.8863 | -0.0285 | 20.4980 | -0.0180 | 15.2402 | 539 | 2.4766 | 21.7728 | no | no |
| temperature_rate | 3362 | 0.0000 | -0.0014 | -0.0316 | 2.8850 | 8.3231 | -15.7158 | 18.2105 | -11.0420 | 12.1347 | 392 | 0.4161 | 19.5122 | no | no |

## 6. Correlation Analysis

Pearson correlations are calculated for the complete numerical candidate-feature set. Absolute correlation **≥ 0.90** is used as a candidate redundancy-review threshold, not an automatic feature deletion rule. Pair details and the full matrix are saved in the feature artifacts.

| feature_a | feature_b | correlation |
| --- | --- | --- |
| current_l3_mean | current_mean | 0.9999 |
| current_l2_mean | current_l3_mean | 0.9997 |
| current_l2_mean | current_mean | 0.9996 |
| current_l2_min | current_l3_min | 0.9994 |
| vibration_y_std | vibration_magnitude_std | 0.9994 |
| current_l2_min | current_min | 0.9994 |
| current_l3_min | current_min | 0.9993 |
| current_l1_min | current_min | 0.9993 |
| current_l1_mean | current_mean | 0.9992 |
| current_l1_mean | current_l3_mean | 0.9986 |
| current_l1_min | current_l3_min | 0.9982 |
| tool_temperature_mean | temperature_delta | 0.9981 |
| current_l1_min | current_l2_min | 0.9978 |
| current_l1_mean | current_l2_mean | 0.9978 |
| vibration_magnitude_mean | vibration_rms | 0.9976 |
| vibration_magnitude | vibration_magnitude_mean | 0.9965 |
| vibration_y_mean | vibration_magnitude | 0.9961 |
| current_l2_std | current_std | 0.9953 |
| current_l2_max | current_max | 0.9946 |
| current_l3_std | current_std | 0.9925 |
| vibration_y_mean | vibration_magnitude_mean | 0.9912 |
| current_l1_std | current_std | 0.9904 |
| vibration_magnitude | vibration_rms | 0.9893 |
| current_l1_std | current_l3_std | 0.9887 |
| vibration_y_mean | vibration_rms | 0.9828 |
| current_l2_std | current_l3_std | 0.9825 |
| current_l1_mean | current_imbalance | -0.9824 |
| current_mean | current_imbalance | -0.9824 |
| current_l3_mean | current_imbalance | -0.9820 |
| current_l2_mean | current_imbalance | -0.9816 |

The selection retains interpretable representatives for distinct sensor modalities. Only `vibration_magnitude_std` is dropped when it crosses the review threshold with `vibration_rms`; other high-correlation pairs are reported for review and are not blanket-pruned. Phase-specific statistics remain in the candidate group and are not selected as separate model inputs because aggregate phase features are more compact.

## 7. Selected Features

### Group B — Selected ML features

Selected model inputs (**9**):

`current_mean`, `current_std`, `current_imbalance`, `voltage_mean`, `voltage_imbalance`, `vibration_rms`, `vibration_magnitude_std`, `temperature_delta`, `temperature_rate`

Selection starts from representative electrical, vibration, and temperature features, removes constants/incomplete features, and removes `vibration_magnitude_std` only when redundant with `vibration_rms` at the stated threshold. Correlated features from different modalities are retained when they represent distinct engineering signals.

`current_mean` and `current_imbalance` are strongly inversely correlated in these windows, but are retained as distinct current-level and relative phase-balance descriptors; this relationship should be reviewed again on actual-machine data. `voltage_mean` is flagged near-zero variance because observed voltage is stable, but is retained as the representative voltage-level input rather than discarding that sensor category based only on this historical data. These choices do not imply that either feature is independently predictive.

| feature | std | unique_values | near_zero_variance |
| --- | --- | --- | --- |
| current_mean | 1.2117 | 543 | no |
| current_std | 0.4446 | 663 | no |
| current_imbalance | 21.0055 | 662 | no |
| voltage_mean | 0.0166 | 849 | yes |
| voltage_imbalance | 0.0058 | 1675 | no |
| vibration_magnitude_std | 162.3972 | 668 | no |
| vibration_rms | 57.9513 | 668 | no |
| temperature_delta | 3.8583 | 539 | no |
| temperature_rate | 2.8850 | 392 | no |

Feature removals:

_No rows._

## 8. Metadata

### Group C — Tracking and data-quality metadata

The ML-ready artifact preserves `machine_id`, `session_id`, `session_number`, `window_start`, and `window_end`. Data-quality metadata is also included: `data_completeness`, `valid_sample_count`, `expected_sample_count`, and `window_duration_seconds`. `split` records the chronological assignment. None of these identifiers, timestamps, quality fields, or split values are model inputs.

## 9. Chronological Split

Splits are assigned by entire persisted sessions in start-time order, never by random window sampling. With 6 sessions, the first half (rounded down) is training, the next chronological third boundary defines validation, and the remaining latest sessions are test. For the present dataset this becomes the following exact allocation:

| session_number | session_id | split | start | end |
| --- | --- | --- | --- | --- |
| 1 | 780fc743-2049-492f-a939-f1096faec6ac | train | 2026-11-01T09:03:01+00:00 | 2026-11-01T18:33:13+00:00 |
| 2 | 6545563d-3c6d-488e-b566-f7f572af0a64 | train | 2026-11-03T09:04:10+00:00 | 2026-11-03T18:21:10+00:00 |
| 3 | 06cb38d0-9ec5-4ae3-b51b-b27b1363cf2b | train | 2026-11-04T09:01:15+00:00 | 2026-11-04T18:15:21+00:00 |
| 4 | 01697e8d-16b7-4a3c-9623-fd59b02c62ac | validation | 2026-11-05T09:03:01+00:00 | 2026-11-05T18:33:13+00:00 |
| 5 | 4e0f9da8-1bb7-47eb-b7d6-3a67c3a21926 | test | 2026-11-06T09:04:10+00:00 | 2026-11-06T18:21:10+00:00 |
| 6 | 6eda8b68-6ae8-469c-89b7-f786da110934 | test | 2026-11-07T09:01:15+00:00 | 2026-11-07T18:15:21+00:00 |

Window counts and temporal bounds:

| split | count | first_window | last_window | sessions |
| --- | --- | --- | --- | --- |
| train | 1681 | 2026-11-01T09:03:01+00:00 | 2026-11-04T18:15:12+00:00 | [1, 2, 3] |
| validation | 570 | 2026-11-05T09:03:01+00:00 | 2026-11-05T18:32:58+00:00 | [4] |
| test | 1111 | 2026-11-06T09:04:10+00:00 | 2026-11-07T18:15:12+00:00 | [5, 6] |

Whole-session holdouts avoid overlapping recording histories across splits. Validation/test session counts are shown explicitly above; small session counts limit claims about generalization.

## 10. Leakage Prevention

- Session split assignment occurs before any future model-fitting stage and is applied to all windows from that session.
- Training windows precede validation windows, which precede test windows; split time bounds are checked for strict chronological order and non-overlap.
- Windows are non-overlapping and are built only within one session and one contiguous region.
- Identifiers, timestamps, completeness metadata, and split labels are excluded from the ML feature matrix.
- No learned scaler or other transformation was fitted in this phase. Any later scaler must be fit on training windows only, then applied unchanged to validation/test.

## Scaling and downstream use

No scaling artifact is produced. Tree-based anomaly methods generally do not require feature scaling; distance- or density-based methods are scale-sensitive and should use a documented scaler fitted on training data only. Skewed features and wide sensor range differences should be reviewed before choosing a later model. This phase does not train any model.

## 11. Limitations

- The dataset has no verified supervised fault or health labels.
- Anomaly detection remains exploratory until independently validated against actual machine events.
- Feature selection and variance/correlation observations are based on this historical dataset and may not transfer to the future YCCE lathe.
- No final production health prediction, anomaly score, health status, alert, or machine-failure claim is made.
- Source sensor units, calibration, machine state, maintenance history, and known event annotations remain incomplete.

## Sensor Time-Series Visualizations

The following additional figures are generated from the current November 2026 working data. Raw sensor plots use the persisted PostgreSQL measurements; the derived-feature plot uses the existing 60-second ML-ready windows without recalculating or changing feature values.

- `current_vs_time.png` — measured `current_l1`, `current_l2`, and `current_l3` over time.
- `temperature_vs_time.png` — measured `tool_temperature` and `ambient_temperature` over time.
- `vibration_vs_time.png` — measured `vibration_x`, `vibration_y`, and `vibration_z` over time.
- `voltage_vs_time.png` — measured `voltage_l1`, `voltage_l2`, and `voltage_l3` over time.
- `current_temperature_blocks.png` — current and temperature traces in six separate blocks, one per persisted recording session.
- `derived_features_over_time.png` — the nine selected ML features (`current_mean`, `current_std`, `current_imbalance`, `voltage_mean`, `voltage_imbalance`, `vibration_rms`, `vibration_magnitude_std`, `temperature_delta`, and `temperature_rate`). Each feature has an independent y-axis to avoid misleading comparisons across units and scales.

Generate these figures without running feature selection or rewriting the ML dataset with `python generate_sensor_visualizations.py` from `ml-service/`. The script validates timestamps and session membership before saving.

## Reproducible outputs

Run from the repository root with `python ml-service/feature_engineering.py`, or from `ml-service` with `python feature_engineering.py`. The script reads only PostgreSQL, uses deterministic window and split rules, and overwrites only generated files in `artifacts/features/`, `reports/feature_engineering_report.md`, and `reports/figures/feature_analysis/`.

**Run validation:** `{"candidate_feature_count": 60, "chronological_order": true, "database_connection": true, "duplicate_timestamps": true, "generated_window_count": 3362, "no_cross_gap_windows": true, "no_cross_session_windows": true, "no_identifiers_in_model_inputs": true, "no_missing_or_nonfinite_sensor_inputs": true, "no_scaler_fit": true, "required_sensor_columns_present": true, "selected_feature_count": 9, "selected_features_finite": true, "selected_features_nonconstant": true, "session_isolation": true, "split_bounds": {"test": {"count": 1111, "first_window": "2026-11-06T09:04:10+00:00", "last_window": "2026-11-07T18:15:12+00:00", "sessions": [5, 6]}, "train": {"count": 1681, "first_window": "2026-11-01T09:03:01+00:00", "last_window": "2026-11-04T18:15:12+00:00", "sessions": [1, 2, 3]}, "validation": {"count": 570, "first_window": "2026-11-05T09:03:01+00:00", "last_window": "2026-11-05T18:32:58+00:00", "sessions": [4]}}, "timestamp_ordering": true, "timestamp_parse": true}`

**Generated artifacts:** `{"feature_correlations": "artifacts\\features\\feature_correlations.csv", "feature_quality": "artifacts\\features\\feature_quality.csv", "figures": ["reports\\figures\\feature_analysis\\selected_feature_distributions.png", "reports\\figures\\feature_analysis\\selected_feature_correlation.png", "reports\\figures\\feature_analysis\\selected_feature_variance.png", "reports\\figures\\feature_analysis\\sensor_features_over_time.png", "reports\\figures\\feature_analysis\\window_completeness.png", "reports\\figures\\feature_analysis\\chronological_split.png", "reports\\figures\\feature_analysis\\candidate_window_coverage.png"], "ml_ready_dataset": "artifacts\\features\\ml_ready_features.csv", "session_splits": "artifacts\\features\\session_splits.csv", "window_candidates": "artifacts\\features\\window_candidates.csv"}`
