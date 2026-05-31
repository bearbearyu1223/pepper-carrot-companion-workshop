"""Modal deployment for Ollama serving qwen2.5:7b + bge-m3.

Cold start: ~15–25s after idle (GPU spin-up + model load into VRAM).
Warm requests: instant within the scaledown_window.

Usage:
    uv tool install modal           # or: brew install pipx && pipx install modal
    modal token new                 # opens a browser to authenticate
    modal deploy infra/modal_ollama.py

The deploy prints a URL like
    https://<workspace>--peppercarrot-ollama-serve.modal.run
which speaks the standard Ollama HTTP API (/api/chat, /api/embed) and is a
drop-in for `OLLAMA_BASE_URL` in `.env.production`. See `docs/deployment.md`.

This is the **only** new model-provider piece in Post 10 — the backend's
OllamaChatClient + OllamaEmbeddingClient from Post 3 already speak the
standard Ollama API. Modal hosts the same server qwen2.5:7b ran behind on
your laptop; the URL is the only thing that changes.
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request

import modal

OLLAMA_PORT = 11434
CHAT_MODEL = "qwen2.5:7b"
EMBEDDING_MODEL = "bge-m3"

app = modal.App("peppercarrot-ollama")

# Persistent volume — qwen2.5:7b (~4.7 GB) + bge-m3 (~1.2 GB) survive across
# cold starts, so we only pay the download cost on the first deploy.
models_volume = modal.Volume.from_name(
    "peppercarrot-ollama-models", create_if_missing=True
)

image = (
    modal.Image.debian_slim(python_version="3.11")
    # zstd is required by Ollama's install script for tarball extraction.
    .apt_install("curl", "zstd")
    .run_commands("curl -fsSL https://ollama.com/install.sh | sh")
)


@app.function(
    image=image,
    gpu="T4",                         # 16 GB VRAM; sufficient for 7b + embeddings.
    volumes={"/root/.ollama": models_volume},
    scaledown_window=300,             # stay warm 5 minutes after the last request.
    timeout=600,
    min_containers=0,                 # scale-to-zero when idle.
)
@modal.web_server(
    port=OLLAMA_PORT,
    startup_timeout=600,              # first deploy pulls ~6 GB of weights.
    requires_proxy_auth=True,         # set False only for private staging URLs.
)
def serve() -> None:
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"0.0.0.0:{OLLAMA_PORT}"
    subprocess.Popen(["ollama", "serve"], env=env)

    # Wait up to 60s for the server to come up before pulling models.
    for _ in range(60):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{OLLAMA_PORT}/api/tags", timeout=2
            ).read()
            break
        except Exception:  # noqa: BLE001 — exhaustive retry loop
            time.sleep(1)
    else:
        raise RuntimeError("ollama serve did not become ready in 60s")

    # Pull both models into the persistent volume so subsequent cold starts
    # skip the download and only pay the VRAM-load cost (~15–25s).
    for model in (CHAT_MODEL, EMBEDDING_MODEL):
        subprocess.run(["ollama", "pull", model], check=True)

    models_volume.commit()
