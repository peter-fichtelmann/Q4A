"""Foul-language check for player and team names.

Names and blacklist entries go through the same normalisation (case, accents,
leetspeak, Cyrillic look-alikes, separators), so "F.u_C|<", "fück" and "FUUUCK"
all reduce to the entry "fuck". An entry is then found in a name in one of two ways:

- whole word: entries marked with "=" in blacklist.txt and every entry of at most
  3 letters must equal one word of the name ("ass" blocks "Big Ass" and "BigAss",
  not "Bassist"). Words are split at non-letters and at camelCase boundaries.
- part of the name: longer entries may sit anywhere in the name with its
  separators removed, so "xXarschlochXx" and "s h i t" are caught. Long entries
  also match when a few filler letters are slipped between their letters
  ("arschxloch", "hurrensxohn"): 1 filler from 9 letters on, 2 from 12 letters on.

Stretched letters are shortened ("shiiit", "assss"), and for part-of-the-name entries
without a double letter of their own every doubled letter is undone ("fuuck"). Benign words
that contain an entry ("Scunthorpe", "peacock", "therapist") are listed in
allowlist.txt and masked before the part-of-the-name search.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

_DATA_DIR = Path(__file__).resolve().parent

# Leetspeak and look-alike letters, applied after lowercasing.
_CHAR_MAP = str.maketrans({
    "0": "o", "1": "i", "!": "i", "|": "i", "3": "e", "4": "a", "@": "a",
    "5": "s", "$": "s", "7": "t", "+": "t", "8": "b", "9": "g", "6": "g", "2": "z",
    "€": "e", "ł": "l", "ø": "o", "đ": "d", "ı": "i", "æ": "ae", "œ": "oe", "þ": "th",
    # Cyrillic letters that look like Latin ones, so mixed-script spellings match too
    "а": "a", "е": "e", "ё": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "і": "i",
})

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Þ])")


def _normalise(text: str) -> str:
    """Lowercase letters with leetspeak mapped and accents removed; everything else becomes a space."""
    text = unicodedata.normalize("NFKC", text).replace("|<", "k")
    text = _CAMEL_BOUNDARY.sub(" ", text)
    text = text.casefold().translate(_CHAR_MAP)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return "".join(ch if ch.isalpha() else " " for ch in text)


def _filler_budget(entry: str) -> int:
    if len(entry) >= 12:
        return 2
    if len(entry) >= 9:
        return 1
    return 0


_RUN_OF_3 = re.compile(r"(.)\1{2,}")
_RUN_OF_2 = re.compile(r"(.)\1+")


def _run_variants(text: str) -> set:
    """`text` with stretched letters ("fuuuck") shortened to one and to two letters."""
    return {text, _RUN_OF_3.sub(r"\1", text), _RUN_OF_3.sub(r"\1\1", text)}


def _contains(entry: str, text: str, fillers: int) -> bool:
    """Is `entry` in `text`, with up to `fillers` filler letters slipped between its letters?"""
    if fillers == 0:
        return entry in text
    for start in range(len(text) - len(entry) + 1):
        if text[start] != entry[0]:
            continue
        j, t, used = 1, start + 1, 0
        while j < len(entry) and t < len(text) and text[t] != " ":
            if text[t] == entry[j]:
                j += 1
            elif used < fillers:
                used += 1
            else:
                break
            t += 1
        if j == len(entry):
            return True
    return False


class NameFilter:
    def __init__(self, blacklist_path: Path = _DATA_DIR / "blacklist.txt",
                 allowlist_path: Path = _DATA_DIR / "allowlist.txt"):
        # (normalised entry, original line, whole word only, has a doubled letter)
        self.entries: List[Tuple[str, str, bool, bool]] = []
        for line in self._read_lines(blacklist_path):
            whole = line.startswith("=")
            original = line.lstrip("=").strip()
            normalised = _normalise(original).replace(" ", "")
            if normalised:
                self.entries.append((normalised, original, whole or len(normalised) <= 3,
                                     _RUN_OF_2.search(normalised) is not None))
        allowed = {_normalise(line).replace(" ", "") for line in self._read_lines(allowlist_path)}
        # longest first, so "assassination" is masked before "assassin"
        self.allowlist: List[str] = sorted((w for w in allowed if w), key=len, reverse=True)

    @staticmethod
    def _read_lines(path: Path) -> List[str]:
        lines = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                lines.append(line)
        return lines

    def _mask_allowed(self, compact: str) -> str:
        for word in self.allowlist:
            compact = compact.replace(word, " " * len(word))
        return compact

    def find_foul_word(self, name: str) -> Optional[str]:
        """The blacklist entry found in `name`, or None when the name is fine."""
        normalised = _normalise(name)
        words = set()
        for word in normalised.split():
            if word not in self.allowlist:
                words |= _run_variants(word)
        compacts = _run_variants(self._mask_allowed(normalised.replace(" ", "")))
        # every doubled letter undone ("fuuck"), only for entries that have none of their own
        deduplicated = _RUN_OF_2.sub(r"\1", min(compacts, key=len))
        for entry, original, whole, has_double in self.entries:
            if whole:
                if entry in words:
                    return original
                continue
            fillers = _filler_budget(entry)
            if any(_contains(entry, compact, fillers) for compact in compacts):
                return original
            if not has_double and _contains(entry, deduplicated, fillers):
                return original
        return None


_default_filter: Optional[NameFilter] = None


def check_name(name: str) -> Optional[str]:
    """The blacklist entry found in `name`, or None when the name is fine."""
    global _default_filter
    if _default_filter is None:
        _default_filter = NameFilter()
    return _default_filter.find_foul_word(name)


def clean_name(raw, max_length: int = 32) -> str:
    """`raw` as a display name: control/format characters dropped, whitespace collapsed, truncated."""
    text = "".join(ch for ch in str(raw) if not unicodedata.category(ch).startswith("C"))
    return " ".join(text.split())[:max_length]
