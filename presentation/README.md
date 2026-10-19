# DocDesk presentation

Open `index.html` in a browser. Use ← / → to navigate, `O` for the overview, `F` for fullscreen, or the on-screen buttons. The diagrams are authored in Mermaid (`diagrams/*.mmd`) and rendered in the interactive deck. When the local API is running, the held-out SkillOpt card fetches `http://localhost:8000/skillopt/showcase`.

## Deliverables

- `DocDesk_Presentation.pptx` — PowerPoint export
- `DocDesk_Presentation.pdf` — 16:9 PDF export
- `SPEAKER_NOTES.md` — concise talk track and demo order

Regenerate with `node export.js` from this folder. The exporter uses the cached Puppeteer installation and Chromium already present in the course workspace.
