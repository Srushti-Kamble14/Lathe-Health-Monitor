# ML Target & Anomaly Strategy

> Preliminary, label-free analysis of the supplied CNC lathe CSV only. The original source file is read-only. No RPM is used, no health label is created, and no production model or deployment threshold is selected.

## Dataset Sessions

Timestamps were reconstructed from `time` (`%d-%m-%y`) and `time.1` (`%I:%M:%S %p`), then sorted chronologically. The median within-run cadence is 3 seconds. A new recording session is defined when the gap exceeds **30 seconds** (ten nominal intervals), separating material pauses rather than treating a date as a session.

| session_id | start | end | duration | duration_minutes | records | median_interval_seconds |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | 2020-02-22 09:03:01 | 2020-02-22 18:33:13 | 0 days 09:30:12 | 570.20 | 11405 | 3.00 |
| S02 | 2020-02-24 09:04:10 | 2020-02-24 18:21:10 | 0 days 09:17:00 | 557.00 | 11141 | 3.00 |
| S03 | 2020-02-25 09:01:15 | 2020-02-25 18:15:21 | 0 days 09:14:06 | 554.10 | 11083 | 3.00 |
| S04 | 2020-02-26 09:03:01 | 2020-02-26 18:33:13 | 0 days 09:30:12 | 570.20 | 11405 | 3.00 |
| S05 | 2020-02-27 09:04:10 | 2020-02-27 18:21:10 | 0 days 09:17:00 | 557.00 | 11141 | 3.00 |
| S06 | 2020-02-28 09:01:15 | 2020-02-28 18:15:21 | 0 days 09:14:06 | 554.10 | 11083 | 3.00 |

Inter-session gaps:

| new_session_start | preceding_gap_seconds |
| --- | --- |
| 2020-02-24 09:04:10 | 138657.0 |
| 2020-02-25 09:01:15 | 52805.0 |
| 2020-02-26 09:03:01 | 53260.0 |
| 2020-02-27 09:04:10 | 52257.0 |
| 2020-02-28 09:01:15 | 52805.0 |

This produced **6 sessions**. These are recording sessions, not verified machine shifts, operations, or tool lives.

## Operating Regimes

RPM is excluded. Sensor activity was explored using 60-second non-overlapping summaries and the following neutral clustering procedure: Three-cluster K-means on standardized 60-second block medians for mean current, cross-phase current standard deviation, vibration RMS, and tool temperature. Voltage medians and phase spread are reported as context, not used to force a cluster if they provide little variation.

| cluster_id | blocks | records | sessions | current_median | current_p90 | voltage_median | voltage_std_median | vibration_rms_median | tool_temp_median | regime | S01 | S02 | S03 | S04 | S05 | S06 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2942 | 58738 | 6 | 0.240 | 0.247 | 231.720 | 0.094 | 16154.446 | 26.600 | Regime A | 9865 | 9821 | 9683 | 9865 | 9821 | 9683 |
| 1 | 130 | 2600 | 6 | 4.405 | 4.570 | 231.722 | 0.096 | 16315.722 | 38.440 | Regime B | 620 | 240 | 440 | 620 | 240 | 440 |
| 2 | 296 | 5920 | 6 | 4.534 | 4.598 | 231.720 | 0.095 | 16168.841 | 37.758 | Regime C | 920 | 1080 | 960 | 920 | 1080 | 960 |

The cluster names are neutral, descriptive partitions only. K-means always returns three clusters here; it does not prove three physical machine states. Cluster differences and session counts should be reviewed alongside the plots. No `idle`, `machining`, or `high-load` semantic label is assigned because no independent state annotation is supplied. Voltage channels have narrow, nearly unchanged observed ranges in Phase 0.1; the cluster table shows whether voltage spread separates any of these groups.

The ordered block sequence changes cluster 208 times within sessions. A cluster transition is a change in standardized sensor signature, not a verified machine-state transition.

## Derived Features

All features are calculated in-memory and aligned to the sorted raw rows; the CSV columns and file are not modified.

