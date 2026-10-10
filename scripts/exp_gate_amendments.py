"""Diagnose why SWK-145 is declined although retrieval found both provisions.

    docker compose run --rm ml python scripts/exp_gate_amendments.py

SWK-145 (Sarawak: may an employer move to five days of nine hours to meet
the 45-hour week?) has recall 1.00 but a gate score of 0.0286, below the
threshold 0.0325. Hypotheses, each tested here:

  H1 bug: the sliding window cuts the relevant proviso badly.
  H2 bug: the gate score is not the top reranker score of the result.
  H3 design: the Sarawak principal text still says "forty-eight", which
     contradicts the question's "45"; the reranker scores it down.
  H4 design: the amending chunk (A1754 s.34, "substitute forty-five for
     forty-eight") has no context, so it scores low on its own.

Controls: the same rule in the EA (s.60A(1)) and Sabah (s.104(1)), whose
texts already say forty-five. Diagnostic only: the "patched" and "joined"
passages are never shown to users or cited.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.rerank import Reranker, passage  # noqa: E402

QUESTION_ID = "SWK-145"


def main() -> None:
    chunks = {c["chunk_id"]: c for c in map(json.loads, Path("data/processed/chunks.jsonl").open(encoding="utf-8"))}
    gold = {g["id"]: g for g in map(json.loads, Path("data/eval/gold_set.jsonl").open(encoding="utf-8"))}
    question = gold[QUESTION_ID]["question"]
    records = [json.loads(l) for l in Path("data/eval/runs/2026-10-10_retrieval_records.jsonl").open(encoding="utf-8")]
    record = next(r for r in records if r["mode"] == "hybrid_rerank" and r["id"] == QUESTION_ID)

    reranker = Reranker()
    model = reranker._load()
    tok = model.tokenizer

    def score(text: str) -> float:
        out = model.compute_score([[question, text]], normalize=True, max_length=512)
        return float(out[0] if isinstance(out, list) else out)

    print(f"Q: {question}\n")

    # H2: is the recorded gate score the top reranker score of the ranked list?
    ranked = reranker.rerank(question, record["ranked"], chunks)
    print("H2 ranked list rescored now:")
    for cid, s in ranked:
        print(f"   {s:.4f}  {cid}")
    print(f"   recorded gate score {record['gate_score']:.4f}; top now {ranked[0][1]:.4f}\n")

    # H1: windows of the principal chunk
    principal = chunks["SWK76_s105_1"]
    n_tokens = len(tok.encode(passage(principal), add_special_tokens=False))
    windows = reranker.windows(question, principal)
    print(f"H1 SWK76_s105_1: {n_tokens} tokens (citation + title + content), {len(windows)} window(s)")
    for i, w in enumerate(windows):
        has_nine = "nine hours" in w
        print(f"   window {i}: score {score(w):.4f}  contains 'nine hours': {has_nine}  starts: {w[:70]!r}")
    print()

    # Controls and H3/H4
    def row(label: str, text: str) -> None:
        print(f"   {score(text):.4f}  {label}")

    print("Controls (same rule, text already says forty-five):")
    for cid in ("EA1955_s60A_1", "SBH67_s104_1"):
        c = chunks[cid]
        best = max(score(w) for w in reranker.windows(question, c))
        print(f"   {best:.4f}  {c['citation']}  ({c['status']})")
    print("\nH3/H4 Sarawak variants:")
    row("principal as indexed (says forty-eight)", passage(principal))
    def best_window(chunk: dict) -> float:
        return max(score(w) for w in reranker.windows(question, chunk))

    print(f"   {best_window(principal):.4f}  principal as indexed (says forty-eight), best window")
    patched = dict(principal, content=principal["content"].replace("forty-eight", "forty-five"))
    print(f"   {best_window(patched):.4f}  principal with 'forty-eight' -> 'forty-five' (diagnostic only)")
    print(f"   {best_window(chunks['A1754_s34']):.4f}  amending chunk A1754 s.34 alone")
    joined = dict(principal, content="[As amended by Act A1754 s.34: " + chunks["A1754_s34"]["content"] + "] "
                  + principal["content"])
    print(f"   {best_window(joined):.4f}  amendment note + principal in one passage, best window")
    reranker.close()


if __name__ == "__main__":
    main()
