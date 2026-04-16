"""CLI commands and argument parsing for arducharts."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any

import yaml

from .compositor import ParamCompositor
from .mavlink_io import MAVLinkConnection, require_mavlink
from .schema import ParamSchema
from .schema_map import build_schema_charts_data
from .utils import (
    DEFAULT_BAUD,
    collect_export_files,
    compute_param_diff,
    lint_plane_config,
    norm_value,
    rebuild_schema_charts,
    version_less_than,
    write_export_zip,
)


# -- Helpers --


def _check_firmware_compat(
    compositor: ParamCompositor,
    installed_charts: list[str],
    plane_firmware: str,
) -> list[str]:
    """Check that all installed charts are compatible with the plane firmware."""
    errors: list[str] = []
    for chart_name in installed_charts:
        chart_yaml = compositor.charts_dir / chart_name / "Chart.yaml"
        if not chart_yaml.exists():
            continue
        chart_meta = compositor.load_yaml(chart_yaml)
        min_fw = chart_meta.get("min_firmware")
        if min_fw and version_less_than(plane_firmware, min_fw):
            errors.append(
                f"Chart '{chart_name}' requires firmware >= {min_fw}, "
                f"but plane specifies {plane_firmware}"
            )
    return errors


# -- Offline commands --


def cmd_list(args: argparse.Namespace) -> None:
    """List all available charts with metadata."""
    compositor = ParamCompositor(args.config_dir)
    charts = compositor.list_charts()
    if not charts:
        print("No charts found.")
        return

    print(f"{'CHART':<25} {'VER':<6} {'PARAMS':<7} {'DEPENDS':<30} DESCRIPTION")
    print("-" * 110)
    for chart in charts:
        deps = ", ".join(chart["depends"]) if chart["depends"] else "-"
        print(
            f"{chart['name']:<25} {chart['version']:<6} {chart['params']:<7} "
            f"{deps:<30} {chart['description']}"
        )


def cmd_build(args: argparse.Namespace) -> None:
    """Compile a plane config into a .param file."""
    compositor = ParamCompositor(args.config_dir)
    result = compositor.load_plane(args.config)

    print(f"Building: {result['name']}")
    print(f"Charts:    {', '.join(result['charts'])}")
    print(f"Installed: {len(result['installed'])} (with dependencies)")
    print(f"Params:    {len(result['params'])}")

    if args.verbose:
        print(f"\nInstall order: {' -> '.join(result['installed'])}")

    if args.output:
        output = args.output
    else:
        plane_name = Path(args.config).stem
        build_dir = Path(args.config_dir) / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        output = str(build_dir / f"{plane_name}.param")

    header = f"{result['name']}\n{result['description']}"
    compositor.to_param_file(result["params"], output, header=header)
    print(f"\nWritten: {output}")


def cmd_show(args: argparse.Namespace) -> None:
    """Print merged parameters with descriptions."""
    compositor = ParamCompositor(args.config_dir)
    result = compositor.load_plane(args.config)
    schema = ParamSchema(args.config_dir)

    print(f"# {result['name']}")
    if result["description"]:
        print(f"# {result['description']}")
    print(f"# Charts: {', '.join(result['charts'])}")
    print(f"# Installed: {' -> '.join(result['installed'])}")
    print(f"# Total: {len(result['params'])} parameters")
    print("#")

    for param_name, raw_value in result["params"].items():
        source = result["meta"].get(param_name, "")
        value = norm_value(raw_value)
        defn = schema.get(param_name)

        if not defn:
            print(f"{param_name},{value}    # {source}")
            continue

        comment_parts = [source]
        display_name = defn.get("DisplayName", "")
        if display_name:
            comment_parts.append(display_name)
        units = defn.get("Units", "")
        if units:
            comment_parts.append(f"[{units}]")
        enum_values = defn.get("Values")
        if enum_values and isinstance(value, (int, float)):
            label = enum_values.get(str(int(value)))
            if label:
                comment_parts.append(f"= {label}")
        print(f"{param_name},{value}    # {' | '.join(comment_parts)}")


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate a plane config against ArduPilot schema."""
    compositor = ParamCompositor(args.config_dir)
    try:
        result = compositor.load_plane(args.config)
    except Exception as e:
        print(f"INVALID: {e}")
        sys.exit(1)

    print(f"Config:    {result['name']}")
    print(f"Charts:    {', '.join(result['charts'])}")
    print(f"Installed: {len(result['installed'])} (with deps)")
    print(f"Params:    {len(result['params'])}")
    if result.get("firmware"):
        print(f"Firmware:  {result['firmware']}")

    warnings: list[str] = []
    errors: list[str] = []

    # Schema validation (param names + ranges)
    schema = ParamSchema(args.config_dir)
    schema_errors, schema_warnings = schema.validate_params(result["params"])
    errors.extend(schema_errors)
    warnings.extend(schema_warnings)

    # Firmware version pinning
    plane_firmware = result.get("firmware")
    if plane_firmware:
        fw_errors = _check_firmware_compat(
            compositor, result["installed"], plane_firmware
        )
        errors.extend(fw_errors)

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for msg in errors:
            print(f"  [ERROR] {msg}")
    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for msg in warnings:
            print(f"  [WARN]  {msg}")
    if not errors and not warnings:
        print("\nAll checks passed.")
    if errors:
        sys.exit(1)


