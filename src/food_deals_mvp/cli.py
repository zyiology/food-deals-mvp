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
    reporter.add_argument(
        "--stage", choices=["normalize", "extract", "geocode"], required=True
    )
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
        "--accept-demo",
        action="store_true",
        help="Explicitly continue demo extraction without exhaustive pilot approval",
    )
    reviewer = subcommands.add_parser(
        "review-demo", help="Rebuild saved extractions offline and render review cards"
    )
    reviewer.add_argument("--data-dir", type=Path, default=Path("data"))
    reviewer.add_argument(
        "--sources",
        type=Path,
        default=Path("config/sources.json"),
        help="Source configuration for optional review images",
    )
    extractor.add_argument(
        "--pilot-review",
        type=Path,
        help="Legacy exhaustive pilot approval (alternative to --accept-demo)",
    )
    geocoder = subcommands.add_parser(
        "geocode", help="Resolve selected demo venues for pin review"
    )
    publisher = subcommands.add_parser(
        "publish", help="Publish reviewed mapped demo rows offline"
    )
    for stage in (geocoder, publisher):
        stage.add_argument("--data-dir", type=Path, default=Path("data"))
        stage.add_argument("--selection", type=Path, required=True)
        stage.add_argument("--decisions", type=Path)
    geocoder.add_argument(
        "--settings", type=Path, help="JSON Nominatim settings including user_agent"
    )
    geocoder.add_argument("--dry-run", action="store_true")
    geo_mode = geocoder.add_mutually_exclusive_group()
    geo_mode.add_argument("--offline", action="store_true")
    geo_mode.add_argument("--resume", action="store_true")
    geo_mode.add_argument(
        "--refresh-query", help="Refresh one selected query by its cache key"
    )
    publisher.add_argument("--allow-partial", action="store_true")
    publisher.add_argument("--sources", type=Path, default=Path("config/sources.json"))
    args = parser.parse_args()
    try:
        if args.command == "publish":
            from .publishing import publish

            snapshot = publish(
                args.data_dir,
                args.selection,
                allow_partial=args.allow_partial,
                decisions_path=args.decisions,
                sources_path=args.sources,
            )
            print(
                f"publish: {len(snapshot.deals)} mapped rows (dataset {snapshot.dataset_id[:12]})"
            )
            return
        if args.command == "geocode" or (
            args.command == "report" and args.stage == "geocode"
        ):
            from .geocoding import geocode, load_geocoding_report
            from .geocoding_models import GeocodingSettings

            if args.command == "geocode":
                settings_path = (
                    args.settings or args.data_dir / "geocoding-settings.json"
                )
                geo_settings = (
                    GeocodingSettings.model_validate(read_json(settings_path))
                    if args.settings is not None or settings_path.exists()
                    else GeocodingSettings()
                )
                geo_report = geocode(
                    args.data_dir,
                    args.selection,
                    geo_settings,
                    decisions_path=args.decisions,
                    dry_run=args.dry_run,
                    offline=args.offline,
                    resume=args.resume,
                    refresh_query=args.refresh_query,
                )
            else:
                geo_report, _ = load_geocoding_report(args.data_dir)
            print(
                f"geocode: {geo_report.status} (dataset {geo_report.dataset_id[:12]})"
            )
            for key, value in geo_report.counts.items():
                print(f"  {key}: {value}")
            for error in geo_report.errors:
                print(f"  ERROR: {error}", file=sys.stderr)
            if geo_report.errors or geo_report.status == "failed":
                raise SystemExit(1)
            return
        if args.command == "review-demo":
            from .demo_review import build_demo_review

            print(build_demo_review(args.data_dir, args.sources))
            return
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
                    accept_demo=args.accept_demo,
                    progress=lambda message: print(message, file=sys.stderr, flush=True),
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
