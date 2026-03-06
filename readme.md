# Algerian Name Matcher

A production-ready Python library for **cross-script fuzzy name matching** between Arabic and Latin (French/English) romanised Algerian names. Built for deduplication, record linkage, and identity resolution in Algerian administrative datasets.

---

## The Problem

Algerian names exist in two competing scripts with no standardised transliteration:

| Arabic | Latin (French) | Latin (English) |
|---|---|---|
| عبد الرحمن بوزيد | Bouzid Abderrahmane | Abderrezak Bouzid |
| هدى بن عيسى | Benaissa Houda | Houda Benaissa |
| زين الدين مخلوفي | Zinedine Makhloufi | Zineddine Makhloufi |

Off-the-shelf fuzzy matchers fail on these because they treat names as bags of characters, letting a shared surname rescue a completely wrong first name — a **collision**.

---

## How It Works

### Normalisation Pipeline

Every name, regardless of script, passes through the same pipeline and emerges as a single phonetic Latin form before scoring:

```
Arabic input
  │
  ├─ Fuse prefixes (بن عيسى → بنعيسى, عبد الله → عبدالله)
  ├─ Remove harakat, unify alif/hamza variants, strip ال
  ├─ Transliterate via Buckwalter (camel-tools)
  ├─ Buckwalter phonetic collapse (emphatics, غ, خ …)
  │
  └─▶ shared path
        ├─ Lowercase + strip punctuation
        ├─ Latin phonetics (dj→j, ch→sh, ou→u …)
        ├─ Fuse Latin prefixes (Ben Aissa → Benaissa)
        └─ Deep phonetic collapse (e→a, h→a, gh→g …)

Latin input
  │
  └─▶ shared path (same steps, skipping the Arabic-only ones)
```

### Scoring Algorithm

```
score = bidirectional_JaroWinkler × 0.7 + token_sort_ratio × 0.3
```

Protected by two guards:

1. **Consonant-skeleton gate** — vowels are stripped from both sides before the worst-case bidirectional match is checked. `hdy` and `houda` both reduce to `hd`, so the gate passes correctly even though the raw strings look very different.

2. **Asymmetry penalty** — if the two names have different word counts after normalisation, the score is scaled down proportionally.

---

## Installation

```bash
pip install rapidfuzz camel-tools
```

> `camel-tools` requires its data files on first use:
> ```bash
> camel_data -i morphology-db-msa-r13
> ```

---

## Quick Start

```python
from name_matcher import NameMatcher, _scorer
from rapidfuzz import process

matcher = NameMatcher()  # defaults to Buckwalter (ar2bw)
```

### Single pair comparison

```python
score = matcher.match("عبد الرحمن بوزيد", "Bouzid Abderrahmane")
print(score)  # e.g. 87.4
```

### Normalise a name

```python
norm = matcher.normalize("هدى بن عيسى")
print(norm)  # e.g. "bnaisa ada"
```

### Bulk search — find best match in a database

```python
latin_db = ["Bouzid Abderrahmane", "Kadri Mohammed", "Benaissa Houda"]
normalized_db = {i: matcher.normalize(n) for i, n in enumerate(latin_db)}

query  = matcher.normalize("هدى بن عيسى")
result = process.extractOne(query, normalized_db, scorer=_scorer)
_, score, idx = result
print(f"Best match: {latin_db[idx]} ({score}%)")
# Best match: Benaissa Houda (88.5%)
```

---

## FastAPI Integration

```python
from fastapi import FastAPI
from pydantic import BaseModel
from name_matcher import NameMatcher

app     = FastAPI()
matcher = NameMatcher()  # instantiate once at startup


class MatchRequest(BaseModel):
    name1: str
    name2: str

class MatchResponse(BaseModel):
    name1_normalized: str
    name2_normalized: str
    score: float


@app.post("/match", response_model=MatchResponse)
def match_names(req: MatchRequest):
    n1 = matcher.normalize(req.name1)
    n2 = matcher.normalize(req.name2)
    return MatchResponse(
        name1_normalized=n1,
        name2_normalized=n2,
        score=NameMatcher.score_normalized(n1, n2),
    )
```

