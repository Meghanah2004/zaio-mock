"""Lightweight lexical novelty / reference-overlap screening.

This is a SCREENING mechanism, not proof of originality. It flags generated
question text that is lexically close to some chunk of the reference
corpus, using plain TF-IDF + cosine similarity (pure Python, no ML
dependency). A HIGH score means "go read this before trusting it was
independently written"; a LOW score does not certify the text is original,
only that it isn't a close lexical match to anything in the supplied
corpus. See docs/DESIGN.md, "Limitations of the novelty checker".

Deliberately NOT used here: semantic/embedding similarity, paraphrase
detection, or any claim that this catches disguised copying (renamed
variables, reordered clauses, translated wording). Those all require either
a real embedding model or LLM judgement - the pipeline's separate quality
review stage (src/validation/quality_reviewer.py) is what's positioned to
catch that, per docs/DESIGN.md, and even that is not a guarantee.

``ReferenceCorpusIndex`` is also reused (via its ``top_k`` method) by
src/retrieval/evidence_selector.py to retrieve the actual learner-guide
passages handed to the LLM at generation time - the SAME lightweight TF-IDF
machinery, no second index, no added dependency. It lives here rather than
under src/retrieval/ because it predates that package and the novelty
checker remains its primary consumer; retrieval imports it from here.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    ["a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "were", "be", "been", "being", "with", "as", "at", "by", "from", "this", "that", "these", "those", "it", "its", "it's", "you", "your", "we", "our", "they", "their", "he", "she", "his", "her", "i", "not", "no", "do", "does", "did", "can", "will", "would", "should", "could", "may", "might", "must", "have", "has", "had"]
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2]


class ReferenceCorpusIndex:
    """A tiny inverted TF-IDF index over reference-text chunks."""

    def __init__(self, chunks: list[dict[str, Any]]):
        self.chunks = chunks
        self._df: Counter[str] = Counter()
        self._chunk_tf: list[Counter[str]] = []
        for c in chunks:
            tokens = _tokenize(c["text"])
            tf = Counter(tokens)
            self._chunk_tf.append(tf)
            for term in tf:
                self._df[term] += 1

        n_docs = max(len(chunks), 1)
        self._idf: dict[str, float] = {term: math.log((n_docs + 1) / (df + 1)) + 1.0 for term, df in self._df.items()}

        self._inverted: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self._chunk_norm: list[float] = [0.0] * len(chunks)
        for idx, tf in enumerate(self._chunk_tf):
            weights = {term: count * self._idf.get(term, 0.0) for term, count in tf.items()}
            norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
            self._chunk_norm[idx] = norm
            for term, w in weights.items():
                self._inverted[term].append((idx, w))

    def max_similarity(self, text: str) -> tuple[float, dict[str, Any] | None]:
        tokens = _tokenize(text)
        if not tokens or not self.chunks:
            return 0.0, None
        tf = Counter(tokens)
        weights = {term: count * self._idf.get(term, 0.0) for term, count in tf.items() if term in self._idf}
        if not weights:
            return 0.0, None
        query_norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0

        scores: dict[int, float] = defaultdict(float)
        for term, qw in weights.items():
            for chunk_idx, cw in self._inverted.get(term, []):
                scores[chunk_idx] += qw * cw

        best_idx, best_score = None, 0.0
        for idx, raw_score in scores.items():
            cosine = raw_score / (query_norm * self._chunk_norm[idx])
            if cosine > best_score:
                best_score, best_idx = cosine, idx

        matched = self.chunks[best_idx] if best_idx is not None else None
        return best_score, {"source": matched["source"]} if matched else None

    def top_k(self, query: str, k: int, chunk_filter: Any = None) -> list[tuple[float, dict[str, Any]]]:
        """Return up to ``k`` corpus chunks best matching ``query``, ranked by
        cosine similarity, highest first.

        ``chunk_filter``, if given, is called as ``chunk_filter(chunk) -> bool``
        and restricts which chunks are eligible before ranking (e.g. "only
        chunks tagged with this Knowledge Topic code"). Used by
        ``src/retrieval/evidence_selector.py`` to retrieve real learner-guide
        passages for a blueprint section instead of a single "most similar"
        result - see that module for how this feeds evidence-grounded
        generation.
        """
        tokens = _tokenize(query)
        if not tokens or not self.chunks:
            return []
        tf = Counter(tokens)
        weights = {term: count * self._idf.get(term, 0.0) for term, count in tf.items() if term in self._idf}
        if not weights:
            return []
        query_norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0

        scores: dict[int, float] = defaultdict(float)
        for term, qw in weights.items():
            for chunk_idx, cw in self._inverted.get(term, []):
                if chunk_filter is not None and not chunk_filter(self.chunks[chunk_idx]):
                    continue
                scores[chunk_idx] += qw * cw

        ranked = sorted(
            ((raw_score / (query_norm * self._chunk_norm[idx]), idx) for idx, raw_score in scores.items()),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [(score, self.chunks[idx]) for score, idx in ranked[:k] if score > 0.0]


def check_paper_novelty(
    paper: dict[str, Any],
    corpus_index: ReferenceCorpusIndex,
    warn_threshold: float,
    flag_threshold: float,
) -> dict[str, Any]:
    question_results = []
    worst_status = "pass"
    for section in paper["sections"]:
        for q in section["questions"]:
            text_parts = [q.get("scenario") or "", q.get("question", "")]
            text_parts.extend(sq["prompt"] for sq in q.get("sub_questions", []))
            combined_text = " ".join(text_parts)

            score, nearest = corpus_index.max_similarity(combined_text)
            if score >= flag_threshold:
                status = "regenerate"
            elif score >= warn_threshold:
                status = "flag_for_review"
            else:
                status = "pass"

            if status == "regenerate":
                worst_status = "regenerate"
            elif status == "flag_for_review" and worst_status == "pass":
                worst_status = "flag_for_review"

            question_results.append(
                {
                    "question_id": q["id"],
                    "max_similarity": round(score, 4),
                    "status": status,
                    "nearest_reference_source": nearest["source"] if nearest else None,
                }
            )

    return {
        "overall_status": worst_status,
        "passed": worst_status == "pass",
        "thresholds": {"warn": warn_threshold, "flag": flag_threshold},
        "question_results": question_results,
        "limitations": (
            "Lexical TF-IDF/cosine screening only: catches close wording overlap with the supplied "
            "corpus, not paraphrase, translation, semantic similarity, or copying from sources "
            "outside sdev/. A 'pass' here is NOT proof of originality - it is one input to review, "
            "not a certification."
        ),
    }
