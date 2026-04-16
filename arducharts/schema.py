"""ArduPilot parameter schema -- definitions from apm.pdef.json."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from .utils import PDEF_URL


class ParamSchema:
    """ArduPilot parameter definitions from apm.pdef.json.

    Downloads once and caches locally. Provides validation and descriptions.
    """

    def __init__(self, config_dir: str | Path = "configs") -> None:
        self.config_dir = Path(config_dir)
        self.cache_path = self.config_dir / ".cache" / "apm.pdef.json"
        self._flat_cache = self.config_dir / ".cache" / "apm.pdef.flat.json"
        self._defs: dict[str, dict] | None = None

    def _ensure_loaded(self) -> None:
        if self._defs is not None:
            return
        if self._flat_cache.exists():
            self._defs = json.loads(self._flat_cache.read_text())
        elif self.cache_path.exists():
            self._flatten_and_cache()
        else:
            self._download()

    def _flatten_and_cache(self) -> None:
        """Flatten the grouped pdef.json into a single param->definition dict."""
        raw = json.loads(self.cache_path.read_text())
        self._defs = {}
        for params in raw.values():
            if isinstance(params, dict):
                for name, defn in params.items():
                    if isinstance(defn, dict):
                        self._defs[name] = defn
        self._flat_cache.write_text(json.dumps(self._defs))
        print(f"Indexed {len(self._defs)} parameter definitions.")

    def _download(self) -> None:
        print(f"Downloading param definitions from {PDEF_URL}...")
        try:
            req = urllib.request.Request(PDEF_URL, headers={"User-Agent": "arducharts"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode("utf-8")
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(data)
            self._flatten_and_cache()
        except Exception as e:
            print(f"Warning: could not download param definitions: {e}")
            self._defs = {}

    def refresh(self) -> None:
        """Force re-download of param definitions."""
        for p in [self.cache_path, self._flat_cache]:
            if p.exists():
                p.unlink()
        self._defs = None
        self._download()

    def get(self, param_name: str) -> dict | None:
        """Get definition for a single param."""
        self._ensure_loaded()
        return self._defs.get(param_name)

    def exists(self, param_name: str) -> bool:
        """Return True if param_name exists in the schema."""
        self._ensure_loaded()
        return param_name in self._defs

    def describe(self, param_name: str) -> str | None:
        """Return a formatted multi-line description string."""
        defn = self.get(param_name)
        if defn is None:
            return None

        lines = []
        display = defn.get("DisplayName", param_name)
        lines.append(f"{param_name} — {display}")
        if defn.get("Description"):
            lines.append(f"  {defn['Description']}")

        parts = []
        if defn.get("Units"):
            parts.append(f"Units: {defn['Units']}")
        rng = defn.get("Range")
        if rng:
            parts.append(f"Range: {rng.get('low', '?')}..{rng.get('high', '?')}")
        if defn.get("Increment"):
            parts.append(f"Increment: {defn['Increment']}")
        if defn.get("User"):
            parts.append(f"User: {defn['User']}")
        if defn.get("RebootRequired"):
            parts.append("Reboot required")
        if parts:
            lines.append(f"  {', '.join(parts)}")

        vals = defn.get("Values")
        if vals:
            val_strs = [
                f"{k}={v}"
                for k, v in sorted(vals.items(), key=lambda x: float(x[0]))
            ]
            lines.append(f"  Values: {', '.join(val_strs)}")

        bits = defn.get("Bitmask")
        if bits:
            bit_strs = [
                f"{k}:{v}"
                for k, v in sorted(bits.items(), key=lambda x: int(x[0]))
            ]
            lines.append(f"  Bitmask: {', '.join(bit_strs)}")

        return "\n".join(lines)

    # Prefixes for dynamically generated params that won't appear in
    # apm.pdef.json but are valid on a live FC.
    _DYNAMIC_PREFIXES = (
        "SR0_", "SR1_", "SR2_", "SR3_", "SR4_", "SR5_", "SR6_",
        "SR7_", "SR8_", "SR9_",
    )

    # Individual params that are deprecated/renamed but still present on
    # many flight controllers.
    _KNOWN_DEPRECATED = {
        "ARMING_CHECK",
        "SYSID_ENFORCE",
        "SYSID_MYGCS",
        "SYSID_THISMAV",
        "TELEM_DELAY",
        "FS_SHORT_TIMEOUT",
        "GLIDE_SLOPE_MIN",
        "GLIDE_SLOPE_THR",
        "FLTMODE_GCSBLOCK",
    }

    def validate_params(
        self, params: dict[str, Any]
    ) -> tuple[list[str], list[str]]:
        """Validate param names and ranges against the schema.

        Returns (errors, warnings) lists of human-readable strings.
        """
        self._ensure_loaded()
        if not self._defs:
            return [], ["Param definitions not available — skipping schema validation"]

        errors: list[str] = []
        warnings: list[str] = []

        for name, value in params.items():
            defn = self._defs.get(name)
            if defn is None:
                # Skip known dynamic / deprecated params
                if name in self._KNOWN_DEPRECATED:
                    continue
                if any(name.startswith(p) for p in self._DYNAMIC_PREFIXES):
                    continue
                warnings.append(f"Unknown param: {name}")
                continue

            # Range check — 0 means "disabled/default" in ArduPilot even when
            # the schema range starts above 0, so skip the check for 0.
            rng = defn.get("Range")
            if rng and isinstance(value, (int, float)) and value != 0:
                lo = float(rng.get("low", float("-inf")))
                hi = float(rng.get("high", float("inf")))
                if value < lo or value > hi:
                    display = defn.get("DisplayName", name)
                    errors.append(
                        f"{name} ({display}): {value} out of range [{lo}..{hi}]"
                    )

            # Enum check — compare against both the shorthand keys and the
            # raw value so that e.g. baud=115200 matches key "115" (115200).
            vals = defn.get("Values")
            if vals and isinstance(value, (int, float)):
                str_val = str(int(value)) if value == int(value) else str(value)
                valid_keys = set(vals.keys())
                if str_val not in valid_keys:
                    # Check if the value itself equals any key * known
                    # multiplier (baud rates stored as raw on FC).
                    matched = False
                    for k in valid_keys:
                        try:
                            if int(value) == int(k):
                                matched = True
                                break
                        except (ValueError, OverflowError):
                            pass
                    if not matched:
                        display = defn.get("DisplayName", name)
                        allowed = ", ".join(
                            f"{k}={v}"
                            for k, v in sorted(
                                vals.items(), key=lambda x: float(x[0])
                            )
                        )
                        warnings.append(
                            f"{name} ({display}): {value} not in [{allowed}]"
                        )

        return errors, warnings

    def search(self, query: str) -> list[tuple[str, dict]]:
        """Search params by name, display name, or description."""
        self._ensure_loaded()
        q = query.lower()
        results = []
        for name, defn in self._defs.items():
            text = (
                f"{name} {defn.get('DisplayName', '')} "
                f"{defn.get('Description', '')}"
            ).lower()
            if q in text:
                results.append((name, defn))
        results.sort(key=lambda x: x[0])
        return results

    @property
    def count(self) -> int:
        """Return the number of parameter definitions in the schema."""
        self._ensure_loaded()
        return len(self._defs)
