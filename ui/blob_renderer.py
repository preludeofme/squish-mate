#!/usr/bin/env python3
"""
blob_renderer.py — draws the alien blob procedurally with QPainter.

No image assets: every frame the full character is rebuilt from Bézier curves
using the Pose produced by PetAnimator:

  * one continuous body silhouette (tentacle arms are part of the outline),
  * a bendy antenna with a glowing bulb,
  * glossy eyes (blink by collapsing height, pupils follow the cursor),
  * a mood-driven mouth, blush, jelly highlights, inner bubbles, and a
    soft ground shadow.

Squash/stretch is anchored at the body's bottom so landings flatten the base
instead of scaling around the center.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

# Default lavender alien palette. Body tones are per-instance (see
# apply_color) so the pet's color can be changed live from Settings; the eye/
# blush/shadow tones stay fixed regardless of body color.
DEFAULT_BODY_COLOR = "#C9A5F0"
EYE_COLOR = QColor("#2D1B36")
BLUSH_COLOR = QColor("#FF9EC4")
SHADOW_COLOR = QColor(30, 20, 50)

# Body silhouette archetypes — the actual "shape" variety Ryan asked for
# (color/pattern were already covered separately by the existing color
# picker + apply_pattern). Every archetype still shares the exact same
# rig/Pose/animation pipeline (squash-stretch anchor, arm sway from
# pose.arm_l/r, antenna sway from pose.antenna_sway, etc.) — only the
# geometry _body_path/_draw_antenna/_draw_horns produce changes, so every
# pet in the library still hops/waves/sleeps/giggles identically.
#   w_scale/h_scale — overall body proportions vs. the base round blob.
#   top_taper       — 1.0 = round top (original); lower = narrower,
#                      more pointed/teardrop-y top.
#   arm_reach       — 1.0 = original long thin tentacle reach; lower =
#                      shorter, stubbier arms.
#   antenna         — "single" (original) | "twin" | "curly" | "none".
#   horns           — draw two small nub horns poking out of the top.
SHAPE_PRESETS = {
    "round": {
        "w_scale": 1.00, "h_scale": 1.00, "top_taper": 1.00,
        "arm_reach": 1.00, "antenna": "single", "horns": False,
    },
    "tall": {
        "w_scale": 0.82, "h_scale": 1.22, "top_taper": 0.85,
        "arm_reach": 0.85, "antenna": "single", "horns": False,
    },
    "wide": {
        "w_scale": 1.22, "h_scale": 0.82, "top_taper": 1.05,
        "arm_reach": 1.15, "antenna": "twin", "horns": False,
    },
    "teardrop": {
        "w_scale": 0.92, "h_scale": 1.14, "top_taper": 0.55,
        "arm_reach": 0.90, "antenna": "curly", "horns": False,
    },
    "chubby": {
        "w_scale": 1.18, "h_scale": 0.92, "top_taper": 1.10,
        "arm_reach": 0.60, "antenna": "none", "horns": True,
    },
    "horned": {
        "w_scale": 1.00, "h_scale": 1.02, "top_taper": 1.00,
        "arm_reach": 1.00, "antenna": "single", "horns": True,
    },
}
DEFAULT_SHAPE = "round"


class BlobRenderer:
    BASE_W = 44.0   # body half-width at shape "round" (w_scale 1.0)
    BASE_H = 42.0   # body half-height at shape "round" (h_scale 1.0)

    PATTERNS = ("plain", "spots", "stripes", "stars")

    def __init__(self, win_w, win_h, color=DEFAULT_BODY_COLOR, pattern="plain",
                 shape=DEFAULT_SHAPE):
        self.win_w = win_w
        self.win_h = win_h
        self.cx = win_w / 2.0
        self.ground = win_h - 20.0
        self._zzz_font = QFont("Sans Serif", 11, QFont.Weight.Bold)
        self.BODY_LIGHT = self.BODY_MID = self.BODY_DARK = self.BODY_EDGE = None
        self.apply_color(color)
        self.pattern = "plain"
        self.apply_pattern(pattern)
        self.shape = DEFAULT_SHAPE
        self._shape = SHAPE_PRESETS[DEFAULT_SHAPE]
        self.BODY_W = self.BASE_W
        self.BODY_H = self.BASE_H
        self.apply_shape(shape)

    def apply_color(self, hex_str):
        """Recompute the body gradient tones from a single base hex color."""
        color = QColor(hex_str)
        if not color.isValid():
            return
        self.BODY_MID = color
        self.BODY_LIGHT = color.lighter(132)
        self.BODY_DARK = color.darker(128)
        self.BODY_EDGE = color.darker(158)

    def apply_pattern(self, pattern):
        """Switch the decorative body pattern (see pet_library.py — this is
        the color-adjacent, no-shape-change distinguisher a "species" can
        have alongside apply_shape below)."""
        self.pattern = pattern if pattern in self.PATTERNS else "plain"

    def apply_shape(self, shape):
        """Switch the body silhouette archetype (see SHAPE_PRESETS above —
        this is the actual "shape" library, distinct from color/pattern).
        Every archetype still uses the identical Pose-driven rig/animation
        pipeline, only the outline/antenna/horn geometry changes."""
        self.shape = shape if shape in SHAPE_PRESETS else DEFAULT_SHAPE
        self._shape = SHAPE_PRESETS[self.shape]
        self.BODY_W = self.BASE_W * self._shape["w_scale"]
        self.BODY_H = self.BASE_H * self._shape["h_scale"]

    # ------------------------------------------------------------------ paths
    def _body_path(self, pose):
        """One continuous silhouette, arms included, in body-center coords.
        `top_taper`/`arm_reach` (from SHAPE_PRESETS) reshape the same curve
        structure per species — a lower top_taper pulls the shoulders in
        for a narrower/pointier top, a lower arm_reach shortens the arms."""
        w, h = self.BODY_W, self.BODY_H
        top = self._shape["top_taper"]
        reach = self._shape["arm_reach"]
        t = pose.t
        # Small independent wobbles so the outline never scales rigidly.
        w1 = math.sin(t * 1.7) * 1.6
        w2 = math.sin(t * 2.3 + 1.0) * 1.4
        w3 = math.sin(t * 1.3 + 2.1) * 1.8
        w4 = math.sin(t * 2.9 + 0.5) * 1.2
        arm_r = h * 0.10 + pose.arm_r
        arm_l = h * 0.10 + pose.arm_l
        # Arm-curve reach multipliers (1.0 == the original fixed constants).
        a1 = 1.0 + 0.02 * reach
        a2 = 1.0 + 0.24 * reach
        a3 = 1.0 + 0.30 * reach
        a4 = 1.0 + 0.34 * reach
        a5 = 1.0 + 0.12 * reach

        p = QPainterPath(QPointF(0, -h))
        # Upper-right body curve (top_taper narrows the shoulders).
        p.cubicTo(w * 0.55 * top, -h + w2, w * 0.98 * top + w1, -h * 0.55,
                  w * 0.94 * top, -h * 0.12)
        # Right tentacle arm, grown out of the outline.
        p.cubicTo(w * a1, 0, w * a2, arm_r - 10, w * a3, arm_r)
        p.cubicTo(w * a4, arm_r + 7, w * a5, arm_r + 12, w * 0.92, h * 0.40)
        # Lower-right down to a soft wavy bottom.
        p.cubicTo(w * 0.86, h * 0.78, w * 0.55, h * 0.98,
                  w * 0.20, h + w3 * 0.4)
        p.cubicTo(w * 0.07, h + 1.5 + w4 * 0.5, -w * 0.07, h + 1.5 - w4 * 0.5,
                  -w * 0.20, h + w4 * 0.4)
        # Lower-left back up.
        p.cubicTo(-w * 0.55, h * 0.98, -w * 0.86, h * 0.78,
                  -w * 0.92, h * 0.40)
        # Left tentacle arm.
        p.cubicTo(-w * a5, arm_l + 12, -w * a4, arm_l + 7,
                  -w * a3, arm_l)
        p.cubicTo(-w * a2, arm_l - 10, -w * a1, 0, -w * 0.94 * top, -h * 0.12)
        # Upper-left body curve, back to the top.
        p.cubicTo(-w * 0.98 * top - w1, -h * 0.55, -w * 0.55 * top, -h + w2, 0, -h)
        p.closeSubpath()
        return p

    # ------------------------------------------------------------------- draw
    def draw(self, painter, pose):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_shadow(painter, pose)

        painter.save()
        # Anchor squash/stretch at the body's bottom (ground contact point).
        painter.translate(self.cx, self.ground + pose.offset_y)
        painter.scale(pose.scale_x, pose.scale_y)
        painter.translate(0, -self.BODY_H)  # origin = body center
        if pose.body_rotation:
            # Whole-character spin (somersault, dance wiggle) around the body
            # center — rotate here so antenna/body/face all turn together.
            painter.rotate(pose.body_rotation)

        # Antenna/horns are drawn BEFORE the body so the body silhouette
        # naturally covers their base attachment, leaving only the part
        # that pokes up above the outline visible.
        self._draw_antenna(painter, pose)
        if self._shape["horns"]:
            self._draw_horns(painter, pose)
        body = self._body_path(pose)
        self._draw_body(painter, body, pose)
        self._draw_face(painter, pose)
        painter.restore()

        if pose.sleeping:
            self._draw_zzz(painter, pose)

    def _draw_shadow(self, painter, pose):
        lift = 1.0 / (1.0 + abs(pose.offset_y) / 30.0)
        rx = 40.0 * (self.BODY_W / self.BASE_W) * pose.scale_x * (0.6 + 0.4 * lift)
        color = QColor(SHADOW_COLOR)
        color.setAlpha(int(60 * lift))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(self.cx, self.ground + 7), rx, 7.0)

    def _draw_antenna(self, painter, pose):
        """Dispatches to the antenna style for the current shape archetype
        (see SHAPE_PRESETS["antenna"])."""
        style = self._shape["antenna"]
        if style == "none":
            return
        if style == "twin":
            self._draw_antenna_stalk(painter, pose, x_off=-7.0, sway_scale=0.75,
                                     height=21.0, pen_width=3.6)
            self._draw_antenna_stalk(painter, pose, x_off=7.0, sway_scale=0.75,
                                     height=21.0, pen_width=3.6)
            return
        if style == "curly":
            self._draw_antenna_curly(painter, pose)
            return
        self._draw_antenna_stalk(painter, pose)

    def _draw_antenna_stalk(self, painter, pose, x_off=0.0, sway_scale=1.0,
                             height=30.0, pen_width=4.5):
        """The original bendy-antenna-with-glowing-bulb, parametrized so it
        can be drawn once (single) or twice, offset/shortened (twin)."""
        h = self.BODY_H
        sway = pose.antenna_sway * sway_scale
        base = QPointF(x_off, -h + 4)
        tip = QPointF(x_off + sway, -h - height)
        path = QPainterPath(base)
        path.cubicTo(x_off + sway * 0.15, -h - height * 0.33,
                     x_off + sway * 0.55, -h - height * 0.70,
                     tip.x(), tip.y())
        pen = QPen(self.BODY_EDGE, pen_width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        # Glowing bulb on the end.
        bulb = QRadialGradient(tip + QPointF(-1.5, -1.5), 7.0)
        bulb.setColorAt(0.0, QColor("#F5EBFF"))
        bulb.setColorAt(0.55, self.BODY_MID)
        bulb.setColorAt(1.0, self.BODY_EDGE)
        painter.setPen(QPen(self.BODY_EDGE, 1.2))
        painter.setBrush(bulb)
        painter.drawEllipse(tip, 5.0, 5.0)

    def _draw_antenna_curly(self, painter, pose):
        """A stem that curls into a small spiral loop instead of ending in
        a glowing bulb — used by the "teardrop" shape archetype."""
        h = self.BODY_H
        sway = pose.antenna_sway
        base = QPointF(0, -h + 4)
        mid = QPointF(sway * 0.4, -h - 16)
        path = QPainterPath(base)
        path.cubicTo(sway * 0.15, -h - 8, sway * 0.4, -h - 14, mid.x(), mid.y())
        path.cubicTo(mid.x() + 7, mid.y() - 4, mid.x() + 7, mid.y() + 6,
                     mid.x(), mid.y() + 6)
        path.cubicTo(mid.x() - 5, mid.y() + 6, mid.x() - 3, mid.y() - 2,
                     mid.x() + 1, mid.y() - 1)
        pen = QPen(self.BODY_EDGE, 4.0, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_horns(self, painter, pose):
        """Two small nub horns poking out of the top of the body — used by
        shape archetypes with SHAPE_PRESETS["horns"] = True."""
        h, w = self.BODY_H, self.BODY_W
        for side in (-1, 1):
            base = QPointF(side * w * 0.32, -h * 0.88)
            tip = QPointF(side * w * 0.40, -h * 1.22)
            path = QPainterPath(QPointF(base.x() - side * 3.5, base.y()))
            path.lineTo(tip)
            path.lineTo(QPointF(base.x() + side * 3.5, base.y()))
            path.closeSubpath()
            painter.setPen(QPen(self.BODY_EDGE, 1.4))
            painter.setBrush(self.BODY_MID)
            painter.drawPath(path)

    def _draw_body(self, painter, body, pose):
        w, h = self.BODY_W, self.BODY_H
        grad = QRadialGradient(QPointF(-w * 0.35, -h * 0.45), w * 2.1)
        grad.setColorAt(0.0, self.BODY_LIGHT)
        grad.setColorAt(0.55, self.BODY_MID)
        grad.setColorAt(1.0, self.BODY_DARK)
        painter.setPen(QPen(self.BODY_EDGE, 2.6))
        painter.setBrush(grad)
        painter.drawPath(body)

        # Interior details clipped to the silhouette (jelly effect).
        painter.save()
        painter.setClipPath(body)
        painter.setPen(Qt.PenStyle.NoPen)

        # Darker translucent lower-body gradient.
        shade = QLinearGradient(QPointF(0, h * 0.1), QPointF(0, h))
        shade.setColorAt(0.0, QColor(126, 93, 192, 0))
        shade.setColorAt(1.0, QColor(126, 93, 192, 90))
        painter.setBrush(shade)
        painter.drawRect(QRectF(-w * 1.4, 0, w * 2.8, h + 4))

        # Drifting internal bubbles.
        t = pose.t
        for i, (bx, by, r) in enumerate(((-w * 0.45, h * 0.45, 4.0),
                                         (w * 0.30, h * 0.60, 3.0),
                                         (w * 0.55, h * 0.25, 2.4))):
            dx = math.sin(t * 0.7 + i * 2.1) * 2.0
            dy = math.cos(t * 0.5 + i * 1.3) * 2.0
            painter.setBrush(QColor(255, 255, 255, 42))
            painter.drawEllipse(QPointF(bx + dx, by + dy), r, r)

        # Soft top-left highlight.
        painter.setBrush(QColor(255, 255, 255, 70))
        painter.drawEllipse(QPointF(-w * 0.34, -h * 0.42), w * 0.30, h * 0.22)

        self._draw_pattern(painter, pose)
        painter.restore()

    def _draw_pattern(self, painter, pose):
        """Decorative species pattern, clipped to the body silhouette by the
        caller. Purely cosmetic — never affects shape or animation."""
        if self.pattern == "plain":
            return
        w, h = self.BODY_W, self.BODY_H
        painter.setPen(Qt.PenStyle.NoPen)
        shade = QColor(self.BODY_DARK.red(), self.BODY_DARK.green(),
                       self.BODY_DARK.blue(), 100)

        if self.pattern == "spots":
            painter.setBrush(shade)
            for sx, sy, r in ((-w * 0.35, h * 0.15, 4.5), (w * 0.15, h * 0.55, 3.6),
                              (w * 0.42, -h * 0.05, 3.0), (-w * 0.05, h * 0.75, 3.2),
                              (-w * 0.50, -h * 0.10, 2.6)):
                painter.drawEllipse(QPointF(sx, sy), r, r)

        elif self.pattern == "stripes":
            painter.setBrush(shade)
            for sy in (-h * 0.35, -h * 0.02, h * 0.32, h * 0.68):
                painter.drawRoundedRect(QRectF(-w * 1.15, sy, w * 2.3, 5.0), 2.5, 2.5)

        elif self.pattern == "stars":
            sparkle = QColor(255, 255, 255, 210)
            for sx, sy, r in ((-w * 0.40, -h * 0.10, 2.4), (w * 0.30, h * 0.30, 2.0),
                              (w * 0.05, -h * 0.38, 1.8), (-w * 0.10, h * 0.62, 2.0),
                              (w * 0.48, -h * 0.02, 1.6)):
                self._draw_star(painter, sx, sy, r, sparkle)

    def _draw_star(self, painter, cx, cy, r, color):
        path = QPainterPath()
        for i in range(5):
            angle = math.pi / 2 + i * (2 * math.pi / 5)
            outer = QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle))
            if i == 0:
                path.moveTo(outer)
            else:
                path.lineTo(outer)
            inner_angle = angle + math.pi / 5
            path.lineTo(QPointF(cx + r * 0.45 * math.cos(inner_angle),
                                cy - r * 0.45 * math.sin(inner_angle)))
        path.closeSubpath()
        painter.setBrush(color)
        painter.drawPath(path)

    def _draw_face(self, painter, pose):
        eye_y = -8.0
        eye_rx = 8.0 * pose.eye_scale
        eye_ry = 10.5 * pose.eye_scale * max(pose.eye_open, 0.0)
        px = pose.pupil_dx * 3.0
        py = pose.pupil_dy * 2.0

        for side in (-1, 1):
            ex = side * 16.0 + px
            if pose.eye_open < 0.18:
                # Closed eye: a soft downward curve.
                path = QPainterPath(QPointF(ex - eye_rx, eye_y + 2))
                path.quadTo(ex, eye_y + 6.5, ex + eye_rx, eye_y + 2)
                painter.setPen(QPen(EYE_COLOR, 2.4,
                                    Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(EYE_COLOR)
            painter.drawEllipse(QPointF(ex, eye_y + py), eye_rx, eye_ry)
            # Sparkles.
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.drawEllipse(
                QPointF(ex - eye_rx * 0.32, eye_y + py - eye_ry * 0.35),
                eye_rx * 0.34, eye_ry * 0.28)
            painter.setBrush(QColor(255, 255, 255, 160))
            painter.drawEllipse(
                QPointF(ex + eye_rx * 0.30, eye_y + py + eye_ry * 0.30),
                eye_rx * 0.16, eye_ry * 0.13)

        # Eyebrows — only drawn when an expression sets pose.brow (angry
        # furrows it down at the center, sad/scared raises it worriedly).
        # Hidden (brow == 0) for the pet's normal neutral/happy look.
        if abs(pose.brow) > 0.05:
            painter.setPen(QPen(EYE_COLOR, 2.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            for side in (-1, 1):
                ex = side * 16.0 + px
                inner_x = ex - side * 6.0
                outer_x = ex + side * 6.0
                base_y = eye_y - 12.0
                inner_y = base_y - 3.0 * pose.brow
                outer_y = base_y + 3.0 * pose.brow
                painter.drawLine(QPointF(outer_x, outer_y),
                                  QPointF(inner_x, inner_y))

        # Blush.
        if pose.blush > 0:
            blush = QColor(BLUSH_COLOR)
            blush.setAlpha(int(120 * pose.blush))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(blush)
            for side in (-1, 1):
                painter.drawEllipse(QPointF(side * 27.0, 3.0), 6.5, 4.0)

        # Mouth: round "o" when surprised, mood curve otherwise.
        if pose.mouth_open > 0.3:
            painter.setPen(QPen(EYE_COLOR, 2.0))
            painter.setBrush(QColor(90, 50, 110))
            painter.drawEllipse(QPointF(0, 9.0), 4.5, 5.5 * pose.mouth_open)
        else:
            path = QPainterPath(QPointF(-7.0, 8.0))
            path.quadTo(0.0, 8.0 + 9.0 * pose.mouth, 7.0, 8.0)
            painter.setPen(QPen(EYE_COLOR, 2.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        # Tiny snack prop, shrinking away — only visible during the EAT action.
        if pose.food_visual > 0.01:
            r = 4.5 * pose.food_visual
            painter.setPen(QPen(QColor("#B87A2E"), 1.0))
            painter.setBrush(QColor("#FFCB61"))
            painter.drawEllipse(QPointF(9.0, 13.0), r, r)

    def _draw_zzz(self, painter, pose):
        pulse = (math.sin(pose.t * 1.6) + 1.0) / 2.0
        color = QColor(self.BODY_EDGE)
        color.setAlpha(int(120 + 100 * pulse))
        painter.setPen(color)
        painter.setFont(self._zzz_font)
        base_x = self.cx + 34
        base_y = self.ground - 2 * self.BODY_H - 14
        painter.drawText(QPointF(base_x, base_y + pulse * -3), "z")
        painter.drawText(QPointF(base_x + 10, base_y - 12 + pulse * -4), "z")
