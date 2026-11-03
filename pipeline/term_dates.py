"""Term-date proposals: read calendar artifacts, propose dates, never write them.

propose(texts, current) scans artifact texts for a Term 1 opening/closing
pair ("5 January 2026" style dates near open/close words) and diffs the
finding against teacher_context/term_calendar.json. The proposal is advisory:
dates stay provisional until the Teacher Reviewer signs them off, so the
pipeline writes a proposal file for a human to apply, never the calendar.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_DATE = re.compile(r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", re.IGNORECASE)
_OPEN = re.compile(r"\b(open|opens|opening|begin|begins|start|starts|reopen|reopens)\b", re.IGNORECASE)
_CLOSE = re.compile(r"\b(clos|end|finish)", re.IGNORECASE)
_HALF = re.compile(r"half[\s-]?term", re.IGNORECASE)


def find_dates(text: str) -> list:
    """(iso_date, sentence) for every "D Month YYYY" date in the text."""
    found = []
    for match in _DATE.finditer(text):
        day, month, year = match.groups()
        iso = f"{int(year):04d}-{MONTHS[month.lower()]:02d}-{int(day):02d}"
        start = max(0, text.rfind(".", 0, match.start()) + 1)
        end = text.find(".", match.end())
        sentence = text[start:end if end != -1 else None].strip()
        found.append((iso, sentence))
    return found


def propose(texts: list, current: dict) -> dict:
    """Propose {opens, closes} from artifact texts; diff against the calendar.

    The earliest date in an opening sentence is the opening; the latest date
    in a closing sentence is the closing. No dates, or dates that contradict
    each other (closing before opening), yield found=False with the spans for
    a human to read.
    """
    openings, closings, spans = [], [], []
    for text in texts:
        for iso, sentence in find_dates(text):
            spans.append({"date": iso, "sentence": sentence})
            if _OPEN.search(sentence):
                openings.append(iso)
            if _CLOSE.search(sentence):
                closings.append(iso)
    opens = min(openings) if openings else None
    closes = max(closings) if closings else None
    calendar = (current.get("calendar") or {})
    proposal = {
        "found": bool(opens and closes and opens < closes),
        "opens": opens,
        "closes": closes,
        "conflicts": [],
        "spans": spans,
    }
    if opens and calendar.get("opens") and opens != calendar["opens"]:
        proposal["conflicts"].append(
            f"opens {opens} vs calendar {calendar['opens']}"
        )
    if closes and calendar.get("closes") and closes != calendar["closes"]:
        proposal["conflicts"].append(
            f"closes {closes} vs calendar {calendar['closes']}"
        )
    if opens and closes and opens >= closes:
        proposal["conflicts"].append(f"opens {opens} is not before closes {closes}")
    return proposal


def current_calendar(root: Path) -> dict:
    """teacher_context/term_calendar.json, or {} when absent."""
    path = Path(root) / "teacher_context" / "term_calendar.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


def write_proposal(var_dir: Path, proposal: dict) -> Path:
    """Save a proposal for human review; return the file. Never touches the calendar."""
    path = Path(var_dir) / "pipeline" / "term_proposal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, indent=1))
    return path
