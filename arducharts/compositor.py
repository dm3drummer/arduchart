"""Chart compositor -- resolves charts, dependencies, and merges parameters."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from .utils import norm_value


class ParamCompositor:
    """Helm-style chart compositor for ArduPilot parameters.

    Chart structure:
        charts/<name>/Chart.yaml     -- name, description, version, base, depends
        charts/<name>/defaults.yaml  -- default param values

    Plane config:
        planes/<name>.yaml -- charts[], values{}, extra_params{}

    Resolution order:
        1. Chart defaults (depth-first dependency resolution)
        2. Plane values (scoped by chart name)
        3. Profile overrides
        4. Plane extra_params
    """

    def __init__(self, config_dir: str | Path = "configs") -> None:
        self.config_dir = Path(config_dir)
        self.charts_dir = self.config_dir / "charts"
        self.schema_dir = self.config_dir / "schema"
        self._yaml_cache: dict[Path, tuple[float, dict]] = {}

    # -- YAML loading --

    def load_yaml(self, path: str | Path) -> dict:
        """Load and cache a YAML file. Returns empty dict for empty files."""
        resolved = Path(path).resolve()
        mtime = resolved.stat().st_mtime
        cached = self._yaml_cache.get(resolved)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(resolved) as f:
            data = yaml.safe_load(f) or {}
        self._yaml_cache[resolved] = (mtime, data)
        return data

    # -- Plane loading --

    def load_plane(
        self, plane_path: str | Path,
    ) -> dict[str, Any]:
        """Load a plane config and resolve all charts into merged parameters.

        Returns a dict with keys: name, description, params,
        charts, installed, meta, firmware.
        """
        installed: list[str] = []
        seen: set[str] = set()

        plane_path = Path(plane_path)
        if not plane_path.is_absolute():
            plane_path = self.config_dir / plane_path

        plane_config = self.load_yaml(plane_path)
        merged_params: dict[str, Any] = {}
        merged_meta: dict[str, str] = {}

        # Install each chart (dependencies resolved recursively)
        for chart_name in plane_config.get("charts", []):
            self._install_chart(
                chart_name, merged_params, merged_meta,
                installed, seen,
            )

        # Plane-level value overrides (scoped by chart name)
        for chart_name, overrides in (plane_config.get("values") or {}).items():
            if isinstance(overrides, dict):
                _merge_params(
                    merged_params, merged_meta,
                    overrides, f"plane values for chart '{chart_name}'",
                )

        # Raw extra params (highest priority)
        extra = plane_config.get("extra_params") or {}
        if extra:
            _merge_params(
                merged_params, merged_meta,
                extra, "plane extra_params",
            )

        return {
            "name": plane_config.get("name", "Unknown"),
            "description": plane_config.get("description", ""),
            "params": merged_params,
            "charts": plane_config.get("charts", []),
            "installed": installed,
            "meta": merged_meta,
            "firmware": plane_config.get("firmware"),
        }

    def _install_chart(
        self,
        chart_name: str,
        merged_params: dict[str, Any],
        merged_meta: dict[str, str],
        installed: list[str],
        seen: set[str],
    ) -> None:
        """Install a chart: resolve depends first, then apply defaults."""
        if chart_name in seen:
            return
        seen.add(chart_name)

        chart_dir = self.charts_dir / chart_name
        chart_yaml = chart_dir / "Chart.yaml"
        defaults_yaml = chart_dir / "defaults.yaml"

        if not chart_dir.exists():
            raise FileNotFoundError(f"Chart not found: {chart_name}")
        if not chart_yaml.exists():
            raise FileNotFoundError(f"Missing Chart.yaml in: {chart_name}")

        chart_meta = self.load_yaml(chart_yaml)

        # Resolve dependencies first (they get lower priority)
        for dep in chart_meta.get("depends", []):
            self._install_chart(
                dep, merged_params, merged_meta,
                installed, seen,
            )

        # Apply this chart's defaults
        if defaults_yaml.exists():
            defaults = self.load_yaml(defaults_yaml)
            params = defaults.get("params", {})
            if params:
                _merge_params(
                    merged_params, merged_meta,
                    params, f"chart '{chart_name}' defaults",
                )

        installed.append(chart_name)

    # -- Chart listing --

    def list_charts(self) -> list[dict]:
        """List all user charts with metadata (supports nested dirs)."""
        charts = []
        if not self.charts_dir.exists():
            return charts
        for chart_yaml in sorted(self.charts_dir.rglob("Chart.yaml")):
            chart_dir = chart_yaml.parent
            # Chart name is the path relative to charts_dir
            chart_name = str(chart_dir.relative_to(self.charts_dir))
            meta = self.load_yaml(chart_yaml)
            defaults_yaml = chart_dir / "defaults.yaml"
            param_count = 0
            if defaults_yaml.exists():
                defaults = self.load_yaml(defaults_yaml)
                param_count = len(defaults.get("params", {}))
            charts.append({
                "name": chart_name,
                "description": meta.get("description", ""),
                "version": meta.get("version", ""),
                "depends": meta.get("depends", []),
                "base": meta.get("base", []),
                "params": param_count,
            })
        return charts

    def list_schema_charts(self) -> list[dict]:
        """List all schema charts (param catalog families)."""
        charts = []
        if not self.schema_dir.exists():
            return charts
        for chart_dir in sorted(self.schema_dir.iterdir()):
            chart_yaml = chart_dir / "Chart.yaml"
            if not (chart_dir.is_dir() and chart_yaml.exists()):
                continue
            meta = self.load_yaml(chart_yaml)
            charts.append({
                "name": meta.get("name", chart_dir.name),
                "description": meta.get("description", ""),
                "schema_params": len(meta.get("schema_params", [])),
            })
        return charts

    def get_schema_params(self, family_name: str) -> list[str]:
        """Get the schema_params list for a schema chart family."""
        chart_yaml = self.schema_dir / family_name / "Chart.yaml"
        if not chart_yaml.exists():
            return []
        meta = self.load_yaml(chart_yaml)
        return meta.get("schema_params", [])

    def validate_chart_bases(self) -> list[str]:
        """Check that chart params match their declared base schema families.

        Returns list of warning strings for params not in the base schema.
        """
        warnings: list[str] = []
        if not self.charts_dir.exists():
            return warnings

        for chart_dir in sorted(self.charts_dir.iterdir()):
            chart_yaml = chart_dir / "Chart.yaml"
            defaults_yaml = chart_dir / "defaults.yaml"
            if not (chart_dir.is_dir() and chart_yaml.exists()):
                continue

            meta = self.load_yaml(chart_yaml)
            chart_name = meta.get("name", chart_dir.name)
            bases = meta.get("base", [])
            if not bases or not defaults_yaml.exists():
                continue

            allowed: set[str] = set()
            for base_name in bases:
                allowed.update(self.get_schema_params(base_name))
            if not allowed:
                continue

            defaults = self.load_yaml(defaults_yaml)
            for param in defaults.get("params", {}):
                if param not in allowed:
                    warnings.append(
                        f"{chart_name}: param '{param}' not in base "
                        f"schema ({', '.join(bases)})"
                    )
        return warnings

    # -- Chart matching (for FC import) --

    def match_charts(
        self, fc_params: dict[str, Any]
    ) -> tuple[list[str], dict[str, dict], dict[str, Any]]:
        """Match FC params against chart defaults and schema_params.

        Two-pass matching:
        1. User charts (have defaults.yaml) -- exact param matching
        2. Schema charts (schema_params only) -- claim remaining FC params

        Returns (matched_chart_names, override_values, unmatched_params).
        """
        matched_names: set[str] = set()
        override_values: dict[str, dict] = {}
        claimed_params: set[str] = set()
        all_user_charts: dict[str, tuple[Path, dict]] = {}

        # Pass 1: user charts with defaults.yaml
        if self.charts_dir.exists():
            for chart_yaml in sorted(self.charts_dir.rglob("Chart.yaml")):
                chart_dir = chart_yaml.parent
                meta = self.load_yaml(chart_yaml)
                chart_name = str(chart_dir.relative_to(self.charts_dir))
                all_user_charts[chart_name] = (chart_dir, meta)

                defaults_yaml = chart_dir / "defaults.yaml"
                if not defaults_yaml.exists():
                    continue
                defaults = self.load_yaml(defaults_yaml)
                chart_params = defaults.get("params", {})
                # All chart params must exist on FC for a match
                if not chart_params or not all(k in fc_params for k in chart_params):
                    continue

                matched_names.add(chart_name)
                overrides = {}
                for param_name, default_val in chart_params.items():
                    claimed_params.add(param_name)
                    fc_val = norm_value(fc_params[param_name])
                    default_val = norm_value(default_val)
                    if fc_val != default_val:
                        overrides[param_name] = fc_val
                if overrides:
                    override_values[chart_name] = overrides

        # Pass 2: schema charts claim remaining FC params
        if self.schema_dir.exists():
            for family_dir in sorted(self.schema_dir.iterdir()):
                chart_yaml = family_dir / "Chart.yaml"
                if not (family_dir.is_dir() and chart_yaml.exists()):
                    continue
                meta = self.load_yaml(chart_yaml)
                family_name = meta.get("name", family_dir.name)
                schema_params = meta.get("schema_params", [])
                if not schema_params:
                    continue

                unclaimed_fc_params = {
                    param: fc_params[param]
                    for param in schema_params
                    if param in fc_params and param not in claimed_params
                }
                if not unclaimed_fc_params:
                    continue
                matched_names.add(family_name)
                override_values[family_name] = unclaimed_fc_params
                claimed_params.update(unclaimed_fc_params)

        # Detect bundle charts (have depends but no own params, all deps matched)
        for chart_name, (_, meta) in all_user_charts.items():
            deps = meta.get("depends", [])
            if deps and all(dep in matched_names for dep in deps):
                matched_names.add(chart_name)

        unmatched = {
            k: v for k, v in sorted(fc_params.items()) if k not in claimed_params
        }
        return sorted(matched_names), override_values, unmatched

    def import_as_charts(
        self,
        fc_params: dict[str, Any],
        plane_name: str,
    ) -> tuple[list[str], dict[str, Any]]:
        """Create per-schema-family charts from FC params.

        For each schema family that has FC params, creates:
            charts/{plane_name}/{family}/Chart.yaml
            charts/{plane_name}/{family}/defaults.yaml

        Returns (created_chart_names, unmatched_params).
        Chart names use '/' so the compositor resolves them as subfolders.
        """
        claimed: set[str] = set()
        created_charts: list[str] = []
        created_dirs: list[Path] = []

        if not self.schema_dir.exists():
            return [], dict(sorted(fc_params.items()))

        try:
            for family_dir in sorted(self.schema_dir.iterdir()):
                chart_yaml = family_dir / "Chart.yaml"
                if not (family_dir.is_dir() and chart_yaml.exists()):
                    continue
                meta = self.load_yaml(chart_yaml)
                family = meta.get("name", family_dir.name)
                schema_params = set(meta.get("schema_params", []))
                if not schema_params:
                    continue

                # Collect FC params that belong to this family
                family_params = {
                    k: v for k, v in fc_params.items() if k in schema_params
                }
                if not family_params:
                    continue

                chart_name = f"{plane_name}/{family}"
                chart_dir = self.charts_dir / chart_name
                chart_dir.mkdir(parents=True, exist_ok=True)
                created_dirs.append(chart_dir)

                # Chart.yaml
                chart_meta = {
                    "name": family,
                    "description": f"{family} params imported from FC",
                    "version": "1.0",
                    "base": [family],
                }
                with open(chart_dir / "Chart.yaml", "w") as f:
                    yaml.dump(chart_meta, f, default_flow_style=False, sort_keys=False)

                # defaults.yaml
                defaults = {"params": dict(sorted(family_params.items()))}
                with open(chart_dir / "defaults.yaml", "w") as f:
                    yaml.dump(defaults, f, default_flow_style=False, sort_keys=False)

                created_charts.append(chart_name)
                claimed.update(family_params)
        except Exception:
            for d in created_dirs:
                shutil.rmtree(d, ignore_errors=True)
            raise

        unmatched = {
            k: v for k, v in sorted(fc_params.items()) if k not in claimed
        }
        return created_charts, unmatched

    # -- File I/O --

    @staticmethod
    def to_param_file(
        params: dict[str, Any],
        output_path: str | Path,
        header: str | None = None,
    ) -> None:
        """Write params to a .param file (CSV format)."""
        with open(output_path, "w") as f:
            if header:
                for line in header.split("\n"):
                    f.write(f"# {line}\n")
                f.write("#\n")
            for key, value in params.items():
                value = norm_value(value)
                if isinstance(value, float):
                    f.write(f"{key},{value:.6f}\n")
                else:
                    f.write(f"{key},{value}\n")

    @staticmethod
    def read_param_file(path: str | Path) -> dict[str, Any]:
        """Read a .param file (comma or space separated)."""
        params: dict[str, Any] = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",", 1) if "," in line else line.split(None, 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    try:
                        value: Any = norm_value(float(parts[1].strip()))
                    except ValueError:
                        value = parts[1].strip()
                    params[key] = value
        return params


def _merge_params(
    merged_params: dict[str, Any],
    merged_meta: dict[str, str],
    new_params: dict[str, Any],
    source: str,
) -> None:
    """Merge new_params into merged_params and update meta."""
    for key, value in new_params.items():
        merged_params[key] = value
        merged_meta[key] = source
