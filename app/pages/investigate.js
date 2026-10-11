import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Cited, Empty, Err, html, Icon, Lanes, Prov, Skel, Status, Toast, useAsync, hhmmss } from "../lib/ui.js";

function Player({ evidence }) {
  const ref = useRef();
  const src = evidence?.proxy_url || evidence?.clip_url;
  useEffect(() => {
    const v = ref.current;
    if (!v || !evidence) return;
    const t = evidence.proxy_url ? Math.max(0, (evidence.t_offset_s || 0) - 1.5) : 0;
    const seek = () => { try { v.currentTime = t; v.play().catch(() => {}); } catch {} };
    if (v.readyState >= 1) seek(); else v.addEventListener("loadedmetadata", seek, { once: true });
  }, [evidence?.id, src]);
  if (!evidence) return html`<div class="skel" style="aspect-ratio:16/9;border-radius:14px"></div>`;
  if (!src && !evidence.url) return html`<div class="gap" style="aspect-ratio:16/9;display:grid;place-items:center;font:italic 22px var(--serif)">
    ${evidence.kind === "transcript" ? `“${evidence.caption}”` : evidence.caption || "No visual evidence for this observation"}</div>`;
  return html`<div style="position:relative">
    ${src ? html`<video ref=${ref} src=${src} controls muted playsinline style="width:100%;aspect-ratio:16/9;border-radius:14px;background:#000;border:1px solid var(--line)"></video>`
          : html`<img src=${evidence.url} alt=${evidence.caption} style="width:100%;border-radius:14px;border:1px solid var(--line)" />`}
    <div class="row wrap" style="position:absolute;top:12px;left:12px;right:12px;gap:6px">
      <span class="chip st-RECORDED">${(evidence.source?.name || evidence.source_id || "").split(" · ")[0]}</span>
      <span class="chip" style="background:rgba(14,15,18,.8);color:var(--text)">${hhmmss(evidence.ts)}</span>
      ${evidence.proxy_url ? html`<span class="chip" style="background:rgba(14,15,18,.8);color:var(--dim)">processed stream · faces masked</span>` : null}
    </div></div>`;
}

