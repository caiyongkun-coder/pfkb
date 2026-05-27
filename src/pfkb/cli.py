from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
import sys

from .inventory import Inventory
from .parse import extract_jobs, plan_parse_jobs_from_records, write_manifest
from .policy import PolicyEngine
from .report import write_access_log, write_scan_plan
from .roots import discover_candidate_roots
from .scan import scan_paths


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="pfkb", description="Personal File Knowledge Base MVP0 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Create a privacy-first dry-run scan plan")
    scan.add_argument("roots", nargs="+", help="Root directories or files to scan")
    scan.add_argument("--privacy", default="configs/privacy.example.yaml", help="Privacy policy YAML")
    scan.add_argument("--excludes", default="configs/excludes.default.yaml", help="Default excludes YAML")
    scan.add_argument("--out", default="data", help="Output directory")
    scan.add_argument("--inventory", default=None, help="SQLite inventory path")
    scan.add_argument("--max-entries", type=int, default=None, help="Stop after N entries")
    scan.add_argument("--follow-symlinks", action="store_true", help="Follow symlinked directories")
    scan.add_argument("--no-inventory", action="store_true", help="Do not write inventory.sqlite")
    scan.set_defaults(func=cmd_scan)

    status = subparsers.add_parser("status", help="Show inventory status")
    status.add_argument("--inventory", default="data/inventory.sqlite", help="SQLite inventory path")
    status.add_argument("--sources", action="store_true", help="Show top policy sources")
    status.set_defaults(func=cmd_status)

    list_cmd = subparsers.add_parser("list", help="List inventory records")
    list_cmd.add_argument("--inventory", default="data/inventory.sqlite", help="SQLite inventory path")
    list_cmd.add_argument("--policy", default=None, help="Filter by access policy")
    list_cmd.add_argument("--limit", type=int, default=20, help="Maximum records to show")
    list_cmd.add_argument("--files-only", action="store_true", help="Hide directories")
    list_cmd.add_argument("--json", action="store_true", help="Emit JSON")
    list_cmd.set_defaults(func=cmd_list)

    show = subparsers.add_parser("show", help="Show one inventory record by path")
    show.add_argument("path", help="Path recorded in inventory")
    show.add_argument("--inventory", default="data/inventory.sqlite", help="SQLite inventory path")
    show.add_argument("--json", action="store_true", help="Emit JSON")
    show.set_defaults(func=cmd_show)

    roots = subparsers.add_parser("roots", help="Show suggested personal scan roots")
    roots.add_argument("--include-missing", action="store_true", help="Also show roots that do not exist")
    roots.add_argument("--json", action="store_true", help="Emit JSON")
    roots.set_defaults(func=cmd_roots)

    extract = subparsers.add_parser("extract", help="Extract content for inventory records allowed by policy")
    extract.add_argument("--inventory", default="data/inventory.sqlite", help="SQLite inventory path")
    extract.add_argument("--out", default="data/extract", help="Extraction output directory")
    extract.add_argument("--limit", type=int, default=100, help="Maximum inventory records to inspect")
    extract.add_argument("--manifest", default=None, help="Manifest JSONL path")
    extract.add_argument("--force", action="store_true", help="Re-extract even when source appears unchanged")
    extract.add_argument("--retry-failed", action="store_true", help="Only retry records whose latest extraction failed or skipped")
    extract.set_defaults(func=cmd_extract)

    extracts = subparsers.add_parser("extracts", help="List extraction results stored in inventory")
    extracts.add_argument("--inventory", default="data/inventory.sqlite", help="SQLite inventory path")
    extracts.add_argument("--status", default=None, help="Filter by extraction status")
    extracts.add_argument("--parser", default=None, help="Filter by parser")
    extracts.add_argument("--path", default=None, help="Filter by source path")
    extracts.add_argument("--limit", type=int, default=20, help="Maximum records to show")
    extracts.add_argument("--json", action="store_true", help="Emit JSON")
    extracts.add_argument("--stats", action="store_true", help="Show status counts (default)")
    extracts.add_argument("--no-stats", action="store_true", help="Hide status counts")
    extracts.set_defaults(func=cmd_extracts)

    return parser


def cmd_scan(args) -> int:
    out_dir = Path(args.out)
    inventory_path = Path(args.inventory) if args.inventory else out_dir / "inventory.sqlite"
    policy = PolicyEngine.from_files(_optional_path(args.privacy), _optional_path(args.excludes))

    result = scan_paths(
        args.roots,
        policy,
        dry_run=True,
        follow_symlinks=args.follow_symlinks,
        max_entries=args.max_entries,
    )

    plan_path = out_dir / "scan-plan.md"
    log_path = out_dir / "access-log.jsonl"
    write_scan_plan(result, plan_path)
    write_access_log(result, log_path)

    inventory_count = 0
    if not args.no_inventory:
        with Inventory(inventory_path) as inventory:
            inventory_count = inventory.upsert_entries(result.entries)

    print(f"scan-plan: {plan_path}")
    print(f"access-log: {log_path}")
    if not args.no_inventory:
        print(f"inventory: {inventory_path} ({inventory_count} entries)")
    for key, value in result.stats.as_dict().items():
        print(f"{key}: {value}")
    if result.errors:
        print("errors:")
        for error in result.errors[:20]:
            print(f"- {error}")
    return 0 if not result.errors else 2


