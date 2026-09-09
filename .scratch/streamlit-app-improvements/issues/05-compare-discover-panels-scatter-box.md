# 05: Compare & Discover panels — scaffold + scatter/box

**What to build:** Replace Compare & Discover's multiselect-and-auto-combinations flow with user-managed comparison panels. A reviewer adds one panel per comparison they want, picks an X and a Y variable independently in each panel, and can rotate (swap) a panel's X/Y assignment. This ticket covers the full panel lifecycle plus the two most common chart-type pairings (scatter, box), both rendered in Plotly.

**Blocked by:** 01

**Status:** done

- [x] The Compare & Discover tab starts with 1 empty comparison panel already present.
- [x] A reviewer can add another comparison panel via an explicit control; there is no maximum on how many panels can be added.
- [x] A reviewer can remove any individual panel.
- [x] Each panel has its own independent X and Y variable select, both offering the full variable catalog (every demographic field, every longitudinal reading at both its per-Subject-summary and raw-over-time levels) — the same catalog the old multiselect used.
- [x] Panels, and each panel's own X/Y picks, survive reruns triggered by unrelated interactions elsewhere on the page (e.g. toggling a widget on a different panel or a different tab) — panel state does not reset itself.
- [x] If a panel's X and Y picks are the same variable, the panel shows a clear inline message instead of attempting to render a chart.
- [x] Each panel has a "rotate" control that swaps its X and Y picks in place.
- [x] The rotate control is present and enabled on every panel regardless of the panel's current chart type.
- [x] When a panel's X/Y picks resolve to a numeric-numeric pairing, it renders a scatter chart in Plotly, matching today's scatter behavior (including the Control Subject overlay toggle, shown only when at least one Control Subject has data for both picked variables).
- [x] When a panel's X/Y picks resolve to a numeric-categorical pairing, it renders a box plot in Plotly, matching today's box-plot behavior (including the Control Subject overlay toggle where meaningful).
- [x] Every chart rendered by a panel is a fixed 500px width, using the app-wide adaptive theme.
- [x] The underlying comparison-building logic (variable catalog, merge rules, chart-type selection) is reused unchanged from the existing comparison module — this ticket only replaces the Streamlit-facing selection/panel UI and the chart-drawing code, not the comparison logic itself.
- [x] Existing automated tests (`pytest`), type checks (`mypy`), and lint (`ruff`) all still pass; the comparison module's own existing tests are unaffected since its public interface doesn't change.
