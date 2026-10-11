import { useState } from "preact/hooks";
import { api, pollJob } from "../lib/api.js";
import { Empty, Err, html, Icon, Prov, Skel, Toast, useAsync } from "../lib/ui.js";

const fmtDur = (s) => s ? `${Math.round(s)} s` : "—";
const fmtTs = (s) => s ? new Date(s).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

function sourceChip(s) {
  const cls = s === "processed" || s === "benchmark" ? "st-OBSERVED" : s === "failed" ? "st-REJECTED" : "st-INFERRED";
  return html`<span class=${`chip ${cls}`}>${s || "registered"}</span>`;
}

function CoverageMap({ coverage }) {
  const src = coverage?.sources || [];
  const byId = new Map(src.map((s) => [s.id, s]));
  const edges = coverage?.topology || [];
  const gaps = coverage?.gaps || [];
  return html`<div class="stack">
    <div class="map"><svg viewBox="0 0 1000 562" preserveAspectRatio="none">
      <defs><pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="8" stroke="rgba(236,230,218,.35)" stroke-width="2" /></pattern></defs>
      ${edges.map((e) => {
        const a = byId.get(e.a_source), b = byId.get(e.b_source);
        if (!a || !b) return null;
        const ax = Number(a.map_x ?? .5) * 1000, ay = Number(a.map_y ?? .5) * 562;
        const bx = Number(b.map_x ?? .5) * 1000, by = Number(b.map_y ?? .5) * 562;
        return html`<g><line x1=${ax} y1=${ay} x2=${bx} y2=${by} stroke="var(--line-2)" stroke-width="2" />
          <text x=${(ax + bx) / 2} y=${(ay + by) / 2 - 8} fill="var(--dim)" font-size="18" font-family="var(--mono)" text-anchor="middle">${Math.round(e.min_travel_s)}–${Math.round(e.max_travel_s)} s</text></g>`;
      })}
      ${src.map((s) => html`<g transform=${`translate(${Number(s.map_x ?? .5) * 1000} ${Number(s.map_y ?? .5) * 562})`}>
        <circle r="16" fill=${s.recording_available === 0 ? "url(#hatch)" : "var(--gold)"} stroke=${s.recording_available === 0 ? "var(--dim)" : "var(--ink)"} stroke-width="4" stroke-dasharray=${s.recording_available === 0 ? "4 4" : ""} />
        <text x="24" y="5" fill="var(--text)" font-size="19" font-family="var(--mono)">${s.id}</text>
      </g>`)}
    </svg></div>
    ${gaps.length ? html`<div class="stack" style="gap:8px">${gaps.map((g) => html`<div class="gap"><b>${g.source_id}</b> · ${fmtTs(g.ts_start)} → ${fmtTs(g.ts_end)}<br/><span class="dim">${g.reason}</span></div>`)}</div>` : html`<div class="dim" style="font-size:12px">No declared coverage gaps for this workspace.</div>`}
  </div>`;
}