def cmd_status(args) -> int:
    inventory_path = Path(args.inventory)
    if not inventory_path.exists():
        print(f"inventory not found: {inventory_path}", file=sys.stderr)
        return 2
    with Inventory(inventory_path) as inventory:
        stats = inventory.stats()
        source_stats = inventory.source_stats() if args.sources else []
    if not stats:
        print("inventory is empty")
        return 0
    for policy, count in sorted(stats.items()):
        print(f"{policy}: {count}")
    if args.sources:
        print("policy_sources:")
        for source, count in source_stats:
            print(f"- {source}: {count}")
    return 0


def cmd_list(args) -> int:
    inventory_path = Path(args.inventory)
    if not inventory_path.exists():
        print(f"inventory not found: {inventory_path}", file=sys.stderr)
        return 2
    with Inventory(inventory_path) as inventory:
        records = inventory.list_files(
            limit=args.limit,
            access_policy=args.policy,
            include_dirs=not args.files_only,
        )
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    for record in records:
        kind = "dir" if record["is_dir"] else "file"
        print(f"{record['access_policy']}\t{kind}\t{record['path']}")
    return 0


def cmd_show(args) -> int:
    inventory_path = Path(args.inventory)
    if not inventory_path.exists():
        print(f"inventory not found: {inventory_path}", file=sys.stderr)
        return 2
    with Inventory(inventory_path) as inventory:
        record = inventory.get_file(args.path)
    if record is None:
        print(f"record not found: {args.path}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    for key, value in record.items():
        print(f"{key}: {value}")
    return 0


def cmd_roots(args) -> int:
    roots = discover_candidate_roots(existing_only=not args.include_missing)
    payload = [
        {
            "name": root.name,
            "path": str(root.path),
            "exists": root.exists,
            "source": root.source,
        }
        for root in roots
    ]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for root in roots:
        status = "exists" if root.exists else "missing"
        print(f"{root.name}\t{status}\t{root.path}")
    return 0


def cmd_extract(args) -> int:
    inventory_path = Path(args.inventory)
    if not inventory_path.exists():
        print(f"inventory not found: {inventory_path}", file=sys.stderr)
        return 2
    output_dir = Path(args.out)
    manifest_path = Path(args.manifest) if args.manifest else output_dir / "extract-manifest.jsonl"
    with Inventory(inventory_path) as inventory:
        records = inventory.list_files(limit=args.limit, include_dirs=False)
        latest_success = inventory.latest_success_by_path()
        latest = inventory.latest_extracts_by_path()
    plan = plan_parse_jobs_from_records(
        records,
        latest_success_by_path=latest_success,
        latest_by_path=latest,
        force=args.force,
        retry_failed=args.retry_failed,
    )
    extracted = extract_jobs(plan.jobs, output_dir)
    results = [*plan.skipped, *extracted]
    write_manifest(results, manifest_path)
    with Inventory(inventory_path) as inventory:
        stored_count = inventory.add_extract_results(results)
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    print(f"jobs: {len(plan.jobs)}")
    print(f"planned: {len(plan.jobs)}")
    print(f"skipped: {len(plan.skipped)}")
    print(f"manifest: {manifest_path}")
    print(f"stored: {stored_count}")
    for status, count in sorted(counts.items()):
        print(f"{status}: {count}")
    return 0 if not any(result.status == "error" for result in results) else 1


def cmd_extracts(args) -> int:
    inventory_path = Path(args.inventory)
    if not inventory_path.exists():
        print(f"inventory not found: {inventory_path}", file=sys.stderr)
        return 2
    with Inventory(inventory_path) as inventory:
        stats = {} if args.no_stats else inventory.extract_stats()
        records = inventory.list_extracts(
            limit=args.limit,
            status=args.status,
            parser=args.parser,
            path=args.path,
        )
    if args.json:
        payload = {"stats": stats, "records": records}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not args.no_stats:
        print("extract_status:")
        if stats:
            for status, count in sorted(stats.items()):
                print(f"- {status}: {count}")
        else:
            print("- empty: 0")
    for record in records:
        print(
            f"{record['status']}\t{record['parser']}\t{record['path']}\t{record.get('output_path') or ''}"
        )
    return 0


def _optional_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str(path) if path.exists() else None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
