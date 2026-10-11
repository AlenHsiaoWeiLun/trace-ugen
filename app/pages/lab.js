import { useEffect, useState } from "preact/hooks";
import { api, pollJob } from "../lib/api.js";
import { Compare, Empty, Err, html, Icon, Skel, useAsync } from "../lib/ui.js";

const pct = (v) => v == null ? "—" : `${Math.round(v * 100)}%`;
const pp = (v) => v == null ? "—" : `${v >= 0 ? "+" : ""}${Math.round(v * 100)} pp`;
const pathUrl = (p) => p ? `/${p.replace(/^\/+/, "")}` : "";
const shortDate = (ts) => ts ? new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

function statusChip(s) {
  const cls = s === "done" ? "st-OBSERVED" : s === "failed" ? "st-REJECTED" : "st-INFERRED";
  return html`<span class=${`chip ${cls}`}>${s || "queued"}</span>`;
}

function normalizeOptions(o) {
  return {
    perturbations: Object.entries(o?.perturbations || {}).map(([name, v]) => ({ name, ...v })),
    mitigations: Object.entries(o?.mitigations || {}).map(([name, label]) => ({ name, label })),
  };
}

function cellKey(c) {
  return `${c.perturbation}:${c.level}:${c.mitigation}`;
}

function rowKey(c) {
  return `${c.perturbation}:${c.level}`;
}

function valueFor(p, level) {
  const levels = p?.levels || {};
  return levels[level] ?? levels[String(level)] ?? "";
}

function groupedRows(cells) {
  const rows = [];
  const seen = new Set();
  for (const c of cells || []) {
    const k = rowKey(c);
    if (!seen.has(k)) {
      seen.add(k);
      rows.push({ key: k, perturbation: c.perturbation, label: c.label, level: c.level });
    }
  }
  return rows;
}

function bestMitigation(cells) {
  return (cells || []).filter((c) => c.mitigation !== "none" && c.delta != null)
    .sort((a, b) => b.delta - a.delta)[0] || null;
}

function worstBaseline(cells) {
  return (cells || []).filter((c) => c.mitigation === "none" && c.retention != null)
    .sort((a, b) => a.retention - b.retention)[0] || null;
}

function rowBest(cells, r) {
  return (cells || []).filter((c) => c.perturbation === r.perturbation && c.level === r.level && c.mitigation !== "none" && c.delta != null)
    .sort((a, b) => b.delta - a.delta)[0] || null;
}

// Per stress: baseline retention vs the best mitigation *for that stress* (they differ: occlusion favours the
// larger model, noise favours TTA). HTML bars so labels stay readable at any card width.
function Chart({ cells }) {
  const rows = groupedRows(cells);
  const by = new Map((cells || []).map((c) => [cellKey(c), c]));
  return html`<div class="rchart" role="img" aria-label="Retention, baseline versus best mitigation per stress">
    <div class="row wrap rchart-legend"><span><i class="sw base"></i>Baseline YOLO11n</span><span><i class="sw best"></i>Best mitigation for that stress</span></div>
    ${rows.map((r) => {
      const b = by.get(`${r.perturbation}:${r.level}:none`);
      const m = rowBest(cells, r);
      const up = m && m.delta > 0;
      return html`<div class="rrow">
        <div class="rlab"><b>${r.label}</b><span class="mono dim">L${r.level}</span></div>
        <div class="rbars">
          <div class="rbar"><i class="base" style=${`width:${Math.round((b?.retention || 0) * 100)}%`}></i><span class="num">${pct(b?.retention)}</span></div>
          <div class="rbar"><i class=${up ? "best" : "flat"} style=${`width:${Math.round((m?.retention || 0) * 100)}%`}></i><span class="num">${pct(m?.retention)}</span></div>
          <div class="rmeta">${m ? html`<span class=${up ? "delta-up" : "delta-flat"}>${pp(m.delta)}</span> · ${m.mitigation_label} · ${m.latency_ms} ms/frame` : "—"}</div>
        </div></div>`;
    })}
  </div>`;
}

