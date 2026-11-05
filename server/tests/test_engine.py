"""Instructor rule checks, independent of the chosen networking technology."""
import unittest
from app.game.engine import World
from app.game.rules import (CLOAK_COST, CLOAK_TICKS, COLLECTIBLES, MOVE_SPEED,
                            MIN_MOVE_SPEED, DECAY_INTERVAL_TICKS, TICK_RATE,
                            radius_for, speed_for, decay_for)
from app.game.service import GameService
from app.network.protocol import parse_input


def isolate(world):
    for item in world.items:
        item.x, item.y = 950.0, 590.0


class MechanicsTests(unittest.TestCase):
    def game(self):
        w = World('test', seed=123)
        a = w.add_player('a', 'Alice')
        b = w.add_player('b', 'Bob')
        isolate(w)
        a.x, a.y = 100.0, 100.0
        b.x, b.y = 600.0, 400.0
        return w, a, b

    def test_waiting_start_midgame_join_and_finish(self):
        w = World('one', seed=3)
        w.add_player('a', 'Alice')
        self.assertEqual(w.phase, 'waiting')
        w.step()
        self.assertEqual(w.phase, 'waiting')
        w.add_player('b', 'Bob')
        self.assertEqual((w.phase, w.round), ('running', 1))
        w.add_player('c', 'Charlie')
        self.assertEqual((w.phase, w.round), ('running', 1))
        w.remove_player('b')
        self.assertEqual(w.phase, 'running')
        w.remove_player('c')
        self.assertEqual((w.phase, w.winner), ('finished', 'a'))
        w.add_player('d', 'Dan')
        self.assertEqual((w.phase, w.round), ('running', 2))
        self.assertEqual(w.players['a'].credits, 0)

    def test_cardinal_movement_and_stale_input(self):
        w, a, _ = self.game()
        self.assertFalse(w.accept_input('a', 1, 1, 1, False))
        self.assertTrue(w.accept_input('a', 1, 1, 0, False))
        self.assertFalse(w.accept_input('a', 1, -1, 0, False))
        w.step()
        self.assertAlmostEqual(a.x, 100 + MOVE_SPEED / TICK_RATE)
        self.assertEqual(a.y, 100)

    def test_speed_decreases_smoothly_with_credits(self):
        self.assertAlmostEqual(speed_for(0), MOVE_SPEED)
        self.assertGreater(speed_for(5), speed_for(25))
        self.assertGreater(speed_for(25), speed_for(100))
        self.assertGreaterEqual(speed_for(100000), MIN_MOVE_SPEED)
        w, a, b = self.game()
        a.credits = 100
        a.next_decay_tick = DECAY_INTERVAL_TICKS
        self.assertTrue(w.accept_input('a', 1, 1, 0, False))
        w.step()
        self.assertAlmostEqual(a.x, 100 + speed_for(100) / TICK_RATE)
        self.assertTrue(b.alive)

    def test_decay_per_player_spawn_and_rejoin_tick(self):
        w, a, b = self.game()
        a.credits = 100
        a.next_decay_tick = w.tick + DECAY_INTERVAL_TICKS
        # Joining mid-round gets a full decay interval, not the room's timer.
        for _ in range(DECAY_INTERVAL_TICKS - 1):
            w.step()
        self.assertEqual(a.credits, 100)
        c = w.add_player('c', 'Charlie')
        c.credits = 25
        self.assertEqual(c.next_decay_tick, w.tick + DECAY_INTERVAL_TICKS)
        w.step()
        self.assertEqual(a.credits, 100 - decay_for(100))
        self.assertEqual(c.credits, 25)
        self.assertTrue(any(e['type'] == 'decay' and e['actor'] == 'a' for e in w.events))
        for _ in range(DECAY_INTERVAL_TICKS - 1):
            w.step()
        self.assertEqual(c.credits, 25 - decay_for(25))
        self.assertGreater(a.radius, radius_for(0))

    def test_decay_stops_at_zero(self):
        self.assertEqual(decay_for(0), 0)
        self.assertEqual(decay_for(1), 1)
        self.assertEqual(decay_for(100), 2)
        self.assertEqual(decay_for(150), 3)
        w, a, _ = self.game()
        a.credits = 1
        for _ in range(DECAY_INTERVAL_TICKS * 2):
            w.step()
        self.assertEqual(a.credits, 0)

    def test_collect_three_tiers_and_growth(self):
        w, a, _ = self.game()
        self.assertEqual({item.tier for item in w.items}, set(COLLECTIBLES))
        values = {'small': 1, 'medium': 3, 'large': 7}
        for tier, value in values.items():
            item = next(x for x in w.items if x.tier == tier)
            item.x, item.y = a.x, a.y
            old = a.credits
            w.step()
            self.assertEqual(a.credits, old + value)
            isolate(w)
        self.assertEqual(a.credits, 11)
        self.assertGreater(a.radius, radius_for(0))
        events = [e for e in w.events if e['type'] == 'collect']
        self.assertEqual({e['tier'] for e in events}, set(values))

    def test_cloak_cost_visibility_expiration(self):
        w, a, b = self.game()
        a.credits = CLOAK_COST + 2
        self.assertTrue(w.accept_input('a', 1, 0, 0, True))
        w.step()
        self.assertEqual(a.credits, 2)
        self.assertEqual(a.invisible_until, w.tick + CLOAK_TICKS)
        self.assertTrue(any(p['id'] == 'a' for p in w.snapshot(viewer_id='a')['players']))
        self.assertFalse(any(p['id'] == 'a' for p in w.snapshot(viewer_id='b')['players']))
        self.assertTrue(any(p['id'] == 'a' for p in w.snapshot(reveal_hidden=True)['players']))
        for _ in range(CLOAK_TICKS):
            w.step()
        self.assertTrue(any(p['id'] == 'a' for p in w.snapshot(viewer_id='b')['players']))
        self.assertEqual(b.credits, 0)

    def test_collision_elimination_credit_transfer_rejoin(self):
        w, a, b = self.game()
        a.credits, b.credits = 10, 5
        b.x, b.y = a.x + 15, a.y
        w.step()
        self.assertFalse(b.alive)
        self.assertEqual(a.credits, 12)  # ceil(0.4 * 5)
        self.assertEqual((w.phase, w.winner), ('finished', 'a'))
        self.assertFalse(w.accept_input('b', 1, 1, 0, False))
        self.assertTrue(w.rejoin('b'))
        self.assertEqual((w.phase, w.round), ('running', 2))
        self.assertEqual((a.credits, b.credits), (0, 0))
        self.assertTrue(b.alive)

    def test_equal_credits_do_not_kill(self):
        w, a, b = self.game()
        a.credits = b.credits = 4
        a.x = b.x
        a.y = b.y
        w.step()
        self.assertTrue(a.alive and b.alive)

    def test_invisibility_is_not_invulnerability(self):
        w, a, b = self.game()
        a.credits, b.credits = 8, 4
        b.invisible_until = w.tick + CLOAK_TICKS
        b.x, b.y = a.x, a.y
        w.step()
        self.assertFalse(b.alive)

    def test_parse_input(self):
        self.assertEqual(parse_input({'seq': 3, 'dx': 0, 'dy': -1, 'cloak': False}), (3, 0, -1, False))
        self.assertIsNone(parse_input({'seq': 4, 'dx': 1, 'dy': 1, 'cloak': False}))
        self.assertIsNone(parse_input({'seq': 4, 'dx': 1, 'dy': 0, 'cloak': 1}))
        self.assertIsNone(parse_input({'seq': True, 'dx': 1, 'dy': 0, 'cloak': False}))

    def test_service_room_isolation(self):
        service = GameService()
        a = service.join('A', 'red')['id']
        b = service.join('B', 'blue')['id']
        self.assertEqual(len(service.rooms), 2)
        service.leave(a)
        self.assertNotIn('red', service.rooms)
        self.assertIn(b, service.player_rooms)

if __name__ == '__main__':
    unittest.main()
