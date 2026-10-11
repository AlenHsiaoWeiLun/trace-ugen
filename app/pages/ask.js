import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Cited, Err, html, Icon, Skel, Steps, Story, Viewer } from "../lib/ui.js";

function evidenceSummary(cs) {
  const direct = cs.filter((c) => c.status === "OBSERVED" || c.status === "LAST_SEEN").length;
  const inf = cs.filter((c) => c.status === "INFERRED").length;
  const other = cs.length - direct - inf;
  return [`${cs.length} piece${cs.length === 1 ? "" : "s"} of evidence`, direct && `${direct} direct observation${direct === 1 ? "" : "s"}`,
    inf && `${inf} inferred`, other && `${other} records`].filter(Boolean).join(" · ");
}

// The three demo workspaces and the question that shows each best.
const SCENES = [
  { ws: "campus", name: "Campus", q: "What happened to my bicycle?" },
  { ws: "metro", name: "Metro", q: "What happened before the emergency alert?" },
  { ws: "construction", name: "Construction", q: "Why was this construction safety event flagged?" },
];
const clip = (t, n = 64) => (t.length > n ? t.slice(0, n - 1).replace(/\s+\S*$/, "") + "…" : t);

// Showcase: a real answer from this workspace's memory, told as a strip of moments.
// Solid = observed on camera, dashed = inferred between cameras, hatched gap = no coverage.
function Showcase({ ws, setWs, go }) {
  const scene = SCENES.find((x) => x.ws === ws) || SCENES[0];
  const [ans, setAns] = useState(null);
  const [i, setI] = useState(0);
  const [auto, setAuto] = useState(true);
  useEffect(() => { api.ask(scene.ws, scene.q).then(setAns).catch(() => setAns(null)); }, [scene.ws]);
  const moments = (ans?.steps || []).filter((st) => st.n != null || st.status === "UNKNOWN")
    .sort((a, b) => (a.ts && b.ts ? a.ts.localeCompare(b.ts) : 0))
    .filter((st, k, arr) => k === 0 || st.n == null || st.n !== arr[k - 1].n).slice(0, 5);
  useEffect(() => {
    if (!auto || moments.length < 2) return;
    const t = setInterval(() => setI((x) => (x + 1) % moments.length), 3200);
    return () => clearInterval(t);
  }, [auto, moments.length]);
  const cur = moments[Math.min(i, moments.length - 1)];
  const cite = cur?.n != null ? ans.citations.find((c) => c.n === cur.n) : null;
  const lastFrame = useRef(null);
  if (cite?.url) lastFrame.current = cite.url;
  const frame = cite?.url || lastFrame.current;
  return html`<div class="show">
    <div class="show-top">
      <div class="seg" role="tablist" aria-label="Demo workspace">${SCENES.map((x) => html`<button role="tab" aria-selected=${x.ws === ws}
        class=${x.ws === ws ? "on" : ""} onClick=${() => setWs(x.ws)}>${x.name}</button>`)}</div>
      <span class="demo-tag">Demo · public footage</span>
    </div>
    <div class="show-frame">
      ${frame ? html`<img key=${frame} class="fadein-fast" src=${frame} alt=${cite?.caption || "evidence frame"} />` : html`<div class="skel" style="position:absolute;inset:0"></div>`}
      ${cur?.status === "UNKNOWN" ? html`<div class="show-unknown"><span>No camera covers what happened next.</span></div>` : null}
      ${cur ? html`<div class="show-cap"><span class=${`tag-s ${cur.status}`}>${STATE[cur.status] || cur.status}</span>
        <span class="mono">${(cur.ts || "").slice(11, 19)}</span><span class="show-place">${cur.place || cite?.source?.split(" · ")[0] || ""}</span></div>` : null}
    </div>
    <ol class="strip" style=${`--n:${Math.max(moments.length, 1)}`}>
      ${moments.map((m, k) => html`<li class=${`mo ${m.status} ${k === i ? "on" : ""} ${k < i ? "past" : ""}`}>
        <button onClick=${() => { setAuto(false); setI(k); }} aria-label=${m.title}>
          <span class="mo-line"></span><span class="mo-dot"></span>
          <span class="mo-t mono">${m.ts ? m.ts.slice(11, 19) : ""}</span>
          <span class="mo-d">${clip(m.title, 52)}</span>
        </button></li>`)}
    </ol>
    <div class="show-foot"><span>${ans ? clip(ans.question, 60) : ""}</span>
      <button class="link" onClick=${() => go("ask", null, { ws: scene.ws, q: scene.q })}>Open the full investigation <${Icon} name="arrow" size=${14} /></button></div>
  </div>`;
}
const STATE = { RECORDED: "Recorded", OBSERVED: "Observed", LAST_SEEN: "Last seen", INFERRED: "Inferred", UNKNOWN: "Unknown" };

