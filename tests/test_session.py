import asyncio
import json
import unittest
from queue import Empty

from websockets.asyncio.server import serve
from tic_tac_toe.session import Session


def snapshot(rating=1000):
    return {"type": "session.state", "protocol": 1, "searching": False, "match": None,
            "profile": {"id": 1, "username": "player", "rating": rating, "wins": 0,
                        "losses": 0, "draws": 0, "joined_at": "2026-10-21T00:00:00Z"},
            "social": {"friends": [], "requests": [], "invitations": []}}


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def get_event(self, session, kind):
        async with asyncio.timeout(6):
            while True:
                try:
                    event = session.events.get_nowait()
                    if event["type"] == kind:
                        return event
                except Empty:
                    pass
                await asyncio.sleep(0.01)

    async def test_reconnect_restores_state_and_revocation_stops_retries(self):
        connections = []
        async def handler(socket):
            connections.append(socket)
            self.assertEqual(socket.request.headers["Authorization"], "Token example")
            await socket.send(json.dumps(snapshot(1000 + len(connections))))
            if len(connections) == 1:
                await socket.close(code=1012)
            else:
                await asyncio.sleep(0.1)
                await socket.close(code=4401)
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            session = Session(f"http://127.0.0.1:{port}", "example")
            session.start()
            try:
                self.assertEqual((await self.get_event(session, "session.state"))["profile"]["rating"], 1001)
                self.assertEqual((await self.get_event(session, "session.state"))["profile"]["rating"], 1002)
                await self.get_event(session, "auth_expired")
            finally:
                session.stop()
                await asyncio.to_thread(session.thread.join, 2)
            self.assertFalse(session.thread.is_alive())
            self.assertEqual(len(connections), 2)

    async def test_rejected_handshake_is_not_retried(self):
        def reject(connection, request):
            return connection.respond(403, "Unauthorized")
        async with serve(lambda socket: None, "127.0.0.1", 0, process_request=reject) as server:
            session = Session(f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", "invalid")
            session.start()
            try:
                await self.get_event(session, "auth_expired")
            finally:
                session.stop()
                await asyncio.to_thread(session.thread.join, 2)
            self.assertFalse(session.thread.is_alive())

    async def test_stop_interrupts_pending_connection(self):
        session = Session("http://127.0.0.1:1", "example")
        session.start()
        await self.get_event(session, "connection")
        session.stop()
        await asyncio.to_thread(session.thread.join, 2)
        self.assertFalse(session.thread.is_alive())

    async def test_malformed_state_is_reported_and_thread_stops(self):
        async def handler(socket):
            await socket.send(json.dumps({"type": "session.state", "protocol": 1, "profile": None}))
            await socket.wait_closed()
        async with serve(handler, "127.0.0.1", 0) as server:
            session = Session(f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", "example")
            session.start()
            try:
                await self.get_event(session, "protocol_error")
            finally:
                session.stop()
                await asyncio.to_thread(session.thread.join, 2)
            self.assertFalse(session.thread.is_alive())
            self.assertFalse(session.connected.is_set())

    async def test_command_is_not_replayed_after_disconnect(self):
        received = []
        connections = []
        async def handler(socket):
            connections.append(socket)
            await socket.send(json.dumps(snapshot()))
            if len(connections) == 1:
                received.append(json.loads(await socket.recv()))
                await socket.close(code=1012)
            else:
                try:
                    received.append(json.loads(await asyncio.wait_for(socket.recv(), 0.2)))
                except TimeoutError:
                    pass
                await socket.close(code=4401)
        async with serve(handler, "127.0.0.1", 0) as server:
            session = Session(f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", "example")
            self.assertFalse(session.send({"type": "queue.join"}))
            session.start()
            try:
                async with asyncio.timeout(5):
                    while not session.connected.is_set():
                        await asyncio.sleep(0.01)
                self.assertTrue(session.send({"type": "queue.join"}))
                await self.get_event(session, "auth_expired")
            finally:
                session.stop()
                await asyncio.to_thread(session.thread.join, 2)
            self.assertEqual(received, [{"type": "queue.join"}])

    async def test_malformed_error_does_not_reach_ui(self):
        async def handler(socket):
            await socket.send(json.dumps(snapshot()))
            await socket.send(json.dumps({"type": "error", "code": "bad", "detail": []}))
            await socket.wait_closed()
        async with serve(handler, "127.0.0.1", 0) as server:
            session = Session(f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", "example")
            session.start()
            try:
                await self.get_event(session, "protocol_error")
            finally:
                session.stop()
                await asyncio.to_thread(session.thread.join, 2)
            self.assertFalse(session.connected.is_set())
