"""Local rules independent of Pygame and networking. Human X starts."""
import random


LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6),
         (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


class Game:
    def __init__(self):
        self.board = [""] * 9
        self.turn = "X"
        self.result = None
        self.winning_line = None

    def move(self, cell, symbol):
        if (self.result is not None or symbol != self.turn or
                type(cell) is not int or not 0 <= cell < 9 or self.board[cell]):
            return False
        self.board[cell] = symbol
        for line in LINES:
            if all(self.board[index] == symbol for index in line):
                self.result = symbol
                self.winning_line = line
                break
        if self.result is None and all(self.board):
            self.result = "draw"
        if self.result is None:
            self.turn = "O" if symbol == "X" else "X"
        return True

    def computer_move(self):
        if self.result is not None or self.turn != "O":
            return False
        return self.move(random.choice([i for i, value in enumerate(self.board) if not value]), "O")
