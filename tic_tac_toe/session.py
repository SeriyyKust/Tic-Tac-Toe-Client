"""Persistent WebSocket on a dedicated thread; UI consumes this instance's queue."""
import asyncio
import json
from queue import Queue
from threading import Event, Thread
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidHandshake
from . import protocol


class Session:
    def __init__(self, base_url, token):
        parts = urlsplit(base_url)
        self.url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                              parts.path.rstrip("/") + "/ws/session/", "", ""))
        self.token = token
        self.events = Queue()
        self.stopped = Event()
        self.loop = None
        self.task = None
        self.thread = Thread(target=self._run, daemon=True)
        self.connected = Event()
        self.commands = None

    def send(self, message):
        if not self.connected.is_set() or self.stopped.is_set():
            return False
        try:
            self.loop.call_soon_threadsafe(self.commands.put_nowait, message)
            return True
        except RuntimeError:
            return False

    async def _send_commands(self, socket, commands):
        while True:
            try:
                message = await asyncio.wait_for(commands.get(), timeout=4)
            except TimeoutError:
                message = {"type": "ping"}
            await socket.send(json.dumps(message))

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass  # Loop already closed.

    def _run(self):
        asyncio.run(self._connect())

    async def _connect(self):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        delay = 1
        try:
            while not self.stopped.is_set():
                self.events.put({"type": "connection", "status": "connecting"})
                try:
                    async with connect(self.url, additional_headers={"Authorization": f"Token {self.token}"},
                                       open_timeout=4, close_timeout=1, proxy=None, max_size=65536,
                                       ping_interval=10, ping_timeout=10) as socket:
                        state = json.loads(await asyncio.wait_for(socket.recv(), timeout=8))
                        protocol.state(state)
                        self.events.put(state)
                        self.commands = asyncio.Queue()
                        self.connected.set()
                        self.events.put({"type": "connection", "status": "connected"})
                        delay = 1
                        sender = asyncio.create_task(self._send_commands(socket, self.commands))
                        try:
                            while not self.stopped.is_set():
                                raw = await asyncio.wait_for(socket.recv(), timeout=13)
                                event = json.loads(raw)
                                if not isinstance(event, dict):
                                    raise ValueError("Invalid event")
                                if event.get("type") == "session.state":
                                    protocol.state(event)
                                elif event.get("type") == "error":
                                    protocol.fields(event, {"code": str})
                                    if "detail" in event:
                                        protocol.fields(event, {"detail": str})
                                elif event.get("type") not in {"pong", "error"}:
                                    raise ValueError("Unknown event")
                                self.events.put(event)
                        finally:
                            self.connected.clear()
                            sender.cancel()
                            await asyncio.gather(sender, return_exceptions=True)
                except InvalidStatus as error:
                    if error.response.status_code in {401, 403}:
                        self.events.put({"type": "auth_expired"})
                        return
                except ConnectionClosed as error:
                    if error.rcvd and error.rcvd.code == 4401:
                        self.events.put({"type": "auth_expired"})
                        return
                except (OSError, TimeoutError, InvalidHandshake):
                    pass
                except (ValueError, TypeError):
                    self.events.put({"type": "protocol_error"})
                    return
                self.events.put({"type": "connection", "status": "reconnecting"})
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15)
        except asyncio.CancelledError:
            pass
        finally:
            self.connected.clear()
