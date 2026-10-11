// Shared primitives. The evidence grammar (status chips, nodes, markers) lives here so every page
// says "observed / inferred / unknown" the same way.
import { h } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import htm from "htm";

export const html = htm.bind(h);

export const hhmmss = (ts) => (ts ? ts.slice(11, 19) : "—");
export const day = (ts) => (ts ? new Date(ts).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
export const STATUS_LABEL = { RECORDED: "Recorded", OBSERVED: "Observed", LAST_SEEN: "Last seen", INFERRED: "Inferred",
  UNKNOWN: "Unknown", REJECTED: "Not linked" };

const ICONS = {
  ask: "M11 19a8 8 0 1 1 5.3-14 8 8 0 0 1-5.3 14zm10 2-4.3-4.3",
  memory: "M4 6h16M4 12h16M4 18h10",
  invest: "M3 5h18v14H3zM3 10h18M8 5v14",
  lab: "M9 3h6M10 3v6L5 19a1.5 1.5 0 0 0 1.3 2h11.4A1.5 1.5 0 0 0 19 19l-5-10V3",
  sources: "M4 7h11v10H4zM15 10l5-3v10l-5-3",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  arrow: "M5 12h14M13 6l6 6-6 6",
  play: "M7 5l12 7-12 7z",
  check: "M5 13l4 4L19 7",
  x: "M6 6l12 12M18 6 6 18",
  q: "M12 18h.01M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3",
  flask: "M9 3h6M10 3v6L5 19a1.5 1.5 0 0 0 1.3 2h11.4A1.5 1.5 0 0 0 19 19l-5-10V3",
  upload: "M12 16V4M6 10l6-6 6 6M4 20h16",
  download: "M12 4v12M6 10l6 6 6-6M4 20h16",
  chev: "M6 9l6 6 6-6",
  chevl: "M15 6l-6 6 6 6",
  chevr: "M9 6l6 6-6 6",
  dots: "M5 12h.01M12 12h.01M19 12h.01",
  plus: "M12 5v14M5 12h14",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z",
  gapi: "M4 12h3M10 12h4M17 12h3",
};
export const Icon = ({ name, size = 17 }) => html`<svg viewBox="0 0 24 24" width=${size} height=${size}
  style="stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round"><path d=${ICONS[name]} /></svg>`;

export const Status = ({ s }) => html`<span class=${`chip st-${s}`}><i></i>${STATUS_LABEL[s] || s}</span>`;
export const Prov = ({ p }) => p ? html`<span class=${`prov ${p === "staged" ? "staged" : ""}`} title="provenance">${p}</span>` : null;

export function Skel({ h = 16, w = "100%", style = "" }) {
  return html`<div class="skel" style=${`height:${h}px;width:${w};${style}`}></div>`;
}

export function Empty({ title, children }) {
  return html`<div class="empty"><div class="serif">${title}</div><div>${children}</div></div>`;
}

export function Err({ error }) {
  return error ? html`<div class="err">${String(error.message || error)}</div>` : null;
}

export function useAsync(fn, deps) {
  const [st, set] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    let live = true;
    set((s) => ({ ...s, loading: true, error: null }));
    fn().then((data) => live && set({ loading: false, data, error: null }))
      .catch((error) => live && set({ loading: false, data: null, error }));
    return () => { live = false; };
  }, deps);
  return st;
}

export function EvidenceCard({ c, on, onClick }) {
  const inferred = c.status === "INFERRED";
  return html`<div class=${`ev fadein ${on ? "on" : ""} ${inferred ? "inferred" : ""}`} onClick=${onClick}
      role="button" tabindex="0" onKeyDown=${(e) => e.key === "Enter" && onClick && onClick()}>
    <span class="n cite ${inferred ? "inferred" : ""}">E${c.n}</span>
    ${c.url ? html`<img src=${c.url} alt=${c.caption || c.label} loading="lazy" />`
            : html`<div class="txt">${c.caption || c.label}</div>`}
    <div class="meta"><${Status} s=${c.status} /><span class="mono dim">${hhmmss(c.ts)}</span>
      <span class="sp"></span><span class="dim" style="font-size:11.5px">${(c.source || c.source_id || "").split(" · ")[0]}</span></div>
  </div>`;
}

