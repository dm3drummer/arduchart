"""Shared utilities and constants for arducharts."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

import yaml


PDEF_URL = "https://autotest.ardupilot.org/Parameters/ArduPlane/apm.pdef.json"
DEFAULT_BAUD = 115200

SENSOR_BITS = {
    0x01: "Gyro",
    0x02: "Accel",
    0x04: "Mag",
    0x08: "Baro",
    0x10: "Diff Pressure",
    0x20: "GPS",
    0x40: "Optical Flow",
    0x100: "RC Receiver",
    0x1000: "Airspeed",
    0x4000: "Battery",
    0x10000: "Pre-arm check",
    0x2000000: "Logging",
}


def norm_value(v: Any) -> int | float | Any:
    """Normalize a parameter value for ArduPilot.

    - bool -> int (YAML true/false -> 1/0)
    - whole floats -> int (1.0 -> 1)
    - NaN/Inf -> left as float
    """
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        try:
            iv = int(v)
            if v == iv:
                return iv
        except (ValueError, OverflowError):
            pass  # NaN, Inf
    return v


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse '4.5.2' or '4.5.2-rc1' into a comparable tuple (4, 5, 2)."""
    parts = re.split(r"[.\-]", str(version_str).strip())
    return tuple(int(p) for p in parts if p.isdigit())


def version_less_than(version_a: str, version_b: str) -> bool:
    """Return True if version_a < version_b (zero-padded comparison)."""
    tuple_a = parse_version(version_a)
    tuple_b = parse_version(version_b)
    pad_len = max(len(tuple_a), len(tuple_b))
    padded_a = tuple_a + (0,) * (pad_len - len(tuple_a))
    padded_b = tuple_b + (0,) * (pad_len - len(tuple_b))
    return padded_a < padded_b


def compute_param_diff(
    desired: dict[str, Any], current: dict[str, Any]
) -> tuple[list[tuple[str, Any, Any]], list[tuple[str, Any]], int]:
    """Compare desired params against current.

    Returns:
        (changes, missing, matching_count) where:
        - changes: [(key, current_val, desired_val), ...]
        - missing: [(key, desired_val), ...]
        - matching_count: number of identical params
    """
    changes: list[tuple[str, Any, Any]] = []
    missing: list[tuple[str, Any]] = []
    matching = 0
    for key, desired_val in desired.items():
        if key in current:
            cur = norm_value(current[key])
            des = norm_value(desired_val)
            if cur != des:
                changes.append((key, cur, des))
            else:
                matching += 1
        else:
            missing.append((key, desired_val))
    return changes, missing, matching


# ---------------------------------------------------------------------------
# Lint helpers (shared between CLI and TUI)
# ---------------------------------------------------------------------------


def lint_plane_config(
    compositor: Any,
    config_path: Path,
    result: dict[str, Any],
) -> list[str]:
    """Run lint checks on a plane config. Returns a list of warning strings."""
    plane_config = compositor.load_yaml(config_path)
    warnings: list[str] = []
    installed = set(result["installed"])

    # Check: values reference installed charts
    values = plane_config.get("values", {})
    for chart_name in values:
        if chart_name not in installed:
            warnings.append(f"values.{chart_name}: chart is not installed")

    # Check: value overrides actually in chart defaults
    for chart_name, overrides in values.items():
        if not isinstance(overrides, dict):
            continue
        defaults_yaml = compositor.charts_dir / chart_name / "defaults.yaml"
        if defaults_yaml.exists():
            defaults = compositor.load_yaml(defaults_yaml)
            chart_param_names = set(defaults.get("params", {}).keys())
            for param in overrides:
                if param not in chart_param_names:
                    warnings.append(
                        f"values.{chart_name}.{param}: not in chart defaults "
                        f"(new param, not an override)"
                    )

    # Check: same param set by multiple chart defaults
    param_sources: dict[str, list[str]] = {}
    for chart_name in result["installed"]:
        defaults_yaml = compositor.charts_dir / chart_name / "defaults.yaml"
        if defaults_yaml.exists():
            defaults = compositor.load_yaml(defaults_yaml)
            for param in defaults.get("params", {}):
                param_sources.setdefault(param, []).append(chart_name)
    for param, charts in param_sources.items():
        if len(charts) > 1:
            warnings.append(
                f"{param}: set in multiple charts: {', '.join(charts)} (last wins)"
            )

    # Check: chart params match declared base schema
    base_warnings = compositor.validate_chart_bases()
    warnings.extend(base_warnings)

    return warnings


# ---------------------------------------------------------------------------
# Schema update (shared between CLI and TUI)
# ---------------------------------------------------------------------------


def rebuild_schema_charts(
    config_dir: Path,
    families: dict[str, list[str]],
) -> tuple[int, int]:
    """Rebuild schema chart catalog from family data.

    Returns (created, updated) counts.
    """
    charts_dir = config_dir / "schema"
    created = 0
    updated = 0

    for family, params in sorted(families.items()):
        if family == "_unmapped":
            continue

        chart_dir = charts_dir / family
        chart_yaml_path = chart_dir / "Chart.yaml"

        if chart_dir.exists() and chart_yaml_path.exists():
            meta = yaml.safe_load(chart_yaml_path.read_text()) or {}
            if set(meta.get("schema_params", [])) == set(params):
                continue
            meta["schema_params"] = params
            with open(chart_yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(meta, f, default_flow_style=False, sort_keys=False)
            updated += 1
        else:
            chart_dir.mkdir(parents=True, exist_ok=True)
            meta = {
                "name": family,
                "description": f"ArduPilot {family} parameters",
                "version": "schema",
                "schema_params": params,
            }
            with open(chart_yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(meta, f, default_flow_style=False, sort_keys=False)
            created += 1

    return created, updated


# ---------------------------------------------------------------------------
# Export helpers (shared between CLI and TUI)
# ---------------------------------------------------------------------------


def collect_export_files(
    config_dir: Path,
    name: str,
) -> list[tuple[Path, str]]:
    """Collect files for a plane/chart export.

    Returns list of (absolute_path, archive_relative_name) tuples.
    """
    files: list[tuple[Path, str]] = []

    plane_path = config_dir / "planes" / f"{name}.yaml"
    if plane_path.exists():
        rel = str(plane_path.relative_to(config_dir))
        files.append((plane_path, rel))

    charts_dir = config_dir / "charts" / name
    if charts_dir.is_dir():
        for f in sorted(charts_dir.rglob("*")):
            if f.is_file():
                rel = str(f.relative_to(config_dir))
                files.append((f, rel))

    return files


def write_export_zip(
    files: list[tuple[Path, str]],
    output_path: Path,
) -> None:
    """Write collected files to a ZIP archive."""
    with zipfile.ZipFile(str(output_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath, arcname in files:
            zf.write(filepath, arcname)
