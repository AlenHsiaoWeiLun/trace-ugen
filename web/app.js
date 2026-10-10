const state = {
  mock: new URLSearchParams(location.search).get("mock") === "1",
  scenario: "all",
  status: "all",
  incidents: [],
  details: new Map(),
  sites: new Map(),
  mockReviews: new Map(),
  selectedId: null,
  stats: null,
  history: [],
  hoveredZone: null,
  changedStatusId: null,
  lastAuditCount: 0,
  sopChecks: new Map(),
  activeCitation: null,
  ask: { loading: false, result: null, error: null, draft: "" }
};

const els = {
  clock: document.getElementById("clock"),
  pipelineChip: document.getElementById("pipelineChip"),
  kpiSignals: document.getElementById("kpiSignals"),
  kpiIncidents: document.getElementById("kpiIncidents"),
  kpiReduction: document.getElementById("kpiReduction"),
  kpiSparkline: document.getElementById("kpiSparkline"),
  kpiPending: document.getElementById("kpiPending"),
  privacyBadge: document.getElementById("privacyBadge"),
  stageBars: document.getElementById("stageBars"),
  queueCount: document.getElementById("queueCount"),
  queueList: document.getElementById("queueList"),
  detailPanel: document.getElementById("detailPanel"),
  statusFilter: document.getElementById("statusFilter"),
  mapWrap: document.getElementById("mapWrap"),
  siteName: document.getElementById("siteName"),
  sopPanel: document.getElementById("sopPanel"),
  sopList: document.getElementById("sopList"),
  sopCount: document.getElementById("sopCount"),
  auditList: document.getElementById("auditList"),
  auditCount: document.getElementById("auditCount"),
  reviewNote: document.getElementById("reviewNote")
};

const severityRank = { critical: 0, high: 1, medium: 2, low: 3 };
const sourceIcons = { camera: "cctv", detector: "siren", radio: "radio" };
const stageOrder = ["detect", "track", "rules", "fusion", "asr", "vlm"];

function api(path) {
  if (!state.mock) return path;
  if (path === "/api/ask") return "mock/ask.json";
  if (path === "/api/stats") return "mock/stats.json";
  if (path.startsWith("/api/site")) {
    const scenario = new URL(path, location.origin).searchParams.get("scenario") || "metro";
    return `mock/site_${scenario}.json`;
  }
  if (path === "/api/incidents" || path.startsWith("/api/incidents?")) return "mock/incidents.json";
  const match = path.match(/^\/api\/incidents\/([^/]+)/);
  return `mock/incident_${match[1]}.json`;
}

