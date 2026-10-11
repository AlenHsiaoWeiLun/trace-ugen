import { html } from "./ui.js";

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