function RetentionMatrix({ rows, columns, by }) {
  return html`<div class="matrix" style=${`--cols:${Math.max(1, columns.length)}`}>
    <div class="matrix-row matrix-head">
      <div>Stress</div>${columns.map((m) => html`<div>${cellsLabel(by, rows, m)}</div>`)}
    </div>
    ${rows.map((r) => html`<div class="matrix-row">
      <div class="matrix-cell" style="background:transparent">
        <b>${r.label}</b>
        <div class="mono dim" style="font-size:11px;margin-top:4px">Level ${r.level}</div>
      </div>
      ${columns.map((m) => {
        const c = by.get(`${r.perturbation}:${r.level}:${m}`);
        const delta = c?.delta || 0;
        const cls = delta > 0 ? "delta-up" : delta < 0 ? "delta-down" : "delta-flat";
        return html`<div class=${`matrix-cell ${m === "none" ? "base" : ""}`} title=${c ? `${c.new_per_frame} new/frame · ${c.latency_ms} ms` : ""}>
          ${c ? html`<div class="v num">${pct(c.retention)}</div>
            <div class="m">${c.kept}/${c.reference} kept</div>
            <div class=${`m ${cls}`}>${m === "none" ? "baseline" : pp(c.delta)}</div>
            <div class="bar"><i style=${`width:${Math.round((c.retention || 0) * 100)}%;background:${m === "none" ? "#5fb3cc" : "var(--gold)"}`}></i></div>` : "—"}
        </div>`;
      })}
    </div>`)}
  </div>`;
}

function cellsLabel(by, rows, mitigation) {
  for (const r of rows) {
    const c = by.get(`${r.perturbation}:${r.level}:${mitigation}`);
    if (c) return c.mitigation_label || mitigation;
  }
  return mitigation;
}