async function getJson(path) {
  const res = await fetch(api(path), { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

async function postJson(path, body) {
  if (state.mock) return getJson(path);
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

function fmtTime(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDateTime(ts) {
  return new Date(ts).toLocaleString([], {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
}

function relative(ts) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes}m ago` : `${Math.floor(minutes / 60)}h ago`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  })[c]);
}

function mediaFallback(label, message = "No media loaded") {
  return `<div class="media-placeholder"><div class="camera-icon" aria-hidden="true"></div><strong>${escapeHtml(message)}</strong><span>${escapeHtml(label)}</span></div>`;
}

function imgWithFallback(src, label, className = "") {
  if (!src) return mediaFallback(label);
  return `<img class="${className}" src="${escapeHtml(src)}" alt="${escapeHtml(label)}" data-fallback-label="${escapeHtml(label)}">`;
}

function evidenceVideo(incident) {
  return `<video src="${escapeHtml(incident.clip)}" controls autoplay muted loop playsinline data-keyframe="${escapeHtml(incident.keyframe || "")}" data-fallback-label="${escapeHtml(incident.id)}"></video>`;
}

function refreshIcons(root = document) {
  if (window.lucide?.createIcons) {
    window.lucide.createIcons({ attrs: { "stroke-width": 2 } });
  }
  bindInteractiveLinks(root);
}

function bindMediaFallbacks(root = document) {
  root.querySelectorAll("img[data-fallback-label]").forEach((img) => {
    img.addEventListener("error", () => {
      img.parentElement.innerHTML = mediaFallback(img.dataset.fallbackLabel);
    }, { once: true });
  });

  root.querySelectorAll("video[data-fallback-label]").forEach((video) => {
    video.addEventListener("error", () => {
      const label = video.dataset.fallbackLabel;
      const keyframe = video.dataset.keyframe;
      const parent = video.parentElement;
      if (!keyframe) {
        parent.innerHTML = mediaFallback(label, "Evidence clip unavailable");
        return;
      }
      parent.innerHTML = `<img src="${escapeHtml(keyframe)}" alt="${escapeHtml(label)}" data-fallback-label="${escapeHtml(label)}" data-evidence-fallback="clip">`;
      const img = parent.querySelector("img");
      img.addEventListener("error", () => {
        parent.innerHTML = mediaFallback(label, "Evidence clip unavailable");
      }, { once: true });
    }, { once: true });
  });
}

function filteredIncidents() {
  return state.incidents.filter((incident) => {
    const scenarioOk = state.scenario === "all" || incident.scenario === state.scenario;
    const statusOk = state.status === "all" || incident.status === state.status;
    return scenarioOk && statusOk;
  }).sort((a, b) => {
    const sev = (severityRank[a.priority] ?? 9) - (severityRank[b.priority] ?? 9);
    if (sev) return sev;
    return new Date(b.start_ts) - new Date(a.start_ts);
  });
}

function stateLabel(status) {
  return { pending: "NEW", confirmed: "CONFIRMED", escalated: "ESCALATED", dismissed: "DISMISSED" }[status] || String(status).toUpperCase();
}

function priorityLabel(priority) {
  return priority === "critical" ? "HIGH" : String(priority || "low").toUpperCase();
}

function priorityColor(priority) {
  return `var(--sev-${priority === "critical" ? "critical" : priority || "low"})`;
}

function priorityBg(priority) {
  const p = priority === "critical" ? "critical" : priority || "low";
  return `rgba(${p === "critical" ? "240,68,56" : p === "high" ? "247,144,9" : p === "medium" ? "234,179,8" : "59,130,246"},.18)`;
}

function addHistory(stats) {
  const last = state.history.at(-1);
  if (!last || last.signals !== stats.signals_total || last.incidents !== stats.incidents_total) {
    state.history.push({ signals: stats.signals_total, incidents: stats.incidents_total });
    state.history = state.history.slice(-18);
  }
}

function sparkPath(values, width, height) {
  if (!values.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  return values.map((value, idx) => {
    const x = values.length === 1 ? 0 : (idx / (values.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 6) - 3;
    return `${idx ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
}

function renderSparkline() {
  const series = state.history.length ? state.history : [{ signals: 0, incidents: 0 }];
  const signals = sparkPath(series.map((p) => p.signals), 164, 48);
  const incidents = sparkPath(series.map((p) => p.incidents), 164, 48);
  els.kpiSparkline.innerHTML = `<path class="signals" d="${signals}"></path><path class="incidents" d="${incidents}"></path>`;
}

function renderStats() {
  const stats = state.stats;
  if (!stats) return;
  addHistory(stats);
  els.kpiSignals.textContent = stats.signals_total;
  els.kpiIncidents.textContent = stats.incidents_total;
  els.kpiReduction.textContent = `${Math.round(stats.alert_reduction * 100)}%`;
  const pending = stats.by_status?.pending ?? 0;
  els.kpiPending.textContent = pending;
  els.kpiPending.classList.toggle("pending-warn", pending > 0);
  renderSparkline();
  const pipe = stats.pipeline || {};
  els.pipelineChip.innerHTML = `<span class="live-dot"></span><span>EDGE · LIVE · ${escapeHtml(pipe.device)} · ${escapeHtml(pipe.detector)} · ${Number(pipe.fps || 0).toFixed(1)} fps · ${escapeHtml(pipe.target)}</span>`;
  els.privacyBadge.textContent = `Frames off-box: ${pipe.frames_off_box ?? "--"} · Retention ${pipe.retention_h ?? "--"} h`;
  renderStageBars(pipe.stage_ms || {});
}

function renderStageBars(stageMs) {
  const entries = stageOrder
    .filter((stage) => stageMs[stage] !== undefined && stageMs[stage] !== null)
    .map((stage) => [stage, Number(stageMs[stage])]);
  if (!entries.length) {
    els.stageBars.innerHTML = `<span class="stage-empty">Awaiting pipeline telemetry</span>`;
    return;
  }
  const max = Math.max(...entries.map(([, ms]) => ms), 1);
  els.stageBars.innerHTML = entries.map(([stage, ms]) => `
    <div class="stage" title="${escapeHtml(stage)} ${ms.toFixed(ms >= 10 ? 0 : 1)} ms">
      <span>${escapeHtml(stage)}</span>
      <div class="stage-track"><div class="stage-fill" style="width:${Math.max(3, (ms / max) * 100).toFixed(1)}%"></div></div>
      <strong class="mono">${ms.toFixed(ms >= 10 ? 0 : 1)}</strong>
    </div>
  `).join("");
}

function syncMockStats() {
  if (!state.mock || !state.stats) return;
  const byStatus = { pending: 0, confirmed: 0, dismissed: 0, escalated: 0 };
  state.incidents.forEach((incident) => {
    byStatus[incident.status] = (byStatus[incident.status] || 0) + 1;
  });
  state.stats.by_status = byStatus;
}

function renderQueue() {
  const list = filteredIncidents();
  els.queueCount.textContent = `${list.length} visible · ${state.incidents.length} total`;
  els.queueList.innerHTML = list.map((incident) => `
    <button class="incident-card ${incident.id === state.selectedId ? "selected" : ""} ${incident.status !== "pending" ? "reviewed" : ""} ${incident.status === "pending" ? "rail-flash" : ""}" data-id="${escapeHtml(incident.id)}" data-severity="${escapeHtml(incident.priority)}" data-zones="${escapeHtml(incident.zones.join(","))}">
      <div class="thumb" data-sensor="${escapeHtml(incident.sensors?.[0] || incident.id)}">${imgWithFallback(incident.keyframe, incident.id)}</div>
      <div class="incident-card-body">
        <div class="incident-title">${escapeHtml(incident.title)}</div>
        <div class="incident-meta">
          <span class="chip priority-chip">${priorityLabel(incident.priority)}</span>
          <span class="chip state-chip ${state.changedStatusId === incident.id ? "changed" : ""}" data-status="${escapeHtml(incident.status)}"><i data-lucide="${incident.status === "pending" ? "circle-dot" : "check"}"></i>${stateLabel(incident.status)}</span>
          <span>${escapeHtml(incident.zones.join(" · "))}</span>
          <span>${incident.n_signals} signals</span>
          <span>${relative(incident.start_ts)}</span>
        </div>
      </div>
    </button>
  `).join("");
  bindMediaFallbacks(els.queueList);
  refreshIcons(els.queueList);
}

function signalOffset(incident, signal) {
  const delta = (new Date(signal.ts) - new Date(incident.start_ts)) / 1000;
  return `+${delta.toFixed(1)}s`;
}

function summaryLatency(incident) {
  return Math.round(520 + (incident.signals?.length || incident.n_signals || 1) * 54 + (incident.score || 0) * 31);
}

function citationChip(id, incidentId = "") {
  const type = id.startsWith("INC-") ? "incident" : "signal";
  const incidentAttr = incidentId ? ` data-incident-id="${escapeHtml(incidentId)}"` : "";
  return `<button class="citation-chip mono" data-citation="${escapeHtml(id)}" data-citation-type="${type}"${incidentAttr} title="Show ${escapeHtml(id)}">${escapeHtml(id)}</button>`;
}

function renderCitedText(text, incidentId = "") {
  return escapeHtml(text).replace(/\[(SIG-[^\]\s]+|INC-[^\]\s]+)\]/g, (_, id) => citationChip(id, incidentId));
}

function hasVlmAudit(incident) {
  return (incident.audit || []).some((item) => item.actor === "vlm");
}

function renderVlm(incident) {
  const vlm = incident.vlm;
  if (!vlm) return "";
  const opinion = vlm.second_opinion ? `
    <div class="vlm-opinion">
      <span>Second opinion: ${escapeHtml(vlm.second_opinion.answer)}</span>
      <span class="chip ${vlm.second_opinion.benign ? "ok-chip" : "dim-chip"}">${vlm.second_opinion.benign ? "BENIGN" : "NO BENIGN EXPLANATION"}</span>
    </div>
  ` : "";
  const auditNote = hasVlmAudit(incident)
    ? `<div class="vlm-note">Priority adjusted by VLM — operator can override</div>`
    : "";
  return `
    <section class="vlm-block">
      <div class="vlm-title"><i data-lucide="scan-eye"></i><span>Scene check · ${escapeHtml(vlm.model)} · ${Number(vlm.ms || 0).toFixed(0)} ms</span></div>
      <blockquote>"${escapeHtml(vlm.description)}"</blockquote>
      ${opinion}
      ${auditNote}
    </section>
  `;
}

function askMarkup() {
  const askIncidentId = state.ask.result?.citations?.find((id) => String(id).startsWith("INC-")) || "";
  const answer = state.ask.result ? `
    <section class="ask-answer">
      <p>${renderCitedText(state.ask.result.answer, askIncidentId)}</p>
      <div class="ask-meta mono">${escapeHtml(state.ask.result.model)} · ${Number(state.ask.result.ms || 0).toFixed(0)} ms · on-device</div>
    </section>
  ` : "";
  const error = state.ask.error ? `<div class="ask-error">${escapeHtml(state.ask.error)}</div>` : "";
  return `
    <section class="ask-box ${state.ask.loading ? "loading" : ""}">
      <form id="askForm" class="ask-form">
        <i data-lucide="message-square-text"></i>
        <input id="askInput" type="text" placeholder="Ask the station… e.g. anything near Exit C?" autocomplete="off" value="${escapeHtml(state.ask.draft)}" ${state.ask.loading ? "disabled" : ""}>
      </form>
      ${state.ask.loading ? `<div class="ask-shimmer"></div>` : ""}
      ${answer}
      ${error}
    </section>
  `;
}

function renderDetail(incident) {
  const features = incident.features && Object.keys(incident.features).length
    ? `<div class="features">${Object.entries(incident.features).map(([key, val]) => `
      <div class="metric"><span>${escapeHtml(key.replaceAll("_", " "))}</span><strong class="mono">${escapeHtml(val)}</strong></div>
    `).join("")}</div>` : "";
  const media = incident.clip
    ? evidenceVideo(incident)
    : imgWithFallback(incident.keyframe, incident.id);
  const sensors = incident.sensors || [...new Set((incident.signals || []).map((sig) => sig.sensor))];

  els.detailPanel.innerHTML = `
    ${askMarkup()}
    <div class="detail-head">
      <div class="detail-title">
        <h2>${escapeHtml(incident.title)}</h2>
        <div class="where-when">
          <span><span class="meta-label">Zone</span> ${escapeHtml(incident.zones.join(" / "))}</span>
          <span><span class="meta-label">Sensor</span> ${escapeHtml(sensors.join(" / "))}</span>
          <span><span class="meta-label">When</span> ${escapeHtml(fmtDateTime(incident.start_ts))} · ${escapeHtml(relative(incident.start_ts))}</span>
          <span class="chip state-chip ${state.changedStatusId === incident.id ? "changed" : ""}" data-status="${escapeHtml(incident.status)}"><i data-lucide="${incident.status === "pending" ? "circle-dot" : "check"}"></i>${stateLabel(incident.status)}</span>
        </div>
      </div>
      <div class="score-wrap">
        <div class="incident-meta">AI score <span class="mono">${Math.round(incident.score * 100)}%</span></div>
        <div class="score-track"><div class="score-fill" style="width:${Math.round(incident.score * 100)}%"></div></div>
      </div>
    </div>
    <div class="evidence-media" style="--sev:${priorityColor(incident.priority)}"><div class="severity-strip"></div>${media}</div>
    <section class="summary-block">
      <div class="summary-top"><div class="summary-label"><i data-lucide="sparkles"></i>On-device summary</div><span class="latency-tag mono">Edge · ${summaryLatency(incident)} ms</span></div>
      <p data-summary-text="${escapeHtml(incident.summary)}"></p>
      ${renderVlm(incident)}
    </section>
    ${features}
    <section class="timeline">
      ${incident.signals.map((sig, idx) => `
        <article class="signal ${sig.kind === "scene_check" ? "scene-check" : ""}" data-zone="${escapeHtml(sig.zone)}" data-source="${escapeHtml(sig.source)}" data-signal-id="${escapeHtml(sig.id)}" data-kind="${escapeHtml(sig.kind)}" style="animation-delay:${idx * 60}ms">
          <div class="signal-top">
            <span class="signal-source"><i data-lucide="${sig.kind === "scene_check" ? "camera" : sourceIcons[sig.source] || "radio-receiver"}"></i>${escapeHtml(sig.source)} · ${escapeHtml(sig.sensor)} · zone ${escapeHtml(sig.zone)}${sig.kind === "scene_check" ? ` <span class="chip snapshot-chip">SNAPSHOT</span>` : ""}</span>
            <span class="mono">${signalOffset(incident, sig)} · ${Math.round(sig.confidence * 100)}%</span>
          </div>
          <div class="signal-detail">${escapeHtml(sig.kind)} · ${escapeHtml(sig.detail)}</div>
          ${sig.transcript ? `<div class="transcript">"${escapeHtml(sig.transcript)}"</div>` : ""}
        </article>
      `).join("")}
    </section>
  `;
  bindMediaFallbacks(els.detailPanel);
  refreshIcons(els.detailPanel);
  bindAskForm();
  typeSummary();
  els.reviewNote.value = incident.review?.note || "";
  renderSop(incident);
  renderAudit(incident);
}

function typeSummary() {
  const block = els.detailPanel.querySelector(".summary-block");
  const target = els.detailPanel.querySelector("[data-summary-text]");
  if (!target) return;
  const text = target.dataset.summaryText || "";
  const html = renderCitedText(text);
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    target.innerHTML = html;
    block?.classList.add("ready");
    bindCitationLinks(target);
    return;
  }
  target.innerHTML = html;
  block?.classList.add("ready");
  bindCitationLinks(target);
}

function renderAudit(incident) {
  const audit = incident?.audit || [];
  els.auditCount.textContent = `${audit.length} events`;
  els.auditList.innerHTML = audit.map((item, idx) => `<li style="animation-delay:${idx === audit.length - 1 && audit.length > state.lastAuditCount ? "0ms" : "0ms"}"><time>${fmtTime(item.ts)}</time><span class="actor">${escapeHtml(item.actor)}</span><span>${escapeHtml(item.action)}</span></li>`).join("");
  state.lastAuditCount = audit.length;
}

function renderSop(incident) {
  const steps = incident?.sop || [];
  els.sopPanel.hidden = !steps.length;
  els.sopCount.textContent = steps.length ? `${steps.length} local checklist items` : "No recommended steps";
  if (!steps.length) {
    els.sopList.innerHTML = "";
    return;
  }
  let checks = state.sopChecks.get(incident.id);
  if (!checks) {
    checks = new Set();
    state.sopChecks.set(incident.id, checks);
  }
  els.sopList.innerHTML = steps.map((step, idx) => `
    <li>
      <label>
        <input type="checkbox" data-sop-index="${idx}" ${checks.has(idx) ? "checked" : ""}>
        <span>${escapeHtml(step)}</span>
      </label>
    </li>
  `).join("");
}

function findLoadedIncidentBySignal(signalId) {
  for (const incident of state.details.values()) {
    if ((incident.signals || []).some((sig) => sig.id === signalId)) return incident;
  }
  const selected = state.details.get(state.selectedId);
  if ((selected?.signals || []).some((sig) => sig.id === signalId)) return selected;
  return null;
}

function citationIncidentId(id, explicitIncidentId) {
  if (id.startsWith("INC-")) return id;
  if (explicitIncidentId) return explicitIncidentId;
  const loaded = findLoadedIncidentBySignal(id);
  return loaded?.id || state.selectedId;
}

async function activateCitation(id, options = {}) {
  const incidentId = citationIncidentId(id, options.incidentId);
  if (!incidentId) return;
  if (id.startsWith("INC-")) {
    await selectIncident(incidentId);
    return;
  }
  if (state.selectedId !== incidentId) await selectIncident(incidentId);
  state.activeCitation = id;
  highlightCitation(id);
}

function highlightCitation(id) {
  document.querySelectorAll(".signal.citation-active").forEach((el) => el.classList.remove("citation-active"));
  const row = document.querySelector(`.signal[data-signal-id="${CSS.escape(id)}"]`);
  if (!row) return;
  row.classList.add("citation-active");
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  setHoverZone(row.dataset.zone);
  setTimeout(() => {
    if (state.activeCitation === id) setHoverZone(null);
  }, 1400);
}

function center(zone) {
  return { x: (zone.x + zone.w / 2) * 1000, y: (zone.y + zone.h / 2) * 700 };
}

function truncateSvgText(value, maxChars) {
  const text = String(value ?? "");
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 1))}…`;
}

async function renderMap(incident) {
  if (!incident) return;
  let site = state.sites.get(incident.scenario);
  if (!site) {
    site = await getJson(`/api/site?scenario=${incident.scenario}`);
    state.sites.set(incident.scenario, site);
  }
  els.siteName.textContent = site.name;
  const zonesById = new Map(site.zones.map((z) => [z.id, z]));
  const active = new Set(incident.zones);
  const zoneColor = priorityColor(incident.priority);
  const zoneBg = priorityBg(incident.priority);
  const lines = site.adjacency.map(([a, b]) => {
    const za = center(zonesById.get(a));
    const zb = center(zonesById.get(b));
    return `<line class="adjacency" x1="${za.x}" y1="${za.y}" x2="${zb.x}" y2="${zb.y}"></line>`;
  }).join("");
  const zones = site.zones.map((z) => {
    const x = z.x * 1000;
    const y = z.y * 700;
    const width = z.w * 1000;
    const height = z.h * 700;
    const labelChars = Math.max(6, Math.floor((width - 36) / 15));
    const cameraChars = Math.max(6, Math.floor((width - 36) / 10));
    const clipId = `clip-${String(z.id).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
    return `
    <g>
      <clipPath id="${clipId}"><rect x="${x + 14}" y="${y + 12}" width="${Math.max(0, width - 28)}" height="${Math.max(0, height - 24)}"></rect></clipPath>
      <rect class="zone ${active.has(z.id) ? "active" : ""} ${state.hoveredZone === z.id ? "hovered" : ""}" data-zone="${escapeHtml(z.id)}" style="--zone-color:${zoneColor};--zone-bg:${zoneBg}" x="${x}" y="${y}" width="${width}" height="${height}" rx="10"></rect>
      <rect class="zone-ring ${active.has(z.id) ? "active" : ""}" style="--zone-color:${zoneColor}" x="${x - 6}" y="${y - 6}" width="${width + 12}" height="${height + 12}" rx="14"></rect>
      <g clip-path="url(#${clipId})">
        <text class="zone-label" x="${x + 20}" y="${y + 45}">${escapeHtml(truncateSvgText(`${z.id} · ${z.name}`, labelChars))}</text>
        <text class="camera-label" x="${x + 20}" y="${y + 78}">${escapeHtml(truncateSvgText(z.cameras.join(", "), cameraChars))}</text>
      </g>
    </g>
  `;
  }).join("");
  els.mapWrap.innerHTML = `<svg class="map-svg" viewBox="0 0 1000 700" preserveAspectRatio="xMidYMid meet">${lines}${zones}</svg>`;
  bindInteractiveLinks(els.mapWrap);
}

