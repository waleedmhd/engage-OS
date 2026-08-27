---
name: ship-issue
description: End-to-end issue resolution workflow. Use when the user says "fix issue #X" or asks you to implement a GitHub issue. Reads the issue, traces root cause across all layers, implements the fix (backend + frontend), runs the full test suite locally, and creates a PR — all in one pass. Prevents the "push, fail, fix, repeat" CI loop by front-loading validation.
---

# Ship an issue end-to-end

Follow this exact workflow so the fix lands in one pass instead of cycling through CI failures.

## 1. Read the issue

Read the issue body completely. Identify the acceptance criteria, the affected feature area, and whether it touches backend, frontend, or both. If it's a bug, reproduce it mentally from the description before writing code.

## 2. Trace root cause across all layers

Use Grep and Read to trace the issue through every affected layer before making any edits:

- **Database**: models, migrations, existing indexes
- **Repository**: query patterns, filters, pagination
- **Service**: business logic, validation, edge cases
- **Router**: request/response contracts, status codes, dependencies
- **Frontend**: component tree, API call sites, state management, TypeScript types

Confirm you understand the full blast radius before touching code.

## 3. Implement the fix

Make changes across all affected layers in the correct dependency order:

- Migration (if schema changes) → model → repository → service → router → frontend
- If backend models or schemas changed, update the corresponding frontend TypeScript types in the same session
- For frontend search/filter inputs: always implement debounce (300ms), manage filter state, avoid duplicate fetch-on-mount logic
- For cursor pagination: use `limit + 1` (not `limit`) when probing for `has_more`; test empty, exact-page, and last-page cases
- Check TYPE_CHECKING blocks for broken imports after refactors

## 4. Check migrations

If the change requires a schema migration:
```bash
cd backend && alembic heads
```
Verify no conflicts with other open PRs. If multiple PRs are in flight, pick a migration number that won't collide.

## 5. Pre-submission validation

Before committing, run these locally:

```bash
# Run the full unit test suite
cd backend && python -m pytest tests/unit/ -q

# Run lint and type checks if applicable
cd backend && ruff check .
```

Fix any failures — do not push with known issues and wait for CI.

## 6. Final checks

- After resolving merge conflicts: re-run the full test suite
- Grep for undefined references (`from app.modules.X.models import` patterns that may have broken)
- Verify no dead imports or unused variables remain

## 7. Commit and create PR

Commit with a message matching the repo's convention (see git log for style). Push and create the PR with a summary of what changed and why.
