"""The pipeline package: fetch curriculum artifacts, extract outcome records,
gate them, and publish pack updates. Stdlib only.

Pipeline order: sources (allowlist) -> fetch -> raw_store -> extract ->
gates/diff -> publish. schedule/term_dates/alerts support the refresh loop.
Nothing here touches the network in tests: fetch takes an injectable
transport, and the tests use a fake one.
"""

from __future__ import annotations
