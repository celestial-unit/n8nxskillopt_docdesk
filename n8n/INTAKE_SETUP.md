# Email and Drive intake

`pipeline_workflow.json` contains three intake paths that converge on the same
document pipeline:

- `POST /webhook/pipeline` for direct API/webhook submissions
- Gmail attachments under the `docdesk` label
- New PDF/image files in one watched Google Drive folder

All paths normalize a document to `{doc_id, company_id, filename, file_b64,
source}` and then run routing, OCR/extraction, RAG coding, validation, and the
final decision. Polling sources end normally; only webhook submissions send an
HTTP response.

## Connect Gmail and Drive

1. In n8n, create Google OAuth2 credentials for **Gmail OAuth2 API** and
   **Google Drive OAuth2 API**. The local n8n instance currently has no Gmail
   or Drive credentials, so both polling triggers and the Drive download node
   are imported disabled.
2. Assign the Gmail credential to `Gmail · Invoice Attachments`. Apply the
   `docdesk` label to the mailbox messages that should be processed. The query
   accepts PDF, PNG, JPG, JPEG, and WEBP attachments.
3. Assign the Drive credential to both `Google Drive · New File` and
   `Download Drive File`. Set the trigger folder to the ID of the folder to
   watch, then enable the trigger and download node.
4. Enable the Gmail trigger. Keep both sources pointed at the intended company
   by editing `company_id` in the matching normalize node (currently
   `company_b`).
5. Send one test email and upload one test file. Confirm each execution reaches
   the router and appears in DocDesk's stored-document ledger.

The workflow is imported into the local n8n instance. Its webhook path is
`/webhook/pipeline`; the Gmail and Drive nodes stay disabled until OAuth and a
Drive folder ID are supplied. n8n credentials are stored in the local n8n
instance and are intentionally not embedded in the export.

## Re-import after editing

From the repository root:

```bash
n8n import:workflow --input=n8n/pipeline_workflow.json
n8n update:workflow --id=a1b2c3d4-e5f6-7890-abcd-ef1234567890 --active=true
```

`company_id` is currently a fixed demo mapping. A multi-tenant deployment should
map source mailbox/folder to a company using an explicit configuration table.
