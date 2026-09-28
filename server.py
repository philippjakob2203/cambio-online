import functools
import json
import os
import random
import secrets
import string
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
SUITS = [
    ("♠", "Pik", "black"),
    ("♥", "Herz", "red"),
    ("♣", "Kreuz", "black"),
    ("♦", "Karo", "red"),
]
RANKS = [
    (1, "A", "Ass"), (2, "2", "2"), (3, "3", "3"), (4, "4", "4"),
    (5, "5", "5"), (6, "6", "6"), (7, "7", "7"), (8, "8", "8"),
    (9, "9", "9"), (10, "10", "10"), (11, "B", "Bube"),
    (12, "D", "Dame"), (13, "K", "König"),
]
MAX_PLAYERS = 13
ROOMS = {}
ROOMS_LOCK = threading.RLock()


def card_points(card):
    rank = card["rankValue"]
    if rank == 0:
        return 0
    if rank == 1:
        return 1
    if rank <= 10:
        return rank
    if rank in (11, 12) or (rank == 13 and card["color"] == "black"):
        return 10
    if rank == 13:
        return -2
    return 0


def make_deck():
    cards = []
    for symbol, suit_name, color in SUITS:
        for value, short, name in RANKS:
            cards.append({
                "id": secrets.token_hex(8), "suit": symbol, "suitName": suit_name,
                "color": color, "rankValue": value, "short": short,
                "name": name, "isJoker": False,
            })
    for _ in range(3):
        cards.append({
            "id": secrets.token_hex(8), "suit": "J", "suitName": "Joker",
            "color": "black", "rankValue": 0, "short": "JOK",
            "name": "Joker", "isJoker": True,
        })
    random.shuffle(cards)
    return cards


def new_player(name, player_type="human", player_id=None):
    return {
        "id": player_id or secrets.token_urlsafe(12),
        "name": name,
        "type": player_type,
        "score": 0,
        "hand": [],
        "revealUntil": 0,
    }


def new_room(host_name):
    host = new_player(host_name)
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    while code in ROOMS:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    room = {
        "code": code,
        "hostId": host["id"],
        "players": [host],
        "phase": "lobby",
        "deck": [],
        "discard": [],
        "drawnCard": None,
        "currentIndex": 0,
        "round": 0,
        "starterIndex": 0,
        "handSize": 4,
        "nextAdjustment": None,
        "schottenCaller": None,
        "schottenRemaining": None,
        "reactionUntil": 0,
        "cpuReactionAt": {},
        "log": ["Raum erstellt. Weitere Personen können mit dem Raumcode beitreten."],
        "revision": 0,
        "winner": None,
        "createdAt": time.time(),
    }
    return room, host


def add_log(room, message):
    room["log"].insert(0, message)
    del room["log"][12:]


def bump(room):
    room["revision"] += 1


def find_player(room, player_id):
    return next((player for player in room["players"] if player["id"] == player_id), None)


def get_room(room_code):
    room = ROOMS.get(room_code.upper())
    if room is None:
        raise ValueError("Raum nicht gefunden.")
    return room


def is_host(room, player_id):
    if room["hostId"] != player_id:
        raise ValueError("Nur die Spielleitung darf das tun.")


def can_add_player(room):
    if len(room["players"]) >= MAX_PLAYERS:
        raise ValueError("Mit einem Kartendeck können höchstens 13 Personen mitspielen.")


def get_player_card_value(card):
    return card_points(card)


def refill_deck(room):
    if room["deck"]:
        return
    if len(room["discard"]) > 1:
        top = room["discard"].pop()
        room["deck"] = room["discard"]
        room["discard"] = [top]
        random.shuffle(room["deck"])


