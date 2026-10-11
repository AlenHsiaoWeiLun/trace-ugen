import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Empty, Err, html, Icon, Skel, Steps, Toast, useAsync, Viewer, hhmmss } from "../lib/ui.js";

// Site map: zones, cameras, topology, and the object's path through the cameras.
function SiteMap({ zones, sources, topology, path, gaps, focus, onFocus }) {
  const W = 1000, H = 562;
  const P = (s) => [s.map_x * W, s.map_y * H];
  const byId = Object.fromEntries(sources.map((s) => [s.id, s]));
  const stops = path.filter((p) => byId[p.source_id]);
  const segs = [];
  for (let i = 1; i < stops.length; i++) {
    if (stops[i].source_id === stops[i - 1].source_id) continue;
    segs.push([stops[i - 1], stops[i]]);
  }
  const last = stops[stops.length - 1];
  return html`<div class="map"><svg viewBox=${`0 0 ${W} ${H}`} aria-label="Site map">
    <defs><pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(255,255,255,.12)" stroke-width="3" /></pattern>
      <marker id="arw" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#e9b054" /></marker></defs>
    ${zones.map((z) => html`<g><rect x=${z.x * W} y=${z.y * H} width=${z.w * W} height=${z.h * H} rx="14"
        fill=${z.kind === "hazard" ? "rgba(229,103,91,.06)" : "rgba(236,230,218,.035)"} stroke=${z.kind === "hazard" ? "rgba(229,103,91,.45)" : "rgba(236,230,218,.18)"} />
      <text x=${z.x * W + 14} y=${z.y * H + 26} fill="#a9a69f" font-family="Inter" font-size="17" font-weight="500">${z.name}</text></g>`)}
    ${topology.map((t) => byId[t.a_source] && byId[t.b_source] ? html`<line x1=${P(byId[t.a_source])[0]} y1=${P(byId[t.a_source])[1]}
        x2=${P(byId[t.b_source])[0]} y2=${P(byId[t.b_source])[1]} stroke="rgba(236,230,218,.14)" stroke-width="1.5" stroke-dasharray="3 6" />` : null)}
    ${segs.map(([a, b]) => html`<line x1=${P(byId[a.source_id])[0]} y1=${P(byId[a.source_id])[1]} x2=${P(byId[b.source_id])[0]} y2=${P(byId[b.source_id])[1]}
        stroke="#e9b054" stroke-width="3" stroke-dasharray=${b.status === "INFERRED" ? "10 8" : ""} marker-end="url(#arw)" />`)}
    ${last && gaps.length ? html`<g><line x1=${P(byId[last.source_id])[0]} y1=${P(byId[last.source_id])[1]} x2=${Math.min(W - 40, P(byId[last.source_id])[0] + 130)} y2=${P(byId[last.source_id])[1] - 70}
        stroke="#5d5b57" stroke-width="2" stroke-dasharray="4 6" />
      <circle cx=${Math.min(W - 40, P(byId[last.source_id])[0] + 130)} cy=${P(byId[last.source_id])[1] - 70} r="20" fill="url(#hatch)" stroke="#5d5b57" stroke-dasharray="4 4" />
      <text x=${Math.min(W - 40, P(byId[last.source_id])[0] + 130)} y=${P(byId[last.source_id])[1] - 64} text-anchor="middle" fill="#85827c" font-family="IBM Plex Mono" font-size="16">?</text></g>` : null}
    ${sources.map((s) => {
      const [x, y] = P(s);
      const hit = path.some((p) => p.source_id === s.id);
      const on = focus === s.id;
      return html`<g style="cursor:pointer" onClick=${() => onFocus && onFocus(s.id)}>
        <circle cx=${x} cy=${y} r=${on ? 15 : 11} fill=${hit ? "#e9b054" : "#131316"} stroke=${hit ? "#e9b054" : "#85827c"} stroke-width="2" />
        ${s.recording_available === 0 ? html`<circle cx=${x} cy=${y} r="19" fill="none" stroke="#ef7468" stroke-dasharray="3 4" />` : null}
        <text x=${x} y=${y + 34} text-anchor="middle" fill=${hit ? "#f3f1ec" : "#a9a69f"} font-family="IBM Plex Mono" font-size="17">${s.id}</text></g>`; })}
  </svg></div>`;
}

function RecordParking({ ws, zones, onDone }) {
  const [zone, setZone] = useState("");
  const [label, setLabel] = useState("my bicycle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const parking = zones.filter((z) => z.kind === "parking");
  if (!parking.length) return html`<div class="dim" style="font-size:13.5px">This site has no parking zones.</div>`;
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr(null);
    let lat = null, lon = null;
    try {
      const pos = await new Promise((res, rej) => navigator.geolocation ? navigator.geolocation.getCurrentPosition(res, rej, { timeout: 2500 }) : rej());
      lat = pos.coords.latitude; lon = pos.coords.longitude;
    } catch {}
    try { await api.checkin(ws, { label, zone_id: zone || parking[0].id, description: "user-registered", lat, lon }); onDone(); }
    catch (e2) { setErr(e2); }
    setBusy(false);
  };
  return html`<form class="row wrap" style="gap:8px" onSubmit=${submit}>
    <input class="input" style="max-width:220px" value=${label} onInput=${(e) => setLabel(e.target.value)} aria-label="Object label" />
    <select class="input" style="max-width:200px" value=${zone} onChange=${(e) => setZone(e.target.value)} aria-label="Parking zone">
      ${parking.map((z) => html`<option value=${z.id}>${z.name}</option>`)}</select>
    <button class="btn gold" disabled=${busy}>${busy ? html`<span class="spin"></span>` : "Record check-in"}</button>
    <span class="note" style="flex-basis:100%">Stored as RECORDED — your statement, not a camera observation.</span>
    <${Err} error=${err} />
  </form>`;
}

