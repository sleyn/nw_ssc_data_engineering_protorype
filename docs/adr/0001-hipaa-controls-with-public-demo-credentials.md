---
status: proposed
---

# HIPAA-style controls implemented literally, gated by public demo credentials

The project's `CLAUDE.md` asks for HIPAA-compliant controls (encryption, authentication, audit logging), but the assignment states the dataset is synthetic/non-PHI and requires a publicly shareable app link and a public GitHub repo — a real access-control need and a "make it public" requirement in direct tension. The user chose to implement the controls literally (real login gate, real encryption at rest, real audit logging) rather than skip them, but to publish the login credentials (e.g. in the README) so reviewers can still access the demo without friction. Concrete mechanics of what "encryption at rest" protects, given the repo itself must be public, are still being worked out in the grilling session — this ADR records the shape of the decision, not yet its full implementation detail.
