"""Shared plumbing for the teaching agent. Use it; do not edit it.

- client:        the Meta Model API client: the OpenAI Python SDK, pointed at api.meta.ai.
- progress:      a run on disk (new_run, save_progress, load_progress), resume after a
                 person acts, and branch (continue a run from its checklist, verification on).
- tools/:        one file per tool: what the model sees and what happens when it calls it.
                 tools.definitions() and tools.run() are all the loop needs.
- case_record:   the record system the agent acts on (Phase 2 renames this to teaching_record).
- document_text: each document's saved text, the source of truth every quote is checked against.
- settings:      MODEL_API_MODEL, SAM_MODEL, VERIFICATION, TEACHING_PACK_DIR.
"""
