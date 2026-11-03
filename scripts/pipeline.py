#!/usr/bin/env python3
"""The curriculum data pipeline: fetch, extract, gate, publish, refresh.

    ./helper pipeline fetch URL                 # fetch one allowlisted URL into the raw store
    ./helper pipeline discover URL [--slug S]   # list PDFs and Drive files from one page
    ./helper pipeline drive-download ID --from PAGE [--drive-robots-exception]
                                                 # download a Drive file an authority page embeds
    ./helper pipeline extract SHA               # show an artifact's extracted records
    ./helper pipeline gates                     # gate the candidate built from stored artifacts
    ./helper pipeline diff                      # diff that candidate against the live pack
    ./helper pipeline publish --reviewed-by ME  # gate, back up, and publish (human required)
    ./helper pipeline rollback [VERSION]        # restore a backed-up pack
    ./helper pipeline staleness                 # pack and source freshness
    ./helper pipeline refresh                   # scheduled run: fetch seeds, extract, gate, report
    ./helper pipeline schedule [--interval-days N]
    ./helper pipeline propose-dates             # propose term dates from calendar artifacts
    ./helper pipeline alerts                    # list recorded failures

Local data lives in var/ (gitignored): raw blobs + manifest, pack history,
quarantine, schedule, alerts. Nothing publishes without the gates and a
named human reviewer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import alerts, discover, extract, gates, raw_store, schedule, staleness, term_dates  # noqa: E402
from pipeline.diff import diff_packs  # noqa: E402
from pipeline.drive import DriveError, download as drive_dl, export_url as drive_export_url  # noqa: E402
from pipeline.extract import ExtractionError  # noqa: E402
from pipeline.fetch import FetchError, RateLimiter, fetch_url  # noqa: E402
from pipeline.publish import (  # noqa: E402
    PublishError,
    build_candidate,
    history,
    load_current,
    publish,
    rollback,
)
from pipeline.sources import SourceError, check as sources_check, is_authority  # noqa: E402


def discover_page(url: str, var_dir: Path, transport=None) -> dict:
    """Fetch a page into the raw store; report its PDF links and Drive embeds."""
    body, _ = fetch_url(url, transport=transport, rate_limiter=RateLimiter(var_dir / "raw"))
    entry = raw_store.store(var_dir, body, url, "text/html")
    text = body.decode("utf-8", errors="replace")
    links, dropped = [], []
    for link in discover.pdf_links(text, url):
        try:
            sources_check(link)
        except SourceError as error:
            dropped.append({"url": link, "reason": str(error)})
        else:
            links.append(link)
    return {
        "page": url,
        "sha256": entry["sha256"],
        "pdf_links": links,
        "drive_files": [
            {"id": file_id, "download_url": drive_export_url(file_id)}
            for file_id in discover.drive_files(text)
        ],
        "dropped": dropped,
    }


def drive_download(
    file_id: str,
    source_page: str,
    var_dir: Path,
    transport=None,
    robots_exception: bool = False,
) -> dict:
    """Download a Drive file embedded in an authority page; store with provenance.

    The authority stays the embedding page: it is recorded as the artifact's
    source_page (and the gate input), while the manifest keeps the Drive
    download URL for audit. `robots_exception` (the CLI flag) bypasses only
    the robots check for the /uc endpoint and is recorded on the artifact.
    """
    try:
        if not is_authority(source_page):
            raise DriveError(
                f"--from must be an authority page, not {source_page!r}: "
                f"only an official page can vouch for the file's wording"
            )
    except SourceError as error:
        raise DriveError(str(error)) from None
    body, content_type = drive_dl(
        file_id,
        transport=transport,
        rate_limiter=RateLimiter(var_dir / "raw"),
        robots_exception=robots_exception,
    )
    entry = raw_store.store(
        var_dir, body, drive_export_url(file_id), content_type,
        source_page=source_page,
        robots_exception=robots_exception,
    )
    return dict(entry, source_page=source_page, robots_exception=robots_exception)


def _candidate(root: Path, var_dir: Path) -> tuple:
    """The candidate pack from every stored artifact (skipping failures loudly)."""
    records = []
    for artifact in raw_store.list_artifacts(var_dir):
        url = artifact.get("source_page") or (artifact.get("urls") or ["?"])[0]
        try:
            records.extend(
                extract.extract(
                    raw_store.get(var_dir, artifact["sha256"]),
                    artifact.get("content_type", ""),
                    url,
                    artifact.get("retrieved_at", ""),
                    artifact["sha256"],
                )
            )
        except ExtractionError as error:
            print(f"skip {artifact['sha256'][:12]} ({url}): {error}", file=sys.stderr)
    current = load_current(root)
    candidate, unmapped = build_candidate(current, records)
    for record in unmapped:
        print(
            f"unmapped record {record.get('outcome_id')}: no such outcome in the pack",
            file=sys.stderr,
        )
    return candidate, current, records


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--var-dir", default=str(ROOT / "var"))
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch one URL into the raw store")
    fetch.add_argument("url")

    disc = sub.add_parser(
        "discover", help="list PDFs and Drive files from one allowlisted page"
    )
    disc.add_argument("url", nargs="?")
    disc.add_argument(
        "--slug",
        help="KICD design-page slug (e.g. grade-seven-designs) instead of a URL",
    )

    dl = sub.add_parser(
        "drive-download",
        help="download a Drive file embedded in an authority page",
    )
    dl.add_argument("file_id")
    dl.add_argument("--from", dest="source_page", required=True)
    dl.add_argument(
        "--drive-robots-exception",
        action="store_true",
        help="bypass the robots check for this download only "
        "(Drive disallows /uc; the bypass is recorded on the artifact)",
    )

    show = sub.add_parser("extract", help="show one artifact's records")
    show.add_argument("sha")

    sub.add_parser("gates", help="gate the candidate from stored artifacts")
    sub.add_parser("diff", help="diff that candidate against the live pack")

    pub = sub.add_parser("publish", help="gate, back up, and publish")
    pub.add_argument("--reviewed-by", default="")

    back = sub.add_parser("rollback", help="restore a backed-up pack")
    back.add_argument("version", nargs="?")

    stale = sub.add_parser("staleness", help="pack and source freshness")
    stale.add_argument("--max-age-days", type=int, default=staleness.DEFAULT_MAX_AGE_DAYS)

    sub.add_parser("refresh", help="fetch seeds, extract, gate, report")

    sched = sub.add_parser("schedule", help="show or set the refresh schedule")
    sched.add_argument("--interval-days", type=int, default=None)

    sub.add_parser("propose-dates", help="propose term dates from artifacts")
    alerts_cmd = sub.add_parser("alerts", help="list recorded failures")
    alerts_cmd.add_argument("--severity", choices=("warning", "error"), default=None)

    args = parser.parse_args(argv)
    root, var_dir = Path(args.root), Path(args.var_dir)
    try:
        if args.command == "fetch":
            body, content_type = fetch_url(
                args.url, rate_limiter=RateLimiter(var_dir / "raw")
            )
            entry = raw_store.store(var_dir, body, args.url, content_type)
            print(json.dumps(entry, indent=1))
        elif args.command == "discover":
            if bool(args.url) == bool(args.slug):
                print("discover needs exactly one of URL and --slug", file=sys.stderr)
                return 1
            url = (
                discover.wp_page_url("https://kicd.ac.ke", args.slug)
                if args.slug
                else args.url
            )
            print(json.dumps(discover_page(url, var_dir), indent=1))
        elif args.command == "drive-download":
            print(
                json.dumps(
                    drive_download(
                        args.file_id,
                        args.source_page,
                        var_dir,
                        robots_exception=args.drive_robots_exception,
                    ),
                    indent=1,
                )
            )
        elif args.command == "extract":
            entry = raw_store.read_manifest(var_dir).get(args.sha)
            if entry is None:
                print(f"no raw artifact {args.sha}", file=sys.stderr)
                return 1
            records = extract.extract(
                raw_store.get(var_dir, args.sha),
                entry.get("content_type", ""),
                (entry.get("urls") or ["?"])[0],
                entry.get("retrieved_at", ""),
                args.sha,
            )
            print(json.dumps(records, indent=1))
        elif args.command == "gates":
            candidate, current, records = _candidate(root, var_dir)
            verdict = gates.run_all(candidate, current, records)
            print("GATES " + ("pass" if verdict["passed"] else "fail"))
            for gate, msgs in verdict["failures"].items():
                for msg in msgs:
                    print(f"  {gate}: {msg}")
            return 0 if verdict["passed"] else 1
        elif args.command == "diff":
            candidate, current, _ = _candidate(root, var_dir)
            print(json.dumps(diff_packs(current, candidate), indent=1))
        elif args.command == "publish":
            candidate, _, records = _candidate(root, var_dir)
            receipt = publish(root, var_dir, candidate, records, args.reviewed_by)
            print(json.dumps(receipt, indent=1))
        elif args.command == "rollback":
            receipt = rollback(root, var_dir, args.version)
            print(json.dumps(receipt, indent=1))
            print(f"restored pack version {receipt['version']}")
        elif args.command == "staleness":
            print(json.dumps(staleness.report(root, var_dir, args.max_age_days), indent=1))
        elif args.command == "refresh":
            report = schedule.refresh(root, var_dir)
            print("REFRESH " + ("ok" if report["ok"] else "FAILED"))
            print(f"  fetched: {len(report['fetched'])}, records: {report['records']}")
            for gate, msgs in report["verdict"]["failures"].items():
                for msg in msgs:
                    print(f"  {gate}: {msg}")
            for warning in report["warnings"]:
                print(f"  warning: {warning}")
            return 0 if report["ok"] else 1
        elif args.command == "schedule":
            if args.interval_days is not None:
                sched_state = schedule.write_schedule(var_dir, interval_days=args.interval_days)
            else:
                sched_state = schedule.read_schedule(var_dir)
            print(json.dumps({**sched_state, "due": schedule.due(var_dir)}, indent=1))
        elif args.command == "propose-dates":
            texts = []
            for artifact in raw_store.list_artifacts(var_dir):
                try:
                    texts.append(
                        raw_store.get(var_dir, artifact["sha256"]).decode("utf-8")
                    )
                except UnicodeDecodeError:
                    continue
            proposal = term_dates.propose(texts, term_dates.current_calendar(root))
            path = term_dates.write_proposal(var_dir, proposal)
            print(json.dumps(proposal, indent=1))
            print(f"proposal written to {path} (human applies it)")
        elif args.command == "alerts":
            for entry in alerts.list_alerts(var_dir, args.severity):
                print(f"{entry['at']} [{entry['severity']}] {entry['source']}: {entry['message']}")
    except (FetchError, SourceError, ExtractionError, PublishError) as error:
        print(f"{args.command} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
