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
function Chart({ cells, sel, onSel }) {
  const rows = groupedRows(cells);
  const by = new Map((cells || []).map((c) => [cellKey(c), c]));
  return html`<div class="rchart" role="group" aria-label="Retention, baseline versus best mitigation per stress">
    <div class="row wrap rchart-legend"><span><i class="sw base"></i>Baseline</span><span><i class="sw best"></i>Most improved in this test</span></div>
    ${rows.map((r) => {
      const b = by.get(`${r.perturbation}:${r.level}:none`);
      const m = rowBest(cells, r);
      const up = m && m.delta > 0;
      return html`<button class=${`rrow ${sel === r.key ? "on" : ""}`} onClick=${() => onSel && onSel(r.key)}>
        <div class="rlab"><b>${r.label}</b><span class="mono dim">L${r.level}</span></div>
        <div class="rbars">
          <div class="rbar"><i class="base" style=${`width:${Math.round((b?.retention || 0) * 100)}%`}></i><span class="num">${pct(b?.retention)}</span></div>
          <div class="rbar"><i class=${up ? "best" : "flat"} style=${`width:${Math.round((m?.retention || 0) * 100)}%`}></i><span class="num">${pct(m?.retention)}</span></div>
          <div class="rmeta">${m ? html`<span class=${up ? "delta-up" : "delta-flat"}>${pp(m.delta)}</span>` : "—"}</div>
        </div></button>`;
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
            <div class="bar"><i style=${`width:${Math.round((c.retention || 0) * 100)}%;background:${m === "none" ? "#6e6b66" : "var(--gold)"}`}></i></div>` : "—"}
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
  const [showConfig, setShowConfig] = useState(!!route.q.get("event"));

  const data = boot.data;
  const opts = normalizeOptions(data?.options);
  const history = hist || data?.history || [];
  const expState = useAsync(() => selected ? api.labGet(selected) : Promise.resolve(null), [selected, refresh]);

  useEffect(() => {
    if (data?.history) setHist(data.history);
  }, [data]);
  useEffect(() => {
    if (!selected && history.length) setSelected((history.find((x) => x.workspace_id === "bench-road" && x.status === "done") || history[0]).id);
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
    .sort((x, y) => (y.b.n_kept - y.a.n_kept) - (x.b.n_kept - x.a.n_kept) || y.a.n_ref - x.a.n_ref) : [];
  const pair = pairs[0];
  const compare = pair ? pair.a : results.find((r) => r.original_path && r.perturbed_path);
  const failures = (experiment?.results || []).filter((r) => r.n_kept < r.n_ref && r.perturbed_path).slice(0, 8);
  const canRun = opts.perturbations.some((p) => pertOn[p.name]) && (mode !== "event" || eventId)
    && (mode !== "sources" || selectedSources.length) && !job;

  const base = cmpRow ? by.get(`${cmpRow.perturbation}:${cmpRow.level}:none`) : null;
  const wsName = (id) => ({ "bench-road": "Taipei Bridge scooters", "bench-station": "Station crowds", campus: "Campus", metro: "Metro", construction: "Construction" })[id] || id;

  return html`<div class="fadein">
    <header class="page-head">
      <div><h1 class="h1">Where does detection break?</h1>
        <p class="lede">We degrade real frames and measure what the detector still finds.</p></div>
      <div class="row wrap" style="gap:8px">
        ${history.length ? html`<select class="input" style="width:auto;min-width:240px" value=${selected} onChange=${(e) => setSelected(e.target.value)} aria-label="Experiment">
          ${history.map((x) => html`<option value=${x.id}>${wsName(x.workspace_id)} · ${shortDate(x.created_ts)}${x.status !== "done" ? ` · ${x.status}` : ""}</option>`)}</select>` : null}
        <button class="btn ghost" onClick=${() => setShowConfig(!showConfig)}><${Icon} name=${showConfig ? "x" : "plus"} size=${15} />${showConfig ? "Close" : "New test"}</button>
      </div>
    </header>
    <${Err} error=${err || boot.error || expState.error} />

    ${showConfig ? html`<section class="config fadein">
      ${boot.loading ? html`<${Skel} h=${160} />` : html`<div class="config-grid">
        <div class="stack">
          <span class="label">What to test</span>
          <div class="seg">${[["event", "An event"], ["benchmark", "Benchmark"], ["sources", "Cameras"]].map(([m, l]) => html`<button class=${mode === m ? "on" : ""} onClick=${() => setMode(m)}>${l}</button>`)}</div>
          ${mode === "event" ? html`<select class="input" value=${eventId} onChange=${(e) => setEventId(e.target.value)}>
            ${(data.events || []).map((e) => html`<option value=${e.id}>${e.title || e.id}</option>`)}</select>` : null}
          ${mode === "benchmark" ? html`<select class="input" value=${bench} onChange=${(e) => setBench(e.target.value)}>
            <option value="bench-road">Taipei Bridge scooters</option><option value="bench-station">Station crowds</option></select>` : null}
          ${mode === "sources" ? html`<div class="stack" style="gap:6px">${(data.sources || []).filter((s) => s.kind === "camera").map((s) => html`<button class=${`toggle ${selectedSources.includes(s.id) ? "on" : ""}`} onClick=${() => setSelectedSources((xs) => xs.includes(s.id) ? xs.filter((x) => x !== s.id) : [...xs, s.id])}>${s.name || s.id}</button>`)}</div>` : null}
          ${mode !== "event" ? html`<label class="stack" style="gap:7px"><span class="label">Frames per camera · ${frames}</span>
            <input type="range" min="4" max="12" value=${frames} onInput=${(e) => setFrames(e.target.value)} /></label>` : null}
        </div>
        <div class="stack" style="gap:8px"><span class="label">Stresses</span>${opts.perturbations.map((p) => html`<div class="pert">
          <button class=${`toggle ${pertOn[p.name] ? "on" : ""}`} onClick=${() => setPertOn((x) => ({ ...x, [p.name]: !x[p.name] }))}>${p.label}</button>
          <div class="seg">${[1, 2, 3].map((l) => html`<button class=${(levels[p.name] || 2) === l ? "on" : ""} onClick=${() => setLevels((x) => ({ ...x, [p.name]: l }))}>L${l}</button>`)}</div>
          ${pertOn[p.name] ? html`<span class="v">${valueFor(p, levels[p.name] || 2)} ${p.unit}</span>` : null}
        </div>`)}</div>
        <div class="stack" style="gap:8px"><span class="label">Fixes to compare</span>${opts.mitigations.map((m) => html`<button disabled=${m.name === "none"} class=${`toggle ${mits[m.name] ? "on" : ""}`} onClick=${() => m.name !== "none" && setMits((x) => ({ ...x, [m.name]: !x[m.name] }))}>${m.name === "none" ? "Baseline (always included)" : m.label}</button>`)}
          <button class="btn gold" style="margin-top:12px" disabled=${!canRun} onClick=${create}>${job ? html`<span class="spin"></span>` : html`<${Icon} name="play" size=${14} />`} Run stress test</button>
          ${job ? html`<div class="stack" style="gap:6px"><div class="bar"><i style=${`width:${Math.round((job.progress || 0) * 100)}%`}></i></div><span class="note">${job.message}</span></div>` : null}</div>
      </div>`}
    </section>` : null}

    ${expState.loading && selected && !experiment ? html`<div class="lab-hero"><${Skel} h=${380} /><${Skel} h=${380} /></div>` : null}
    ${!selected && !boot.loading ? html`<${Empty} title="No experiments yet">Run your first stress test.</${Empty}>` : null}
    ${experiment && experiment.status !== "done" ? html`<div class="gap">This experiment is ${experiment.status}${experiment.error ? `: ${experiment.error}` : "…"}</div>` : null}
    ${experiment && cells.length ? html`<div class="lab-hero fadein">
      <div>
        ${pair ? html`<${Compare} a=${pathUrl(pair.a.perturbed_path)} b=${pathUrl(pair.b.perturbed_path)} labelA=${`Baseline · found ${pair.a.n_kept}/${pair.a.n_ref}`} labelB=${`${cmpBest.mitigation_label} · ${pair.b.n_kept}/${pair.b.n_ref}`} />`
          : compare ? html`<${Compare} a=${pathUrl(compare.original_path)} b=${pathUrl(compare.perturbed_path)} labelA="Clean" labelB=${`${compare.perturbation} · ${compare.mitigation}`} />` : html`<div class="viewer-empty">No saved frames for this stress.</div>`}
        <div class="legend"><span><i style="border-color:#ece6da"></i>found</span><span><i style="border-color:var(--red)"></i>missed</span><span class="sp"></span><span>Drag to compare</span></div>
      </div>
      <div>
        <span class="label">${cmpRow?.label} · ${wsName(experiment.workspace_id)}</span>
        <div class="big-num"><span class="from">${pct(base?.retention)}</span><span class="arr">→</span><span class="to">${pct(cmpBest?.retention)}</span></div>
        <p class="lab-claim">The detector still finds <b>${pct(base?.retention)}</b> of what it finds on clean frames.${" "}
          ${cmpBest && cmpBest.delta > 0 ? html`In this test, <b>${cmpBest.mitigation_label.replace(/^./, (x) => x.toLowerCase())}</b> raised that to <b>${pct(cmpBest.retention)}</b>.` : html`None of the tested methods helped here.`}</p>
        <${Chart} cells=${cells} sel=${cmpRow?.key} onSel=${setCmpKey} />
        <p class="note" style="margin-top:18px">Detection retention, not accuracy.</p>
      </div>
    </div>
    <details class="disclose" style="margin-top:40px"><summary>Full results and method</summary><div class="stack" style="gap:24px">
      <${RetentionMatrix} rows=${rows} columns=${columns} by=${by} />
      ${summary.method ? html`<p class="note" style="margin:0">${summary.method} Retention = share of the model's own clean-frame detections still found (IoU ≥ 0.5); it measures robustness, not accuracy against human labels.</p>` : null}
      <div><button class="btn sm" onClick=${download}><${Icon} name="download" size=${14} /> Download report</button></div></div></details>` : null}
  </div>`;
}
