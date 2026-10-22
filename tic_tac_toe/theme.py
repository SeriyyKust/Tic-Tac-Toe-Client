"""Procedural steel surfaces. Built once; no textures or extra dependencies."""
from functools import lru_cache
from math import exp
from random import Random

import pygame

TEXT = "#e2e6e8"
MUTED = "#a0aab0"
COLD = "#9bc7d8"
ORANGE = "#f39a50"


@lru_cache(maxsize=4)
def background(size):
    width, height = size
    # Low-resolution light field, smoothly scaled before fine brushed grain.
    light = pygame.Surface((180, 132))
    for y in range(132):
        for x in range(180):
            cold = exp(-((x - 12) / 34) ** 2 - ((y - 37) / 65) ** 2)
            fire = exp(-((x - 173) / 27) ** 2 - ((y - 104) / 48) ** 2)
            steel = 12 + 11 * (1 - y / 132)
            light.set_at((x, y), (int(steel + cold * 17 + fire * 46),
                                  int(steel + cold * 29 + fire * 21),
                                  int(steel + cold * 36 + fire * 7)))
    surface = pygame.transform.smoothscale(light, size)
    rng = Random(34)
    grain = pygame.Surface(size, pygame.SRCALPHA)
    for y in range(0, height, 2):
        pygame.draw.line(grain, (170, 185, 190, rng.randrange(2, 9)), (0, y), (width, y))
    for _ in range(1600):
        x, y = rng.randrange(width), rng.randrange(height)
        pygame.draw.line(grain, (180, 197, 205, rng.randrange(3, 13)), (x, y),
                         (min(width - 1, x + rng.randrange(3, 65)), y))
    surface.blit(grain, (0, 0))
    # Architectural seams and quiet drafting marks stay outside the content.
    for x in (22, width - 23):
        pygame.draw.line(surface, "#3a4348", (x, 22), (x, height - 28))
        for y in range(142, height - 50, 12):
            pygame.draw.line(surface, "#505a5e", (x, y), (x + (5 if x < 50 else -5), y))
    pygame.draw.line(surface, "#596267", (40, 114), (width - 40, 114))
    pygame.draw.line(surface, ORANGE, (230, 114), (298, 114), 3)
    pygame.draw.line(surface, "#42494d", (40, 615), (width - 40, 615))
    for x in (22, width - 23):
        for y in (22, height - 28):
            pygame.draw.circle(surface, "#737a7d", (x, y), 3, 1)
            pygame.draw.line(surface, "#737a7d", (x - 1, y + 1), (x + 1, y - 1))
    # Keep the background fully opaque, including SDL scaled-surface alpha.
    surface = surface.convert_alpha()
    surface.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MAX)
    return surface


@lru_cache(maxsize=64)
def metal(size, state="normal"):
    """Cached bevelled plates, with a distinct hover and disabled treatment."""
    surface = pygame.Surface(size)
    width, height = size
    top, bottom = {"normal": (65, 37), "hover": (85, 51),
                   "disabled": (37, 28), "cell": (47, 29),
                   "winning": (88, 48)}[state]
    for y in range(height):
        value = int(top + (bottom - top) * y / max(1, height - 1))
        value += 1 if y % 3 == 0 else 0
        pygame.draw.line(surface, (value, value + 3, value + 5), (0, y), (width, y))
    pygame.draw.rect(surface, "#14191c", surface.get_rect(), 1)
    pygame.draw.line(surface, "#829097" if state == "hover" else "#626b70",
                     (1, 1), (width - 2, 1))
    pygame.draw.line(surface, "#41494e", (1, 1), (1, height - 2))
    return surface