const place = (e) => (e?.source || "").split(" · ").slice(-1)[0];

export function MemoryPage({ ws, route, go }) {
  const [reload, setReload] = useState(0);
  const objs = useAsync(() => api.objects(ws), [ws, reload]);
  const cov = useAsync(() => api.coverage(ws), [ws]);
  const zones = useAsync(() => api.zones(ws), [ws]);
  const tracks = useAsync(() => api.tracks(ws), [ws]);
  const [sel, setSel] = useState(route.arg || null);
  const [toast, setToast] = useState(null);
  const [activeIdx, setActiveIdx] = useState(null);
  const [cite, setCite] = useState(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => { if (!sel && objs.data?.length) setSel(objs.data[0].id); }, [objs.data]);
  const hist = useAsync(() => (sel ? api.history(sel) : Promise.resolve(null)), [sel, reload]);
  // the object's story, told the same way as an answer (short steps, evidence on click)
  const story = useAsync(() => (hist.data?.object ? api.ask(ws, `What happened to ${hist.data.object.label.split(" · ").slice(-1)[0]}?`) : Promise.resolve(null)), [hist.data?.object?.id, reload]);
  const [active, setActive] = useState(null);

  const pick = async (e, i) => {
    setActiveIdx(i);
    const ev = e.evidence_id ? await api.evidence(e.evidence_id, ws).catch(() => null) : null;
    setCite(ev && { evidence_id: ev.id, url: ev.url, proxy_url: ev.proxy_url, t_offset_s: ev.t_offset_s, ts: ev.ts,
      source: ev.source?.name || ev.source_id, caption: ev.caption, provenance: ev.provenance, status: e.status });
  };
  const h = hist.data;
  const entries = h?.entries || [];
  const rec = entries.find((e) => e.status === "RECORDED");
  const lastObs = [...entries].reverse().find((e) => e.status === "OBSERVED" || e.status === "LAST_SEEN");
  const lastInf = [...entries].reverse().find((e) => e.status === "INFERRED");
  const objects = objs.data || [];

  return html`<div class="fadein">
    <div class="page-head" style="align-items:center">
      <div class="obj-strip">${objects.map((o) => html`<button class=${`seg-like btn sm ${sel === o.id ? "" : "ghost"}`} onClick=${() => { setSel(o.id); setActiveIdx(null); setCite(null); }}>${o.label}</button>`)}
        ${!objs.loading && !objects.length ? html`<span class="dim">No registered objects on this site — the cameras still remember ${tracks.data?.length ?? 0} tracks.</span>` : null}</div>
      <button class="btn" onClick=${() => setAdding(!adding)}><${Icon} name="plus" size=${15} /> Record parking</button>
    </div>
    ${adding ? html`<div class="config" style="margin-bottom:28px"><${RecordParking} ws=${ws} zones=${zones.data || []} onDone=${() => { setAdding(false); setReload(reload + 1); setToast("Check-in recorded."); }} /></div>` : null}
    <${Err} error=${objs.error || cov.error || hist.error} />

    ${h?.object ? html`<div>
      <h1 class="h1">${h.object.label.split(" · ").slice(-1)[0].replace(/^./, (c) => c.toUpperCase())}</h1>

      <div class="facts">
        <div class="fact"><span class="v">${rec ? hhmmss(rec.ts) : "—"}</span><span class="k">Recorded by you · ${rec ? place(rec) : "no check-in"}</span></div>
        <div class="fact"><span class="v">${lastObs ? hhmmss(lastObs.ts) : "—"}</span><span class="k">Last direct observation · ${lastObs ? place(lastObs) : "none"}</span></div>
        <div class="fact"><span class="v inf">${lastInf ? hhmmss(lastInf.ts) : "—"}</span><span class="k">Last inferred sighting · ${lastInf ? place(lastInf) : "none"}</span></div>
      </div>
    </div>` : objs.loading ? html`<${Skel} h=${140} />` : null}

    <div class="mem-grid">
      <div class="stack" style="gap:24px">
        ${cov.data ? html`<${SiteMap} zones=${zones.data || []} sources=${cov.data.sources.filter((s) => s.map_x != null)} topology=${cov.data.topology}
            path=${entries.filter((e) => e.source_id && e.status !== "RECORDED")} gaps=${h?.gaps || []} />` : html`<${Skel} h=${420} />`}
        ${cite ? html`<${Viewer} c=${cite} list=${story.data?.citations || []} onNav=${(n) => { setActive(n); setCite(story.data.citations.find((x) => x.n === n)); }} />` : null}
      </div>
      <aside>
        ${h ? html`<div class="section-t">Timeline</div>
          ${story.data ? html`<${Steps} steps=${story.data.steps || []} active=${active} onPick=${(n) => { setActive(n); setCite(story.data.citations.find((x) => x.n === n)); }} compact />` : html`<${Skel} h=${300} />`}`
          : !objs.loading ? html`<${Empty} title="Nothing registered yet">Record where you parked to start an object history.</${Empty}>` : null}
      </aside>
    </div>
    <${Toast} msg=${toast} onDone=${() => setToast(null)} />
  </div>`;
}
