#!/usr/bin/env bash
# n8n/import_and_activate.sh — Import, activate, and test the pipeline workflow.
# Usage: bash n8n/import_and_activate.sh

set -e

WORKFLOW_FILE="n8n/pipeline_workflow.json"

echo "=== Importing n8n workflow ==="
n8n import:workflow --input="$WORKFLOW_FILE"

echo ""
echo "=== Listing workflows to find the ID ==="
WORKFLOW_ID=$(n8n list:workflow 2>/dev/null | grep "Document Pipeline" | awk '{print $1}' | head -1)

if [ -z "$WORKFLOW_ID" ]; then
  echo "WARNING: Could not auto-detect workflow ID. Activate manually in the n8n UI."
else
  echo "Activating workflow ID: $WORKFLOW_ID"
  n8n update:workflow --id="$WORKFLOW_ID" --active=true || echo "Activation via CLI not supported in this n8n version — activate in UI."
fi

echo ""
echo "=== Test curl command ==="
echo "Run the following to test the webhook:"
echo ""
echo 'curl -X POST http://localhost:5678/webhook/pipeline \'
echo '  -H "Content-Type: application/json" \'
echo '  -d '"'"'{"doc_id":"test-001","company_id":"company_a","text":"FACTURE N° FAC-1234\nSTEG NIF: 00123456/A/M/000\nHTVA: 245,000 TND TVA 19%: 46,550 TND TTC: 291,550 TND Timbre: 0,600 TND"}'"'"

echo ""
echo "=== Exporting final workflow JSON ==="
if [ -n "$WORKFLOW_ID" ]; then
  n8n export:workflow --id="$WORKFLOW_ID" --output="$WORKFLOW_FILE" 2>/dev/null || echo "Export skipped (use n8n UI export)."
fi

echo "Done."