async function selectIncident(id) {
  state.selectedId = id;
  let incident = state.details.get(id);
  if (!incident) {
    incident = await getJson(`/api/incidents/${id}`);
    state.details.set(id, incident);
  }
  renderQueue();
  renderDetail(incident);
  await renderMap(incident);
  refreshIcons();
}

async function refresh() {
  try {
    const params = new URLSearchParams();
    if (!state.mock && state.scenario !== "all") params.set("scenario", state.scenario);
    if (!state.mock && state.status !== "all") params.set("status", state.status);
    const suffix = params.toString() ? `?${params}` : "";
    const [incidents, stats] = await Promise.all([getJson(`/api/incidents${suffix}`), getJson("/api/stats")]);
    if (state.mock) {
      incidents.forEach((incident) => {
        const override = state.mockReviews.get(incident.id);
        if (override) incident.status = override.status;
      });
    }
    state.incidents = incidents.sort((a, b) => {
      const sev = (severityRank[a.priority] ?? 9) - (severityRank[b.priority] ?? 9);
      if (sev) return sev;
      return new Date(b.start_ts) - new Date(a.start_ts);
    });
    state.stats = stats;
    syncMockStats();
    if (!state.selectedId || !state.incidents.some((i) => i.id === state.selectedId)) {
      state.selectedId = filteredIncidents()[0]?.id || state.incidents[0]?.id || null;
    }
    renderStats();
    renderQueue();
    if (state.selectedId) await selectIncident(state.selectedId);
  } catch (err) {
    els.queueCount.textContent = `Feed error: ${err.message}`;
  }
}

