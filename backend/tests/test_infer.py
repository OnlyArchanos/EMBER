"""
Tests for app/ml/infer.py.

Each test is isolated from the real artifact on disk and from other tests'
module-level state by resetting infer._artifact and patching infer._ARTIFACT_PATH
via monkeypatch.

Coverage:
  - load_model: missing artifact file → FileNotFoundError
  - load_model: artifact missing a required key → KeyError
  - load_model: artifact with wrong feature_columns order → KeyError (order-sensitive)
  - score_persistent_source: called before load_model → RuntimeError
"""

import pathlib
import pickle
import datetime

import pytest

import app.ml.infer as infer
from app.ml.features import FEATURE_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_artifact(overrides: dict | None = None) -> dict:
    """Build a minimal valid artifact dict, optionally overriding keys."""
    # A real sklearn object is not needed for load_model() tests — the key
    # validation and feature_columns check happen before the model is ever used.
    base = {
        "model": object(),          # placeholder; never called in these tests
        "score_min": 0.1,
        "score_max": 0.9,
        "feature_columns": list(FEATURE_COLUMNS),
    }
    if overrides:
        base.update(overrides)
    return base


def _write_artifact(path: pathlib.Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(artifact, f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_artifact_cache(monkeypatch):
    """
    Reset infer._artifact to None before every test so load_model() always
    starts from a clean state regardless of test execution order.
    """
    monkeypatch.setattr(infer, "_artifact", None)


# ---------------------------------------------------------------------------
# load_model tests
# ---------------------------------------------------------------------------

def test_load_model_missing_file_raises_file_not_found(monkeypatch, tmp_path):
    """load_model() raises FileNotFoundError when the artifact file doesn't exist."""
    nonexistent = tmp_path / "does_not_exist.pkl"
    monkeypatch.setattr(infer, "_ARTIFACT_PATH", nonexistent)

    with pytest.raises(FileNotFoundError, match="Model artifact not found"):
        infer.load_model()


def test_load_model_missing_required_key_raises_key_error(monkeypatch, tmp_path):
    """
    load_model() raises KeyError when a required artifact key is absent.
    Tests the 'score_max' key specifically — exercises the required_key loop
    for a key that exists in the new artifact shape but was absent in older artifacts.
    """
    artifact_path = tmp_path / "isolation_forest.pkl"
    # score_max deliberately omitted to simulate a stale artifact.
    stale_artifact = {
        "model": object(),
        "score_min": 0.1,
        # "score_max" missing
        "feature_columns": list(FEATURE_COLUMNS),
    }
    _write_artifact(artifact_path, stale_artifact)
    monkeypatch.setattr(infer, "_ARTIFACT_PATH", artifact_path)

    with pytest.raises(KeyError, match="missing key 'score_max'"):
        infer.load_model()


def test_load_model_missing_feature_columns_key_raises_key_error(monkeypatch, tmp_path):
    """
    load_model() raises KeyError when 'feature_columns' is absent.
    This is the pre-Phase-4-addition artifact shape — confirmed caught by the loop.
    """
    artifact_path = tmp_path / "isolation_forest.pkl"
    old_artifact = {
        "model": object(),
        "score_min": 0.1,
        "score_max": 0.9,
        # "feature_columns" missing — artifact predates the Phase 4 addition
    }
    _write_artifact(artifact_path, old_artifact)
    monkeypatch.setattr(infer, "_ARTIFACT_PATH", artifact_path)

    with pytest.raises(KeyError, match="missing key 'feature_columns'"):
        infer.load_model()


def test_load_model_wrong_feature_columns_order_raises_key_error(monkeypatch, tmp_path):
    """
    load_model() raises KeyError when feature_columns is present but the order
    doesn't match the current FEATURE_COLUMNS.

    This is the order-sensitivity test: the artifact has the same elements as
    FEATURE_COLUMNS but in a different order.  A set-based check would pass;
    the list equality check must not.
    """
    artifact_path = tmp_path / "isolation_forest.pkl"
    # Reverse the column order — same elements, wrong sequence.
    reordered = list(reversed(FEATURE_COLUMNS))
    assert sorted(reordered) == sorted(FEATURE_COLUMNS), (
        "Test precondition: reordered must contain the same elements as FEATURE_COLUMNS"
    )
    assert reordered != FEATURE_COLUMNS, (
        "Test precondition: reversed FEATURE_COLUMNS must differ from the original "
        "(only possible if FEATURE_COLUMNS has >1 element and is not a palindrome)"
    )

    _write_artifact(artifact_path, _make_artifact({"feature_columns": reordered}))
    monkeypatch.setattr(infer, "_ARTIFACT_PATH", artifact_path)

    with pytest.raises(KeyError, match="does not match"):
        infer.load_model()


def test_load_model_wrong_feature_columns_subset_raises_key_error(monkeypatch, tmp_path):
    """
    load_model() raises KeyError when feature_columns is a strict subset of
    FEATURE_COLUMNS (same order for the elements present, but one is missing).
    """
    artifact_path = tmp_path / "isolation_forest.pkl"
    subset = list(FEATURE_COLUMNS)[:-1]   # drop the last column
    _write_artifact(artifact_path, _make_artifact({"feature_columns": subset}))
    monkeypatch.setattr(infer, "_ARTIFACT_PATH", artifact_path)

    with pytest.raises(KeyError, match="does not match"):
        infer.load_model()


# ---------------------------------------------------------------------------
# score_persistent_source tests
# ---------------------------------------------------------------------------

def test_score_persistent_source_before_load_model_raises_runtime_error():
    """
    score_persistent_source() raises RuntimeError when _artifact is None
    (i.e., load_model() has not been called).

    The autouse fixture ensures _artifact is None at the start of this test.
    No file I/O or model needed — the guard fires before any feature computation.
    """
    with pytest.raises(RuntimeError, match="Inference model is not loaded"):
        infer.score_persistent_source(
            ps=None,       # never reached; guard fires first
            members=[],
            gdf_zones=None,
        )
