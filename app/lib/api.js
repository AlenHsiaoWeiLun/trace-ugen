// Thin API client. Every call is scoped to a workspace; errors surface with the server's message.
async function req(path, opts = {}) {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(`${r.status} · ${msg}`);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

export const api = {
  workspaces: () => req("/api/workspaces"),
  overview: (ws) => req(`/api/workspaces/${ws}/overview`),
  objects: (ws, q = "") => req(`/api/workspaces/${ws}/objects?q=${encodeURIComponent(q)}`),
  history: (oid) => req(`/api/objects/${oid}/history`),
  tracks: (ws) => req(`/api/workspaces/${ws}/tracks`),
  relations: (ws) => req(`/api/workspaces/${ws}/relations`),
  events: (ws) => req(`/api/workspaces/${ws}/events`),
  timeline: (eid, before = 60) => req(`/api/events/${eid}/timeline?before_s=${before}`),
  review: (eid, decision, note = "") => req(`/api/events/${eid}/review`, { method: "POST", body: JSON.stringify({ decision, note }) }),
  evidence: (id, ws) => req(`/api/evidence/${id}${ws ? `?ws=${ws}` : ""}`),
  coverage: (ws) => req(`/api/workspaces/${ws}/coverage`),
  audit: (ws) => req(`/api/workspaces/${ws}/audit`),
  ask: (ws, question, event_id = null) => req(`/api/workspaces/${ws}/ask`, { method: "POST", body: JSON.stringify({ question, event_id }) }),
  zones: (ws) => req(`/api/workspaces/${ws}/zones`),
  trackObs: (tid) => req(`/api/tracks/${tid}/observations`),
  checkin: (ws, body) => req(`/api/workspaces/${ws}/checkin`, { method: "POST", body: JSON.stringify(body) }),
  sources: (ws) => req(`/api/workspaces/${ws}/sources`),
  upload: async (ws, form) => {
    const r = await fetch(`/api/workspaces/${ws}/sources`, { method: "POST", body: form });
    if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail; } catch {} throw new Error(m); }
    return r.json();
  },
  job: (id) => req(`/api/jobs/${id}`),
  labOptions: () => req("/api/lab/options"),
  labList: (ws) => req(`/api/lab/experiments${ws ? `?ws=${ws}` : ""}`),
  labGet: (id) => req(`/api/lab/experiments/${id}`),
  labCreate: (body) => req("/api/lab/experiments", { method: "POST", body: JSON.stringify(body) }),
  labReport: (id) => req(`/api/lab/experiments/${id}/report.md`),
  metrics: () => req("/api/metrics"),
};

export async function pollJob(id, onTick, every = 700) {
  for (;;) {
    const j = await api.job(id);
    onTick && onTick(j);
    if (j.status === "done" || j.status === "failed") return j;
    await new Promise((r) => setTimeout(r, every));
  }
}
