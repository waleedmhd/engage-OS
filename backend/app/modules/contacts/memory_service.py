"""Client memory service — per-contact AI memory files on the Railway volume.

Each contact's memory is a JSON file at ``/app/media/memories/{contact_id}.json``.
A companion ``client_memories`` DB row tracks the file path, version, and a short
preview for the inbox UI.

The memory is a running summary that accumulates across all conversations with a
contact. It's updated after each AI reply so subsequent turns carry forward context
that would otherwise scroll out of the message-history window.

File format (JSON)::

    {
      "contact_id": "uuid",
      "version": 1,
      "updated_at": "2026-07-04T12:00:00+00:00",
      "summary": "Running paragraph summarising all known context...",
      "key_points": ["bullet 1", "bullet 2", ...],
      "preferences": {"language": "English"},
      "goals": [
        {
          "field": "name",
          "value": "Ahmed",
          "status": "confirmed"
        },
        {
          "field": "company",
          "value": "Dubai Mobile Trading",
          "status": "confirmed"
        },
        {
          "field": "product_interest",
          "value": "iPhone 15 Pro HK spec",
          "status": "tentative"
        },
        {
          "field": "buy_sell",
          "value": "buyer",
          "status": "confirmed"
        }
      ],
      "total_interactions": 42
    }

Goals track structured facts extracted from conversations. Each entry has a
``field`` (what was learned — e.g. name, company, product_interest, buy_sell,
budget, timeline, spec_preference), a ``value``, and a ``status``
("tentative", "confirmed", or "needs_clarification"). The summariser adds new
fields as conversations reveal them and upgrades status as facts are confirmed.
Confirmed goals are never dropped unless contradicted.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.orm import Session as SyncSession

from app.core.config import Settings, get_settings
from app.modules.contacts.memory_models import ClientMemory

logger = structlog.get_logger(__name__)

MEMORIES_DIR = "memories"

_MEMORY_SUMMARISE_SYSTEM = """You maintain a concise, running memory summary for a WhatsApp business
chat customer. Given the existing memory and the latest exchange, return an
updated memory as a JSON object.

Rules:
- The summary is a running paragraph (max 400 words) covering who the customer is,
  what they want, their history, decisions made, preferences expressed, and any
  important context for future conversations. Accumulate over time — don't drop
  old facts unless they are contradicted by newer information.
- key_points: 3-8 short bullet points of the most salient facts (preferences,
  budget, timeline, objections, key decisions, contact info shared).
- preferences: object mapping preference keys to values (e.g. language,
  contact_time, payment_method). Only include preferences the customer has
  actually expressed. Merge with existing preferences — don't lose old ones.
- goals: array of structured facts the AI sales agent needs to qualify the
  contact. Each entry has:
    - field: the category of information (e.g. "name", "company",
      "product_interest", "buy_sell", "budget", "timeline", "region",
      "spec_preference", "volume"). Use snake_case, keep names consistent
      across updates.
    - value: what was learned, short and specific. E.g. "Ahmed" not "the
      customer said his name is Ahmed".
    - status: "tentative" (mentioned casually or inferred), "confirmed"
      (explicitly stated by the customer), or "needs_clarification"
      (ambiguous or contradictory).
  Merge with existing goals: update value and status when new information
  arrives, upgrade tentative→confirmed when the customer states something
  explicitly, add new fields as conversations reveal them. Never drop a
  confirmed goal unless explicitly contradicted by newer information (in
  which case set status to "needs_clarification" rather than deleting).
  Extract every piece of qualifying information the customer shares —
  name, company, what they deal in, whether they buy or sell, budget,
  timeline, preferred specs, regions, volumes. These are the highest-value
  facts for the sales agent.
