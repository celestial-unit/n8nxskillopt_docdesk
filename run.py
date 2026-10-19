"""
run.py — Single entry point to start the entire document pipeline system.

Starts three components concurrently:
  1. FastAPI backend  (uvicorn, port 8000)
  2. n8n              (n8n start, port 5678)
  3. React UI         (pnpm dev in ./ui, port 3000)  OR  Streamlit fallback

After n8n is up, imports and activates the pipeline workflow automatically.

Usage:
    source .venv/bin/activate && python3 run.py
"""

import os
import signal
import subprocess
import sys
import time
import shutil
from pathlib import Path

FASTAPI_PORT    = 8000
N8N_PORT        = 5678
UI_PORT         = 3000
STREAMLIT_PORT  = 8501
FASTAPI_TIMEOUT = 30    # seconds
N8N_TIMEOUT     = 90    # n8n takes longer on first boot
UI_TIMEOUT      = 60    # next dev compile takes time

ROOT = Path(__file__).parent.resolve()


# ── Load .env before starting any subprocess ──────────────────────────────────

def _load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        print("[run.py] WARNING: .env not found — LLM calls may fail")
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


# ── Health polling ─────────────────────────────────────────────────────────────

def wait_for_http(url: str, timeout: int) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(2)
    return False


def wait_for_tcp(host: str, port: int, timeout: int) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            time.sleep(2)
    return False


# ── Component launchers ────────────────────────────────────────────────────────

def start_fastapi() -> subprocess.Popen:
    print(f"[run.py] Starting FastAPI on :{FASTAPI_PORT}...")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app",
         "--host", "0.0.0.0", "--port", str(FASTAPI_PORT)],
        cwd=str(ROOT),
        env=os.environ.copy(),
    )


def start_n8n() -> subprocess.Popen:
    print(f"[run.py] Starting n8n on :{N8N_PORT}...")
    env = os.environ.copy()
    env["N8N_PORT"]              = str(N8N_PORT)
    env["N8N_PROTOCOL"]          = "http"
    env["N8N_HOST"]              = "127.0.0.1"
    env["N8N_BASIC_AUTH_ACTIVE"] = "false"

    # Use installed n8n binary directly (faster than npx)
    n8n_bin = shutil.which("n8n") or "n8n"
    return subprocess.Popen(
        [n8n_bin, "start"],
        cwd=str(ROOT),
        env=env,
    )


def import_workflow() -> None:
    """Import and activate the pipeline workflow in n8n."""
    workflow_json = ROOT / "n8n" / "pipeline_workflow.json"
    if not workflow_json.exists():
        print("[run.py] WARNING: n8n/pipeline_workflow.json not found — skipping import")
        return

    n8n_bin = shutil.which("n8n") or "n8n"
    env = os.environ.copy()
    env["N8N_PORT"]              = str(N8N_PORT)
    env["N8N_PROTOCOL"]          = "http"
    env["N8N_HOST"]              = "127.0.0.1"
    env["N8N_BASIC_AUTH_ACTIVE"] = "false"

    print("[run.py] Importing n8n workflow...")
    result = subprocess.run(
        [n8n_bin, "import:workflow", f"--input={workflow_json}"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[run.py] WARNING: workflow import failed:\n{result.stderr[:300]}")
        return

    print("[run.py]   ✓ Workflow imported")

    # Try to activate — extract workflow ID from import output or use known ID
    output = result.stdout + result.stderr
    import re
    m = re.search(r"id[:\s]+([a-zA-Z0-9_-]{10,})", output, re.IGNORECASE)
    if m:
        wf_id = m.group(1)
        subprocess.run(
            [n8n_bin, "update:workflow", f"--id={wf_id}", "--active=true"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
        )
        print(f"[run.py]   ✓ Workflow {wf_id} activated")


def start_ui() -> tuple[subprocess.Popen, str, int]:
    ui_dir = ROOT / "ui"
    if ui_dir.exists() and (ui_dir / "package.json").exists():
        print(f"[run.py] Starting React UI on :{UI_PORT}...")
        # pnpm dev is standard for Next.js projects here
        pnpm = shutil.which("pnpm") or "pnpm"
        proc = subprocess.Popen(
            [pnpm, "dev"],
            cwd=str(ui_dir),
            env=os.environ.copy(),
        )
        return proc, "React UI", UI_PORT
    else:
        print(f"[run.py] ./ui absent — starting Streamlit fallback on :{STREAMLIT_PORT}...")
        streamlit_app = ROOT / "streamlit_app.py"
        if not streamlit_app.exists():
            print("[run.py] ERROR: neither ./ui nor streamlit_app.py found")
            sys.exit(1)
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(streamlit_app),
             "--server.port", str(STREAMLIT_PORT), "--server.headless", "true"],
            cwd=str(ROOT),
            env=os.environ.copy(),
        )
        return proc, "Streamlit", STREAMLIT_PORT


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    _load_env()

    processes: list[tuple[str, subprocess.Popen]] = []

    def cleanup(sig=None, frame=None):
        print("\n[run.py] Shutting down all components...")
        for name, p in processes:
            try:
                p.terminate()
                print(f"  stopped {name}")
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # ── Launch all three concurrently ──────────────────────────────────────
    fastapi_proc              = start_fastapi()
    n8n_proc                  = start_n8n()
    ui_proc, ui_name, ui_port = start_ui()

    processes.extend([
        ("FastAPI", fastapi_proc),
        ("n8n",     n8n_proc),
        (ui_name,   ui_proc),
    ])

    # ── Wait for each component with its own timeout ───────────────────────
    print(f"\n[run.py] Waiting for services to come up...\n")

    if not wait_for_http(f"http://localhost:{FASTAPI_PORT}/health", FASTAPI_TIMEOUT):
        print(f"[run.py] ERROR: FastAPI did not start within {FASTAPI_TIMEOUT}s")
        cleanup()
    print(f"  ✓ FastAPI  http://localhost:{FASTAPI_PORT}/docs")

    if not wait_for_tcp("localhost", N8N_PORT, N8N_TIMEOUT):
        print(f"[run.py] ERROR: n8n did not start within {N8N_TIMEOUT}s")
        cleanup()
    print(f"  ✓ n8n      http://localhost:{N8N_PORT}")

    # Import workflow now that n8n is up
    import_workflow()

    if not wait_for_tcp("localhost", ui_port, UI_TIMEOUT):
        print(f"[run.py] ERROR: {ui_name} did not start within {UI_TIMEOUT}s")
        cleanup()
    print(f"  ✓ {ui_name:<10} http://localhost:{ui_port}")

    print(f"""
╔═══════════════════════════════════════════════════════════╗
║          All systems ready — pipeline is live             ║
╠═══════════════════════════════════════════════════════════╣
║  FastAPI docs : http://localhost:{FASTAPI_PORT}/docs                ║
║  n8n canvas  : http://localhost:{N8N_PORT}                 ║
║  UI           : http://localhost:{ui_port}                 ║
╚═══════════════════════════════════════════════════════════╝

Press Ctrl+C to stop everything.
""")

    # ── Keep alive — crash any process and we shut down cleanly ───────────
    try:
        while True:
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"\n[run.py] ERROR: {name} exited unexpectedly (code {proc.returncode})")
                    cleanup()
            time.sleep(2)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
