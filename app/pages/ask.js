import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Cited, Err, html, Icon, Skel, Steps, Story, Toast, Viewer, hhmmss } from "../lib/ui.js";
import { SiteMap } from "./memory.js";

// Alerts waiting for a person, shown on the home page: one click opens the answer.
function Inbox({ onOpen }) {
  const [items, setItems] = useState(null);
  useEffect(() => { api.alerts().then((xs) => setItems(xs.slice(0, 4))).catch(() => setItems([])); }, []);
  if (!items?.length) return null;
  return html`<section class="inbox fadein">
    <div class="section-t">Needs review <span class="dim">· ${items.length}</span></div>
    <div class="inbox-row">${items.map((e) => html`<button class="alert" onClick=${() => onOpen(e)}>
      ${e.img ? html`<img src=${e.img} alt="" loading="lazy" />` : html`<div class="alert-noimg"></div>`}
      <div class="alert-b"><b>${e.title}</b><span><i class=${`pdot ${e.priority}`}></i>${hhmmss(e.ts_start)} · ${e.place || e.site}</span></div>
    </button>`)}</div>
  </section>`;
}

// Where an object went, on the site map (folded into the answer for object questions).
function ObjectMap({ ws, id }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    Promise.all([api.coverage(ws), api.zones(ws), api.history(id)]).then(([cov, zones, h]) => setD({ cov, zones, h })).catch(() => setD(null));
  }, [ws, id]);
  if (!d) return null;
  return html`<section class="omap"><div class="section-t">Where it went</div>
    <${SiteMap} zones=${d.zones} sources=${d.cov.sources.filter((s) => s.map_x != null)} topology=${d.cov.topology}
      path=${d.h.entries.filter((e) => e.source_id && e.status !== "RECORDED")} gaps=${d.h.gaps} /></section>`;
}


// The three demo workspaces and the question that shows each best.
const SCENES = [
  { ws: "construction", name: "Construction site", q: "What safety alerts happened today?" },
  { ws: "campus", name: "Campus", q: "What happened to my bicycle?" },
  { ws: "metro", name: "Metro", q: "What happened before the emergency alert?" },
];
const clip = (t, n = 64) => (t.length > n ? t.slice(0, n - 1).replace(/\s+\S*$/, "") + "…" : t);

