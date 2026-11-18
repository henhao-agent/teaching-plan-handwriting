# -*- coding: utf-8 -*-
"""笔画级手写渲染器 V4 —— 照萝卜工坊的笔迹特征复刻

看了萝卜工坊的成品放大图，它的笔画有四个决定性特征（我之前全没做对）：

1. **横画是"梭子形"**：两头尖细、中段略粗，不是等宽的矩形条。
   这是硬笔快写的典型——下笔轻、中间压重、收笔一挑就离开纸。
2. **竖画/撇捺带弧度**：不是笔直的一条，中段有轻微弯曲，末端甩出去变尖。
3. **笔画之间有牵丝**：上一笔收笔和下一笔起笔之间有细细的连接线，
   字内部因此"气脉贯通"，不是一个笔画一个笔画地摆上去。
4. **墨色沿笔画渐淡**：起笔浓、走笔淡、收笔几乎没墨（快写时提笔离纸）。

我自己 V3 失败的原因：在"字体轮廓"上叠噪点、叠压力场。
字体轮廓本身就是等宽笔画，叠什么都是在等宽笔画上打补丁，所以永远像印刷体。
正确做法：**先求出笔画的骨架线（中轴线），再沿骨架线做粗细调制**，
粗细和方向由骨架的局部走向决定——这才叫"写出来"。

实现：
    字体轮廓 → 骨架提取（形态学细化）
    → 每条骨架分支（=一笔）判定走向（横/竖/斜）
    → 按走向给变宽模板（横梭形、竖半梭形、撇捺渐细）
    → 用距离变换把细骨架"长"成变宽笔画
    → 端点加牵丝、墨色渐变、纸纹
"""
import os
import math
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "app", "fonts")

FONT_PATHS = {
    "悠哉": os.path.join(FONT_DIR, "Yozai-悠哉手写.ttf"),
    "猫啃": os.path.join(FONT_DIR, "Maoken-猫啃硬笔楷书.ttf"),
    "小赖": os.path.join(FONT_DIR, "Xiaolai-小赖手写.ttf"),
    "文楷": os.path.join(FONT_DIR, "LXGWWenKai-Regular.ttf"),
    "LuoboF3": os.path.join(FONT_DIR, "LuoboF3-萝卜工坊手写.ttf"),
    "龙藏": os.path.join(FONT_DIR, "LongCang-龙藏.ttf"),
    "志莽行": os.path.join(FONT_DIR, "ZhiMangXing-志莽行.ttf"),
    "马善政": os.path.join(FONT_DIR, "MaShanZheng-马善政.ttf"),
}

SS = 3      # 超采样
# 笔画粗细系数：base_w = 字形最大内切半径 × STROKE_GAIN
# 1.18 → 均值约0.48mm（偏细，像0.38笔）
# 1.28 → 均值约0.52mm，主笔0.5mm上下、顿笔0.6~0.7mm（0.5mm签字笔那一版）
# 1.45 → 均值约0.59mm（哥哥2026-11-17选定 C 档，笔画更实更黑）
STROKE_GAIN = 1.45

# 字形视觉归一化：每个字按最长边拉到 fs*GLYPH_FILL 的视觉尺寸
# 字体本身各字字形框不齐（"入"101 vs "等"123），不归一化会"有的字大有的字小"，太刻意
# 1.0 = 最大边正好等于字号；汉字手写约占九成字面
GLYPH_FILL = 0.92
# 单字残余自然随机（σ）。0.018 → 极差约 ±5%，肉眼能看出是手写，但不会有明显大小跳变
SIZE_JITTER = 0.010
# 归一化门槛：字形最长边至少达字号的这个比例才归一化（0.5 → 小于半字号的一律不碰）
# 汉字字形框一般 ≥0.8 字号；句点 "." 只有 0.15，硬拉会变大黑块
NORM_MIN_RATIO = 0.5
# 归一化上限：字形最长边超过 1.3 字号的（如"（）"竖长条）也不归一化
NORM_MAX_RATIO = 1.3