def cmd_lint(args: argparse.Namespace) -> None:
    """Lint a plane config for common mistakes."""
    compositor = ParamCompositor(args.config_dir)
    result = compositor.load_plane(args.config)

    plane_path = Path(args.config)
    if not plane_path.is_absolute():
        plane_path = compositor.config_dir / plane_path

    warnings = lint_plane_config(compositor, plane_path, result)

    print(f"Linting: {result['name']}")
    print(f"Charts: {len(result['installed'])}, Params: {len(result['params'])}")
    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for msg in warnings:
            print(f"  [LINT] {msg}")
    else:
        print("\nNo issues found.")


def cmd_diff_planes(args: argparse.Namespace) -> None:
    """Compare two plane configs side by side."""
    compositor = ParamCompositor(args.config_dir)
    plane_a = compositor.load_plane(args.config1)
    plane_b = compositor.load_plane(args.config2)

    all_keys = set(plane_a["params"]) | set(plane_b["params"])
    only_in_a: list[tuple[str, Any]] = []
    only_in_b: list[tuple[str, Any]] = []
    different: list[tuple[str, Any, str, Any, str]] = []
    matching = 0

    for key in sorted(all_keys):
        in_a = key in plane_a["params"]
        in_b = key in plane_b["params"]
        if in_a and not in_b:
            only_in_a.append((key, plane_a["params"][key]))
        elif in_b and not in_a:
            only_in_b.append((key, plane_b["params"][key]))
        else:
            val_a = norm_value(plane_a["params"][key])
            val_b = norm_value(plane_b["params"][key])
            if val_a != val_b:
                source_a = plane_a["meta"].get(key, "")
                source_b = plane_b["meta"].get(key, "")
                different.append((key, val_a, source_a, val_b, source_b))
            else:
                matching += 1

    print(f"Comparing: {plane_a['name']} vs {plane_b['name']}")
    print(f"Matching: {matching}")
    if different:
        print(f"\nDifferent ({len(different)}):")
        for key, val_a, source_a, val_b, source_b in different:
            print(f"  {key}: {val_a} ({source_a}) vs {val_b} ({source_b})")
    if only_in_a:
        print(f"\nOnly in {plane_a['name']} ({len(only_in_a)}):")
        for key, val in only_in_a:
            print(f"  {key} = {val}")
    if only_in_b:
        print(f"\nOnly in {plane_b['name']} ({len(only_in_b)}):")
        for key, val in only_in_b:
            print(f"  {key} = {val}")
    if not different and not only_in_a and not only_in_b:
        print("Planes produce identical parameters.")


