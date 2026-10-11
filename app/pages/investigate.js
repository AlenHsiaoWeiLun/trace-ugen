import { useEffect, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Cited, Empty, Err, html, Icon, Lanes, Prov, Skel, Status, Steps, Toast, useAsync, Viewer, hhmmss } from "../lib/ui.js";

// Evidence rows from /api/evidence → the citation shape the Viewer understands.
const asCite = (e, status = "OBSERVED") => e && ({
  evidence_id: e.id, url: e.url, proxy_url: e.proxy_url, clip_url: e.clip_url, t_offset_s: e.t_offset_s, ts: e.ts,
  source: e.source?.name || e.source_id, caption: e.caption, provenance: e.provenance, status, label: e.caption,
});

const QUESTIONS = [["before", "What happened before?", "What happened before this event?"], ["why", "Why flagged?", "Why was this event flagged?"]];

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
  const [cite, setCite] = useState(null);
  const [mode, setMode] = useState(null);
  const [ai, setAi] = useState(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiErr, setAiErr] = useState(null);
  const [active, setActive] = useState(null);
  const [note, setNote] = useState("");
  const [toast, setToast] = useState(null);

  const ev = tl.data?.event;
  const askAi = async (m) => {
    setMode(m); setAiBusy(true); setAiErr(null);
    try { setAi(await api.ask(ws, QUESTIONS.find((x) => x[0] === m)[2], eid)); } catch (e) { setAiErr(e); }
    setAiBusy(false);
  };
  useEffect(() => {
    setAi(null); setObs(null); setActive(null);
    if (!ev) return;
    if (ev.evidence_id) api.evidence(ev.evidence_id, ws).then((e) => setCite(asCite(e))).catch(() => setCite(null));
    else setCite(null);
    askAi(ev.kind === "worker_vehicle_proximity" || ev.kind === "object_moved" ? "why" : "before");
  }, [ev?.id]);

  const pickObs = async (o) => {
    setObs(o.id);
    if (o.evidence_id) setCite(asCite(await api.evidence(o.evidence_id, ws).catch(() => null), o.status));
  };
  const onCite = (n) => {
    setActive(n);
    const c = ai?.citations.find((x) => x.n === n);
    if (c) setCite(c);
  };
  const doReview = async (d) => {
    try { await api.review(eid, d, note); setToast(`Marked ${d} · written to the audit log`); setNote(""); setReload(reload + 1); }
    catch (e) { setToast(String(e.message)); }
  };

  const sources = cov.data?.sources || [];
  const observations = tl.data?.observations || [];
  const metrics = Object.entries(ev?.metrics || {}).filter(([, v]) => typeof v !== "object");

  return html`<div class="fadein">
    <${Err} error=${evs.error || tl.error} />
    ${evs.loading ? html`<div class="row" style="margin-bottom:28px"><${Skel} h=${62} w="220px" /><${Skel} h=${62} w="220px" /></div>` : null}
    ${!evs.loading && !evs.data?.length ? html`<${Empty} title="No events">Nothing has been flagged on this site yet.</${Empty}>` : null}
    <div class="ev-strip">${(evs.data || []).map((e) => html`<button class=${`ev-tab ${eid === e.id ? "on" : ""}`} onClick=${() => setEid(e.id)}>
      <b>${e.title}</b><span><i class=${`pdot ${e.priority}`}></i>${hhmmss(e.ts_start)} – ${hhmmss(e.ts_end)}</span></button>`)}</div>

    ${ev ? html`<div class="ev-head">
      <div><h1 class="ev-title">${ev.title}</h1>
        <div class="ev-sub"><span class="row" style="gap:7px"><i class=${`pdot ${ev.priority}`}></i>${ev.priority} priority</span><span>·</span>
          <span class="mono">${hhmmss(ev.ts_start)} – ${hhmmss(ev.ts_end)}</span><span>·</span><span>${ev.status}</span><${Prov} p=${ev.provenance} /></div></div>
      <button class="btn" onClick=${() => go("lab", null, { event: ev.id, ws })}><${Icon} name="flask" size=${15} /> Stress-test this event</button>
    </div>
    <div class="ev-grid">
      <div class="stack" style="gap:28px">
        <${Viewer} c=${cite} list=${ai?.citations || []} onNav=${onCite} empty="No visual evidence for this event." />
        <section>
          <div class="section-t">Cameras, 60 s before the event <span class="dim">· click a marker to open its evidence</span></div>
          ${tl.data ? html`<${Lanes} sources=${sources} observations=${observations} gaps=${tl.data.gaps} window=${[ev.ts_start, ev.ts_end]}
              active=${obs} onPick=${pickObs} playhead=${cite?.ts} />` : html`<${Skel} h=${150} />`}
          <div class="row wrap" style="gap:8px;margin-top:6px"><${Status} s="RECORDED" /><${Status} s="OBSERVED" /><${Status} s="INFERRED" /><span class="chip st-UNKNOWN"><i></i>No coverage</span></div>
          ${(tl.data?.gaps || []).map((g) => html`<div class="gap" style="margin-top:14px"><b>${g.source}</b> — ${g.reason}</div>`)}
        </section>
        <details class="disclose"><summary>All observations <span class="dim">· ${observations.length}</span></summary><div class="table-wrap">
          <table class="t"><thead><tr><th>Time</th><th>State</th><th>Camera</th><th>What was recorded</th></tr></thead><tbody>
          ${observations.map((o) => html`<tr class=${obs === o.id ? "sel" : ""} onClick=${() => pickObs(o)} style="cursor:pointer">
            <td class="mono">${hhmmss(o.ts)}</td><td><${Status} s=${o.status} /></td><td>${(o.source || "").split(" · ")[0]}</td>
            <td>${o.detail}${o.role === "trigger" ? html` <span class="pill">trigger</span>` : null}</td></tr>`)}
          </tbody></table></div></details>
        ${metrics.length ? html`<details class="disclose"><summary>Detection details <span class="dim">· ${ev.model}</span></summary>
          <div class="metrics">${metrics.map(([k, v]) => html`<span class="pill">${k.replace(/_/g, " ")}: <b style="color:var(--text);font-weight:500">${String(v)}</b></span>`)}</div></details>` : null}
      </div>

      <aside class="ev-side">
        <div>
          <div class="panel-t"><div class="seg">${QUESTIONS.map(([k, label]) => html`<button class=${mode === k ? "on" : ""} onClick=${() => askAi(k)}>${label}</button>`)}</div>
            ${ai && !aiBusy ? html`<span class="dim" style="font-size:12px">${ai.tool_calls.length} lookups · ${ai.latency_ms} ms</span>` : null}</div>
          ${aiBusy ? html`<div class="stack"><${Skel} h=${20} /><${Skel} h=${20} w="85%" /><${Skel} h=${20} w="70%" /></div>` : null}
          <${Err} error=${aiErr} />
          ${ai && !aiBusy && ai.headline ? html`<p class="headline sm"><${Cited} text=${ai.headline} citations=${ai.citations} active=${active} onCite=${onCite} /></p>` : null}
          ${ai && !aiBusy ? html`<${Steps} steps=${ai.steps || []} active=${active} onPick=${onCite} compact />` : null}
        </div>
        ${ev.metrics?.sop ? html`<details class="disclose" style="margin-top:0"><summary>Recommended steps</summary>
          <div><ol class="why-list">${ev.metrics.sop.map((s) => html`<li>${s}</li>`)}</ol></div></details>` : null}
        <div class="review">
          <div class="section-t" style="margin:0">Review this alert <span class="dim">· ${ev.title}, ${hhmmss(ev.ts_start)}</span></div>
          <textarea class="input" placeholder="Note for the audit log (optional)" value=${note} onInput=${(e) => setNote(e.target.value)} aria-label="Review note"></textarea>
          <div class="row wrap" style="gap:8px"><button class="btn gold" onClick=${() => doReview("confirmed")}><${Icon} name="check" size=${15} /> Confirm alert</button>
            <button class="btn" onClick=${() => doReview("uncertain")}>Uncertain</button>
            <button class="btn ghost" onClick=${() => doReview("rejected")}>False alarm</button></div>
          <div class="note">An alert is a reason to look, not a verdict. Movement is not theft; proximity is not intent.</div>
        </div>
      </aside>
    </div>` : eid ? html`<${Skel} h=${420} />` : null}
    <${Toast} msg=${toast} onDone=${() => setToast(null)} />
  </div>`;
}