export function LabPage({ ws, route }) {
  const boot = useAsync(() => Promise.all([
    api.labOptions(), api.events(ws), api.sources(ws), api.sources("bench-road"), api.sources("bench-station"), api.labList(),
  ]).then(([options, events, sources, road, station, history]) => ({ options, events, sources, road, station, history })), [ws]);
  const [mode, setMode] = useState(route.q.get("event") ? "event" : "sources");
  const [eventId, setEventId] = useState(route.q.get("event") || "");
  const [bench, setBench] = useState("bench-road");
  const [selectedSources, setSelectedSources] = useState([]);
  const [frames, setFrames] = useState(8);
  const [pertOn, setPertOn] = useState({});
  const [levels, setLevels] = useState({});
  const [mits, setMits] = useState({ none: true, enhance: true });
  const [selected, setSelected] = useState("");
  const [experiment, setExperiment] = useState(null);
  const [hist, setHist] = useState(null);
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);
  const [refresh, setRefresh] = useState(0);

  const data = boot.data;
  const opts = normalizeOptions(data?.options);
  const history = hist || data?.history || [];
  const expState = useAsync(() => selected ? api.labGet(selected) : Promise.resolve(null), [selected, refresh]);

  useEffect(() => {
    if (data?.history) setHist(data.history);
  }, [data]);
  useEffect(() => {
    if (!selected && history.length) setSelected(history[0].id);
  }, [history.length, selected]);
  useEffect(() => {
    if (data?.events?.length && !eventId) setEventId(data.events[0].id);
    if (data?.sources?.length && !selectedSources.length) setSelectedSources(data.sources.filter((s) => s.kind === "camera").map((s) => s.id));
    if (opts.perturbations.length && !Object.keys(pertOn).length) {
      const p = {};
      const l = {};
      opts.perturbations.forEach((x, i) => { p[x.name] = i < 3; l[x.name] = 2; });
      setPertOn(p); setLevels(l);
    }
  }, [data]);
  useEffect(() => {
    setExperiment(expState.data);
  }, [expState.data]);
  useEffect(() => {
    const running = history.find((x) => x.status === "running" || x.status === "queued");
    if (!running) return;
    const t = setInterval(async () => {
      setRefresh((x) => x + 1);
      try { setHist(await api.labList()); } catch {}
    }, 2000);
    return () => clearInterval(t);
  }, [history.map((x) => `${x.id}:${x.status}`).join("|")]);

  const create = async () => {
    setErr(null); setJob({ progress: 0, message: "queued" });
    try {
      const benchSources = bench === "bench-road" ? data.road : data.station;
      const scope = mode === "event" ? { event_id: eventId }
        : mode === "benchmark" ? { source_ids: benchSources.map((s) => s.id), frames_per_source: Number(frames) }
          : { source_ids: selectedSources, frames_per_source: Number(frames) };
      const workspace_id = mode === "benchmark" ? bench : ws;
      const perturbations = opts.perturbations.filter((p) => pertOn[p.name]).map((p) => ({ name: p.name, level: levels[p.name] || 2 }));
      const mitigations = Object.keys(mits).filter((k) => mits[k]);
      const res = await api.labCreate({ workspace_id, scope, perturbations, mitigations });
      setSelected(res.experiment_id);
      const done = await pollJob(res.job_id, setJob);
      if (done.status === "failed") throw new Error(done.message || "IncidentLab failed");
      const latest = await api.labGet(res.experiment_id);
      setExperiment(latest); setRefresh((x) => x + 1);
      setHist(await api.labList());
    } catch (e) {
      setErr(e);
    } finally {
      setJob(null);
    }
  };

  const download = async () => {
    if (!experiment?.id) return;
    const text = await api.labReport(experiment.id);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    a.download = `experiment-${experiment.id}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const summary = experiment?.summary || {};
  const cells = summary.cells || [];
  const rows = groupedRows(cells);
  const columns = ["none", ...new Set(cells.map((c) => c.mitigation).filter((m) => m !== "none"))];
  const by = new Map(cells.map((c) => [cellKey(c), c]));
  const worst = worstBaseline(cells);
  const best = bestMitigation(cells);
  const results = experiment?.results || [];
  const [cmpKey, setCmpKey] = useState(null);
  const cmpRow = rows.find((r) => r.key === cmpKey) || (worst && rows.find((r) => r.perturbation === worst.perturbation && r.level === worst.level)) || rows[0];
  const cmpBest = cmpRow ? rowBest(cells, cmpRow) : null;
  const shot = (ref, mit) => results.find((r) => r.frame_ref === ref && r.perturbation === cmpRow?.perturbation
    && r.params?.level === cmpRow?.level && r.mitigation === mit && r.perturbed_path);
  const pairs = cmpRow && cmpBest ? [...new Set(results.filter((r) => r.perturbed_path).map((r) => r.frame_ref))]
    .map((ref) => ({ a: shot(ref, "none"), b: shot(ref, cmpBest.mitigation) })).filter((x) => x.a && x.b)
    .sort((x, y) => (y.b.n_kept - y.a.n_kept) - (x.b.n_kept - x.a.n_kept)) : [];
  const pair = pairs[0];
  const compare = pair ? pair.a : results.find((r) => r.original_path && r.perturbed_path);
  const failures = (experiment?.results || []).filter((r) => r.n_kept < r.n_ref && r.perturbed_path).slice(0, 8);
  const canRun = opts.perturbations.some((p) => pertOn[p.name]) && (mode !== "event" || eventId)
    && (mode !== "sources" || selectedSources.length) && !job;

  return html`<div class="stack" style="gap:22px">
    <header class="page-head">
      <div><div class="kicker">VERIFY · IncidentLab</div>
        <h1 class="h1" style="margin-top:10px">IncidentLab — know where the AI fails.</h1>
        <div class="dim" style="max-width:860px;margin-top:10px">Detection Retention Rate uses the model's own clean-frame detections as the reference, not human ground truth; it measures robustness under controlled corruption.</div></div>
      <button class="btn" onClick=${download} disabled=${!experiment?.id || experiment.status !== "done"}><${Icon} name="download" />Download report</button>
    </header>
    <${Err} error=${err || boot.error || expState.error} />

    <section class="card">
      <div class="card-h"><span class="kicker">Configure stress test</span>${job ? html`<span class="row"><span class="spin"></span><span class="mono dim">${job.message}</span></span>` : null}</div>
      <div class="card-b stack">
        ${boot.loading ? html`<${Skel} h=${160} />` : html`<div class="grid g3">
          <div class="stack">
            <span class="label">Scope</span>
            <div class="seg">${["event", "benchmark", "sources"].map((m) => html`<button class=${mode === m ? "on" : ""} onClick=${() => setMode(m)}>${m}</button>`)}</div>
            ${mode === "event" ? html`<select class="input" value=${eventId} onChange=${(e) => setEventId(e.target.value)}>
              ${(data.events || []).map((e) => html`<option value=${e.id}>${e.title || e.id}</option>`)}</select>` : null}
            ${mode === "benchmark" ? html`<select class="input" value=${bench} onChange=${(e) => setBench(e.target.value)}>
              <option value="bench-road">Taipei Bridge scooters</option><option value="bench-station">Station crowds</option></select>` : null}
            ${mode === "sources" ? html`<div class="stack" style="gap:6px">${(data.sources || []).filter((s) => s.kind === "camera").map((s) => html`<button class=${`toggle ${selectedSources.includes(s.id) ? "on" : ""}`} onClick=${() => setSelectedSources((xs) => xs.includes(s.id) ? xs.filter((x) => x !== s.id) : [...xs, s.id])}>${s.name || s.id}</button>`)}</div>` : null}
            ${mode !== "event" ? html`<label class="stack" style="gap:7px"><span class="label">Frames per source · ${frames}</span>
              <input type="range" min="4" max="12" value=${frames} onInput=${(e) => setFrames(e.target.value)} /></label>` : null}
          </div>
          <div class="stack"><span class="label">Perturbations</span>${opts.perturbations.map((p) => html`<div class="row wrap" style="justify-content:space-between;border-bottom:1px solid var(--line);padding:6px 0">
            <button class=${`toggle ${pertOn[p.name] ? "on" : ""}`} onClick=${() => setPertOn((x) => ({ ...x, [p.name]: !x[p.name] }))}>${p.label}</button>
            <span class="mono dim" style="font-size:11px">${valueFor(p, levels[p.name] || 2)} ${p.unit}</span>
            <div class="seg">${[1, 2, 3].map((l) => html`<button class=${(levels[p.name] || 2) === l ? "on" : ""} onClick=${() => setLevels((x) => ({ ...x, [p.name]: l }))}>L${l}</button>`)}</div>
          </div>`)}</div>
          <div class="stack"><span class="label">Mitigations</span>${opts.mitigations.map((m) => html`<button disabled=${m.name === "none"} class=${`toggle ${mits[m.name] ? "on" : ""}`} onClick=${() => m.name !== "none" && setMits((x) => ({ ...x, [m.name]: !x[m.name] }))}>${m.label}</button>`)}
            <button class="btn gold" style="margin-top:auto" disabled=${!canRun} onClick=${create}><${Icon} name="play" />Run IncidentLab</button></div>
        </div>`}
        ${job ? html`<div class="bar"><i style=${`width:${Math.round((job.progress || 0) * 100)}%`}></i></div>` : null}
      </div>
    </section>

    <section class="grid lab-layout">
      <div class="stack">
        ${expState.loading && selected ? html`<div class="grid g3"><${Skel} h=${120} /><${Skel} h=${120} /><${Skel} h=${120} /></div>` : null}
        ${!selected && !boot.loading ? html`<${Empty} title="No experiments yet">Run your first stress test.</${Empty}>` : null}
        ${experiment ? html`<div class="stack fadein">
          <div class="stats" style="grid-template-columns:repeat(3,1fr)">
            <div class="stat"><span class="label">Worst baseline</span><span class="v num">${pct(worst?.retention)}</span><span class="dim">${worst ? `${worst.label} · L${worst.level}` : "—"}</span></div>
            <div class="stat"><span class="label">Best gain</span><span class="v num">${pp(best?.delta)}</span><span class="dim">${best?.mitigation_label || "—"}</span></div>
            <div class="stat"><span class="label">Cost of that gain</span><span class="v num">${best ? `${best.latency_ms} ms` : "—"}</span><span class="dim">${best ? `per frame vs ${by.get(`${best.perturbation}:${best.level}:none`)?.latency_ms ?? "—"} ms baseline · ${best.new_delta >= 0 ? "+" : ""}${best.new_delta} new/frame` : "—"}</span></div>
          </div>

          <div class="grid lab-showcase">
            ${compare ? html`<div class="card"><div class="card-h"><span class="kicker">Before / after mitigation</span></div><div class="card-b">${pair ? html`<div class="seg" style="margin-bottom:12px;flex-wrap:wrap">${rows.map((r) => html`<button class=${cmpRow?.key === r.key ? "on" : ""} onClick=${() => setCmpKey(r.key)}>${r.label}</button>`)}</div>
              <${Compare} a=${pathUrl(pair.a.perturbed_path)} b=${pathUrl(pair.b.perturbed_path)} labelA=${`Baseline · ${pair.a.n_kept}/${pair.a.n_ref}`} labelB=${`${cmpBest.mitigation_label} · ${pair.b.n_kept}/${pair.b.n_ref}`} />
              <div class="dim" style="font-size:12px;margin-top:8px">Same frame, same ${cmpRow.label.toLowerCase()} (L${cmpRow.level}); drag to compare the baseline detector with the best mitigation for this stress.</div>`
            : html`<${Compare} a=${pathUrl(compare.original_path)} b=${pathUrl(compare.perturbed_path)} labelA="Clean" labelB=${`${compare.perturbation} · ${compare.mitigation}`} />`}
            <div class="row wrap" style="margin-top:12px"><span class="pill" style="border-color:#ece6da;color:#ece6da">ivory = re-detected</span><span class="pill" style="border-color:var(--red);color:var(--red)">red = missed</span><span class="pill" style="border-color:var(--cyan);color:var(--cyan)">cyan = new detection</span></div></div></div>
            ` : null}
            <div class="card"><div class="card-h"><span class="kicker">Baseline versus best mitigation</span></div><div class="card-b"><${Chart} cells=${cells} /></div></div>
          </div>

          <div class="card"><div class="card-h"><span class="kicker">Retention matrix</span><span class="mono dim">${summary.frames || 0} frames · ${cells.length} cells</span></div>
            <div class="card-b"><${RetentionMatrix} rows=${rows} columns=${columns} by=${by} /></div></div>

          ${compare ? html`<div class="card"><div class="card-h"><span class="kicker">Failure gallery</span></div><div class="card-b grid evidence-grid">${failures.length ? failures.map((r) => html`<div class="ev"><img src=${pathUrl(r.perturbed_path)} alt=${`${r.perturbation} ${r.mitigation}`} /><div class="meta"><b>missed ${r.n_ref - r.n_kept} of ${r.n_ref}</b><span class="sp"></span><span class="mono dim">${r.perturbation} · ${r.mitigation}</span></div></div>`) : html`<span class="dim">No misses in saved thumbnails.</span>`}</div></div>` : null}
          ${summary.method ? html`<div class="dim" style="font-size:12px">${summary.method}</div>` : null}
        </div>` : null}
      </div>
      <aside class="card"><div class="card-h"><span class="kicker">History</span></div><div class="card-b stack" style="gap:4px">
        ${history.length ? history.map((x) => html`<button class="btn ghost" style=${`height:auto;justify-content:flex-start;padding:10px;border-color:${selected === x.id ? "var(--gold)" : "transparent"}`} onClick=${() => setSelected(x.id)}>
          <span class=${x.status === "running" ? "spin" : ""}></span><span style="text-align:left"><span class="mono">${x.id}</span><br/><span class="dim" style="font-size:12px">${x.workspace_id} · ${shortDate(x.created_ts)} · ${(x.summary?.cells || []).length} cells</span></span><span class="sp"></span>${statusChip(x.status)}</button>`) : html`<span class="dim">No experiments yet.</span>`}
      </div></aside>
    </section>
  </div>`;
}