- `mean_current`: row arithmetic mean of `c1`, `c2`, `c3`.
- `current_std`: population standard deviation (`ddof=0`) across the three current phases per row.
- `current_imbalance`: maximum absolute phase deviation from `mean_current`, divided by `abs(mean_current)`, × 100; undefined for zero mean.
- `mean_voltage`, `voltage_std`, `voltage_imbalance`: analogous calculations for `v1`, `v2`, `v3`.
- `vibration_magnitude`: `sqrt(accx² + accy² + accz²)` on the recorded raw axes.
- `vibration_rms`, `vibration_std`, `vibration_peak`, `vibration_peak_to_peak`, `crest_factor`: trailing window of up to **60 records** (nominally 3 minutes), including the current record; windows reset at each recording session; early windows use available records. RMS and standard deviation are calculated on the magnitude series; crest factor = window peak / window RMS.
- `tool_temp`, `ambient_temp`: source values.
- `tool_temp_rate`: within-session backward temperature difference per actual elapsed minute; no rate is calculated across a session boundary.
- `temperature_difference`: `tool_temp - ambient_temp`.
- For plots/regimes, these features are summarized into non-overlapping **20-record (nominally 60-second) blocks**. Partial final blocks are retained and their record counts reported.

| model_feature | present_in_derived_frame |
| --- | --- |
| mean_current | True |
| current_std | True |
| current_imbalance | True |
| mean_voltage | True |
| voltage_std | True |
| voltage_imbalance | True |
| vibration_rms | True |
| vibration_std | True |
| vibration_peak | True |
| vibration_peak_to_peak | True |
| crest_factor | True |
| tool_temp | True |
| ambient_temp | True |
| tool_temp_rate | True |
| temperature_difference | True |

Complete feature rows: **67,252/67,258**. The first row in each session has no tool-temperature rate; the model/scoring paths omit rows missing any selected feature rather than imputing across time gaps.

## Temporal Behavior

The block plots expose repeatable intraday electrical and temperature patterns and long low-current intervals mixed with elevated-current intervals. Voltage is comparatively narrow in range. These are sensor patterns only; the CSV contains no operation annotation to verify machining state. Similar shapes recur on recording days, so repetition can reflect the acquisition schedule or replayed daily process and is not independent proof of machine health.

The figures use 60-second block aggregates for legibility; they preserve the chronology and do not resample or alter the source file.

- `figures/target_analysis/derived_features_over_time.png`
- `figures/target_analysis/neutral_operating_regimes.png`
- `figures/target_analysis/baseline_stability_candidates.png`
- `figures/target_analysis/candidate_anomaly_scores.png`
- `figures/target_analysis/current_and_temperature_blocks.png`

## Candidate Anomalies

No observations are called faults. Two preliminary screens were run with session-aware chronology:

1. **Trailing robust rolling z-score:** for each model feature, compare the current value to the previous up to 60 records in the same session, requiring at least 20 prior points. Center is the prior rolling median; scale is prior IQR / 1.349. Zero-IQR cases produce no z-score rather than an infinite score. Points with any feature at |z| ≥ 3.5 are review candidates, not fault labels.
2. **Isolation Forest:** 2,251 one-minute-spaced records from earlier sessions fit the exploratory model; 1,111 one-minute-spaced records from the final held-out sessions are scored. A `RobustScaler` is fit on training sessions only. Isolation Forest uses 200 trees, a fixed random seed for reproducibility, and `contamination='auto'`; its output here is a continuous ranking score, not the model's binary prediction.

The Isolation Forest held-out score quantiles are: median **0.36720**, 90th **0.57644**, 95th **0.60850**, 99th **0.64338**. Lower method-specific scores are not automatically better; this implementation negates `score_samples`, so larger scores indicate more isolated points.

Top held-out Isolation Forest ranked candidate anomalies (ranking only):

