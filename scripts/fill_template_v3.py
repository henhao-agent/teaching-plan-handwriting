# -*- coding: utf-8 -*-
"""整页填充 V3 —— 用 V4 笔画级引擎 + 红色二次备课批注

相对 V2 的变化：
1. 渲染引擎换成 handwrite_v4（笔画变宽/出锋/牵丝/墨色渐变），字体默认小赖手写
2. 新增二次备课：在右侧「二次备课」栏用**红笔**写批注（真人听课/复备时的红笔记录）
3. 红笔有自己的墨色与质感（偏细、偏淡、偶有连笔），与正文的黑笔区分

二次备课内容不是装饰，得是老师真会写的：教学环节旁记重点/提醒/学生易错。
"""
import os
import re
import sys
import json
import argparse
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import handwrite_v4 as HW
import hand_diagram as HD

TPL_DIR = os.path.join(ROOT, "templates")
OUT_DEFAULT = os.path.join(ROOT, "output")
DPI = 200

# 字体：小赖最像成年人日常手写（实测排序：小赖 > 悠哉 > 猫啃 > 文楷）
def _find_font():
    """定位手写字体（用户自己的定制字体）。

    查找顺序：
      1. 环境变量 HWSIM_FONT 指定的路径
      2. 仓库根目录 assets/ 下任意 .ttf/.otf（用户把自己的字体丢这里就行）
      3. 仓库根目录 font.ttf
    都找不到就报错并提示怎么放。
    """
    env = os.environ.get("HWSIM_FONT")
    if env and os.path.exists(env):
        return env
    assets = os.path.join(ROOT, "assets")
    if os.path.isdir(assets):
        fonts = sorted(f for f in os.listdir(assets)
                       if f.lower().endswith((".ttf", ".otf", ".ttc")))
        if fonts:
            return os.path.join(assets, fonts[0])
    plain = os.path.join(ROOT, "font.ttf")
    if os.path.exists(plain):
        return plain
    raise SystemExit(
        "\n[错误] 没找到手写字体。请把你的字体文件放到：\n"
        "    %s\n"
        "或者用环境变量指定：HWSIM_FONT=/path/to/your-font.ttf\n" % assets)


FONT_DEFAULT = _find_font()
FONT_RED = FONT_DEFAULT      # 红笔批注用同一款字体（保持笔迹一致）

INK_BLACK = (26, 28, 36)

FS_STEPS_CAP = 34   # 教学环节字号上限，红字也对齐到这个值

# ---- 读取固化版面框架（改内容不改框架）----
_FRAME = None
def _load_frame():
    global _FRAME
    if _FRAME is None:
        import os as _os
        fp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "版面框架_固化.json")
        _FRAME = json.load(open(fp, encoding="utf-8")) if _os.path.exists(fp) else {}
    return _FRAME

INK_RED = (176, 32, 40)

P1 = {
    "topic":      (389, 344, 837, 431),
    "type":       (941, 344, 1134, 431),
    "duration":   (1271, 344, 1425, 431),
    "objectives": (389, 431, 1425, 665),
    "keypoints":  (389, 665, 1425, 887),
    "methods":    (389, 887, 1170, 970),
    "tools":      (1271, 887, 1425, 970),
    "steps":      (246, 1060, 389, 2025),
    "process":    (389, 1060, 1171, 2025),
}
P2 = {
    "steps2":     (230, 177, 380, 1328),
    "process2":   (380, 177, 1169, 1328),
    "homework":   (230, 1397, 833, 1818),
    "blackboard": (833, 1397, 1424, 1818),
    "reflection": (380, 1818, 1424, 2028),
}
# 二次备课栏（右栏，红色批注写这里）
BEIFEN1 = (1171, 1060, 1425, 2025)
BEIFEN2 = (1169, 177, 1424, 1328)
# 第2页除板书外的其余栏（板书单独用更大字号绘制）
P2_NOHW = {k: v for k, v in P2.items() if k != "blackboard"}

P1_LINES = {
    # 下划线实测（y=237~239）：年级 654-730 / 学科 844-906 / 单元 1021-1082 / 课时 待定
    "grade":    (516, 196, 578, 236),
    "subject":  (654, 196, 730, 236),
    "unit":     (844, 196, 906, 236),
    "lesson":   (1021, 196, 1082, 236),
    "author":   (382, 278, 551, 319),
    "prepdate": (794, 278, 994, 319),
    "polish":   (1207, 278, 1388, 319),
}

