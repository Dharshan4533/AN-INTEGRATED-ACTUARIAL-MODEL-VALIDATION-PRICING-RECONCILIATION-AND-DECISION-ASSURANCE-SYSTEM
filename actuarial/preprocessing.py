"""
Actuarial Data Preprocessing and Feature Engineering Module.
Ensures identical transformations between model training and real-time inference.
"""

import json
import os
import joblib
import numpy as np
import pandas as pd


CATEGORICAL_FEATURES = ["Area", "VehBrand", "VehGas", "Region"]
NUMERICAL_FEATURES = ["VehPower", "VehAge", "DrivAge", "BonusMalus"]

# Explicit categories defined by the freMTPL2 dataset
VALID_CATEGORIES = {
    "Area": ["A", "B", "C", "D", "E", "F"],
    "VehPower": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "VehBrand": ["B1", "B2", "B3", "B4", "B5", "B6", "B10", "B11", "B12", "B13", "B14"],
    "VehGas": ["Regular", "Diesel"],
    "Region": [
        "R11", "R21", "R22", "R23", "R24", "R25", "R26",
        "R31", "R41", "R42", "R43", "R52", "R53", "R54",
        "R72", "R73", "R74", "R82", "R83", "R91", "R93", "R94"
    ]
}

FEATURE_RANGES = {
    "VehPower": {"min": 4, "max": 15, "default": 6},
    "VehAge": {"min": 0, "max": 100, "default": 6},
    "DrivAge": {"min": 18, "max": 100, "default": 45},
    "BonusMalus": {"min": 50, "max": 230, "default": 50},
    "Density": {"min": 1.0, "max": 30000.0, "default": 500.0},
    "Exposure": {"min": 0.01, "max": 2.0, "default": 1.0}
}


class ActuarialPreprocessor:
    def __init__(self):
        self.feature_columns = None
        self.fitted = False

    def fit(self, df: pd.DataFrame):
        """Fit preprocessor design matrix columns from training dataframe."""
        X_trans = self._create_design_matrix(df, is_training=True)
        self.feature_columns = list(X_trans.columns)
        self.fitted = True
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform input dataframe into design matrix with exact training columns."""
        if not self.fitted and self.feature_columns is None:
            raise ValueError("Preprocessor must be fitted or feature columns loaded before transform.")
        return self._create_design_matrix(df, is_training=False)

    def _create_design_matrix(self, df: pd.DataFrame, is_training: bool = False) -> pd.DataFrame:
        df_work = df.reset_index(drop=True).copy()

        # Input cleaning & clipping to valid actuarial boundaries
        df_work["VehPower"] = pd.to_numeric(df_work["VehPower"], errors="coerce").fillna(6).clip(4, 15)
        df_work["VehAge"] = pd.to_numeric(df_work["VehAge"], errors="coerce").fillna(6).clip(0, 100)
        df_work["DrivAge"] = pd.to_numeric(df_work["DrivAge"], errors="coerce").fillna(45).clip(18, 100)
        df_work["BonusMalus"] = pd.to_numeric(df_work["BonusMalus"], errors="coerce").fillna(50).clip(50, 230)
        
        # Log density transformation
        density = pd.to_numeric(df_work["Density"], errors="coerce").fillna(500.0).clip(lower=1.0)
        df_work["LogDensity"] = np.log(density)

        # Baseline continuous features
        X_num = df_work[["VehPower", "VehAge", "DrivAge", "BonusMalus", "LogDensity"]]

        # Categorical one-hot encoding
        cat_dfs = []
        for cat_col in CATEGORICAL_FEATURES:
            # Ensure categorical type with all possible valid categories to preserve column alignment
            cats = VALID_CATEGORIES[cat_col]
            s = df_work[cat_col].astype(str)
            # Replace unseen categories with modal/default category
            s = s.where(s.isin(cats), cats[0])
            s_cat = pd.Series(pd.Categorical(s, categories=cats), index=df_work.index)
            dummies = pd.get_dummies(s_cat, prefix=cat_col, drop_first=True, dtype=float)
            cat_dfs.append(dummies)

        X_design = pd.concat([X_num] + cat_dfs, axis=1)

        # Add constant term (intercept) for statsmodels GLM
        X_design.insert(0, "const", 1.0)

        if not is_training and self.feature_columns is not None:
            # Reindex to ensure identical column ordering and fill any missing dummy with 0.0
            X_design = X_design.reindex(columns=self.feature_columns, fill_value=0.0)

        return X_design

    def transform_single(self, policy_dict: dict) -> pd.DataFrame:
        """Transform a single policy dictionary into a 1-row DataFrame design matrix."""
        df = pd.DataFrame([policy_dict])
        return self.transform(df)

    def save(self, filepath: str):
        """Save preprocessor state."""
        state = {
            "feature_columns": self.feature_columns,
            "fitted": self.fitted,
            "valid_categories": VALID_CATEGORIES,
            "feature_ranges": FEATURE_RANGES
        }
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(state, filepath)
        
        # Also save as human-readable json schema
        json_path = os.path.splitext(filepath)[0] + "_schema.json"
        with open(json_path, "w") as f:
            json.dump({
                "feature_columns": self.feature_columns,
                "n_features": len(self.feature_columns) if self.feature_columns else 0,
                "valid_categories": VALID_CATEGORIES,
                "feature_ranges": FEATURE_RANGES
            }, f, indent=2)

    @classmethod
    def load(cls, filepath: str):
        """Load preprocessor from state file."""
        state = joblib.load(filepath)
        preprocessor = cls()
        preprocessor.feature_columns = state["feature_columns"]
        preprocessor.fitted = state["fitted"]
        return preprocessor
