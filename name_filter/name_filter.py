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

The entries come from blacklist.txt (hand-written) and blacklist_external.txt (generated
from better_profanity and LDNOOBW by build_external_blacklist.py). Entries with spaces
are phrases and must match whole consecutive words. A name the blacklist lets through
can finally be scored by the alt-profanity-check model, turned off by default (see
PROFANITY_MODEL_ENABLED).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

_DATA_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("quadball.name_filter")

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


def _strip_accents(decomposed: str):
    """Drop combining marks after Latin, Greek and Cyrillic letters; keep e.g. Japanese voicing marks (ブ is not フ)."""
    base = ""
    for ch in decomposed:
        if not unicodedata.combining(ch):
            base = ch
            yield ch
        elif base >= "֐":
            yield ch


def _normalise(text: str) -> str:
    """Lowercase letters with leetspeak mapped and accents removed; everything else becomes a space."""
    # zero-width (non-)joiners sit inside Persian words (هیچ‌کس), they are not word breaks
    text = unicodedata.normalize("NFKC", text).replace("|<", "k").replace("‌", "").replace("‍", "")
    text = _CAMEL_BOUNDARY.sub(" ", text)
    text = text.casefold().translate(_CHAR_MAP)
    text = unicodedata.normalize("NFC", "".join(_strip_accents(unicodedata.normalize("NFKD", text))))
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


def _is_unspaced_script(text: str) -> bool:
    """Chinese, Japanese and Thai are written without spaces, so their entries cannot be whole words."""
    return any("฀" <= ch <= "๿" or "぀" <= ch <= "ヿ" or "㐀" <= ch <= "鿿"
               for ch in text)


# Phrases ("blow job") whose letters run this long are also searched for with the spaces removed.
_PHRASE_PART_MIN_LETTERS = 8


class NameFilter:
    def __init__(self, blacklist_paths=(_DATA_DIR / "blacklist.txt", _DATA_DIR / "blacklist_external.txt"),
                 allowlist_path: Path = _DATA_DIR / "allowlist.txt",
                 model_allowlist_path: Path = _DATA_DIR / "model_allowlist.txt"):
        # (normalised entry, original line, whole word only, has a doubled letter); part-of-the-name
        # entries have their spaces removed
        self.entries: List[Tuple[str, str, bool, bool]] = []
        # (normalised phrase with single spaces, original line), matched word by word
        self.phrases: List[Tuple[str, str]] = []
        for path in blacklist_paths:
            if not Path(path).exists():
                continue
            for line in self._read_lines(path):
                whole = line.startswith("=")
                original = line.lstrip("=").strip()
                phrase = " ".join(_normalise(original).split())
                normalised = phrase.replace(" ", "")
                if not normalised:
                    continue
                if " " in phrase:
                    self.phrases.append((phrase, original))
                    if len(normalised) < _PHRASE_PART_MIN_LETTERS:
                        continue
                    whole = False
                else:
                    whole = whole or (len(normalised) <= 3 and not _is_unspaced_script(normalised))
                self.entries.append((normalised, original, whole, _RUN_OF_2.search(normalised) is not None))
        allowed = {_normalise(line).replace(" ", "") for line in self._read_lines(allowlist_path)}
        # longest first, so "assassination" is masked before "assassin"
        self.allowlist: List[str] = sorted((w for w in allowed if w), key=len, reverse=True)
        # words left out before asking the profanity model
        self.model_allowed_words = set(self.allowlist) | {
            _normalise(line).replace(" ", "") for line in self._read_lines(model_allowlist_path)}

    @staticmethod
    def _read_lines(path: Path) -> List[str]:
        lines = []
        for raw in Path(path).read_text(encoding="utf-8").splitlines():
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
        spaced = {f" {variant} " for variant in _run_variants(" ".join(normalised.split()))}
        for phrase, original in self.phrases:
            if any(f" {phrase} " in variant for variant in spaced):
                return original
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


    def model_verdict(self, name: str) -> Optional[str]:
        """"profanity model <probability>" when the profanity model rejects `name`, else None.

        Words in allowlist.txt or model_allowlist.txt ("Hell's" counts as "hell") are left out
        before the model scores the rest of the name. It is scored as a whole: single words
        on their own ("fat", "nerd", "fool") score far higher than in a name.
        """
        predict_prob = _profanity_model()
        if predict_prob is None:
            return None
        words = [w for w in _MODEL_WORD.findall(_CAMEL_BOUNDARY.sub(" ", name))
                 if _normalise(_POSSESSIVE.sub("", w)).replace(" ", "") not in self.model_allowed_words]
        if not words:
            return None
        probability = predict_prob([" ".join(words)])[0]
        if probability >= PROFANITY_MODEL_THRESHOLD:
            return f"profanity model {probability:.2f}"
        return None


# alt-profanity-check (a linear SVM trained on English comments) is asked after the
# blacklist, for insults the blacklist does not list ("Stupid Seekers"). It only knows
# English and also scores harmless words high ("die" is German "the", "Toro Negro"),
# so the threshold is high and such words go into model_allowlist.txt.
# Off: scikit-learn costs ~200 MB installed, seconds to load and memory on the server, for a
# few English insults. To turn it on, set this True and `pip install alt-profanity-check==1.9.1`.
PROFANITY_MODEL_ENABLED = False
PROFANITY_MODEL_THRESHOLD = 0.9
_MODEL_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_POSSESSIVE = re.compile(r"'s$", re.IGNORECASE)
_predict_prob = None


def _profanity_model():
    """alt-profanity-check's predict_prob, or None when it is turned off or not installed (then only the blacklist is used)."""
    global _predict_prob
    if not PROFANITY_MODEL_ENABLED:
        return None
    if _predict_prob is None:
        try:
            from profanity_check import predict_prob
            _predict_prob = predict_prob
        except Exception as error:  # not installed, or a scikit-learn it cannot load its model with
            logger.warning("profanity model unavailable, names are checked against the blacklist only: %s", error)
            _predict_prob = False
    return _predict_prob or None


_default_filter: Optional[NameFilter] = None


def warm_up() -> None:
    """Load the blacklist and the profanity model now instead of on the first check."""
    check_name("warm up")
    _profanity_model()


def check_name(name: str) -> Optional[str]:
    """Why `name` is rejected (the blacklist entry found, or the profanity model's verdict), or None when it is fine."""
    global _default_filter
    if _default_filter is None:
        _default_filter = NameFilter()
    return _default_filter.find_foul_word(name) or _default_filter.model_verdict(name)


def clean_name(raw, max_length: int = 32) -> str:
    """`raw` as a display name: control/format characters dropped, whitespace collapsed, truncated."""
    text = "".join(ch for ch in str(raw) if not unicodedata.category(ch).startswith("C"))
    return " ".join(text.split())[:max_length]
