# -*- coding: utf-8 -*-
"""手绘示意图：在教案上画出像老师随手画的简笔示意图（红笔/黑笔）。

设计要点（做到"看得出是人画的"）：
- 所有线条用抖动贝塞尔曲线，不是标准几何直线
- 线宽有粗细变化（起笔重、收笔轻）
- 圆/椭圆故意画歪、首尾不完全闭合
- 图旁配手写文字标注（无衬线箭头指向）
- 整体有一点随机旋转（人写字不会完全水平）
"""
import math
import random

import numpy as np
from PIL import Image, ImageDraw


class HandPen:
    """手绘笔：画在 RGBA 图层上，输出可叠加到教案的图块。"""

    def __init__(self, w, h, ink=(26, 28, 36), seed=0, width=3.0):
        self.w, self.h = w, h
        self.ink = ink
        self.rng = random.Random(seed)
        self.base_w = width
        self.img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)

    # ---- 基础：抖动线段 ----
    def _w(self, t):
        """线宽沿笔画变化：起笔略重、中间最重、收笔轻。"""
        return max(0.7, self.base_w * (0.75 + 0.55 * math.sin(math.pi * min(1, max(0, t)) ** 0.8)))

    def line(self, p0, p1, jitter=0.55, segs=22, taper=True):
        rng = self.rng
        x0, y0 = p0
        x1, y1 = p1
        pts = []
        for i in range(segs + 1):
            t = i / segs
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            if 0 < i < segs:
                x += rng.uniform(-jitter, jitter)
                y += rng.uniform(-jitter, jitter)
            pts.append((x, y))
        self.polyline(pts, taper=taper)

    def polyline(self, pts, taper=True):
        n = len(pts)
        for i in range(n - 1):
            t = i / max(1, n - 1)
            wpx = self._w(t) if taper else self.base_w
            self.draw.line([pts[i], pts[i + 1]], fill=self.ink + (255,), width=max(1, int(round(wpx))))

    # ---- 圆/椭圆：故意画歪、不闭合 ----
    def ellipse(self, cx, cy, rx, ry, start=0, end=None, jitter=None, wobble=None, segs=110):
        rng = self.rng
        if end is None:
            end = 2 * math.pi
        # 半径越小，抖动要按比例收敛，否则小圆会被抖开缺口
        rmin = min(abs(rx), abs(ry))
        if jitter is None:
            jitter = max(0.06, min(0.18, rmin * 0.010))
        if wobble is None:
            wobble = max(0.002, min(0.006, rmin * 0.0004))
        # 画满一整圈并略微过头（人画圈会多画一点），保证首尾接上
        end = start + (end - start) * rng.uniform(1.06, 1.12)
        pts = []
        for i in range(segs + 1):
            t = i / segs
            a = start + (end - start) * t
            # 半径轻微起伏 + 手抖
            r_rx = rx * (1 + rng.uniform(-wobble, wobble))
            r_ry = ry * (1 + rng.uniform(-wobble, wobble))
            x = cx + r_rx * math.cos(a) + rng.uniform(-jitter, jitter)
            y = cy + r_ry * math.sin(a) + rng.uniform(-jitter, jitter)
            pts.append((x, y))
        # 收口：沿圆周再多走一小段（圆弧，不是直线弦），落点贴近起点
        over = 0.10
        for k in (0.35, 0.70, 1.0):
            a = start + (end - start) * (1.0 + over * k)
            x = cx + rx * math.cos(a) + rng.uniform(-0.35, 0.35)
            y = cy + ry * math.sin(a) + rng.uniform(-0.35, 0.35)
            pts.append((x, y))
        self.polyline(pts)


    # ---- 箭头（带箭头头部） ----
    def arrow(self, p0, p1, head=7.0):
        self.line(p0, p1, jitter=0.8, segs=12)
        x0, y0 = p0
        x1, y1 = p1
        ang = math.atan2(y1 - y0, x1 - x0)
        for da in (2.6, -2.6):
            hx = x1 + head * math.cos(ang + da)
            hy = y1 + head * math.sin(ang + da)
            self.line((x1, y1), (hx, hy), jitter=0.4, segs=5)


