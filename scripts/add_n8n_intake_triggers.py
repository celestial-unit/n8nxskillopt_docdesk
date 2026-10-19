"""Add credential-gated Gmail and Drive intake branches to the n8n export."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "n8n/pipeline_workflow.json"
P = "n8n-nodes-base."

def node(name, kind, params, x, y, version=1, **extra):
    return {"parameters": params, "id": f"docdesk-{name.lower().replace(' ', '-')}",
            "name": name, "type": P + kind, "typeVersion": version,
            "position": [x, y], **extra}

def main():
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    existing = {n["name"] for n in workflow["nodes"]}
    nodes = [
        node("Gmail · Invoice Attachments", "gmailTrigger", {
            "pollTimes": {"item": [{"mode": "everyMinute"}]},
            "simple": False,
            "filters": {"q": "label:docdesk has:attachment {filename:pdf filename:png filename:jpg filename:jpeg filename:webp}"},
            "options": {"downloadAttachments": True, "dataPropertyAttachmentsPrefixName": "attachment_"},
        }, 180, 820, 1.4, disabled=True),
        node("Normalize Email Attachments", "code", {"mode": "runOnceForAllItems", "jsCode": '''const out = [];
const allowed = new Set(["pdf", "png", "jpg", "jpeg", "webp"]);
for (let i = 0; i < $input.all().length; i++) {
  const item = $input.all()[i];
  for (const [key, meta] of Object.entries(item.binary || {})) {
    const filename = meta.fileName || key;
    const ext = filename.split(".").pop().toLowerCase();
    if (!allowed.has(ext)) continue;
    const buffer = await this.helpers.getBinaryDataBuffer(i, key);
    const clean = String(item.json.id || Date.now()).replace(/[^a-zA-Z0-9_-]/g, "");
    out.push({json: {body: {doc_id: `email-${clean}-${key}`, company_id: "company_b", filename, file_b64: buffer.toString("base64"), source: "email"}}});
  }
}
return out;'''}, 440, 820, 2),
        node("Google Drive · New File", "googleDriveTrigger", {
            "pollTimes": {"item": [{"mode": "everyMinute"}]},
            "triggerOn": "specificFolder",
            "folderToWatch": {"mode": "id", "value": "REPLACE_WITH_DRIVE_FOLDER_ID"},
            "event": "fileCreated",
            "options": {},
        }, 180, 1080, 1, disabled=True),
        node("Download Drive File", "googleDrive", {
            "resource": "file", "operation": "download",
            "fileId": {"mode": "id", "value": "={{$json.id}}"},
            "options": {"binaryPropertyName": "data"},
        }, 440, 1080, 3, disabled=True),
        node("Normalize Drive File", "code", {"mode": "runOnceForAllItems", "jsCode": '''const out = [];
const allowed = new Set(["pdf", "png", "jpg", "jpeg", "webp"]);
for (let i = 0; i < $input.all().length; i++) {
  const item = $input.all()[i];
  const meta = item.binary?.data;
  if (!meta) continue;
  const filename = meta.fileName || item.json.name || "drive-document.pdf";
  const ext = filename.split(".").pop().toLowerCase();
  if (!allowed.has(ext)) continue;
  const buffer = await this.helpers.getBinaryDataBuffer(i, "data");
  const clean = String(item.json.id || Date.now()).replace(/[^a-zA-Z0-9_-]/g, "");
  out.push({json: {body: {doc_id: `drive-${clean}`, company_id: "company_b", filename, file_b64: buffer.toString("base64"), source: "drive"}}});
}
return out;'''}, 680, 1080, 2),
    ]
    workflow["nodes"].extend(n for n in nodes if n["name"] not in existing)

    router = next(n for n in workflow["nodes"] if n["name"] == "2. Router (Deterministic)")
    code = router["parameters"]["jsCode"]
    if "source: body.source" not in code:
        code = code.replace("doc_id: body.doc_id, company_id: body.company_id, filename,", "doc_id: body.doc_id, company_id: body.company_id, source: body.source || 'webhook', filename,")
        router["parameters"]["jsCode"] = code
    logic = next(n for n in workflow["nodes"] if n["name"] == "7. Decision Logic")
    dcode = logic["parameters"]["jsCode"]
    if "source: $('2. Router (Deterministic)')" not in dcode:
        dcode = dcode.replace("doc_id: c.doc_id, company_id: c.company_id, extracted:", "doc_id: c.doc_id, company_id: c.company_id, source: $('2. Router (Deterministic)').first().json.source, extracted:")
        logic["parameters"]["jsCode"] = dcode

    # Webhook runs need an HTTP response; polling triggers must finish without
    # trying to respond to a nonexistent HTTP request.
    for label, source_node, response_node, y in [
        ("Escalated", "10a. Escalate", "11a. Respond ESCALATED", 400),
        ("Accepted", "9b. Accept", "11b. Respond ACCEPTED", 600),
        ("Failed", "Error. Fail", "11c. Respond FAILED", 800),
    ]:
        gate_name = f"{label} · Webhook response?"
        done_name = f"{label} · Intake complete"
        if gate_name not in {n["name"] for n in workflow["nodes"]}:
            workflow["nodes"].append(node(gate_name, "if", {
                "conditions": {"options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
                               "conditions": [{"id": f"docdesk-source-{label.lower()}",
                                               "leftValue": "={{ $('2. Router (Deterministic)').first().json.source }}",
                                               "rightValue": "webhook",
                                               "operator": {"type": "string", "operation": "equals"}}],
                               "combinator": "and"}, "options": {},
            }, 2180, y, 2.2))
            workflow["nodes"].append(node(done_name, "code", {
                "mode": "runOnceForAllItems",
                "jsCode": f"return [{{json: {{source: $('2. Router (Deterministic)').first().json.source, decision: '{label.upper()}'}}}}];",
            }, 2420, y + 90, 2))
        workflow["connections"][source_node]["main"][0][0]["node"] = gate_name
        workflow["connections"][gate_name] = {"main": [
            [{"node": response_node, "type": "main", "index": 0}],
            [{"node": done_name, "type": "main", "index": 0}],
        ]}

    workflow["connections"]["Gmail · Invoice Attachments"] = {"main": [[{"node": "Normalize Email Attachments", "type": "main", "index": 0}]]}
    workflow["connections"]["Normalize Email Attachments"] = {"main": [[{"node": "2. Router (Deterministic)", "type": "main", "index": 0}]]}
    workflow["connections"]["Google Drive · New File"] = {"main": [[{"node": "Download Drive File", "type": "main", "index": 0}]]}
    workflow["connections"]["Download Drive File"] = {"main": [[{"node": "Normalize Drive File", "type": "main", "index": 0}]]}
    workflow["connections"]["Normalize Drive File"] = {"main": [[{"node": "2. Router (Deterministic)", "type": "main", "index": 0}]]}
    WORKFLOW.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