def cmd_search(args: argparse.Namespace) -> None:
    """Search parameter names and descriptions."""
    schema = ParamSchema(args.config_dir)
    results = schema.search(args.query)
    if not results:
        print(f"No parameters matching '{args.query}'")
        return
    limit = args.limit
    print(f"Found {len(results)} params matching '{args.query}':\n")
    for name, defn in results[:limit]:
        display = defn.get("DisplayName", "")
        units = f" [{defn['Units']}]" if defn.get("Units") else ""
        print(f"  {name:<35} {display}{units}")
    if len(results) > limit:
        print(f"\n  ... and {len(results) - limit} more (use --limit to see all)")


def cmd_describe(args: argparse.Namespace) -> None:
    """Show detailed ArduPilot param descriptions."""
    schema = ParamSchema(args.config_dir)
    for name in args.params:
        text = schema.describe(name.upper())
        if text:
            print(text)
        else:
            print(f"{name.upper()} — not found in ArduPlane definitions")
        print()


def cmd_create_chart(args: argparse.Namespace) -> None:
    """Scaffold a new chart directory."""
    charts_dir = Path(args.config_dir) / "charts"
    schema_dir = Path(args.config_dir) / "schema"
    chart_dir = charts_dir / args.name

    if chart_dir.exists():
        print(f"Error: chart '{args.name}' already exists")
        sys.exit(1)

    # Validate --base charts exist in schema dir
    if args.base:
        for base_name in args.base:
            base_chart_yaml = schema_dir / base_name / "Chart.yaml"
            if not base_chart_yaml.exists():
                print(f"Error: schema chart '{base_name}' not found")
                print("Available schema charts (run generate-schema-charts first):")
                if schema_dir.exists():
                    for d in sorted(schema_dir.iterdir()):
                        cy = d / "Chart.yaml"
                        if cy.exists():
                            meta = yaml.safe_load(cy.read_text()) or {}
                            sp = meta.get("schema_params", [])
                            print(f"  {d.name} ({len(sp)} params)")
                sys.exit(1)

    chart_dir.mkdir(parents=True)

    # Chart.yaml
    chart_meta: dict = {
        "name": args.name,
        "description": "",
        "version": "1.0",
    }
    if args.base:
        chart_meta["base"] = list(args.base)
    if args.depends:
        chart_meta["depends"] = list(args.depends)
    with open(chart_dir / "Chart.yaml", "w", encoding="utf-8") as f:
        yaml.dump(chart_meta, f, default_flow_style=False, sort_keys=False)

    # defaults.yaml
    params = [p.upper() for p in (args.params or [])]
    data = {"params": {p: 0 for p in params}} if params else {"params": {}}
    with open(chart_dir / "defaults.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    print(f"Created: {chart_dir}/")
    print("  Chart.yaml")
    print(f"  defaults.yaml ({len(params)} params)")

    if args.base:
        total = 0
        for base_name in args.base:
            meta = yaml.safe_load(
                (schema_dir / base_name / "Chart.yaml").read_text()
            ) or {}
            total += len(meta.get("schema_params", []))
        print(f"\nBase: {', '.join(args.base)} ({total} params available)")
        print("Use 'arducharts describe PARAM' to look up param details.")
    print("Edit defaults.yaml to add the params you need.")


def cmd_update_schema(args: argparse.Namespace) -> None:
    """Download latest param definitions and rebuild schema charts."""
    config_dir = Path(args.config_dir)

    print("Downloading latest ArduPilot param definitions...")
    schema = ParamSchema(args.config_dir)
    schema.refresh()
    print(f"  {schema.count} parameters cached.\n")

    print("Rebuilding schema charts...")
    families = build_schema_charts_data(config_dir)
    created, updated = rebuild_schema_charts(config_dir, families)

    unmapped = families.get("_unmapped", [])
    if unmapped:
        print(f"\nUnmapped params ({len(unmapped)}):")
        prefixes: dict[str, list[str]] = {}
        for p in unmapped:
            prefix = p.split("_")[0] + "_" if "_" in p else p
            prefixes.setdefault(prefix, []).append(p)
        for prefix, plist in prefixes.items():
            print(f"  {prefix}: {len(plist)} params")

    total_families = len(families) - (1 if "_unmapped" in families else 0)
    total_params = sum(len(v) for v in families.values())
    print(
        f"\nDone: {created} created, {updated} updated, "
        f"{total_families} families, {total_params} total params"
    )
    if unmapped:
        print("Add unmapped groups to SCHEMA_CHART_MAP in schema_map.py.")


# -- FC commands --


def cmd_diff(args: argparse.Namespace) -> None:
    """Diff a plane config against the FC or a .param file."""
    compositor = ParamCompositor(args.config_dir)
    result = compositor.load_plane(args.config)

    if args.port:
        require_mavlink()
        with MAVLinkConnection(args.port, args.baud) as mav:
            current = mav.read_all_params()
        source = args.port
    elif args.param_file:
        current = ParamCompositor.read_param_file(args.param_file)
        source = args.param_file
    else:
        print("Error: specify --port or --param-file")
        sys.exit(1)

    changes, missing, matching = compute_param_diff(result["params"], current)

    print(f"\nDiff: {result['name']} vs {source}")
    print(f"Matching: {matching}")
    if changes:
        print(f"\nNeed update ({len(changes)}):")
        for key, current_val, desired_val in changes:
            print(f"  {key}: {current_val} -> {desired_val}")
    if missing:
        print(f"\nNot on FC ({len(missing)}):")
        for key, val in missing:
            print(f"  {key} = {val}")
    if not changes and not missing:
        print("All parameters match!")
    return changes, missing


def cmd_flash(args: argparse.Namespace) -> None:
    """Flash parameters to a flight controller."""
    require_mavlink()
    compositor = ParamCompositor(args.config_dir)
    result = compositor.load_plane(args.config)
    with MAVLinkConnection(args.port, args.baud) as mav:
        if args.changed_only:
            print("Reading current params to find differences...")
            current = mav.read_all_params()
            changes, missing, _ = compute_param_diff(result["params"], current)

            to_flash: dict[str, Any] = {}
            for key, _current, desired in changes:
                to_flash[key] = desired
            for key, desired in missing:
                to_flash[key] = desired

            if not to_flash:
                print("All parameters already match.")
                return
            print(f"\n{len(to_flash)} differ (out of {len(result['params'])} total)")
            params_to_write = to_flash
        else:
            params_to_write = result["params"]

        print(f"\nFlashing: {result['name']}")
        print(f"Parameters: {len(params_to_write)}")

        if not args.force:
            resp = input("\nContinue? [y/N] ")
            if resp.lower() != "y":
                print("Aborted.")
                return
        mav.flash_params(params_to_write, dry_run=args.dry_run)

        if not args.dry_run and args.verify:
            print("\nVerifying — reading back params from FC...")
            readback = mav.read_all_params()
            mismatched, not_found, _ = compute_param_diff(params_to_write, readback)
            if mismatched or not_found:
                total_issues = len(mismatched) + len(not_found)
                print(f"\nVerify FAILED — {total_issues} mismatch(es):")
                for key, actual, expected in mismatched:
                    print(f"  {key}: expected {expected}, got {actual}")
                for key, _ in not_found:
                    print(f"  {key}: NOT FOUND on FC")
            else:
                print(
                    f"Verify OK — all {len(params_to_write)} params confirmed."
                )


def cmd_read(args: argparse.Namespace) -> None:
    """Read all parameters from the FC."""
    require_mavlink()
    with MAVLinkConnection(args.port, args.baud) as mav:
        params = mav.read_all_params()

        if args.output:
            if args.output.endswith(".yaml"):
                data = {
                    "name": "Read from FC",
                    "description": f"Read from {args.port}",
                    "params": dict(sorted(params.items())),
                }
                with open(args.output, "w", encoding="utf-8") as f:
                    yaml.dump(
                        data, f, default_flow_style=False, sort_keys=False
                    )
            else:
                ParamCompositor.to_param_file(
                    dict(sorted(params.items())), args.output
                )
            print(f"Written: {args.output}")
        else:
            for key, value in sorted(params.items()):
                print(f"{key},{value}")



def cmd_import(args: argparse.Namespace) -> None:
    """Create a plane config from FC or .param file."""
    compositor = ParamCompositor(args.config_dir)

    if args.port:
        require_mavlink()
        with MAVLinkConnection(args.port, args.baud) as mav:
            fc_params = mav.read_all_params()
    elif args.param_file:
        fc_params = ParamCompositor.read_param_file(args.param_file)
    else:
        print("Error: specify --port or --param-file")
        sys.exit(1)

    name = args.name or "imported"
    safe_name = name.lower().replace(" ", "_")

    print(f"Read {len(fc_params)} params")
    charts, unmatched = compositor.import_as_charts(fc_params, safe_name)

    print(f"Created {len(charts)} charts:")
    for chart in charts:
        print(f"  {chart}")
    if unmatched:
        print(f"Unmatched params: {len(unmatched)}")

    # Build plane config referencing the new charts
    plane: dict = {
        "name": name,
        "description": f"Imported from FC ({len(fc_params)} params)",
        "charts": charts,
    }
    if unmatched:
        plane["extra_params"] = unmatched

    output = args.output
    if not output:
        planes_dir = Path(args.config_dir) / "planes"
        planes_dir.mkdir(parents=True, exist_ok=True)
        output = str(planes_dir / f"{safe_name}.yaml")

    with open(output, "w", encoding="utf-8") as f:
        yaml.dump(plane, f, default_flow_style=False, sort_keys=False)
    print(f"\nWritten: {output}")

    if unmatched and args.verbose:
        print("\nUnmatched params (not in any chart):")
        for key, val in list(unmatched.items())[:30]:
            print(f"  {key}: {val}")
        if len(unmatched) > 30:
            print(f"  ... and {len(unmatched) - 30} more")


def cmd_export_chart(args: argparse.Namespace) -> None:
    """Export a plane config + its charts as a portable .zip archive.

    Archive format (real relative paths from config_dir):
        planes/<name>.yaml
        charts/<name>/<family>/Chart.yaml
        charts/<name>/<family>/defaults.yaml
    """
    config_dir = Path(args.config_dir)
    name = args.name

    files = collect_export_files(config_dir, name)
    if not files:
        print(f"Nothing found for '{name}'. Expected planes/{name}.yaml or charts/{name}/")
        sys.exit(1)

    if args.output:
        output = Path(args.output)
    else:
        export_dir = config_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        output = export_dir / f"{name}.zip"

    write_export_zip(files, output)

    print(f"Exported {len(files)} files to {output}")
    for _, arcname in files:
        print(f"  {arcname}")


def cmd_import_chart(args: argparse.Namespace) -> None:
    """Import a .zip chart archive into the config directory.

    Files are extracted directly to config_dir using their archive paths.
    Only entries under charts/ or planes/ are allowed.
    """
    import zipfile

    config_dir = Path(args.config_dir)
    if not args.archive.endswith(".zip"):
        print("Error: file must be a .zip")
        sys.exit(1)
    archive_path = Path(args.archive)

    if not archive_path.exists():
        print(f"File not found: {archive_path}")
        sys.exit(1)

    with zipfile.ZipFile(str(archive_path), "r") as zf:
        members = zf.namelist()

        # Validate entries
        for m in members:
            if not (m.startswith("charts/") or m.startswith("planes/")):
                print(f"Unexpected entry: {m} (expected charts/* or planes/*)")
                sys.exit(1)

        # Check for conflicts
        targets: list[tuple[str, Path]] = []
        for m in members:
            targets.append((m, config_dir / m))

        existing = [t for _, t in targets if t.exists()]
        if existing and not args.force:
            print("Files already exist (use --force to overwrite):")
            for e in existing:
                print(f"  {e.relative_to(config_dir)}")
            sys.exit(1)

        # Extract directly
        for arcname, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(arcname))

    print(f"Imported {len(targets)} files")
    for _, t in targets:
        print(f"  {t.relative_to(config_dir)}")