# ---------------------------------------------------------------- 基础
def glyph_mask(font_path, ch, fs):
    """高分辨率实心字形（0/1）"""
    px = max(16, int(fs * SS))
    font = ImageFont.truetype(font_path, px)
    box = px * 3
    img = Image.new("L", (box, box), 0)
    ImageDraw.Draw(img).text((px * 0.3, px * 0.3), ch, font=font, fill=255)
    a = np.array(img)
    ys, xs = np.where(a > 100)
    if len(ys) == 0:
        return None
    return (a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 100).astype(np.uint8)


def skeletonize(binimg):
    """形态学细化求骨架（不依赖 skimage）"""
    try:
        from skimage.morphology import skeletonize as sk
        return sk(binimg.astype(bool)).astype(np.uint8)
    except Exception:
        pass
    # 手写 Zhang-Suen 细化
    img = binimg.copy().astype(np.uint8)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            p = np.pad(img, 1)
            P2 = p[0:-2, 1:-1]; P3 = p[0:-2, 2:]; P4 = p[1:-1, 2:]; P5 = p[2:, 2:]
            P6 = p[2:, 1:-1];   P7 = p[2:, 0:-2]; P8 = p[1:-1, 0:-2]; P9 = p[0:-2, 0:-2]
            B = P2 + P3 + P4 + P5 + P6 + P7 + P8 + P9
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            if step == 0:
                cond = ((img == 1) & (B >= 2) & (B <= 6) & (A == 1) &
                        (P2 * P4 * P6 == 0) & (P4 * P6 * P8 == 0))
            else:
                cond = ((img == 1) & (B >= 2) & (B <= 6) & (A == 1) &
                        (P2 * P4 * P8 == 0) & (P2 * P6 * P8 == 0))
            if cond.any():
                img[cond] = 0
                changed = True
    return img


def branch_directions(skel):
    """给骨架每个像素估局部走向（用邻域主成分），返回 (angle, straightness)。
    angle: 0=水平, pi/2=垂直；straightness 越高越"直"。"""
    ys, xs = np.nonzero(skel)
    if len(ys) < 3:
        return np.zeros(skel.shape, np.float32), np.zeros(skel.shape, np.float32)
    ang = np.zeros(skel.shape, np.float32)
    strt = np.zeros(skel.shape, np.float32)
    pts = set(zip(ys.tolist(), xs.tolist()))
    h, w = skel.shape
    R = 3
    for (y, x) in pts:
        nb = []
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                if dy == 0 and dx == 0:
                    continue
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w and skel[yy, xx]:
                    nb.append((dy, dx))
        if len(nb) < 2:
            ang[y, x] = 0
            strt[y, x] = 0.5
            continue
        m = np.array(nb, np.float32)
        cov = m.T @ m / len(m)
        ev, evec = np.linalg.eigh(cov)
        v = evec[:, -1]                     # 主方向
        ang[y, x] = math.atan2(v[0], v[1]) % math.pi
        # 直的程度：主轴/次轴比
        ratio = (ev[-1] + 1e-6) / (ev[0] + 1e-6)
        strt[y, x] = float(np.clip(ratio / 8.0, 0, 1))
    return ang, strt


def width_profile(dist, skel, ang, strt, rng, base_w):
    """按骨架走向给每个骨架点一个"笔画半宽"。

    这是整个 V4 的核心：横画梭形（两端细）、竖画匀中带细、撇捺单向渐细。
    """
    h, w = dist.shape
    prof = np.ones((h, w), np.float32)

    ys, xs = np.nonzero(skel)
    if len(ys) == 0:
        return prof

    # 先按 8 连通把骨架拆成一条条「笔画」（=一个连通分支），
    # 只有在同一笔内部才谈「两头细中间粗」——按整字位置算会导致
    # 每道横都只中间一点粗、其余变成浮空短线（这是 V4 第一版的致命错）
    from scipy import ndimage as ndi
    labels, n_lab = ndi.label(skel, structure=np.ones((3, 3), dtype=int))

    for lab in range(1, n_lab + 1):
        m = (labels == lab)
        if m.sum() < 2:
            continue
        by, bx = np.nonzero(m)
        y_lo, y_hi = by.min(), by.max()
        x_lo, x_hi = bx.min(), bx.max()
        span_y = max(1, y_hi - y_lo)
        span_x = max(1, x_hi - x_lo)
        horiz = span_x >= span_y          # 这一笔整体是横还是竖

        for yy, xx in zip(by, bx):
            a = ang[yy, xx]
            st = strt[yy, xx]
            near_h = min(abs(a), abs(a - math.pi))
            near_v = abs(a - math.pi / 2)
            if horiz and near_h < 0.55:
                # 横笔：在这一笔自身的起止之间做梭子形
                t = (xx - x_lo) / span_x
                prof[yy, xx] = 0.50 + 0.80 * math.sin(math.pi * min(1.0, max(0.0, t)) ** 0.70)
            elif (not horiz) and near_v < 0.55:
                # 竖笔：起笔略重，收笔提细
                t = (yy - y_lo) / span_y
                prof[yy, xx] = 1.00 - 0.30 * t
            else:
                # 斜笔/折笔：沿这一笔自身走向渐细
                t = ((yy - y_lo) / span_y * 0.5 + (xx - x_lo) / span_x * 0.5)
                prof[yy, xx] = 1.06 - 0.42 * t
            # 转折处压笔稍粗
            prof[yy, xx] *= (1.0 + 0.14 * (1.0 - st))

    return prof


