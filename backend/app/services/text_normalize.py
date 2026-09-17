import re
import unicodedata


def normalize_text(value: str) -> str:
    """Low-risk normalization shared by node-key duplicate-format detection
    (Stage 1) and monitor name matching (Stage 5): trim, collapse internal
    whitespace, fullwidth->halfwidth, lowercase. Never applied to identity
    silently outside of trim -- only used to *detect* likely duplicates so a
    human can confirm, per the spec's caution against auto-merging distinct
    names (e.g. "松平" vs "松坪").
    """

    text = unicodedata.normalize("NFKC", value.strip())
    text = re.sub(r"\s+", " ", text)
    return text.lower()
