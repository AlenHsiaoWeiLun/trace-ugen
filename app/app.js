import { render } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "./lib/api.js";
import { html, Icon } from "./lib/ui.js";
import { AskPage } from "./pages/ask.js";
import { LabPage } from "./pages/lab.js";
import { SourcesPage } from "./pages/sources.js";
import { SettingsPage } from "./pages/settings.js";

// One place for users: ask, read the answer, watch the footage. Admin and engineering pages live in the menu.
// Engineering and admin pages stay reachable but out of the user's way.
const MORE = [["sources", "Cameras & sources"], ["lab", "Detection lab"], ["settings", "Settings & data policy"]];

function parseHash() {
  const [path, query] = (location.hash.slice(2) || "ask").split("?");
  const [page, ...rest] = path.split("/");
  return { page: page || "ask", arg: rest.join("/") || null, q: new URLSearchParams(query || "") };
}

export function go(page, arg, params) {
  const q = params ? "?" + new URLSearchParams(params).toString() : "";
  location.hash = `#/${page}${arg ? "/" + encodeURIComponent(arg) : ""}${q}`;
}

function SiteSwitch({ ws, setWs, sites }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => {
    const f = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    addEventListener("pointerdown", f);
    return () => removeEventListener("pointerdown", f);
  }, []);
  const cur = sites.find((s) => s.id === ws);
  return html`<div class="menu" ref=${ref}>
    <button class="site" onClick=${() => setOpen(!open)} aria-haspopup="listbox" aria-expanded=${open}>
      <span class="live"></span><span>${cur?.name || ws}</span><${Icon} name="chev" size=${14} /></button>
    ${open ? html`<div class="pop" role="listbox">
      <div class="pop-h">Workspace</div>
      ${sites.map((s) => html`<button role="option" aria-selected=${s.id === ws} class=${s.id === ws ? "on" : ""}
          onClick=${() => { setWs(s.id); setOpen(false); }}>
        <b>${s.name}</b><span>${s.description}</span></button>`)}
    </div>` : null}
  </div>`;
}

function More({ page }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => {
    const f = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    addEventListener("pointerdown", f);
    return () => removeEventListener("pointerdown", f);
  }, []);
  return html`<div class="menu" ref=${ref}>
    <button class=${`iconbtn ${MORE.some((m) => m[0] === page) ? "on" : ""}`} onClick=${() => setOpen(!open)} aria-label="More"><${Icon} name="dots" size=${18} /></button>
    ${open ? html`<div class="pop right">${MORE.map(([id, label]) => html`<a href=${`#/${id}`} onClick=${() => setOpen(false)} class=${page === id ? "on" : ""}>${label}</a>`)}
      <div class="pop-foot">TRACE engine · target ASUS UGen300<br/>VESTIGE — an Archean project</div></div>` : null}
  </div>`;
}

function App() {
  const [route, setRoute] = useState(parseHash());
  const [wss, setWss] = useState([]);
  const [ws, setWsState] = useState(() => {
    try { return localStorage.getItem("vestige.site") || "construction"; } catch { return "construction"; }
  });
  const setWs = (id) => { setWsState(id); try { localStorage.setItem("vestige.site", id); } catch {} };

  useEffect(() => {
    const f = () => { setRoute(parseHash()); window.scrollTo(0, 0); };
    addEventListener("hashchange", f);
    api.workspaces().then(setWss).catch(() => setWss([]));
    return () => removeEventListener("hashchange", f);
  }, []);

  const qws = route.q.get("ws");
  useEffect(() => { if (qws && qws !== ws) setWs(qws); }, [qws]);
  const sites = wss.filter((w) => !w.id.startsWith("bench"));
  const props = { ws, setWs, route, go, workspaces: wss };
  // memory / investigate links from older screens resolve into the single answer view
  const Page = { lab: LabPage, sources: SourcesPage, settings: SettingsPage }[route.page] || AskPage;

  return html`<div class="app">
    <header class="top"><div class="top-in">
      <a class="logo" href="#/ask" aria-label="VESTIGE home"><svg viewBox="0 0 24 24" width="22" height="22"><path d="M5 6l7 13 7-13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>VESTIGE</span></a>
      <div class="top-r">${Page === AskPage ? null : html`<${SiteSwitch} ws=${ws} setWs=${setWs} sites=${sites} />`}<${More} page=${route.page} /></div>
    </div></header>
    <main class="main"><${Page} ...${props} key=${Page === AskPage ? "ask" + (route.q.get("q") || "") + (route.q.get("event") || route.arg || "") : route.page + ws} /></main>
  </div>`;
}

render(html`<${App} />`, document.getElementById("root"));