| timestamp | session_id | iforest_anomaly_score | rolling_max_abs_z | rolling_max_abs_z_feature |
| --- | --- | --- | --- | --- |
| 2020-02-28 10:39:15 | S06 | 0.6838 | 2.5175 | tool_temp_rate |
| 2020-02-28 10:40:15 | S06 | 0.6746 | 1.3490 | vibration_peak |
| 2020-02-28 10:38:15 | S06 | 0.6701 | 1.6177 | current_std |
| 2020-02-27 16:44:10 | S05 | 0.6682 | 142.5052 | current_imbalance |
| 2020-02-27 14:15:10 | S05 | 0.6578 | 4.3598 | current_std |
| 2020-02-28 14:51:15 | S06 | 0.6549 | 1.6744 | temperature_difference |
| 2020-02-28 16:39:15 | S06 | 0.6516 | 3.2360 | crest_factor |
| 2020-02-28 14:53:15 | S06 | 0.6476 | 2.5634 | vibration_std |
| 2020-02-28 17:54:15 | S06 | 0.6473 | 4.7740 | crest_factor |
| 2020-02-28 14:52:15 | S06 | 0.6440 | 1.8047 | current_imbalance |
| 2020-02-28 17:52:15 | S06 | 0.6437 | 1.4833 | vibration_rms |
| 2020-02-27 17:38:10 | S05 | 0.6435 | 4.1343 | tool_temp |

Top held-out rolling robust-z candidates:

| timestamp | session_id | iforest_anomaly_score | rolling_max_abs_z | rolling_max_abs_z_feature |
| --- | --- | --- | --- | --- |
| 2020-02-28 17:31:18 | S06 |  | 3410.7468 | vibration_peak_to_peak |
| 2020-02-28 14:10:12 | S06 |  | 1622.5118 | vibration_peak |
| 2020-02-28 15:25:18 | S06 |  | 1081.8980 | temperature_difference |
| 2020-02-28 10:07:57 | S06 |  | 1045.4750 | temperature_difference |
| 2020-02-28 10:08:00 | S06 |  | 1039.4045 | temperature_difference |
| 2020-02-28 10:07:54 | S06 |  | 1037.3810 | temperature_difference |
| 2020-02-28 10:07:51 | S06 |  | 1024.5655 | temperature_difference |
| 2020-02-28 10:07:48 | S06 |  | 995.5620 | temperature_difference |
| 2020-02-28 10:08:03 | S06 |  | 917.3200 | temperature_difference |
| 2020-02-28 15:25:21 | S06 |  | 911.4743 | temperature_difference |
| 2020-02-28 15:25:15 | S06 | 0.6203 | 881.3467 | temperature_difference |
| 2020-02-27 18:11:19 | S05 |  | 868.7160 | vibration_peak |

Held-out records crossing the exploratory |z| ≥ 3.5 screen by feature:

| feature | heldout_points_over_3_5 |
| --- | --- |
| crest_factor | 4105 |
| ambient_temp | 3344 |
| tool_temp_rate | 3116 |
| tool_temp | 3103 |
| temperature_difference | 2278 |
| vibration_peak_to_peak | 2100 |
| mean_current | 1803 |
| current_imbalance | 1423 |
| current_std | 1120 |
| vibration_rms | 1105 |
| vibration_std | 986 |
| vibration_peak | 690 |
| mean_voltage | 11 |
| voltage_imbalance | 4 |
| voltage_std | 2 |

Scores may reflect normal transitions, mixed operating states, sensor offsets, day-to-day repetition, or measurement artifacts. There are no labels with which to estimate precision, recall, false alarm rate, or mechanical-failure validity. No candidate is confirmed as a failure.

Very large rolling robust-z values can result when a feature has a small but nonzero prior IQR (including quantized or nearly constant readings); magnitudes are not comparable across features and should be treated as ranking prompts only. The chronological holdout also is not independent machine validation: similar daily patterns recur in both earlier and later sessions.

## Baseline Analysis

The data were divided into complete, non-overlapping **30-minute (600-record)** windows within each session; incomplete trailing windows were excluded from baseline ranking. For mean current, mean voltage, vibration RMS, and tool temperature, each window's coefficient of variation (CV = within-window sample standard deviation / absolute window median × 100) was calculated. A relative stability score is the median of each CV divided by that feature's median CV across windows; lower ranks indicate comparatively stable observed sensor distributions, not “healthy” operation.

Most stable windows by this descriptive criterion:

