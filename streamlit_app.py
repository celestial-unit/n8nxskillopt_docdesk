"""
streamlit_app.py — Fallback UI when ./ui is absent.

Provides the same core workflow as the React Command Center:
- Upload or pick a document
- Submit to n8n webhook
- Poll /trace every 500ms and display 5 stage cards
- Show ACCEPTED / ESCALATED badge
"""

import base64
import json
import time
import uuid
from pathlib import Path

import requests
import streamlit as st

API_URL = "http://localhost:8000"
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/pipeline"
POLL_INTERVAL = 0.5  # seconds

STAGE_ORDER = ["route", "extract", "code", "validate", "accept", "escalate", "fail"]
STAGE_LABELS = {
    "route": "🔀 Router",
    "extract": "📋 Extractor",
    "code": "🏷️ Coder",
    "validate": "✅ Validator",
    "accept": "✔️ Decision",
    "escalate": "⚠️ Decision",
    "fail": "❌ Failed",
}

st.set_page_config(page_title="Document Pipeline", layout="wide", page_icon="🤖")

st.markdown("""
<style>
body { background: #0a0a1a; color: #00ff88; }
.stage-card { border: 1px solid #00ff88; border-radius: 8px; padding: 12px; margin: 4px; background: #0d1117; }
.stage-pending { border-color: #333; color: #555; }
.stage-running { border-color: #ffaa00; color: #ffaa00; }
.stage-done    { border-color: #00ff88; color: #00ff88; }
.stage-error   { border-color: #ff4444; color: #ff4444; }
</style>
""", unsafe_allow_html=True)

st.title("🤖 Document Pipeline — Tactical Dashboard")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Configuration")
    company_id = st.selectbox("Company", ["company_a", "company_b"])
    st.markdown("---")
    st.markdown(f"**API**: {API_URL}")
    st.markdown(f"**n8n**: {N8N_WEBHOOK_URL}")

    # Health check
    try:
        h = requests.get(f"{API_URL}/health", timeout=2)
        st.success(f"FastAPI: {h.json().get('status', 'ok')}")
    except Exception:
        st.error("FastAPI: offline")

# ── Main ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["Command Center", "Operations", "Systems"])

with tab1:
    st.header("Command Center")

    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader("Upload document (PDF or image)", type=["pdf", "jpg", "jpeg", "png"])
    with col2:
        demo_files = list(Path("demo").glob("*.pdf")) + list(Path("demo").glob("*.jpg"))
        demo_choice = st.selectbox("Or pick a demo file", [""] + [f.name for f in demo_files])

    run_btn = st.button("▶ Run Pipeline", type="primary")

    if run_btn and (uploaded or demo_choice):
        doc_id = f"ui-{uuid.uuid4().hex[:8]}"

        if uploaded:
            file_bytes = uploaded.read()
            filename = uploaded.name
        else:
            fpath = Path("demo") / demo_choice
            file_bytes = fpath.read_bytes()
            filename = fpath.name

        file_b64 = base64.b64encode(file_bytes).decode()

        st.info(f"Processing document `{filename}` (doc_id: `{doc_id}`)...")

        # Submit to n8n webhook
        try:
            payload = {
                "doc_id": doc_id,
                "company_id": company_id,
                "file_b64": file_b64,
                "filename": filename,
            }
            resp = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=5)
            st.caption(f"Webhook response: {resp.status_code}")
        except Exception as e:
            st.warning(f"n8n webhook unavailable ({e}), processing via FastAPI directly...")

        # Stage cards
        st.markdown("---")
        st.subheader("Pipeline Progress")
        stage_placeholders = {}
        cols = st.columns(5)
        stage_names = ["route", "extract", "code", "validate", "accept"]
        for i, stage in enumerate(stage_names):
            with cols[i]:
                stage_placeholders[stage] = st.empty()
                stage_placeholders[stage].markdown(
                    f'<div class="stage-card stage-pending">{STAGE_LABELS.get(stage, stage)}<br><small>⏳ pending</small></div>',
                    unsafe_allow_html=True,
                )

        decision_placeholder = st.empty()

        # Poll traces
        deadline = time.time() + 120
        final_decision = None
        seen_steps = set()

        while time.time() < deadline:
            try:
                r = requests.get(f"{API_URL}/trace/{doc_id}", timeout=2)
                traces = r.json().get("traces", [])
            except Exception:
                traces = []

            for t in traces:
                step = t.get("step", "")
                status = t.get("status", "")
                ms = t.get("duration_ms", 0)
                seen_steps.add(step)

                if step in stage_placeholders:
                    css = "stage-done" if status == "success" else "stage-error"
                    stage_placeholders[step].markdown(
                        f'<div class="stage-card {css}">{STAGE_LABELS.get(step, step)}<br>'
                        f'<small>{"✓" if status == "success" else "✗"} {ms}ms</small></div>',
                        unsafe_allow_html=True,
                    )

                if step in ("accept", "escalate", "fail"):
                    final_decision = step
                    break

            if final_decision:
                break
            time.sleep(POLL_INTERVAL)

        # Decision badge
        if final_decision == "accept":
            decision_placeholder.success("✔️ ACCEPTED")
        elif final_decision == "escalate":
            decision_placeholder.warning("⚠️ ESCALATED — Requires human review")
        elif final_decision == "fail":
            decision_placeholder.error("❌ FAILED")
        else:
            decision_placeholder.info("⏳ Processing timed out or pipeline still running")

with tab2:
    st.header("Operations — Processed Documents")
    try:
        # List all unique doc_ids from recent traces (simplified)
        st.info("Connect to FastAPI /trace endpoint to see document history.")
    except Exception as e:
        st.error(str(e))

with tab3:
    st.header("Systems Health")
    try:
        h = requests.get(f"{API_URL}/health", timeout=3)
        data = h.json()
        for comp, status in data.get("components", {}).items():
            if status == "ok":
                st.success(f"✓ {comp}: {status}")
            else:
                st.error(f"✗ {comp}: {status}")
    except Exception as e:
        st.error(f"FastAPI offline: {e}")

    try:
        requests.get(f"http://localhost:{5678}/healthz", timeout=2)
        st.success("✓ n8n: running")
    except Exception:
        st.warning("n8n: not detected (may still be starting)")
