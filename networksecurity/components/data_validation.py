import os
import sys

import pandas as pd
from scipy.stats import ks_2samp

from networksecurity.constant.training_pipeline import SCHEMA_FILE_PATH
from networksecurity.entity.artifact_entity import DataIngestionArtifact, DataValidationArtifact
from networksecurity.entity.config_entity import DataValidationConfig
from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging
from networksecurity.utils.main_utils.utils import read_yaml_file, write_yaml_file


class DataValidation:
    def __init__(self, data_ingestion_artifact: DataIngestionArtifact,
                 data_validation_config: DataValidationConfig):
        try:
            self.data_ingestion_artifact = data_ingestion_artifact
            self.data_validation_config = data_validation_config
            self._schema_config = read_yaml_file(SCHEMA_FILE_PATH)
        except Exception as e:
            raise NetworkSecurityException(e, sys)

    @staticmethod
    def read_data(file_path) -> pd.DataFrame:
        try:
            return pd.read_csv(file_path)
        except Exception as e:
            raise NetworkSecurityException(e, sys)

    def _expected_columns(self) -> list:
        """Column names declared in data_schema/schema.yaml.

        schema.yaml maps `columns` to a list of single-key {name: dtype} dicts.
        The previous implementation used len(self._schema_config), which counts
        the two top-level keys (columns, numerical_columns), not the 31 feature
        columns, so the check could never pass.
        """
        return [list(entry.keys())[0] for entry in self._schema_config["columns"]]

    def validate_number_of_columns(self, dataframe: pd.DataFrame) -> bool:
        try:
            expected = self._expected_columns()
            logging.info(f"Required number of columns: {len(expected)}")
            logging.info(f"Dataframe has columns: {len(dataframe.columns)}")
            return len(dataframe.columns) == len(expected)
        except Exception as e:
            raise NetworkSecurityException(e, sys)

    def validate_column_names(self, dataframe: pd.DataFrame) -> list:
        """Return the expected column names missing from the dataframe."""
        try:
            expected = self._expected_columns()
            return [c for c in expected if c not in dataframe.columns]
        except Exception as e:
            raise NetworkSecurityException(e, sys)

    def detect_dataset_drift(self, base_df, current_df, threshold=0.05) -> bool:
        """Per-column two-sample KS test.

        Returns True when NO column has drifted (i.e. the data is acceptable),
        False when at least one column's p-value falls below `threshold`.
        The original version had no return statement, so validation_status was
        always None and drift never gated anything.
        """
        try:
            status = True
            report = {}
            for column in base_df.columns:
                d1 = base_df[column]
                d2 = current_df[column]
                is_same_dist = ks_2samp(d1, d2)
                drift_found = is_same_dist.pvalue < threshold
                if drift_found:
                    status = False
                report[column] = {
                    "p_value": float(is_same_dist.pvalue),
                    "drift_status": bool(drift_found),
                }

            drift_report_file_path = self.data_validation_config.drift_report_file_path
            os.makedirs(os.path.dirname(drift_report_file_path), exist_ok=True)
            write_yaml_file(file_path=drift_report_file_path, content=report)

            drifted = [c for c, r in report.items() if r["drift_status"]]
            if drifted:
                logging.warning(f"Drift detected in {len(drifted)} column(s): {drifted}")

            return status
        except Exception as e:
            raise NetworkSecurityException(e, sys)

    def initiate_data_validation(self) -> DataValidationArtifact:
        try:
            train_dataframe = DataValidation.read_data(self.data_ingestion_artifact.trained_file_path)
            test_dataframe = DataValidation.read_data(self.data_ingestion_artifact.test_file_path)

            # Schema check. A failure here is fatal: training on data whose shape
            # does not match the schema produces a silently wrong model.
            for label, df in (("train", train_dataframe), ("test", test_dataframe)):
                if not self.validate_number_of_columns(df):
                    raise ValueError(
                        f"{label} dataframe has {len(df.columns)} columns, "
                        f"schema declares {len(self._expected_columns())}"
                    )
                missing = self.validate_column_names(df)
                if missing:
                    raise ValueError(f"{label} dataframe is missing columns: {missing}")

            drift_status = self.detect_dataset_drift(base_df=train_dataframe, current_df=test_dataframe)

            os.makedirs(os.path.dirname(self.data_validation_config.valid_train_file_path), exist_ok=True)
            train_dataframe.to_csv(self.data_validation_config.valid_train_file_path, index=False, header=True)
            test_dataframe.to_csv(self.data_validation_config.valid_test_file_path, index=False, header=True)

            return DataValidationArtifact(
                validation_status=drift_status,
                valid_train_file_path=self.data_validation_config.valid_train_file_path,
                valid_test_file_path=self.data_validation_config.valid_test_file_path,
                invalid_train_file_path=None,
                invalid_test_file_path=None,
                drift_report_file_path=self.data_validation_config.drift_report_file_path,
            )
        except Exception as e:
            raise NetworkSecurityException(e, sys)
