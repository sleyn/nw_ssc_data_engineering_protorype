---
status: accepted
---

# Remove longitudinal_series ("... over time") variables from Compare & Discover

Two of the three pairings involving a `longitudinal_series` variable are broken: pairing it with a categorical variable falls back to a plain table (no chart), and pairing two `longitudinal_series` variables together degenerates into a near-empty 1x1 heatmap, because `build_comparison` joins on exact same-day `date` match and the resulting sparse frame gets misclassified as categorical data. The third pairing — a `longitudinal_series` variable against a numeric per-patient variable — does render correctly as a line chart.

We chose to remove `longitudinal_series` from the Compare & Discover variable picker entirely, rather than keep the one working pairing and suppress only the two broken ones. The working case still requires a user to correctly guess which of the three pairings is safe, with no signal in the picker itself distinguishing "will render" from "will render uselessly." Removing the level avoids a variable category that is selectable but only conditionally functional, at the cost of losing the one legitimate trend-line chart it enabled.

This does not affect Patient Trajectory's per-measure trend charts (`domain_series` / `_plot_measure_series`), which are a separate code path built specifically for single/multi-subject trajectories and were not exhibiting this bug.