def draw_mitosis_diagram(w, h, ink=(176, 32, 40), seed=7):
    """有丝分裂/细胞分裂示意：一个细胞 → 两个细胞，中间染色体变化。

    画成老师随手画的样子：圆圈 + 中间几条染色体（扭曲线）+ 箭头。
    """
    pen = HandPen(w, h, ink=ink, seed=seed, width=3.2)
    rng = pen.rng

    # 布局自适应：画布偏竖（宽/高 < 0.55）时上下排，否则左右排
    vertical = (w / max(1, h)) < 0.55
    if vertical:
        # 母细胞在左上，箭头向下，两个子细胞并排在下方
        r = min(w * 0.36, h * 0.155)
        mx = w * 0.42
        my = h * 0.26
        pen.ellipse(mx, my, r, r, start=rng.uniform(0, 1), segs=80)
        # 母细胞内两条清晰的 X 形染色体
        for k in (-1, 1):
            cx0 = mx + k * r * 0.30
            cy0 = my + rng.uniform(-r * 0.10, r * 0.10)
            arm = r * 0.34
            a = rng.uniform(0.2, 0.6)
            for sgn in (-1, 1):
                pts = [(cx0 - arm * math.cos(a * sgn), cy0 - arm * math.sin(a * sgn)),
                       (cx0 + arm * math.cos(a * sgn), cy0 + arm * math.sin(a * sgn))]
                pen.polyline(pts)
        # 竖箭头
        a0 = (mx, my + r * 1.15)
        a1 = (mx, h * 0.50)
        pen.line(a0, a1, jitter=0.55, segs=22)
        ang = math.atan2(a1[1] - a0[1], a1[0] - a0[0])
        for da in (2.6, -2.6):
            pen.line(a1, (a1[0] + 9 * math.cos(ang + da), a1[1] + 9 * math.sin(ang + da)),
                     jitter=0.4, segs=5)
        rs = w * 0.215
        for (ccx, ccy) in ((w * 0.245, h * 0.71), (w * 0.755, h * 0.71)):
            pen.ellipse(ccx, ccy, rs, rs, start=rng.uniform(0, 2), end=None,
                        jitter=0.10, wobble=0.0025, segs=96)
            # 圈内画两条短染色体（长度限制在半径 0.55 以内，绝不画出圈外）
            for k in range(2):
                cx0 = ccx + rng.uniform(-rs * 0.22, rs * 0.22)
                cy0 = ccy + rng.uniform(-rs * 0.22, rs * 0.22)
                arm = rs * rng.uniform(0.30, 0.42)
                a = rng.uniform(0, math.pi)
                pts = [(cx0 - arm * math.cos(a), cy0 - arm * math.sin(a)),
                       (cx0 + arm * math.cos(a), cy0 + arm * math.sin(a))]
                pen.polyline(pts)
        return pen.img

    # 横向布局：左圆（母细胞）→ 箭头 → 右两个小圆（子细胞）
    cy = h * 0.50


def draw_microscope_diagram(w, h, ink=(176, 32, 40), seed=11):
    """显微镜简笔示意：镜筒+目镜+物镜+载物台+反光镜。"""
    pen = HandPen(w, h, ink=ink, seed=seed, width=2.5)
    rng = pen.rng
    cx = w * 0.5

    # 镜筒（略斜）
    top_x, top_y = cx - w * 0.02, h * 0.10
    bot_x, bot_y = cx + w * 0.01, h * 0.38
    pen.line((top_x, top_y), (bot_x, bot_y), jitter=1.0, segs=16)
    pen.line((top_x + w * 0.07, top_y), (bot_x + w * 0.07, bot_y), jitter=1.0, segs=16)
    # 目镜
    pen.ellipse(top_x + w * 0.035, top_y - 3, w * 0.045, h * 0.028, segs=36)
    # 物镜
    pen.line((bot_x - 2, bot_y), (bot_x + w * 0.05, bot_y), jitter=0.6, segs=8)
    pen.line((bot_x + w * 0.015, bot_y), (bot_x + w * 0.012, bot_y + h * 0.06), jitter=0.7, segs=8)
    pen.line((bot_x + w * 0.04, bot_y), (bot_x + w * 0.042, bot_y + h * 0.06), jitter=0.7, segs=8)
    # 载物台
    pen.line((cx - w * 0.18, bot_y + h * 0.09), (cx + w * 0.20, bot_y + h * 0.09), jitter=1.0, segs=14)
    # 镜臂
    pen.line((cx + w * 0.10, top_y + h * 0.04), (cx + w * 0.10, bot_y + h * 0.22), jitter=1.2, segs=18)
    # 底座
    pen.line((cx - w * 0.14, bot_y + h * 0.30), (cx + w * 0.22, bot_y + h * 0.30), jitter=1.0, segs=14)
    pen.line((cx - w * 0.10, bot_y + h * 0.30), (cx - w * 0.06, bot_y + h * 0.22), jitter=0.8, segs=8)
    # 反光镜
    pen.ellipse(cx - w * 0.06, bot_y + h * 0.19, w * 0.055, h * 0.030, segs=40)
    return pen.img


def make_diagram(kind, w, h, ink=(176, 32, 40), seed=7):
    if kind == "mitosis":
        return draw_mitosis_diagram(w, h, ink=ink, seed=seed)
    if kind == "microscope":
        return draw_microscope_diagram(w, h, ink=ink, seed=seed)
    raise ValueError(kind)


if __name__ == "__main__":
    for kind in ("mitosis", "microscope"):
        im = make_diagram(kind, 300, 260, seed=7)
        bg = Image.new("RGB", im.size, (252, 250, 246))
        bg.paste(im, (0, 0), im)
        bg.save(r"D:\hermes-files\手写模拟器\_diag_%s.png" % kind)
        print(kind, "ok")
