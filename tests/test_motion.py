import math
import unittest

from desktop_ai.brain import ACTIONS
from desktop_ai.motion import Motion, pose_for


class MotionTests(unittest.TestCase):
    def test_action_transition_interpolates_instead_of_snapping(self):
        motion = Motion(seed=1)
        before = motion.pose["rh"]
        motion.react("wave")
        motion.tick(1 / 60, 1000)
        after = motion.pose["rh"]
        goal = pose_for("wave", 1 / 60)["rh"]
        self.assertGreater(math.dist(before, after), 0)
        self.assertLess(math.dist(before, after), math.dist(before, goal) / 2)

    def test_walk_speed_is_independent_of_render_rate(self):
        positions = []
        for fps in (30, 60, 120):
            motion = Motion(0.2, seed=1)
            motion.autonomy = False
            motion.react("walk", 0.8)
            for _ in range(fps * 3):
                motion.tick(1 / fps, 1000)
            positions.append(motion.x)
        self.assertLess(max(positions) - min(positions), 0.004)

    def test_long_pause_cannot_teleport_or_leave_screen(self):
        motion = Motion(0.95)
        motion.react("walk", 5)
        motion.tick(100, 1000)
        self.assertLess(motion.x - 0.95, 0.01)
        self.assertLessEqual(motion.x, 1)
        self.assertEqual(motion.target, 1)

    def test_all_actions_keep_the_same_finite_skeleton(self):
        joints = pose_for("idle", 0).keys()
        for action in ACTIONS:
            for time in (0, 0.1, 0.5, 1, 3, 10):
                pose = pose_for(action, time)
                self.assertEqual(pose.keys(), joints)
                self.assertTrue(all(math.isfinite(value) for point in pose.values() for value in point))


if __name__ == "__main__":
    unittest.main()
