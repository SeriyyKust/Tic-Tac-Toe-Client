import os
import time
import unittest
from queue import Queue
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from tic_tac_toe.network import APIError
from tic_tac_toe.ui import App


class UITests(unittest.TestCase):
    def setUp(self):
        self.session_patch = patch("tic_tac_toe.ui.Session")
        self.session_type = self.session_patch.start()
        self.session_type.return_value.events = Queue()
        self.addCleanup(self.session_patch.stop)
        self.app = App("http://127.0.0.1:8000")

    def tearDown(self):
        self.app.close_session()
        pygame.quit()

    def test_game_redraw_fully_replaces_previous_screen(self):
        self.app.profile = {"username": "player", "rating": 1000}
        self.app.page = "menu"
        self.app.draw()
        self.app.activate("computer")
        self.app.draw()
        first = pygame.image.tostring(self.app.screen, "RGB")
        self.app.screen.fill("magenta")
        self.app.draw()
        self.assertEqual(first, pygame.image.tostring(self.app.screen, "RGB"))
        self.assertEqual(self.app.background.get_at((450, 300)).a, 255)

    def finish_request(self):
        deadline = time.monotonic() + 2
        while self.app.busy and time.monotonic() < deadline:
            self.app.poll()
            time.sleep(0.005)
        self.assertFalse(self.app.busy)
        self.app.draw()

    def test_revocation_discards_pending_http_result(self):
        self.app.session = self.session_type.return_value
        self.app.token = "old"
        self.app.busy = True
        generation = self.app.generation
        self.app.session.events.put({"type": "auth_expired"})
        self.app.results.put((generation, "profile", {"username": "old"}, None))
        self.app.poll()
        self.assertEqual(self.app.page, "login")
        self.assertIsNone(self.app.profile)
        self.assertFalse(self.app.busy)
        self.app.draw()

    @patch("tic_tac_toe.ui.api_request")
    def test_register_profile_logout(self, request):
        profile = {"username": "player", "rating": 1000, "wins": 0, "losses": 0,
                   "draws": 0, "joined_at": "2026-10-19T10:00:00Z"}
        request.return_value = {"token": "example", "profile": profile}
        self.app.activate("switch")
        self.app.draw()
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text="player"))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, mod=0))
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text="a valid password"))
        self.app.confirm = "a valid password"
        self.app.submit("register")
        self.finish_request()
        self.assertEqual(self.app.page, "menu")
        self.assertEqual(self.app.password, "")
        request.return_value = profile
        self.app.activate("profile")
        self.finish_request()
        self.assertEqual(self.app.page, "profile")
        request.return_value = None
        self.app.activate("logout")
        self.finish_request()
        self.assertEqual(self.app.page, "login")
        self.assertIsNone(self.app.token)

    @patch("tic_tac_toe.ui.api_request", side_effect=APIError("Сервер недоступен"))
    def test_failed_login_keeps_form_usable(self, request):
        self.app.username, self.app.password = "player", "password"
        self.app.submit("login")
        self.finish_request()
        self.assertEqual(self.app.page, "login")
        self.assertIn("недоступен", self.app.message)
        self.assertIsNone(self.app.token)

    @patch("tic_tac_toe.ui.api_request")
    def test_mismatched_confirmation_does_not_send_request(self, request):
        self.app.activate("switch")
        self.app.username, self.app.password, self.app.confirm = "player", "abc", "def"
        self.app.submit("register")
        request.assert_not_called()
        self.assertFalse(self.app.busy)

    @patch("tic_tac_toe.ui.api_request")
    def test_local_game_clicks_restart_and_rating_unchanged(self, request):
        self.app.profile = {"username": "player", "rating": 1000}
        self.app.activate("computer")
        self.app.draw()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(330, 190)))
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(420, 190)))
        self.assertEqual(self.app.game.board.count("X"), 1)
        self.app.computer_due = 0
        self.app.update_game()
        self.assertEqual(self.app.game.board.count("O"), 1)
        self.app.draw()
        self.app.activate("computer")
        self.assertEqual(self.app.game.board, [""] * 9)
        self.assertIsNone(self.app.computer_due)
        self.assertTrue(self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)))
        self.assertEqual(self.app.page, "menu")
        self.assertIsNone(self.app.game)
        self.assertEqual(self.app.profile["rating"], 1000)
        request.assert_not_called()

    def test_leaving_game_cancels_pending_computer_move(self):
        self.app.activate("computer")
        self.app.play_cell((330, 190))
        game = self.app.game
        self.app.activate("menu")
        self.app.update_game()
        self.assertEqual(game.board.count("O"), 0)
        self.assertIsNone(self.app.computer_due)
        self.app.activate("computer")
        self.app.clear_session()
        self.app.update_game()
        self.assertIsNone(self.app.game)

    def test_online_board_waits_for_server_and_blocks_duplicate_clicks(self):
        self.app.session = self.session_type.return_value
        self.app.connection_status = "connected"
        match = {"id": 10, "symbol": "O", "opponent": "other", "board": ["X"] + [""] * 8,
                 "turn": "O", "result": "", "reason": "", "version": 1, "winning_line": None}
        self.app.session.events.put({"type": "session.state", "profile": {"username": "player"}, "match": match})
        self.app.poll()
        self.app.draw()
        self.assertEqual(self.app.page, "online")
        self.app.play_cell((420, 190))
        self.app.play_cell((420, 190))
        self.app.session.send.assert_called_once_with({"type": "match.move", "match_id": 10, "version": 1, "cell": 1})
        self.assertEqual(self.app.game.board[1], "")
        self.app.session.events.put({"type": "connection", "status": "reconnecting"})
        self.app.poll()
        self.assertIsNone(self.app.pending_move)
        self.app.play_cell((420, 190))
        self.assertEqual(self.app.session.send.call_count, 1)

    def test_queue_cancel_race_opens_started_match(self):
        self.app.session = self.session_type.return_value
        self.app.connection_status = "connected"
        self.app.session.events.put({"type": "session.state", "profile": {}, "searching": True, "match": None})
        self.app.poll()
        self.assertEqual(self.app.page, "search")
        self.app.activate("queue.cancel")
        self.app.session.events.put({"type": "session.state", "profile": {}, "searching": False,
            "match": {"board": [""] * 9, "turn": "X", "result": "", "version": 0, "winning_line": None}})
        self.app.poll()
        self.assertEqual(self.app.page, "online")

    @patch("tic_tac_toe.ui.api_request")
    def test_history_pagination_and_failure_preserves_previous_page(self, request):
        self.app.token = "example"
        request.return_value = {"results": [{"id": 1, "opponent": "other", "symbol": "X",
            "outcome": "win", "reason": "line", "finished_at": "2026-10-19T12:00:00Z",
            "rating_applied": True, "rating_before": 1000, "rating_after": 1016, "rating_delta": 16}],
            "next": "http://localhost/api/me/history/?page=2", "previous": None, "count": 6}
        self.app.activate("history:1")
        self.finish_request()
        self.assertEqual(self.app.page, "history")
        self.assertEqual(self.app.history_page, 1)
        request.assert_called_with(self.app.server, "/api/me/history/?page=1", None, "example")
        request.side_effect = APIError("Сервер недоступен")
        self.app.activate("history:2")
        self.finish_request()
        self.assertEqual(self.app.history_page, 1)
        self.assertIn("недоступен", self.app.message)
        self.app.clear_session()
        self.assertIsNone(self.app.history)

    @patch("tic_tac_toe.ui.api_request", return_value={"results": [], "count": 0, "next": None, "previous": None})
    def test_empty_history(self, request):
        self.app.activate("history:1")
        self.finish_request()
        self.assertEqual(self.app.history["results"], [])
        self.assertFalse(self.app.buttons[0][2])
        self.assertFalse(self.app.buttons[1][2])

    @patch("tic_tac_toe.ui.api_request")
    def test_social_search_and_request(self, request):
        self.app.token = "example"
        self.app.activate("social:search")
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text="other"))
        request.return_value = {"results": [{"user_id": 7, "username": "other"}]}
        self.app.activate("user.search")
        self.finish_request()
        request.assert_called_with(self.app.server, "/api/users/?q=other", None, "example")
        request.return_value = {"friends": [], "requests": [{"user_id": 7, "username": "other", "incoming": False}], "invitations": []}
        self.app.activate("friend.request:7")
        self.finish_request()
        self.assertFalse(self.app.social["requests"][0]["incoming"])
        request.assert_called_with(self.app.server, "/api/social/", {"type": "friend.request", "user_id": 7}, "example")
        self.app.activate("social:requests")
        self.app.draw()
        self.app.clear_session()
        self.assertEqual(self.app.social["requests"], [])
        self.assertEqual(self.app.friend_query, "")

    def test_social_invitation_does_not_start_match_optimistically(self):
        self.app.session = self.session_type.return_value
        self.app.connection_status = "connected"
        self.app.social["invitations"] = [{"id": 4, "username": "other", "incoming": True}]
        self.app.activate("social:invitations")
        self.app.draw()
        self.app.activate("invite.accept:4")
        self.app.session.send.assert_called_with({"type": "invite.accept", "invite_id": 4})
        self.assertEqual(self.app.page, "social")
        self.assertIsNone(self.app.match)

    def test_social_pages_clamp_when_request_disappears(self):
        self.app.social["requests"] = [{"user_id": i, "username": f"player_{i}", "incoming": True} for i in range(5)]
        self.app.activate("social:requests")
        self.app.activate("socialpage:1")
        self.app.draw()
        self.assertEqual(self.app.social_page, 1)
        self.app.social["requests"] = []
        self.app.draw()
        self.assertEqual(self.app.social_page, 0)

    def test_escape_returns_from_secondary_screens(self):
        for page in ["social", "history", "profile"]:
            self.app.page = page
            self.assertTrue(self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)))
            self.assertEqual(self.app.page, "menu")