| session_id | start | end | records | current_cv_pct | voltage_cv_pct | vibration_cv_pct | tool_temp_cv_pct | relative_stability_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S02 | 2020-02-24 13:34:10 | 2020-02-24 14:04:07 | 600 | 26.5981 | 0.0323 | 0.0360 | 0.7416 | 0.1932 |
| S05 | 2020-02-27 13:34:10 | 2020-02-27 14:04:07 | 600 | 26.5981 | 0.0323 | 0.0360 | 0.7416 | 0.1932 |
| S06 | 2020-02-28 12:01:15 | 2020-02-28 12:31:12 | 600 | 27.0835 | 0.0320 | 0.0355 | 0.9412 | 0.1973 |
| S03 | 2020-02-25 12:01:15 | 2020-02-25 12:31:12 | 600 | 27.0835 | 0.0320 | 0.0355 | 0.9412 | 0.1973 |
| S04 | 2020-02-26 12:33:01 | 2020-02-26 13:02:58 | 600 | 28.7964 | 0.0321 | 0.0354 | 0.9663 | 0.1978 |

These are **sensor-stability candidates only**, not a defensible healthy baseline: the dataset has no verified healthy/abnormal state, tool/maintenance history, process annotations, or unit/calibration documentation. The windows are chosen by a relative ranking over the same dataset and cannot establish normality. Anomaly detection against them would require YCCE operators and labelled baseline collection to validate.

## Health/Fault Label Investigation

- Label-like header candidates: none.
- Accompanying dataset-directory documentation: no documentation files in the supplied dataset directory.
- The CSV has no verified tool-condition, tool-wear, fault, failure, maintenance, degradation, or health-state target. The one populated unnamed export field has no documented meaning and is not considered a label.

**NO VERIFIED SUPERVISED HEALTH LABEL**

## Classification Feasibility

**Healthy/faulty classification is not justified.** A classifier requires trusted labels for machine/tool health at the observation time, representative examples of each state, and an evaluation split independent by time/run. None of those target labels or event records are supplied. High current, temperature, or vibration cannot be relabeled as “fault”.

## Regression Feasibility

Predicting a future tool temperature from past sensor values is technically possible as a forecasting exercise, but it does not predict tool health or maintenance need and there is no ground-truth wear target. Reconstructing contemporaneous temperature from other same-time sensors would be a sensor-estimation task and risks leakage, not predictive maintenance. Regression is therefore not recommended as the initial project ML objective.

## Anomaly Detection Feasibility

Unlabeled deviation ranking is supported as **exploratory anomaly methodology/pipeline development** because the file contains a long, ordered sensor series with repeated 3-second samples and several sensor domains. The methods above provide reproducible candidate scores under a chronological session holdout. They do **not** show that scores represent machine faults, nor establish a healthy baseline, operational threshold, or transfer to a different lathe. The dataset's repeated daily patterns, sensor offsets, unknown units, mixed unidentified regimes, and only six sessions materially limit inference.

## RUL Feasibility

**Remaining useful life (RUL) is not supportable.** RUL requires asset/tool identity, observed run-to-failure or censoring timelines, failure/maintenance events, and operating exposure. None is available, so no RUL target can be defined or validated.

## Recommended ML Objective

Start with **offline, unlabeled sensor-anomaly score experimentation**, then validate it against future YCCE baseline and reviewed event data. Do not frame the result as fault detection or predictive maintenance until independently validated. This is a pipeline/method objective, not a trained production model.

## Input Features

Use the following exact derived values for the preliminary anomaly experiment:

| feature |
| --- |
| mean_current |
| current_std |
| current_imbalance |
| mean_voltage |
| voltage_std |
| voltage_imbalance |
| vibration_rms |
| vibration_std |
| vibration_peak |
| vibration_peak_to_peak |
| crest_factor |
| tool_temp |
| ambient_temp |
| tool_temp_rate |
| temperature_difference |

Timestamps and `session_id` are for ordering, session boundaries, and chronological evaluation only; they are not model predictors. **RPM is excluded.** Transformations/scaling must be fitted on training-only historical data. Existing raw phase/axis channels remain untouched in the CSV; this first feature experiment uses the summaries above, not every raw channel as an additional duplicate input.

## Expected Output

