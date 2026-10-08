"""Compare retrieval methods side by side in the browser.

    docker compose run --rm -p 127.0.0.1:8000:8000 ml python scripts/compare.py
    then open http://localhost:8000

For one question, four columns:
    Dense            bge-m3 cosine similarity, top 20 kept
    BM25             keyword scores, top 20 kept
    Hybrid           reciprocal rank fusion of the two (src/retrieval/fusion.py)
    Hybrid + rerank  the hybrid top 20 rescored by bge-reranker-large

A learning and inspection tool, not the M3 pipeline: it has no abstention
gate, no amendment-link following and no definition co-retrieval. Both
models stay loaded (about 2.5 GB of GPU memory together) so each question
answers in about a second.

Standard library HTTP server, single-threaded, bound to localhost only.
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.indexing.bm25 import Bm25Index  # noqa: E402
from src.indexing.embed import BgeM3Embedder  # noqa: E402
from src.indexing.store import ChunkStore, connect  # noqa: E402
from src.retrieval.fusion import rrf  # noqa: E402
from src.retrieval.rerank import Reranker  # noqa: E402

POOL = 20  # candidates kept per retriever, and reranked
PORT = 8000


class Engine:
    def __init__(self) -> None:
        self.config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
        settings = self.config["indexing"]
        self.version = json.loads(Path(settings["manifest_path"]).read_text(encoding="utf-8"))["index_version"]
        chunks_path = Path(self.config["corpus"]["processed_dir"]) / "chunks.jsonl"
        self.chunks = {c["chunk_id"]: c for c in map(json.loads, chunks_path.open(encoding="utf-8"))}
        print("loading bge-m3 and bge-reranker-large...", flush=True)
        self.embedder = BgeM3Embedder(settings["embedding_model"], settings["embed_batch_size"])
        self.embedder.encode(["warm up"])
        self.reranker = Reranker()
        self.reranker.rerank("warm up", [next(iter(self.chunks))], self.chunks)
        self.bm25 = Bm25Index.load(settings["bm25_dir"])
        self.store = ChunkStore(connect(self.config), settings["embedding_dim"])

    def _item(self, rank: int, chunk_id: str, score: float, **extra) -> dict:
        chunk = self.chunks[chunk_id]
        return {
            "rank": rank, "chunk_id": chunk_id, "score": round(score, 4),
            "citation": chunk["citation"], "title": chunk.get("section_title"),
            "status": chunk["status"], "amended_by": chunk.get("amended_by") or [],
            "jurisdiction": chunk["jurisdiction"], "content": chunk["content"], **extra,
        }

    def search(self, query: str, region: str | None, k: int) -> dict:
        allowed = self.config["retrieval"]["regions"][region] if region else None
        timings = {}

        t = time.perf_counter()
        vector = self.embedder.encode([query])[0][0]
        dense = self.store.dense_search(vector, POOL, allowed, self.version)
        timings["dense"] = time.perf_counter() - t

        t = time.perf_counter()
        bm25 = self.bm25.search(query, POOL, allowed)
        timings["bm25"] = time.perf_counter() - t

        t = time.perf_counter()
        hybrid = rrf([dense, bm25])[:POOL]
        timings["hybrid"] = time.perf_counter() - t

        t = time.perf_counter()
        reranked = self.reranker.rerank(query, [c for c, _ in hybrid], self.chunks)
        timings["rerank"] = time.perf_counter() - t

        hybrid_rank = {c: i for i, (c, _) in enumerate(hybrid, start=1)}
        dense_rank = {c: i for i, (c, _) in enumerate(dense, start=1)}
        bm25_rank = {c: i for i, (c, _) in enumerate(bm25, start=1)}
        return {
            "query": query, "region": region, "allowed": allowed, "pool": POOL,
            "dense": [self._item(i, c, s) for i, (c, s) in enumerate(dense[:k], 1)],
            "bm25": [self._item(i, c, s) for i, (c, s) in enumerate(bm25[:k], 1)],
            "hybrid": [self._item(i, c, s, from_dense=dense_rank.get(c), from_bm25=bm25_rank.get(c))
                       for i, (c, s) in enumerate(hybrid[:k], 1)],
            "rerank": [self._item(i, c, s, from_hybrid=hybrid_rank.get(c))
                       for i, (c, s) in enumerate(reranked[:k], 1)],
            "top_rerank_score": round(reranked[0][1], 4) if reranked else None,
            "timings_ms": {name: round(seconds * 1000) for name, seconds in timings.items()},
        }


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Retrieval Comparison</title>
<style>
:root { --bg:#f7f7f5; --panel:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#e2e2dc;
        --accent:#2f5d8a; --warn:#a24a00; --good:#2e7d4f; --hl:#fff3c4; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --panel:#1f1f1d; --ink:#ececea; --muted:#9a9a94; --line:#33332f;
          --accent:#8ab4e0; --warn:#f0a35e; --good:#7fcf9c; --hl:#4a4224; } }
* { box-sizing: border-box; }
body { margin:0; font:14px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--ink); }
header { padding:16px 20px; border-bottom:1px solid var(--line); background:var(--panel); }
h1 { font-size:18px; margin:0 0 10px; }
form { display:flex; gap:8px; flex-wrap:wrap; }
input[type=text] { flex:1 1 360px; padding:8px 10px; font-size:15px; border:1px solid var(--line);
  border-radius:6px; background:var(--bg); color:var(--ink); }
select, button { padding:8px 10px; font-size:14px; border-radius:6px; border:1px solid var(--line);
  background:var(--bg); color:var(--ink); }
button { background:var(--accent); color:#fff; border:none; cursor:pointer; }
#meta { margin-top:8px; color:var(--muted); font-size:13px; }
#examples a { color:var(--accent); cursor:pointer; margin-right:12px; }
main { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; padding:16px 20px; }
@media (max-width: 1100px) { main { grid-template-columns:repeat(2, minmax(0,1fr)); } }
@media (max-width: 640px) { main { grid-template-columns:1fr; padding:12px; } header { padding:12px; } }
.col { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px; min-width:0; }
.col h2 { font-size:14px; margin:0; }
.col .how { color:var(--muted); font-size:12px; margin:2px 0 8px; }
.item { border-top:1px solid var(--line); padding:8px 4px; cursor:pointer; border-radius:4px; }
.item.hl { background:var(--hl); }
.top { display:flex; gap:6px; align-items:baseline; }
.rank { font-weight:600; min-width:18px; }
.cite { font-weight:600; overflow-wrap:anywhere; }
.score { margin-left:auto; color:var(--muted); font-variant-numeric:tabular-nums; }
.title { color:var(--muted); font-size:12px; }
.flag { color:var(--warn); font-size:12px; font-weight:600; }
.from { color:var(--muted); font-size:12px; }
.up { color:var(--good); } .down { color:var(--warn); }
.text { font-size:13px; margin-top:4px; white-space:pre-wrap; }
.clip { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.empty { color:var(--muted); font-style:italic; padding:8px 4px; }
</style></head><body>
<header>
  <h1>Retrieval comparison: Dense vs BM25 vs Hybrid vs Hybrid + Rerank</h1>
  <form id="f">
    <input id="q" type="text" placeholder="Ask a question in English" autofocus>
    <select id="region">
      <option value="">All regions</option>
      <option value="peninsular">Peninsular + Labuan</option>
      <option value="sabah">Sabah</option>
      <option value="sarawak">Sarawak</option>
    </select>
    <select id="k"><option>5</option><option selected>10</option><option>20</option></select>
    <button>Search</button>
  </form>
  <div id="meta">Try: <span id="examples"></span></div>
</header>
<main id="cols"></main>
<script>
const EXAMPLES = [
  ["how many days of maternity leave", "sabah"], ["maternity leave", "sarawak"],
  ["section 60E", ""], ["my boss fired me without telling me", "peninsular"],
  ["can my employer cut my salary", "peninsular"], ["can I bring my dog to work", ""]];
const COLS = [
  ["dense", "Dense (bge-m3)", "meaning; cosine similarity 0 to 1"],
  ["bm25", "BM25", "shared words; score has no upper bound"],
  ["hybrid", "Hybrid (RRF)", "ranks of both lists fused; rank only"],
  ["rerank", "Hybrid + Rerank", "bge-reranker-large reads question and chunk together; 0 to 1"]];
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag);
  if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

for (const [q, r] of EXAMPLES) {
  const a = el("a", null, q + (r ? " [" + r + "]" : ""));
  a.onclick = () => { $("q").value = q; $("region").value = r; run(); };
  $("examples").append(a);
}

function highlight(id, on) {
  document.querySelectorAll('[data-id="' + CSS.escape(id) + '"]').forEach(e => e.classList.toggle("hl", on));
}

function card(key, it) {
  const d = el("div", "item"); d.dataset.id = it.chunk_id;
  const top = el("div", "top");
  top.append(el("span", "rank", it.rank + "."), el("span", "cite", it.citation),
             el("span", "score", key === "hybrid" ? it.score.toFixed(4) : it.score.toFixed(3)));
  d.append(top);
  if (it.title) d.append(el("div", "title", it.title));
  const flags = [];
  if (it.status !== "in_force") flags.push(it.status.toUpperCase());
  if (it.amended_by.length) flags.push("amended by " + it.amended_by.slice(0, 2).join(", "));
  if (flags.length) d.append(el("div", "flag", flags.join(" · ")));
  if (key === "hybrid") d.append(el("div", "from",
      "dense #" + (it.from_dense ?? "–") + " · BM25 #" + (it.from_bm25 ?? "–")));
  if (key === "rerank") {
    const f = el("div", "from"); const was = it.from_hybrid;
    const moved = was - it.rank;
    f.append("was hybrid #" + was + " ");
    if (moved) f.append(el("span", moved > 0 ? "up" : "down", (moved > 0 ? "▲" : "▼") + Math.abs(moved)));
    d.append(f);
  }
  const t = el("div", "text clip", it.content); d.append(t);
  d.onclick = () => t.classList.toggle("clip");
  d.onmouseenter = () => highlight(it.chunk_id, true);
  d.onmouseleave = () => highlight(it.chunk_id, false);
  return d;
}

async function run(ev) {
  if (ev) ev.preventDefault();
  const q = $("q").value.trim(); if (!q) return;
  $("cols").replaceChildren(el("div", "empty", "Searching..."));
  const params = new URLSearchParams({ q, region: $("region").value, k: $("k").value });
  const res = await fetch("/api/search?" + params); const data = await res.json();
  if (data.error) { $("cols").replaceChildren(el("div", "empty", data.error)); return; }
  const t = data.timings_ms;
  $("meta").textContent = "Filter: " + (data.allowed ? data.allowed.join(" + ") : "none") +
    " · top reranker score " + data.top_rerank_score + " (not yet a calibrated threshold)" +
    " · time ms: dense " + t.dense + ", BM25 " + t.bm25 + ", rerank " + t.rerank + " · hover to match, click to expand";
  const cols = COLS.map(([key, name, how]) => {
    const c = el("section", "col"); c.append(el("h2", null, name), el("div", "how", how));
    if (!data[key].length) c.append(el("div", "empty", "nothing found"));
    data[key].forEach(it => c.append(card(key, it))); return c; });
  $("cols").replaceChildren(...cols);
}
$("f").onsubmit = run;
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    engine: Engine

    def _send(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/api/search":
            params = parse_qs(url.query)
            query = params.get("q", [""])[0].strip()
            region = params.get("region", [""])[0] or None
            k = max(1, min(POOL, int(params.get("k", ["10"])[0])))
            if not query or (region and region not in self.engine.config["retrieval"]["regions"]):
                body = {"error": "Enter a question (and a valid region)."}
            else:
                body = self.engine.search(query, region, k)
            self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, fmt: str, *args) -> None:
        pass


def main() -> None:
    Handler.engine = Engine()
    print(f"ready: open http://localhost:{PORT}  (Ctrl+C to stop)", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
