"""Tests for arducharts.schema_map — chart family mapping and pdef grouping."""

from __future__ import annotations

import json
from pathlib import Path

from arducharts.schema_map import (
    PDEF_GROUP_TO_FAMILY,
    SCHEMA_CHART_MAP,
    build_schema_charts_data,
)


# -- SCHEMA_CHART_MAP --


class TestSchemaChartMap:
    def test_map_is_not_empty(self):
        assert len(SCHEMA_CHART_MAP) > 0

    def test_all_values_are_lists_of_strings(self):
        for family, prefixes in SCHEMA_CHART_MAP.items():
            assert isinstance(prefixes, list), f"{family} value is not a list"
            for prefix in prefixes:
                assert isinstance(prefix, str), f"{family} has non-string prefix: {prefix}"

    def test_no_duplicate_prefixes_across_families(self):
        seen: dict[str, str] = {}
        for family, prefixes in SCHEMA_CHART_MAP.items():
            for prefix in prefixes:
                assert prefix not in seen, (
                    f"Prefix '{prefix}' in both '{seen[prefix]}' and '{family}'"
                )
                seen[prefix] = family

    def test_known_families_exist(self):
        for family in ["airspeed", "battery", "gps", "servo", "ekf", "rc"]:
            assert family in SCHEMA_CHART_MAP


# -- PDEF_GROUP_TO_FAMILY --


class TestPdefGroupToFamily:
    def test_reverse_map_is_not_empty(self):
        assert len(PDEF_GROUP_TO_FAMILY) > 0

    def test_known_mapping(self):
        assert PDEF_GROUP_TO_FAMILY["ARSPD_"] == "airspeed"
        assert PDEF_GROUP_TO_FAMILY["BATT_"] == "battery"
        assert PDEF_GROUP_TO_FAMILY["SERVO1_"] == "servo"

    def test_all_prefixes_mapped(self):
        for family, prefixes in SCHEMA_CHART_MAP.items():
            for prefix in prefixes:
                assert prefix in PDEF_GROUP_TO_FAMILY
                assert PDEF_GROUP_TO_FAMILY[prefix] == family


# -- build_schema_charts_data --


class TestBuildSchemaChartsData:
    def test_basic_grouping(self, pdef_cache_dir: Path):
        families = build_schema_charts_data(pdef_cache_dir)
        assert "airspeed" in families
        assert "ARSPD_TYPE" in families["airspeed"]
        assert "ARSPD_USE" in families["airspeed"]

    def test_battery_family(self, pdef_cache_dir: Path):
        families = build_schema_charts_data(pdef_cache_dir)
        assert "battery" in families
        assert "BATT_MONITOR" in families["battery"]

    def test_sim_groups_excluded(self, pdef_cache_dir: Path):
        families = build_schema_charts_data(pdef_cache_dir)
        for family, params in families.items():
            for param in params:
                assert not param.startswith("SIM_"), (
                    f"SIM param '{param}' found in family '{family}'"
                )

    def test_unmapped_group_goes_to_unmapped(self, pdef_cache_dir: Path):
        # INS group (not INS_ with underscore) is in SCHEMA_CHART_MAP under imu,
        # so let's add a truly unmapped group to the pdef
        cache = pdef_cache_dir / ".cache" / "apm.pdef.json"
        raw = json.loads(cache.read_text())
        raw["ZZTEST_"] = {"ZZTEST_PARAM": {"DisplayName": "Test"}}
        cache.write_text(json.dumps(raw))

        families = build_schema_charts_data(pdef_cache_dir)
        assert "_unmapped" in families
        assert "ZZTEST_PARAM" in families["_unmapped"]

    def test_params_sorted(self, pdef_cache_dir: Path):
        families = build_schema_charts_data(pdef_cache_dir)
        for family, params in families.items():
            assert params == sorted(params), f"Family '{family}' params not sorted"

    def test_missing_cache_raises(self, tmp_path: Path):
        import pytest
        with pytest.raises(FileNotFoundError, match="Param schema not found"):
            build_schema_charts_data(tmp_path)
