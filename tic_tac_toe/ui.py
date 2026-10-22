"""Pygame owns the UI thread; workers only return API results through a queue."""
from queue import Empty, Queue
from threading import Thread
from datetime import datetime
from urllib.parse import quote

import pygame

from .network import APIError, api_request
from .session import Session
from .game import Game
from . import theme


class App:
    def __init__(self, server):
        pygame.init()
        self.screen = pygame.display.set_mode((900, 660))
        pygame.display.set_caption("Tic tac toe — Крестики-нолики")
        self.font = pygame.font.SysFont("arial,dejavusans,liberationsans", 23)
        self.small = pygame.font.SysFont("arial,dejavusans,liberationsans", 18)
        self.title = pygame.font.SysFont("arial narrow,dejavusans,liberationsans", 48, bold=True)
        self.micro = pygame.font.SysFont("arial,dejavusans,liberationsans", 13)
        self.background = theme.background(self.screen.get_size())
        self.server = server
        self.page = "login"
        self.username = ""
        self.password = ""
        self.confirm = ""
        self.focus = "username"
        self.token = None
        self.profile = None
        self.busy = False
        self.message = ""
        self.results = Queue()
        self.buttons = []
        self.fields = {}
        self.session = None
        self.connection_status = ""
        self.generation = 0
        self.game = None
        self.computer_due = None
        self.board_rect = pygame.Rect(315, 175, 270, 270)
        self.match = None
        self.searching = False
        self.pending_move = None
        self.history = None
        self.history_page = 1
        self.social = {"friends": [], "requests": [], "invitations": []}
        self.social_tab = "friends"
        self.social_page = 0
        self.friend_query = ""
        self.user_results = []

    def submit(self, action):
        if self.busy:
            return
        if action in {"login", "register"}:
            if not self.username or not self.password:
                self.message = "Введите логин и пароль."
                return
            if action == "register" and self.password != self.confirm:
                self.message = "Пароли не совпадают."
                return
            path, data = f"/api/auth/{action}/", {"username": self.username, "password": self.password}
        elif action == "logout":
            path, data = "/api/auth/logout/", {}
        elif action.startswith("history:"):
            path, data = f"/api/me/history/?page={int(action.split(':')[1])}", None
        elif action == "user.search":
            path, data = f"/api/users/?q={quote(self.friend_query.strip())}", None
        elif action.startswith("friend."):
            kind, target = action.split(":")
            path, data = "/api/social/", {"type": kind, "user_id": int(target)}
        else:
            path, data = "/api/me/", None
        self.busy = True
        self.message = "Подождите…"
        token = self.token
        generation = self.generation

        def work():
            try:
                result = api_request(self.server, path, data, token)
                self.results.put((generation, action, result, None))
            except APIError as error:
                self.results.put((generation, action, None, error))
            except Exception:
                self.results.put((generation, action, None, APIError("Некорректный ответ сервера.")))

        Thread(target=work, daemon=True).start()

    def poll(self):
        self.poll_session()
        try:
            generation, action, result, error = self.results.get_nowait()
        except Empty:
            return
        if generation != self.generation:
            return
        self.busy = False
        self.message = ""
        if error:
            if error.status == 401:
                self.clear_session()
            self.message = str(error)
            return
        if action in {"login", "register"}:
            self.token = result["token"]
            self.profile = result["profile"]
            self.password = self.confirm = ""
            self.page = "menu"
            self.session = Session(self.server, self.token)
            self.connection_status = "connecting"
            self.session.start()
        elif action == "logout":
            self.clear_session()
        elif action.startswith("history:"):
            self.history = result
            self.history_page = int(action.split(":")[1])
            if self.page not in {"online", "search"}:
                self.page = "history"
        elif action == "user.search":
            self.user_results = result["results"]
            self.social_page = 0
        elif action.startswith("friend."):
            self.social = result
            self.message = "Готово."
        else:
            self.profile = result
            if self.page not in {"online", "search"}:
                self.page = "profile"

    def clear_session(self):
        self.social = {"friends": [], "requests": [], "invitations": []}
        self.friend_query = ""
        self.user_results = []
        self.history = None
        self.history_page = 1
        self.match = None
        self.searching = False
        self.pending_move = None
        self.game = None
        self.computer_due = None
        self.generation += 1
        self.busy = False
        self.close_session()
        self.token = self.profile = None
        self.password = self.confirm = ""
        self.page = "login"
        self.focus = "username"

    def close_session(self):
        if self.session:
            self.session.stop()
            self.session = None
        self.connection_status = ""

    def poll_session(self):
        while self.session:
            try:
                event = self.session.events.get_nowait()
            except Empty:
                break
            if event["type"] == "session.state":
                self.social = event.get("social", self.social)
                self.profile = event["profile"]
                self.match = event.get("match")
                self.searching = event.get("searching", False)
                if self.match:
                    self.page = "online"
                    self.game = Game()
                    self.game.board = self.match["board"]
                    self.game.turn = self.match["turn"]
                    self.game.result = self.match["result"] or None
                    self.game.winning_line = self.match["winning_line"]
                    self.computer_due = None
                    if self.pending_move != self.match["version"]:
                        self.pending_move = None
                elif self.searching:
                    self.page = "search"
                elif self.page in {"online", "search"}:
                    self.page = "menu"
                    self.game = None
                    self.pending_move = None
            elif event["type"] == "connection":
                self.connection_status = event["status"]
                if event["status"] != "connected":
                    self.pending_move = None
            elif event["type"] == "error":
                self.pending_move = None
                self.message = event.get("detail", "Команда отклонена сервером.")
            elif event["type"] == "auth_expired":
                self.clear_session()
                self.message = "Сессия завершена. Войдите снова."
            elif event["type"] == "protocol_error":
                self.connection_status = "error"
                self.message = "Версия протокола не поддерживается или ответ сервера повреждён."

    def activate(self, action):
        if self.busy:
            return
        if action in {"login", "register", "logout", "profile"}:
            self.submit(action)
        elif action.startswith("history:"):
            self.submit(action)
        elif action == "user.search" or action.startswith("friend."):
            self.submit(action)
        elif action.startswith("social:"):
            self.page = "social"
            self.social_tab = action.split(":")[1]
            self.social_page = 0
            self.focus = "friend_query"
            self.message = ""
        elif action.startswith("socialpage:"):
            self.social_page = int(action.split(":")[1])
        elif action.startswith("invite."):
            kind, target = action.split(":")
            self.send_command({"type": kind, "user_id" if kind == "invite.send" else "invite_id": int(target)})
        elif action == "switch":
            self.page = "register" if self.page == "login" else "login"
            self.password = self.confirm = ""
            self.message = ""
            self.focus = "username"
        elif action == "menu":
            self.game = None
            self.computer_due = None
            self.page = "menu"
            self.message = ""
        elif action == "computer":
            self.game = Game()
            self.computer_due = None
            self.page = "game"
            self.message = ""
        elif action in {"queue.join", "queue.cancel", "match.resign", "match.dismiss"}:
            command = {"type": action}
            if action.startswith("match."):
                command["match_id"] = self.match["id"]
            self.send_command(command)

    def send_command(self, command):
        if self.session and self.connection_status == "connected" and self.session.send(command):
            self.message = ""
            return True
        self.message = "Нет связи с сервером. Дождитесь переподключения."
        return False

    def play_cell(self, position):
        if self.page not in {"game", "online"} or not self.board_rect.collidepoint(position):
            return
        col = (position[0] - self.board_rect.x) // 90
        row = (position[1] - self.board_rect.y) // 90
        if self.page == "online":
            if (self.match["result"] or self.match["turn"] != self.match["symbol"] or
                    self.pending_move is not None or self.match["board"][row * 3 + col]):
                return
            if self.send_command({"type": "match.move", "match_id": self.match["id"],
                                  "version": self.match["version"], "cell": row * 3 + col}):
                self.pending_move = self.match["version"]
            return
        if self.game.move(row * 3 + col, "X") and self.game.result is None:
            self.computer_due = pygame.time.get_ticks() + 350

    def update_game(self):
        if self.page == "game" and self.computer_due is not None and pygame.time.get_ticks() >= self.computer_due:
            self.computer_due = None
            self.game.computer_move()

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.play_cell(event.pos)
            for name, rect in self.fields.items():
                if rect.collidepoint(event.pos) and not self.busy:
                    self.focus = name
            for rect, action, enabled in self.buttons:
                if rect.collidepoint(event.pos) and enabled:
                    self.activate(action)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.page in {"social", "history", "profile"}:
                    self.activate("menu")
                    return True
                if self.page in {"online", "search"}:
                    return True
                if self.page == "game":
                    self.activate("menu")
                    return True
                return False
            if self.page in {"login", "register"} and not self.busy:
                names = ["username", "password"] + (["confirm"] if self.page == "register" else [])
                if event.key == pygame.K_TAB:
                    direction = -1 if event.mod & pygame.KMOD_SHIFT else 1
                    self.focus = names[(names.index(self.focus) + direction) % len(names)]
                elif event.key == pygame.K_RETURN:
                    self.submit(self.page)
                elif event.key == pygame.K_BACKSPACE:
                    setattr(self, self.focus, getattr(self, self.focus)[:-1])
            elif self.page == "social" and self.social_tab == "search" and not self.busy:
                if event.key == pygame.K_RETURN:
                    self.activate("user.search")
                elif event.key == pygame.K_BACKSPACE:
                    self.friend_query = self.friend_query[:-1]
        if event.type == pygame.TEXTINPUT and self.page in {"login", "register"} and not self.busy:
            value = getattr(self, self.focus) + event.text
            setattr(self, self.focus, value[:30 if self.focus == "username" else 128])
        elif event.type == pygame.TEXTINPUT and self.page == "social" and self.social_tab == "search" and not self.busy:
            self.friend_query = (self.friend_query + event.text)[:30]
        return True

    def text(self, value, x, y, color=theme.TEXT, font=None):
        self.screen.blit((font or self.font).render(value, True, color).convert_alpha(), (x, y))

    def button(self, label, y, action, enabled=True, x=230, width=440):
        rect = pygame.Rect(x, y, width, 44)
        enabled = enabled and not self.busy
        hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())
        state = "hover" if hovered else "normal" if enabled else "disabled"
        self.screen.blit(theme.metal(rect.size, state), rect)
        primary = action in {"login", "register", "computer", "queue.join", "user.search"} or action.startswith("invite.accept:")
        accent = theme.ORANGE if primary or hovered else "#7f929c"
        if enabled:
            pygame.draw.rect(self.screen, accent, (rect.x, rect.y + 1, 3, rect.height - 2))
        if hovered:
            pygame.draw.rect(self.screen, theme.ORANGE, rect, 1)
        surface = self.fit_text(label, rect.width - 24, theme.TEXT if enabled else "#81898e")
        self.screen.blit(surface, surface.get_rect(center=rect.center))
        self.buttons.append((rect, action, enabled))

    def fit_text(self, value, width, color):
        font = self.font
        if font.size(value)[0] > width:
            font = self.small
        while value and font.size(value)[0] > width:
            value = value[:-2]
        return font.render(value, True, color)

    def field(self, name, label, y, secret=False):
        self.text(label, 230, y, font=self.small)
        rect = pygame.Rect(230, y + 25, 440, 42)
        self.fields[name] = rect
        pygame.draw.rect(self.screen, "#13191d", rect)
        pygame.draw.rect(self.screen, "#525d63", rect, 1)
        pygame.draw.line(self.screen, theme.ORANGE if self.focus == name else "#74818a",
                         rect.bottomleft, (rect.right - 1, rect.bottom), 2)
        value = getattr(self, name)
        value = "•" * len(value) if secret else value
        while value and self.font.size(value)[0] > rect.width - 24:
            value = value[1:]
        self.text(value, rect.x + 12, rect.y + 7)
        if self.focus == name and not self.busy and pygame.time.get_ticks() % 1000 < 500:
            x = rect.x + 12 + self.font.size(value)[0]
            pygame.draw.line(self.screen, theme.COLD, (x, rect.y + 8), (x, rect.bottom - 8), 2)

    def draw(self):
        self.buttons = []
        self.fields = {}
        self.screen.blit(self.background, (0, 0))
        self.text("TIC TAC TOE", 230, 28, "#070b0e", self.title)
        self.text("TIC TAC TOE", 230, 25, font=self.title)
        self.text("К Р Е С Т И К И – Н О Л И К И", 233, 85, theme.MUTED, self.micro)
        self.text("X / O", 47, 42, theme.COLD, self.small)
        self.text("3 × 3", 791, 43, theme.MUTED, self.small)
        if self.page in {"login", "register", "menu", "profile", "search"}:
            # Quiet backing keeps the forms legible over the lit metal.
            panel = pygame.Rect(210, 132, 480, 408)
            pygame.draw.rect(self.screen, "#1b2125", panel)
            pygame.draw.line(self.screen, "#4a5358", panel.topleft, panel.topright)
            pygame.draw.line(self.screen, "#323b40", panel.bottomleft, panel.bottomright)
        self.text("TIC TAC TOE", 48, 631, theme.MUTED, self.micro)
        if self.page in {"login", "register"}:
            self.text("Вход" if self.page == "login" else "Регистрация", 230, 140)
            self.field("username", "Логин: 3–30 латинских букв, цифр или _", 190)
            self.field("password", "Пароль (при регистрации — от 8 символов)", 270, True)
            if self.page == "register":
                self.field("confirm", "Повторите пароль", 350, True)
            self.button("Войти" if self.page == "login" else "Создать аккаунт", 435, self.page)
            self.button("Создать аккаунт" if self.page == "login" else "Уже есть аккаунт — войти", 490, "switch")
        elif self.page == "menu":
            self.text(f"Привет, {self.profile['username']}!", 230, 150)
            self.button("Мой профиль", 210, "profile")
            self.button("С компьютером", 265, "computer")
            self.button("Случайный соперник", 320, "queue.join", self.connection_status == "connected")
            count = sum(row["incoming"] for row in self.social["requests"] + self.social["invitations"])
            self.button(f"Друзья и приглашения ({count})", 375, "social:friends")
            self.button("Выйти из аккаунта", 470, "logout")
        elif self.page == "search":
            self.text("Ищем случайного соперника…", 230, 210)
            self.text("Ожидаем другого игрока в очереди.", 230, 260, font=self.small)
            self.text("Поиск можно отменить в любой момент.", 230, 285, font=self.small)
            self.button("Отменить поиск", 410, "queue.cancel", self.connection_status == "connected")
        elif self.page in {"game", "online"}:
            self.draw_game()
        elif self.page == "history":
            self.draw_history()
        elif self.page == "social":
            self.draw_social()
        else:
            p = self.profile
            self.text(f"Профиль: {p['username']}", 230, 150)
            self.text(f"Рейтинг Elo: {p['rating']}", 230, 205, color=theme.COLD)
            self.text(f"Победы: {p['wins']}   Поражения: {p['losses']}   Ничьи: {p['draws']}", 230, 250)
            joined = datetime.fromisoformat(p['joined_at'].replace("Z", "+00:00")).astimezone().strftime("%d.%m.%Y")
            self.text(f"Дата регистрации: {joined}", 230, 295)
            self.button(f"Друзья ({len(self.social['friends'])})", 325, "social:friends")
            self.button("История матчей", 380, "history:1")
            self.button("Обновить профиль", 435, "profile")
            self.button("В меню", 490, "menu")
        # Wrap API validation errors so they stay within the window.
        line, y = "", 590 if self.page in {"social", "history"} else 575 if self.page in {"game", "online"} else 550
        # Keep error messages above the connection footer, even for long API errors.
        message_rect = pygame.Rect(65, y, 770, 625 - y)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(message_rect)
        for word in self.message.split():
            candidate = f"{line} {word}".strip()
            if self.small.size(candidate)[0] > 760:
                self.text(line, 70, y, theme.ORANGE, self.small)
                line, y = word, y + 23
            else:
                line = candidate
        self.text(line, 70, y, theme.ORANGE, self.small)
        self.screen.set_clip(previous_clip)
        if self.token:
            statuses = {"connecting": "Подключение…", "connected": "Соединение установлено",
                        "reconnecting": "Связь потеряна. Переподключение…", "error": "Ошибка соединения"}
            self.text(statuses.get(self.connection_status, ""), 230, 625, theme.COLD, self.small)

    def draw_social(self):
        tabs = [("friends", "Друзья"), ("requests", "Заявки"), ("invitations", "Приглашения"), ("search", "Поиск")]
        for index, (key, label) in enumerate(tabs):
            count = f" ({len(self.social[key])})" if key != "search" else ""
            self.button(label + count, 140, f"social:{key}", x=40 + index * 210, width=190)
            if key == self.social_tab:
                pygame.draw.rect(self.screen, theme.COLD, pygame.Rect(40 + index * 210, 140, 190, 44), 1)
        rows = self.user_results if self.social_tab == "search" else self.social[self.social_tab]
        y_start = 210
        if self.social_tab == "search":
            self.field("friend_query", "Логин или начало логина (от 3 символов)", 190)
            self.button("Найти", 215, "user.search", x=685, width=150)
            y_start = 275
        self.social_page = min(self.social_page, max(0, (len(rows) - 1) // 4))
        if not rows:
            self.text("Список пуст." if self.social_tab != "search" else "Введите логин и нажмите «Найти».", 55, y_start, font=self.small)
        for index, row in enumerate(rows[self.social_page * 4:self.social_page * 4 + 4]):
            y = y_start + index * 55
            pygame.draw.line(self.screen, "#39444b", (55, y + 49), (835, y + 49))
            self.text(row["username"], 55, y, font=self.small)
            connected = self.connection_status == "connected"
            if self.social_tab == "friends":
                status = "Занят" if row["online"] and row["busy"] else "Онлайн" if row["online"] else "Не в сети"
                self.text(f"{status} · Elo {row['rating']}", 55, y + 23, theme.COLD if row["online"] else theme.MUTED, self.small)
                self.button("Пригласить", y, f"invite.send:{row['user_id']}", connected and row["online"] and not row["busy"], x=520, width=150)
                self.button("Удалить", y, f"friend.remove:{row['user_id']}", x=685, width=150)
            elif self.social_tab == "requests":
                self.text("Входящая заявка" if row["incoming"] else "Заявка отправлена", 55, y + 23, font=self.small)
                if row["incoming"]:
                    self.button("Принять", y, f"friend.accept:{row['user_id']}", x=520, width=150)
                self.button("Отклонить" if row["incoming"] else "Отменить", y, f"friend.remove:{row['user_id']}", x=685, width=150)
            elif self.social_tab == "invitations":
                self.text("Рейтинговый матч · " + ("входящее" if row["incoming"] else "отправлено"), 55, y + 23, font=self.small)
                if row["incoming"]:
                    self.button("Играть", y, f"invite.accept:{row['id']}", connected, x=520, width=150)
                self.button("Отклонить" if row["incoming"] else "Отменить", y,
                            f"invite.decline:{row['id']}" if row["incoming"] else f"invite.cancel:{row['id']}", connected, x=685, width=150)
            else:
                existing = any(item["user_id"] == row["user_id"] for item in self.social["friends"] + self.social["requests"])
                self.button("Добавить" if not existing else "Добавлен", y, f"friend.request:{row['user_id']}", not existing, x=685, width=150)
        self.button("Назад", 505, f"socialpage:{self.social_page - 1}", self.social_page > 0, x=150, width=280)
        self.button("Далее", 505, f"socialpage:{self.social_page + 1}", (self.social_page + 1) * 4 < len(rows), x=470, width=280)
        self.button("В меню", 550, "menu")

    def draw_game(self):
        if self.page == "online":
            m = self.match
            self.text(f"Вы — {m['symbol']} · Соперник: {m['opponent']}", 230, 119, font=self.small)
            labels = {m["symbol"]: "Вы победили!", "O" if m["symbol"] == "X" else "X": "Вы проиграли",
                      "draw": "Ничья", "abandoned": "Матч отменён: оба игрока отключились"}
            status = labels.get(m["result"], "Ваш ход" if m["turn"] == m["symbol"] else "Ход соперника…")
            if m["reason"] in {"resign", "disconnect"}:
                status += " (сдача)" if m["reason"] == "resign" else " (обрыв связи)"
        else:
            self.text("Вы — X · Компьютер — O · Без рейтинга", 230, 119, font=self.small)
            labels = {"X": "Вы победили!", "O": "Компьютер победил", "draw": "Ничья"}
            status = labels.get(self.game.result, "Ваш ход" if self.game.turn == "X" else "Ход компьютера…")
        self.text(status, 315, 143, theme.ORANGE, self.small)
        frame = self.board_rect.inflate(18, 18)
        pygame.draw.rect(self.screen, "#101619", frame)
        pygame.draw.rect(self.screen, "#5d6d76", frame, 1)
        for index, symbol in enumerate(self.game.board):
            cell = pygame.Rect(self.board_rect.x + index % 3 * 90,
                               self.board_rect.y + index // 3 * 90, 90, 90)
            winning = self.game.winning_line and index in self.game.winning_line
            plate = cell.inflate(-6, -6)
            hovered = not symbol and not self.game.result and cell.collidepoint(pygame.mouse.get_pos())
            self.screen.blit(theme.metal(plate.size, "winning" if winning else "hover" if hovered else "cell"), plate)
            if winning:
                pygame.draw.rect(self.screen, theme.ORANGE, plate, 1)
            if not symbol:
                self.text(str(index + 1).zfill(2), plate.x + 6, plate.y + 5, "#78868e", self.micro)
            if symbol == "X":
                pygame.draw.line(self.screen, theme.COLD, (cell.x + 24, cell.y + 24), (cell.right - 24, cell.bottom - 24), 5)
                pygame.draw.line(self.screen, theme.COLD, (cell.right - 24, cell.y + 24), (cell.x + 24, cell.bottom - 24), 5)
            elif symbol == "O":
                pygame.draw.circle(self.screen, theme.ORANGE, cell.center, 25, 5)
        if self.page == "online":
            self.button("В меню" if self.match["result"] else "Сдаться", 460,
                        "match.dismiss" if self.match["result"] else "match.resign",
                        self.connection_status == "connected")
            if self.match.get("rating_applied"):
                m = self.match
                label = f"Elo: {m['rating_before']} → {m['rating_after']} ({m['rating_delta']:+d})"
            elif self.match.get("rated") and not self.match["result"]:
                label = "Рейтинговый матч · Elo"
            else:
                label = "Рейтинг не изменён."
            self.text(label, 230, 520, font=self.small)
        else:
            self.button("Сыграть ещё раз" if self.game.result else "Начать заново", 460, "computer")
            self.button("В меню", 515, "menu")

    def draw_history(self):
        self.text(f"История матчей · страница {self.history_page}", 230, 140)
        results = self.history["results"]
        if not results:
            self.text("Завершённых сетевых матчей пока нет.", 150, 220, font=self.small)
        labels = {"win": "Победа", "loss": "Поражение", "draw": "Ничья", "cancelled": "Отмена"}
        reasons = {"line": "три в ряд", "board_full": "поле заполнено", "resign": "сдача", "disconnect": "обрыв связи"}
        for i, match in enumerate(results):
            y = 185 + i * 58
            pygame.draw.line(self.screen, "#39444b", (150, y + 52), (750, y + 52))
            when = datetime.fromisoformat(match["finished_at"].replace("Z", "+00:00")).astimezone().strftime("%d.%m.%Y %H:%M")
            self.text(f"{labels[match['outcome']]} · {match['opponent']} · вы {match['symbol']}", 150, y, font=self.small)
            rating = (f"Elo {match['rating_before']} → {match['rating_after']} ({match['rating_delta']:+d})"
                      if match["rating_applied"] else "без рейтинга")
            self.text(f"{when} · {reasons.get(match['reason'], match['reason'])} · {rating}",
                      150, y + 25, theme.MUTED, self.small)
        self.button("Назад", 490, f"history:{self.history_page - 1}", bool(self.history["previous"]), x=150, width=280)
        self.button("Далее", 490, f"history:{self.history_page + 1}", bool(self.history["next"]), x=470, width=280)
        self.button("В профиль", 540, "profile")

    def run(self):
        clock = pygame.time.Clock()
        pygame.key.start_text_input()
        running = True
        while running:
            self.poll()
            self.update_game()
            self.draw()
            for event in pygame.event.get():
                if not self.handle_event(event):
                    running = False
            pygame.display.flip()
            clock.tick(60)
        self.close_session()
        pygame.quit()
