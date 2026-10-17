"""Generate the animated profile banner (light + dark SVG).

The arm is a UR3e. Every frame is solved with the analytical inverse
kinematics from the ur-kinematics repository: the gripper moves straight
down, grasps a box, carries it across, places it, and brings it back, so the
animation loops seamlessly.

    pip install numpy git+https://github.com/Mohammedgmail/ur-kinematics.git
    python scripts/make_banner.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from urkin import UR3e, make_transform

ASSETS = Path(__file__).resolve().parents[1] / "assets"

TEXT = {
    "name": "Mohammed Alfandi",
    "title": "Robotics &amp; Machine Learning Engineer",
    "tagline": "Sim-to-real RL · Robot manipulation · Computer vision · Optimisation",
    "detail": "MSc Robotics &amp; AI (Distinction), Newcastle University · 13+ years in automation",
}

THEMES = {
    "light": {
        "bg": "#f6f8fa",
        "border": "#d0d7de",
        "text": "#1f2328",
        "accent": "#004b8c",
        "muted": "#59636e",
        "arm": "#004b8c",
        "joint": "#ffffff",
        "ground": "#afb8c1",
        "box": "#bc4c00",
    },
    "dark": {
        "bg": "#161b22",
        "border": "#30363d",
        "text": "#e6edf3",
        "accent": "#58a6ff",
        "muted": "#9198a1",
        "arm": "#58a6ff",
        "joint": "#0d1117",
        "ground": "#3d444d",
        "box": "#f0883e",
    },
}

# ---- task (metres, base frame) ----
PICK_Y, PLACE_Y = -0.38, 0.28  # left / right of the base on screen
BOX = 0.05  # cube edge
FINGER = 0.05  # finger length
GRASP_DEPTH = 0.028  # flange-to-box-centre distance when grasped
HOVER = 0.12  # approach height above the grasp pose
OPEN, CLOSED = 0.036, 0.027  # finger half-spacing
R_DOWN = np.column_stack([[-1, 0, 0], [0, 1, 0], [0, 0, -1]]).astype(float)  # gripper down

# ---- timing (frames at a constant rate) ----
FPS = 14
MOVE, VERTICAL, PAUSE = 22, 9, 5

# ---- canvas / projection ----
W, H = 1000, 260
ORIGIN = np.array([800.0, 232.0])  # robot base (z = 0) on screen
SCALE = 360.0  # pixels per metre
ELEV = np.deg2rad(18.0)

robot = UR3e()


def project(p):
    """Orthographic view looking along +x: screen-right = +y, tilted by ELEV."""
    x, y, z = p
    return ORIGIN + SCALE * np.array([y, -(z * np.cos(ELEV) - x * np.sin(ELEV))])


def smooth(n):
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    return t * t * (3 - 2 * t)


def flange_pose(y, lift):
    z = BOX / 2 + GRASP_DEPTH + lift
    return make_transform(R_DOWN, [0.0, y, z])


def elbow_up_ik(T, q_prev):
    """IK solution nearest to q_prev among those with the elbow above the shoulder."""
    best, best_cost = None, np.inf
    for sol in robot.ik(T):
        F = robot.fk_frames(sol)
        if F[2][2, 3] < F[1][2, 3] + 0.1:  # elbow must sit clearly above the shoulder
            continue
        cand = sol + 2 * np.pi * np.round((q_prev - sol) / (2 * np.pi))
        cost = np.sum((cand - q_prev) ** 2)
        if cost < best_cost:
            best, best_cost = cand, cost
    if best is None:
        raise ValueError("no elbow-up solution for this pose")
    return best


def plan():
    """Return per-frame (q, finger_half_spacing, box_state) for one full loop."""
    frames = []
    q = elbow_up_ik(flange_pose(PICK_Y, HOVER), np.array([1.2, -1.2, 1.75, -2.1, -1.57, 0.0]))

    def vertical(y, down, grip, box):
        nonlocal q
        for s in smooth(VERTICAL):
            lift = HOVER * (1 - s) if down else HOVER * s
            q = elbow_up_ik(flange_pose(y, lift), q)
            frames.append((q, grip, box))

    def move(y_to, grip, box):
        nonlocal q
        q_end = elbow_up_ik(flange_pose(y_to, HOVER), q)
        # The base can turn either way round; swing in front of the base (x < 0)
        # so the projected arm never passes behind it.
        options = [q_end + [k * 2 * np.pi, 0, 0, 0, 0, 0] for k in (-1, 0, 1)]
        options = [o for o in options if abs(o[0]) <= 2 * np.pi]
        q_end = min(options, key=lambda o: robot.fk((q + o) / 2)[0, 3])
        for s in smooth(MOVE):
            frames.append((q + (q_end - q) * s, grip, box))
        q = q_end

    def pause(g0, g1, box):
        for s in smooth(PAUSE):
            frames.append((q, g0 + (g1 - g0) * s, box))

    for src, dst in ((PICK_Y, PLACE_Y), (PLACE_Y, PICK_Y)):
        vertical(src, True, OPEN, ("ground", src))
        pause(OPEN, CLOSED, ("ground", src))
        vertical(src, False, CLOSED, ("held", None))
        move(dst, CLOSED, ("held", None))
        vertical(dst, True, CLOSED, ("held", None))
        pause(CLOSED, OPEN, ("ground", dst))
        vertical(dst, False, OPEN, ("ground", dst))
        pause(OPEN, OPEN, ("ground", dst))
        move(src, OPEN, ("ground", dst))
    return frames


def render_frame(q, w, box):
    T = robot.fk_frames(q)
    arm = [project(F[:3, 3]) for F in T]
    o, y, z = T[-1][:3, 3], T[-1][:3, 1], T[-1][:3, 2]
    fingers = [o + w * y + FINGER * z, o + w * y, o - w * y, o - w * y + FINGER * z]
    state, ground_y = box
    centre = o + GRASP_DEPTH * z if state == "held" else np.array([0.0, ground_y, BOX / 2])
    return arm, [project(p) for p in fingers], project(centre)


def fmt(points):
    return " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in points)


def build_svg(theme: dict, rendered) -> str:
    arms, grippers, boxes = zip(*rendered, strict=True)
    n = len(arms)
    anim = f'dur="{n / FPS:.2f}s" repeatCount="indefinite" calcMode="linear"'
    t = theme
    half = BOX * SCALE / 2

    joints = []
    for j in range(1, 6):
        cx = ";".join(f"{a[j][0]:.1f}" for a in arms)
        cy = ";".join(f"{a[j][1]:.1f}" for a in arms)
        joints.append(
            f'<circle cx="{arms[0][j][0]:.1f}" cy="{arms[0][j][1]:.1f}" r="5" '
            f'fill="{t["joint"]}" stroke="{t["arm"]}" stroke-width="2.5">'
            f'<animate attributeName="cx" values="{cx}" {anim}/>'
            f'<animate attributeName="cy" values="{cy}" {anim}/></circle>'
        )
    bx = ";".join(f"{b[0] - half:.1f}" for b in boxes)
    by = ";".join(f"{b[1] - half:.1f}" for b in boxes)
    pads = "".join(
        f'<line x1="{project([0, y, 0])[0] - 16:.1f}" y1="{ORIGIN[1]:.1f}" '
        f'x2="{project([0, y, 0])[0] + 16:.1f}" y2="{ORIGIN[1]:.1f}" '
        f'stroke="{t["muted"]}" stroke-width="3" stroke-linecap="round"/>'
        for y in (PICK_Y, PLACE_Y)
    )
    base = ORIGIN
    font = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"
     width="{W}" height="{H}" role="img"
     aria-label="Mohammed Alfandi, Robotics and Machine Learning Engineer">
  <title>Mohammed Alfandi - Robotics &amp; Machine Learning Engineer</title>
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14"
        fill="{t["bg"]}" stroke="{t["border"]}"/>
  <g font-family="{font}">
    <text x="44" y="96" font-size="44" font-weight="700" fill="{t["text"]}">{TEXT["name"]}</text>
    <text x="46" y="134" font-size="22" font-weight="600"
          fill="{t["accent"]}">{TEXT["title"]}</text>
    <text x="46" y="174" font-size="15.5" fill="{t["muted"]}">{TEXT["tagline"]}</text>
    <text x="46" y="200" font-size="14" fill="{t["muted"]}">{TEXT["detail"]}</text>
  </g>
  <line x1="{base[0] - 190}" y1="{base[1]}" x2="{base[0] + 175}" y2="{base[1]}"
        stroke="{t["ground"]}" stroke-width="1.5" stroke-dasharray="4 5"/>
  {pads}
  <path d="M{base[0] - 24},{base[1]} L{base[0] - 16},{base[1] - 12}
           L{base[0] + 16},{base[1] - 12} L{base[0] + 24},{base[1]} Z" fill="{t["arm"]}"/>
  <rect x="{boxes[0][0] - half:.1f}" y="{boxes[0][1] - half:.1f}" width="{2 * half:.1f}"
        height="{2 * half:.1f}" rx="3" fill="{t["box"]}">
    <animate attributeName="x" values="{bx}" {anim}/>
    <animate attributeName="y" values="{by}" {anim}/>
  </rect>
  <polyline points="{fmt(arms[0])}" fill="none" stroke="{t["arm"]}" stroke-width="10"
            stroke-linecap="round" stroke-linejoin="round">
    <animate attributeName="points" values="{";".join(fmt(a) for a in arms)}" {anim}/>
  </polyline>
  <polyline points="{fmt(grippers[0])}" fill="none" stroke="{t["text"]}" stroke-width="3.5"
            stroke-linecap="round" stroke-linejoin="round">
    <animate attributeName="points" values="{";".join(fmt(g) for g in grippers)}" {anim}/>
  </polyline>
  {"".join(joints)}
</svg>
"""


def main() -> None:
    frames = plan()
    rendered = [render_frame(q, w, box) for q, w, box in frames]
    ASSETS.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        path = ASSETS / f"banner-{name}.svg"
        path.write_text(build_svg(theme, rendered), encoding="utf-8")
        print(f"wrote {path} ({len(frames)} frames, {len(frames) / FPS:.1f} s loop)")


if __name__ == "__main__":
    main()
