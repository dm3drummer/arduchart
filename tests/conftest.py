"""Shared fixtures for arducharts tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Minimal pdef.json data used by schema and schema_map tests
# ---------------------------------------------------------------------------

MINI_PDEF: dict = {
    "ARSPD_": {
        "ARSPD_TYPE": {
            "DisplayName": "Airspeed Type",
            "Description": "Airspeed sensor type",
            "Values": {"0": "None", "1": "Analog", "2": "MS4525"},
            "Range": {"low": "0", "high": "100"},
            "User": "Standard",
        },
        "ARSPD_USE": {
            "DisplayName": "Airspeed Use",
            "Description": "Use airspeed for control",
            "Values": {"0": "Disabled", "1": "Enabled"},
        },
    },
    "BATT_": {
        "BATT_MONITOR": {
            "DisplayName": "Battery Monitor",
            "Description": "Battery monitoring type",
            "Range": {"low": "0", "high": "50"},
            "Units": "V",
            "Increment": "1",
            "RebootRequired": "True",
        },
        "BATT_CAPACITY": {
            "DisplayName": "Battery Capacity",
            "Description": "Battery capacity in mAh",
            "Range": {"low": "0", "high": "1000000"},
            "Units": "mAh",
        },
    },
    "SIM_": {
        "SIM_SPEEDUP": {"DisplayName": "Sim speedup"},
    },
    "INS": {
        "INS_ENABLE": {
            "DisplayName": "IMU Enable",
            "Description": "Enable the IMU",
            "Values": {"0": "Disabled", "1": "Enabled"},
        },
    },
}


def _flatten_pdef(raw: dict) -> dict:
    """Flatten grouped pdef into a single param->definition dict."""
    flat: dict = {}
    for params in raw.values():
        if isinstance(params, dict):
            for name, defn in params.items():
                if isinstance(defn, dict):
                    flat[name] = defn
    return flat


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


@pytest.fixture()
def pdef_cache_dir(tmp_path: Path) -> Path:
    """Create a minimal .cache with pdef.json and flat cache."""
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    (cache_dir / "apm.pdef.json").write_text(json.dumps(MINI_PDEF))
    (cache_dir / "apm.pdef.flat.json").write_text(json.dumps(_flatten_pdef(MINI_PDEF)))
    return tmp_path


@pytest.fixture()
def mini_config_dir(tmp_path: Path) -> Path:
    """Build a small but complete config directory tree for testing.

    Charts:
        alpha  – no deps, no base, params {PARAM_A: 1, PARAM_B: 2}
        beta   – depends on alpha, params {PARAM_C: 10, PARAM_A: 99} (overlap)
        gamma  – bundle: depends [alpha, beta], no own params
        delta  – has base: [myschema], params {PARAM_A: 1, PARAM_B: 2}

    Schema:
        myschema – schema_params [PARAM_A, PARAM_B, PARAM_D, PARAM_E]

    Planes:
        test_plane – charts [alpha, beta], values override, extra_params
        test_plane2 – charts [alpha] only (for diff-planes tests)

    """
    # -- charts/alpha --
    _write_yaml(tmp_path / "charts" / "alpha" / "Chart.yaml", {
        "name": "alpha", "description": "Alpha chart", "version": "1.0",
    })
    _write_yaml(tmp_path / "charts" / "alpha" / "defaults.yaml", {
        "params": {"PARAM_A": 1, "PARAM_B": 2},
    })

    # -- charts/beta (depends on alpha, overlaps PARAM_A) --
    _write_yaml(tmp_path / "charts" / "beta" / "Chart.yaml", {
        "name": "beta", "description": "Beta chart", "version": "1.0",
        "depends": ["alpha"],
    })
    _write_yaml(tmp_path / "charts" / "beta" / "defaults.yaml", {
        "params": {"PARAM_C": 10, "PARAM_A": 99},
    })

    # -- charts/gamma (bundle) --
    _write_yaml(tmp_path / "charts" / "gamma" / "Chart.yaml", {
        "name": "gamma", "description": "Bundle chart", "version": "1.0",
        "depends": ["alpha", "beta"],
    })
    _write_yaml(tmp_path / "charts" / "gamma" / "defaults.yaml", {
        "params": {},
    })

    # -- charts/delta (has base) --
    _write_yaml(tmp_path / "charts" / "delta" / "Chart.yaml", {
        "name": "delta", "description": "Delta chart", "version": "1.0",
        "base": ["myschema"],
    })
    _write_yaml(tmp_path / "charts" / "delta" / "defaults.yaml", {
        "params": {"PARAM_A": 1, "PARAM_B": 2},
    })

    # -- schema/myschema --
    _write_yaml(tmp_path / "schema" / "myschema" / "Chart.yaml", {
        "name": "myschema",
        "description": "Test schema",
        "version": "schema",
        "schema_params": ["PARAM_A", "PARAM_B", "PARAM_D", "PARAM_E"],
    })

    # -- planes/test_plane --
    _write_yaml(tmp_path / "planes" / "test_plane.yaml", {
        "name": "Test Plane",
        "description": "A test plane config",
        "charts": ["alpha", "beta"],
        "values": {"beta": {"PARAM_C": 20}},
        "extra_params": {"PARAM_X": 42},
    })

    # -- planes/test_plane2 (just alpha) --
    _write_yaml(tmp_path / "planes" / "test_plane2.yaml", {
        "name": "Test Plane 2",
        "description": "Second test plane",
        "charts": ["alpha"],
    })

    # -- .cache (minimal pdef for validate/show) --
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    (cache_dir / "apm.pdef.json").write_text(json.dumps(MINI_PDEF))
    (cache_dir / "apm.pdef.flat.json").write_text(json.dumps(_flatten_pdef(MINI_PDEF)))

    return tmp_path


@pytest.fixture()
def sample_param_file(tmp_path: Path) -> Path:
    """Create a .param file with a few entries."""
    path = tmp_path / "sample.param"
    path.write_text(
        "# header comment\n"
        "PARAM_A,1\n"
        "PARAM_B,2.500000\n"
        "PARAM_C,10\n"
    )
    return path
