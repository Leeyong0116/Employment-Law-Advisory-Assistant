"""Ask the M4 system questions in the browser, and browse a saved gold run.

    docker compose run --rm -p 127.0.0.1:8001:8001 ml python scripts/ask.py
    then open http://localhost:8001

Two tabs:
    Ask        a question and a region -> the full pipeline: retrieval (M3,
               hybrid + rerank, gate on) then generation (M4, the vLLM server
               on the HPC). Shows the answer, its sources with full text,
               notes, the traceability checks and what the model was shown.
    Gold run   the saved answers in data/eval/runs/*_answers*.jsonl next to
               the gold reference answer and expected citations.

A development tool for this phase, not the GetRight frontend (M5). Needs the
database (docker compose up -d) and, for Ask, GENERATOR_BASE_URL and a fresh
OOD_COOKIE_SECRET in .env. When the OOD session expires, paste a fresh cookie
into .env and ask again: .env is re-read after an expired session.

Standard library HTTP server, single-threaded, bound to localhost by the
port mapping above.
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.generation.answer import Answerer  # noqa: E402
from src.generation.llm import GeneratorError, SessionExpired  # noqa: E402
from src.retrieval.pipeline import Retriever  # noqa: E402

PORT = 8001
RUNS = Path("data/eval/runs")
GOLD = Path("data/eval/gold_set.jsonl")


class Engine:
    def __init__(self) -> None:
        self.config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
        print("loading retrieval (bge-m3, bge-reranker-large, database)...", flush=True)
        self.retriever = Retriever.from_config()
        self.retriever.retrieve("warm up the models", None)
        self.chunks = self.retriever.chunks
        self.answerer: Answerer | None = None

    def _answerer(self) -> Answerer:
        if self.answerer is None:
            load_dotenv(override=True)  # pick up a fresh cookie pasted into .env
            self.answerer = Answerer.from_config()
        return self.answerer

    def ask(self, query: str, region: str | None) -> dict:
        t = time.perf_counter()
        result = self.retriever.retrieve(query, region)
        retrieval_ms = round((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        try:
            answer = self._answerer().answer(result)
        except SessionExpired as error:
            self.answerer = None
            return {"error": f"{error}. Then ask again (no restart needed)."}
        except GeneratorError as error:
            return {"error": f"Generator error: {error}"}
        return {
            "answer": answer.model_dump(),
            "texts": {c.chunk_id: c.content for c in result.chunks},
            "context": [{"chunk_id": c.chunk_id, "citation": c.citation, "rank": c.rank, "score": c.score,
                         "added_because": c.added_because, "linked_from": c.linked_from, "status": c.status,
                         "jurisdiction": c.jurisdiction} for c in result.chunks],
            "gate": {"score": result.gate_score, "threshold": result.threshold, "abstained": result.abstained,
                     "reason": result.abstain_reason, "language": result.detected_language},
            "timings_ms": {"retrieval": retrieval_ms, "generation": round((time.perf_counter() - t) * 1000)},
        }

    def runs(self) -> list[str]:
        newest_first = sorted(RUNS.glob("*_answers*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.name for p in newest_first]

    def gold_run(self, name: str) -> dict:
        if name not in self.runs():
            return {"error": f"unknown run {name!r}"}
        gold = {g["id"]: g for g in map(json.loads, GOLD.open(encoding="utf-8"))}
        items = []
        for line in (RUNS / name).open(encoding="utf-8"):
            record = json.loads(line)
            g, a = gold.get(record["id"], {}), record["answer"]
            items.append({
                "id": record["id"], "scope": g.get("scope_class"), "topic": g.get("topic"),
                "reference_answer": g.get("reference_answer"), "expected_chunk_ids": g.get("expected_chunk_ids") or [],
                "expected_citations": g.get("expected_citations") or [], "answer": a,
                "texts": {c["chunk_id"]: self.chunks[c["chunk_id"]]["content"] for c in a["citations"]
                          if c["chunk_id"] in self.chunks},
            })
        return {"run": name, "items": items}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GetRight Dev Console</title>
<style>
:root { --bg:#f7f7f5; --panel:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#e2e2dc;
        --accent:#2f5d8a; --warn:#a24a00; --good:#2e7d4f; --bad:#b3261e; --hl:#fff3c4; --info:#eef3f8; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --panel:#1f1f1d; --ink:#ececea; --muted:#9a9a94; --line:#33332f;
          --accent:#8ab4e0; --warn:#f0a35e; --good:#7fcf9c; --bad:#f2948c; --hl:#4a4224; --info:#22303d; } }
* { box-sizing: border-box; }
body { margin:0; font:14px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--ink); }
header { padding:14px 20px 0; border-bottom:1px solid var(--line); background:var(--panel); }
h1 { font-size:18px; margin:0 0 10px; }
nav button { background:none; color:var(--muted); border:none; border-bottom:2px solid transparent;
  padding:8px 12px; font-size:14px; cursor:pointer; border-radius:0; }
nav button.on { color:var(--ink); border-bottom-color:var(--accent); font-weight:600; }
.wrap { max-width:1100px; margin:0 auto; padding:16px 20px; }
form { display:flex; gap:8px; flex-wrap:wrap; }
input[type=text] { flex:1 1 360px; padding:9px 10px; font-size:15px; border:1px solid var(--line);
  border-radius:6px; background:var(--panel); color:var(--ink); }
select, button { padding:8px 10px; font-size:14px; border-radius:6px; border:1px solid var(--line);
  background:var(--panel); color:var(--ink); }
button.go { background:var(--accent); color:#fff; border:none; cursor:pointer; }
.examples { margin-top:8px; color:var(--muted); font-size:13px; }
.examples a { color:var(--accent); cursor:pointer; margin-right:12px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; margin-top:14px; min-width:0; }
.card h2 { font-size:14px; margin:0 0 8px; }
.muted { color:var(--muted); font-size:13px; }
.badge { display:inline-block; font-size:12px; font-weight:600; padding:2px 8px; border-radius:10px; border:1px solid currentColor; }
.answered { color:var(--good); } .abstained { color:var(--accent); } .insufficient_context { color:var(--warn); }
.prose { white-space:pre-wrap; font-size:15px; }
.prose sup a { color:var(--accent); font-weight:600; cursor:pointer; text-decoration:none; }
.notice { background:var(--info); border-radius:6px; padding:10px 12px; white-space:pre-wrap; }
.src { border-top:1px solid var(--line); padding:8px 4px; border-radius:4px; }
.src.hl { background:var(--hl); }
.src .top { display:flex; gap:8px; align-items:baseline; cursor:pointer; }
.num { font-weight:700; color:var(--accent); min-width:24px; }
.cite { font-weight:600; overflow-wrap:anywhere; }
.flag { color:var(--warn); font-size:12px; font-weight:600; }
.text { font-size:13px; margin-top:6px; white-space:pre-wrap; display:none; }
.src.open .text { display:block; }
ul.checks { margin:0; padding-left:18px; }
.bad { color:var(--bad); } .ok { color:var(--good); }
table { border-collapse:collapse; width:100%; font-size:13px; }
td, th { text-align:left; padding:4px 6px; border-top:1px solid var(--line); vertical-align:top; }
.gold { display:grid; grid-template-columns:300px minmax(0,1fr); gap:14px; }
@media (max-width: 800px) { .gold { grid-template-columns:1fr; } .wrap { padding:12px 16px; } }
.list { max-height:75vh; overflow:auto; background:var(--panel); border:1px solid var(--line); border-radius:8px; }
.row { padding:7px 10px; border-top:1px solid var(--line); cursor:pointer; display:flex; gap:8px; align-items:baseline; }
.row:first-child { border-top:none; }
.row.sel { background:var(--hl); }
.row .id { font-weight:600; min-width:84px; }
.filters { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
.disclaimer { color:var(--muted); font-size:12px; margin-top:10px; }
.err { color:var(--bad); }
</style></head><body>
<header>
  <h1>GetRight dev console (M4)</h1>
  <nav><button id="tAsk" class="on">Ask</button><button id="tGold">Gold run</button></nav>
</header>

<div id="ask" class="wrap">
  <form id="f">
    <input id="q" type="text" placeholder="Ask a question about Malaysian employment law, in English" autofocus>
    <select id="region">
      <option value="">Region not given</option>
      <option value="peninsular">Peninsular Malaysia / Labuan</option>
      <option value="sabah">Sabah</option>
      <option value="sarawak">Sarawak</option>
    </select>
    <button class="go">Ask</button>
  </form>
  <div class="examples">Try: <span id="examples"></span></div>
  <div id="out"></div>
</div>

<div id="goldTab" class="wrap" hidden>
  <div class="filters">
    <select id="run"></select>
    <select id="fScope"><option value="">All scopes</option><option>in_scope</option><option>out_of_scope</option><option>external</option></select>
    <select id="fStatus"><option value="">All statuses</option><option>answered</option><option>abstained</option><option>insufficient_context</option></select>
    <span id="goldMeta" class="muted"></span>
  </div>
  <div class="gold"><div id="list" class="list"></div><div id="detail"></div></div>
</div>

<script>
const EXAMPLES = [
  ["How many days of maternity leave do I get?", "sarawak"], ["How many days of annual leave am I entitled to?", "sabah"],
  ["What is the overtime pay rate on a normal working day?", "peninsular"],
  ["How many days of maternity leave do I get?", ""], ["Can my employer fire me while I am pregnant?", "peninsular"],
  ["How do I renew my passport?", ""]];
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag);
  if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const STATUS_TEXT = {answered: "Answered", abstained: "Abstained (gate)", insufficient_context: "Model: not in the sources"};

function prose(text, scope) {
  // Answer text with [n] turned into links to source n. Built as DOM nodes, never innerHTML.
  const p = el("div", "prose");
  text.split(/(\\[\\d+\\])/).forEach(part => {
    const m = part.match(/^\\[(\\d+)\\]$/);
    if (!m) { p.append(part); return; }
    const sup = el("sup"), a = el("a", null, "[" + m[1] + "]");
    a.onclick = () => { const s = scope.querySelector('[data-n="' + m[1] + '"]');
      if (s) { s.classList.add("open", "hl"); s.scrollIntoView({block: "center"}); setTimeout(() => s.classList.remove("hl"), 1500); } };
    sup.append(a); p.append(sup);
  });
  return p;
}

function sources(citations, texts, expected) {
  const box = el("div");
  if (!citations.length) { box.append(el("div", "muted", "No citations.")); return box; }
  citations.forEach(c => {
    const s = el("div", "src"); s.dataset.n = c.number;
    const top = el("div", "top");
    top.append(el("span", "num", "[" + c.number + "]"), el("span", "cite", c.citation));
    if (expected) top.append(el("span", expected.includes(c.chunk_id) ? "ok" : "muted", expected.includes(c.chunk_id) ? "expected" : ""));
    s.append(top);
    const meta = [c.section_title, c.jurisdiction, c.source_page ? "page " + c.source_page : null, c.source_version].filter(Boolean);
    s.append(el("div", "muted", meta.join(" · ")));
    if (c.status !== "in_force") s.append(el("div", "flag", c.status.replaceAll("_", " ").toUpperCase()));
    s.append(el("div", "text", texts[c.chunk_id] || "(text not available)"));
    top.onclick = () => s.classList.toggle("open");
    box.append(s);
  });
  box.append(el("div", "muted", "Click a source to show the full provision text. Citations are copied from chunk metadata, not written by the model."));
  return box;
}

function checks(a) {
  const ul = el("ul", "checks"), k = a.checks;
  const line = (bad, text) => ul.append(el("li", bad ? "bad" : "ok", text));
  line(k.invalid_markers.length, "Invalid markers removed: " + (k.invalid_markers.join(", ") || "none"));
  line(k.provision_mentions.length, "Acts / sections named in the prose (rule 3): " + (k.provision_mentions.join("; ") || "none"));
  line(k.non_current_citations.length, "Cited text that is not current law: " + (k.non_current_citations.join(", ") || "none"));
  line(k.uncited_sentences > 0, "Sentences without a marker: " + k.uncited_sentences);
  line(k.truncated, "Cut off at max tokens: " + (k.truncated ? "yes" : "no"));
  return ul;
}

function answerView(a, texts, expected) {
  const frag = el("div");
  const head = el("div"); head.append(el("span", "badge " + a.status, STATUS_TEXT[a.status] || a.status));
  if (a.generator) head.append(el("span", "muted", "  " + a.generator.model + " · prompt " + a.generator.prompt_version +
    " · " + a.generator.prompt_tokens + " + " + a.generator.completion_tokens + " tokens"));
  frag.append(head);
  const scope = el("div");
  if (a.status === "answered") frag.append(prose(a.answer, scope));
  if (a.status === "abstained") frag.append(el("div", "notice", a.abstention.message));
  if (a.status === "insufficient_context") frag.append(el("div", "notice",
    "The model found no answer in the retrieved provisions (it replied INSUFFICIENT_CONTEXT)."));
  if (a.notes.length) { const n = el("div", "card"); n.append(el("h2", null, "Notes"));
    a.notes.forEach(t => n.append(el("div", "muted", "• " + t))); frag.append(n); }
  if (a.external_dependencies.length) frag.append(el("div", "muted",
    "Depends on statutes GetRight does not hold: " + a.external_dependencies.join("; ")));
  const src = el("div", "card"); src.append(el("h2", null, "Sources"), sources(a.citations, texts, expected));
  scope.append(src); frag.append(scope);
  if (a.status === "answered") { const c = el("div", "card"); c.append(el("h2", null, "Traceability checks"), checks(a)); frag.append(c); }
  frag.append(el("div", "disclaimer", a.disclaimer));
  return frag;
}

async function ask(ev) {
  if (ev) ev.preventDefault();
  const q = $("q").value.trim(); if (!q) return;
  $("out").replaceChildren(el("div", "card muted", "Retrieving, then asking the model on the HPC..."));
  const res = await fetch("/api/ask?" + new URLSearchParams({q, region: $("region").value}));
  const d = await res.json();
  if (d.error) { $("out").replaceChildren(el("div", "card err", d.error)); return; }
  const g = d.gate, t = d.timings_ms;
  const meta = el("div", "muted", "Gate score " + (g.score == null ? "–" : g.score.toFixed(4)) + " vs threshold " + g.threshold +
    (g.abstained ? " → abstained (" + g.reason + ")" : " → passed") + " · retrieval " + t.retrieval + " ms · generation " + t.generation + " ms");
  const ans = el("div", "card"); ans.append(answerView(d.answer, d.texts));
  const ctx = el("details", "card"); ctx.append(el("summary", null, "What the model was shown (" + d.context.length + " chunks)"));
  const tbl = el("table"); tbl.append(Object.assign(el("tr"), {innerHTML: "<th>#</th><th>Citation</th><th>How it got in</th><th>Status</th><th>Score</th>"}));
  d.context.forEach((c, i) => { const tr = el("tr");
    [String(i + 1), c.citation, c.added_because + (c.linked_from ? " " + c.linked_from : "") + (c.rank ? " (rank " + c.rank + ")" : ""),
     c.status, c.score == null ? "" : c.score.toFixed(4)].forEach(v => tr.append(el("td", null, v))); tbl.append(tr); });
  ctx.append(tbl);
  $("out").replaceChildren(meta, ans, ctx);
}

let GOLD = null, SEL = null;
async function loadRuns() {
  const runs = await (await fetch("/api/runs")).json();
  $("run").replaceChildren(...runs.map(r => el("option", null, r)));
  await loadGold();
}
async function loadGold() {
  GOLD = await (await fetch("/api/gold?" + new URLSearchParams({run: $("run").value}))).json();
  if (GOLD.error) { $("list").replaceChildren(el("div", "err", GOLD.error)); return; }
  renderList();
}
function renderList() {
  const sc = $("fScope").value, st = $("fStatus").value;
  const items = GOLD.items.filter(i => (!sc || i.scope === sc) && (!st || i.answer.status === st));
  const counts = {}; GOLD.items.forEach(i => counts[i.answer.status] = (counts[i.answer.status] || 0) + 1);
  $("goldMeta").textContent = GOLD.items.length + " items · " + Object.entries(counts).map(([k, v]) => k + " " + v).join(" · ");
  $("list").replaceChildren(...items.map(i => { const r = el("div", "row" + (i.id === SEL ? " sel" : ""));
    r.append(el("span", "id", i.id), el("span", "badge " + i.answer.status, i.answer.status.replace("_context", "")), el("span", "muted", i.scope));
    r.onclick = () => { SEL = i.id; renderList(); detail(i); }; return r; }));
}
function detail(i) {
  const d = $("detail"), q = el("div", "card");
  q.append(el("h2", null, i.id + " · " + (i.topic || "") + " · " + i.scope + " · region " + (i.answer.region || "not given")));
  q.append(el("div", "prose", i.answer.query));
  const ref = el("div", "card"); ref.append(el("h2", null, "Gold reference answer"), el("div", null, i.reference_answer || "–"));
  if (i.expected_citations.length) ref.append(el("div", "muted", "Expected: " + i.expected_citations.join("; ")));
  const a = el("div", "card"); a.append(el("h2", null, "System answer"), answerView(i.answer, i.texts, i.expected_chunk_ids));
  d.replaceChildren(q, ref, a); window.scrollTo({top: 0});
}

for (const [q, r] of EXAMPLES) { const a = el("a", null, q + (r ? " [" + r + "]" : ""));
  a.onclick = () => { $("q").value = q; $("region").value = r; ask(); }; $("examples").append(a); }
$("f").onsubmit = ask;
$("run").onchange = loadGold; $("fScope").onchange = renderList; $("fStatus").onchange = renderList;
function tab(gold) { $("ask").hidden = gold; $("goldTab").hidden = !gold;
  $("tAsk").classList.toggle("on", !gold); $("tGold").classList.toggle("on", gold); if (gold && !GOLD) loadRuns(); }
$("tAsk").onclick = () => tab(false); $("tGold").onclick = () => tab(true);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    engine: Engine

    def _send(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, body) -> None:
        self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/api/ask":
            query, region = params.get("q", "").strip(), params.get("region") or None
            if not query or (region and region not in self.engine.config["retrieval"]["regions"]):
                self._json({"error": "Enter a question (and a valid region)."})
            else:
                self._json(self.engine.ask(query, region))
        elif url.path == "/api/runs":
            self._json(self.engine.runs())
        elif url.path == "/api/gold":
            self._json(self.engine.gold_run(params.get("run", "")))
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
