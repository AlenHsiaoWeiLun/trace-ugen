import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../lib/api.js";
import { Empty, Err, html, Icon, Prov, Skel, Status, Toast, useAsync, VTimeline, hhmmss } from "../lib/ui.js";

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
      <marker id="arw" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#e0a33b" /></marker></defs>
    ${zones.map((z) => html`<g><rect x=${z.x * W} y=${z.y * H} width=${z.w * W} height=${z.h * H} rx="14"
        fill=${z.kind === "hazard" ? "rgba(229,103,91,.06)" : "rgba(236,230,218,.035)"} stroke=${z.kind === "hazard" ? "rgba(229,103,91,.45)" : "rgba(236,230,218,.18)"} />
      <text x=${z.x * W + 14} y=${z.y * H + 26} fill="#a39d92" font-family="IBM Plex Mono" font-size="15" letter-spacing="1.5">${z.name.toUpperCase()}</text></g>`)}
    ${topology.map((t) => byId[t.a_source] && byId[t.b_source] ? html`<line x1=${P(byId[t.a_source])[0]} y1=${P(byId[t.a_source])[1]}
        x2=${P(byId[t.b_source])[0]} y2=${P(byId[t.b_source])[1]} stroke="rgba(236,230,218,.14)" stroke-width="1.5" stroke-dasharray="3 6" />` : null)}
    ${segs.map(([a, b]) => html`<line x1=${P(byId[a.source_id])[0]} y1=${P(byId[a.source_id])[1]} x2=${P(byId[b.source_id])[0]} y2=${P(byId[b.source_id])[1]}
        stroke="#e0a33b" stroke-width="3" stroke-dasharray=${b.status === "INFERRED" ? "10 8" : ""} marker-end="url(#arw)" />`)}
    ${last && gaps.length ? html`<g><line x1=${P(byId[last.source_id])[0]} y1=${P(byId[last.source_id])[1]} x2=${Math.min(W - 40, P(byId[last.source_id])[0] + 130)} y2=${P(byId[last.source_id])[1] - 70}
        stroke="#6f6b64" stroke-width="2" stroke-dasharray="4 6" />
      <circle cx=${Math.min(W - 40, P(byId[last.source_id])[0] + 130)} cy=${P(byId[last.source_id])[1] - 70} r="20" fill="url(#hatch)" stroke="#6f6b64" stroke-dasharray="4 4" />
      <text x=${Math.min(W - 40, P(byId[last.source_id])[0] + 130)} y=${P(byId[last.source_id])[1] - 64} text-anchor="middle" fill="#a39d92" font-family="IBM Plex Mono" font-size="16">?</text></g>` : null}
    ${sources.map((s) => {
      const [x, y] = P(s);
      const hit = path.some((p) => p.source_id === s.id);
      const on = focus === s.id;
      return html`<g style="cursor:pointer" onClick=${() => onFocus && onFocus(s.id)}>
        <circle cx=${x} cy=${y} r=${on ? 15 : 11} fill=${hit ? "#e0a33b" : "#16181c"} stroke=${hit ? "#e0a33b" : "#a39d92"} stroke-width="2" />
        ${s.recording_available === 0 ? html`<circle cx=${x} cy=${y} r="19" fill="none" stroke="#e5675b" stroke-dasharray="3 4" />` : null}
        <text x=${x} y=${y + 34} text-anchor="middle" fill=${hit ? "#ece6da" : "#a39d92"} font-family="IBM Plex Mono" font-size="14">${s.id}</text></g>`; })}
  </svg></div>`;
}

function RecordParking({ ws, zones, onDone }) {
  const [zone, setZone] = useState("");
  const [label, setLabel] = useState("my bicycle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const parking = zones.filter((z) => z.kind === "parking");
  if (!parking.length) return null;
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
  return html`<form class="card pad stack" style="gap:10px" onSubmit=${submit}>
    <span class="kicker">Record parking</span>
    <div class="dim" style="font-size:12.5px">Creates a RECORDED check-in (your statement, not an observation).</div>
    <input class="input" value=${label} onInput=${(e) => setLabel(e.target.value)} aria-label="Object label" />
    <select class="input" value=${zone} onChange=${(e) => setZone(e.target.value)} aria-label="Parking zone">
      ${parking.map((z) => html`<option value=${z.id}>${z.name}</option>`)}</select>
    <button class="btn" disabled=${busy}>${busy ? html`<span class="spin"></span>` : "Record check-in"}</button>
    <${Err} error=${err} />
  </form>`;
}

export function MemoryPage({ ws, route, go }) {
  const [reload, setReload] = useState(0);
  const objs = useAsync(() => api.objects(ws), [ws, reload]);
  const cov = useAsync(() => api.coverage(ws), [ws]);
  const zones = useAsync(() => api.zones(ws), [ws]);
  const tracks = useAsync(() => api.tracks(ws), [ws]);
  const [sel, setSel] = useState(route.arg || null);
  const [selTrack, setSelTrack] = useState(null);
  const [q, setQ] = useState("");
  const [toast, setToast] = useState(null);
  const [activeIdx, setActiveIdx] = useState(null);
  const [ev, setEv] = useState(null);

  useEffect(() => { if (!sel && objs.data?.length) setSel(objs.data[0].id); }, [objs.data]);
  const hist = useAsync(() => (sel ? api.history(sel) : Promise.resolve(null)), [sel, reload]);
  const tobs = useAsync(() => (selTrack ? api.trackObs(selTrack) : Promise.resolve(null)), [selTrack]);

  const pick = async (e, i) => {
    setActiveIdx(i);
    setEv(e.evidence_id ? await api.evidence(e.evidence_id, ws).catch(() => null) : null);
  };
  const list = (objs.data || []).filter((o) => !q || (o.label + o.description).toLowerCase().includes(q.toLowerCase()));
  const h = hist.data;
  const entries = h?.entries || [];

  return html`<div class="stack" style="gap:22px">
    <header class="page-head"><div class="stack" style="gap:10px"><span class="kicker">Remember</span>
      <h1 class="h1">Every object has a history.</h1>
      <div class="dim" style="max-width:720px">Detections become persistent memories: what was seen, where, when, by which camera — and whether it was recorded, observed, inferred or unknown.</div></div>
      <div class="row" style="gap:6px"><${Status} s="RECORDED" /><${Status} s="OBSERVED" /><${Status} s="INFERRED" /><${Status} s="UNKNOWN" /></div>
    </header>
    <${Err} error=${objs.error || cov.error || hist.error} />
    <div class="grid" style="grid-template-columns:280px minmax(0,1fr) 400px;align-items:start">
      <div class="stack">
        <input class="input" placeholder="Search objects…" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Search objects" />
        ${objs.loading ? html`<${Skel} h=${64} /><${Skel} h=${64} />` : null}
        ${list.map((o) => html`<button class="card" onClick=${() => { setSel(o.id); setSelTrack(null); setActiveIdx(null); setEv(null); }}
            style=${`text-align:left;padding:14px 16px;cursor:pointer;${sel === o.id ? "border-color:var(--gold);box-shadow:0 0 0 1px var(--gold)" : ""}`}>
          <div class="row"><span class="h3">${o.label}</span><span class="sp"></span><${Prov} p=${o.provenance} /></div>
          <div class="dim" style="font-size:12.5px;margin-top:4px">${o.description || o.cls} · since ${hhmmss(o.created_ts)}</div></button>`)}
        ${!objs.loading && !list.length ? html`<div class="dim" style="font-size:13px;padding:4px 2px">No registered objects. Tracks below are what the cameras remember.</div>` : null}
        <${RecordParking} ws=${ws} zones=${zones.data || []} onDone=${() => { setReload(reload + 1); setToast("Check-in recorded."); }} />
        <div class="card"><div class="card-h"><span class="kicker">Tracks in memory</span><span class="mono dim" style="font-size:11px">${tracks.data?.length ?? ""}</span></div>
          <div style="max-height:320px;overflow:auto">${(tracks.data || []).slice(0, 60).map((t) => html`<button onClick=${() => { setSelTrack(t.id); setSel(null); }}
              class="row" style=${`width:100%;border:0;background:${selTrack === t.id ? "var(--gold-soft)" : "transparent"};padding:8px 16px;border-bottom:1px solid var(--line);cursor:pointer;text-align:left`}>
            <span class="mono" style="font-size:11px;width:120px">${t.id.replace("T-", "")}</span><span style="font-size:12.5px">${t.cls}</span><span class="sp"></span>
            <span class="mono dim" style="font-size:11px">${hhmmss(t.start_ts)}</span></button>`)}</div></div>
      </div>

      <div class="stack">
        ${cov.data ? html`<${SiteMap} zones=${zones.data || []} sources=${cov.data.sources.filter((s) => s.map_x != null)} topology=${cov.data.topology}
            path=${entries.filter((e) => e.source_id && e.status !== "RECORDED")} gaps=${h?.gaps || []} />` : html`<${Skel} h=${420} />`}
        ${h?.object ? html`<div class="card pad fadein"><div class="row"><span class="kicker">${h.object.label}</span><span class="sp"></span>
            <span class="dim" style="font-size:12px">${entries.length} memories · ${h.events.length} events · ${h.rejected_links.length} rejected links</span></div>
          <div class="grid g3" style="margin-top:14px">
            ${[["Recorded", entries.find((e) => e.status === "RECORDED")], ["Last direct observation", [...entries].reverse().find((e) => e.status === "OBSERVED" || e.status === "LAST_SEEN")],
               ["Last inferred sighting", [...entries].reverse().find((e) => e.status === "INFERRED")]].map(([k, e]) => html`<div class="stack" style="gap:4px">
              <span class="label">${k}</span><span class="serif" style="font-size:28px">${e ? hhmmss(e.ts) : "—"}</span>
              <span class="dim" style="font-size:12.5px">${e ? e.source.split(" · ").slice(-1)[0] : "none"}</span></div>`)}
          </div></div>` : null}
        ${ev ? html`<div class="card pad fadein stack" style="gap:10px"><div class="row"><span class="kicker">Evidence ${ev.id}</span><span class="sp"></span><${Prov} p=${ev.provenance} /></div>
          ${ev.proxy_url ? html`<video src=${`${ev.proxy_url}#t=${Math.max(0, (ev.t_offset_s || 0) - 1)}`} controls autoplay muted playsinline style="width:100%;border-radius:10px"></video>`
            : ev.url ? html`<img src=${ev.url} alt=${ev.caption} style="border-radius:10px" />` : null}
          <div style="font-size:13px">${ev.caption}</div><div class="mono dim" style="font-size:11px">${ev.source?.name} · ${ev.ts} · sha256 ${ev.sha256 || "—"}</div></div>` : null}
        ${selTrack && tobs.data ? html`<div class="card"><div class="card-h"><span class="kicker">Track ${selTrack}</span></div><div class="card-b">
          <${VTimeline} items=${tobs.data.map((o) => ({ ...o, source: o.source_id }))} onPick=${pick} /></div></div>` : null}
      </div>

      <div class="stack">
        ${h ? html`<div class="card"><div class="card-h"><span class="kicker">History</span><button class="btn sm" onClick=${() => go("ask", null, { ws, q: "What happened to my bicycle?" })}>Ask about it <${Icon} name="arrow" size=${13} /></button></div>
          <div class="card-b"><${VTimeline} items=${entries} gaps=${h.gaps} active=${activeIdx} onPick=${pick} /></div></div>` : !selTrack ? html`<${Empty} title="Select an object">Pick an object or a track to see its memory.</${Empty}>` : null}
        ${h?.rejected_links?.length ? html`<div class="card"><div class="card-h"><span class="kicker">Checked, not linked</span></div><div class="card-b stack" style="gap:10px">
          ${h.rejected_links.map((r) => html`<div class="stack" style="gap:4px;padding-bottom:10px;border-bottom:1px dashed var(--line)">
            <div class="row"><${Status} s="REJECTED" /><span class="mono" style="font-size:11px">${r.b_id.replace("T-", "")}</span></div>
            <div class="dim" style="font-size:12.5px">${(r.basis.reasons || []).join("; ")} · colour ${r.basis.colours?.join(" vs ")} (${r.basis.colour_similarity})</div></div>`)}
        </div></div>` : null}
      </div>
    </div>
    <${Toast} msg=${toast} onDone=${() => setToast(null)} />
  </div>`;
}