def start_round(room):
    room["round"] += 1
    room["phase"] = "turn"
    room["deck"] = make_deck()
    room["discard"] = []
    room["drawnCard"] = None
    room["schottenCaller"] = None
    room["schottenRemaining"] = None
    room["reactionUntil"] = 0
    room["cpuReactionAt"] = {}
    now = time.time()
    for index, player in enumerate(room["players"]):
        hand_size = room["handSize"]
        if room["nextAdjustment"] and room["nextAdjustment"]["playerId"] == player["id"]:
            hand_size = room["nextAdjustment"]["count"]
        player["hand"] = [room["deck"].pop() for _ in range(hand_size)]
        player["revealUntil"] = now + 5 if player["type"] == "human" else 0
    room["nextAdjustment"] = None
    room["starterIndex"] %= len(room["players"])
    room["currentIndex"] = room["starterIndex"]
    add_log(room, f"Runde {room['round']} gestartet. {room['players'][room['currentIndex']]['name']} beginnt.")


def start_reaction(room):
    room["phase"] = "reaction"
    room["reactionUntil"] = time.time() + 1.5
    room["cpuReactionAt"] = {
        player["id"]: time.time() + random.uniform(0.2, 0.9)
        for player in room["players"] if player["type"] == "cpu"
    }


def matching_index(player, top_card):
    for index, card in enumerate(player["hand"]):
        if card["rankValue"] == top_card["rankValue"]:
            return index
    return None


def score_value(card):
    if card["rankValue"] == 13 and card["color"] == "black":
        return 10
    if card["rankValue"] == 13 and card["color"] == "red":
        return -2
    return card["rankValue"] if card["rankValue"] <= 10 else 10


def finish_round(room):
    for player in room["players"]:
        black_kings = sum(1 for card in player["hand"] if card["rankValue"] == 13 and card["color"] == "black")
        points = -12 if black_kings == 2 else sum(score_value(card) for card in player["hand"])
        player["score"] += points

    if any(player["score"] >= 50 for player in room["players"]):
        room["phase"] = "finished"
        room["winner"] = min(room["players"], key=lambda player: player["score"])["id"]
        winner = find_player(room, room["winner"])
        add_log(room, f"Spiel beendet. {winner['name']} gewinnt mit den wenigsten Punkten.")
        return

    if room["schottenCaller"]:
        caller = find_player(room, room["schottenCaller"])
        lowest_score = min(player["score"] for player in room["players"])
        adjustment = 3 if caller["score"] == lowest_score else 5
        room["nextAdjustment"] = {"playerId": caller["id"], "count": adjustment}
        add_log(room, f"{caller['name']} bekommt in der nächsten Runde {adjustment} Karten; alle anderen bekommen 4.")
    else:
        room["nextAdjustment"] = None
        add_log(room, "Runde beendet. In der nächsten Runde bekommen alle 4 Karten.")

    room["starterIndex"] = (room["starterIndex"] + 1) % len(room["players"])
    room["handSize"] = 4
    start_round(room)


def end_turn(room, actor_index):
    if room["schottenRemaining"] is not None:
        remaining = room["schottenRemaining"]
        if actor_index in remaining:
            remaining.remove(actor_index)
        if not remaining:
            finish_round(room)
            return
    room["currentIndex"] = (actor_index + 1) % len(room["players"])
    room["phase"] = "turn"
    room["drawnCard"] = None