// Sentence with [E#] tokens → clickable citations.
export function Cited({ text, citations, active, onCite }) {
  const parts = text.split(/(\[E\d+\])/g);
  return parts.map((p) => {
    const m = p.match(/^\[E(\d+)\]$/);
    if (!m) return p;
    const n = +m[1];
    const c = citations.find((x) => x.n === n);
    return html`<button class=${`cite ${c && c.status === "INFERRED" ? "inferred" : ""} ${active === n ? "on" : ""}`}
      onClick=${() => onCite && onCite(n)} title=${c ? `${c.status} · ${c.label}` : ""}>E${n}</button>`;
  });
}

export function VTimeline({ items, gaps = [], active, onPick }) {
  return html`<div class="vt">
    ${items.map((e, i) => html`<div class=${`it ${active === i ? "hi" : ""}`} key=${i} onClick=${() => onPick && onPick(e, i)} style="cursor:pointer">
      <div class=${`node ${e.status}`}></div>
      <div class="t">${hhmmss(e.ts)}</div>
      <div class="d"><div class="row wrap" style="gap:8px;margin-bottom:3px"><${Status} s=${e.status} />
        <b>${(e.source || "").split(" · ")[0]}</b>${e.provenance === "staged" ? html`<${Prov} p="staged" />` : null}</div>
        ${e.detail}${e.via ? html`<div class="dim" style="font-size:12px;margin-top:3px">via ${e.via.topology} · ${Math.round(e.via.travel_s)} s · colour similarity ${e.via.colour_similarity}</div>` : null}</div>
    </div>`)}
    ${gaps.map((g) => html`<div class="it"><div class="node UNKNOWN"></div><div class="t">${hhmmss(g.ts_start)} →</div>
      <div class="d"><div class="row" style="margin-bottom:3px"><${Status} s="UNKNOWN" /></div><span class="dim">${g.reason}</span></div></div>`)}
  </div>`;
}

export function Toast({ msg, onDone }) {
  useEffect(() => { if (msg) { const t = setTimeout(onDone, 3200); return () => clearTimeout(t); } }, [msg]);
  return msg ? html`<div class="toast">${msg}</div>` : null;
}

export function Compare({ a, b, labelA = "Original", labelB = "Perturbed" }) {
  const ref = useRef();
  const [x, setX] = useState(50);
  const move = (e) => {
    const r = ref.current.getBoundingClientRect();
    const cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
    setX(Math.max(0, Math.min(100, (cx / r.width) * 100)));
  };
  return html`<div class="cmp" ref=${ref} style=${`--x:${x}%`} onMouseMove=${(e) => e.buttons && move(e)} onClick=${move}
      onTouchMove=${move} role="slider" aria-label="Compare original and perturbed" aria-valuenow=${Math.round(x)} tabindex="0"
      onKeyDown=${(e) => { if (e.key === "ArrowLeft") setX(Math.max(0, x - 5)); if (e.key === "ArrowRight") setX(Math.min(100, x + 5)); }}>
    <img src=${a} alt=${labelA} /><img class="top" src=${b} alt=${labelB} />
    <div class="handle"></div>
    <span class="tag glass" style="left:12px">${labelA}</span>
    <span class="tag glass gold-t" style="right:12px">${labelB}</span>
  </div>`;
}