export function InvestigatePage({ ws, route, go }) {
  const evs = useAsync(() => api.events(ws), [ws]);
  const cov = useAsync(() => api.coverage(ws), [ws]);
  const [eid, setEid] = useState(route.arg || null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!eid && evs.data?.length) {
      const order = { high: 0, medium: 1, low: 2 };
      setEid([...evs.data].sort((a, b) => order[a.priority] - order[b.priority])[0].id);
    }
  }, [evs.data]);
  const tl = useAsync(() => (eid ? api.timeline(eid, 60) : Promise.resolve(null)), [eid, reload]);
  const [obs, setObs] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [ai, setAi] = useState(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiErr, setAiErr] = useState(null);
  const [activeCite, setActiveCite] = useState(null);
  const [note, setNote] = useState("");
  const [toast, setToast] = useState(null);

  const ev = tl.data?.event;
  useEffect(() => {
    setAi(null); setObs(null); setActiveCite(null);
    if (ev?.evidence_id) api.evidence(ev.evidence_id, ws).then(setEvidence).catch(() => setEvidence(null));
    else setEvidence(null);
  }, [ev?.id]);

  const pickObs = async (o) => {
    setObs(o.id);
    if (o.evidence_id) setEvidence(await api.evidence(o.evidence_id, ws).catch(() => null));
  };
  const askAi = async (q) => {
    setAiBusy(true); setAiErr(null);
    try { setAi(await api.ask(ws, q, eid)); } catch (e) { setAiErr(e); }
    setAiBusy(false);
  };
  const onCite = async (n) => {
    setActiveCite(n);
    const c = ai.citations.find((x) => x.n === n);
    if (c) setEvidence(await api.evidence(c.evidence_id, ws).catch(() => null));
  };
  const doReview = async (d) => {
    try { await api.review(eid, d, note); setToast(`Event marked ${d}. Logged to audit.`); setNote(""); setReload(reload + 1); }
    catch (e) { setToast(String(e.message)); }
  };

  const sources = cov.data?.sources || [];
  const observations = tl.data?.observations || [];

  return html`<div class="stack" style="gap:20px">
    <header class="page-head"><div class="stack" style="gap:10px"><span class="kicker">Investigate</span>
      <h1 class="h1">Every answer has evidence.</h1></div>
      ${ev ? html`<div class="row"><button class="btn" onClick=${() => go("lab", null, { event: ev.id, ws })}><${Icon} name="flask" size=${15} /> Stress test this event</button></div>` : null}
    </header>
    <${Err} error=${evs.error || tl.error} />
    <div class="grid investigate-grid">
      <div class="stack" style="gap:8px">
        <span class="label">Events · ${evs.data?.length ?? ""}</span>
        ${evs.loading ? html`<${Skel} h=${70} /><${Skel} h=${70} />` : null}
        ${!evs.loading && !evs.data?.length ? html`<${Empty} title="No events">Nothing has been flagged in this workspace.</${Empty}>` : null}
        ${(evs.data || []).map((e) => html`<button class="card" onClick=${() => setEid(e.id)}
            style=${`text-align:left;padding:13px 14px;cursor:pointer;${eid === e.id ? "border-color:var(--gold);box-shadow:0 0 0 1px var(--gold)" : ""}`}>
          <div class="row"><span class=${`mono prio-${e.priority}`} style="font-size:10.5px">${e.priority.toUpperCase()}</span><span class="sp"></span>
            <span class="mono dim" style="font-size:10.5px">${e.status}</span></div>
          <div style="font-weight:600;margin-top:5px;line-height:1.3">${e.title}</div>
          <div class="mono dim" style="font-size:11px;margin-top:5px">${hhmmss(e.ts_start)} – ${hhmmss(e.ts_end)}</div></button>`)}
      </div>

      <div class="stack">
        ${ev ? html`<div class="row wrap" style="gap:10px"><span class="serif" style="font-size:30px">${ev.title}</span>
          <span class=${`mono prio-${ev.priority}`}>${ev.priority.toUpperCase()}</span><${Prov} p=${ev.provenance} />
          <span class="sp"></span><span class="mono dim" style="font-size:12px;overflow-wrap:anywhere">${ev.model}</span></div>
          <div class="row wrap" style="gap:8px">${Object.entries(ev.metrics || {}).filter(([k, v]) => typeof v !== "object").map(([k, v]) =>
            html`<span class="pill">${k.replace(/_/g, " ")}: <b style="color:var(--text)">${String(v)}</b></span>`)}</div>` : html`<${Skel} h=${40} />`}
        <${Player} evidence=${evidence} />
        ${evidence ? html`<div class="row" style="font-size:13px"><span class="mono dim">${evidence.id}</span><span>${evidence.caption}</span></div>` : null}
        <div class="card"><div class="card-h"><span class="kicker">Camera lanes · 60 s before the event</span>
          <div class="row" style="gap:6px"><${Status} s="RECORDED" /><${Status} s="OBSERVED" /><span class="chip st-UNKNOWN">gap</span></div></div>
          <div class="card-b">${tl.data ? html`<${Lanes} sources=${sources} observations=${observations} gaps=${tl.data.gaps} window=${[ev.ts_start, ev.ts_end]}
              active=${obs} onPick=${pickObs} playhead=${evidence?.ts} />` : html`<${Skel} h=${150} />`}
            ${tl.data?.gaps?.length ? tl.data.gaps.map((g) => html`<div class="gap" style="margin-top:12px"><b style="color:var(--text)">${g.source}</b> — ${g.reason}</div>`) : null}
          </div></div>
        <div class="card"><div class="card-h"><span class="kicker">Observations</span><span class="dim" style="font-size:12px">click to open evidence</span></div><div class="table-wrap">
          <table class="t"><thead><tr><th>Time</th><th>State</th><th>Source</th><th>What was recorded</th></tr></thead><tbody>
          ${observations.map((o) => html`<tr class=${obs === o.id ? "sel" : ""} onClick=${() => pickObs(o)} style="cursor:pointer">
            <td class="mono">${hhmmss(o.ts)}</td><td><${Status} s=${o.status} /></td><td class="mono" style="font-size:12px">${(o.source || "").split(" · ")[0]}</td>
            <td>${o.detail} ${o.role === "trigger" ? html`<span class="pill" style="margin-left:6px">trigger</span>` : null}</td></tr>`)}
          </tbody></table></div></div>
      </div>

      <div class="stack">
        <div class="card"><div class="card-h"><span class="kicker">AI investigation</span><span class="pill">grounded</span></div>
          <div class="card-b stack">
            <div class="row wrap" style="gap:8px">
              <button class="sug" onClick=${() => askAi("What happened before this event?")}>What happened before this?</button>
              <button class="sug" onClick=${() => askAi("Why was this event flagged?")}>Why was it flagged?</button>
            </div>
            ${aiBusy ? html`<${Skel} h=${18} /><${Skel} h=${18} w="85%" /><${Skel} h=${18} w="70%" />` : null}
            <${Err} error=${aiErr} />
            ${ai && !aiBusy ? html`<div class="fadein" style="font:400 18px/1.55 var(--serif)">${ai.sentences.map((s) => html`<p style="margin:0 0 8px"><${Cited} text=${s} citations=${ai.citations} active=${activeCite} onCite=${onCite} /></p>`)}</div>
              <div class="mono dim" style="font-size:11px">${ai.tool_calls.length} tool calls · ${ai.latency_ms} ms · planner ${ai.planner}</div>` : null}
            ${!ai && !aiBusy ? html`<div class="dim" style="font-size:13px">Answers are composed only from World Memory tool results; camera sightings cite stored frames; records and gaps are labelled as such.</div>` : null}
          </div></div>
        <div class="card"><div class="card-h"><span class="kicker">Human review</span><span class="mono dim" style="font-size:11px">${ev?.status || ""}</span></div>
          <div class="card-b stack" style="gap:10px">
            <textarea class="input" style="height:70px;padding:10px 12px;resize:vertical" placeholder="Note for the audit log (optional)"
              value=${note} onInput=${(e) => setNote(e.target.value)} aria-label="Review note"></textarea>
            <div class="row"><button class="btn gold" onClick=${() => doReview("confirmed")}><${Icon} name="check" size=${15} /> Confirm</button>
              <button class="btn" onClick=${() => doReview("uncertain")}><${Icon} name="q" size=${15} /> Uncertain</button>
              <button class="btn ghost" onClick=${() => doReview("rejected")}><${Icon} name="x" size=${15} /> Reject</button></div>
            <div class="dim" style="font-size:12px">An alert is a reason to look, not a verdict. Movement is not theft; proximity is not intent.</div>
          </div></div>
        ${ev?.metrics?.sop ? html`<div class="card"><div class="card-h"><span class="kicker">Recommended steps</span></div><div class="card-b">
          <ol style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:13px">${ev.metrics.sop.map((s) => html`<li>${s}</li>`)}</ol></div></div>` : null}
      </div>
    </div>
    <${Toast} msg=${toast} onDone=${() => setToast(null)} />
  </div>`;
}