def attempt_match(room, player_index, card_index, target_index=None, gift_index=None):
    if room["phase"] != "reaction" or not room["discard"]:
        return False
    player = room["players"][player_index]
    target_index = player_index if target_index is None else target_index
    if target_index < 0 or target_index >= len(room["players"]):
        return False
    target = room["players"][target_index]
    if card_index < 0 or card_index >= len(target["hand"]):
        return False
    card = target["hand"][card_index]
    if card["rankValue"] != room["discard"][-1]["rankValue"]:
        refill_deck(room)
        if room["deck"]:
            player["hand"].append(room["deck"].pop())
        add_log(room, f"{player['name']} legt falsch und zieht eine verdeckte Strafkarte.")
        bump(room)
        return False

    if target_index != player_index:
        if gift_index is None or gift_index < 0 or gift_index >= len(player["hand"]):
            raise ValueError("Wähle eine eigene Karte als Ersatz aus.")
        gift = player["hand"].pop(gift_index)
        target["hand"].append(gift)
    target["hand"].pop(card_index)
    room["discard"].append(card)
    if target_index == player_index:
        add_log(room, f"{player['name']} legt schnell {card['short']}{card['suit']} ab.")
    else:
        add_log(room, f"{player['name']} erwischt eine passende Karte von {target['name']} und gibt eine eigene dafür.")
    actor_index = room["currentIndex"]
    if not player["hand"]:
        add_log(room, f"{player['name']} hat keine Karten mehr. Die Runde endet sofort.")
        finish_round(room)
    else:
        end_turn(room, actor_index)
    bump(room)
    return True


def process_cpu_turn(room):
    player = room["players"][room["currentIndex"]]
    refill_deck(room)
    if not room["deck"]:
        end_turn(room, room["currentIndex"])
        return
    drawn = room["deck"].pop()
    highest = max(range(len(player["hand"])), key=lambda index: get_player_card_value(player["hand"][index]))
    if player["hand"] and get_player_card_value(drawn) < get_player_card_value(player["hand"][highest]):
        replaced = player["hand"][highest]
        player["hand"][highest] = drawn
        room["discard"].append(replaced)
        add_log(room, f"{player['name']} tauscht eine Karte und legt eine ab.")
    else:
        room["discard"].append(drawn)
        add_log(room, f"{player['name']} legt eine Karte ab.")
    start_reaction(room)
    bump(room)


def snapshot(room, player_id):
    viewer = find_player(room, player_id)
    if viewer is None:
        raise ValueError("Du bist diesem Raum nicht beigetreten.")
    now = time.time()
    players = []
    for player in room["players"]:
        visible = player["id"] == player_id and now < player["revealUntil"]
        players.append({
            "id": player["id"],
            "name": player["name"],
            "type": player["type"],
            "score": player["score"],
            "hand": [card if visible and index < 2 else None for index, card in enumerate(player["hand"])],
            "cardCount": len(player["hand"]),
            "isHost": player["id"] == room["hostId"],
        })
    current = room["players"][room["currentIndex"]] if room["players"] else None
    return {
        "code": room["code"],
        "revision": room["revision"],
        "phase": room["phase"],
        "players": players,
        "hostId": room["hostId"],
        "viewerId": player_id,
        "currentPlayerId": current["id"] if current else None,
        "currentPlayerName": current["name"] if current else None,
        "round": room["round"],
        "deckCount": len(room["deck"]),
        "discardTop": room["discard"][-1] if room["discard"] else None,
        "discardCount": len(room["discard"]),
        "drawnCard": room["drawnCard"] if current and current["id"] == player_id else None,
        "reactionRemaining": max(0, room["reactionUntil"] - now) if room["phase"] == "reaction" else 0,
        "log": list(room["log"]),
        "winnerId": room["winner"],
        "schottenCallerId": room["schottenCaller"],
    }


