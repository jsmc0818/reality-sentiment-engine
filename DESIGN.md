# Reality Engine: command dashboard

Adapted from **Romer Command Dashboard**, the screen selected by Dan in
[Remix of Romer Saas Dashboard](https://stitch.withgoogle.com/projects/18215519617237111178).
Source screen: `ecb152ece4094984be5b2c85419c5fcc`. Inspected September 8, 2026.

## Imported visual structure

- Fixed desktop sidebar, active row with a cyan edge, secondary resource links, violet primary action.
- Three compact metric panels across the top.
- A large graph beside a narrow signal list, followed by detailed tables and research panels.
- Dark, flat surfaces, fine borders, small corner radii, tabular figures, restrained labels.
- Inter for data and body text; Manrope for headings.

Source colors retained: page `#131314`, sidebar `#0e0e0f`, panels `#101112`,
graph `#151617`, border `#232426`, text `#e5e2e3`, cyan `#50d8e9`,
violet `#7a85ff`, primary button `#5e6bff`, caution `#ffb689`, risk `#ffb4ab`.

## Product adaptation

Romer's uptime, latency and incident counters become dated index panic and EPS-revision readings.
Its telemetry graph becomes the existing opportunity map; service status becomes seven company research setups.
The finance model, evidence rules, company coverage and scheduled collection remain unchanged.
All outputs use the existing published observations. No Romer demo data or simulated activity is shipped.

Native CSS replaces the export's Tailwind CDN dependency. Inline SVGs replace the icon-font dependency.
Stitch editor scripts, demo avatar, disabled focus rings, forced viewport height and hidden scrollbars are omitted.
Mobile navigation uses a horizontal rail; tables scroll within their panel. About and methodology remain accessible.
The original design is adapted to a working research dashboard, not embedded as an iframe.
