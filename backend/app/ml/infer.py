"""
Single-source ML inference for the anomaly-detection model.

load_model() is called once at application startup.  score_persistent_source()
is called synchronously in the live request path by flagging.py — both feature
extraction and model scoring must be fast (CPU-only, no network I/O, RULES.md §5).

Feature extraction always delegates to compute_features() from features.py —
there is no independent feature implementation here (RULES.md §5).

The loaded artifact is a dict produced by train.py:
    {"model": IsolationForest, "score_min": float, "score_max": float,
     "feature_columns": list[str]}
where score_min and score_max are the negated-score bounds over the training
set.  Normalization uses these bounds so the output is always in [0, 1]
relative to the distribution seen during training, regardless of what raw
score values the current fit happened to produce.
feature_columns is asserted to match the current FEATURE_COLUMNS at load
time so a future column reorder is caught immediately rather than silently
corrupting scores.
"""

import logging
import pathlib
import pickle
from typing import Optional

import geopandas as gpd
import pandas as pd

from app.ml.features import FEATURE_COLUMNS, compute_features, normalize_score
from app.models import FireDetection, PersistentSource

logger = logging.getLogger(__name__)

_ARTIFACT_PATH = pathlib.Path(__file__).parent / "artifacts" / "isolation_forest.pkl"

# Module-level cache populated by load_model().
# Stored as the raw artifact dict so score_min/score_max are always
# co-located with the model they were computed from.
_artifact: Optional[dict] = None


def load_model() -> None:
    """
    Load the trained model artifact from disk into the module cache.

    The artifact is a dict produced by train.py:
        {"model": IsolationForest, "score_min": float, "score_max": float,
         "feature_columns": list[str]}

    Call once at application startup (e.g., from app/main.py's lifespan
    handler).  Safe to call multiple times; each call reloads from disk.

    Raises:
        FileNotFoundError: if the artifact file doesn't exist.
        KeyError: if the artifact is missing expected keys (e.g., produced by
            an older version of train.py that didn't store normalization bounds).
    """
    global _artifact
    if not _ARTIFACT_PATH.exists():
        raise FileNotFoundError(
            f"Model artifact not found at {_ARTIFACT_PATH}.  "
            "Run app/ml/train.py to train and save the model before starting the server."
        )
    with open(_ARTIFACT_PATH, "rb") as f:
        loaded = pickle.load(f)

    # Validate artifact structure so a stale artifact from before normalization
    # was added produces a clear error rather than a mysterious AttributeError.
    for required_key in ("model", "score_min", "score_max", "feature_columns"):
        if required_key not in loaded:
            raise KeyError(
                f"Artifact at {_ARTIFACT_PATH} is missing key '{required_key}'.  "
                "Retrain the model with the current train.py to regenerate a "
                "complete artifact."
            )

    # Order-sensitive equality: list equality preserves column order, so a
    # reorder that set-equality would miss is caught here.  No sorting, no set
    # conversion — the check only passes if the list is identical element-by-element.
    if loaded["feature_columns"] != FEATURE_COLUMNS:
        raise KeyError(
            f"Artifact feature_columns {loaded['feature_columns']} does not match "
            f"the current FEATURE_COLUMNS {FEATURE_COLUMNS}.  "
            "FEATURE_COLUMNS was reordered or changed after this artifact was trained.  "
            "Retrain the model with train.py to produce a matching artifact."
        )

    _artifact = loaded
    logger.info(
        "Model artifact loaded from %s  "
        "(score_min=%.4f, score_max=%.4f).",
        _ARTIFACT_PATH,
        _artifact["score_min"],
        _artifact["score_max"],
    )


def score_persistent_source(
    ps: PersistentSource,
    members: list[FireDetection],
    gdf_zones: Optional[gpd.GeoDataFrame],
) -> float:
    """
    Compute the normalized anomaly score for a single PersistentSource.

    Returns a float in [0, 1] where higher values indicate a more anomalous
    (unexplained) source, calibrated to the training distribution via the
    min-max bounds stored in the artifact.  Scores are clipped to [0, 1] so a
    point that falls outside the training distribution range never produces an
    out-of-range value.

    Feature extraction delegates entirely to compute_features() from features.py
    — this function adds no feature logic of its own (RULES.md §5).

    Raises:
        RuntimeError: if load_model() has not been called.
        ValueError:   propagated from compute_features() if members is empty or
                      gdf_zones is in a geographic CRS.
    """
    if _artifact is None:
        raise RuntimeError(
            "Inference model is not loaded.  "
            "Call infer.load_model() at application startup before scoring."
        )

    feature_dict = compute_features(ps, members, gdf_zones)

    # Build a one-row DataFrame with columns in FEATURE_COLUMNS order.
    # nearest_zone_type is excluded automatically by the column slice.
    X: pd.DataFrame = pd.DataFrame([feature_dict])[FEATURE_COLUMNS]

    model = _artifact["model"]
    score_min: float = _artifact["score_min"]
    score_max: float = _artifact["score_max"]

    # IsolationForest.score_samples() returns lower (more negative) values for
    # anomalies.  Negate and normalize using bounds from the current artifact.
    # Delegates to normalize_score() in features.py — same function train.py's
    # validation hook uses; one normalization implementation, two call sites.
    raw_score = float(model.score_samples(X)[0])
    return normalize_score(-raw_score, score_min, score_max)