def build_stroke(binimg, rng, base_w=None):
    """把实心字形 → 变宽笔画墨量场（0~1）"""
    skel = skeletonize(binimg)
    if skel.sum() == 0:
        return binimg.astype(np.float32)
    ang, strt = branch_directions(skel)
    try:
        import scipy.ndimage as ndi
        dist = ndi.distance_transform_edt(binimg)
    except Exception:
        dist = None

    if dist is None or dist.max() == 0:
        return binimg.astype(np.float32)

    h, w = binimg.shape
    if base_w is None:
        base_w = max(1.0, dist.max() * STROKE_GAIN)

    prof = width_profile(dist, skel, ang, strt, rng, base_w)

    # 每个笔画点向外"长"出变宽笔画：用 prof 缩放距离场
    # 先把 prof 从骨架扩散到整个字形区域
    try:
        import scipy.ndimage as ndi
        idx = ndi.distance_transform_edt(skel == 0, return_distances=False, return_indices=True)
        prof_full = prof[tuple(idx)]
    except Exception:
        prof_full = np.ones((h, w), np.float32)

    # 目标半宽 = base_w * prof；实际距离 dist。用 sigmoid 边缘制造软过渡
    target = np.maximum(1.0, base_w * prof_full)
    t = dist / np.maximum(1e-3, target)
    # t=1 处正好是笔画边缘，用平滑衰减得到抗锯齿边缘
    ink = 1.0 / (1.0 + np.exp((t - 1.0) * 4.2))
    # 只保留原字形附近的范围，别把空白糊满
    ink = ink * (dist > 0).astype(np.float32)
    # 笔画中心加浓（墨在纸中间积得多）
    ink = ink * (0.82 + 0.30 * np.clip(dist / np.maximum(1e-3, target), 0, 1))
    return np.clip(ink, 0, 1)


