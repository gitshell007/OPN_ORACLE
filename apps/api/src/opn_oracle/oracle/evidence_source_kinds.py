"""Single source of truth for dossier-corpus evidence source_kind allowlists.

Preguntar (dual-authority) and situation-summary analysis must share the same
set. If either path diverges, demos show empty summary corpora while Ask has
citations (or the reverse). Keep this module the only place that lists kinds.
"""

from __future__ import annotations

# Kinds eligible when loading Evidence linked to a dossier for LLM corpus use.
# Includes memory_signal (immutable dual-memory materializations) so situation
# analysis and Preguntar see the same authorised evidence set.
DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS: tuple[str, ...] = (
    "signal",
    "document",
    "procurement",
    "entity_intel",
    "memory_signal",
)
