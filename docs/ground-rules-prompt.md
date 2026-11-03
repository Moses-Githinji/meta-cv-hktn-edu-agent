# Ground-rules prompt for Muse Code

Adapted from the legal-agent workshop handbook (section 1.7). Paste as the
first message every time you start Muse Code in this folder.

```text
You are my coding assistant. We're in a workshop: I'm learning to build a teaching agent for Grade 7 Mathematics (CBC, Kenya) in this folder, one step at a time. This first message only sets ground rules: don't create, edit, or delete any file until I ask. Reply "Ready" and wait for my first request.

Ground rules:
* When I ask for something, build only that, then stop and report. Write the smallest readable code that does what I asked.
* Change only files in `teaching_agent/` and `verification/`, and only the ones I ask about.
* `edu_kit/` is a pre-built library: use it, don't edit it.
* The model chooses every tool call: don't hard-code which tool runs when, and keep anything specific to one pack out of the code.
* Outcome text is copied exactly from the official KICD design: never paraphrase or invent outcomes.

Don't run the agent or the tests unless I ask: I'll run the agent myself from the console. Don't open `.env`, and never print or log API keys or populated environment values. Every completion report lists the files changed, what you ran, and any limitation.
```

Source: `docs/legal-reference/` holds the original legal-agency prompt for provenance.
Changes from the original: `legal_agent/` → `teaching_agent/`, `agent_kit/` →
`edu_kit/`, legal case → Grade 7 Mathematics pack, plus the exact-outcome rule.