// Multi-camera lanes: sources as rows, observations as markers, gaps hatched, event window banded.
export function Lanes({ sources, observations, gaps = [], window, active, onPick, playhead }) {
  const t = (s) => new Date(s).getTime();
  const pts = observations.map((o) => t(o.ts));
  let t0 = Math.min(...pts, window ? t(window[0]) : Infinity);
  let t1 = Math.max(...pts, window ? t(window[1]) : -Infinity);
  if (!isFinite(t0)) return html`<${Empty} title="No observations">Nothing recorded in this window.</${Empty}>`;
  const pad = Math.max(4000, (t1 - t0) * 0.08);
  t0 -= pad; t1 += pad;
  const X = (ms) => `${((ms - t0) / (t1 - t0)) * 100}%`;
  const ticks = Array.from({ length: 6 }, (_, i) => t0 + ((t1 - t0) * i) / 5);
  const rowsIds = [...new Set(observations.map((o) => o.source_id))];
  const lanes = sources.filter((s) => rowsIds.includes(s.id)).concat(
    rowsIds.filter((id) => !sources.find((s) => s.id === id)).map((id) => ({ id, name: id })));
  const lane = "var(--lane-label)";
  return html`<div class="lanes">
    ${window ? html`<div class="band" style=${`left:calc(${lane} + (100% - ${lane}) * ${(t(window[0]) - t0) / (t1 - t0)});width:calc((100% - ${lane}) * ${(t(window[1]) - t(window[0]) || 1000) / (t1 - t0)})`}></div>` : null}
    ${lanes.map((s) => html`<div class="lane" key=${s.id}>
      <div class="ln">${(s.name || s.id).split(" · ")[0]}<span>${(s.name || "").split(" · ")[1] || s.kind || ""}</span></div>
      <div class="tr">
        ${s.start_ts && s.end_ts ? html`<div class="cov" style=${`left:${X(t(s.start_ts))};width:calc(${X(t(s.end_ts))} - ${X(t(s.start_ts))})`}></div>` : null}
        ${gaps.filter((g) => g.source_id === s.id).map((g) => html`<div class="gapbar" title=${g.reason}
          style=${`left:${X(Math.max(t0, t(g.ts_start)))};width:calc(${X(Math.min(t1, g.ts_end ? t(g.ts_end) : t1))} - ${X(Math.max(t0, t(g.ts_start)))})`}></div>`)}
        ${observations.filter((o) => o.source_id === s.id).map((o) => html`<div class=${`mk ${o.status} ${active === o.id ? "on" : ""}`}
          style=${`left:${X(t(o.ts))}`} title=${`${hhmmss(o.ts)} · ${o.detail}`} onClick=${() => onPick && onPick(o)}></div>`)}
      </div></div>`)}
    ${playhead ? html`<div class="playhead" style=${`left:calc(${lane} + (100% - ${lane}) * ${(t(playhead) - t0) / (t1 - t0)})`}></div>` : null}
    <div class="axis">${ticks.map((v) => html`<span style=${`left:${((v - t0) / (t1 - t0)) * 100}%`}>${new Date(v).toTimeString().slice(0, 8)}</span>`)}</div>
  </div>`;
}

// Story: each answer sentence becomes a step; the step's evidence state comes from what it cites.
export function stepState(sentence, citations) {
  const ns = [...sentence.matchAll(/\[E(\d+)\]/g)].map((m) => +m[1]);
  const cs = ns.map((n) => citations.find((c) => c.n === n)).filter(Boolean);
  if (cs.some((c) => c.status === "INFERRED")) return { state: "INFERRED", cites: cs };
  if (cs.length) return { state: cs[0].status === "LAST_SEEN" ? "LAST_SEEN" : "OBSERVED", cites: cs };
  if (/no authorized camera|unknown|no camera|not covered|no recording|no replay|gap/i.test(sentence)) return { state: "UNKNOWN", cites: [] };
  if (/recorded|check-in|registered/i.test(sentence)) return { state: "RECORDED", cites: [] };
  return { state: "NOTE", cites: [] };
}

export function Story({ sentences, citations, active, onPick, gaps = [] }) {
  return html`<ol class="story">${sentences.map((s, i) => {
    const { state, cites } = stepState(s, citations);
    const c = cites[0];
    const t = c ? hhmmss(c.ts) : state === "UNKNOWN" && gaps[0] ? `${hhmmss(gaps[0].ts_start)} →` : "";
    const on = c && cites.some((x) => x.n === active);
    return html`<li class=${`step ${state} ${on ? "on" : ""} ${c ? "has" : ""}`} key=${i} style=${`--i:${i}`}
        onClick=${() => c && onPick && onPick(c.n)}>
      <span class="rail"><i></i></span>
      <div class="step-b">
        <div class="step-m">${t ? html`<span class="mono">${t}</span>` : null}${state !== "NOTE" ? html`<span class=${`tag-s ${state}`}>${STATUS_LABEL[state]}</span>` : null}
          ${c ? html`<span>${(c.source || "").split(" · ").slice(-1)[0]}</span>` : null}</div>
        <p><${Cited} text=${s} citations=${citations} active=${active} onCite=${onPick} /></p>
      </div>
      ${c?.url ? html`<img class="thumb" src=${c.url} alt=${c.caption || ""} loading="lazy" />` : null}
    </li>`;
  })}</ol>`;
}

