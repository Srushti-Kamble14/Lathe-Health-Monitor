# Anomaly Detection Report
## 1. Objective
This analysis applies unsupervised anomaly detection to the existing Phase 3 ML-ready windows because the dataset does not contain verified health/fault labels. The goal is to estimate normal operating behavior from the training data and identify windows with unusually high score relative to the learned baseline.
## 2. Dataset
The model uses the persisted Phase 3 artifact `artifacts/features/ml_ready_features.csv`, which already contains the approved 9-feature windows with the chronological session split. The dataset was not re-engineered or relabeled.
## 3. Feature Set
The approved feature set is exactly: current_mean, current_std, current_imbalance, voltage_mean, voltage_imbalance, vibration_rms, vibration_magnitude_std, temperature_delta, temperature_rate.
## 4. Data Split
- Train: sessions 1-3
- Validation: session 4
- Test: sessions 5-6
## 5. Models
- Isolation Forest: ensemble-based anomaly detector trained only on the TRAIN split.
- One-Class SVM: fits a radial-basis support model on TRAIN after a train-only StandardScaler.
- Robust statistical baseline: median/MAD score created from TRAIN robust deviations.
## 6. Preprocessing
For One-Class SVM, the scaler is fitted only on the training set and applied to validation/test windows. Isolation Forest is fit on the raw training features because scaling is not required for the algorithm and the feature set is already numerically comparable. The anomaly score direction is standardized so that higher values are more anomalous.
## 7. Threshold Method
The final thresholds for the selected model are derived from the TRAIN split only. The warning threshold is the 95th percentile of the training anomaly score distribution, and the anomaly threshold is the 99th percentile. Scores below the warning threshold are NORMAL, scores between warning and anomaly are WARNING, and scores at or above the anomaly threshold are ANOMALOUS.
## 8. Results
### Selected model: IsolationForest
- Warning threshold: 0.6200
- Anomaly threshold: 0.6558

| Model | Split | Normal | Warning | Anomalous | Mean score | Max score |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| IsolationForest | train | 1596 | 68 | 17 | 0.4017 | 0.6853 |
| IsolationForest | validation | 544 | 22 | 4 | 0.4047 | 0.6753 |
| IsolationForest | test | 1052 | 46 | 13 | 0.4001 | 0.6853 |
| OneClassSVM | train | 1596 | 68 | 17 | -0.1137 | 0.0005 |
| OneClassSVM | validation | 542 | 21 | 7 | -0.1114 | 0.0005 |
| OneClassSVM | test | 1054 | 47 | 10 | -0.1149 | 0.0004 |
| RobustBaseline | train | 1596 | 68 | 17 | 515.8607 | 6917.1938 |
| RobustBaseline | validation | 559 | 11 | 0 | 464.8747 | 4527.6674 |
| RobustBaseline | test | 1037 | 57 | 17 | 542.0192 | 6917.1938 |

## 9. Quantitative Temporal Analysis

The selected IsolationForest results cover 3,362 windows. There are 136 WARNING windows (4.05%) and 34 ANOMALOUS windows (1.01%). These are model-generated statuses, not verified machine-health labels.

An anomalous sequence is defined as anomalous windows exactly 60 seconds apart within the same session. Under this definition, there are 30 sequences: 26 single-window sequences and 4 multi-window sequences. The longest sequence is 2 windows. Anomalies are therefore predominantly isolated rather than persistent in this dataset. This pattern does not prove that the machine is healthy.

## 10. Session-Level Analysis

| Session | Anomalous windows |
| --- | ---: |
| Session 1 | 4 |
| Session 2 | 5 |
| Session 3 | 8 |
| Session 4 | 4 |
| Session 5 | 5 |
| Session 6 | 8 |

All six sessions contain anomalous windows. These counts describe the detector's outputs only and do not establish that any session represents a machine fault.

## 11. Model Comparison and Selection

The existing model-comparison table above reports descriptive score and status summaries for each split. Overall, IsolationForest identifies 34 anomalous windows, OneClassSVM identifies 34, and RobustBaseline identifies 34. Their distributions differ across validation and test (including 4/13, 7/10, and 0/17 anomalous windows, respectively), and their score scales differ, so raw score magnitudes are not directly comparable.

No ground-truth fault labels are available to determine which model is more accurate. The comparison is therefore descriptive and is not used to claim predictive superiority.

IsolationForest is used as the selected exploratory anomaly detector for Phase 4 based on the predefined model preference order. Because the dataset has no verified fault labels, the model comparison is descriptive rather than an accuracy-based model selection exercise.

## 12. Feature-Level Anomaly Characterization

The `feature_anomaly_analysis.png` figure displays standardized feature profiles for the 12 highest-scoring windows. Its z-scores are relative to that plotted window set; the figure is a descriptive view, not a feature-importance measure or a comparison against a verified healthy baseline. Feature-level anomaly characterization is descriptive and does not establish causal fault attribution.

## 13. Limitations

- The dataset has no verified health/fault labels.
- An anomaly is not a confirmed machine fault.
- Anomaly detection identifies unusual operating behavior; it does not diagnose a fault.
- Model comparison is descriptive, not an accuracy-based evaluation.
- This is exploratory anomaly detection.
- Additional real-world validation is required before operational predictive-maintenance decisions.

## 14. Phase 4 Conclusion

The Phase 4 pipeline applies the predefined exploratory IsolationForest detector to the existing Phase 3 windows and reports TRAIN-derived NORMAL/WARNING/ANOMALOUS statuses. In these results, 34 windows are anomalous, predominantly as isolated events under the stated sequence definition. Without verified fault labels and additional real-world validation, these outputs should be treated as candidates for investigation—not as evidence of machine health, confirmed faults, or operational predictive-maintenance capability.