// Showcase: a real answer from this workspace's memory, told as a strip of moments.
// Solid = observed on camera, dashed = inferred between cameras, hatched gap = no coverage.
function Showcase({ go }) {
  const scene = SCENES[0];
  const [ans, setAns] = useState(null);
  const [i, setI] = useState(0);
  const [auto, setAuto] = useState(true);
  useEffect(() => { api.ask(scene.ws, scene.q).then(setAns).catch(() => setAns(null)); }, []);
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
      <span class="show-site"><span class="live"></span>${scene.name}</span>
      <button class="link" onClick=${() => go("ask", null, { q: scene.q })}>“${scene.q}” <${Icon} name="arrow" size=${14} /></button>
    </div>
    <div class="show-frame" role="button" tabindex="0" onClick=${() => go("ask", null, { q: scene.q })}>
      ${frame ? html`<img key=${frame} class="fadein-fast" src=${frame} alt=${cite?.caption || "evidence frame"} />` : html`<div class="skel" style="position:absolute;inset:0"></div>`}
      ${cur?.status === "UNKNOWN" ? html`<div class="show-unknown"><span>No camera covers what happened next.</span></div>` : null}
      ${cur ? html`<div class="show-cap"><span class=${`tag-s ${cur.status}`}>${STATE[cur.status] || cur.status}</span>
        <span class="mono">${(cur.ts || "").slice(11, 19)}</span><span class="show-place">${cur.title}</span></div>` : null}
      <span class="demo-corner">Demo · public footage</span>
    </div>
    <ol class="strip" style=${`--n:${Math.max(moments.length, 1)}`}>
      ${moments.map((m, k) => html`<li class=${`mo ${m.status} ${k === i ? "on" : ""} ${k < i ? "past" : ""}`}>
        <button onClick=${() => { setAuto(false); setI(k); }} aria-label=${m.title}>
          <span class="mo-line"></span><span class="mo-dot"></span>
          <span class="mo-t mono">${m.ts ? m.ts.slice(11, 19) : ""}</span>
          <span class="mo-d">${m.place || STATE[m.status]}</span>
        </button></li>`)}
    </ol>
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
  const [toast, setToast] = useState(null);
  const [reviewed, setReviewed] = useState(null);
  const input = useRef();

  const run = async (question, eventId = null) => {
    const text = (question ?? q).trim();
    if (!text) return;
    setQ(text); setBusy(true); setErr(null); setReviewed(null);
    try {
      const r = await api.askAny(text, eventId);
      // default to the evidence that answers the question (first citation in the conclusion)
      const m = (r.headline || "").match(/\[E(\d+)\]/);
      const visual = r.citations.find((c) => c.url || c.proxy_url || c.clip_url);
      setRes(r); setActive(m ? +m[1] : visual?.n ?? r.citations[0]?.n ?? null);
    } catch (e) { setErr(e); setRes(null); }
    setBusy(false);
  };
  const openEvent = (e) => run(`Why was the ${hhmmss(e.ts_start).slice(0, 5)} alert flagged?`, e.id);
  useEffect(() => {
    const ev = route.q.get("event") || (route.page === "investigate" ? route.arg : null);
    if (ev) api.timeline(ev, 60).then((t) => openEvent(t.event)).catch(() => {});
    else if (route.q.get("q")) run(route.q.get("q"));
    else if (route.page === "memory") run("What happened to my bicycle?");
  }, []);
  const review = async (d) => {
    try { await api.review(res.subject.id, d, ""); setReviewed(d); setToast("Saved to the audit log"); } catch (e) { setToast(String(e.message)); }
  };
  const [examples, setExamples] = useState([]);
  const [bySite, setBySite] = useState({});
  useEffect(() => { api.suggestions().then((x) => { setExamples(x.examples); setBySite(x.by_site); }).catch(() => {}); }, []);
  useEffect(() => { setSugs(res ? bySite[res.workspace?.id] || examples : examples); }, [res, bySite, examples]);
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
          <h1 class="display">The world<br/>leaves a trace.</h1>
          <p class="lede">Ask what happened. See the footage that answers it.</p>
          ${box(true)}
          <div class="chips">${examples.map((s) => html`<button class="chip-q" onClick=${() => run(s)}>${s}</button>`)}</div>
          <${Err} error=${err} />
        </div>
        <div class="h-right"><${Showcase} go=${go} /></div>
      </section>
      <${Inbox} onOpen=${openEvent} />
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
        ${res.workspace ? html`<div class="where"><span class="live"></span>${res.workspace.name}</div>` : null}
        ${res.headline ? html`<p class="headline"><${Cited} text=${res.headline} citations=${res.citations} active=${active} onCite=${setActive} /></p>` : null}
        ${res.subject?.type === "event" ? html`<div class="verdict">
          ${reviewed ? html`<span class="note">Marked as ${reviewed === "confirmed" ? "a real incident" : reviewed === "rejected" ? "a false alarm" : "not sure"}.</span>`
            : html`<span class="label">Is this a real incident?</span>
              <button class="btn sm gold" onClick=${() => review("confirmed")}>Yes</button>
              <button class="btn sm" onClick=${() => review("rejected")}>False alarm</button>
              <button class="btn sm ghost" onClick=${() => review("uncertain")}>Not sure</button>`}</div>` : null}
      </div>
      <div class="a-steps">
        <div class="section-t">Timeline</div>
        ${res.steps?.length ? html`<${Steps} steps=${res.steps} active=${active} onPick=${setActive} onOpen=${(id, ts) => openEvent({ id, ts_start: ts })} />`
          : html`<${Story} sentences=${res.sentences} citations=${res.citations} active=${active} onPick=${setActive} gaps=${res.gaps} />`}
        ${res.subject?.type === "object" ? html`<${ObjectMap} ws=${res.workspace.id} id=${res.subject.id} />` : null}
        ${sugs.filter((x) => x !== res.question).length ? html`<div class="follow"><span class="label">Ask next</span>
          <div class="row wrap" style="gap:8px">${sugs.filter((x) => x !== res.question).slice(0, 3).map((x) => html`<button class="chip-q" onClick=${() => run(x)}>${x}</button>`)}</div></div>` : null}
      </div>
      <aside class="answer-side"><${Viewer} c=${cite} list=${res.citations} onNav=${setActive} empty="This answer has no visual evidence." /></aside>
    </div>`}
    <${Toast} msg=${toast} onDone=${() => setToast(null)} />
  </div>`;
}
