"""Step 5: answer a question from the 10-Ks, citing the passages used, or say the filings don't contain it.

    ./venv/bin/python ask.py "How much did NVIDIA spend on research and development?"
"""
import json
import sys

import llm
from search import Index

SYSTEM = """You answer questions about companies' annual reports (10-K filings) using ONLY the numbered passages given.
Rules:
- Use only facts stated in the passages. Never use outside knowledge, never guess, never compute a figure the passages don't support.
- Cite every passage you used by its id, e.g. MSFT-0102.
- If the passages don't contain the answer, set found to false and say the filings provided don't state it.
- When the question asks for a dollar amount, also give it in value_usd_millions (millions of US dollars, as a plain number);
  otherwise value_usd_millions is null. Tables in these filings are usually "in millions"; read the table's unit line.
- Keep the answer to 1-3 sentences and name the fiscal year the figure is for."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["found", "answer", "value_usd_millions", "citations"],
    "properties": {
        "found": {"type": "boolean"},
        "answer": {"type": "string"},
        "value_usd_millions": {"type": ["number", "null"]},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
}


def answer(idx, question, k=6, mode="vector"):
    # meaning-only search, top 6: it beat keyword and hybrid search on the test set (results/retrieval.json)
    passages = idx.search(question, k=k, mode=mode)
    context = "\n\n".join(f"[{p['id']}] {p['company']} 10-K, {p['section']}\n{p['text']}" for p in passages)
    out = llm.chat_json(SYSTEM, f"Passages:\n\n{context}\n\nQuestion: {question}", SCHEMA)
    ids = {p["id"] for p in passages}
    out["citations"] = [c for c in out["citations"] if c in ids]       # drop any id that wasn't actually provided
    out["retrieved"] = [p["id"] for p in passages]
    return out


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "How much did NVIDIA spend on research and development?"
    r = answer(Index(), q)
    print(json.dumps(r, indent=2))
    print(f"cost ${llm.spent['usd']:.4f} ({llm.spent['in_tokens']:,} in / {llm.spent['out_tokens']:,} out tokens)")
