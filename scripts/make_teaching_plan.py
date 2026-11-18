# -*- coding: utf-8 -*-
"""教学设计手写 PDF —— 一键封装（2026-11-17 定版规格）

哥哥的标准：「以后所有教学设计都按这个来写」。本脚本把定版规格封成一条命令：

    python make_teaching_plan.py 内容.json [--out 输出目录] [--desk]

定版规格（全部固化，不需要再调）：
  1. 全表字号统一，基准取「教学过程」，上限 43 号（UNI_FS_CAP）
  2. 教学过程行距 1.26；正文每段首行缩进 2 字，环节标题（一、/二、）顶格不缩
  3. 标点用手写笔点（render_punct），不用字体的印刷标点
  4. 教法学法左对齐；课时/课型/教具居中
  5. 二次备课红字不带 ①②③ / 圆点
  6. 字体：萝卜工坊 40105511.ttf
  7. 绝���裁字、绝不叠字：内容超量先报字数再删内容，不缩字号

用法：
    python make_teaching_plan.py D:/x/动物体结构层次.json
    python make_teaching_plan.py D:/x/动物体结构层次.json --desk 动物体的结构层次_教学设计_手写.pdf

内容 JSON 字段（缺项用空串）：
    grade subject unit lesson author prep_date polish_date
    topic type duration objectives keypoints methods tools
    process process_cont steps_col homework blackboard reflection
    beifen1 beifen2      # 二次备课红字批注（字符串数组）
"""
import os
import sys
import json
import argparse
import subprocess
import shutil
import hashlib
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable              # 用当前解释器，不写死路径
OUT_DEFAULT = os.path.join(ROOT, "output")
DESK = os.path.join(os.path.expanduser("~"), "Desktop")

# 每栏的容量（fs=43 + 教学过程首行缩进下的实测上限，字）
CAPACITY = {
    "process": 266,
    "process_cont": 254,
    "objectives": 99,
    "keypoints": 82,
    "homework": 52,
    "blackboard": 55,
    "reflection": 53,
    "methods": 27,
    "tools": 8,
}


def check_capacity(content):
    """写之前先核字数：超了当早报，别等渲染完几张图才发现要改。"""
    bad = []
    for k, cap in CAPACITY.items():
        if k in content and content[k]:
            n = len(str(content[k]).replace("\n", "").strip())
            if n > cap:
                bad.append((k, n, cap))
    return bad


def run(script, args, cwd=HERE, timeout=1800):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [PY, script] + args
    print("  $", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=cwd, env=env, timeout=timeout)
    return r


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


# 教学过程栏在两页上的实际位置（200dpi，与 fill_template_v3 的 P1/P2 对应）
_PROC_BOX = {0: (389, 1060, 1171, 2025), 1: (380, 177, 1169, 1328)}


