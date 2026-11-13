"""Bounded vision requests and a small, validated animation command protocol."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request


PERSONALITIES = {
    "Orange": ("#ff9e36", "The Second Coming: creativo, curioso, protector; improvisa soluciones y dibuja ideas.", True),
    "Red": ("#f35764", "Red: impulsivo, cariñoso con animales, juguetón y valiente; se entusiasma rápido.", False),
    "Yellow": ("#f3d64b", "Yellow: lógico e inventor; le atraen circuitos, código y mecanismos; explica con pocas palabras.", False),
    "Green": ("#55ce92", "Green: musical, expresivo y competitivo; marca ritmos y celebra pequeños logros.", False),
    "Blue": ("#59b5ed", "Blue: tranquilo, amable y observador; le gustan plantas, cocina y experimentos.", False),
    "Purple": ("#b08aeb", "Purple: sensible y ambicioso; busca amistad y reconocimiento, aprende a confiar.", False),
    "TCO": ("#b0b7c5", "The Chosen One: reservado, independiente y protector; gestos decididos, pocas palabras.", True),
    "TDL": ("#d84858", "The Dark Lord: teatral, desafiante y competitivo; travieso en la ficción, sin dañar el equipo.", True),
    "victim": ("#9da5b2", "victim: cauteloso, ingenioso y estratégico; estudia la escena antes de actuar.", True),
}
ACTIONS = frozenset({"idle", "walk", "wave", "jump", "dance", "sit", "think", "point", "celebrate", "surprised", "sleep"})
EMOTIONS = frozenset({"calm", "curious", "happy", "surprised", "focused", "sleepy"})
MAX_RESPONSE_BYTES = 256_000


@dataclass(frozen=True)
class BrainSettings:
    provider: str = "ollama"
    endpoint: str = "http://localhost:11434"
    model: str = "qwen2.5vl:7b"
    api_key: str = ""

    def validate(self) -> None:
        parsed = urlparse(self.endpoint)
        if self.provider not in {"ollama", "openai"}:
            raise ValueError("Proveedor no reconocido.")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("La URL debe comenzar por http:// o https://.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Usá una URL base sin contraseña, parámetros ni fragmentos.")
        if not self.model.strip():
            raise ValueError("Indicá un modelo; para ver la pantalla debe aceptar imágenes.")


@dataclass(frozen=True)
class Reaction:
    speech: str = ""
    action: str = "idle"
    emotion: str = "calm"
    target_x: float | None = None

    @classmethod
    def parse(cls, content: str) -> "Reaction":
        # Some compatible servers put JSON inside a Markdown code fence.
        content = content.strip()
        if content.startswith("```") and content.endswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ValueError("El modelo no devolvió JSON válido. Probá otro modelo o repetí la consulta.") from exc
        if not isinstance(value, dict):
            raise ValueError("La respuesta del modelo debe ser un objeto JSON.")
        speech = value.get("speech", "")
        if not isinstance(speech, str):
            speech = ""
        # Plain text only. Keep bubbles and optional speech short.
        speech = " ".join("".join(c for c in speech if c.isprintable() or c.isspace()).split())[:180]
        action, emotion = value.get("action"), value.get("emotion")
        target = value.get("target_x")
        if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target):
            target = None
        else:
            target = max(0.0, min(1.0, target))
        return cls(speech, action if isinstance(action, str) and action in ACTIONS else "idle",
                   emotion if isinstance(emotion, str) and emotion in EMOTIONS else "calm", target)

    def as_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def system_prompt(character: str) -> str:
    template = (Path(__file__).parent / "prompts" / "system.txt").read_text(encoding="utf-8")
    return template.replace("{{PERSONALITY}}", PERSONALITIES[character][1])


def build_request(settings: BrainSettings, character: str, message: str,
                  screenshot: bytes | None, history: list[dict[str, str]]) -> tuple[str, dict, dict]:
    settings.validate()
    prompt = system_prompt(character)
    context = history[-12:]
    if screenshot:
        message += "\nAdjunto una captura actual del área elegida. Basá tu reacción en lo visible."
    else:
        message += "\nEn este turno no hay captura. No afirmes estar viendo la pantalla ahora."
    encoded = base64.b64encode(screenshot).decode("ascii") if screenshot else None
    headers = {"Content-Type": "application/json"}
    if settings.provider == "ollama":
        turn: dict = {"role": "user", "content": message}
        if encoded:
            turn["images"] = [encoded]
        body = {"model": settings.model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": prompt}, *context, turn],
                "options": {"num_predict": 220, "temperature": 0.7}}
        return settings.endpoint.rstrip("/") + "/api/chat", headers, body
    content: list[dict] = [{"type": "text", "text": message}]
    if encoded:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    key = settings.api_key or os.environ.get("OPENAI_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": settings.model, "messages": [{"role": "system", "content": prompt}, *context,
             {"role": "user", "content": content}], "max_tokens": 220,
            "response_format": {"type": "json_object"}}
    return settings.endpoint.rstrip("/") + "/chat/completions", headers, body


def request_reaction(settings: BrainSettings, character: str, message: str,
                     screenshot: bytes | None = None, history: list[dict[str, str]] | None = None) -> Reaction:
    from urllib.request import HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    url, headers, body = build_request(settings, character, message, screenshot, history or [])
    request = Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        # No redirects: a configured endpoint cannot forward the key or screenshot elsewhere.
        with build_opener(NoRedirect).open(request, timeout=45) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("El servidor devolvió una respuesta demasiado grande.")
        result = json.loads(data)
        if settings.provider == "ollama":
            content = result["message"]["content"]
        else:
            content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("El modelo no devolvió texto.")
        return Reaction.parse(content)
    except HTTPError as exc:
        # Do not display response bodies: some servers echo the request and its image.
        help_text = {401: "Revisá la clave de API.", 403: "El servidor rechazó el acceso.",
                     404: "Revisá la URL y el nombre del modelo.",
                     400: "Revisá que el modelo acepte imágenes y salida JSON.",
                     429: "Límite de uso alcanzado; aumentá el intervalo."}.get(exc.code, "Revisá el servidor y el modelo.")
        code = exc.code
        exc.close()
        raise ValueError(f"HTTP {code}. {help_text}") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("No se pudo consultar el modelo (conexión fallida o tiempo agotado). Revisá el servidor y la URL; el límite de espera de red es de 45 s.") from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError("Formato de respuesta inesperado. Elegí Ollama o una API de Chat Completions compatible.") from None