async function review(decision) {
  if (!state.selectedId) return;
  const note = els.reviewNote.value.trim();
  if (state.mock) {
    const incident = state.details.get(state.selectedId);
    const ts = new Date().toISOString().slice(0, 19);
    incident.status = decision;
    incident.review = { decision, reviewer: "operator-1", note, ts };
    incident.audit = [...(incident.audit || []), { ts, actor: "operator-1", action: `${decision} incident${note ? `: ${note}` : ""}` }];
    state.changedStatusId = incident.id;
    state.mockReviews.set(incident.id, { status: decision });
    const summary = state.incidents.find((item) => item.id === incident.id);
    if (summary) summary.status = decision;
    syncMockStats();
    renderStats();
    renderQueue();
    renderDetail(incident);
    setTimeout(() => {
      if (state.changedStatusId === incident.id) state.changedStatusId = null;
      renderQueue();
      renderDetail(incident);
    }, 320);
    return;
  }
  const res = await fetch(`/api/incidents/${state.selectedId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note, reviewer: "operator-1" })
  });
  const updated = await res.json();
  state.details.set(updated.id, updated);
  await refresh();
}

function moveSelection(step) {
  const list = filteredIncidents();
  if (!list.length) return;
  const idx = Math.max(0, list.findIndex((i) => i.id === state.selectedId));
  const next = list[(idx + step + list.length) % list.length];
  selectIncident(next.id);
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab === button));
    state.scenario = button.dataset.scenario;
    renderQueue();
    const first = filteredIncidents()[0];
    if (first) selectIncident(first.id);
  });
});

function setHoverZone(zone) {
  state.hoveredZone = zone;
  document.querySelectorAll("[data-zone], [data-zones]").forEach((el) => {
    const zones = (el.dataset.zone || el.dataset.zones || "").split(",");
    el.classList.toggle("linked", Boolean(zone && zones.includes(zone)));
    el.classList.toggle("hovered", Boolean(zone && zones.includes(zone)));
  });
}

function bindInteractiveLinks(root = document) {
  root.querySelectorAll(".signal[data-zone], .zone[data-zone], .incident-card[data-zones]").forEach((el) => {
    if (el.dataset.hoverBound) return;
    el.dataset.hoverBound = "1";
    const zoneValue = el.dataset.zone || (el.dataset.zones || "").split(",")[0];
    el.addEventListener("mouseenter", () => setHoverZone(zoneValue));
    el.addEventListener("mouseleave", () => setHoverZone(null));
  });
  bindCitationLinks(root);
}

function bindCitationLinks(root = document) {
  root.querySelectorAll(".citation-chip[data-citation]").forEach((chip) => {
    if (chip.dataset.citationBound) return;
    chip.dataset.citationBound = "1";
    const incidentId = chip.dataset.incidentId;
    const run = () => activateCitation(chip.dataset.citation, { incidentId });
    chip.addEventListener("mouseenter", run);
    chip.addEventListener("focus", run);
    chip.addEventListener("click", (event) => {
      event.preventDefault();
      run();
    });
  });
}

function bindAskForm() {
  const form = document.getElementById("askForm");
  const input = document.getElementById("askInput");
  if (!form || !input || form.dataset.askBound) return;
  form.dataset.askBound = "1";
  input.addEventListener("input", () => {
    state.ask.draft = input.value;
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || state.ask.loading) return;
    state.ask = { loading: true, result: null, error: null, draft: question };
    renderDetail(state.details.get(state.selectedId));
    try {
      const result = await postJson("/api/ask", { question });
      state.ask = { loading: false, result, error: null, draft: question };
    } catch (err) {
      state.ask = { loading: false, result: null, error: err.message, draft: question };
    }
    renderDetail(state.details.get(state.selectedId));
  });
}

els.statusFilter.addEventListener("change", () => {
  state.status = els.statusFilter.value;
  renderQueue();
  const first = filteredIncidents()[0];
  if (first) selectIncident(first.id);
});

els.queueList.addEventListener("click", (event) => {
  const card = event.target.closest(".incident-card");
  if (card) selectIncident(card.dataset.id);
});

document.querySelectorAll("[data-review]").forEach((button) => {
  button.addEventListener("click", () => review(button.dataset.review));
});

els.sopList.addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-sop-index]");
  if (!checkbox || !state.selectedId) return;
  let checks = state.sopChecks.get(state.selectedId);
  if (!checks) {
    checks = new Set();
    state.sopChecks.set(state.selectedId, checks);
  }
  const idx = Number(checkbox.dataset.sopIndex);
  if (checkbox.checked) checks.add(idx);
  else checks.delete(idx);
});

document.addEventListener("keydown", (event) => {
  if (event.target.matches("textarea, input, select")) return;
  if (event.key === "j") moveSelection(1);
  if (event.key === "k") moveSelection(-1);
  if (event.key === "c") review("confirmed");
  if (event.key === "e") review("escalated");
  if (event.key === "d") review("dismissed");
});

setInterval(() => {
  els.clock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}, 250);

refresh();
setInterval(refresh, 2000);
