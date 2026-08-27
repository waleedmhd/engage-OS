---
name: log-bugs-to-bugstxt
description: Record bugs found during review, exploration, or debugging into bugs.txt. Use PROACTIVELY whenever you discover bugs during code review, exploration, or debugging — do not wait for the user to ask. If the user explicitly says "log these bugs" or "add to bugs.txt," invoke this skill to ensure the format conventions are followed. Records ALL bugs found, no filtering by severity.
---

# Logging bugs to bugs.txt

Record **every** bug you found into `bugs.txt` at the repo root, following the file's existing convention exactly. Do not filter, summarize away, or drop low-severity bugs — all bugs get recorded.

## File structure

`bugs.txt` is divided into LAYER sections. Each section:

```
<LAYER NAME> — BUG LIST
=======================

CRITICAL
--------
C1  path/to/file.py:LINE-RANGE (function_name)
    One- to few-line description of the bug and its consequence.

IMPORTANT
---------
I1  ...

MINOR
-----
M1  ...
```

## Rules

1. **Pick the right LAYER section.** Match the bug's module to an existing `<LAYER> — BUG LIST` block (e.g. DATABASE LAYER, AUTH LAYER, META INTEGRATION LAYER, CONVERSATION STATE MACHINE LAYER). If no section fits, add a new one with the `— BUG LIST` header + `===` underline.
2. **Severity subsections** are `CRITICAL` / `IMPORTANT` / `MINOR`, each with a dashed underline. CRITICAL = runtime failure / data corruption / security. IMPORTANT = correctness bug under realistic conditions. MINOR = latent / cosmetic / will-bite-later.
3. **IDs** are letter+number, numbered sequentially within each layer's subsection: `C1, C2...`, `I1, I2...`, `M1, M2...`. Continue from the highest existing ID in that section — never reuse or renumber.
4. **Entry format**: ID, two spaces, `file:line-range (function)`, newline, then a 4-space-indented description. Keep the description precise: what is wrong and what it causes. Include the failing condition.
5. **Do not** mark anything `[PATCHED ...]` here — this skill only records, it does not fix.
6. Record all bugs found in this pass, even if minor or uncertain — note uncertainty in the description rather than omitting.

## Steps

1. Read `bugs.txt` to learn the current sections and the highest ID in each relevant subsection.
2. Group your findings by layer and severity.
3. Append each finding under the correct section with the next sequential ID.
4. Report a short tally back to the user (e.g. "Added C5-C6, I9, M3").
