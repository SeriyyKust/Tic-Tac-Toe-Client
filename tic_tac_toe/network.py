"""Diagnostic transport; contains no Pygame calls."""
import asyncio
import json
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect
from . import protocol


def server_url(value):
    parts = urlsplit(value)
    if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment):
        raise ValueError("Адрес сервера должен быть http(s)://хост[:порт], без логина, запроса и фрагмента.")
    try:
        parts.port
    except ValueError as error:
        raise ValueError("Некорректный порт сервера.") from error
    return value.rstrip("/")


def check_http(base_url):
    with urlopen(base_url.rstrip("/") + "/api/health/", timeout=6) as response:
        payload = json.load(response)
    if payload.get("status") != "ok":
        raise RuntimeError("Server dependencies are unavailable")


async def check_websocket(base_url):
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("Server URL must use http or https")
    url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                     parts.path.rstrip("/") + "/ws/diagnostics/", "", ""))
    async with connect(url, open_timeout=4, close_timeout=1, proxy=None) as socket:
        async with asyncio.timeout(4):
            ready = json.loads(await socket.recv())
            if ready.get("type") != "ready":
                raise RuntimeError("Unexpected WebSocket greeting")
            await socket.send(json.dumps({"type": "ping"}))
            if json.loads(await socket.recv()) != {"type": "pong"}:
                raise RuntimeError("Unexpected WebSocket response")


def check_connection(base_url):
    check_http(base_url)
    asyncio.run(check_websocket(base_url))


class APIError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def api_request(base_url, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    request = Request(base_url.rstrip("/") + path,
                      data=json.dumps(data).encode() if data is not None else None,
                      headers=headers)
    try:
        with urlopen(request, timeout=8) as response:
            return protocol.http(path, json.load(response) if response.status != 204 else None)
    except HTTPError as error:
        try:
            payload = json.load(error)
            messages = []
            for value in payload.values():
                messages.extend(value if isinstance(value, list) else [str(value)])
            message = " ".join(messages)
        except (ValueError, AttributeError, TypeError):
            message = f"Ошибка сервера: {error.code}"
        raise APIError(message, error.code) from error
    except (URLError, TimeoutError, OSError) as error:
        raise APIError("Сервер недоступен. Проверьте соединение и повторите попытку.") from error
    except (ValueError, TypeError, KeyError) as error:
        raise APIError("Некорректный ответ сервера. Повторите попытку или проверьте версию сервера.") from error
