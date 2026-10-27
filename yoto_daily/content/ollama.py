"""A client for a local Ollama server.

Ollama keeps a model on the machine that runs it, which makes it a natural
home for the words on a daily card: tomorrow's story is written on the same
box that renders it, and nothing about the children leaves the house.

The client is deliberately small.  It speaks the two endpoints the project
needs -- ``/api/tags`` to see what is installed and ``/api/generate`` to ask
for text -- and nothing else.
"""

from __future__ import annotations

from typing import Any

#: Where Ollama listens unless it is told otherwise.
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"

#: A model small enough to run on a laptop with no GPU of its own.
DEFAULT_MODEL = "qwen3:1.7b"


class OllamaError(RuntimeError):
    """Raised when the local Ollama server cannot do what was asked."""


class OllamaClient:
    """Talks to a local Ollama server."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        *,
        timeout: float = 600.0,
        keep_alive: str = "10m",
        num_ctx: int = 8192,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.keep_alive = keep_alive
        # Ollama defaults to a 32k context window.  Attention is quadratic
        # in it, so on a machine without a dedicated GPU the default costs
        # minutes per story.  The prompts here are a couple of thousand
        # tokens and the answer is another couple of thousand, so a smaller
        # window is plenty and much faster.
        self.num_ctx = num_ctx

    # ------------------------------------------------------------------
    def available(self) -> bool:
        """Whether the server is up and the configured model is installed.

        A model that is not installed is not an error: Ollama pulls one on
        demand.  This only reports what is true right now, so the listing
        can tell somebody to run ``ollama pull`` before they wonder why the
        card took no text.
        """
        if not self.model:
            return False
        return self.model in self.installed_models()

    def installed_models(self) -> list[str]:
        """The names of the models this server has."""
        import requests

        try:
            resp = requests.get(f"{self.endpoint}/api/tags", timeout=5)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return []
        return [str(m.get("name") or "") for m in (payload.get("models") or [])]

    def detail(self) -> str:
        """A short note about the server, shown in the generator listing."""
        models = self.installed_models()
        if not models:
            return f"no response from {self.endpoint}"
        if self.model and self.model not in models:
            return (
                f"{self.model} is not installed; run 'ollama pull {self.model}' "
                f"(have: {', '.join(models[:4])})"
            )
        return f"reachable at {self.endpoint} with {self.model}"

    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        options: dict[str, Any] | None = None,
    ) -> str:
        """Ask the model for a completion."""
        import requests

        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx, **(options or {})},
            # Thinking models answer twice: once in a "thinking" field and
            # once for real.  The thinking is not something to read aloud,
            # and it is slow, so it is switched off.
            "think": False,
        }
        if system:
            body["system"] = system

        try:
            resp = requests.post(
                f"{self.endpoint}/api/generate", json=body, timeout=self.timeout
            )
        except Exception as exc:
            raise OllamaError(
                f"could not reach Ollama at {self.endpoint}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            # Newer Ollama builds understand ``think``.  Older ones reject the
            # field outright, and a model that cannot think does not mind
            # either way, so the request is retried without it.
            if resp.status_code == 400 and "think" in resp.text.lower():
                body.pop("think", None)
                try:
                    resp = requests.post(
                        f"{self.endpoint}/api/generate", json=body, timeout=self.timeout
                    )
                except Exception as exc:
                    raise OllamaError(
                        f"could not reach Ollama at {self.endpoint}: {exc}"
                    ) from exc

        if resp.status_code >= 400:
            raise OllamaError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise OllamaError("Ollama returned a response that is not JSON") from exc

        text = str(data.get("response") or "").strip()
        if not text:
            raise OllamaError(f"{self.model} returned no text")
        return text


__all__ = ["DEFAULT_ENDPOINT", "DEFAULT_MODEL", "OllamaClient", "OllamaError"]
