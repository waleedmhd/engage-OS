#!/usr/bin/env python3
"""One-shot backfill: stream-copy archived_messages → market_archive.

Usage:
    # Set both connection strings, then run:
    export SOURCE_DATABASE_URL="postgresql://..."   # old archive DB
    export TARGET_DATABASE_URL="postgresql://..."   # CRM main DB (same as DATABASE_URL)
    python backend/scripts/backfill_market_archive.py

    # Or via railway run:
    railway run --service api python backend/scripts/backfill_market_archive.py

Idempotent: ``ON CONFLICT (source_msg_id) DO NOTHING`` — safe to re-run.
Purely additive: never deletes from the source DB.
"""

from __future__ import annotations

import os
import random
import sys
from textwrap import dedent

import psycopg
from psycopg.rows import dict_row


def _connect(url: str) -> psycopg.Connection:
    try:
        conn = psycopg.connect(url, row_factory=dict_row)
        print(f"Connected: {conn.info.host}:{conn.info.port}/{conn.info.dbname}")
        return conn
    except Exception as exc:
        sys.exit(f"Connection failed: {exc}")


def _row_count(cur, table: str) -> int:
    cur.execute(f"SELECT count(*) AS cnt FROM {table}")
    return cur.fetchone()["cnt"]  # type: ignore[no-any-return]


def main() -> None:
    source_url = os.environ.get("SOURCE_DATABASE_URL", "")
    target_url = os.environ.get("TARGET_DATABASE_URL", os.environ.get("DATABASE_URL", ""))

    if not source_url or not target_url:
        sys.exit(
            "Set SOURCE_DATABASE_URL (old archive DB) and "
            "TARGET_DATABASE_URL or DATABASE_URL (CRM main DB)."
        )

    print("=== Market Archive Backfill ===\n")
    print(f"Source: {source_url[:source_url.index('@')] if '@' in source_url else source_url}")
    print(f"Target: {target_url[:target_url.index('@')] if '@' in target_url else target_url}")
    print()

    src = _connect(source_url)
    tgt = _connect(target_url)

    # 1. Pre-flight counts
    with src.cursor() as cur:
        src_total = _row_count(cur, "archived_messages")
    with tgt.cursor() as cur:
        tgt_before = _row_count(cur, "market_archive")

    print(f"Source archived_messages rows : {src_total:>8,}")
    print(f"Target market_archive (before): {tgt_before:>8,}")
    print()

    if src_total == 0:
        print("Nothing to backfill — exiting.")
        src.close()
        tgt.close()
        return

    # 2. Stream-copy: SELECT from source, INSERT into target in batches.
    batch_size = 1000
    copied = 0
    skipped = 0
    errors = 0

    # Columns mapping archived_messages → market_archive.
    # archived_messages: group_name, sender_name, sender_number,
    #   message_timestamp, message_content, type, tags, source_msg_id,
    #   ai_assigned, created_at
    # market_archive: group_name, sender_name, sender_number,
    #   message_timestamp, message_content, msg_type, tags, source_msg_id,
    #   status, created_at

    with src.cursor(name="backfill_cursor") as src_cur, tgt.cursor() as tgt_cur:
        src_cur.execute(
            "SELECT group_name, sender_name, sender_number, message_timestamp, "
            "       message_content, type, tags, source_msg_id "
            "FROM archived_messages "
            "ORDER BY message_timestamp"
        )

        insert_sql = (
            "INSERT INTO market_archive "
            "(group_name, sender_name, sender_number, message_timestamp, "
            " message_content, msg_type, tags, source_msg_id, status) "
            "VALUES (%(group_name)s, %(sender_name)s, %(sender_number)s, "
            " %(message_timestamp)s, %(message_content)s, %(msg_type)s, "
            " %(tags)s, %(source_msg_id)s, 'lead') "
            "ON CONFLICT (source_msg_id) DO NOTHING"
        )

        batch = []
        for row in src_cur:
            batch.append({
                "group_name": row["group_name"],
                "sender_name": row["sender_name"],
                "sender_number": row["sender_number"],
                "message_timestamp": row["message_timestamp"],
                "message_content": row["message_content"],
                "msg_type": row["type"],
                "tags": row["tags"],
                "source_msg_id": row["source_msg_id"],
            })

            if len(batch) >= batch_size:
                for r in batch:
                    try:
                        tgt_cur.execute(insert_sql, r)
                        if tgt_cur.rowcount and tgt_cur.rowcount > 0:
                            copied += 1
                        else:
                            skipped += 1
                    except Exception:
                        errors += 1
                tgt_cur.connection.commit()
                print(f"  Progress: {copied + skipped:,}/{src_total:,} "
                      f"(copied {copied:,}, skipped {skipped:,})", end="\r")
                batch = []

        # Flush final partial batch.
        for r in batch:
            try:
                tgt_cur.execute(insert_sql, r)
                if tgt_cur.rowcount and tgt_cur.rowcount > 0:
                    copied += 1
                else:
                    skipped += 1
            except Exception:
                errors += 1
        tgt_cur.connection.commit()

    print(f"\n  Final: {copied + skipped:,}/{src_total:,} "
          f"(copied {copied:,}, skipped {skipped:,}, errors {errors})")
    print()

    # 3. Verify count parity
    with tgt.cursor() as cur:
        tgt_after = _row_count(cur, "market_archive")

    print(f"Target market_archive (after) : {tgt_after:>8,}")
    print(f"Expected (before + copied)    : {tgt_before + copied:>8,}")

    if tgt_after != tgt_before + copied:
        print("WARNING: Count mismatch! Investigate before proceeding.")
    else:
        print("Count parity OK.")
    print()

    # 4. Spot-check 20 random source_msg_ids for content match
    with src.cursor() as sc, tgt.cursor() as tc:
        sc.execute("SELECT source_msg_id FROM archived_messages")
        all_ids = [r["source_msg_id"] for r in sc]
        sample = random.sample(all_ids, min(20, len(all_ids)))

        mismatches = 0
        for sid in sample:
            sc.execute(
                "SELECT message_content, message_timestamp, sender_number "
                "FROM archived_messages WHERE source_msg_id = %s",
                (sid,),
            )
            src_row = sc.fetchone()
            tc.execute(
                "SELECT message_content, message_timestamp, sender_number "
                "FROM market_archive WHERE source_msg_id = %s",
                (sid,),
            )
            tgt_row = tc.fetchone()

            if tgt_row is None:
                print(f"  MISSING in target: {sid}")
                mismatches += 1
            elif (
                src_row["message_content"] != tgt_row["message_content"]
                or str(src_row["sender_number"]) != str(tgt_row["sender_number"])
            ):
                print(f"  MISMATCH: {sid}")
                mismatches += 1

        if mismatches == 0:
            print(f"Spot-check: {len(sample)} records — all match.")
        else:
            print(f"Spot-check: {mismatches}/{len(sample)} mismatches.")
    print()

    # 5. Summarise
    print("=== Backfill complete ===")
    print(dedent(f"""\
        Source rows       : {src_total:>8,}
        Copied            : {copied:>8,}
        Skipped (dups)    : {skipped:>8,}
        Errors            : {errors:>8,}
        Target after      : {tgt_after:>8,}
    """))

    src.close()
    tgt.close()


if __name__ == "__main__":
    main()
