import unittest
from grove.core.navigation import CollisionGrid, BLOCKED


class CollisionTests(unittest.TestCase):
    def grid(self, changes=()):
        flags = [0] * 25
        for x, y, value in changes:
            flags[x * 5 + y] = value
        return CollisionGrid(0, 0, 5, 5, 0, tuple(flags))

    def test_wall_blocks_both_directions(self):
        grid = self.grid(((1, 1, 8),))
        self.assertFalse(grid.can_step((1, 1), (2, 1)))
        self.assertFalse(grid.can_step((2, 1), (1, 1)))

    def test_diagonal_cannot_cut_blocked_corner(self):
        grid = self.grid(((2, 1, BLOCKED),))
        self.assertFalse(grid.can_step((1, 1), (2, 2)))

    def test_path_detours_and_every_step_is_valid(self):
        grid = self.grid(tuple((2, y, BLOCKED) for y in range(4)))
        path = grid.path((1, 1), (3, 1))
        self.assertEqual(path[0], (1, 1))
        self.assertEqual(path[-1], (3, 1))
        self.assertIn((2, 4), path)
        self.assertTrue(all(grid.can_step(a, b) for a, b in zip(path, path[1:])))

    def test_blocked_object_uses_adjacent_goal(self):
        grid = self.grid(((3, 3, BLOCKED),))
        self.assertFalse(grid.path((0, 0), (3, 3)))
        path = grid.path((0, 0), (3, 3), adjacent=True)
        self.assertEqual(max(abs(path[-1][0]-3), abs(path[-1][1]-3)), 1)

    def test_unloaded_destination_and_exhausted_budget_are_empty(self):
        grid = self.grid()
        self.assertEqual(grid.path((0, 0), (9, 9)), ())
        self.assertEqual(grid.path((0, 0), (4, 4), max_nodes=1), ())
