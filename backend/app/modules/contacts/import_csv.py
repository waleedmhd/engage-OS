"""CSV import parser + row processor for contacts (DSD §4.7 audience selection).

The CSV format is intentionally permissive:

  * Header row required.
  * Required column: ``phone``.
  * Optional columns (case-insensitive, leading/trailing whitespace stripped):
      - ``name``
      - ``company``
  * Any other columns are ignored.
  * Empty rows are skipped silently.

The pure functions here are shared by:
  - ``ContactService.import_csv`` (sync HTTP endpoint, async repo)
  - ``contacts.tasks.import_csv_task`` (Celery worker, sync repo)

Keeping parsing separate from persistence lets us unit-test the parser
without a database and re-use it under both async and sync sessions.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass

# Hard cap to prevent OOM / runaway imports.
MAX_IMPORT_ROWS = 10_000

# E.164-ish: optional leading +, 4-32 digits/spaces/hyphens. We normalize
# whitespace and hyphens out before validation.
_PHONE_RE = re.compile(r"^\+?[0-9]{4,32}$")


@dataclass(frozen=True)
class ParsedContactRow:
    """A successfully parsed CSV row, ready to upsert."""

    row_number: int  # 1-based, where row 1 is the header
    phone: str       # canonical wa_id form: digits only, no leading +
    name: str | None
    company: str | None


@dataclass(frozen=True)
class ParseError:
    """A row that could not be parsed."""

    row_number: int
    phone: str | None
    error: str


def _normalize_phone(raw: str) -> str:
    """Reduce to the canonical digits-only (wa_id) form used everywhere a phone
    is stored or matched. Crucially this also strips the leading ``+`` so an
    imported contact matches Meta's bare-wa_id inbound ``from`` and is never
    re-created as a name-less duplicate on the customer's reply. See
    app.modules.contacts.phone."""
    from app.modules.contacts.phone import canonicalize_phone

    return canonicalize_phone(raw)


def _normalize_header(name: str) -> str:
    return name.strip().lower()


def parse_csv(
    raw_bytes: bytes,
    *,
    max_rows: int = MAX_IMPORT_ROWS,
) -> Iterator[ParsedContactRow | ParseError]:
    """Stream rows from a raw CSV byte string.

    Yields one ParsedContactRow or ParseError per data row. Stops cleanly
    at ``max_rows``; the caller should check whether the iterator was
    exhausted by the row cap (the iterator itself does not raise).

    Bytes are decoded as UTF-8 with replacement so a BOM or stray Latin-1
    char doesn't abort the whole import.
    """
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        return  # empty file
    headers = {_normalize_header(h): h for h in reader.fieldnames if h is not None}

    if "phone" not in headers:
        # Single error covering the whole file; emit on row 1 (header row).
        yield ParseError(row_number=1, phone=None, error="csv_missing_phone_column")
        return

    phone_key = headers["phone"]
    name_key = headers.get("name")
    company_key = headers.get("company")

    # csv.DictReader rows start at row 2 (after header). Track explicitly.
    for idx, row in enumerate(reader, start=2):
        if idx - 1 > max_rows:
            return

        # Skip entirely-empty rows (common in CSV exports).
        if not any((row.get(k) or "").strip() for k in row):
            continue

        raw_phone = (row.get(phone_key) or "").strip()
        if not raw_phone:
            yield ParseError(row_number=idx, phone=None, error="missing_phone")
            continue

        phone = _normalize_phone(raw_phone)
        if not _PHONE_RE.match(phone):
            yield ParseError(row_number=idx, phone=raw_phone, error="invalid_phone_format")
            continue

        yield ParsedContactRow(
            row_number=idx,
            phone=phone,
            name=(row.get(name_key) or "").strip() or None if name_key else None,
            company=(row.get(company_key) or "").strip() or None if company_key else None,
        )
