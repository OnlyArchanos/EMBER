"""
Offline training script for the ML anomaly-detection model.

Run once after historical data has been seeded (python -m app.ml.train from
the backend/ directory, or via scripts/ wrapper once that exists).  Never
runs as part of a live request — inference only (RULES.md §3).

Produces a model artifact at app/ml/artifacts/isolation_forest.pkl that
infer.py loads at startup.  Retraining replaces the artifact in place.
The artifact is a dict containing the fitted model plus the min-max
normalization bounds computed from the training set, so infer.py always uses
bounds from the current fit (never hardcoded values).
"""

import datetime
import logging
import pathlib
import pickle

import geopandas as gpd
import numpy as np
from shapely import wkt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.ml.features import (
    FEATURE_COLUMNS,
    NO_ZONES_SENTINEL,
    compute_features,
    compute_features_batch,
    normalize_score,
)
from app.ml.known_sites_fixture import (
    FIXTURE_DETECTION_COUNT,
    build_site_fixture,
    load_known_sites,
)
from app.models import FireDetection, PersistentSource, Zone

logger = logging.getLogger(__name__)

ARTIFACT_DIR = pathlib.Path(__file__).parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "isolation_forest.pkl"

# Tunable thresholds — named constants so they are easy to find and adjust
# after the validation run has produced real data (RULES.md §5).

# IsolationForest contamination parameter.
# "auto" applies sklearn's fixed offset of -0.5 to the raw score_samples()
# output when computing decision_function(), making the decision boundary
# independent of the training set's own anomaly rate.  This is the right
# default before the real contamination rate has been measured from labelled
# data — an explicit float (e.g. 0.05) would be a guess with no calibration
# basis yet.
CONTAMINATION: str = "auto"

# After normalization, a known-industrial site scoring above this value means
# the freshly-trained model would incorrectly flag a site we already know is
# explained.  Training raises a loud error rather than saving that artifact.
VALIDATION_ANOMALY_THRESHOLD: float = 0.5

# Minimum number of real PersistentSource rows (with members) required before
# fitting.  Below this the training matrix is too sparse for IsolationForest's
# path-length distribution to be meaningful.  Starting value: 10.
# Named constant so it is easy to find and adjust once real data accumulates.
MIN_TRAINING_SAMPLES: int = 10

# Fixed base date for the ML validation hook — ensures the known-sites score
# report is reproducible across retraining runs on the same data.
# validate_known_sites.py uses today's date instead (so the cluster reads as
# "active" against the current ENDED_THRESHOLD_DAYS window).
_VALIDATION_BASE_DATE: datetime.date = datetime.date(2025, 1, 1)


def _build_zone_gdf(db: Session) -> gpd.GeoDataFrame:
    """Load all Zone rows and return a GeoDataFrame projected to EPSG:7755."""
    zones = db.scalars(select(Zone)).all()
    if not zones:
        raise RuntimeError(
            "No Zone rows found in the database.  Run zone fetching "
            "(osm_client.py) before training."
        )
    records = [
        {"zone_type": z.zone_type, "geometry": wkt.loads(z.geometry)}
        for z in zones
    ]
    return gpd.GeoDataFrame(records, crs="EPSG:4326").to_crs("EPSG:7755")


def _load_sources_with_members(
    db: Session,
) -> list[tuple[PersistentSource, list[FireDetection]]]:
    """
    Return all PersistentSources (any status) paired with their member
    FireDetection rows.  Sources with no members are skipped with a warning —
    this indicates a data integrity issue worth noting but not worth aborting
    training over, since the affected source simply won't be in the matrix.
    """
    sources = db.scalars(select(PersistentSource)).all()
    result: list[tuple[PersistentSource, list[FireDetection]]] = []
    for ps in sources:
        members = list(
            db.scalars(
                select(FireDetection).where(FireDetection.cluster_id == ps.id)
            ).all()
        )
        if not members:
            logger.warning(
                "PersistentSource id=%d has no member detections; skipping.", ps.id
            )
            continue
        result.append((ps, members))
    return result


