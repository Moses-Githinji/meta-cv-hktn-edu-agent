#!/usr/bin/env python3
"""The admin dashboard: pass rates, escalations, edit rates, cost, scrape health.

    ./helper dashboard              # text summary over workspace/ + var/
    ./helper dashboard --json       # the same metrics as JSON
    ./helper dashboard --html FILE  # standalone report (open directly, no server)
    ./helper dashboard --alerts     # record threshold alerts for what is wrong

Read-only, except --alerts, which appends to the pipeline alert log. Costs
need var/routing/prices.json; unpriced tokens are reported as unpriced.
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape as html_escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import alerts as pipeline_alerts  # noqa: E402
from routing import registry  # noqa: E402

PASS_RATE_FLOOR = 0.8
OPEN_ESCALATION_LIMIT = 5


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def collect(root: Path, var_dir: Path) -> dict:
    """Every dashboard metric from runs, records, reports, and pipeline state."""
    root, var_dir = Path(root), Path(var_dir)
    runs_dir = root / "workspace/runs"
    records_dir = root / "workspace/case_records"
    metrics: dict = {
        "runs": {"total": 0, "by_status": {}},
        "tokens_by_model": {},
        "input_tokens": 0,
        "output_tokens": 0,
        "independent": {"reports": 0, "passed": 0},
        "escalations": {"total": 0, "open": 0, "by_rule": {}},
        "reviews": {"approved": 0, "rejected": 0, "edited": 0, "memos": {}},
        "figures": 0,
        "lesson_plans": 0,
    }
    run_ids = sorted(p.name for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else []
    for run_id in run_ids:
        progress = _read_json(runs_dir / run_id / "progress.json", None)
        if not isinstance(progress, dict):
            continue
        metrics["runs"]["total"] += 1
        status = progress.get("status", "?")
        metrics["runs"]["by_status"][status] = metrics["runs"]["by_status"].get(status, 0) + 1
        model = progress.get("model", "?")
        usage = metrics["tokens_by_model"].setdefault(model, {"input": 0, "output": 0, "runs": 0})
        usage["runs"] += 1
        for turn in progress.get("turns", []) or []:
            usage["input"] += turn.get("input_tokens", 0) or 0
            usage["output"] += turn.get("output_tokens", 0) or 0
        reports = _read_json(runs_dir / run_id / "independent_verification.json", [])
        if isinstance(reports, list) and reports:
            metrics["independent"]["reports"] += 1
            metrics["independent"]["passed"] += 1 if reports[-1].get("passed") else 0
        record = _read_json(records_dir / f"{run_id}.json", None)
        if not isinstance(record, dict):
            continue
        for request in record.get("requests", []) or []:
            metrics["escalations"]["total"] += 1
            rule = request.get("rule", "?")
            by_rule = metrics["escalations"]["by_rule"]
            by_rule[rule] = by_rule.get(rule, 0) + 1
            if request.get("status") == "open":
                metrics["escalations"]["open"] += 1
        memo = record.get("memo") or {}
        if memo:
            key = f"{memo.get('kind', '?')}/{memo.get('status', '?')}"
            memos = metrics["reviews"]["memos"]
            memos[key] = memos.get(key, 0) + 1
            for review in (memo.get("item_reviews") or {}).values():
                decision = review.get("decision")
                if decision in metrics["reviews"]:
                    metrics["reviews"][decision] += 1
        metrics["figures"] += len(record.get("figures", []) or [])
        metrics["lesson_plans"] += len(record.get("lesson_plans", []) or [])
    for usage in metrics["tokens_by_model"].values():
        metrics["input_tokens"] += usage["input"]
        metrics["output_tokens"] += usage["output"]
    metrics["pass_rate"] = (
        round(metrics["independent"]["passed"] / metrics["independent"]["reports"], 3)
        if metrics["independent"]["reports"]
        else None
    )
    reviewed = metrics["reviews"]["approved"] + metrics["reviews"]["rejected"] + metrics["reviews"]["edited"]
    metrics["reviews"]["edit_rate"] = round(metrics["reviews"]["edited"] / reviewed, 3) if reviewed else None
    metrics["cost"] = _cost(var_dir, metrics["tokens_by_model"])
    metrics["scrape"] = _scrape(root, var_dir)
    return metrics


def _cost(var_dir: Path, tokens_by_model: dict) -> dict:
    total, unpriced = 0.0, 0
    by_model = {}
    for model, usage in tokens_by_model.items():
        price = registry.cost_usd(var_dir, model, usage["input"], usage["output"])
        if price is None:
            unpriced += usage["input"] + usage["output"]
            by_model[model] = {"usd": None, **usage}
        else:
            total += price
            by_model[model] = {"usd": price, **usage}
    return {"usd": round(total, 4), "unpriced_tokens": unpriced, "by_model": by_model}


def _scrape(root: Path, var_dir: Path) -> dict:
    try:
        from pipeline import staleness

        report = staleness.report(root, var_dir)
        fresh, stale = report["fresh"], report["stale"]
    except Exception as error:  # noqa: BLE001  (dashboard never breaks on scrape state)
        fresh, stale = None, [f"staleness unavailable: {error}"]
    logged = pipeline_alerts.list_alerts(var_dir)
    return {
        "fresh": fresh,
        "stale": stale,
        "warnings": sum(1 for e in logged if e.get("severity") == "warning"),
        "errors": sum(1 for e in logged if e.get("severity") == "error"),
        "recent": [
            {k: e.get(k, "") for k in ("at", "severity", "source", "message")}
            for e in logged[-5:]
        ],
    }


def check_alerts(metrics: dict, var_dir: Path) -> list:
    """Threshold alerts for the metrics; records each and returns the messages."""
    messages = []
    rate = metrics.get("pass_rate")
    if rate is not None and rate < PASS_RATE_FLOOR:
        messages.append(("error", f"independent pass rate {rate:.0%} below {PASS_RATE_FLOOR:.0%}"))
    opened = metrics["escalations"]["open"]
    if opened > OPEN_ESCALATION_LIMIT:
        messages.append(("warning", f"{opened} open escalations"))
    if metrics["scrape"]["errors"]:
        messages.append(("error", f"{metrics['scrape']['errors']} pipeline errors logged"))
    for stale in metrics["scrape"]["stale"]:
        messages.append(("warning", f"stale: {stale}"))
    recorded = []
    for severity, message in messages:
        pipeline_alerts.record(var_dir, severity, "dashboard", message)
        recorded.append(f"[{severity}] {message}")
    return recorded


def render_text(metrics: dict) -> str:
    """The metrics as aligned console text."""
    lines = ["Runs: {}".format(metrics["runs"]["total"])]
    for status, count in sorted(metrics["runs"]["by_status"].items()):
        lines.append(f"  {status:<16} {count}")
    rate = metrics["pass_rate"]
    lines.append(
        "Independent pass rate: {}".format(
            f"{rate:.0%} ({metrics['independent']['passed']}/{metrics['independent']['reports']})"
            if rate is not None
            else "no reports yet"
        )
    )
    lines.append(
        "Escalations: {} total, {} open".format(
            metrics["escalations"]["total"], metrics["escalations"]["open"]
        )
    )
    for rule, count in sorted(metrics["escalations"]["by_rule"].items()):
        lines.append(f"  {rule:<20} {count}")
    reviews = metrics["reviews"]
    lines.append(
        "Item reviews: {} approved, {} rejected, {} edited{}".format(
            reviews["approved"], reviews["rejected"], reviews["edited"],
            f" (edit rate {reviews['edit_rate']:.0%})" if reviews["edit_rate"] is not None else "",
        )
    )
    for memo, count in sorted(reviews["memos"].items()):
        lines.append(f"  memo {memo:<24} {count}")
    cost = metrics["cost"]
    lines.append(
        "Cost: ${:.4f} ({} in / {} out tokens{})".format(
            cost["usd"], metrics["input_tokens"], metrics["output_tokens"],
            f", {cost['unpriced_tokens']} unpriced" if cost["unpriced_tokens"] else "",
        )
    )
    scrape = metrics["scrape"]
    lines.append(
        "Scrape: {}".format(
            "fresh"
            if scrape["fresh"]
            else "stale: " + "; ".join(scrape["stale"]) if scrape["fresh"] is False else "unknown"
        )
    )
    lines.append(
        "Alerts logged: {} warnings, {} errors".format(scrape["warnings"], scrape["errors"])
    )
    lines.append(f"Figures: {metrics['figures']}, lesson plans: {metrics['lesson_plans']}")
    return "\n".join(lines)


def render_html(metrics: dict) -> str:
    """The metrics as a standalone HTML report (no server, no dependencies)."""
    def row(label: str, value: str) -> str:
        return f"<tr><th scope='row'>{html_escape(label)}</th><td>{html_escape(value)}</td></tr>"

    def pill(text: str, tone: str) -> str:
        return f"<span class='pill {html_escape(tone)}'>{html_escape(text)}</span>"

    rate = metrics["pass_rate"]
    if rate is None:
        verdict = pill("no reports", "grey")
    elif rate >= PASS_RATE_FLOOR:
        verdict = pill(f"{rate:.0%} pass", "green")
    else:
        verdict = pill(f"{rate:.0%} pass", "red")
    scrape = metrics["scrape"]
    scrape_pill = (
        pill("fresh", "green") if scrape["fresh"]
        else pill("stale", "red") if scrape["fresh"] is False else pill("unknown", "grey")
    )
    by_status = "".join(
        row(status, str(count)) for status, count in sorted(metrics["runs"]["by_status"].items())
    )
    by_rule = "".join(
        row(rule, str(count)) for rule, count in sorted(metrics["escalations"]["by_rule"].items())
    ) or row("none", "0")
    memos = "".join(
        row(memo, str(count)) for memo, count in sorted(metrics["reviews"]["memos"].items())
    ) or row("none", "0")
    stale = "".join(f"<li>{html_escape(s)}</li>" for s in scrape["stale"]) or "<li>None</li>"
    recent = "".join(
        f"<li>[{html_escape(e['severity'])}] {html_escape(e['source'])}: "
        f"{html_escape(e['message'])}</li>"
        for e in scrape["recent"]
    ) or "<li>None</li>"
    cost = metrics["cost"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Teaching agent - admin dashboard</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #1a1a1a;
         max-width: 860px; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  h2 {{ font-size: 1.05rem; margin: 1.75rem 0 0.5rem; border-bottom: 2px solid #1a1a1a;
       padding-bottom: 0.25rem; }}
  p.sub {{ color: #444; margin-top: 0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: 0.35rem 0.5rem; border-top: 1px solid #ddd;
            font-variant-numeric: tabular-nums; }}
  th[scope='row'] {{ font-weight: 600; width: 60%; }}
  td {{ text-align: right; }}
  .pill {{ display: inline-block; padding: 0.1rem 0.6rem; border-radius: 999px;
           font-size: 0.85rem; font-weight: 600; }}
  .green {{ background: #dff0d8; color: #1e6b2e; }}
  .red {{ background: #f8d7da; color: #8f1d26; }}
  .grey {{ background: #e8e8e8; color: #444; }}
  ul {{ padding-left: 1.25rem; }}
</style>
</head>
<body>
<h1>Admin dashboard</h1>
<p class="sub">{metrics["runs"]["total"]} runs &middot; {metrics["input_tokens"]} in / \
{metrics["output_tokens"]} out tokens</p>
<h2>Verification {verdict}</h2>
<table><tbody>{by_status}</tbody></table>
<h2>Escalations ({metrics["escalations"]["open"]} open)</h2>
<table><tbody>{by_rule}</tbody></table>
<h2>Reviews</h2>
<table><tbody>{memos}</tbody></table>
<h2>Cost</h2>
<table><tbody>{row("Total (USD)", f"${cost['usd']:.4f}")}\
{row("Unpriced tokens", str(cost["unpriced_tokens"]))}</tbody></table>
<h2>Scrape health {scrape_pill}</h2>
<ul>{stale}</ul>
<p>{scrape["warnings"]} warnings, {scrape["errors"]} errors logged.</p>
<h2>Recent alerts</h2>
<ul>{recent}</ul>
</body>
</html>
"""


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--var-dir", default=str(ROOT / "var"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--html", default="", metavar="FILE")
    parser.add_argument("--alerts", action="store_true", help="record threshold alerts")
    args = parser.parse_args(argv)
    metrics = collect(Path(args.root), Path(args.var_dir))
    if args.alerts:
        for message in check_alerts(metrics, Path(args.var_dir)):
            print(f"ALERT {message}")
    if args.html:
        Path(args.html).write_text(render_html(metrics))
        print(f"dashboard -> {args.html}")
    if args.json:
        print(json.dumps(metrics, indent=1))
    elif not args.html:
        print(render_text(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
