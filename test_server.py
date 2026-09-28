import unittest

import server


def card(rank, card_id):
    return {
        "id": str(card_id),
        "rankValue": rank,
        "short": str(rank),
        "suit": "♠",
        "color": "black",
        "isJoker": False,
    }


def make_room(rank):
    actor = server.new_player("Mina")
    target = server.new_player("Sam")
    actor["hand"] = [card(2, "a2"), card(9, "a9"), card(5, "a5")]
    target["hand"] = [card(7, "b7"), card(4, "b4")]
    room = {
        "code": "TEST01",
        "revision": 0,
        "hostId": actor["id"],
        "players": [actor, target],
        "phase": "special",
        "deck": [],
        "discard": [],
        "drawnCard": None,
        "currentIndex": 0,
        "round": 1,
        "reactionUntil": 0,
        "cpuReactionAt": {},
        "cpuTurnAt": 0,
        "pendingSpecial": {
            "actorId": actor["id"],
            "rank": rank,
            "step": "offer",
            "deadline": server.time.time() + 30,
        },
        "privateReveal": None,
        "schottenCaller": None,
        "schottenRemaining": None,
        "log": [],
        "winner": None,
    }
    return room, actor, target


class SpecialCardTests(unittest.TestCase):
    def accept(self, room, actor):
        server.handle_special_action(room, actor, {"specialAction": "accept"})

    def test_own_peek_is_private(self):
        room, actor, target = make_room(7)
        self.accept(room, actor)
        server.handle_special_action(room, actor, {"specialAction": "select_own", "cardIndex": 2})
        self.assertEqual(server.snapshot(room, actor["id"])["players"][0]["hand"][2]["rankValue"], 5)
        self.assertTrue(all(card is None for card in server.snapshot(room, target["id"])["players"][0]["hand"]))
        self.assertEqual(server.snapshot(room, target["id"])["specialResult"], [])

    def test_opponent_peek_is_private(self):
        room, actor, target = make_room(9)
        self.accept(room, actor)
        server.handle_special_action(room, actor, {"specialAction": "select_target", "targetPlayerIndex": 1, "cardIndex": 1})
        self.assertEqual(server.snapshot(room, actor["id"])["specialResult"][0]["rankValue"], 4)
        self.assertEqual(server.snapshot(room, target["id"])["specialResult"], [])
        self.assertTrue(all(card is None for card in server.snapshot(room, target["id"])["players"][1]["hand"]))

    def test_jack_swaps_blindly(self):
        room, actor, target = make_room(11)
        actor_card_id = actor["hand"][0]["id"]
        target_card_id = target["hand"][1]["id"]
        self.accept(room, actor)
        server.handle_special_action(room, actor, {"specialAction": "select_own", "cardIndex": 0})
        server.handle_special_action(room, actor, {"specialAction": "select_target", "targetPlayerIndex": 1, "cardIndex": 1})
        self.assertEqual(actor["hand"][0]["id"], target_card_id)
        self.assertEqual(target["hand"][1]["id"], actor_card_id)
        self.assertEqual(room["phase"], "reaction")

    def test_queen_reveals_only_to_actor_and_can_swap(self):
        room, actor, target = make_room(12)
        actor_card_id = actor["hand"][0]["id"]
        target_card_id = target["hand"][1]["id"]
        self.accept(room, actor)
        server.handle_special_action(room, actor, {"specialAction": "select_own", "cardIndex": 0})
        server.handle_special_action(room, actor, {"specialAction": "select_target", "targetPlayerIndex": 1, "cardIndex": 1})
        self.assertEqual(len(server.snapshot(room, actor["id"])["specialResult"]), 2)
        self.assertEqual(server.snapshot(room, target["id"])["specialResult"], [])
        server.handle_special_action(room, actor, {"specialAction": "queen_swap"})
        self.assertEqual(actor["hand"][0]["id"], target_card_id)
        self.assertEqual(target["hand"][1]["id"], actor_card_id)

    def test_cpu_reaction_leaves_human_response_time(self):
        self.assertGreaterEqual(server.CPU_REACTION_DELAY[0], 2.5)
        self.assertGreater(server.REACTION_WINDOW_SECONDS, server.CPU_REACTION_DELAY[1])


if __name__ == "__main__":
    unittest.main()
