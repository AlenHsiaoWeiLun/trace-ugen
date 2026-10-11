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

// The three demo sites, each with the question that shows it best and real processed footage as cover.
const SCENES = [
  { ws: "campus", name: "Campus", title: "A bicycle disappears from the rack", q: "What happened to my bicycle?", meta: "4 cameras",
    video: "/media/vestige/campus/CAM-P3/proxy.mp4" },
  { ws: "metro", name: "Metro", title: "An emergency alarm on the platform", q: "What happened before the emergency alert?", meta: "Cameras · alarm · radio",
    video: "/media/vestige/metro/INC-M-0001.mp4" },
  { ws: "construction", name: "Construction", title: "A worker steps into a truck's path", q: "Why was this construction safety event flagged?", meta: "2 cameras",
    video: "/media/vestige/construction/CAM-S1/proxy.mp4" },
];

function Scene({ s, current, go }) {
  const ref = useRef();
  return html`<button class=${`scene ${current ? "cur" : ""}`} onClick=${() => go("ask", null, { ws: s.ws, q: s.q })}
      onMouseEnter=${() => ref.current?.play().catch(() => {})} onMouseLeave=${() => ref.current?.pause()}>
    <video ref=${ref} src=${`${s.video}#t=2`} muted loop playsinline preload="metadata"></video>
    ${current ? html`<span class="scene-cur">Current site</span>` : null}
    <div class="scene-b">
      <span class="scene-n">${s.name} demo · ${s.meta}</span>
      <span class="scene-t">${s.title}</span>
      <span class="scene-go">Explore ${s.name} demo <${Icon} name="arrow" size=${14} /></span>
    </div>
  </button>`;
}

export function AskPage({ ws, go, route }) {
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
    <input ref=${input} value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="Ask about an object, a place or an event…"
      aria-label="Ask VESTIGE" autocomplete="off" />
    <button class="go" disabled=${busy || !q.trim()} aria-label="Ask">${busy ? html`<span class="spin"></span>` : html`<${Icon} name="arrow" size=${18} />`}</button>
  </form>`;

  // ---------- home ----------
  if (!res && !busy) {
    return html`<div class="home fadein">
      <section class="hero">
        <div class="eyebrow"><span class="live"></span>Edge AI memory for the physical world</div>
        <h1 class="display">What happened here?</h1>
        <p class="lede">Ask about your physical world. Get answers backed by footage.</p>
        ${box(true)}
        <div class="chips"><span class="chips-l">Try on ${SCENES.find((x) => x.ws === ws)?.name || ws}:</span>${sugs.map((s) => html`<button class="chip-q" onClick=${() => run(s)}>${s}</button>`)}</div>
        <${Err} error=${err} />
      </section>
      <section class="scenes">${SCENES.map((s) => html`<${Scene} s=${s} current=${s.ws === ws} go=${go} />`)}</section>
      <section class="proof">
        <div><${Icon} name="spark" size=${18} /><b>Remembers</b><span>Detections become a persistent memory of objects and events, with provenance on every row.</span></div>
        <div><${Icon} name="ask" size=${18} /><b>Investigates</b><span>Answers are composed from memory lookups only and cite the frame behind each sighting.</span></div>
        <div><${Icon} name="flask" size=${18} /><b>Verifies itself</b><span>IncidentLab stress-tests the detector and measures which fixes recover what it misses.</span></div>
      </section>
      <p class="foot">Demo sites use public stock footage and staged inputs, labelled as such. No face recognition — heads are blurred in everything stored.</p>
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
