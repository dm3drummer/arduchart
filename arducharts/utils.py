"""Shared utilities and constants for arducharts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


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
