import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from tic_tac_toe.network import APIError, api_request, server_url
from tic_tac_toe import protocol


class Response(io.BytesIO):
    status = 200


class NetworkTests(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(server_url("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")
        self.assertEqual(server_url("https://example.org/game/"), "https://example.org/game")
        for value in ["localhost:8000", "file:///tmp", "http://", "http://a:bad", "http://user:secret@host", "http://a?q=1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server_url(value)

    def test_malformed_http_success_becomes_readable_error(self):
        for content in [b"not json", b"[]", b'{}', b'{"profile": null, "token": "a"}']:
            with patch("tic_tac_toe.network.urlopen", return_value=Response(content)):
                with self.assertRaisesRegex(APIError, "Некорректный ответ"):
                    api_request("http://localhost", "/api/auth/login/", {})

    def test_http_errors_and_unavailable_server(self):
        errors = [HTTPError("http://localhost", 401, "Unauthorized", {}, io.BytesIO(b'{"detail":"expired"}')),
                  HTTPError("http://localhost", 503, "Unavailable", {}, io.BytesIO(b'<html>bad</html>')),
                  URLError("connection refused")]
        for error in errors:
            with patch("tic_tac_toe.network.urlopen", side_effect=error), self.assertRaises(APIError):
                api_request("http://localhost", "/api/me/", token="test")

    def test_invalid_history_date_rejected_before_rendering(self):
        value = {"count": 1, "next": None, "previous": None, "results": [
            {"id": 1, "opponent": "other", "symbol": "X", "outcome": "win", "reason": "line", "finished_at": "bad"}]}
        with patch("tic_tac_toe.network.urlopen", return_value=Response(json.dumps(value).encode())):
            with self.assertRaises(APIError):
                api_request("http://localhost", "/api/me/history/")
