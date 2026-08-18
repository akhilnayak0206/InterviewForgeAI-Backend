from __future__ import annotations

import re
import unicodedata

# — Unicode Replacement Map —
# These are the most common unicode variants found in PDFs.
# Each maps to its ASCII equivalent.
UNICODE_REPLACEMENTS: dict[str, str] = {
    # Curly/smart quotes → straight quotes
    "\u2018": "'",  # left single
    "\u2019": "'",  # right single (apostrophe)
    "\u201a": "'",  # single low-9
    "\u201c": '"',  # left double
    "\u201d": '"',  # right double
    "\u201e": '"',  # double low-9

    # Dashes → standard hyphen/dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar

    # Spaces → standard space
    "\u00a0": " ",  # non-breaking space
    "\u2002": " ",  # en space
    "\u2003": " ",  # em space
    "\u2009": " ",  # thin space
    "\u200a": " ",  # hair space
    "\u200b": "",   # zero-width space (remove entirely)

    # Bullets → standard dash (for list items)
    "\u2022": "-",  # bullet
    "\u2023": "-",  # triangular bullet
    "\u25e6": "-",  # white bullet

    # Ellipsis
    "\u2026": "...",  # horizontal ellipsis

    # Other
    "\ufeff": "",  # BOM (byte order mark) - remove
    "\ufffd": "",  # replacement character - remove
}

# Pre-compile the regex pattern for unicode replacement.
# re.escape() handles any regex-special characters in the keys.
_UNICODE_PATTERN = re.compile(
    r"|".join(re.escape(k) for k in UNICODE_REPLACEMENTS)
)


def normalize_text(raw_text: str) -> str:
    """Apply the full normalization pipeline to extracted text.

    This is the main entry point. Call this on raw extracted text
    from the PDF extractor.

    Args:
        raw_text: Raw text from PDF extraction (messy).

    Returns:
        Cleaned, normalized text ready for chunking.
    """
    if not raw_text:
        return ""

    text = raw_text

    # Step 1: Remove null bytes and control characters.
    # PDFs sometimes contain these from encoding issues.
    # \x00 = null, \x0c = form feed (page break in PDFs).
    text = _strip_control_characters(text)

    # Step 2: Normalize unicode variants to ASCII equivalents.
    # This ensures consistent tokenization by embedding models.
    text = _normalize_unicode(text)

    # Step 3: Apply NFC normalization.
    # Ensures composed unicode forms (é as single char, not e + combining accent).
    # Consistent representation → consistent tokenization.
    text = unicodedata.normalize("NFC", text)

    # Step 4: Collapse multiple spaces into single spaces.
    # PDFs often have "John    Doe" due to character positioning.
    text = _collapse_spaces(text)

    # Step 5: Clean up line breaks.
    # - Strip leading/trailing whitespace from each line
    # - Collapse 3+ consecutive newlines into 2 (preserving paragraph breaks)
    text = _clean_line_breaks(text)

    # Step 6: Final strip.
    text = text.strip()

    return text


def _strip_control_characters(text: str) -> str:
    """Remove null bytes, form feeds, and other control characters.

    Preserves: newlines (\n), tabs (\t), carriage returns (\r).
    These are the only control characters with semantic meaning in text.
    """

    # Remove specific problematic control characters
    text = text.replace("\x00", "")  # null byte
    text = text.replace("\x0c", "\n")  # form feed → newline (page break)
    text = text.replace("\x0b", "\n")  # vertical tab → newline

    # Remove remaining C0/C1 control characters while preserving all
    # whitespace that carries text structure, including ordinary spaces.
    # The previous whitespace-based expression also removed spaces, causing
    # extracted PDF text such as "Software Engineer" to become
    # "SoftwareEngineer".
    return re.sub(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]", "", text)


def _normalize_unicode(text: str) -> str:
    """Replace common unicode variants with ASCII equivalents.

    Uses the pre-compiled regex pattern and replacement map for speed.
    """
    return _UNICODE_PATTERN.sub(
        lambda match: UNICODE_REPLACEMENTS[match.group(0)],
        text,
    )


def _collapse_spaces(text: str) -> str:
    """Collapse multiple consecutive spaces into a single space.

    Does NOT touch newlines - those are handled separately.
    Only collapses horizontal whitespace (spaces and tabs).

    "John    Doe" → "John Doe"
    "  Software    Engineer  " → " Software Engineer "
    """
    return re.sub(r"[^\S\n]+", " ", text)


def _clean_line_breaks(text: str) -> str:
    """Clean up line breaks:

    1. Normalize \\r\\n to \\n (Windows → Unix line endings)
    2. Strip trailing whitespace from each line
    3. Collapse 3+ consecutive newlines into exactly 2

    The result preserves paragraph breaks (double newline) but removes
    excessive vertical whitespace from PDF page boundaries.
    """

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Collapse 3+ newlines into 2 (keep paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text
