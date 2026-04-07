#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 \"<model name>\""
    exit 1
fi

MODEL="$1"

echo "==> Validating listings for: $MODEL (including sold)"
uv run reverb2odoo validate --include-sold --yes "$MODEL"

echo ""
echo "==> Syncing listings for: $MODEL (including brand new and sold)"
uv run reverb2odoo sync --include-sold --include-brand-new --yes "$MODEL"

echo ""
echo "==> Computing price brackets for: $MODEL"
uv run reverb2odoo compute-price-brackets --model "$MODEL"
