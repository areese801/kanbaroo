"""
Unit tests for :mod:`kanbaroo_core.text`.

The normalisation rules drive the duplicate-title detection across
services, the API, the CLI, and the MCP layer. Edge cases get full
coverage here so the higher-level tests can assume the helper is
trustworthy.
"""

from kanbaroo_core.text import normalize_for_comparison


def test_lowercases_and_strips_punctuation() -> None:
    """
    Mixed casing and punctuation collapse to the alphanumeric form.
    """
    assert normalize_for_comparison("Fix the bug!") == "fixthebug"
    assert normalize_for_comparison("fix-the-bug") == "fixthebug"
    assert normalize_for_comparison("FIX THE BUG") == "fixthebug"


def test_distinct_word_content_does_not_collide() -> None:
    """
    Different word content normalises to different keys.
    """
    assert normalize_for_comparison("Fix bug") != normalize_for_comparison(
        "Fix the bug"
    )


def test_idempotent_on_already_normalised_input() -> None:
    """
    Running the helper twice yields the same result.
    """
    once = normalize_for_comparison("Refactor the API")
    twice = normalize_for_comparison(once)
    assert once == twice


def test_empty_string_normalises_to_empty() -> None:
    """
    The empty string stays empty.
    """
    assert normalize_for_comparison("") == ""


def test_pure_punctuation_normalises_to_empty() -> None:
    """
    A title made entirely of punctuation has no comparison key.
    """
    assert normalize_for_comparison("!!! ??? ...") == ""


def test_unicode_whitespace_is_stripped() -> None:
    """
    Non-ASCII whitespace (NBSP, em space) is treated as whitespace.
    """
    assert normalize_for_comparison("foo\u00a0bar") == "foobar"
    assert normalize_for_comparison("foo\u2003bar") == "foobar"


def test_unicode_letters_and_digits_are_preserved() -> None:
    """
    Letters and digits from any script survive normalisation.
    """
    assert normalize_for_comparison("Caf\u00e9 42") == "caf\u00e9" + "42"
