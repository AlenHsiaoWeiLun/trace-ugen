import { api } from "../lib/api.js";
import { Err, html, Prov, Skel, Status, useAsync } from "../lib/ui.js";

const fmt = (ts) => ts ? new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

export function SettingsPage({ ws, workspaces }) {
  const metrics = useAsync(() => api.metrics(), []);
  const audit = useAsync(() => api.audit(ws), [ws]);
  const workspace = (workspaces || []).find((w) => w.id === ws) || {};
  const cats = [
    ["RECORDED", "User or machine record, preserved as a stated fact."],
    ["OBSERVED", "Perception output from processed footage."],
    ["LAST_SEEN", "Latest observed position before a gap."],
    ["INFERRED", "Linked by association logic; never merged into observed."],
    ["UNKNOWN", "A declared gap or unresolved state."],
  ];
  const prov = [
    ["public-footage", "Openly licensed video inputs used for demo evidence."],
    ["staged", "Scripted demo inputs such as check-ins, alarms, or missing recording hosts."],
    ["user", "Material or declarations supplied by the operator."],
    ["synthetic", "Generated or simulation-only test data."],
  ];

  return html`<div class="stack" style="gap:22px">
    <header class="page-head"><div><div class="kicker">Settings</div><h1 class="h1" style="margin-top:10px">Settings & data policy.</h1></div></header>
    <${Err} error=${metrics.error || audit.error} />

    <section class="grid g2">
      <div class="card"><div class="card-h"><span class="kicker">Workspace</span><span class="pill">${workspace.kind || ws}</span></div>
        <div class="card-b stack">
          <div><h2 class="h2">${workspace.name || ws}</h2><div class="dim" style="margin-top:8px">${workspace.description || "No description."}</div></div>
          <div class="gap"><b>Retention</b><br/>${workspace.retention_days || 30} days (configured value, display only — the demo does not yet delete expired data automatically).</div>
          <div class="grid g2">
            <div class="stack"><span class="label">Data categories</span>${cats.map(([s, d]) => html`<div class="row" style="align-items:flex-start"><span style="width:94px"><${Status} s=${s} /></span><span class="dim" style="font-size:13px">${d}</span></div>`)}</div>
            <div class="stack"><span class="label">Provenance</span>${prov.map(([p, d]) => html`<div class="row" style="align-items:flex-start"><span style="width:118px"><${Prov} p=${p} /></span><span class="dim" style="font-size:13px">${d}</span></div>`)}</div>
          </div>
        </div></div>

      <div class="card"><div class="card-h"><span class="kicker">Engine</span></div>
        <div class="card-b stack" style="gap:16px">
          ${[
            ["Perception", "YOLO11n + ByteTrack + tracklet stitching"],
            ["Association", "topology + travel window + colour signature (no faces)"],
            ["Investigation planner", "deterministic tool planner (optional local Qwen intent classifier: VESTIGE_LLM=qwen)"],
            ["Target hardware", "ASUS UGen300 · Hailo-10H — HailoRT backends implemented, hardware validation pending"],
          ].map(([k, v]) => html`<div><div class="label">${k}</div><div style="margin-top:5px">${v}</div></div>`)}
        </div></div>
    </section>

    <section class="grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));align-items:start">
      <div class="card"><div class="card-h"><span class="kicker">Live metrics</span><span class="mono dim">${fmt(metrics.data?.measured_at)}</span></div>
        <div class="card-b stack">
          ${metrics.loading ? html`<${Skel} h=${180} />` : html`<div class="stats" style="grid-template-columns:1fr">
            <div class="stat"><span class="label">Query latency</span><span class="v num">${metrics.data?.query_latency_ms ?? "—"} ms</span><span class="dim">Measured through the local ask pipeline.</span></div>
          </div>
          <table class="t"><thead><tr><th>Store</th><th>Rows</th></tr></thead><tbody>
            ${Object.entries(metrics.data?.store || {}).map(([k, v]) => html`<tr><td>${k}</td><td class="mono num">${v}</td></tr>`)}
          </tbody></table>`}
        </div></div>

      <div class="card"><div class="card-h"><span class="kicker">Audit log</span><span class="mono dim">${ws}</span></div>
        <div class="card-b" style="overflow:auto">
          ${audit.loading ? html`<${Skel} h=${240} />` : html`<table class="t" style="min-width:720px"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Note</th></tr></thead><tbody>
            ${(audit.data || []).map((r) => html`<tr><td class="mono">${fmt(r.ts)}</td><td>${r.actor}</td><td>${r.action}</td><td class="mono">${r.target || "—"}</td><td class="dim">${r.note || "—"}</td></tr>`)}
          </tbody></table>`}
        </div></div>
    </section>
    <footer class="dim serif" style="font-size:20px">VESTIGE — an Archean project</footer>
  </div>`;
}
