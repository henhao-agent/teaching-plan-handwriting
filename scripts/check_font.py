# -*- coding: utf-8 -*-
"""字体覆盖率检查 —— 生成前先确认你的字体写得出这份教案。

用法：
    python scripts/check_font.py my_lesson.json
    python scripts/check_font.py            # 检查 examples/ 里的模板

为什么必须先跑这一步：
    手写字体（尤其是自己定制的）经常缺字。缺字时 PIL 会静默用系统字体兜底，
    你看预览会以为是自己的字，实际上混进了印刷体；或者直接渲染成空方框。
    先查一遍，缺字就回萝卜工坊补字，别等出了 PDF 才发现。
"""
import os
import sys
import json
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def find_font():
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
    return None


def collect_text(obj):
    """把 JSON 里所有字符串抽出来（含数组元素）。"""
    out = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, (list, tuple)):
        for it in obj:
            out.extend(collect_text(it))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(collect_text(v))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        jpath = os.path.abspath(args[0])
    else:
        cands = glob.glob(os.path.join(ROOT, "examples", "*.json"))
        if not cands:
            print("没找到要检查的 JSON。用法：python scripts/check_font.py 内容.json")
            return 2
        jpath = cands[0]
        print("（未指定文件，检查示例：%s）" % os.path.basename(jpath))

    if not os.path.exists(jpath):
        print("文件不存在：", jpath)
        return 2

    font = find_font()
    if not font:
        print("\n[错误] 没找到字体。请把字体文件放到：")
        print("    %s" % os.path.join(ROOT, "assets"))
        print("或设置环境变量：HWSIM_FONT=/path/to/your-font.ttf\n")
        return 2

    print("字体：", font)
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        print("\n需要 fontTools 来读字体表：pip install fonttools")
        return 2

    f = TTFont(font)
    cmap = set()
    for t in f["cmap"].tables:
        cmap |= set(t.cmap.keys())
    f.close()

    data = json.load(open(jpath, encoding="utf-8"))
    text = "".join(collect_text(data))
    need = {c for c in text if "\u4e00" <= c <= "\u9fff"}

    miss = sorted(c for c in need if ord(c) not in cmap)
    hit = len(need) - len(miss)
    pct = hit / len(need) * 100 if need else 100.0

    print("这份内容用到 %d 个不同汉字" % len(need))
    print("覆盖 %d 个，覆盖率 %.1f%%" % (hit, pct))

    if not miss:
        print("\n✓ 字体完全覆盖，可以开始生成。")
        return 0

    print("\n✗ 缺 %d 个字：" % len(miss))
    print("   " + "".join(miss))
    print("\n这些字渲染出来会是方框，或悄悄退回系统印刷体。")
    print("处理办法：")
    print("  1. 回萝卜工坊补写这些字，重新下载字体（推荐，笔迹一致）")
    print("  2. 把这几个字换成同义字（如「细胞」→「胞体」不合适时就用方案1）")
    print("  3. 换一款覆盖更全的手写字体")
    return 1


if __name__ == "__main__":
    sys.exit(main())
