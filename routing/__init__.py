"""Model routing: which model does what, and what it costs.

table.py holds the static role table (agent, judge) and enforces the one
hard rule: the judge never equals the generator. performance.py learns
per-model pass rates from recorded outcomes for later promotion.
shadow.py runs a second model beside the primary and logs agreement.
registry.py names the known models; prices come from var/routing/prices.json
(set yours: no invented defaults).
"""

from __future__ import annotations
