# EngageOS — Claude Code Instructions

When producing an implementation plan, lead with a CONTROL SHEET of at most one page,
followed by full detail as an appendix.

The control sheet contains exactly these sections, in this order:

  1. FILES TOUCHED     — path | created/modified/deleted | one-line reason
  2. IRREVERSIBLE OPS  — migrations, NOT NULL adds, drops, backfills, contract changes.
                         Write "none" if none. Never omit the heading.
  3. CLAIMS            — every factual assertion about the existing codebase, one per
                         line, each with the shell command that verifies it
  4. ORDER             — numbered steps, each independently verifiable before the next
  5. ROLLBACK          — how to undo, per irreversible op
  6. OUT OF SCOPE      — what this plan deliberately does not do

Rules:
- No line on the control sheet may contain information absent from the appendix.
- Every control sheet line must be traceable to an appendix section.
- Do not put rationale, alternatives considered, or background on the control sheet.
- If a section would be empty, print the heading and "none" rather than deleting it.

## Testing

Before creating a PR, always run the full unit test suite locally and fix any failures before pushing. Never rely on CI as the first line of testing feedback — CI infrastructure can be flaky (runners not starting, coverage gate hangs) and introduces unnecessary iteration cycles.

After resolving merge conflicts, always re-run the full test suite and perform a grep for undefined references before committing. Merge conflict resolution has been the single biggest source of post-CI failures (missing imports, broken annotations, test regressions).

## Migration Conventions

When creating Alembic migrations, always check the current migration head topology first (`alembic heads`). Coordinate with open PR branches to avoid renumbering conflicts (e.g., 035 vs 036 migrations were renumbered multiple times across sessions). If multiple PRs are in flight, communicate which migration number you're using.

## Full-Stack Patterns

When making backend model/schema changes, always include the corresponding frontend TypeScript type updates in the same session. Model relationship annotations in TYPE_CHECKING blocks (e.g., Message import) are easily broken by other refactors and cause CI failures.

## Frontend Patterns

For React frontend changes involving search/filter input fields, always implement debounce (300ms), manage filter state carefully, and avoid duplicate fetch-on-mount logic. Test the search interaction flow before considering the feature complete.

## Backend Patterns

Use `limit + 1` (not `limit`) when probing for cursor pagination `has_more` results. Always test pagination edge cases (empty results, exact page size, last page) before pushing.