export function SourcesPage({ ws }) {
  const [refresh, setRefresh] = useState(0);
  const cov = useAsync(() => api.coverage(ws), [ws, refresh]);
  const [open, setOpen] = useState("");
  const [name, setName] = useState("");
  const [zone, setZone] = useState("");
  const [start, setStart] = useState("");
  const [file, setFile] = useState(null);
  const [auth, setAuth] = useState(false);
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);
  const [toast, setToast] = useState("");

  const submit = async (e) => {
    e.preventDefault(); setErr(null); setJob({ progress: 0, message: "uploading" });
    try {
      const form = new FormData();
      form.append("name", name || file.name);
      form.append("zone_id", zone);
      form.append("start_ts", start);
      form.append("authorized", "true");
      form.append("file", file);
      const res = await api.upload(ws, form);
      const done = await pollJob(res.job_id, setJob);
      if (done.status === "failed") throw new Error(done.message || "processing failed");
      setToast("Source processed and added."); setName(""); setZone(""); setStart(""); setFile(null); setAuth(false);
      setRefresh((x) => x + 1);
    } catch (e2) {
      setErr(e2);
    } finally {
      setJob(null);
    }
  };

  const sources = cov.data?.sources || [];

  return html`<div class="stack" style="gap:22px">
    <header class="page-head"><div><div class="kicker">Sources</div><h1 class="h1" style="margin-top:10px">Sources — authorized inputs only.</h1></div></header>
    <${Err} error=${err || cov.error} />
    <${Toast} msg=${toast} onDone=${() => setToast("")} />

    <section class="grid sources-grid">
      <div class="card"><div class="card-h"><span class="kicker">Workspace inputs</span><span class="mono dim">${sources.length} sources · click a row for details</span></div>
        <div class="card-b table-wrap">
          ${cov.loading ? html`<${Skel} h=${260} />` : sources.length ? html`<table class="t table-compact src-table"><thead><tr><th>Source</th><th class="hide-m">Zone</th><th>Provenance</th><th class="hide-m">Duration</th><th>Status</th><th>Replay</th></tr></thead><tbody>
            ${sources.map((s) => html`<tr class=${open === s.id ? "sel" : ""} onClick=${() => setOpen(open === s.id ? "" : s.id)} style="cursor:pointer" aria-expanded=${open === s.id}>
              <td class="src-name"><b>${(s.name || s.id).split(" · ")[0]}</b><div class="dim" style="font-size:12px">${(s.name || "").split(" · ")[1] || s.kind || ""}</div></td>
              <td class="mono hide-m">${s.zone_id || "—"}</td><td><${Prov} p=${s.provenance} /></td><td class="mono num hide-m">${fmtDur(s.duration_s)}</td><td>${sourceChip(s.status)}</td>
              <td>${s.recording_available === 0 ? html`<span class="chip st-UNKNOWN">live only</span>` : html`<span class="dim">available</span>`}</td>
            </tr>
            ${open === s.id ? html`<tr class="src-detail"><td colspan="6"><dl>
              <dt>Id</dt><dd class="mono">${s.id}</dd>
              <dt>Kind</dt><dd>${s.kind || "—"} · zone ${s.zone_id || "—"} · ${fmtDur(s.duration_s)}</dd>
              <dt>License</dt><dd>${s.license || "—"}</dd>
              ${s.recording_available === 0 ? html`<dt>Replay</dt><dd>Live only — no recording is retained, so gaps are reported, never filled.</dd>` : null}
              <dt>Media</dt><dd>${s.media_path ? `${s.width || "—"}×${s.height || "—"} · ${s.fps ? Math.round(s.fps) : "—"} fps` : "not recorded"}</dd>
              ${s.notes ? html`<dt>Notes</dt><dd>${s.notes}</dd>` : null}
              ${s.error ? html`<dt>Error</dt><dd style="color:var(--red)">${s.error}</dd>` : null}
            </dl></td></tr>` : null}`)}
          </tbody></table>` : html`<${Empty} title="No sources">Add authorized footage to begin processing.</${Empty}>`}
        </div></div>

      <div class="stack">
        <div class="card"><div class="card-h"><span class="kicker">Coverage mini-map</span></div><div class="card-b">${cov.loading ? html`<${Skel} h=${220} />` : html`<${CoverageMap} coverage=${cov.data} />`}</div></div>
        <div class="card"><div class="card-h"><span class="kicker">Upload authorized footage</span></div>
          <form class="card-b stack" onSubmit=${submit}>
            <input class="input" placeholder="Source name" value=${name} onInput=${(e) => setName(e.target.value)} />
            <input class="input" placeholder="Zone id (optional)" value=${zone} onInput=${(e) => setZone(e.target.value)} />
            <label class="stack" style="gap:6px"><span class="label">Start time</span><input class="input" type="datetime-local" value=${start} onInput=${(e) => setStart(e.target.value)} /></label>
            <input class="input" type="file" accept="video/*" onChange=${(e) => setFile(e.target.files[0])} />
            <label class=${`toggle ${auth ? "on" : ""}`}><input type="checkbox" checked=${auth} onChange=${(e) => setAuth(e.target.checked)} /> I am authorized to process this footage</label>
            ${job ? html`<div class="stack" style="gap:8px"><div class="bar"><i style=${`width:${Math.round((job.progress || 0) * 100)}%`}></i></div><span class="mono dim">${job.message}</span></div>` : null}
            <button class="btn gold" disabled=${!auth || !file || !!job}><${Icon} name="upload" />Submit source</button>
          </form></div>
        <div class="gap">Privacy: VESTIGE does not perform face recognition; head regions are blurred in stored evidence, and raw footage is never shown in the UI, only processed proxies.</div>
      </div>
    </section>
  </div>`;
}