def _build_normalization_bounds(
    model, X: "pd.DataFrame"  # type: ignore[name-defined]
) -> tuple[float, float]:
    """
    Compute the min-max bounds of the negated score_samples output over X.

    We negate because IsolationForest.score_samples() returns lower (more
    negative) values for anomalies, so -score_samples() gives higher values
    for anomalies.  Bounds are used by infer.py to map any raw score into
    [0, 1] relative to the training distribution.

    Returns (neg_min, neg_max) where neg_min corresponds to the least
    anomalous point seen during training and neg_max to the most anomalous.
    """
    raw_scores = model.score_samples(X[FEATURE_COLUMNS])
    neg_scores = -raw_scores
    return float(np.min(neg_scores)), float(np.max(neg_scores))


def _run_validation_hook(
    model,
    score_min: float,
    score_max: float,
    gdf_zones: gpd.GeoDataFrame,
) -> None:
    """
    Score each known-industrial-site fixture entry with the freshly-fitted model.

    Synthetic objects are built via build_site_fixture() from
    app.ml.known_sites_fixture — the same function validate_known_sites.py uses
    so the two callers cannot produce divergent fixture data.

    Raises RuntimeError if any site scores above VALIDATION_ANOMALY_THRESHOLD
    after normalization.  The artifact is never written if this raises.

    gdf_zones is passed in from train_model() so features use the same zone
    data as the training matrix.
    """
    import pandas as pd  # local import — not needed at module level

    sites = load_known_sites()
    failures: list[str] = []

    for i, site in enumerate(sites):
        ps, members = build_site_fixture(
            site, base_date=_VALIDATION_BASE_DATE, site_id=i + 1
        )

        feature_dict = compute_features(ps, members, gdf_zones)
        X_site = pd.DataFrame([feature_dict])[FEATURE_COLUMNS]

        raw_score = float(model.score_samples(X_site)[0])
        neg_score = -raw_score

        # Apply the same normalization that infer.py will use at serve time.
        # Delegates to normalize_score() in features.py — one implementation, two call sites.
        normalized = normalize_score(neg_score, score_min, score_max)

        logger.info(
            "Validation: %s → raw=%.4f  neg=%.4f  normalized=%.4f",
            site["name"], raw_score, neg_score, normalized,
        )

        if normalized > VALIDATION_ANOMALY_THRESHOLD:
            failures.append(
                f"  {site['name']} (lat={site['lat']}, lon={site['lon']}): "
                f"normalized score {normalized:.4f} > threshold {VALIDATION_ANOMALY_THRESHOLD}"
            )

    if failures:
        raise RuntimeError(
            f"Post-fit validation failed: {len(failures)} known industrial "
            f"site(s) scored above the anomaly threshold ({VALIDATION_ANOMALY_THRESHOLD}).\n"
            "The model would incorrectly flag sites that are already known to be explained.\n"
            "Do NOT use this artifact.  Investigate the training data before retraining.\n\n"
            "Failing sites:\n" + "\n".join(failures)
        )

    logger.info(
        "Post-fit validation passed: all %d known industrial sites scored "
        "<= %.2f after normalization.",
        len(sites),
        VALIDATION_ANOMALY_THRESHOLD,
    )