export function AskPage({ ws, setWs, go, route }) {
  const [q, setQ] = useState(route.q.get("q") || "");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [active, setActive] = useState(null);
  const [sugs, setSugs] = useState([]);
  const input = useRef();

  const run = async (question) => {
    const text = (question ?? q).trim();
    if (!text) return;
    setQ(text); setBusy(true); setErr(null);
    try {
      const r = await api.ask(ws, text);
      // default to the evidence that answers the question (first citation in the conclusion)
      const m = (r.headline || "").match(/\[E(\d+)\]/);
      setRes(r); setActive(m ? +m[1] : r.citations[0]?.n ?? null);
    } catch (e) { setErr(e); setRes(null); }
    setBusy(false);
  };
  useEffect(() => { if (route.q.get("q")) run(route.q.get("q")); }, []);
  useEffect(() => { api.overview(ws).then((o) => setSugs(o.suggestions || [])).catch(() => {}); }, [ws]);
  useEffect(() => {
    const k = (e) => { if (e.key === "/" && document.activeElement !== input.current) { e.preventDefault(); input.current?.focus(); } };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, []);

  const box = (big) => html`<form class=${`ask ${big ? "big" : ""}`} onSubmit=${(e) => { e.preventDefault(); run(); }}>
    <${Icon} name="ask" size=${big ? 20 : 17} />
    <input ref=${input} value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="Ask what happened…"
      aria-label="Ask VESTIGE" autocomplete="off" />
    <button class="go" disabled=${busy || !q.trim()} aria-label="Ask">${busy ? html`<span class="spin"></span>` : html`<${Icon} name="arrow" size=${18} />`}</button>
  </form>`;

  // ---------- home ----------
  if (!res && !busy) {
    return html`<div class="home fadein">
      <section class="hero2">
        <div class="h-left">
          <div class="eyebrow"><span class="live"></span>Edge AI for the physical world</div>
          <h1 class="display">The world<br/>leaves a trace.</h1>
          <p class="lede">Ask what happened to an object, a place or an event. VESTIGE answers from your cameras — and shows you the footage.</p>
          ${box(true)}
          <div class="chips">${sugs.slice(0, 2).map((s) => html`<button class="chip-q" onClick=${() => run(s)}>${s}</button>`)}</div>
          <${Err} error=${err} />
        </div>
        <div class="h-right"><${Showcase} ws=${ws} setWs=${setWs} go=${go} /></div>
      </section>
      <section class="proof">
        <div><${Icon} name="spark" size=${18} /><b>Remembers</b><span>Objects and events, kept as a timeline you can search — what was seen, where and when.</span></div>
        <div><${Icon} name="ask" size=${18} /><b>Shows its evidence</b><span>Every answer comes with the footage behind it, and says plainly what is certain, inferred or unknown.</span></div>
        <div><${Icon} name="flask" size=${18} /><b>Tests its limits</b><span>Measures how detection holds up in low light, blur and occlusion — and which fixes help.</span></div>
      </section>
      <p class="foot">Demo workspaces use public stock footage and staged inputs, labelled as such. No face recognition; heads are blurred in everything stored.</p>
    </div>`;
  }

  // ---------- answer ----------
  const cite = res?.citations.find((c) => c.n === active);
  return html`<div class="answer-page">
    <div class="qbar">${box(false)}</div>
    <${Err} error=${err} />
    ${busy ? html`<div class="answer-grid"><div class="stack"><${Skel} h=${44} w="70%" /><${Skel} h=${90} /><${Skel} h=${90} /><${Skel} h=${90} /></div><${Skel} h=${360} /></div>` : html`
    <div class="answer-grid fadein">
      <div class="a-head">
        <h1 class="answer-q">${res.question}</h1>
        ${res.headline ? html`<p class="headline"><${Cited} text=${res.headline} citations=${res.citations} active=${active} onCite=${setActive} /></p>` : null}
        <div class="answer-meta">${evidenceSummary(res.citations)}</div>
      </div>
      <div class="a-steps">
        <div class="section-t">How it unfolded</div>
        ${res.steps?.length ? html`<${Steps} steps=${res.steps} active=${active} onPick=${setActive} />`
          : html`<${Story} sentences=${res.sentences} citations=${res.citations} active=${active} onPick=${setActive} gaps=${res.gaps} />`}
        <div class="row wrap actions">
          ${res.subject?.type === "object" ? html`<button class="btn" onClick=${() => go("memory", res.subject.id)}><${Icon} name="map" size=${15} /> See it on the map</button>` : null}
          ${res.subject?.type === "event" ? html`<button class="btn" onClick=${() => go("investigate", res.subject.id)}>Open the event <${Icon} name="arrow" size=${15} /></button>
            <button class="btn ghost" onClick=${() => go("lab", null, { event: res.subject.id, ws })}><${Icon} name="flask" size=${15} /> Stress-test it</button>` : null}
        </div>
        <details class="how"><summary>How this answer was built</summary>
          <p>${res.tool_calls.length} memory lookups · ${res.latency_ms} ms on this machine</p>
          <ol>${res.tool_calls.map((t) => html`<li><span class="mono">${t.tool}</span><span>${t.results} rows · ${t.ms} ms</span></li>`)}</ol>
          <p>Planner: ${res.planner}. Facts come only from these lookups; the planner picks tools and never writes times or places. Inferred links are adjacency + travel time + colour similarity, not identity.</p>
        </details>
      </div>
      <aside class="answer-side"><${Viewer} c=${cite} list=${res.citations} onNav=${setActive} empty="This answer has no visual evidence." /></aside>
    </div>`}
  </div>`;
}
