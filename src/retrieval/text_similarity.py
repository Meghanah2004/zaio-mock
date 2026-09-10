"""Small, dependency-free pairwise text similarity helper.

Used wherever the pipeline needs "how similar are these two specific
pieces of text" (a generated question vs. its cited evidence; a new
question vs. an earlier paper's question for the same section) rather than
"how similar is this text to anything in a large corpus" (that broader
case is src/validation/novelty_checker.ReferenceCorpusIndex, which needs a
real IDF-weighted index because it ranks against thousands of chunks).
Plain term-frequency cosine similarity is deliberately used here instead:
with only two short texts being compared, IDF weighting from a two-document
"corpus" would be meaningless, so this is simpler AND more correct for the
pairwise case, not just cheaper.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "were",
        "be", "been", "being", "with", "as", "at", "by", "from", "this", "that", "these", "those",
        "it", "its", "it's", "you", "your", "we", "our", "they", "their", "he", "she", "his", "her",
        "i", "not", "no", "do", "does", "did", "can", "will", "would", "should", "could", "may",
        "might", "must", "have", "has", "had",
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2]


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Plain (non-IDF) term-frequency cosine similarity in [0.0, 1.0]."""
    tf_a = Counter(tokenize(text_a))
    tf_b = Counter(tokenize(text_b))
    if not tf_a or not tf_b:
        return 0.0
    common_terms = set(tf_a) & set(tf_b)
    dot_product = sum(tf_a[t] * tf_b[t] for t in common_terms)
    norm_a = math.sqrt(sum(v * v for v in tf_a.values()))
    norm_b = math.sqrt(sum(v * v for v in tf_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)
