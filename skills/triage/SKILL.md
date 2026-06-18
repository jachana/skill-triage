---
name: triage
description: >-
  Sort a pile of incoming/unsorted items on a project board — route each to the right list, set priority
  AND size, detect dependencies between cards, flag duplicates, and surface what needs a human decision.
  Provider-agnostic (local board.json, Trello, Jira) via board.py. Use when the user says "/triage",
  "triage the backlog", "sort the inbox", "what should I work on", "size these cards", "estimate these",
  "tria las tarjetas", "ordena el backlog", "clasifica lo que entró", "estima el tamaño". Bilingual (EN/ES).
---

# Triage — sort the board

Turn an undifferentiated pile into a prioritized, routed board. Decide; don't just describe.

## Language / Idioma
Work and report in the user's language (EN/ES).

## Steps
1. **Sync first.** `python board.py status`; if online, `python board.py pull` (remote wins).
2. **Read the unsorted items** — cards in `Backlog`/inbox without a priority or clear home.
3. **For each item decide:**
   - **Route** — which list it belongs in (`To Do` if ready, stays `Backlog` if not, `Done`/remove if obsolete).
   - **Priority** — p0 (drop everything) / p1 (this week) / p2 (later). Justify in one phrase.
   - **Size** — set an estimate (see **Sizing** below). Record it on the card (e.g. `size: M` in the desc).
   - **Dependencies** — does this card need another to land first? Record them (see **Dependencies** below).
   - **Duplicate?** — if it restates an existing card, flag it for `prune` rather than keeping both.
   - **Too big / vague?** — flag for `breakdown` (needs splitting) or `refine` (needs detail/acceptance criteria).
   - **Blocked / needs human input?** — surface it explicitly; don't silently bury it.
4. **Apply** via board.py (`move … --to`, `add`, etc.). For provider boards, `push` after.
5. **Report** a short triage summary: counts per bucket, the top 3 to do next, the dependency chains you
   found, and anything that needs the user's call.

## Sizing — two methods (pick what fits)

**Method A — absolute (default).** Judge effort directly: `XS / S / M / L / XL` (or 1/2/3/5/8 points).
Use when the work is familiar and you can estimate from first principles.

**Method B — relative / reference-class (use when unsure, or when the user asks for consistency).**
Don't estimate in a vacuum — anchor against work already sized:
1. From the board, **pick 2 already-sized cards** that are *similar in kind* to the one you're sizing —
   ideally one a bit smaller and one a bit bigger ("brackets" it).
2. Compare the new card to each: more or less work than card X? than card Y? Why (scope, unknowns, surface area)?
3. **Assign the size that places it correctly between/next to the two anchors.** State the two anchors and the
   one-line reasoning, e.g. *"Bigger than 'Login UI' (S), smaller than 'Billing flow' (L) → **M**."*
This keeps sizes consistent across the board and is more defensible than a lone guess. If you can't find two
comparable sized cards, fall back to Method A and say so.

## Dependencies — detect and record
While sizing/routing, ask for each card: **does anything have to ship before this can?** Look for cards that
build on the same feature, share a prerequisite (auth, schema, an API), or are named as blockers in the desc.
- Record blockers as a single line in the card's description: `depends-on: Auth API; Login UI`
  (comma/semicolon separated, matched by card name). This is the exact format the `dependency-graph` skill reads.
- A card with unmet (still-open) dependencies is **not ready** — keep it in `Backlog`, not `To Do`, and note why.
- After triage, you (or the user) can run the **`dependency-graph`** skill to visualize the whole chain and
  catch cycles / dangling references.

## Rules
- ⚠ Don't invent priorities or sizes from nothing — base them on stated impact/scope, the reference cards, or ask when genuinely unclear.
- ⚠ Don't delete here — route obvious junk to `prune`'s judgment, not straight to the bin.
- ⚠ Only record a `depends-on:` you can justify — a wrong edge pollutes the dependency graph. When unsure, note it as a question instead.
- ✅ Hand off: tag items for `breakdown` (too big), `refine` (too thin), `prune` (dead/dupe), `dependency-graph` (visualize blockers).
