"""Validate network data before it reaches the Pygame thread."""
from datetime import datetime


def require(condition):
    if not condition:
        raise ValueError("Invalid server response")


def fields(value, schema):
    require(isinstance(value, dict))
    for key, kind in schema.items():
        require(key in value and type(value[key]) is kind)


def profile(value):
    fields(value, {"id": int, "username": str, "rating": int, "wins": int,
                   "losses": int, "draws": int, "joined_at": str})
    datetime.fromisoformat(value["joined_at"].replace("Z", "+00:00"))


def social(value):
    fields(value, {"friends": list, "requests": list, "invitations": list})
    for row in value["friends"]:
        fields(row, {"user_id": int, "username": str, "online": bool, "busy": bool, "rating": int})
    for row in value["requests"]:
        fields(row, {"user_id": int, "username": str, "incoming": bool})
    for row in value["invitations"]:
        fields(row, {"id": int, "username": str, "incoming": bool, "expires_at": str})


def rating(value):
    fields(value, {"rating_applied": bool})
    if value["rating_applied"]:
        fields(value, {"rating_before": int, "rating_after": int, "rating_delta": int})


def state(value):
    fields(value, {"type": str, "protocol": int, "searching": bool})
    require(value["type"] == "session.state" and value["protocol"] == 1)
    profile(value.get("profile"))
    social(value.get("social"))
    require("match" in value)
    match = value["match"]
    if match is not None:
        fields(match, {"id": int, "symbol": str, "opponent": str, "board": list,
                       "turn": str, "result": str, "reason": str, "version": int})
        require(match["symbol"] in ("X", "O") and match["turn"] in ("X", "O"))
        require(match["result"] in ("", "X", "O", "draw", "abandoned"))
        require(len(match["board"]) == 9 and all(cell in ("", "X", "O") for cell in match["board"]))
        line = match.get("winning_line")
        require(line is None or (isinstance(line, list) and len(line) == 3 and all(type(i) is int and 0 <= i < 9 for i in line)))
        require("winning_line" in match)
        rating(match)


def http(path, value):
    route = path.split("?")[0]
    if route in {"/api/auth/login/", "/api/auth/register/"}:
        fields(value, {"token": str})
        require(bool(value["token"]))
        profile(value.get("profile"))
    elif route == "/api/me/":
        profile(value)
    elif route == "/api/social/":
        social(value)
    elif route == "/api/users/":
        fields(value, {"results": list})
        for row in value["results"]:
            fields(row, {"user_id": int, "username": str})
    elif route == "/api/me/history/":
        fields(value, {"results": list, "count": int})
        require("next" in value and "previous" in value)
        for row in value["results"]:
            fields(row, {"id": int, "opponent": str, "symbol": str, "outcome": str, "reason": str, "finished_at": str})
            require(row["outcome"] in ("win", "loss", "draw", "cancelled"))
            datetime.fromisoformat(row["finished_at"].replace("Z", "+00:00"))
            rating(row)
    elif route == "/api/auth/logout/":
        require(value is None)
    return value