PUNCT = set("，。、；：！？”’）》…")
PUNCT_HEAD = set("，。、；：！？”’）》…")
PUNCT_TAIL = set("“‘《（【")   # 行尾不能留这些开引号/开括号
INK_RATIO = 1.08
LINE_RATIO = 1.12
PROCESS_LH = 1.26   # 教学过程行距（用户要求行间距更大）
UNI_FS_CAP = 43     # 全表字号上限（用户指定"再大2个号"= 43）
PROCESS_KEYS = ("process", "process2")
# 矮而窄的单行栏：字号放大后必须整句一行放下，否则折行会把字挤成两截
THIN_KEYS = ("tools", "duration", "type", "topic", "methods")
MIN_SHRINK = 0.90   # 字号最多只缩 10%，宁可报超量也不缩小字


# ---------------------------------------------------------------- 量算
_probe = {}


def char_w(ch, fs_ref=24):
    key = ch
    if key in _probe:
        return _probe[key]
    b = HW.glyph_mask(FONT_DEFAULT, ch, fs_ref)
    w = 0 if b is None else b.shape[1] / HW.SS
    _probe[key] = w
    return w


def wrap_text(text, box_w, fs, font=None, indent=0):
    """按真实渲染像素宽度折行（不再用估算比例）。

    旧版用 0.94*fs 估算字宽、标点估 0.42*fs，估算偏大导致每行提前折断、
    右边留出半截空白（用户反馈"写半截、换行不对"）。
    现在直接量每一行渲染后的真实像素宽，尽量把行填满，只保留 2px 余量。
    """
    font = font or FONT_DEFAULT
    lines = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        # 标题行不缩进；正文首行缩进
        _is_head = bool(re.match(r"^[一二三四五六七八九十]+[、.．]|^\d+[、.．]|^（[一二三四五六七八九十]+）", para))
        cur = ""
        line_w = box_w if _is_head else (box_w - indent)
        first_line = True
        for ch in para:
            trial = cur + ch
            w = HW.measure_text(font, trial, fs, tight=0.94)
            if cur and w > line_w + 1:
                # 标点禁则：行首不能放这些标点。只在仅超出 1 字宽内才硬塞（避免把整词挤到下一行）
                if ch in PUNCT_HEAD and (w - line_w) <= fs * 0.9:
                    cur = trial
                    continue
                # 行尾不能是开括号/开引号，把它挪到下一行
                while cur and cur[-1] in PUNCT_TAIL:
                    ch = cur[-1] + ch
                    cur = cur[:-1]
                lines.append(cur)
                cur = ch
                if first_line:
                    first_line = False
                    line_w = box_w
            else:
                cur = trial
        if cur:
            lines.append(cur)
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def render_block(text, box_w, box_h, target_ink_h, font=FONT_DEFAULT,
                 ink_rgb=INK_BLACK, pad=8, seed=0, tight=0.94, fs_lock=None,
                 lh_ratio=None, indent=False):
    """把一段文字渲染成贴合 box 的手写块（V4 引擎）。

    fs_lock: 锁定字号（用户要求全表字号统一时用）。给了就完全不缩放，
    只负责折行排布；内容实在放不下才在外部提示，不做小字妥协。
    """
    avail_w = int((box_w - pad * 2 - 6) * 0.995)
    avail_h = box_h - pad * 2 - 12   # 底部多留 12px，末行不贴格线
    min_fs = max(16, int(target_ink_h / INK_RATIO * MIN_SHRINK))

    # 锁定字号模式：直接按锁定字号折行排布，不做任何缩放
    if fs_lock:
        fs = int(fs_lock)
        lines = wrap_text(text, avail_w, fs, font=font,
                          indent=int(fs * 2 * 0.99) if indent else 0)
        n_ink = sum(1 for l in lines if l)
        need = n_ink * fs * 1.15
        lh_l = fs * LINE_RATIO
        eff = n_ink
        squeeze = 1.0
        if eff > 0:
            if lh_ratio:
                # 指定行距（教学过程放宽用）：行距固定取大值，靠内容量保证放得下
                lh_l = fs * lh_ratio
                if eff * lh_l > avail_h:
                    print("  !! 行距%.2f 时 fs=%d %d行放不下(需%d>有%d)，需删内容"
                          % (lh_ratio, fs, eff, int(eff * lh_l), int(avail_h)))
            else:
                # 行距贴合格子：真人手写也会写紧。先按 1.04 下限，超出 6% 内按格高均分
                lh_l = max(fs * 1.04, min(fs * LINE_RATIO, avail_h / eff))
                if eff * fs * 1.04 > avail_h and eff * fs * 0.98 <= avail_h:
                    lh_l = avail_h / eff          # 刚好铺满，不叠字
            if eff * fs * 0.98 > avail_h:
                print("  !! 锁定字号%d 放不下（需%d>格%d），删%d字"
                      % (fs, int(eff * fs * 1.04), int(avail_h),
                         int((eff * fs * 1.04 - avail_h) / fs) + 1))
        squeeze = 1.0
        canvas = Image.new("RGBA", (max(8, avail_w), max(8, avail_h)), (0, 0, 0, 0))
        yy = 0.0
        rngl = random.Random(seed)
        indent_px = int(fs * 2 * 0.99) if indent else 0   # 首行缩进两个字的宽度
        # 标记每一行是否段首；只有「正文段」首行缩进，标题段（一、/二、/（5分钟）等）不缩
        _is_heading = lambda s: bool(re.match(
            r"^[一二三四五六七八九十]+[、.．]|^\d+[、.．]|^（[一二三四五六七八九十]+）", s))
        _para_first = []
        for _p in text.split("\n"):
            _p = _p.strip()
            if not _p:
                _para_first.append(False)
                continue
            _n = len(wrap_text(_p, avail_w, fs, font=font,
                               indent=int(fs * 2 * 0.99) if indent else 0))
            _ind = False if _is_heading(_p) else True   # 标题行不缩进
            _para_first += [_ind] + [False] * max(0, _n - 1)
        for li_idx, line in enumerate(lines):
            if not line:
                yy += lh_l * 0.62
                continue
            _, tile_l = HW.render_text(font, line, fs, seed=rngl.randint(0, 99999),
                                       tight=tight, ink_rgb=ink_rgb)
            if tile_l.width > canvas.width:
                sc = canvas.width / tile_l.width
                tile_l = tile_l.resize((max(4, int(tile_l.width * sc)),
                                        max(4, int(tile_l.height * sc))), Image.LANCZOS)
            _x = indent_px if (indent_px and _para_first[li_idx]) else 0
            canvas.alpha_composite(tile_l, (int(_x), int(yy)))
            yy += lh_l
        # 行距被压到 1.12 下限时，字块底部紧贴格线（看着满），留 6px 呼吸位
        # 自检：实际墨迹比预算高就压行距到刚好（宁可稍紧，也不让末行出格）
        _arr = np.array(canvas)
        _ys_now = np.where(_arr[:, :, 3] > 20)[0]
        if len(_ys_now) and _ys_now.max() > avail_h - 2 and eff > 1:
            _scale_lh = (avail_h - 6) / max(1, (_ys_now.max() + 1))
            if _scale_lh < 0.98:
                # 重建：行距整体乘系数
                lh_l = max(fs * 0.96, lh_l * _scale_lh)
                canvas = Image.new("RGBA", (max(8, avail_w), max(8, avail_h)), (0, 0, 0, 0))
                yy = 0.0
                rngl = random.Random(seed)
                for li_idx, line in enumerate(lines):
                    if not line:
                        yy += lh_l * 0.62
                        continue
                    _, tile_l = HW.render_text(font, line, fs, seed=rngl.randint(0, 99999),
                                               tight=tight, ink_rgb=ink_rgb)
                    if tile_l.width > canvas.width:
                        sc = canvas.width / tile_l.width
                        tile_l = tile_l.resize((max(4, int(tile_l.width * sc)),
                                                max(4, int(tile_l.height * sc))), Image.LANCZOS)
                    _x = indent_px if (indent_px and _para_first[li_idx]) else 0
                    canvas.alpha_composite(tile_l, (int(_x), int(yy)))
                    yy += lh_l
        if eff and eff * fs * 1.04 >= avail_h - 2:
            arr0 = np.array(canvas)
            _ys = np.where(arr0[:, :, 3] > 20)[0]
            if len(_ys):
                canvas = canvas.crop((0, 0, canvas.width, min(canvas.height, int(_ys.max()) + 6)))
        return canvas, fs, n_ink

    # 窄栏（如教具栏 154×83）：内容短但格子窄时，先尝试"整段一行放下"，
    # 避免被拆成两行 + 每行只排半截（用户反馈"内容是半截"）。
    plain = text.replace("\n", "")
    if len(plain) <= 14 and box_h < 140:
        one_w = HW.measure_text(FONT_DEFAULT, plain, 1, tight=0.94)  # 每 px 字号的宽度
        if one_w > 0:
            fit_fs = int(avail_w / one_w)
            if fit_fs >= max(22, int(target_ink_h / INK_RATIO * 0.55)):
                _, tile = HW.render_text(FONT_DEFAULT, plain,
                                         min(fit_fs, int(target_ink_h / INK_RATIO)),
                                         seed=seed, tight=0.94, ink_rgb=ink_rgb)
                # 强制贴合格子宽度，绝不溢出到格线外
                if tile.width > avail_w:
                    sc = avail_w / tile.width
                    tile = tile.resize((avail_w, max(4, int(tile.height * sc))), Image.LANCZOS)
                if tile.height > avail_h:
                    sc2 = avail_h / tile.height
                    tile = tile.resize((max(4, int(tile.width * sc2)), avail_h), Image.LANCZOS)
                return tile.crop((0, 0, tile.width, tile.height)), min(fit_fs, int(target_ink_h / INK_RATIO)), 1

    # 选字号：先按行数判断，再按"字块真实需要的高度"复核。
    # 关键：行距不固定用 LINE_RATIO，而是让字块正好填满格子——
    # 只要 (行数) 能放进格子，就用 fs 不变、行距自适应；
    # 行数本身就放不下时才降字号。这样既不裁字，字又够大。
    best = None
    # 先按宽松比例试；放不下就继续往小缩，宁可字小一点也绝不裁字
    for mul in (1.00, 0.96, 0.93, 0.90, 0.87, 0.84, 0.80, 0.76, 0.72, 0.68, 0.64, 0.60):
        fs = int(target_ink_h / INK_RATIO * mul)
        if fs < 14:
            break
        lines = wrap_text(text, avail_w, fs)
        n_ink = sum(1 for l in lines if l)
        n_blank = len(lines) - n_ink
        # 最小可接受行距 = 1.15*fs（再小会叠字）；空白行按 0.62 计
        need_min = (n_ink * fs * 1.15) + (n_blank * fs * 1.15 * 0.62)
        if need_min <= avail_h:
            best = (fs, lines)
            break
    if best is None:
        # 缩到最小仍放不下：按可用高度反推最大可行字号（二分），绝不裁字
        lo, hi = 12, int(target_ink_h / INK_RATIO)
        best_fs = 12
        while lo <= hi:
            mid = (lo + hi) // 2
            _l = wrap_text(text, avail_w, mid)
            _ni = sum(1 for x in _l if x)
            if _ni and _ni * mid * 1.15 <= avail_h:
                best_fs = mid; lo = mid + 1
            else:
                hi = mid - 1
        fs = best_fs
        lines = wrap_text(text, avail_w, fs)
        best = (fs, lines)
        print("  !! 内容超量 %d字 → 最小字号%d（需人工删减）"
              % (len(text.replace("\n", "")), fs))

    fs, lines = best
    n_ink2 = sum(1 for l in lines if l)
    n_blank2 = len(lines) - n_ink2
    eff2 = n_ink2 + n_blank2 * 0.62
    # 行距：在 [1.02*fs, 1.30*fs] 之间取能让字块填满格子的最大值
    lh = fs * (lh_ratio or LINE_RATIO)
    if eff2 > 0 and not lh_ratio:
        fit_lh = avail_h / eff2
        lh = max(fs * 1.15, min(fs * LINE_RATIO, fit_lh))
    canvas = Image.new("RGBA", (max(8, avail_w), max(8, avail_h)), (0, 0, 0, 0))
    y = 0.0
    rng = random.Random(seed)
    for li, line in enumerate(lines):
        if not line:
            y += lh * 0.62
            continue
        _, tile = HW.render_text(font, line, fs, seed=rng.randint(0, 99999),
                                 tight=tight, ink_rgb=ink_rgb)
        if tile.width > canvas.width:
            sc = canvas.width / tile.width
            tile = tile.resize((max(4, int(tile.width * sc)), max(4, int(tile.height * sc))),
                               Image.LANCZOS)
        canvas.alpha_composite(tile, (0, int(y)))
        y += lh
    return canvas, fs, len([l for l in lines if l])