// Steps: the agent's structured timeline. Meta line = time · state · place; title is short; the reasoning
// ("basis") opens only for the selected step.
export function Steps({ steps, active, onPick, compact = false }) {
  const sorted = [...steps].sort((a, b) => (a.ts && b.ts ? a.ts.localeCompare(b.ts) : 0));
  const [open, setOpen] = useState(null);
  return html`<ol class=${`story ${compact ? "compact" : ""}`}>${sorted.map((st, i) => {
    const on = st.n != null && st.n === active;
    const show = on || open === i;
    return html`<li class=${`step ${st.status} ${on ? "on" : ""} has`} key=${i} style=${`--i:${i}`}
        onClick=${() => { if (st.n != null) onPick && onPick(st.n); setOpen(open === i ? null : i); }}>
      <span class="rail"><i></i></span>
      <div class="step-b">
        <div class="step-m">${st.ts ? html`<span class="mono">${hhmmss(st.ts)}${st.status === "UNKNOWN" ? " →" : ""}</span>` : null}
          <span class=${`tag-s ${st.status}`}>${STATUS_LABEL[st.status] || st.status}</span>${st.place ? html`<span>${st.place}</span>` : null}
          ${st.n != null ? html`<span class=${`cite ${st.status === "INFERRED" ? "inferred" : ""} ${on ? "on" : ""}`}>E${st.n}</span>` : null}</div>
        <div class="step-t">${st.title}</div>
        ${show && st.basis ? html`<div class="basis fadein">${st.basis}</div>` : null}
        ${!show && st.basis ? html`<button class="basis-t" onClick=${(e) => { e.stopPropagation(); setOpen(i); }}>Why we think so</button>` : null}
      </div>
    </li>`;
  })}</ol>`;
}

// Evidence viewer: processed video at the cited moment when available, else the stored frame.
export function Viewer({ c, list = [], onNav, empty = "Select a step to see its evidence." }) {
  const ref = useRef();
  const [playing, setPlaying] = useState(false);
  const idx = c ? list.findIndex((x) => x.n === c.n) : -1;
  const play = () => {
    const v = ref.current;
    if (!v) return;
    v.currentTime = c.proxy_url ? Math.max(0, (c.t_offset_s || 0) - 1.5) : 0;
    v.play().catch(() => {});
  };
  const src = c?.proxy_url || c?.clip_url;
  useEffect(() => {
    const v = ref.current;
    if (!v || !c) return;
    const t = c.proxy_url ? Math.max(0, (c.t_offset_s || 0) - 1.5) : 0;
    const seek = () => { try { v.currentTime = t; v.pause(); } catch {} };
    if (v.readyState >= 1) seek(); else v.addEventListener("loadedmetadata", seek, { once: true });
  }, [c?.evidence_id || c?.id, src]);
  if (!c) return html`<div class="viewer-empty">${empty}</div>`;
  return html`<figure class="viewer fadein">
    <div class="media">
      ${src ? html`<video ref=${ref} src=${src} muted playsinline poster=${c.url || ""} onPlay=${() => setPlaying(true)} onPause=${() => setPlaying(false)} onEnded=${() => setPlaying(false)} onClick=${() => (playing ? ref.current.pause() : play())}></video>`
            : c.url ? html`<img src=${c.url} alt=${c.caption || ""} />` : html`<div class="noimg">${c.caption || c.label}</div>`}
      <div class="media-tags"><span class="glass">${(c.source || c.source_id || "").split(" · ")[0]}</span><span class="glass mono">${hhmmss(c.ts)}</span>
        <span class="sp"></span><span class="glass dimmed">${src ? "Video · faces masked" : "Still frame"}</span></div>
      ${src && !playing ? html`<button class="play" onClick=${play} aria-label="Play clip"><${Icon} name="play" size=${18} /> Play clip</button>` : null}
    </div>
    ${list.length > 1 && idx >= 0 ? html`<div class="vnav">
      <button class="iconbtn" disabled=${idx <= 0} onClick=${() => onNav && onNav(list[idx - 1].n)} aria-label="Previous evidence"><${Icon} name="chevl" size=${18} /></button>
      <span class="mono">E${c.n} <span class="dim">/ ${list.length}</span></span>
      <button class="iconbtn" disabled=${idx >= list.length - 1} onClick=${() => onNav && onNav(list[idx + 1].n)} aria-label="Next evidence"><${Icon} name="chevr" size=${18} /></button>
    </div>` : null}
    <figcaption><${Status} s=${c.status} /><span>${c.caption || c.label || ""}</span><span class="sp"></span>
      ${c.provenance ? html`<span class="prov">${c.provenance}</span>` : null}</figcaption>
  </figure>`;
}
