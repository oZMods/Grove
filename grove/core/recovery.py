"""Reusable bounded recovery budgets, reset by observed gameplay progress."""
import time


class RecoveryBudget:
    def __init__(self, limit=8):
        self.limit = limit
        self.key = None
        self.attempts = 0

    def observe(self, snapshot):
        player = snapshot['player']
        key = (player['world_id'], player['plane'], player['x'], player['y'], snapshot['xp'],
               snapshot['bank_open'], tuple((i['slot'],i['id'],i['quantity']) for i in snapshot['inventory']))
        if key != self.key:
            self.key, self.attempts = key, 0

    def consume(self):
        self.attempts += 1
        if self.attempts > self.limit:
            raise RuntimeError('Visibility recovery exhausted its attempts without gameplay progress.')


class MovementProgress:
    def __init__(self, timeout=12, clock=time.monotonic):
        self.timeout, self.clock = timeout, clock
        self.position = self.changed_at = None

    def observe(self, player):
        position = (player['world_id'],player['plane'],player['x'],player['y'])
        now = self.clock()
        if position != self.position or player['route'] <= 0:
            self.position, self.changed_at = position, now
        return player['route'] > 0 and now-self.changed_at >= self.timeout
