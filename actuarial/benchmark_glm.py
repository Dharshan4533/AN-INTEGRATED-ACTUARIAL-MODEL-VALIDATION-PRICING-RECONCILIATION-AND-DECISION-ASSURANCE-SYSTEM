import time
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import train_test_split

print("Testing training speed and convergence...")
df = pd.read_csv("data/raw/freMTPL2freq.csv")
print(f"Loaded {len(df)} rows.")

# Preprocessing
df["LogDensity"] = np.log(df["Density"])
df["Exposure_capped"] = np.clip(df["Exposure"], 0.001, 1.0)
df["LogExposure"] = np.log(df["Exposure_capped"])
df["ClaimNb_capped"] = np.clip(df["ClaimNb"], 0, 4)

features_num = ["VehPower", "VehAge", "DrivAge", "BonusMalus", "LogDensity"]
features_cat = ["Area", "VehBrand", "VehGas", "Region"]

# One-hot encoding
df_encoded = pd.get_dummies(df[features_cat], drop_first=True, dtype=float)
X = pd.concat([df[features_num], df_encoded], axis=1)
X = sm.add_constant(X)
y = df["ClaimNb_capped"]
offset = df["LogExposure"]

print(f"Feature matrix shape: {X.shape}")

# Subsample test of 100k
idx_sub = np.random.RandomState(42).choice(len(df), size=100000, replace=False)
X_sub = X.iloc[idx_sub]
y_sub = y.iloc[idx_sub]
offset_sub = offset.iloc[idx_sub]

t0 = time.time()
model_sm = sm.GLM(y_sub, X_sub, family=sm.families.Poisson(), offset=offset_sub)
res_sm = model_sm.fit()
t1 = time.time()
print(f"Statsmodels 100k fit time: {t1 - t0:.2f}s, AIC: {res_sm.aic:.2f}")

# Full dataset test
t0 = time.time()
model_full = sm.GLM(y, X, family=sm.families.Poisson(), offset=offset)
res_full = model_full.fit()
t1 = time.time()
print(f"Statsmodels FULL (678k) fit time: {t1 - t0:.2f}s, AIC: {res_full.aic:.2f}")
