---
status: accepted
---

# Unify lab/vital/MRSS long-format tables internally, keep them distinct in the domain vocabulary

`lab_report.csv`, `vitals.csv`, and `mrss.csv` share an identical shape (component/category name + value, per patient per date), so the loader, QC checks, and trajectory-plotting code treat them as one generic Observation abstraction to avoid tripling near-duplicate logic. Deliberately not carried into CONTEXT.md, the QC report, or the app's UI: those keep Lab Result, Vital Sign, and MRSS/Skin Score as separate, named concepts, since a clinically-literate reviewer expects them distinguished. A future reader seeing one generic loader behind three distinct domain terms might otherwise "simplify" the vocabulary to match the code — this is recorded so they don't.
