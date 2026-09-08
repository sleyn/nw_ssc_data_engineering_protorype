---
status: accepted
---

# Encrypt the app's runtime data store, not the source CSVs

The repo must stay clone-and-run reproducible for reviewers (part of the assignment's explicit ask), which rules out encrypting the committed CSVs — a reviewer without the key couldn't inspect the source data at all. Instead, the raw CSVs stay plaintext in the repo, and the app's derived runtime data store (the cleaned/joined dataset it actually serves from) is what gets encrypted at rest, with the key supplied via deployment secrets. This keeps a real, explainable encryption-at-rest component (satisfying the literal-HIPAA-controls decision in [0001](./0001-hipaa-controls-with-public-demo-credentials.md)) without blocking reproducibility.
