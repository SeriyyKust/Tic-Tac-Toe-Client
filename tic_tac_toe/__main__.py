import argparse
import os
from queue import Empty, Queue
from threading import Thread

import pygame

from .network import check_connection, server_url


def main():
    parser = argparse.ArgumentParser(description="Tic tac toe desktop client")
    parser.add_argument("--server", default=os.environ.get("TICTACTOE_SERVER_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--smoke-test", action="store_true", help="Check rendering and network, then exit")
    args = parser.parse_args()
    try:
        args.server = server_url(args.server)
    except ValueError as error:
        parser.error(str(error))
    if not args.smoke_test:
        from .ui import App
        App(args.server).run()
        return
    pygame.init()
    screen = pygame.display.set_mode((800, 560))
    pygame.display.set_caption("Tic tac toe")
    font = pygame.font.Font(None, 30)
    title_font = pygame.font.Font(None, 64)
    clock = pygame.time.Clock()
    results = Queue()
    status = "Checking server..."
    busy = False
    success = False
    button = pygame.Rect(220, 415, 360, 55)

    def probe():
        try:
            check_connection(args.server)
            results.put((True, "HTTP + WebSocket + PostgreSQL + Redis: OK"))
        except Exception as error:
            results.put((False, f"Connection failed: {type(error).__name__}"))

    def start_probe():
        nonlocal busy, status
        busy = True
        status = "Checking server..."
        Thread(target=probe, daemon=True).start()

    start_probe()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and button.collidepoint(event.pos) and not busy:
                start_probe()
        try:
            success, status = results.get_nowait()
            busy = False
        except Empty:
            pass
        screen.fill("#101827")
        screen.blit(title_font.render("Tic tac toe", True, "#f3f6ff"), (270, 65))
        screen.blit(font.render("Development build / Connection check", True, "#aab8cd"), (180, 140))
        for offset in (1, 2):
            pygame.draw.line(screen, "#506581", (325 + offset * 50, 205), (325 + offset * 50, 355), 3)
            pygame.draw.line(screen, "#506581", (325, 205 + offset * 50), (475, 205 + offset * 50), 3)
        pygame.draw.line(screen, "#61d7d1", (338, 218), (362, 242), 4)
        pygame.draw.line(screen, "#61d7d1", (362, 218), (338, 242), 4)
        pygame.draw.circle(screen, "#f4bf75", (400, 280), 16, 4)
        color = "#61d7d1" if success else "#f4bf75"
        label = font.render(status, True, color)
        screen.blit(label, label.get_rect(center=(400, 385)))
        pygame.draw.rect(screen, "#273b56" if busy else "#345679", button, border_radius=10)
        label = font.render("Checking..." if busy else "Check connection again", True, "#ffffff")
        screen.blit(label, label.get_rect(center=button.center))
        pygame.display.flip()
        clock.tick(60)
        if args.smoke_test and not busy:
            print(status)
            running = False
    pygame.quit()
    if args.smoke_test and not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
