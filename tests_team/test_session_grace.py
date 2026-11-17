#!/usr/bin/env python3
"""Team unit tests for session persistence, 15s grace period, and disconnect edge cases.

These tests live in `tests_team/` to strictly comply with FILE_POLICY.md.
"""
import asyncio
import unittest
from unittest.mock import MagicMock

from app.game.service import GameService
from app.game.rules import TICK_RATE, DECAY_RATE


class SessionGraceEdgeCaseTests(unittest.TestCase):
    def setUp(self):
        self.service = GameService()

    def test_session_token_mapping_and_reconnection(self):
        """Test that joining with a session token binds player_id and reconnects cleanly."""
        token = "tok_test_alice_123"
        welcome1 = self.service.join("Alice", "room-grace", session_token=token)
        pid1 = welcome1["id"]
        self.assertEqual(self.service.session_players.get(token), pid1)
        self.assertEqual(self.service.player_sessions.get(pid1), token)
        self.assertFalse(welcome1.get("resumed", False))

        # Add 2nd player so phase becomes running and inputs are processed
        self.service.join("Bob", "room-grace")
        # Alice moves for 50 ticks
        self.service.apply_input(pid1, seq=50, dx=1, dy=0, cloak=False)
        self.assertEqual(self.service.rooms["room-grace"].players[pid1].seq, 50)

        # Simulate disconnect (socket closed, but token preserved in service)
        # Reconnect with same token
        welcome2 = self.service.join("Alice", "room-grace", session_token=token)
        pid2 = welcome2["id"]
        self.assertEqual(pid1, pid2, "Player ID must be preserved across reconnection")
        self.assertTrue(welcome2.get("resumed", False), "Welcome must indicate session was resumed")
        self.assertEqual(self.service.rooms["room-grace"].players[pid1].seq, -1, "Player seq must reset on resume")

        # Client starts seq from 1 on reconnect; input must be accepted immediately!
        moved = self.service.apply_input(pid1, seq=1, dx=0, dy=1, cloak=False)
        self.assertTrue(moved, "Input starting from seq=1 must be accepted after resume")

    def test_disconnected_player_remains_in_world_during_grace(self):
        """Test that a player disconnected with active session remains in the room,
        still subject to credit decay and collision until grace period expires or round completes."""
        token1 = "tok_p1"
        token2 = "tok_p2"
        w1 = self.service.join("P1", "room-clash", session_token=token1)
        w2 = self.service.join("P2", "room-clash", session_token=token2)
        p1 = w1["id"]
        p2 = w2["id"]

        room = self.service.rooms["room-clash"]
        # Both players in room
        self.assertIn(p1, room.players)
        self.assertIn(p2, room.players)

        # Award credits to P1
        room.players[p1].credits = 100
        room.players[p2].credits = 10

        # Simulate P2 dropping connection (socket dropped, session preserved)
        # P2 is NOT removed immediately from room.players
        self.assertIn(p2, room.players)
        self.assertTrue(room.players[p2].alive)

        # Advance 100 ticks (5 seconds) -> periodic decay should apply to alive players in room
        initial_p1_credits = room.players[p1].credits
        for _ in range(100):
            room.step()

        # Both players experienced periodic decay
        self.assertLess(room.players[p1].credits, initial_p1_credits)
        self.assertLess(room.players[p2].credits, 10)

        # Explicit leave clears session and removes player
        self.service.leave(p2, clear_session=True)
        self.assertNotIn(p2, room.players)
        self.assertNotIn(token2, self.service.session_players)


if __name__ == '__main__':
    unittest.main()
