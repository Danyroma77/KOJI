"""
LLM Manager — Wrapper per Ollama REST API.
Gestisce caricamento, scaricamento, generazione e switch dei modelli.
"""

from __future__ import annotations
import asyncio
import json
import httpx
from typing import Optional, Generator

from app.config import settings


class LLMManager:
    """Gestore interazione con Ollama."""

    def __init__(self, base_url: str = None):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = settings.OLLAMA_TIMEOUT
        self._active_model: Optional[str] = None
        # Stato interno per download (pull) asincrono dei modelli
        self._pull_tasks: dict[str, asyncio.Task] = {}
        self._pull_progress: dict[str, dict] = {}

    @property
    def active_model(self) -> str:
        return self._active_model or settings.OLLAMA_MODEL

    def set_active_model(self, model: str):
        self._active_model = model

    async def check_health(self) -> bool:
        """Verifica che Ollama sia raggiungibile."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        """Lista modelli disponibili in Ollama."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return data.get("models", [])

    async def running_models(self) -> list[dict]:
        """Modelli attualmente caricati in memoria (in linea) in Ollama."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/api/ps")
            resp.raise_for_status()
            data = resp.json()
            return data.get("models", [])

    async def load_model(self, name: str, keep_alive: str = None) -> dict:
        """Carica un modello nella memoria di Ollama ('metterlo in linea')."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": name,
                    "prompt": "",
                    "stream": False,
                    # Tiene il modello in RAM/VRAM per il tempo richiesto
                    "keep_alive": keep_alive or settings.OLLAMA_KEEP_ALIVE,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def unload_model(self, name: str) -> dict:
        """Libera la memoria scaricando il modello ('toglierlo dalla linea')."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": name,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": 0,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def show_model(self, name: str) -> dict:
        """Dettagli di un modello specifico."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/show",
                json={"name": name},
            )
            resp.raise_for_status()
            return resp.json()

    async def generate(
        self,
        prompt: str,
        model: str = None,
        temperature: float = None,
        top_k: int = None,
        max_tokens: int = None,
    ) -> str:
        """Genera risposta completa (non streaming).

        Returns:
            Testo generato dal modello.
        """
        model = model or self.active_model
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature or settings.RAG_TEMPERATURE,
                "top_k": top_k or 40,
                "num_predict": max_tokens or settings.RAG_MAX_TOKENS,
            }
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")

    async def generate_stream(
        self,
        prompt: str,
        model: str = None,
        temperature: float = None,
        top_k: int = None,
        max_tokens: int = None,
    ) -> Generator[str, None, None]:
        """Genera risposta in streaming.

        Yields:
            Token singoli man mano che vengono generati.
        """
        model = model or self.active_model
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature or settings.RAG_TEMPERATURE,
                "top_k": top_k or 40,
                "num_predict": max_tokens or settings.RAG_MAX_TOKENS,
            }
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        import json
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            yield token
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue

    async def pull_model(self, name: str) -> dict:
        """Avvia lo scaricamento (pull) di un modello da Ollama in background.

        Il download viene eseguito in background (asyncio task) per non bloccare
        la richiesta HTTP. L'avanzamento si legge tramite :meth:`pull_status`.
        """
        task = self._pull_tasks.get(name)
        if task and not task.done():
            return {"status": "running", "model": name}
        self._pull_progress[name] = {
            "model": name,
            "status": "starting",
            "progress": 0.0,
            "message": "Avvio dello scaricamento...",
        }
        task = asyncio.create_task(self._run_pull(name))
        self._pull_tasks[name] = task
        # Pulisce il riferimento a download terminato
        task.add_done_callback(lambda _t: self._pull_tasks.pop(name, None))
        return {"status": "started", "model": name}

    def pull_status(self, name: str) -> dict:
        """Stato di avanzamento di un pull (idle se nessun download in corso)."""
        return self._pull_progress.get(
            name, {"model": name, "status": "idle", "progress": 0.0, "message": None}
        )

    async def _run_pull(self, name: str) -> None:
        """Scarica il modello da Ollama interpretando i messaggi di avanzamento.

        Ollama restituisce una sequenza di oggetti JSON: "pulling manifest", poi
        vari oggetti "downloading ..." con {total, completed}, quindi
        "verifying sha256 digest", "writing manifest", "success".
        """
        progress = self._pull_progress.setdefault(
            name, {"model": name, "status": "starting", "progress": 0.0, "message": None}
        )
        try:
            async with httpx.AsyncClient(timeout=settings.OLLAMA_PULL_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/pull",
                    json={"name": name, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        status = data.get("status", "")
                        progress["status"] = status
                        progress["message"] = status
                        if status == "success":
                            progress["progress"] = 1.0
                        elif status and status.startswith("downloading"):
                            total = data.get("total") or 0
                            completed = data.get("completed") or 0
                            if total:
                                progress["progress"] = round(min(1.0, completed / total), 4)
                            else:
                                progress["progress"] = 0.0
                            progress["message"] = (
                                f"{status} · {_format_bytes(completed)} / {_format_bytes(total)}"
                            )
            progress["status"] = "success"
            progress["message"] = "Modello scaricato con successo"
            progress["progress"] = 1.0
        except Exception as e:
            progress["status"] = "error"
            progress["message"] = str(e) or "Errore durante lo scaricamento"


def _format_bytes(value: int) -> str:
    """Formatta un quantitativo di byte in unità leggibili (KB/MB/GB)."""
    value = max(0, int(value or 0))
    if value >= 1e9:
        return f"{value / 1e9:.1f} GB"
    if value >= 1e6:
        return f"{value / 1e6:.1f} MB"
    if value >= 1e3:
        return f"{value / 1e3:.0f} KB"
    return f"{value} B"


# Istanza singleton
llm_manager = LLMManager()