def fit_header(text, box, kind, font=FONT_DEFAULT, uni_ink=None):
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    # 目标墨高不能超过格子高度（表头窄格只有 41px 高，用 62 会顶出下划线）
    target = min(58 if kind == "title" else 62, max(bh * 0.72, 30))
    if uni_ink:
        target = min(target, uni_ink)
    fs = max(20, int(target / INK_RATIO * 1.10))
    _, t = HW.render_text(font, text, fs, seed=7300 + len(text), tight=0.90)
    if t.width > bw * 1.02:
        sc = (bw * 1.02) / t.width
        t = t.resize((max(4, int(t.width * sc)), max(4, int(t.height * sc))), Image.LANCZOS)
    return t


# ---------------------------------------------------------------- 模板
def load_template():
    os.makedirs(TPL_DIR, exist_ok=True)
    paths = [os.path.join(TPL_DIR, "tpl_p%d.png" % i) for i in range(2)]
    if not all(os.path.exists(p) for p in paths):
        # 模板图缺失时，从仓库里的 PDF 现转（放在 templates/ 下任意 pdf）
        import glob as _glob
        src = None
        for cand in (os.path.join(ROOT, "templates", "教学设计模版.pdf"),
                     os.path.join(ROOT, "templates", "template.pdf")):
            if os.path.exists(cand):
                src = cand
                break
        if src is None:
            pdfs = sorted(_glob.glob(os.path.join(ROOT, "templates", "*.pdf")))
            src = pdfs[0] if pdfs else None
        if src is None:
            raise SystemExit(
                "\n[错误] 模板图缺失。请确认这两个文件存在：\n  %s\n  %s\n"
                "或者把模板 PDF 放到 templates/ 目录下（会自动转成 PNG）。\n"
                % (paths[0], paths[1]))
        import fitz
        d = fitz.open(src)
        for k, p in enumerate(d):
            if k < 2:
                p.get_pixmap(dpi=DPI).save(paths[k])
    return [Image.open(p).convert("RGB") for p in paths]


