import re
from rapidfuzz import fuzz, process
from rapidfuzz.distance import JaroWinkler
from camel_tools.utils.charmap import CharMapper

__all__ = ['NameMatcher', 'score_normalized']

# ─────────────────────────────────────────────────────────
# Phonetic mapping tables
# ─────────────────────────────────────────────────────────

# Buckwalter-specific — applied BEFORE lowercasing (case-sensitive).
_BUCKWALTER_MAP = [
    ('$', 'sh'),
    ('H', 'h'), ('T', 't'), ('D', 'd'), ('S', 's'), ('Z', 'z'),
    ('E', 'a'), ('G', 'g'),
    ('x', 'kh'), ('q', 'k'),
]

# Latin (Algerian French/English) — applied AFTER lowercasing.
_LATIN_MAP = [
    ('dj', 'j'), ('ch', 'sh'), ('ou', 'u'), ('kh', 'k'), ('gh', 'g'),
]

# Deep phonetic collapses — applied last, on fully normalised text.
_DEEP_PHONETIC = [
    ('gh', 'g'), ('q', 'g'),
    ('p', 'a'), ('h', 'a'),            # Taa Marbouta fix
    ('ou', 'u'), ('w', 'u'), ('o', 'u'),
    ('y', 'i'), ('ee', 'i'),
    ('e', 'a'),                          # Kamel↔Kamal, Abdel↔Abdal
    ('sh', 's'), ('ch', 's'), ('c', 's'),
    ('th', 't'), ('v', 't'),
]


# ─────────────────────────────────────────────────────────
# Name Matcher
# ─────────────────────────────────────────────────────────