For each scored timestamp/block, eventual system output could include:

```text
anomaly_score
anomaly_status
```

`anomaly_score` is a continuous, model-specific ranking value. `anomaly_status` (for example `NORMAL`, `WARNING`, `ANOMALY`) is **not assigned in this phase**. Until labels and validation exist, report scores/candidates for human review only; do not present them as health states.

## Threshold Strategy

Do not choose a deployment threshold from this public dataset's arbitrary score percentile or from `contamination`. Collect a representative verified-normal YCCE baseline across machine states, shifts, tools, and loads; freeze model and preprocessing; score separate chronological runs; review candidate alerts with operators; link alerts to verified abnormal events and benign transitions; quantify false alerts per operating hour and event sensitivity. Select thresholds against an agreed operational false-alarm/recall cost, then validate on a later untouched period. Recalibrate only under documented change control. Until then, thresholds are exploratory review filters only.

## Public Dataset vs YCCE Lathe

**Public dataset:** historical recorded CNC-lathe measurements with names matching project channels; useful for parsing, feature engineering, plots, and anomaly-method experimentation.

**Actual YCCE lathe:** future live readings from PT100 + MAX31865, ADXL355/ADXL345, and a 3-phase energy meter over RS-485 Modbus. These hardware readings, units, sampling/aggregation, mounting/orientation, calibration, filtering, and operational patterns can differ from this CSV.

That mismatch is **domain shift**: a model may flag ordinary YCCE values as novel or miss a real event because sensor scales, offsets, bandwidth, placement, machine, process, and regime distributions differ. Public-data scores are not evidence of YCCE model performance. Calibrate/validate using real YCCE data before operational use; never transfer score thresholds unchanged.

## Real-World Data Collection Requirements

Collect synchronized records keyed by machine and session, with:

- Timestamp with timezone/clock-sync and clear sampling or aggregation interval.
- Tool temperature from PT100/MAX31865; ambient temperature if available.
- Calibrated vibration X/Y/Z from ADXL355/ADXL345, with sensor identity, units, orientation/mounting, sample rate, filtering, and window aggregation.
- Three-phase current and voltage via RS-485 Modbus meter, including meter/register mapping, units, phase identity, and whether values are RMS/instantaneous.
- Machine operating state and operation/load context, recorded independently of model output.
- Tool identity, tool replacement events, inspection/tool-wear measurements where available.
- Maintenance events, known abnormal events, onset/clear times, operator confirmation, and known benign events.
- Operator notes when possible, plus workpiece/material, job, shift, and sensor/calibration changes where obtainable.

Do **not** add RPM unless project scope is explicitly changed. Preserve raw synchronized observations and provenance so later labels can be audited and time-aware splits can be made.

## Final Decision

1. **What ML problem are we implementing first?** Offline exploratory **unlabeled anomaly detection**; not production fault classification.
2. **Why?** The dataset contains chronological multichannel sensor readings but no verified health/fault/wear target. Anomaly scores can be explored without inventing labels, though their operational meaning is unproven.
3. **What exact input features will be used?** `mean_current`, `current_std`, `current_imbalance`, `mean_voltage`, `voltage_std`, `voltage_imbalance`, `vibration_rms`, `vibration_std`, `vibration_peak`, `vibration_peak_to_peak`, `crest_factor`, `tool_temp`, `ambient_temp`, `tool_temp_rate`, `temperature_difference`. Time/session fields are split metadata only; no RPM.
4. **What will the model output?** A continuous `anomaly_score` for human review. No `anomaly_status` or health/fault label will be emitted until threshold calibration and independent validation.
5. **What information is still missing?** Sensor units/calibration and acquisition semantics, verified operating states, machine/tool/workpiece identity, healthy baseline coverage, confirmed abnormal/fault labels, wear measurements, and maintenance/failure timelines.
6. **What data must eventually come from the real YCCE lathe?** Timestamped tool/ambient temperature, X/Y/Z vibration, three-phase current/voltage, independently recorded operating states, maintenance and abnormal events, tool replacement/condition, and operator notes, with sensor metadata and synchronization. Validate across later YCCE runs before claiming predictive-maintenance capability.