def _measure_fill(png_path, page):
    """量教学过程栏里墨迹占格高的比例。

    内容写得太少时这一栏会空一大片，页面上一眼就看出来。
    写作建议：process 235~265 字、process_cont 195~250 字。
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    box = _PROC_BOX.get(page)
    if not box:
        return None
    a = np.array(Image.open(png_path).convert("L"))
    x0, y0, x1, y1 = box
    inner = a[y0 + 8:y1 - 8, x0 + 8:x1 - 8]
    dark = inner < 110
    rows = np.where(dark.sum(axis=1) > 2)[0]
    if len(rows) == 0:
        return 0.0
    return float(rows.max() - rows.min()) / inner.shape[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content", help="内容 JSON 路径")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--desk", default=None,
                    help="交付到桌面时用的文件名（如 动物体的结构层次_教学设计_手写.pdf）")
    a = ap.parse_args()

    cpath = os.path.abspath(a.content)
    content = json.load(open(cpath, encoding="utf-8"))
    outdir = a.out or os.path.join(OUT_DEFAULT,
                                   os.path.splitext(os.path.basename(cpath))[0])
    os.makedirs(outdir, exist_ok=True)

    print("[1/4] 核对内容容量 …")
    bad = check_capacity(content)
    if bad:
        print("  !! 下列栏目超出定版容量，请先精简（不缩字号是定规）：")
        for k, n, cap in bad:
            print("     %-12s %3d 字 / 上限 %3d → 需删 %d 字" % (k, n, cap, n - cap))
        print("  （继续渲染会被裁字，已中止）")
        return 2
    print("  OK 全部在容量内")

    print("[2/4] 渲染手写 PDF …")
    # outdir 必须是绝对路径：子进程 cwd 是 scripts/，相对路径会写歪
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    r = run("fill_template_v3.py", [cpath, "--out", outdir])
    if r.returncode != 0:
        print("  渲染失败：")
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        return 3
    # 打印关键行（字号 / 报警）
    for ln in r.stdout.splitlines():
        if any(k in ln for k in ("fs=", "!!", "~ ", "PDF:")):
            print("   ", ln.strip())

    pdf = os.path.join(outdir, "教学设计_手写.pdf")
    if not os.path.exists(pdf):
        print("  !! 没有生成 PDF，检查上面的输出")
        return 4
    print("  产物:", pdf)

    print("[3/4] 自检（尺寸/页数）…")
    try:
        import fitz
        d = fitz.open(pdf)
        print("  %d 页 · %s" % (d.page_count,
                                "x".join("%.0f" % v for v in d[0].rect[2:])))
        if d.page_count != 2:
            print("  !! 教学设计必须是两页（定规），当前 %d 页" % d.page_count)
        d.close()

        # 填充率自检：教学过程两栏写得太空，页面上会留一大片白，一眼看出偷工
        for pno, png in ((0, "第1页"), (1, "第2页")):
            png_path = os.path.join(outdir, "教学设计_%s.png" % png)
            if not os.path.exists(png_path):
                continue
            fill = _measure_fill(png_path, pno)
            if fill is None:
                continue
            flag = "" if fill >= (0.90 if pno == 0 else 0.72) else "  ← 偏空，建议补内容"
            print("  %s填充率 %.0f%%%s" % (png, fill * 100, flag))
    except Exception as e:
        print("  (跳过 fitz 自检:", e, ")")

    print("[4/4] 交付 …")
    if a.desk:
        dst = os.path.join(DESK, a.desk)
        try:
            shutil.copy(pdf, dst)
        except PermissionError:
            print("  桌面文件被占用，尝试按窗口标题关掉阅读器 …")
            _kill_holder(a.desk)
            time.sleep(2)
            shutil.copy(pdf, dst)
        ok = md5(pdf) == md5(dst)
        print("  桌面:", dst)
        print("  MD5 一致:", ok, "| 时间:", time.strftime("%H:%M:%S"))
        if not ok:
            return 5
    else:
        print("  未指定 --desk，只留在:", pdf)

    pngs = [os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".png")]
    print("\n验收图（逐页目视，重点看：末行是否完整 / 缩进 / 笔点）：")
    for p in sorted(pngs):
        print("  ", p)
    return 0


def _kill_holder(fname):
    """只按窗口标题关掉打开这份 PDF 的进程，不盲杀 WPS。"""
    code = (
        "import win32gui, win32process\n"
        "out=[]\n"
        "def cb(h,o):\n"
        "    if win32gui.IsWindowVisible(h):\n"
        "        t=win32gui.GetWindowText(h)\n"
        "        if t.strip():\n"
        "            _,pid=win32process.GetWindowThreadProcessId(h); o.append((pid,t))\n"
        "win32gui.EnumWindows(cb,out)\n"
        "for pid,t in out:\n"
        "    if %r in t: print(pid)\n" % os.path.splitext(fname)[0]
    )
    tmp = os.path.join(os.environ.get("TEMP", "."), "_kill_holder.py")
    open(tmp, "w", encoding="utf-8").write(code)
    r = subprocess.run([PY, tmp], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    for pid in r.stdout.split():
        if pid.strip().isdigit():
            subprocess.run(["taskkill", "/PID", pid.strip(), "/F"],
                           capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