def fill_steps_column(img, key, text, box, seed=0, font=FONT_DEFAULT, uni_fs=None):
    """教学环节栏：竖排列项，字号尽量大，长名允许折成两行（不缩字）。

    用户要求"字大一点"：以前为了不拆行把 fs 压到 23~28，太小。
    现在反向做——先给足字号（32 起），一行放不下就在该项内部折成两行，
    项与项之间仍均匀分布，保证整栏铺满。
    """
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    items = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not items:
        return img

    inner_w = bw - 24
    longest = max(items, key=len)
    # 取"最长一项能单行放下"的最大字号；一行都放不下才降到 26 并折行
    # 保证所有项都能单行放下（折行会让栏目显乱）
    fs = 26
    for cand in (46, 44, 42, 40, 38, 36, 34, 32, 30, 28, 26, 24, 22):
        if all(HW.measure_text(font, it, cand, tight=0.94) <= inner_w for it in items):
            fs = cand
            break
    # 用户要求全表字号统一：环节栏也压到统一字号（栏窄放不下时保持自身能放下的最大值）
    if uni_fs:
        fs = min(fs, int(uni_fs))

    # 渲染：每项内部按真实宽度折行
    blocks = []
    for it in items:
        sub = wrap_text(it, inner_w, fs, font=font)
        tiles = []
        for ln in sub:
            _, t = HW.render_text(font, ln, fs, seed=seed + hash(it) % 9999,
                                  tight=0.94, ink_rgb=INK_BLACK)
            a = np.array(t)
            ys, xs = np.where(a[:, :, 3] > 20)
            if len(ys):
                t = t.crop((0, 0, min(t.width, xs.max() + 4), min(t.height, ys.max() + 4)))
            tiles.append(t)
        blocks.append(tiles)

    total_h = sum(t.height for tk in blocks for t in tk)
    n_gaps = max(1, len(blocks))
    gap = max(6, (bh - total_h - 16) / n_gaps)
    y = y0 + 8
    for tiles in blocks:
        for t in tiles:
            if t.width > inner_w:
                sc = inner_w / t.width
                t = t.resize((inner_w, max(4, int(t.height * sc))), Image.LANCZOS)
            img.paste(t, (x0 + 9, int(y)), t)
            y += t.height + fs * 0.18
        y += gap - fs * 0.18
    print("  %-12s 竖排%d项 fs=%d 高度%d/%d" % (key, len(items), fs, int(y - y0), bh))
    return img


