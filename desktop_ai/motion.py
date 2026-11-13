"""Time-based skeletal poses. Geometry is interpolated, never bitmap-upscaled."""

from __future__ import annotations

import math
import random

from .brain import ACTIONS

Point = tuple[float, float]
Pose = dict[str, Point]


def pose_for(action: str, time: float, moving: bool = False) -> Pose:
    phase = time * (9 if moving else 2.2)
    breath = math.sin(time * 2.5) * 1.2
    p: Pose = {"head": (0, -105 + breath), "neck": (0, -86 + breath), "hip": (0, -48),
               "le": (-18, -66), "lh": (-25, -46), "re": (18, -66), "rh": (25, -46),
               "lk": (-10, -25), "lf": (-15, 0), "rk": (10, -25), "rf": (15, 0)}
    if action == "walk" or moving:
        stride = math.sin(phase)
        for side, sign in (("l", 1), ("r", -1)):
            swing = stride * sign
            p[side + "f"] = (swing * 25, -max(0, math.cos(phase) * sign) * 12)
            p[side + "k"] = (swing * 11 + 5, -26 - max(0, swing) * 5)
            p[side + "h"] = (-swing * 22, -51)
            p[side + "e"] = (-swing * 10, -68)
        p["hip"] = (0, -48 - abs(math.cos(phase)) * 2)
    if action in {"wave", "celebrate", "surprised"}:
        p["re"] = (28, -100)
        p["rh"] = (26 + math.sin(time * 12) * 9, -129)
        if action != "wave":
            p["le"], p["lh"] = (-28, -100), (-32 - math.sin(time * 10) * 6, -127)
        if action == "surprised":
            p["head"] = (-5, -109)
    if action == "jump":
        p["le"], p["lh"], p["re"], p["rh"] = (-25, -90), (-32, -115), (25, -90), (32, -115)
        # Anticipation -> takeoff -> flight -> soft landing. The whole skeleton blends.
        if time < 0.22:
            lift = -8 * math.sin(time / 0.22 * math.pi)
        elif time < 1.02:
            lift = 46 * math.sin((time - 0.22) / 0.8 * math.pi)
        elif time < 1.24:
            lift = -5 * math.sin((time - 1.02) / 0.22 * math.pi)
        else:
            lift = 0
        p = {name: (x, y - lift) for name, (x, y) in p.items()}
    if action == "dance":
        sway = math.sin(time * 6)
        p["head"] = (sway * 12, -106 + math.cos(time * 12) * 3)
        p["neck"], p["hip"] = (sway * 8, -85), (-sway * 6, -47)
        p["le"], p["lh"] = (-30, -90 + sway * 17), (-44, -104 + sway * 25)
        p["re"], p["rh"] = (30, -90 - sway * 17), (44, -104 - sway * 25)
        p["lf"], p["rf"] = (-22, -max(0, sway) * 10), (22, -max(0, -sway) * 10)
    if action in {"sit", "sleep"}:
        p.update(head=(0, -75), neck=(0, -56), hip=(0, -20), le=(-13, -34), lh=(-22, -20),
                 re=(13, -34), rh=(22, -20), lk=(-24, -16), lf=(-35, 0), rk=(24, -16), rf=(35, 0))
        if action == "sleep":
            p["head"], p["neck"] = (12, -70 + breath), (5, -54)
    if action == "think":
        p["head"] = (5, -104)
        p["re"], p["rh"] = (27, -70), (13, -94)
        p["le"], p["lh"] = (-17, -65), (12, -63)
    if action == "point":
        p["re"], p["rh"] = (31, -89), (58, -96)
        p["head"] = (5, -105)
    return p


class Motion:
    def __init__(self, x: float = 0.5, seed: int | None = None):
        self.x = x
        self.target = x
        self.velocity = 0.0
        self.action = "idle"
        self.emotion = "curious"
        self.action_time = 0.0
        self.clock = 0.0
        self.direction = 1
        self.pose = pose_for("idle", 0)
        self.random = random.Random(seed)
        self.next_idle = 7.0
        self.autonomy = True
        self.dragging = False

    def react(self, action: str, target_x: float | None = None):
        self.action = action if action in ACTIONS else "idle"
        self.action_time = 0.0
        self.next_idle = self.clock + self.random.uniform(9, 16)
        # Gestures stop an unfinished walk. Only explicit walking changes position.
        if self.action == "walk":
            self.target = max(0.0, min(1.0, target_x if target_x is not None else self.x + self.direction * 0.15))
        else:
            self.target = self.x
        if target_x is not None and abs(target_x - self.x) > 0.02:
            self.direction = 1 if target_x > self.x else -1

    def tick(self, dt: float, width: float):
        dt = max(0.0, min(0.05, dt))  # Resume without teleporting after a stalled frame.
        self.clock += dt
        self.action_time += dt
        distance = (self.target - self.x) * max(width, 1)
        desired_velocity = max(-95, min(95, distance * 4)) if not self.dragging else 0
        self.velocity += (desired_velocity - self.velocity) * (1 - math.exp(-9 * dt))
        if not self.dragging:
            self.x = max(0, min(1, self.x + self.velocity * dt / max(width, 1)))
        moving = abs(self.velocity) > 5
        if moving:
            self.direction = 1 if self.velocity > 0 else -1
        if self.action == "walk" and abs(distance) < 2 and not moving:
            self.action = "idle"
        duration = {"jump": 1.5, "wave": 2.7, "dance": 5, "celebrate": 3,
                    "surprised": 2.2, "think": 5, "point": 4, "sit": 8, "sleep": 12}
        if self.action in duration and self.action_time > duration[self.action]:
            self.action = "idle"
            self.action_time = 0
        if self.autonomy and not self.dragging and self.clock > self.next_idle:
            action = self.random.choice(["idle", "walk", "think", "sit", "wave"])
            self.react(action, self.random.uniform(0.12, 0.88) if action == "walk" else None)
        phase_time = self.clock if self.action == "walk" else self.action_time
        target_pose = pose_for(self.action, phase_time, moving)
        if self.action in {"idle", "think", "point"}:
            hx, hy = target_pose["head"]
            tilt = {"curious": (3, -1), "happy": (0, -3), "sleepy": (6, 4), "focused": (4, 1)}.get(self.emotion, (0, 0))
            target_pose["head"] = (hx + tilt[0], hy + tilt[1])
        blend = 1 - math.exp(-16 * dt)
        self.pose = {name: (x + (target_pose[name][0] - x) * blend,
                            y + (target_pose[name][1] - y) * blend)
                     for name, (x, y) in self.pose.items()}