def train_model(db: Session) -> None:
    """
    Build the feature matrix, fit an IsolationForest, compute normalization
    bounds, run the known-sites validation hook, and save the artifact.

    Raises on any data quality problem or validation failure rather than
    silently saving an artifact that is known to be wrong.

    The saved artifact is a dict:
        {
            "model":           fitted IsolationForest,
            "score_min":       float — neg_score of the least-anomalous training point,
            "score_max":       float — neg_score of the most-anomalous training point,
            "feature_columns": list[str] — FEATURE_COLUMNS at training time,
        }
    infer.py asserts that its current FEATURE_COLUMNS matches the stored list
    at load time, catching any future silent reorder before it corrupts scores.
    It then unpacks the normalization bounds and applies the same transform so
    anomaly_score is always in [0, 1] relative to the distribution seen during training.
    """
    from sklearn.ensemble import IsolationForest  # local import — CPU-only, lightweight
    import pandas as pd

    gdf_zones = _build_zone_gdf(db)
    sources_with_members = _load_sources_with_members(db)

    n_sources = len(sources_with_members)
    if n_sources == 0:
        raise RuntimeError(
            "No PersistentSource rows with member detections found in the database.  "
            "The analysis pipeline has not been run yet.  "
            "Next steps: (1) run scripts/fetch_historical.py to ingest fire detections, "
            "(2) run the classifier, persistence, and flagging services to produce "
            "PersistentSource rows, (3) run osm_client.py to populate Zone rows, "
            "then re-run train.py."
        )
    if n_sources < MIN_TRAINING_SAMPLES:
        raise RuntimeError(
            f"Only {n_sources} PersistentSource row(s) with members found; "
            f"training requires at least {MIN_TRAINING_SAMPLES} (MIN_TRAINING_SAMPLES).  "
            "The pipeline has run but produced too few persistent sources.  "
            "Fetch more historical data (scripts/fetch_historical.py covers a wider "
            "date range) and re-run the analysis pipeline, then retry train.py."
        )

    X = compute_features_batch(sources_with_members, gdf_zones)

    # Pre-fit sentinel guard: reject any training matrix that contains the
    # no-zones sentinel value.  nearest_zone_distance_m == NO_ZONES_SENTINEL
    # means zone data was absent when features were computed — a real pipeline
    # problem that must surface loudly rather than be silently trained through.
    # In correct operation this count is always zero: zones exist in the DB
    # well before the first PersistentSource is created.
    sentinel_count = int((X["nearest_zone_distance_m"] == NO_ZONES_SENTINEL).sum())
    if sentinel_count > 0:
        raise RuntimeError(
            f"{sentinel_count} row(s) in the training matrix have "
            f"nearest_zone_distance_m == {NO_ZONES_SENTINEL} (the no-zones "
            "sentinel).  Zone data was absent when features were computed.  "
            "Re-run zone fetching (osm_client.py) and recompute features before "
            "retraining."
        )

    logger.info(
        "Training IsolationForest on %d samples, %d features: %s",
        len(X),
        len(FEATURE_COLUMNS),
        FEATURE_COLUMNS,
    )

    model = IsolationForest(contamination=CONTAMINATION, random_state=42)
    model.fit(X[FEATURE_COLUMNS])

    # Compute normalization bounds over the training set's own score distribution.
    # Bounds are stored in the artifact so infer.py always uses the bounds from
    # the current fit — a retrain on a different distribution updates them
    # automatically without any hardcoded values.
    score_min, score_max = _build_normalization_bounds(model, X)
    logger.info(
        "Score normalization bounds (negated): min=%.4f  max=%.4f  "
        "(span=%.4f; higher neg_score = more anomalous)",
        score_min, score_max, score_max - score_min,
    )

    if score_max == score_min:
        logger.warning(
            "All training samples produced identical scores (span=0).  "
            "The training set may be too small or too homogeneous to produce "
            "a meaningful model.  Normalization will clamp all scores to 0.5."
        )

    # Run the post-fit validation hook before saving the artifact.
    # Raises RuntimeError if any known industrial site scores above the threshold.
    _run_validation_hook(model, score_min, score_max, gdf_zones)

    # Validation passed — save the artifact.
    artifact = {
        "model": model,
        "score_min": score_min,
        "score_max": score_max,
        # Stored so infer.py can assert column order at load time — a future
        # reorder of FEATURE_COLUMNS would silently corrupt scores without this.
        "feature_columns": list(FEATURE_COLUMNS),
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(artifact, f)

    logger.info(
        "Artifact saved to %s  (model + normalization bounds score_min=%.4f, score_max=%.4f).",
        MODEL_PATH, score_min, score_max,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        train_model(db)
    finally:
        db.close()
