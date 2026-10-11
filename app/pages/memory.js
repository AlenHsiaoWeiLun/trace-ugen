import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Empty, Err, html, Icon, Skel, Steps, Toast, useAsync, Viewer, hhmmss } from "../lib/ui.js";

// Site map, drawn to read as a map: footpaths between areas, a river, parking bays, camera icons,
// and the object's route in gold (solid = seen on camera, dashed = inferred, grey "?" = no coverage).
const route = (a, b) => {
  const xm = (a[0] + b[0]) / 2;
  return `M${a[0]},${a[1]} L${xm},${a[1]} L${xm},${b[1]} L${b[0]},${b[1]}`;
};

export function SiteMap({ zones, sources, topology, path, gaps }) {
  const W = 1000, H = 562;
  const P = (s) => [s.map_x * W, s.map_y * H];
  const byId = Object.fromEntries(sources.map((s) => [s.id, s]));
  const stops = [];
  for (const p of path.filter((p) => byId[p.source_id])) {
    if (!stops.length || stops[stops.length - 1].source_id !== p.source_id) stops.push(p);
  }
  const last = stops[stops.length - 1];
  const zc = (z) => [(z.x + z.w / 2) * W, (z.y + z.h / 2) * H];
  const river = zones.find((z) => /river/i.test(z.name));
  const under = zones.find((z) => /underpass|gate/i.test(z.name));
  return html`<div class="map v2"><svg viewBox=${`0 0 ${W} ${H}`} role="img" aria-label="Map of the site with the object's route">
    <defs>
      <pattern id="grass" width="14" height="14" patternUnits="userSpaceOnUse"><rect width="14" height="14" fill="#0f1210" /><circle cx="3" cy="4" r="1" fill="#16201a" /><circle cx="10" cy="10" r="1" fill="#16201a" /></pattern>
      <marker id="arw" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#e9b054" /></marker>
    </defs>
    <rect width=${W} height=${H} fill="url(#grass)" />
    <!-- buildings -->
    ${[[40, 20, 250, 70], [380, 20, 230, 110], [650, 30, 140, 90], [380, 470, 170, 70], [880, 40, 100, 120]].map(([x, y, w, h]) =>
      html`<rect x=${x} y=${y} width=${w} height=${h} rx="6" fill="#18191c" stroke="#222327" />`)}
    <!-- river along the riverside path -->
    ${river ? html`<path d=${`M330,${(river.y + river.h) * H + 26} C480,${(river.y + river.h) * H + 6} 640,${(river.y + river.h) * H + 50} ${W},${(river.y + river.h) * H + 22} L${W},${(river.y + river.h) * H + 70} C640,${(river.y + river.h) * H + 96} 480,${(river.y + river.h) * H + 52} 330,${(river.y + river.h) * H + 72} Z`}
      fill="#10222c" stroke="#16313e" /><text x="560" y=${(river.y + river.h) * H + 62} fill="#3d6a7e" font-family="Inter" font-size="15" font-style="italic">river</text>` : null}
    <!-- road crossing over the underpass -->
    ${under ? html`<rect x=${(under.x + under.w * 0.62) * W} y="0" width="34" height=${H} fill="#1d1e21" /><line x1=${(under.x + under.w * 0.62) * W + 17} y1="0" x2=${(under.x + under.w * 0.62) * W + 17} y2=${H} stroke="#3a3b3f" stroke-dasharray="14 12" stroke-width="2" />` : null}
    <!-- footpaths between areas -->
    ${topology.map((t) => byId[t.a_source] && byId[t.b_source] ? html`<path d=${route(P(byId[t.a_source]), P(byId[t.b_source]))} fill="none" stroke="#26272b" stroke-width="22" stroke-linejoin="round" stroke-linecap="round" />` : null)}
    <!-- areas -->
    ${zones.map((z) => {
      const [cx] = zc(z);
      const parking = z.kind === "parking";
      return html`<g>
        <rect x=${z.x * W} y=${z.y * H} width=${z.w * W} height=${z.h * H} rx="10" fill=${parking ? "#1a1b1e" : "rgba(255,255,255,.025)"} stroke=${parking ? "#2c2d31" : "rgba(255,255,255,.08)"} />
        ${parking ? Array.from({ length: 9 }, (_, i) => html`<line x1=${z.x * W + 18 + i * ((z.w * W - 36) / 8)} y1=${(z.y + z.h) * H - 52} x2=${z.x * W + 18 + i * ((z.w * W - 36) / 8)} y2=${(z.y + z.h) * H - 14} stroke="#33343a" stroke-width="2" />`) : null}
        ${parking ? html`<g><rect x=${z.x * W + 12} y=${z.y * H + 12} width="26" height="26" rx="6" fill="#2c4a7a" /><text x=${z.x * W + 25} y=${z.y * H + 31} text-anchor="middle" fill="#fff" font-family="Inter" font-weight="700" font-size="17">P</text></g>` : null}
        <text x=${parking ? z.x * W + 46 : z.x * W + 14} y=${z.y * H + 31} fill="#d9d6cf" font-family="Inter" font-size="18" font-weight="500">${z.name}</text>
      </g>`; })}
    <!-- the object's route -->
    ${stops.slice(1).map((b, i) => html`<path d=${route(P(byId[stops[i].source_id]), P(byId[b.source_id]))} fill="none" stroke="#e9b054" stroke-width="5"
        stroke-linejoin="round" stroke-dasharray=${b.status === "INFERRED" ? "12 10" : ""} marker-end="url(#arw)" />`)}
    ${last && gaps.length ? html`<g>
      <path d=${`M${P(byId[last.source_id])[0]},${P(byId[last.source_id])[1]} L${W - 46},${P(byId[last.source_id])[1]}`} stroke="#6e6b66" stroke-width="3" stroke-dasharray="3 8" stroke-linecap="round" />
      <circle cx=${W - 34} cy=${P(byId[last.source_id])[1]} r="20" fill="#131316" stroke="#6e6b66" stroke-width="2" stroke-dasharray="4 4" />
      <text x=${W - 34} y=${P(byId[last.source_id])[1] + 6} text-anchor="middle" fill="#b9b6af" font-family="Inter" font-weight="600" font-size="18">?</text>
      <text x=${W - 34} y=${P(byId[last.source_id])[1] + 42} text-anchor="middle" fill="#9b988f" font-family="Inter" font-size="13">no camera</text></g>` : null}
    <!-- cameras -->
    ${sources.map((s) => {
      const [x, y] = P(s);
      const k = stops.findIndex((p) => p.source_id === s.id);
      const hit = k >= 0;
      return html`<g>
        <path d=${`M${x},${y} L${x - 42},${y + 58} A70,70 0 0,0 ${x + 42},${y + 58} Z`} fill=${hit ? "rgba(233,176,84,.10)" : "rgba(255,255,255,.035)"} />
        <rect x=${x - 15} y=${y - 11} width="24" height="22" rx="5" fill=${hit ? "#e9b054" : "#2a2b2f"} stroke=${hit ? "#e9b054" : "#55534e"} />
        <path d=${`M${x + 9},${y - 5} L${x + 17},${y - 10} L${x + 17},${y + 10} L${x + 9},${y + 5} Z`} fill=${hit ? "#e9b054" : "#55534e"} />
        ${hit ? html`<g><rect x=${x - 34} y=${y - 46} width="68" height="24" rx="12" fill="#09090b" stroke=${stops[k].status === "INFERRED" ? "#e9b054" : "#e9b054"} stroke-dasharray=${stops[k].status === "INFERRED" ? "4 3" : ""} />
          <text x=${x} y=${y - 29} text-anchor="middle" fill="#f3f1ec" font-family="IBM Plex Mono" font-size="14">${(stops[k].ts || "").slice(11, 16)}</text></g>` : null}
      </g>`; })}
    <!-- legend -->
    <g transform="translate(24 ${H - 26})"><line x1="0" y1="0" x2="34" y2="0" stroke="#e9b054" stroke-width="5" /><text x="42" y="5" fill="#b9b6af" font-family="Inter" font-size="14">seen on camera</text>
      <line x1="170" y1="0" x2="204" y2="0" stroke="#e9b054" stroke-width="5" stroke-dasharray="10 7" /><text x="212" y="5" fill="#b9b6af" font-family="Inter" font-size="14">inferred between cameras</text></g>
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
