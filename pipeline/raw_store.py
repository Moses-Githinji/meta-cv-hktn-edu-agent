"""The raw store: fetched artifacts, content-addressed, outside git.

Layout under var_dir (default var/, gitignored):

    raw/blobs/<sha256[:2]>/<sha256>   # the bytes, once per distinct content
    raw/manifest.json                 # {sha256: {urls, content_type, size,
                                      #           retrieved_at, first_seen,
                                      #           source_page?}}

Identical bytes from different URLs land once (dedupe by SHA-256); every
source URL is recorded on the shared entry. Nothing here is trusted content:
extraction and gates decide what the bytes may become.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _manifest_path(var_dir: Path) -> Path:
    return Path(var_dir) / "raw" / "manifest.json"


def read_manifest(var_dir: Path) -> dict:
    """The manifest ({sha256: entry}); empty when nothing is stored yet."""
    path = _manifest_path(var_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


def _write_manifest(var_dir: Path, manifest: dict) -> None:
    path = _manifest_path(var_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    tmp.replace(path)


def blob_path(var_dir: Path, sha256: str) -> Path:
    return Path(var_dir) / "raw" / "blobs" / sha256[:2] / sha256


def store(
    var_dir: Path,
    body: bytes,
    url: str,
    content_type: str = "",
    retrieved_at: str | None = None,
    source_page: str | None = None,
    robots_exception: bool = False,
) -> dict:
    """Store one fetched artifact; identical bytes dedupe to one blob.

    `source_page` records the authority page a transport-hosted file was
    embedded in; provenance prefers it over the download URL. `robots_exception`
    records an operator-authorized robots bypass (once set, never cleared).
    Returns the manifest entry plus "sha256" and "deduped" (True when the
    bytes were already stored).
    """
    var_dir = Path(var_dir)
    sha256 = hashlib.sha256(body).hexdigest()
    manifest = read_manifest(var_dir)
    entry = manifest.get(sha256)
    if entry is None:
        blob = blob_path(var_dir, sha256)
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(body)
        entry = {
            "urls": [url],
            "content_type": content_type,
            "size": len(body),
            "retrieved_at": retrieved_at or _now(),
            "first_seen": retrieved_at or _now(),
        }
        if source_page:
            entry["source_page"] = source_page
        if robots_exception:
            entry["robots_exception"] = True
        manifest[sha256] = entry
        deduped = False
    else:
        if url not in entry["urls"]:
            entry["urls"].append(url)
        if source_page and entry.get("source_page") != source_page:
            entry["source_page"] = source_page
        if robots_exception:
            entry["robots_exception"] = True
        entry["retrieved_at"] = retrieved_at or _now()
        deduped = True
    _write_manifest(var_dir, manifest)
    return dict(entry, sha256=sha256, deduped=deduped)


def get(var_dir: Path, sha256: str) -> bytes:
    """One blob's bytes, or raise FileNotFoundError."""
    path = blob_path(var_dir, sha256)
    if not path.is_file():
        raise FileNotFoundError(f"no raw artifact {sha256}")
    return path.read_bytes()


def list_artifacts(var_dir: Path) -> list:
    """Every manifest entry, oldest first, each with its sha256."""
    manifest = read_manifest(var_dir)
    entries = [dict(entry, sha256=sha) for sha, entry in manifest.items()]
    return sorted(entries, key=lambda e: e.get("first_seen", ""))
