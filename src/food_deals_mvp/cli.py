"""Command-line interface for inspectable offline stages."""

import argparse
import sys
from pathlib import Path

from .models import ImportReport, MediaManifest, Posts
from .preprocessing import normalize
from .storage import error_detail, read_json


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
    reporter.add_argument("--stage", choices=["normalize"], required=True)
    reporter.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    try:
        if args.command == "normalize":
            report = normalize(args.sources, args.data_dir)
        else:
            report = ImportReport.model_validate(
                read_json(args.data_dir / "reports" / "normalize.json")
            )
            if report.status == "success":
                posts = Posts.model_validate(
                    read_json(args.data_dir / "intermediate" / "posts.json")
                )
                media = MediaManifest.model_validate(
                    read_json(args.data_dir / "intermediate" / "media.json")
                )
                if (
                    posts.dataset_id != report.dataset_id
                    or media.dataset_id != report.dataset_id
                ):
                    raise ValueError(
                        "artifact dataset IDs differ; rerun normalize before downstream processing"
                    )
        print_report(report)
        if report.status != "success":
            raise SystemExit(1)
    except (OSError, ValueError) as exc:
        print(f"food-deals-mvp: {error_detail(exc)}", file=sys.stderr)
        raise SystemExit(1) from exc
