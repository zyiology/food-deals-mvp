"""Command-line interface for inspectable offline stages."""

import argparse
import sys
from pathlib import Path

from .extraction import extract, load_extraction_report
from .models import ImportReport
from .openrouter import Settings
from .preprocessing import normalize
from .storage import error_detail, load_normalized, read_json


def print_report(report: ImportReport) -> None:
    print(f"normalize: {report.status} (dataset {report.dataset_id[:12]})")
    for key, value in report.counts.items():
        print(f"  {key}: {value}")
    for issue in report.errors:
        target = (
            f"{issue.source}:{issue.message_id}" if issue.message_id else issue.source
        )
        print(f"  ERROR {issue.code} [{target}]: {issue.detail}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline Telegram food-deal processing"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    importer = subcommands.add_parser(
        "normalize", help="Normalize the configured Telegram exports"
    )
    importer.add_argument(
        "--sources",
        type=Path,
        default=Path("config/sources.json"),
        help="Configuration file; export roots are relative to this file",
    )
    importer.add_argument("--data-dir", type=Path, default=Path("data"))
    reporter = subcommands.add_parser(
        "report", help="Inspect the most recent normalization report"
    )
    reporter.add_argument("--stage", choices=["normalize", "extract"], required=True)
    reporter.add_argument("--data-dir", type=Path, default=Path("data"))
    extractor = subcommands.add_parser(
        "extract", help="Extract caption-grounded food offers"
    )
    extractor.add_argument("--data-dir", type=Path, default=Path("data"))
    extractor.add_argument(
        "--settings", type=Path, help="Optional JSON OpenRouter settings"
    )
    extractor.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect selection/cache without network or writes",
    )
    extractor.add_argument(
        "--post-ids", type=Path, help="Balanced 30-post pilot JSON ID array"
    )
    extractor.add_argument("--limit", type=int)
    rerun = extractor.add_mutually_exclusive_group()
    rerun.add_argument(
        "--resume", action="store_true", help="Retry failed or interrupted requests"
    )
    rerun.add_argument(
        "--refresh",
        action="store_true",
        help="Request fresh results for selected posts",
    )
    extractor.add_argument(
        "--corrections", type=Path, help="Reviewed field corrections JSON"
    )
    extractor.add_argument(
        "--pilot-review",
        type=Path,
        help="Reviewed pilot approval required for full-batch requests",
    )
    args = parser.parse_args()
    try:
        if args.command == "extract" or (
            args.command == "report" and args.stage == "extract"
        ):
            if args.command == "extract":
                settings = (
                    Settings.model_validate(read_json(args.settings))
                    if args.settings
                    else Settings()
                )
                extraction_report = extract(
                    args.data_dir,
                    settings,
                    dry_run=args.dry_run,
                    post_ids=args.post_ids,
                    limit=args.limit,
                    resume=args.resume,
                    refresh=args.refresh,
                    corrections_path=args.corrections,
                    pilot_review=args.pilot_review,
                )
            else:
                extraction_report = load_extraction_report(args.data_dir)
            print(
                f"extract: {extraction_report.status} (dataset {extraction_report.dataset_id[:12]})"
            )
            for key, value in extraction_report.counts.items():
                print(f"  {key}: {value}")
            print(f"  budget: {extraction_report.budget}")
            for error in extraction_report.errors:
                print(f"  ERROR: {error}", file=sys.stderr)
            if (
                extraction_report.status == "failed"
                or any(
                    extraction_report.counts.get(f"status_{state}", 0)
                    for state in ("failed", "pending")
                )
                and extraction_report.status != "dry_run"
            ):
                raise SystemExit(1)
            return
        if args.command == "normalize":
            report = normalize(args.sources, args.data_dir)
        else:
            report = ImportReport.model_validate(
                read_json(args.data_dir / "reports" / "normalize.json")
            )
            if report.status == "success":
                load_normalized(args.data_dir)
        print_report(report)
        if report.status != "success":
            raise SystemExit(1)
    except (OSError, ValueError) as exc:
        print(f"food-deals-mvp: {error_detail(exc)}", file=sys.stderr)
        raise SystemExit(1) from exc