# 短内容的栏：字少，理应摆正中（用户反馈"课时/课型没在最中间"）
CENTER_KEYS = ("topic", "type", "duration", "tools", "methods", "homework",
               "blackboard", "reflection")
# 锁定字号的栏：全表统一用教学过程那个字号
LOCK_KEYS = ("topic", "type", "duration", "objectives", "keypoints",
             "methods", "tools", "process", "steps2", "process2",
             "homework", "reflection", "blackboard")


def fill_page(img, spec, texts, target_ink_h, seed0=100, pad=8, uni_fs=None):
    """uni_fs: 全表统一字号（用户要求所有栏跟教学过程一样大）。"""
    for i, (key, box) in enumerate(spec.items()):
        text = (texts.get(key) or "").strip()
        if not text:
            continue
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        if bw < 20 or bh < 20:
            continue
        # 教学环节栏：竖排列项，每项整块不拆行，垂直均分填满整栏
        if key.startswith("steps"):
            fill_steps_column(img, key, text, box, seed0 + i * 37, uni_fs=uni_fs)
            continue
        # 窄栏（教学环节、教具等）按栏宽自适应：一栏至少能放 3 个字，否则字号减半
        ink = target_ink_h
        if bw < target_ink_h * 4 and key not in ("blackboard", "homework", "tools"):
            ink = min(target_ink_h, bw / 3.2)
        lock = uni_fs if (uni_fs and key in LOCK_KEYS) else None
        pad_use = pad
        # 锁字号但内容放不下时：逐级降 1 号（最多降 3 号）重试，绝不裁字
        if lock and key not in THIN_KEYS:
            _aw0, _ah0 = bw - pad * 2 - 6, bh - pad * 2 - 12
            for _try in range(16):
                _ln = wrap_text(text, int(_aw0 * 0.995), int(lock))
                _nk = sum(1 for l in _ln if l)
                if _nk * int(lock) * 1.04 <= _ah0:
                    break
                lock = int(lock) - 1
                if lock <= 18:
                    break
        # 矮窄单行栏（教具/课时/课型等）：强制单行，按格宽反算能放的最大字号
        if lock and key in THIN_KEYS:
            inner_w2, inner_h2 = bw - 14, bh - 10
            flat = text.replace("\n", "")
            # 教法学法有两行内容（教法/学法），按原文分段，取每段单行放得下的最大字号
            segs = [s.strip() for s in text.split("\n") if s.strip()]
            seg_w = max((HW.measure_text(FONT_DEFAULT, s, 1, tight=0.94) for s in segs), default=1)
            fit_seg = int(inner_w2 / max(1e-6, seg_w))
            # 段数 × 字号 × 行距 要装进格高
            _nseg = max(1, len(segs))
            fit_h = int((bh - 12) / (_nseg * 1.10))   # 段间行距可贴格（手写写紧）
            lock = max(18, min(int(lock), fit_seg, fit_h))
            pad_use = 4
        if lock and key in THIN_KEYS:
            # 矮栏专用：每段强制单行，宽度超出就横缩（不折行、不裁字）
            segs = [s.strip() for s in text.split("\n") if s.strip()]
            fs_l = int(lock)
            rng_t = random.Random(seed0 + i * 37)
            tiles_t = []
            for s in segs:
                _, tk = HW.render_text(FONT_DEFAULT, s, fs_l, seed=rng_t.randint(0, 99999),
                                       tight=0.94, ink_rgb=INK_BLACK)
                a_t = np.array(tk)
                yy_t, xx_t = np.where(a_t[:, :, 3] > 20)
                if len(yy_t):
                    tk = tk.crop((0, 0, min(tk.width, xx_t.max() + 4), min(tk.height, yy_t.max() + 4)))
                max_w = bw - 26
                if tk.width > max_w:
                    s2 = max_w / tk.width
                    tk = tk.resize((max_w, max(4, int(tk.height * s2))), Image.LANCZOS)
                tiles_t.append(tk)
            gap_t = max(0, int(fs_l * 0.05))
            tot_h = sum(t.height for t in tiles_t) + gap_t * (len(tiles_t) - 1)
            _cw = max(tk.width for tk in tiles_t)
            canvas_t = Image.new("RGBA", (max(8, _cw), max(8, tot_h)), (0, 0, 0, 0))
            yt = 0
            for tk in tiles_t:
                canvas_t.alpha_composite(tk, (max(0, (_cw - tk.width) // 2), yt))
                yt += tk.height + gap_t
            tile, fs, nlines = canvas_t, fs_l, len(tiles_t)
        else:
            tile, fs, nlines = render_block(text, bw, bh, ink, seed=seed0 + i * 37,
                                            fs_lock=lock, pad=pad_use,
                                            lh_ratio=PROCESS_LH if key in PROCESS_KEYS else None,
                                            indent=key in PROCESS_KEYS)
        # 真实墨迹高度复核：估算可能偏低，溢出就降档重排，绝不裁字（锁字号时不缩）
        if not lock:
            for _retry in range(6):
                arr = np.array(tile)
                ys, xs = np.where(arr[:, :, 3] > 20)
                if not len(ys):
                    break
                if ys.max() + 1 <= bh - pad * 2 and xs.max() + 1 <= bw - pad * 2:
                    break
                ink *= 0.93
                if ink < 16:
                    break
                tile, fs, nlines = render_block(text, bw, bh, ink, seed=seed0 + i * 37)
        arr = np.array(tile)
        ys, xs = np.where(arr[:, :, 3] > 20)
        if len(ys):
            tile = tile.crop((0, 0, min(tile.width, xs.max() + 6), min(tile.height, ys.max() + 6)))
        # 超出格子：整体等比缩进格子（宁可字略小，也绝不裁字、不叠字）
        if (key not in THIN_KEYS) and (tile.height > bh - pad * 2 or tile.width > bw - pad * 2):
            sc = min((bw - pad * 2) / tile.width, (bh - pad * 2) / tile.height)
            if sc < 1.0:
                tile = tile.resize((max(4, int(tile.width * sc)), max(4, int(tile.height * sc))),
                                   Image.LANCZOS)
                print("  ~ %s 内容超出，整体缩放至%.0f%%塞进格子" % (key, sc * 100))
        # ---- 摆位：短内容整块居中（水平+垂直），长段落仍左上起笔 ----
        short = (len(text.replace("\n", "")) <= 16) or (nlines <= 1)
        if key in THIN_KEYS:
            # 教法学法左对齐；其余矮栏仍居中
            if key == "methods":
                px = x0 + 10
            else:
                px = x0 + (bw - tile.width) // 2
            py = y0 + max(1, (bh - tile.height) // 2)
        elif key in CENTER_KEYS or short:
            px = x0 + (bw - tile.width) // 2
            py = y0 + (bh - tile.height) // 2
        else:
            px = x0 + pad
            py = y0 + pad
        img.paste(tile, (max(0, px), max(0, py)), tile)
        print("  %-12s %3d字 fs=%2d %d行 → %dx%d in %dx%d @(%d,%d)%s" %
              (key, len(text.replace("\n", "")), fs, nlines,
               tile.width, tile.height, bw, bh, px, py,
               " 居中" if (key in CENTER_KEYS or short) else ""))
    return img


def fill_beifen(img, notes, box, seed=0, ink_rgb=INK_RED, fs=34, diagram=None):
    """在二次备课栏用红笔写批注，下半部画手绘示意图。

    notes: list[str]，每条前面自动加① ② ③ 或 — 。
    diagram: None / "mitosis" / "microscope"，画在批注下方的空白处。
    """
    if not notes and not diagram:
        return img
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if diagram:
        # 批注自适应：先量批注实际需要多高，图从下面开始，绝不重叠
        need_h = int(len(notes) * fs * 1.55 + 24)
        note_h = min(int(bh * 0.46), max(need_h, int(bh * 0.22)))
        note_box = (x0, y0, x1, y0 + note_h)
        img = fill_beifen(img, notes, note_box, seed=seed, ink_rgb=ink_rgb, fs=fs)
        dw = bw - 16
        avail = max(160, y1 - (y0 + note_h) - 16)
        dh = int(avail * 0.98)
        dy = y0 + note_h + 8
        try:
            dg = HD.make_diagram(diagram, dw, dh, ink=ink_rgb, seed=seed + 7)
            img.paste(dg, (x0 + 10, dy), dg)
            print("  红笔手绘示意图 %s → %dx%d @(%d,%d)" % (diagram, dw, dh, x0 + 10, dy))
        except Exception as e:
            print("  !! 示意图失败:", e)
        return img
    if not notes:
        return img
    # 逐条渲染：直接调手写引擎，字号就是真字号（不再经 render_block 等比缩小）
    inner_w = bw - 14
    # 自动放大：按最长的批注反算能放下的最大字号，上限 FS_STEPS_CAP（与教学环节对齐）
    longest_note = max(notes, key=len) if notes else ""
    if longest_note:
        probe = longest_note
        cap = FS_STEPS_CAP
        best = fs
        for cand in range(cap, fs - 1, -1):
            if HW.measure_text(FONT_RED, probe, cand, tight=0.90) <= inner_w:
                best = cand
                break
        fs = best
    rng = random.Random(seed)
    y = y0 + 24
    max_h = bh - 34
    drawn = 0
    tiles = []
    for n in notes:
        # 用户要求：不加 ①②③ 和圆点，直接写批注原文
        line = n
        _, t = HW.render_text(FONT_RED, line, fs, seed=rng.randint(0, 99999),
                              tight=0.90, ink_rgb=ink_rgb)
        a = np.array(t)
        ys, xs = np.where(a[:, :, 3] > 20)
        if len(ys):
            t = t.crop((0, 0, min(t.width, xs.max() + 4), min(t.height, ys.max() + 4)))
        if t.width > inner_w:
            sc = inner_w / t.width
            t = t.resize((inner_w, max(4, int(t.height * sc))), Image.LANCZOS)
        if y + t.height > y0 + max_h:
            break
        tiles.append(t)
        y += t.height + fs * 0.30
        drawn += 1
    # 铺满整栏：批注按可用高度均匀分布，下面不留大片空白
    if tiles:
        total = sum(t.height for t in tiles)
        gapn = (max_h - total - 8) / len(tiles)
        gapn = max(fs * 0.28, gapn)
        yy = y0 + 24
        for t in tiles:
            img.paste(t, (x0 + 7, int(yy)), t)
            yy += t.height + gapn
        end_y = int(yy - gapn)
    else:
        end_y = y0 + 8
    print("  红笔二次备课 %d条 fs=%d 写入%d条 高度%d/%d" % (len(notes), fs, drawn, end_y - y0, bh))
    return img


def build(co, out_dir, target_ink_h=65, seed=20261106, font=FONT_DEFAULT):
    os.makedirs(out_dir, exist_ok=True)
    pages = load_template()
    img1 = pages[0].copy()
    img2 = pages[1].copy()

    # ---- 统一字号：以「教学过程」为基准，取"行距放宽后仍放得下"的最大字号 ----
    uni_fs = None
    _proc = (co.get("process") or "").strip()
    if _proc and co.get("uni_font", True):
        _b = P1["process"]
        _, uni_fs, _n = render_block(_proc, _b[2] - _b[0], _b[3] - _b[1],
                                     target_ink_h, seed=seed)
        # 上限锁定：用户指定的字号上限（"再大2个号"），超出就压回来
        uni_fs = min(int(uni_fs), UNI_FS_CAP)
        # 往上顶：行距按 PROCESS_LH 放宽，看能大几号（用户要求字号更大、行距更松）
        _aw = _b[2] - _b[0] - 22
        _ah = _b[3] - _b[1] - 22
        for _cand in range(min(int(uni_fs) + 14, UNI_FS_CAP), int(uni_fs), -1):
            _lines = wrap_text(_proc, _aw, _cand, indent=int(_cand * 2 * 0.99))
            _ni = sum(1 for l in _lines if l)
            if _ni and _ni * _cand * PROCESS_LH <= _ah:
                uni_fs = _cand
                break
        print("  统一字号基准（教学过程）fs=%d，教学过程行距%.2f" % (uni_fs, PROCESS_LH))
    uni_ink = (uni_fs * INK_RATIO) if uni_fs else None

    header = {
        "grade": co.get("grade", ""), "subject": co.get("subject", ""),
        "unit": co.get("unit", ""), "lesson": co.get("lesson", ""),
        "author": co.get("author", ""), "prepdate": co.get("prep_date", ""),
        "polish": co.get("polish_date", ""),
    }
    for key, box in P1_LINES.items():
        text = (header.get(key) or "").strip()
        if not text:
            continue
        kind = "title" if key in ("grade", "subject", "unit", "lesson") else "body"
        t = fit_header(text, box, kind, font, uni_ink=uni_ink)
        x0, y0, x1, y1 = box
        px = x0 + ((x1 - x0) - t.width) // 2
        py = y1 - t.height          # 字底边贴住格子底（下划线）
        img1.paste(t, (max(0, px), max(0, py)), t)
        print("  表头 %-9s %s @(%d,%d) %dx%d" % (key, text, px, py, t.width, t.height))

    img1 = fill_page(img1, P1, {k: co.get(k, "") for k in P1}, target_ink_h,
                     seed0=seed, uni_fs=uni_fs)
    # 板书栏格子小但内容少，单独给更大字号（否则被压成蝇头小字）
    img2 = fill_page(img2, P2_NOHW, {
        "steps2": co.get("steps_col2", ""),
        "process2": co.get("process_cont", ""),
        "homework": co.get("homework", ""),
        "blackboard": "",
        "reflection": co.get("reflection", ""),
    }, target_ink_h, seed0=seed + 500, uni_fs=uni_fs)
    # 板书单独画，字号按内容长度自适应放大
    img2 = fill_page(img2, {"blackboard": P2["blackboard"]},
                     {"blackboard": co.get("blackboard", "")},
                     target_ink_h, seed0=seed + 700, uni_fs=uni_fs)
    print("  [板书] uni_fs=%s" % uni_fs)

    # 红色二次备课批注（支持 beifen1..N 多条，或 beifen1 直接给列表）
    def _notes(key):
        v = co.get(key)
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        out = []
        n = 1
        while True:
            t = co.get("%s%d" % (key, n))
            if t is None:
                break
            if str(t).strip():
                out.append(str(t))
            n += 1
        if not out and isinstance(v, str) and v.strip():
            out = [v]
        return out
    bf1 = _notes("beifen1")
    bf2 = _notes("beifen2") or _notes("beifen2x") or bf1
    img1 = fill_beifen(img1, bf1, BEIFEN1, seed=seed + 900, diagram=co.get("diagram1"))
    img2 = fill_beifen(img2, bf2, BEIFEN2, seed=seed + 950, diagram=co.get("diagram2"))

    outs = []
    for i, im in enumerate([img1, img2], 1):
        f = os.path.join(out_dir, "教学设计_第%d页.png" % i)
        im.save(f, dpi=(DPI, DPI))
        outs.append(f)
    import img2pdf
    pdf = os.path.join(out_dir, "教学设计_手写.pdf")
    with open(pdf, "wb") as f:
        f.write(img2pdf.convert(outs))
    print("PDF:", pdf)
    return pdf, outs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--ink", type=float, default=65)   # 目标墨高px@200dpi；65px≈8.3mm=真人手写
    ap.add_argument("--seed", type=int, default=20261106)
    a = ap.parse_args()
    co = json.load(open(a.json, encoding="utf-8"))
    build(co, a.out, a.ink, a.seed)