class GameHandler(SimpleHTTPRequestHandler):
    server_version = "Cambio/1.0"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16000:
            raise ValueError("Anfrage zu groß.")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_json(200, {"ok": True})
            return
        if parsed.path.startswith("/api/room/"):
            room_code = parsed.path.split("/")[3].upper()
            player_id = parse_qs(parsed.query).get("player_id", [""])[0]
            with ROOMS_LOCK:
                try:
                    self.send_json(200, snapshot(get_room(room_code), player_id))
                except ValueError as error:
                    self.send_json(404, {"error": str(error)})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self.read_json()
            with ROOMS_LOCK:
                if parsed.path == "/api/rooms":
                    room, host = new_room(clean_name(body.get("name"), "Spielleitung"))
                    ROOMS[room["code"]] = room
                    bump(room)
                    self.send_json(201, {"code": room["code"], "playerId": host["id"], "revision": room["revision"]})
                    return

                parts = parsed.path.strip("/").split("/")
                if len(parts) < 3 or parts[0] != "api" or parts[1] != "room":
                    self.send_json(404, {"error": "Endpunkt nicht gefunden."})
                    return
                room = get_room(parts[2])
                if len(parts) == 4 and parts[3] == "join":
                    if room["phase"] != "lobby":
                        raise ValueError("Diese Partie hat bereits begonnen.")
                    can_add_player(room)
                    player = new_player(clean_name(body.get("name"), f"Spieler {len(room['players']) + 1}"))
                    room["players"].append(player)
                    add_log(room, f"{player['name']} ist beigetreten.")
                    bump(room)
                    self.send_json(201, {"code": room["code"], "playerId": player["id"], "revision": room["revision"]})
                    return

                player_id = body.get("playerId", "")
                is_host(room, player_id)
                if len(parts) == 4 and parts[3] == "cpu":
                    if room["phase"] != "lobby":
                        raise ValueError("CPUs können nur vor Spielbeginn hinzugefügt werden.")
                    can_add_player(room)
                    number = 1 + sum(1 for player in room["players"] if player["type"] == "cpu")
                    player = new_player(f"CPU {number}", "cpu")
                    room["players"].append(player)
                    add_log(room, f"{player['name']} wurde hinzugefügt.")
                    bump(room)
                    self.send_json(200, {"ok": True})
                    return

                if len(parts) == 5 and parts[3] == "cpu" and parts[4] == "remove":
                    if room["phase"] != "lobby":
                        raise ValueError("CPUs können nur in der Lobby entfernt werden.")
                    cpu_id = body.get("cpuId")
                    room["players"] = [player for player in room["players"] if not (player["id"] == cpu_id and player["type"] == "cpu")]
                    if len(room["players"]) == 0:
                        raise ValueError("Mindestens eine Person muss im Raum bleiben.")
                    add_log(room, "CPU entfernt.")
                    bump(room)
                    self.send_json(200, {"ok": True})
                    return

                if len(parts) == 4 and parts[3] == "start":
                    if room["phase"] != "lobby":
                        raise ValueError("Die Partie läuft bereits.")
                    if len(room["players"]) < 2:
                        raise ValueError("Füge mindestens eine weitere Person oder CPU hinzu.")
                    if len(room["players"]) > MAX_PLAYERS:
                        raise ValueError("Mit einem Kartendeck können höchstens 13 Personen mitspielen.")
                    room["handSize"] = 4
                    start_round(room)
                    bump(room)
                    self.send_json(200, {"ok": True})
                    return

                if len(parts) == 4 and parts[3] == "action":
                    self.handle_action(room, player_id, body)
                    return

                self.send_json(404, {"error": "Endpunkt nicht gefunden."})
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": f"Serverfehler: {error}"})

    def handle_action(self, room, player_id, body):
        player = find_player(room, player_id)
        if not player or player["type"] != "human":
            raise ValueError("Spieler nicht gefunden.")
        action = body.get("action")
        player_index = room["players"].index(player)

        if action == "match":
            if room["phase"] != "reaction":
                raise ValueError("Gerade läuft kein Reaktionsfenster.")
            target_index = int(body.get("targetPlayerIndex", player_index))
            attempt_match(
                room,
                player_index,
                int(body.get("targetCardIndex", body.get("cardIndex", -1))),
                target_index,
                int(body["giftCardIndex"]) if body.get("giftCardIndex") is not None else None,
            )
            self.send_json(200, {"ok": True})
            return

        if room["phase"] != "turn" or room["players"][room["currentIndex"]]["id"] != player_id:
            raise ValueError("Du bist gerade nicht am Zug.")
        if action == "draw_deck":
            if room["drawnCard"]:
                raise ValueError("Du hast bereits eine Karte gezogen.")
            refill_deck(room)
            if not room["deck"]:
                raise ValueError("Der Nachziehstapel ist leer.")
            room["drawnCard"] = room["deck"].pop()
            add_log(room, f"{player['name']} zieht eine Karte vom Stapel.")
        elif action == "draw_discard":
            if room["drawnCard"]:
                raise ValueError("Du hast bereits eine Karte gezogen.")
            if not room["discard"]:
                raise ValueError("Der Ablagestapel ist leer.")
            room["drawnCard"] = room["discard"].pop()
            add_log(room, f"{player['name']} nimmt die oberste Ablagekarte.")
        elif action == "discard_drawn":
            if not room["drawnCard"]:
                raise ValueError("Es gibt keine gezogene Karte zum Ablegen.")
            card = room["drawnCard"]
            room["discard"].append(card)
            room["drawnCard"] = None
            add_log(room, f"{player['name']} legt eine Karte ab.")
            start_reaction(room)
        elif action == "swap":
            if not room["drawnCard"]:
                raise ValueError("Ziehe zuerst eine Karte.")
            card_index = int(body.get("cardIndex", -1))
            if card_index < 0 or card_index >= len(player["hand"]):
                raise ValueError("Diese Handkarte gibt es nicht.")
            replaced = player["hand"][card_index]
            player["hand"][card_index] = room["drawnCard"]
            room["discard"].append(replaced)
            room["drawnCard"] = None
            add_log(room, f"{player['name']} tauscht eine verdeckte Karte; die ersetzte Karte liegt auf der Ablage.")
            start_reaction(room)
        elif action == "schotten":
            if room["drawnCard"]:
                raise ValueError("Lege zuerst die gezogene Karte ab oder tausche sie.")
            room["schottenCaller"] = player_id
            caller_index = room["currentIndex"]
            room["schottenRemaining"] = [
                (caller_index + offset) % len(room["players"])
                for offset in range(1, len(room["players"]))
            ]
            add_log(room, f"{player['name']} ruft Schotten dicht. Alle anderen sind noch einmal dran.")
            if not room["schottenRemaining"]:
                finish_round(room)
            else:
                room["currentIndex"] = room["schottenRemaining"][0]
        else:
            raise ValueError("Unbekannte Aktion.")

        bump(room)
        self.send_json(200, {"ok": True})

    def log_message(self, _format, *_args):
        return