class NameMatcher:
    """Algerian Arabic↔Latin cross-script name matcher.

    Pipeline:
      Arabic  → fuse prefixes → normalise script → transliterate (Buckwalter)
              → phonetic collapse → lowercase/strip → Latin phonetics
              → fuse Latin prefixes → deep phonetics

      Latin   → lowercase/strip → Latin phonetics → fuse prefixes
              → deep phonetics

    Scoring:
      Bidirectional averaged JaroWinkler (70 %) + token_sort_ratio (30 %),
      guarded by a consonant-skeleton gate that halves the score when any
      token's skeleton is a clear mismatch (< 55 %).
    """

    def __init__(self, scheme: str = 'ar2bw'):
        self.transliterator = CharMapper.builtin_mapper(scheme)

    # ── Arabic helpers ────────────────────────────────────

    @staticmethod
    def _is_arabic(text: str) -> bool:
        return bool(re.search(r'[\u0600-\u06FF]', text))

    @staticmethod
    def _normalize_arabic(text: str) -> str:
        """Harakat removal, alif/hamza unification, taa marbouta, article strip."""
        harakat = '\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0653\u0654\u0655'
        text = ''.join(c for c in text if c not in harakat)
        text = re.sub(r'[أإآء]', 'ا', text)
        text = text.replace('ؤ', 'و').replace('ئ', 'ي')
        text = text.replace('ى', 'ي')
        text = text.replace('ة', 'ه')
        text = text.replace('\u0640', '')
        text = re.sub(r'\bال', '', text)
        return text.strip()

    @staticmethod
    def _fuse_arabic(text: str) -> str:
        """Merge multi-word Arabic prefixes into single tokens.

        Runs twice to catch nested prefixes (e.g. بو + عبد).
        """
        text = re.sub(r'(^|\s)(عبد|بن|بو|ابو|أبو|أم|ام|بني)\s+', r'\1\2', text)
        text = re.sub(r'(^|\s)(عبد|بن|بو|ابو|أبو|أم|ام|بني)\s+', r'\1\2', text)
        text = text.replace('نور الدين', 'نورالدين')
        text = text.replace('زين الدين', 'زينالدين')
        text = text.replace('عبد الله', 'عبدالله')
        return text

    # ── Latin helpers ─────────────────────────────────────

    @staticmethod
    def _fuse_latin(text: str) -> str:
        """Merge multi-word Latin prefixes into single tokens."""
        text = re.sub(r'\b(abd\s*el|abd\s*al)\s+', 'abdel', text)
        text = re.sub(r'\b(abdel|abd|ben|bin|bou|bu|dj|dja|el|al)\s+', r'\1', text)
        text = text.replace('nour eddine', 'noureddine')
        text = re.sub(r'\b(zine\s*eddine|zineddine)\b', 'zinedine', text)
        return text

    @staticmethod
    def _custom_process(text: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace."""
        text = text.lower().strip()
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # ── Normalisation pipeline ────────────────────────────

    def normalize(self, text: str) -> str:
        """Full normalisation: any script → single phonetic Latin form.

        Arabic path:
          fuse prefixes → normalise script → transliterate (Buckwalter)
          → Buckwalter phonetics → lowercase → Latin phonetics
          → fuse Latin prefixes → deep phonetics

        Latin path:
          lowercase → Latin phonetics → fuse prefixes → deep phonetics
        """
        if not text:
            return ''

        if self._is_arabic(text):
            text = self._fuse_arabic(text)
            text = self._normalize_arabic(text)
            text = self.transliterator.map_string(text)
            for src, dst in _BUCKWALTER_MAP:
                text = text.replace(src, dst)

        text = self._custom_process(text)

        for src, dst in _LATIN_MAP:
            text = text.replace(src, dst)

        text = self._fuse_latin(text)

        for src, dst in _DEEP_PHONETIC:
            text = text.replace(src, dst)

        return text.strip()

    # ── Scoring (static — works on pre-normalised strings) ─

    @staticmethod
    def _consonant_skeleton(word: str) -> str:
        """Strip vowels to get the consonant backbone."""
        sk = re.sub(r'[aeiouy]', '', word)
        return sk if sk else word

    @staticmethod
    def score_normalized(s1: str, s2: str) -> float:
        """Score two *already-normalised* name strings (0-100).

        Designed as a standalone function so it can be passed directly
        to ``rapidfuzz.process.extractOne(scorer=…)`` for bulk search.

        Algorithm:
          1. Bidirectional averaged JaroWinkler (70 %) + token_sort_ratio (30 %).
          2. Consonant-skeleton gate — if the worst bidirectional skeleton
             match falls below 55 %, the score is halved.
          3. Asymmetry penalty for word-count mismatch.
        """
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 100.0

        t1 = s1.split()
        t2 = s2.split()
        if not t1 or not t2:
            return 0.0

        # 1. Bidirectional averaged JaroWinkler + token_sort blend
        avg_fwd = sum(
            max(JaroWinkler.similarity(w1, w2) * 100 for w2 in t2)
            for w1 in t1
        ) / len(t1)
        avg_bwd = sum(
            max(JaroWinkler.similarity(w2, w1) * 100 for w1 in t1)
            for w2 in t2
        ) / len(t2)

        base_score = (avg_fwd + avg_bwd) / 2
        sort_ratio = fuzz.token_sort_ratio(s1, s2)
        final_score = base_score * 0.7 + sort_ratio * 0.3

        # 2. Consonant-skeleton gate
        skel = NameMatcher._consonant_skeleton
        sk1 = [skel(w) for w in t1]
        sk2 = [skel(w) for w in t2]

        sk_fwd = min(max(fuzz.ratio(a, b) for b in sk2) for a in sk1)
        sk_bwd = min(max(fuzz.ratio(b, a) for a in sk1) for b in sk2)

        if min(sk_fwd, sk_bwd) < 55:
            final_score *= 0.5

        # 3. Asymmetry penalty
        len_diff = abs(len(t1) - len(t2))
        if len_diff > 0:
            final_score *= max(0.6, 1.0 - len_diff * 0.15)

        return round(final_score, 2)

    # ── Public API ────────────────────────────────────────

    def match(self, name1: str, name2: str) -> float:
        """Compare two names (any script) and return a similarity score (0-100)."""
        return self.score_normalized(
            self.normalize(name1),
            self.normalize(name2),
        )


# ─────────────────────────────────────────────────────────
# Bulk search helper
# ─────────────────────────────────────────────────────────

def _scorer(s1, s2, **kwargs):
    """Thin wrapper for ``rapidfuzz.process`` compatibility."""
    return NameMatcher.score_normalized(s1, s2)


# ─────────────────────────────────────────────────────────
# Usage examples
# ─────────────────────────────────────────────────────────
#
# from name_matcher import NameMatcher, _scorer
# from rapidfuzz import process
#
# matcher = NameMatcher(scheme='ar2bw')
#
# # --- Single pair comparison ---
# score = matcher.match("عبد الرحمن بوزيد", "Bouzid Abderrahmane")
# print(score)  # e.g. 85.3
#
# # --- Normalise a name (useful for pre-processing a database) ---
# norm = matcher.normalize("بن عيسى هدى")
# print(norm)   # e.g. "bnaisa ada"
#
# # --- Bulk search (find best match in a database) ---
# latin_db = ["Bouzid Abderrahmane", "Kadri Mohammed", "Benaissa Houda"]
# normalized_db = {i: matcher.normalize(n) for i, n in enumerate(latin_db)}
#
# query = matcher.normalize("هدى بن عيسى")
# result = process.extractOne(query, normalized_db, scorer=_scorer)
# best_name, score, idx = result
# print(f"Best match: {latin_db[idx]} ({score}%)")
#
# # --- FastAPI integration ---
# # from fastapi import FastAPI
# # from pydantic import BaseModel
# #
# # app = FastAPI()
# # matcher = NameMatcher(scheme='ar2bw')
# #
# # class MatchRequest(BaseModel):
# #     name1: str
# #     name2: str
# #
# # @app.post("/match")
# # def match_names(req: MatchRequest):
# #     return {"score": matcher.match(req.name1, req.name2)}
