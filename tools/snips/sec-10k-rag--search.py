"""Step 4: hybrid search over the passages: keywords (BM25) + meaning (embeddings), merged by rank.

    ./venv/bin/python search.py "What was Microsoft's total revenue?"

If the question names a company, only that company's passages are searched.
"""
import json
import math
import re
import sys
from collections import Counter

import numpy as np

import llm
from llm import HERE

ALIASES = {"AAPL": ("apple", "aapl"), "MSFT": ("microsoft", "msft"), "AMZN": ("amazon", "amzn", "aws"),
           "GOOGL": ("alphabet", "google", "googl", "youtube"), "NVDA": ("nvidia", "nvda")}
TOKEN = re.compile(r"[a-z0-9][a-z0-9,.]*[a-z0-9]|[a-z0-9]")


def tokens(text):
    return [t.replace(",", "") for t in TOKEN.findall(text.lower())]


class Index:
    def __init__(self):
        self.chunks = [json.loads(l) for l in open(HERE / "data" / "chunks.jsonl")]
        self.vecs = np.load(HERE / "data" / "embeddings.npy")
        self.docs = [Counter(tokens(f"{c['section']} {c['text']}")) for c in self.chunks]
        self.lens = np.array([sum(d.values()) for d in self.docs])
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def companies(self, q):
        ql = q.lower()
        return [t for t, names in ALIASES.items() if any(re.search(rf"\b{re.escape(a)}\b", ql) for a in names)]

    def bm25(self, q, k1=1.5, b=0.75):
        qt, avg = set(tokens(q)), self.lens.mean()
        return np.array([sum(self.idf.get(t, 0) * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * L / avg)) for t in qt if t in d)
                         for d, L in zip(self.docs, self.lens)])

    def search(self, q, k=6, mode="hybrid", qvec=None):
        allowed = set(self.companies(q)) or {c["ticker"] for c in self.chunks}
        mask = np.array([c["ticker"] in allowed for c in self.chunks])
        ranks = []
        if mode in ("hybrid", "keyword"):
            s = np.where(mask, self.bm25(q), -np.inf)
            ranks.append(np.argsort(-s)[:50])
        if mode in ("hybrid", "vector"):
            qv = np.asarray(qvec if qvec is not None else llm.embed([q])[0], dtype=np.float32)
            s = np.where(mask, self.vecs @ (qv / np.linalg.norm(qv)), -np.inf)
            ranks.append(np.argsort(-s)[:50])
        fused = Counter()                                  # reciprocal rank fusion: 1/(60 + rank) from each list
        for r in ranks:
            for pos, i in enumerate(r):
                fused[int(i)] += 1 / (60 + pos + 1)
        return [self.chunks[i] for i, _ in fused.most_common(k)]


if __name__ == "__main__":
    idx = Index()
    q = " ".join(sys.argv[1:]) or "What was Microsoft's total revenue?"
    for c in idx.search(q):
        print(f"{c['id']}  {c['section']}\n   {c['text'][:160].replace(chr(10), ' / ')}")
    print(f"(search cost ${llm.spent['usd']:.6f})")
