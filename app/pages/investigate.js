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
  const [reviewing, setReviewing] = useState(false);
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
    setReviewing(false);
    askAi("why");
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
    try { await api.review(eid, d, note); setToast(`Saved: ${d === "confirmed" ? "alert confirmed" : d === "rejected" ? "false alarm" : "uncertain"}`); setNote(""); setReviewing(false); setReload(reload + 1); }
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
      <b>${e.title}</b><span><i class=${`pdot ${e.priority}`}></i>${hhmmss(e.ts_start)}${e.metrics?.duration_s ? ` · ${Math.round(e.metrics.duration_s)} s` : ""}</span></button>`)}</div>

    ${ev ? html`<div class="ev-head">
      <div><h1 class="ev-title">${ev.title}</h1>
        <div class="ev-sub"><span class="row" style="gap:7px"><i class=${`pdot ${ev.priority}`}></i>${ev.priority} priority</span><span>·</span>
          <span class="mono">${hhmmss(ev.ts_start)} – ${hhmmss(ev.ts_end)}</span>${ev.status !== "open" ? html`<span>· ${ev.status}</span>` : null}</div></div>
    </div>
    <div class="ev-grid">
      <div class="stack" style="gap:28px">
        <${Viewer} c=${cite} list=${ai?.citations || []} onNav=${onCite} empty="No visual evidence for this event." />
      </div>

      <aside class="ev-side">
        <div>
          ${aiBusy ? html`<div class="stack"><${Skel} h=${20} /><${Skel} h=${20} w="85%" /><${Skel} h=${20} w="70%" /></div>` : null}
          <${Err} error=${aiErr} />
          ${ai && !aiBusy && ai.headline ? html`<p class="headline sm"><${Cited} text=${ai.headline} citations=${ai.citations} active=${active} onCite=${onCite} /></p>` : null}
          ${ai && !aiBusy ? html`<${Steps} steps=${ai.steps || []} active=${active} onPick=${onCite} compact />` : null}
        </div>
        ${ev.metrics?.sop ? html`<details class="disclose" style="margin-top:0"><summary>Recommended steps</summary>
          <div><ol class="why-list">${ev.metrics.sop.map((s) => html`<li>${s}</li>`)}</ol></div></details>` : null}
        <div class="review">
          ${reviewing ? html`<div class="stack fadein" style="gap:10px">
            <textarea class="input" placeholder="Note (optional)" value=${note} onInput=${(e) => setNote(e.target.value)} aria-label="Review note"></textarea>
            <div class="row wrap" style="gap:8px"><button class="btn gold" onClick=${() => doReview("confirmed")}><${Icon} name="check" size=${15} /> Confirm alert</button>
              <button class="btn" onClick=${() => doReview("rejected")}>False alarm</button>
              <button class="btn ghost" onClick=${() => doReview("uncertain")}>Not sure</button></div></div>`
          : html`<div class="row wrap" style="gap:8px"><button class="btn" onClick=${() => setReviewing(true)}><${Icon} name="check" size=${15} /> Review this alert</button>
</div>`}
          <div class="note">An alert is a reason to look, not a verdict.</div>
        </div>
      </aside>
    </div>` : eid ? html`<${Skel} h=${420} />` : null}
    <${Toast} msg=${toast} onDone=${() => setToast(null)} />
  </div>`;
}
