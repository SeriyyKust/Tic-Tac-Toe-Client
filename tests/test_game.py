import unittest
from unittest.mock import patch

from tic_tac_toe.game import Game


class GameTests(unittest.TestCase):
    def play(self, moves):
        game = Game()
        for cell in moves:
            self.assertTrue(game.move(cell, game.turn))
        return game

    def test_human_wins_and_no_more_moves_allowed(self):
        game = self.play([0, 3, 1, 4, 2])
        self.assertEqual(game.result, "X")
        self.assertEqual(game.winning_line, (0, 1, 2))
        before = game.board.copy()
        self.assertFalse(game.move(8, "O"))
        self.assertFalse(game.computer_move())
        self.assertEqual(game.board, before)

    def test_computer_wins(self):
        game = self.play([0, 3, 1, 4, 8, 5])
        self.assertEqual(game.result, "O")

    def test_draw_on_last_cell(self):
        game = self.play([0, 1, 2, 4, 3, 5, 7, 6, 8])
        self.assertEqual(game.result, "draw")
        self.assertIsNone(game.winning_line)
        self.assertFalse(game.computer_move())

    def test_last_cell_win_takes_precedence_over_draw(self):
        game = self.play([0, 1, 2, 3, 4, 5, 7, 6, 8])
        self.assertEqual(game.result, "X")

    def test_all_winning_directions(self):
        sequences = [
            [0, 3, 1, 4, 2], [3, 0, 4, 1, 5], [6, 0, 7, 1, 8],
            [0, 1, 3, 2, 6], [1, 0, 4, 2, 7], [2, 0, 5, 1, 8],
            [0, 1, 4, 2, 8], [2, 0, 4, 1, 6],
        ]
        for sequence in sequences:
            with self.subTest(sequence=sequence):
                self.assertEqual(self.play(sequence).result, "X")

    def test_invalid_moves_do_not_change_state(self):
        game = Game()
        for cell in [-1, 9, True, "0", None]:
            self.assertFalse(game.move(cell, "X"))
        self.assertFalse(game.move(0, "O"))
        self.assertTrue(game.move(0, "X"))
        self.assertFalse(game.move(0, "O"))
        self.assertFalse(game.move(1, "X"))
        self.assertEqual(game.board, ["X"] + [""] * 8)
        self.assertEqual(game.turn, "O")

    @patch("tic_tac_toe.game.random.choice", side_effect=lambda cells: cells[-1])
    def test_computer_selects_only_free_cells(self, choose):
        game = Game()
        self.assertFalse(game.computer_move())
        game.move(8, "X")
        self.assertTrue(game.computer_move())
        self.assertEqual(choose.call_args.args[0], list(range(8)))
        self.assertEqual(game.board[7:], ["O", "X"])
        self.assertEqual(game.turn, "X")