# -- Argument parsing --


def main() -> None:
    """CLI entry point — parse arguments and dispatch to command handlers."""
    parser = argparse.ArgumentParser(
        prog="arducharts",
        description="ArduPilot YAML Configuration Compositor (Helm-style)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s list
  %(prog)s build planes/talon_x.yaml -o talon_x.param
  %(prog)s show planes/talon_x.yaml
  %(prog)s diff planes/talon_x.yaml --port /dev/ttyACM0
  %(prog)s flash planes/talon_x.yaml --port /dev/ttyACM0 --changed-only
  %(prog)s read --port /dev/ttyACM0 -o current.yaml
  %(prog)s validate planes/talon_x.yaml
  %(prog)s describe ARSPD_TYPE BATT_MONITOR
  %(prog)s update-schema
""",
    )
    parser.add_argument(
        "-d", "--config-dir", default="configs",
        help="Base config directory (default: configs)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # -- Offline commands --

    sub.add_parser("list", help="List available charts")

    p = sub.add_parser("build", help="Compile plane config to .param file")
    p.add_argument("config")
    p.add_argument("-o", "--output", help="Output .param path")
    p.add_argument("-v", "--verbose", action="store_true")


    p = sub.add_parser("show", help="Print merged params with descriptions")
    p.add_argument("config")


    p = sub.add_parser(
        "validate", help="Validate plane config against ArduPilot schema"
    )
    p.add_argument("config")


    p = sub.add_parser("lint", help="Lint plane config for common mistakes")
    p.add_argument("config")


    p = sub.add_parser("diff-planes", help="Compare two plane configs")
    p.add_argument("config1")
    p.add_argument("config2")


    p = sub.add_parser("search", help="Search param names and descriptions")
    p.add_argument("query", help="Search term")
    p.add_argument("--limit", type=int, default=50, help="Max results")

    p = sub.add_parser("describe", help="Show ArduPilot param description")
    p.add_argument("params", nargs="+", help="Param name(s)")

    p = sub.add_parser("create-chart", help="Scaffold a new chart directory")
    p.add_argument("name", help="Chart name (directory name)")
    p.add_argument(
        "--base", nargs="+", default=[],
        help="Schema chart(s) to base on",
    )
    p.add_argument(
        "--params", nargs="+", default=[],
        help="Param names to include",
    )
    p.add_argument(
        "--depends", nargs="*", default=[],
        help="Chart dependencies",
    )

    sub.add_parser(
        "update-schema",
        help="Download latest param definitions and rebuild schema charts",
    )

    p = sub.add_parser(
        "import", help="Create plane config from FC or .param file"
    )
    p.add_argument("--port", help="MAVLink port")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("--param-file", help="Existing .param file")
    p.add_argument("--name", default="Imported from FC")
    p.add_argument("-o", "--output")
    p.add_argument("-v", "--verbose", action="store_true")

    # -- FC commands --

    p = sub.add_parser("diff", help="Diff config vs FC or .param file")
    p.add_argument("config")
    p.add_argument("--port")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("--param-file")


    p = sub.add_parser("flash", help="Flash params to FC")
    p.add_argument("config")
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--changed-only", action="store_true")
    p.add_argument("--verify", action="store_true")


    p = sub.add_parser("read", help="Read params from FC")
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("-o", "--output")

    p = sub.add_parser(
        "export-chart", help="Export plane + charts as .zip archive"
    )
    p.add_argument("name", help="Plane or chart folder name")
    p.add_argument("-o", "--output", help="Output .zip path")

    p = sub.add_parser(
        "import-chart", help="Import .zip chart archive"
    )
    p.add_argument("archive", help="Path to .zip file")
    p.add_argument(
        "--force", action="store_true",
        help="Overwrite existing files",
    )

    sub.add_parser("tui", help="Launch interactive TUI")

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "build": cmd_build,
        "show": cmd_show,
        "validate": cmd_validate,
        "lint": cmd_lint,
        "diff-planes": cmd_diff_planes,
        "search": cmd_search,
        "describe": cmd_describe,
        "create-chart": cmd_create_chart,
        "update-schema": cmd_update_schema,
        "import": cmd_import,
        "diff": cmd_diff,
        "flash": cmd_flash,
        "read": cmd_read,
        "export-chart": cmd_export_chart,
        "import-chart": cmd_import_chart,
        "tui": lambda a: importlib.import_module("tui").run_tui(a.config_dir),
    }
    try:
        commands[args.command](args)
    except ImportError as e:
        print(f"Error: {e}")
        sys.exit(1)
