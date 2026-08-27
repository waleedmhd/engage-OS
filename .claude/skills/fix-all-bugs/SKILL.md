---
name: fix-all-bugs
description: Patch unpatched bugs from bugs.txt. Use PROACTIVELY when the user asks to fix bugs, mentions bugs.txt, or says "fix the bugs." Default scope is CRITICAL + IMPORTANT; use ALL scope only when the user explicitly says "all bugs," "every bug," or "including minor." Also invoke after a code review that surfaces bugs from bugs.txt entries. For ALL scope, patches CRITICAL, IMPORTANT, and MINOR. For default scope, patches CRITICAL and IMPORTANT only and lists deferred MINOR items at the end.
---

# Fixing bugs from bugs.txt

Patch unpatched entries in `bugs.txt`. Default to CRITICAL + IMPORTANT scope unless the user explicitly asks for ALL (which adds MINOR).

## Scope

- **Default (CRITICAL + IMPORTANT):** every unpatched entry under a `CRITICAL` or `IMPORTANT` subsection.
- **ALL scope:** additionally include every unpatched `MINOR` entry.
- **Skip:** entries already marked `[PATCHED YYYY-MM-DD]` or `[VERIFIED NOT A BUG ...]`.

Work in order CRITICAL -> IMPORTANT -> MINOR within each layer so the highest-impact fixes land first.

## Binding constraints

All fixes MUST respect the project's architectural invariants. Before editing, read
`C:\Users\HP\.claude\projects\D--Documents-Claude-WA-CRM\memory\architectural_invariants.md`
and follow it — especially: 7-file module layout, `router -> service -> repository` dependency direction, async-service / sync-Celery split, Msg-C4 commit ordering (service flushes, router commits + dispatches), dedup-key-after-success, identity-map-aware `BaseRepository.update`, atomic server-side counters, Redis NX AI lock, `asyncio.run()` bridge cleanup. Deviating reintroduces the bug classes bugs.txt tracks.

## Per-bug protocol

For each unpatched entry in scope:

1. Read the cited `file:line (function)` and confirm the bug still exists (line cites may be stale — verify against current code).
2. If it is no longer a bug, append `[VERIFIED NOT A BUG YYYY-MM-DD] <reason>` and move on.
3. Implement the minimal fix consistent with the invariants. No incidental refactoring.
4. Append under the entry, 4-space indented:
   `[PATCHED YYYY-MM-DD] <one-line summary of the fix and where>` (today's date, matching existing `[PATCHED ...]` style).
5. If a fix needs a product decision or is genuinely ambiguous, stop and ask the user for that entry rather than guessing — note it as still-open.

## Finish

- Summarize every ID: patched / verified-not-a-bug / still-open-awaiting-decision.
- If MINOR items were deferred, list them explicitly.
- Add regression guards for the fixes via the `crm-test-suite` skill (cross-checking bugs.txt) and run the suite.
