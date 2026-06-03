"""
Retrieval layer for the Contract Clause Explainer.

Given a plain-English question, decide WHICH clauses are most likely relevant
and return only those to the LLM. This is the first agentic decision — the
agent selects clauses rather than dumping the whole contract into context.

TF-IDF over clauses (not vector embeddings) because a single contract is a
small corpus, this runs instantly with no heavy dependencies, and it's fully
explainable. A legal synonym map bridges the gap between how a normal person
phrases a question ("can they fire me without notice?") and contract language
("termination", "notice period", "cause").
"""

import math
import re
from collections import Counter

import config


# Plain-English -> legalese bridges. Everyday users don't say "indemnify".
SYNONYMS = {
    "fire": ["terminate", "termination", "dismiss", "dismissal", "cause"],
    "fired": ["terminate", "termination", "dismissal"],
    "quit": ["resign", "resignation", "termination", "notice"],
    "leave": ["terminate", "resign", "notice", "vacate"],
    "evict": ["eviction", "terminate", "vacate", "possession", "tenancy"],
    "kick": ["evict", "eviction", "terminate", "vacate"],
    "rent": ["rent", "payment", "due", "lease", "premises"],
    "deposit": ["security", "deposit", "refund", "damages"],
    "pay": ["payment", "fee", "compensation", "remuneration", "salary"],
    "money": ["payment", "fee", "compensation", "damages", "penalty"],
    "penalty": ["penalty", "liquidated", "damages", "breach", "default"],
    "fine": ["penalty", "damages", "charge", "fee"],
    "cancel": ["terminate", "termination", "cancellation", "rescind"],
    "renew": ["renewal", "renew", "extension", "auto-renew", "term"],
    "secret": ["confidential", "confidentiality", "non-disclosure", "proprietary"],
    "compete": ["non-compete", "competition", "restraint", "solicit"],
    "sue": ["liability", "indemnify", "indemnification", "claim", "dispute"],
    "blame": ["liability", "indemnify", "responsible", "fault"],
    "notice": ["notice", "notify", "written", "days", "period"],
    "hours": ["working", "hours", "overtime", "shift", "schedule"],
    "ip": ["intellectual", "property", "ownership", "work", "rights"],
    "own": ["ownership", "title", "intellectual", "property", "rights"],
    "break": ["breach", "default", "violation", "fail"],
}

_WORD_RE = re.compile(r"[a-z0-9\.\-]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _expand(question: str) -> list[str]:
    toks = _tokenize(question)
    out = list(toks)
    for t in toks:
        if t in SYNONYMS:
            out.extend(SYNONYMS[t])
    return out


class RetrievedClause:
    def __init__(self, clause, score):
        self.clause = clause
        self.score = score

    def __repr__(self):
        return f"<Retrieved {self.clause.ref!r} score={self.score:.3f}>"


class Retriever:
    def __init__(self, clauses):
        self.clauses = [c for c in clauses if c.text.strip()]
        self._toks = [_tokenize(c.text) for c in self.clauses]
        self._df = Counter()
        for toks in self._toks:
            for term in set(toks):
                self._df[term] += 1
        self._n = max(len(self.clauses), 1)

    def _idf(self, term):
        return math.log((1 + self._n) / (1 + self._df.get(term, 0))) + 1.0

    def search(self, question, top_k=None):
        if top_k is None:
            top_k = config.TOP_K_CLAUSES
        q = Counter(_expand(question))
        scored = []
        for clause, toks in zip(self.clauses, self._toks):
            if not toks:
                continue
            tf = Counter(toks)
            length = len(toks)
            score = 0.0
            for term, qw in q.items():
                if term in tf:
                    score += (tf[term] / length) * self._idf(term) * qw
            scored.append(RetrievedClause(clause, score))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def best_score(self, question):
        r = self.search(question, top_k=1)
        return r[0].score if r else 0.0
