#!/usr/bin/env bash
# Re-render slides.qmd to slides.html (revealjs) and slides.pdf (via decktape).
# Run from anywhere; paths are resolved relative to this script's location.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v quarto >/dev/null 2>&1; then
    export PATH="$HOME/.local/share/quarto/bin:$PATH"
fi
if ! command -v quarto >/dev/null 2>&1; then
    echo "quarto not found on PATH (checked \$HOME/.local/share/quarto/bin too)." >&2
    exit 1
fi

cd "$REPO_ROOT"
uv run quarto render presentation/slides.qmd --to revealjs

cd "$SCRIPT_DIR"
npx --yes decktape@3 reveal slides.html slides.pdf --size 1280x720

echo "Done: presentation/slides.html and presentation/slides.pdf"