---

## Public API

| Symbol | Type | Description |
|---|---|---|
| `NameMatcher(scheme)` | class | Main entry point. `scheme` defaults to `'ar2bw'` (Buckwalter). |
| `matcher.normalize(text)` | method | Normalise any name (Arabic or Latin) → phonetic Latin string. |
| `matcher.match(name1, name2)` | method | Compare two raw names and return a similarity score (0–100). |
| `NameMatcher.score_normalized(s1, s2)` | static method | Score two **already-normalised** strings. Use for bulk pre-normalised comparisons. |
| `_scorer(s1, s2, **kwargs)` | function | `rapidfuzz.process`-compatible wrapper around `score_normalized`. |

## Phonetic Rules Reference

### Buckwalter collapse (Arabic → Latin, before lowercasing)

| Rule | Example |
|---|---|
| `$` → `sh` | شريف → Sherif |
| `H/T/D/S/Z` → `h/t/d/s/z` | emphatic consonant collapse |
| `E` → `a` | عين approximation |
| `G` → `g` | غين |
| `x` → `kh` | خاء |
| `q` → `k` | قاف (Algerian Latin writes ق as k) |

### Latin phonetics (French ↔ English unification)

| Rule | Example |
|---|---|
| `dj` → `j` | Djamila → Jamila |
| `ch` → `sh` | Cherif → Sherif |
| `ou` → `u` | Younes → Yunes |
| `kh` → `k` | Khaled → Kaled |
| `gh` → `g` | Ghanem → Ganem |

### Deep phonetic collapse (applied last)

| Rule | Purpose |
|---|---|
| `p/h` → `a` | Taa Marbouta fix (ة → Buckwalter `p` or `h`) |
| `ou/w/o` → `u` | Vowel unification |
| `y/ee` → `i` | Vowel unification |
| `e` → `a` | Kamel ↔ Kamal, Abdel ↔ Abdal |
| `sh/ch/c` → `s` | Consonant unification |
| `th/v` → `t` | Othmane (عثمان) |
| `gh/q` → `g` | Qaf/Gha trap (بوقرة ↔ Bougherra) |

---

## Dependencies

| Package | Purpose |
|---|---|
| [`rapidfuzz`](https://github.com/maxbachmann/RapidFuzz) | JaroWinkler, token_sort_ratio, bulk search |
| [`camel-tools`](https://github.com/CAMeL-Lab/cameltools) | Arabic → Buckwalter transliteration |

---

## Benchmarks

Tested on a synthetic dataset of **1,000 Algerian name pairs** (randomly sampled from 200+ common first/last names), featuring:
- Mixed scripts (Arabic ↔ Latin)
- Random name swaps (First Last ↔ Last First)
- Varied transliterations (French ↔ English)

| Metric | Result |
|---|---|
| **Accuracy** | ~90.6% |

> [!NOTE]
> Most failures (~9%) are "clean collisions" where two distinct names become phonetically identical (e.g., *Hassan* `حسن` vs *Hocine* `حسين`). In administrative data, these are often resolved by adding a Birth Date guard.

---

## Caveats & Known Collisions

While highly effective, phonetic matching has inherent limitations:

1.  **Semantic Similarities**: `Hassan` (حسن) and `Hocine` (حسين) are distinct names but collapse to similar phonetic forms (`hasan` vs `hasin` → both become `hasan` after deep collapse).
2.  **Short Names**: Very short surnames (e.g., "Ali", "Abad") have less entropy and are more prone to false positives if the first name is also common.
3.  **Title Removal**: The library automatically strips the "Al-" (ال) prefix from surnames, which is standard for matching but might be undesirable for some display purposes.

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details. (Note: `camel-tools` and `rapidfuzz` have their own licenses).

