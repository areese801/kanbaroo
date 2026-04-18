"""
Text-normalisation utilities used for cross-surface comparison.

The current consumer is the duplicate-title heuristic shared by
stories, epics, and tags: clients call the ``similar`` endpoints
before creating an entity and surface a warning when the normalised
title already exists. The normalisation rules are intentionally
permissive so visually identical titles (``Fix the bug!`` vs
``fix-the-bug``) collapse to the same key, while titles with
different word content (``Fix bug`` vs ``Fix the bug``) do not.

If we ever need higher precision (token-level similarity, stemming,
fuzzy matching) the helper here can be replaced without touching
service signatures.
"""


def normalize_for_comparison(text: str) -> str:
    """
    Return the canonical comparison form of ``text``.

    Lowercases (Unicode case-fold), drops every character that is
    not a letter or digit (so punctuation, symbols, and whitespace
    fall away), and concatenates the remainder. Idempotent: calling
    it on an already-normalised string returns the same string.

    Returns an empty string when ``text`` contains no alphanumerics
    or is itself empty; callers that want to treat empty
    normalisations as "no match possible" should check for that
    explicitly.
    """
    if not text:
        return ""
    return "".join(ch for ch in text.casefold() if ch.isalnum())
