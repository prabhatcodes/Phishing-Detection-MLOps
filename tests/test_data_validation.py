"""Regression tests for the data-validation stage.

Both of these cover bugs that shipped: detect_dataset_drift had no return
statement (validation_status was always None), and validate_number_of_columns
compared against len(schema_dict) == 2 instead of the 31 declared columns.
"""
import numpy as np
import pytest

from networksecurity.components.data_validation import DataValidation
from networksecurity.entity.artifact_entity import DataIngestionArtifact
from networksecurity.entity.config_entity import DataValidationConfig, TrainingPipelineConfig


@pytest.fixture
def validator(tmp_path):
    cfg = TrainingPipelineConfig()
    cfg.artifact_dir = str(tmp_path / "Artifacts")
    return DataValidation(
        data_ingestion_artifact=DataIngestionArtifact("unused", "unused"),
        data_validation_config=DataValidationConfig(cfg),
    )


def test_schema_declares_31_columns(validator):
    assert len(validator._expected_columns()) == 31


def test_column_count_check_passes_on_real_data(validator, raw_df):
    assert validator.validate_number_of_columns(raw_df) is True


def test_column_count_check_fails_when_a_column_is_dropped(validator, raw_df):
    assert validator.validate_number_of_columns(raw_df.drop(columns=raw_df.columns[0])) is False


def test_missing_column_names_are_reported(validator, raw_df):
    missing = validator.validate_column_names(raw_df.drop(columns=["URL_Length"]))
    assert missing == ["URL_Length"]


def test_no_drift_between_two_random_halves_of_the_same_data(validator, raw_df):
    # Note: a *sequential* split of this CSV does report drift in ~9 columns,
    # because the file is ordered. That is a property of the file, not of the
    # detector, and it is why ingestion shuffles (train_test_split with a fixed
    # random_state) before the train/test files are written.
    shuffled = raw_df.sample(frac=1.0, random_state=42).reset_index(drop=True)
    half = len(shuffled) // 2
    status = validator.detect_dataset_drift(shuffled.iloc[:half], shuffled.iloc[half:])
    assert status is True, "randomly split halves should not report drift"


def test_drift_is_detected_on_a_shifted_distribution(validator, raw_df):
    shifted = raw_df.copy()
    rng = np.random.default_rng(0)
    # Flip most of one feature's values: a distribution the KS test must reject.
    shifted["URL_Length"] = rng.choice([1], size=len(shifted))
    status = validator.detect_dataset_drift(raw_df, shifted)
    assert status is False, "a shifted column must set validation_status to False"


def test_drift_report_is_written(validator, raw_df):
    validator.detect_dataset_drift(raw_df.iloc[:100], raw_df.iloc[100:200])
    import os
    assert os.path.exists(validator.data_validation_config.drift_report_file_path)
