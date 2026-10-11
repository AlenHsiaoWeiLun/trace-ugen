import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api } from "./lib/api.js";
import { html, Icon } from "./lib/ui.js";
import { AskPage } from "./pages/ask.js";
import { MemoryPage } from "./pages/memory.js";
import { InvestigatePage } from "./pages/investigate.js";
import { LabPage } from "./pages/lab.js";
import { SourcesPage } from "./pages/sources.js";
import { SettingsPage } from "./pages/settings.js";

const SHORT = { memory: "Memory", investigate: "Events", lab: "Lab" };
const NAV = [
  ["ask", "Ask", "ask", "1"], ["memory", "World Memory", "memory", "2"], ["investigate", "Investigations", "invest", "3"],
  ["lab", "IncidentLab", "lab", "4"], ["sources", "Sources", "sources", "5"], ["settings", "Settings", "settings", "6"],
];

function parseHash() {
  const [path, query] = (location.hash.slice(2) || "ask").split("?");
  const [page, ...rest] = path.split("/");
  return { page: page || "ask", arg: rest.join("/") || null, q: new URLSearchParams(query || "") };
}

export function go(page, arg, params) {
  const q = params ? "?" + new URLSearchParams(params).toString() : "";
  location.hash = `#/${page}${arg ? "/" + encodeURIComponent(arg) : ""}${q}`;
}

function App() {
  const [route, setRoute] = useState(parseHash());
  const [wss, setWss] = useState([]);
  const [ws, setWsState] = useState(() => {
    try { return localStorage.getItem("vestige.ws") || "campus"; } catch { return "campus"; }
  });
  const setWs = (id) => { setWsState(id); try { localStorage.setItem("vestige.ws", id); } catch {} };

  useEffect(() => {
    const f = () => setRoute(parseHash());
    addEventListener("hashchange", f);
    api.workspaces().then(setWss).catch(() => setWss([]));
    const keys = (e) => {
      if (e.target.matches("input, textarea, select")) return;
      const n = NAV.find((x) => x[3] === e.key);
      if (n && !e.metaKey && !e.ctrlKey) go(n[0]);
    };
    addEventListener("keydown", keys);
    return () => { removeEventListener("hashchange", f); removeEventListener("keydown", keys); };
  }, []);

  const qws = route.q.get("ws");
  useEffect(() => { if (qws && qws !== ws) setWs(qws); }, [qws]);
  const scenario = wss.filter((w) => !w.id.startsWith("bench"));
  const props = { ws, setWs, route, go, workspaces: wss };
  const Page = { ask: AskPage, memory: MemoryPage, investigate: InvestigatePage, lab: LabPage, sources: SourcesPage,
    settings: SettingsPage }[route.page] || AskPage;

  return html`<div class="shell">
    <aside class="side">
      <div class="brand"><div class="word">VESTIGE</div><div class="tag">The world leaves a trace.</div></div>
      <div class="ws"><span class="label">Workspace</span>
        <select value=${ws} onChange=${(e) => setWs(e.target.value)} aria-label="Workspace">
          ${scenario.map((w) => html`<option value=${w.id}>${w.name}</option>`)}
        </select></div>
      <nav class="nav">
        ${NAV.map(([id, label, icon, k]) => html`<a href=${`#/${id}`} class=${`${route.page === id ? "on" : ""} ${id === "settings" ? "hide-m" : ""}`}>
          <${Icon} name=${icon} /><span class="full">${label}</span><span class="short">${SHORT[id] || label}</span><span class="k">${k}</span></a>`)}
      </nav>
      <div class="side-foot">
        <div class="row"><span class="dot"></span><span>Edge pipeline · local</span></div>
        <div class="mono" style="font-size:11px">TRACE engine · target ASUS UGen300</div>
        <div style="font-size:11px">VESTIGE — an Archean project</div>
      </div>
    </aside>
    <main class="main"><${Page} ...${props} key=${route.page + ws} /></main>
  </div>`;
}

render(html`<${App} />`, document.getElementById("root"));