def ink_shade(ink, rng):
    """墨色渐变：起笔浓、收笔淡（沿骨架方向），叠加低频不均匀。"""
    h, w = ink.shape
    # 低频墨量起伏
    n = np.random.default_rng(rng.randint(0, 999999)).normal(0, 1, (h // 6 + 1, w // 6 + 1))
    n = np.array(Image.fromarray(((n * 30) + 128).clip(0, 255).astype(np.uint8))
                 .resize((w, h), Image.BICUBIC)).astype(np.float32)
    n = (n - 128) / 128.0
    shade = 1.0 + n * 0.34
    # 左上浓、右下淡（书写方向）
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ramp = 1.14 - 0.34 * ((xx / max(1, w)) * 0.55 + (yy / max(1, h)) * 0.45)
    return np.clip(ink * shade * ramp, 0, 1)


def glyph_norm_scale(font_path, ch, fs):
    """单字的视觉大小归一化系数。

    字体本身各字字形框大小不齐（"入"101、"等"123，差两成），
    不归一化就会出现"有的字大有的字小"，看着很刻意。
    这里按字形框最长边（≈汉字的视觉字面）把每个字拉到同一视觉尺寸，
    只保留极小的自然偏差。结果按 (fs*SS) 为基准长度换算。
    """
    b = glyph_mask(font_path, ch, fs)
    if b is None:
        return 1.0
    m = float(max(b.shape))
    ref = fs * SS * GLYPH_FILL   # 目标视觉边长（相对字号）
    return ref / max(1.0, m)


def render_char(font_path, ch, fs, rng, ink_rgb=(26, 28, 36)):
    """单字 → RGBA，带真运笔质感（视觉大小已归一化）"""
    b = glyph_mask(font_path, ch, fs)
    if b is None:
        return None
    ink = build_stroke(b, rng)
    ink = ink_shade(ink, rng)

    # 纸纹毛刺（轻）
    h, w = ink.shape
    fn = np.random.default_rng(rng.randint(0, 999999)).normal(0, 1, (h, w)).astype(np.float32)
    fn = np.array(Image.fromarray(((fn * 26) + 128).clip(0, 255).astype(np.uint8))
                  .filter(ImageFilter.GaussianBlur(0.5))).astype(np.float32)
    ink = ink * (1.0 + ((fn - 128) / 128.0) * 0.14)
    ink = np.clip(ink, 0, 1)

    img = Image.fromarray((ink * 255).astype(np.uint8))
    # 缩回目标字号（超采样 → 缩，边缘自然有灰阶）
    # 视觉归一化：按最长边拉到统一字面，只留极小随机差（σ=0.018 ≈ 极差 12%）
    # 但标点（. , 等）、数字、超小字形不归一化——它们本来就该小，
    # 硬拉到统一字面会变成大黑块（"." 曾是 40×40 的实心圆）
    sc = 1.0 / SS
    m = float(max(h, w))
    # 只有"像汉字"的字形才归一化：字宽、字高都在半字号到1.3字号之间。
    # 标点（. “” （） ）、数字、窄横都不碰——它们本来就该小/该窄，
    # 硬拉到统一字面会变成大黑块（"." 曾是 40×40 实心圆），引号会被压成顿号
    if (fs * SS * NORM_MIN_RATIO) <= m <= (fs * SS * NORM_MAX_RATIO) \
            and min(h, w) >= fs * SS * NORM_MIN_RATIO:
        sc *= (GLYPH_FILL * SS * fs / m) * (1.0 + rng.gauss(0, SIZE_JITTER))
    nw = max(2, int(w * sc))
    nh = max(2, int(h * sc))
    img = img.resize((nw, nh), Image.LANCZOS)
    a = np.array(img).astype(np.float32) / 255.0

    _rot = rng.gauss(0, 0.9)
    if abs(_rot) > 0.35:
        a = np.array(Image.fromarray((a * 255).astype(np.uint8))
                     .rotate(_rot, resample=Image.BICUBIC,
                             expand=False, fillcolor=0)).astype(np.float32) / 255.0

    base = np.array(ink_rgb, np.float32)
    rgba = np.zeros((*a.shape, 4), np.float32)
    for i in range(3):
        rgba[:, :, i] = base[i]
    rgba[:, :, 3] = np.clip(a * 255 * 1.15, 0, 255)
    return Image.fromarray(rgba.astype(np.uint8), "RGBA")


def render_text(font_path, text, fs, seed=0, tight=0.94, ink_rgb=(26, 28, 36),
                paper=(252, 250, 246)):
    """一行字（含字间牵丝）→ (RGB 图, RGBA)"""
    rng = random.Random(seed)
    items = []
    for ch in text:
        if ch == " ":
            items.append((" ", None, fs * 0.45)); continue
        if ch in "，、。；：！？":
            t = render_punct(ch, fs, rng, ink_rgb)      # 手写笔点，不用印刷体标点
            adv = fs * rng.uniform(0.40, 0.50)
        else:
            t = render_char(font_path, ch, fs, rng, ink_rgb)
            adv = fs * tight
        items.append((ch, t, adv))

    H = int(fs * 1.95)
    W = int(sum(a for _, _, a in items) + fs * 1.5)
    canvas = Image.new("RGBA", (max(8, W), max(8, H)), (0, 0, 0, 0))
    x = fs * 0.35
    base_line = int(H * 0.74)
    slope = rng.gauss(0, 0.004)
    prev = None

    for ch, t, adv in items:
        if t is not None:
            is_p = ch in "，。、；：！？"
            dy = rng.gauss(0, fs * 0.011) + slope * x
            if is_p:
                # 笔点：墨点中心压在基线上，露在字的右下角（真手写位置）
                py = base_line - int(t.height * 0.42) + int(dy)
            else:
                py = base_line - t.height + int(dy)
                # 扁字（一/二/三、冖这类只有横画的）视觉重心在字面下三分之一处，
                # 纯按底边对齐会显得往下掉，抬一点回来
                if t.height < fs * 0.42:
                    py = int(base_line - t.height - fs * 0.30 + dy)
            px = int(x)

            # 字间牵丝：上一个字右端 → 这个字左端，一条细弧线
            if prev is not None and rng.random() < 0.0:
                p0 = (prev[0] + prev[1].width - 2, prev[2] + int(prev[1].height * 0.55))
                p1 = (px + 2, py + int(t.height * 0.60))
                _draw_tie(canvas, p0, p1, rng, ink_rgb, fs)

            if 0 <= px < canvas.width:
                canvas.alpha_composite(t, (max(0, px), max(0, min(py, canvas.height - t.height))))
            prev = (px, t, py)
        x += adv + rng.gauss(0, fs * 0.008)
        if rng.random() < 0.03:
            x += fs * rng.uniform(0.08, 0.20)

    a = np.array(canvas)
    ys, xs = np.where(a[:, :, 3] > 8)
    if len(ys):
        canvas = canvas.crop((max(0, xs.min() - 4), max(0, ys.min() - 4),
                              min(canvas.width, xs.max() + 5), min(canvas.height, ys.max() + 5)))
    bg = Image.new("RGB", canvas.size, paper)
    bg.paste(canvas, (0, 0), canvas)
    return bg, canvas




# ============ 手写笔点标点 ============
def render_punct(ch, fs, rng, ink_rgb=(26, 28, 36)):
    """把印刷体标点画成真人手写的笔点/短撇。

    真人写「，」「。」「、」就是笔尖在纸上顿一下，是一个圆润的墨点，
    带拖动的小尾巴；「；」「：」是上下两点；「！」「？」保留问号但改手写感。
    返回 RGBA（尺寸按 fs 缩放），高度与汉字基线对齐。
    """
    S = SS * 2                    # 超采样
    H = int(fs * 1.95)
    W = int(fs * 0.62)
    Wc, Hc = W * S, H * S
    layer = Image.new("L", (max(4, Wc), max(4, Hc)), 0)
    d = ImageDraw.Draw(layer)

    # 基线位置（和 render_text 里 base_line 一致：H*0.74）
    base = Hc * 0.74
    r_base = fs * S * rng.uniform(0.050, 0.068)     # 点的大小：约字号 5-7%（真手写标点很小）

    def pen_dot(cx, cy, r, wag=1.0):
        """真人用笔尖在纸上顿一下：不是圆，是一小团不规则的墨渍。

        做法：沿一条随机的短路径反复落笔（多用几条粗细不一的短线叠出形状），
        起笔重、收笔轻，边缘随机吐墨、飞白，绝不出现规整的圆/椭圆。
        """
        rr = max(1.0, r * wag)
        # 主体：一条沿粗略书写方向（右下）的短粗线，就是"按下去"那一下
        n_ov = rng.randint(2, 4)                    # 叠笔次数（太多就成一坨墨）
        ang0 = rng.uniform(0.35, 1.15) * (1 if rng.random() < 0.75 else -1)   # 主方向
        for k in range(n_ov):
            t = k / max(1, n_ov - 1)
            # 反复描画同一处，位置有细微漂移 → 墨迹不均
            ox = rng.gauss(0, rr * 0.22)
            oy = rng.gauss(0, rr * 0.20)
            seg_len = rr * rng.uniform(0.45, 1.15)
            dx = math.cos(ang0 + rng.gauss(0, 0.28)) * seg_len
            dy = math.sin(ang0 + rng.gauss(0, 0.28)) * seg_len
            wv = max(1, int(rr * rng.uniform(0.75, 1.20) * (1.0 - 0.35 * t)))  # 渐细
            x1 = cx + ox - dx * 0.5
            y1 = cy + oy - dy * 0.5
            x2 = cx + ox + dx * 0.5
            y2 = cy + oy + dy * 0.5
            fill = int(rng.uniform(165, 235) * (1.0 - 0.15 * t))
            d.line([x1, y1, x2, y2], fill=fill, width=wv)
            # 圆头收尾（用几个小点糊一下端点，模拟笔尖压纸）
            for (qx, qy, qw) in ((x1, y1, wv), (x2, y2, max(1, wv - 1))):
                d.line([qx - qw * 0.35, qy, qx + qw * 0.35, qy], fill=fill, width=qw)
        # 边缘吐墨：沿主体外圈几个随机小碎点
        for _ in range(rng.randint(2, 5)):
            a = rng.uniform(0, 2 * math.pi)
            rad = rr * rng.uniform(0.55, 1.15)
            sx, sy = cx + math.cos(a) * rad, cy + math.sin(a) * rad * 0.82
            sw = max(1, int(rr * rng.uniform(0.16, 0.34)))
            d.line([sx, sy, sx + rng.gauss(0, rr * 0.18), sy + rng.gauss(0, rr * 0.18)],
                   fill=int(rng.uniform(150, 220)), width=sw)

    def tail(cx, cy, dx, dy, w0):
        """手写的挑尾/拖尾：一条从粗到细、略带弧度的短线。"""
        steps = rng.randint(2, 4)
        px, py = cx, cy
        for k in range(steps):
            t = (k + 1) / steps
            nx = cx + dx * t + rng.gauss(0, w0 * 0.20)
            ny = cy + dy * t + rng.gauss(0, w0 * 0.18)
            wv = max(1, int(w0 * (1.0 - 0.55 * t)))
            d.line([px, py, nx, ny], fill=int(rng.uniform(160, 235)), width=wv)
            px, py = nx, ny

    if ch in "，、":
        # 顿点 + 往右下带一个短尾（不是圆点）
        cx = Wc * rng.uniform(0.38, 0.48)
        cy = base - r_base * rng.uniform(0.0, 0.4)
        pen_dot(cx, cy, r_base)
        tail(cx + r_base * 0.5, cy + r_base * 0.3,
             r_base * rng.uniform(0.7, 1.5), r_base * rng.uniform(0.9, 1.8),
             max(1, r_base * 0.55))
    elif ch == "。":
        # 句号：一团压得重一点的墨渍（手写常是小点，不画圈）
        cx = Wc * rng.uniform(0.40, 0.52)
        cy = base - r_base * rng.uniform(0.0, 0.35)
        pen_dot(cx, cy, r_base * rng.uniform(1.00, 1.18), wag=1.0)
    elif ch == "；":
        r_s = r_base * rng.uniform(0.9, 1.1)
        c1 = (Wc * rng.uniform(0.38, 0.50), base - r_base * rng.uniform(1.7, 2.2))
        c2 = (Wc * rng.uniform(0.38, 0.50), base - r_s * rng.uniform(0.0, 0.5))
        pen_dot(c1[0], c1[1], r_s)
        tail(c1[0] + r_s * 0.4, c1[1] + r_s * 0.3, r_s * 0.8, r_s * 1.3, max(1, r_s * 0.5))
        pen_dot(c2[0], c2[1], r_s)
        tail(c2[0] + r_s * 0.4, c2[1] + r_s * 0.3, r_s * 0.8, r_s * 1.3, max(1, r_s * 0.5))
    elif ch == "：":
        r_s = r_base * rng.uniform(0.85, 1.05)
        pen_dot(Wc * rng.uniform(0.38, 0.50), base - r_base * rng.uniform(2.0, 2.4), r_s)
        pen_dot(Wc * rng.uniform(0.38, 0.52), base - r_s * rng.uniform(0.0, 0.4), r_s)
    elif ch == "！":
        wv = max(2, int(fs * S * 0.075))
        # 竖笔：略弯、上细下粗
        y_top = base - r_base * rng.uniform(4.8, 5.6)
        y_bot = base - r_base * rng.uniform(1.4, 1.9)
        xb = Wc * rng.uniform(0.40, 0.50)
        d.line([xb + rng.gauss(0, 1.5), y_top, xb, y_bot], fill=245, width=wv)
        pen_dot(xb, base - r_base * rng.uniform(0.1, 0.4), r_base * 0.85)
    else:
        return None

    # 纸面颗粒：让墨迹里有飞白/不均匀（关键，规整就假）
    arr0 = np.array(layer).astype(np.float32) / 255.0
    hn, wn = arr0.shape
    grain = np.random.default_rng(rng.randint(0, 999999)).normal(0, 1, (hn // 2 + 1, wn // 2 + 1))
    grain = np.array(Image.fromarray(((grain * 55) + 128).clip(0, 255).astype(np.uint8))
                     .resize((wn, hn), Image.BICUBIC)).astype(np.float32)
    grain = (grain - 128) / 128.0
    fine = np.random.default_rng(rng.randint(0, 999999)).normal(0, 1, (hn, wn)).astype(np.float32)
    arr0 = arr0 * (1.0 + grain * 0.42 + fine * 0.10)
    layer = Image.fromarray((np.clip(arr0, 0, 1) * 255).astype(np.uint8))

    # 缩回目标字号 + 手写抖动
    img = layer.resize((max(2, W), max(2, H)), Image.LANCZOS)
    a = np.array(img).astype(np.float32) / 255.0
    # 轻微旋转，跟手写一致
    if abs(rng.gauss(0, 2.0)) > 0.4:
        a = np.array(Image.fromarray((a * 255).astype(np.uint8))
                     .rotate(rng.gauss(0, 2.5), resample=Image.BICUBIC, expand=False, fillcolor=0)
                     ).astype(np.float32) / 255.0
    # 墨色浓淡（跟正文同一套逻辑）
    a = a * rng.uniform(0.88, 1.0)

    base_rgb = np.array(ink_rgb, np.float32)
    rgba = np.zeros((*a.shape, 4), np.float32)
    for i in range(3):
        rgba[:, :, i] = base_rgb[i]
    rgba[:, :, 3] = np.clip(a * 255 * 1.18, 0, 255)
    out = Image.fromarray(rgba.astype(np.uint8), "RGBA")

    # 裁到墨迹
    yy, xx = np.where(a > 0.05)
    if len(yy):
        out = out.crop((max(0, xx.min() - 1), max(0, yy.min() - 1),
                        min(out.width, xx.max() + 2), min(out.height, yy.max() + 2)))
    return out


def measure_text(font_path, text, fs, tight=0.94):
    """按 render_text 的真实字距规则量一行像素宽度。

    render_text 里逐字推进量：普通字 fs*tight，标点 fs*0.42，空格 fs*0.45，
    再加上首尾各 fs*0.35 的留白。这里用同一套规则累加，误差不超过一个字宽。
    """
    adv = 0.0
    for ch in text:
        if ch == " ":
            adv += fs * 0.45
        elif ch in "，。、；：！？":
            adv += fs * 0.45
        else:
            adv += fs * tight
    return adv + fs * 0.70


def _draw_tie(canvas, p0, p1, rng, ink_rgb, fs):
    """画一笔牵丝：细、淡、带弧度。"""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0 = p0
    x1, y1 = p1
    if x1 <= x0 or x1 - x0 > fs * 1.4:
        return
    mid = ((x0 + x1) / 2, (y0 + y1) / 2 + rng.uniform(-fs * 0.10, fs * 0.10))
    wpx = max(1, int(fs * rng.uniform(0.022, 0.042)))
    col = tuple(int(c) for c in ink_rgb) + (int(rng.uniform(150, 205)),)
    pts = []
    for i in range(13):
        t = i / 12.0
        xx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mid[0] + t ** 2 * x1
        yy = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * mid[1] + t ** 2 * y1
        pts.append((xx, yy))
    d.line(pts, fill=col, width=wpx, joint="curve")
    layer = layer.filter(ImageFilter.GaussianBlur(0.4))
    canvas.alpha_composite(layer)


if __name__ == "__main__":
    out = os.path.join(HERE, "_v4_测试.png")
    rows = []
    for name in ("悠哉", "猫啃", "小赖"):
        fp = FONT_PATHS.get(name)
        if not fp or not os.path.exists(fp):
            continue
        bg, _ = render_text(fp, "细胞分裂时染色体先复制再平分", 54, seed=11)
        rows.append((name, bg))
    W = max(b.width for _, b in rows)
    H = sum(b.height + 34 for _, b in rows)
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    y = 0
    for name, b in rows:
        d.text((6, y + 5), name, fill=(150, 150, 150))
        sheet.paste(b, (0, y + 24))
        y += b.height + 34
    sheet.save(out)
    print("saved", out, sheet.size)
