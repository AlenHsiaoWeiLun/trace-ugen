# VESTIGE deck — design rationale (Phase 1)

**Direction: "forensic editorial."** A product launch that reads like a case file. Cinematic night imagery
for the human story, precise editorial pages for the argument, utilitarian tables where judges need facts.

- **Three densities** (per brief): cinematic (cover, p.2, closing), editorial (problem, product, capabilities),
  technical (architecture, differentiation, hardware, status, market, pilot, roadmap). 17 main pages + 4 appendix.
- **Type:** Instrument Serif (display; editorial, slightly cinematic), Inter (text), IBM Plex Mono (timestamps,
  evidence labels — the "machine voice"). Minimum 24 px everywhere so a judge reading alone can parse every label.
- **Color:** ink `#0E0F12` and bone `#ECE7DE` as the two grounds; one accent, evidence amber `#E0A33B`
  (light-ground variant `#8A5A10`). Amber only marks evidence: frames, chips, the inferred link, key numbers.
  Chart pair cyan `#2D97B5` / amber `#C4851E` validated for CVD separation and contrast.
- **Evidence grammar reused everywhere:** solid frame = observed; dashed = inferred/unknown; hatched = no coverage.
  The same grammar is the planned product UI, so deck, app and video share one visual language.
- **Honesty is designed in:** every generated image is labelled; every number carries a source or a script;
  status words (Built / Partial / Phase 2 / Stage II / Pilot measured) are consistent across p.11–16.

## Process
1. Research agents verified every news fact (NTU notice, CNA Metro briefing, MOL fatalities, CNA roller case),
   checked the brand (VESTIGE conflicts found — see summary) and mapped competitors.
2. Original imagery generated with OpenAI's image model via Codex (bike present/gone pair edited from one frame).
3. IncidentLab pilot run for real (`scripts/incidentlab_pilot.py`) to give VERIFY measured results.
4. Rendered every page, inspected, then an adversarial Codex review of the rendered pages; fixes applied
   (status clarity, hardware columns, softened competitor table, cost anchor, earlier trust message).
