import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Cited, Empty, Err, EvidenceCard, html, Icon, Skel, Status, useAsync, VTimeline, hhmmss } from "../lib/ui.js";

const WS_TITLE = {
  campus: ["Campus", "Bicycles, racks and paths"],
  metro: ["Metro demo", "Station alarms, cameras and staff radio"],
  construction: ["Construction", "Workers, machines and hazard zones"],
};

export function AskPage({ ws, go, route }) {
  const ov = useAsync(() => api.overview(ws), [ws]);
  const [q, setQ] = useState(route.q.get("q") || "");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [active, setActive] = useState(null);
  const input = useRef();

  const run = async (question) => {
    const text = (question ?? q).trim();
    if (!text) return;
    setQ(text); setBusy(true); setErr(null); setActive(null);
    try { setRes(await api.ask(ws, text)); } catch (e) { setErr(e); setRes(null); }
    setBusy(false);
  };
  useEffect(() => { if (route.q.get("q")) run(route.q.get("q")); }, []);
  useEffect(() => {
    const k = (e) => { if (e.key === "/" && document.activeElement !== input.current) { e.preventDefault(); input.current.focus(); } };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, []);

  const o = ov.data;
  const [title, sub] = WS_TITLE[ws] || [ws, ""];
  const cite = res && active ? res.citations.find((c) => c.n === active) : null;

  return html`<div class="stack" style="gap:22px">
    <section class="ask-hero">
      <div class="row"><span class="kicker">${title}</span><span class="dim" style="font-size:13px">· ${sub}</span></div>
      <h1 class="h1" style="margin-top:14px">Ask what happened.<br/><i style="color:var(--gold)">Get the evidence.</i></h1>
      <form class="askbox" onSubmit=${(e) => { e.preventDefault(); run(); }}>
        <${Icon} name="ask" size=${20} />
        <input ref=${input} value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="Ask VESTIGE about this workspace…"
          aria-label="Ask VESTIGE" autocomplete="off" />
        <span class="kbd">/</span>
        <button class="btn gold" disabled=${busy || !q.trim()}>${busy ? html`<span class="spin"></span>` : "Ask"}</button>
      </form>
      <div class="sugs">${(o?.suggestions || []).map((s) => html`<button class="sug" onClick=${() => run(s)}>${s}</button>`)}</div>
    </section>

    <${Err} error=${err || ov.error} />

    ${busy ? html`<div class="grid g2"><div class="card pad stack"><${Skel} h=${22} /><${Skel} h=${22} w="80%" /><${Skel} h=${22} w="60%" /></div>
      <div class="card pad"><${Skel} h=${200} /></div></div>` : null}

    ${res && !busy ? html`<section class="grid ask-result-grid fadein">
      <div class="card">
        <div class="card-h"><div class="row"><span class="kicker">Answer</span>
          <span class="pill">${res.intent.replace("_", " ")}</span><span class="pill">${res.planner}</span></div>
          <span class="mono dim" style="font-size:11px">${res.latency_ms} ms · ${res.tool_calls.length} tool calls</span></div>
        <div class="card-b">
          <div class="answer">${res.sentences.map((s) => html`<p class="s"><${Cited} text=${s} citations=${res.citations} active=${active} onCite=${setActive} /></p>`)}</div>
          ${res.subject ? html`<div class="row wrap" style="margin-top:14px">
            ${res.subject.type === "object" ? html`<button class="btn sm" onClick=${() => go("memory", res.subject.id)}>Open object history <${Icon} name="arrow" size=${14} /></button>` : null}
            ${res.subject.type === "event" ? html`<button class="btn sm" onClick=${() => go("investigate", res.subject.id)}>Open investigation <${Icon} name="arrow" size=${14} /></button>
              <button class="btn sm" onClick=${() => go("lab", null, { event: res.subject.id, ws })}><${Icon} name="flask" size=${14} /> Stress test this event</button>` : null}
          </div>` : null}
          <details style="margin-top:18px"><summary class="label" style="cursor:pointer">How this answer was built</summary>
            <div class="trace" style="margin-top:10px">
              ${res.tool_calls.map((t, i) => html`<div class="tc"><span>${i + 1}</span><span><b>${t.tool}</b>(${(t.args || []).join?.(", ") ?? ""})</span><span>${t.results} rows · ${t.ms} ms</span></div>`)}
              <div style="margin-top:8px">Facts come only from these calls; the planner chooses tools, it never writes timestamps or places.</div>
            </div></details>
        </div>
      </div>
      <div class="stack">
        <div class="row"><span class="kicker">Evidence</span><span class="dim" style="font-size:12px">${res.citations.length} items · click to inspect</span></div>
        ${res.citations.length ? html`<div class="grid evidence-grid">
          ${res.citations.map((c) => html`<${EvidenceCard} c=${c} on=${active === c.n} onClick=${() => setActive(c.n)} />`)}</div>`
          : html`<${Empty} title="No evidence">This answer has no supporting evidence.</${Empty}>`}
        ${cite ? html`<div class="card pad fadein stack" style="gap:8px">
          <div class="row"><span class="cite on">E${cite.n}</span><${Status} s=${cite.status} /><span class="mono dim">${hhmmss(cite.ts)}</span>
            <span class="sp"></span><span class="pill">${cite.provenance}</span></div>
          ${cite.url ? html`<img src=${cite.url} alt=${cite.caption} style="border-radius:10px" />` : null}
          <div style="font-size:13px">${cite.caption}</div>
          <div class="dim mono" style="font-size:11px">${cite.source} · evidence ${cite.evidence_id}${cite.t_offset_s != null ? ` · t+${cite.t_offset_s}s in source` : ""}</div>
          ${cite.proxy_url ? html`<video src=${`${cite.proxy_url}#t=${Math.max(0, (cite.t_offset_s || 0) - 1)}`} controls muted playsinline style="width:100%;border-radius:10px"></video>` : null}
        </div>` : null}
        ${res.gaps.map((g) => html`<div class="gap"><div class="row" style="margin-bottom:6px"><${Status} s="UNKNOWN" /><span class="mono">${hhmmss(g.ts_start)} →</span></div>${g.reason}</div>`)}
      </div>
    </section>
    ${res.timeline.length ? html`<section class="card fadein"><div class="card-h"><span class="kicker">Reconstructed timeline</span>
      <div class="row" style="gap:6px"><${Status} s="RECORDED" /><${Status} s="OBSERVED" /><${Status} s="INFERRED" /><${Status} s="UNKNOWN" /></div></div>
      <div class="card-b"><${VTimeline} items=${res.timeline} gaps=${res.gaps} /></div></section>` : null}` : null}

    ${!res && !busy && o ? html`<section class="stats fadein">
      ${[["Sources", o.counts.sources], ["Tracks", o.counts.tracks], ["Observations", o.counts.observations], ["Events", o.counts.events], ["Evidence items", o.counts.evidence]]
        .map(([k, v]) => html`<div class="stat"><span class="label">${k}</span><span class="v num">${v}</span></div>`)}
    </section>
    <section class="grid g2 fadein">
      <div class="card"><div class="card-h"><span class="kicker">Recent events</span><a href="#/investigate" class="label">All →</a></div>
        <div class="card-b stack" style="gap:2px">${o.events.length ? o.events.map((e) => html`<a href=${`#/investigate/${e.id}`} class="row" style="padding:8px 0;color:var(--text);border-bottom:1px solid var(--line)">
          <span class=${`mono prio-${e.priority}`} style="font-size:11px;width:56px">${e.priority.toUpperCase()}</span><span>${e.title}</span><span class="sp"></span>
          <span class="mono dim" style="font-size:11px">${hhmmss(e.ts_start)}</span></a>`) : html`<span class="dim">No events yet.</span>`}</div></div>
      <div class="card"><div class="card-h"><span class="kicker">Memory by evidence state</span></div>
        <div class="card-b stack">${["RECORDED", "OBSERVED", "LAST_SEEN", "INFERRED"].map((s) => {
          const n = o.observations_by_status[s] || 0, tot = o.counts.observations || 1;
          return html`<div class="row"><span style="width:92px"><${Status} s=${s} /></span><div class="bar sp"><i style=${`width:${(100 * n) / tot}%`}></i></div><span class="mono num" style="width:36px;text-align:right">${n}</span></div>`; })}
          <div class="dim" style="font-size:12px">Inferred = cross-camera links. States are never merged: an inferred link is not shown as an observation.</div></div></div>
    </section>` : null}
  </div>`;
}