def clean_name(value, fallback):
    name = " ".join(str(value or "").split())[:24]
    return name or fallback


def run_cpu_loop():
    while True:
        now = time.time()
        with ROOMS_LOCK:
            for room in list(ROOMS.values()):
                if room["phase"] == "reaction":
                    cpu_found = False
                    for player_index, player in enumerate(room["players"]):
                        ready_at = room["cpuReactionAt"].get(player["id"])
                        if ready_at and now >= ready_at and room["discard"]:
                            match = matching_index(player, room["discard"][-1])
                            if match is not None:
                                attempt_match(room, player_index, match)
                                cpu_found = True
                                break
                            room["cpuReactionAt"].pop(player["id"], None)
                    if not cpu_found and room["phase"] == "reaction" and now >= room["reactionUntil"]:
                        actor_index = room["currentIndex"]
                        room["reactionUntil"] = 0
                        room["cpuReactionAt"] = {}
                        end_turn(room, actor_index)
                        bump(room)
                elif room["phase"] == "turn" and room["players"]:
                    player = room["players"][room["currentIndex"]]
                    if player["type"] == "cpu":
                        process_cpu_turn(room)
        time.sleep(0.05)


def main():
    threading.Thread(target=run_cpu_loop, daemon=True).start()
    port = int(os.environ.get("PORT", "8002"))
    handler = functools.partial(GameHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Cambio server listening on port {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