- If the existing memory is empty, start fresh from the new exchange.
- Return ONLY valid JSON, no other text."""


def _media_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "media"


def _memory_file_path(contact_id: uuid.UUID) -> Path:
    return _media_root() / MEMORIES_DIR / f"{contact_id}.json"


def _ensure_memories_dir() -> None:
    (_media_root() / MEMORIES_DIR).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------- public API


def get_memory_text(contact_id: uuid.UUID) -> str | None:
    """Return the memory summary as a formatted string for the AI prompt.

    Returns None when there is no memory file yet — the caller should omit the
    memory section from the prompt.
    """
    data = _read_memory_file(contact_id)
    if data is None:
        return None
    parts: list[str] = []
    summary = data.get("summary", "").strip()
    if summary:
        parts.append(f"Client memory (accumulated context from past conversations):\n{summary}")
    key_points = data.get("key_points", [])
    if key_points:
        parts.append("Key points:\n" + "\n".join(f"  - {p}" for p in key_points))
    prefs = data.get("preferences", {})
    if prefs:
        parts.append("Known preferences:\n" + "\n".join(f"  - {k}: {v}" for k, v in prefs.items()))
    goals = data.get("goals", [])
    if goals:
        lines = ["Learned about this contact:"]
        for g in goals:
            field = g.get("field", "unknown")
            value = g.get("value", "")
            status = g.get("status", "tentative")
            if status == "confirmed":
                lines.append(f"  - {field}: {value}")
            elif status == "needs_clarification":
                lines.append(f"  - {field}: {value} (needs clarification)")
            else:
                lines.append(f"  - {field}: {value} (tentative)")
        parts.append("\n".join(lines))
    return "\n\n".join(parts) if parts else None


def load_memory(contact_id: uuid.UUID) -> dict[str, Any] | None:
    """Load the full memory dict from disk. Returns None if no file exists."""
    return _read_memory_file(contact_id)


def update_memory_sync(
    session: SyncSession,
    contact_id: uuid.UUID,
    *,
    messages: list[dict[str, Any]],
    ai_reply: str,
    settings: Settings | None = None,
) -> None:
    """Update (or create) the contact's memory after an AI reply.

    Called inline from the AI orchestrator. Loads the existing memory, calls
    Claude Haiku to produce an updated summary, writes the JSON file, and
    upserts the ``client_memories`` tracking row.

    Does NOT commit — the caller (AIOrchestrator) owns the transaction.
    """
    _settings = settings or get_settings()
    existing = _read_memory_file(contact_id) or {}
    updated = asyncio.run(
        _summarise(existing, messages, ai_reply, _settings)
    )
    if updated is None:
        return  # summarisation failed — don't corrupt existing memory

    updated["contact_id"] = str(contact_id)
    updated["version"] = existing.get("version", 0) + 1
    updated["updated_at"] = datetime.now(tz=UTC).isoformat()
    updated["total_interactions"] = (
        existing.get("total_interactions", 0) + 1
    )

    _write_memory_file(contact_id, updated)
    _upsert_tracking_row(session, contact_id, updated)


def update_memory_from_history_sync(
    session: SyncSession,
    contact_id: uuid.UUID,
    *,
    messages: list[dict[str, Any]],
    settings: Settings | None = None,
) -> None:
    """Update (or create) the contact's memory from conversation history.

    Used when a conversation transitions from HUMAN_ASSIGNED back to
    AI_ACTIVE, so the AI agent has up-to-date context that includes the
    human-handled conversation. Unlike ``update_memory_sync`` this does not
    require an AI reply — it summarises the existing message history alone.

    If no memory file exists yet for this contact, a new one is created.
    Does NOT commit — the caller owns the transaction.
    """
    _settings = settings or get_settings()
    existing = _read_memory_file(contact_id) or {}
    updated = asyncio.run(
        _summarise(existing, messages, "", _settings)
    )
    if updated is None:
        return  # summarisation failed — don't corrupt existing memory

    updated["contact_id"] = str(contact_id)
    updated["version"] = existing.get("version", 0) + 1
    updated["updated_at"] = datetime.now(tz=UTC).isoformat()
    updated["total_interactions"] = (
        existing.get("total_interactions", 0) + 1
    )

    _write_memory_file(contact_id, updated)
    _upsert_tracking_row(session, contact_id, updated)


# --------------------------------------------------------------------- file I/O


def _read_memory_file(contact_id: uuid.UUID) -> dict[str, Any] | None:
    path = _memory_file_path(contact_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "memory_file_read_error",
            contact_id=str(contact_id),
            path=str(path),
            error=str(exc),
        )
        return None


def _write_memory_file(contact_id: uuid.UUID, data: dict[str, Any]) -> None:
    _ensure_memories_dir()
    path = _memory_file_path(contact_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------- DB tracking


def _upsert_tracking_row(
    session: SyncSession,
    contact_id: uuid.UUID,
    data: dict[str, Any],
) -> None:
    """Insert or update the ``client_memories`` index row."""
    import sqlalchemy as sa

    summary = data.get("summary", "") or ""
    preview = summary[:500] if summary else None
    file_path = str(_memory_file_path(contact_id).relative_to(_media_root()))

    existing = session.execute(
        sa.select(ClientMemory).where(ClientMemory.contact_id == contact_id)
    ).scalar_one_or_none()

    if existing is not None:
        existing.file_path = file_path
        existing.version = data.get("version", existing.version + 1)
        existing.summary_preview = preview
        existing.total_interactions = data.get(
            "total_interactions", existing.total_interactions + 1
        )
        existing.updated_at = datetime.now(tz=UTC)
    else:
        row = ClientMemory(
            id=uuid.uuid4(),
            contact_id=contact_id,
            file_path=file_path,
            version=data.get("version", 1),
            summary_preview=preview,
            total_interactions=data.get("total_interactions", 1),
        )
        session.add(row)


# -------------------------------------------------------------- Claude Haiku call


async def _summarise(
    existing: dict[str, Any],
    messages: list[dict[str, Any]],
    ai_reply: str,
    settings: Settings,
) -> dict[str, Any] | None:
    """Call Claude Haiku to update the memory summary.

    Returns the parsed JSON dict, or None on failure.
    Retries once after a 5-second wait on transient errors.
    """
    existing_text = json.dumps(existing, ensure_ascii=False, indent=2) if existing else "{}"

    # Build a compact transcript of the recent messages + AI reply.
    # 30 messages gives enough context to capture goal-relevant details
    # even after a summarisation failure skipped one update cycle.
    transcript_parts: list[str] = []
    for m in messages[-30:]:
        role = m.get("role", "user")
        content = m.get("content", "")
        if content:
            label = "Customer" if role == "user" else "Assistant"
            transcript_parts.append(f"{label}: {content}")
    if ai_reply:
        transcript_parts.append(f"Assistant (latest reply): {ai_reply}")

    transcript = "\n".join(transcript_parts)

    user_message = (
        f"Existing memory:\n{existing_text}\n\n"
        f"Latest exchange:\n{transcript}\n\n"
        "Return the updated memory as a JSON object with: summary, key_points, preferences, goals."
    )

    return await _call_haiku_for_summary(user_message, settings)


_MEMORY_SUMMARISE_TIMEOUT = 20  # seconds — generous for Haiku 4.5 on this payload


def _strip_markdown_fence(text: str) -> str:
    """Remove leading/trailing markdown code fences that some models wrap JSON in."""
    text = text.strip()
    if text.startswith("```"):
        text = text[3:]  # strip leading ``` (with or without language tag)
        # remove language tag if present (e.g. ```json)
        newline_idx = text.find("\n")
        if newline_idx != -1:
            text = text[newline_idx + 1 :]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def _call_haiku_for_summary(
    user_message: str,
    settings: Settings,
) -> dict[str, Any] | None:
    """Call Claude Haiku with one retry on failure."""
    for attempt in (1, 2):
        try:
            client = AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY,
                timeout=_MEMORY_SUMMARISE_TIMEOUT,
            )
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=768,
                system=_MEMORY_SUMMARISE_SYSTEM,
                messages=[{"role": "user", "content": user_message}],
            )
            await client.close()
        except Exception as exc:
            if attempt == 1:
                logger.warning(
                    "memory_summarise_attempt_failed",
                    attempt=attempt,
                    error=str(exc)[:300],
                )
                await asyncio.sleep(5)
                continue
            logger.warning(
                "memory_summarise_failed",
                error=str(exc)[:300],
            )
            return None

        text = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        )

        text = _strip_markdown_fence(text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if attempt == 1:
                logger.warning(
                    "memory_summarise_bad_json_retrying",
                    raw=text[:500],
                )
                await asyncio.sleep(5)
                continue
            logger.warning(
                "memory_summarise_bad_json",
                raw=text[:500],
            )
            return None

    return None  # unreachable — both attempts either return or continue
