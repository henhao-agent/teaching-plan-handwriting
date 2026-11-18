# -*- coding: utf-8 -*-
"""批量生成：把一个目录里所有 .json 逐节做成手写教学设计。

用法：
    python scripts/batch_plans.py ./my_contents/
    python scripts/batch_plans.py ./my_contents/ -f     # 强制重跑已存在的

每节约 70~100 秒。8 节约 10~13 分钟。
单独跑某一个节时用 make_teaching_plan.py 更快。
"""
import os
import sys
import json
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "-f" in sys.argv or "--force" in sys.argv
    if not args:
        print("用法：python scripts/batch_plans.py <内容目录> [-f]")
        return 2

    src = os.path.abspath(args[0])
    if not os.path.isdir(src):
        print("不是目录：", src)
        return 2

    out_root = os.path.join(ROOT, "output")
    files = sorted(f for f in os.listdir(src) if f.endswith(".json"))
    if not files:
        print("目录里没有 .json：", src)
        return 2

    print("共 %d 节，开始批量生成" % len(files), flush=True)
    summary = []
    t_all = time.time()

    for i, fname in enumerate(files, 1):
        name = fname[:-5]
        outdir = os.path.join(out_root, name)
        pdf = os.path.join(outdir, "教学设计_手写.pdf")
        if os.path.exists(pdf) and not force:
            print("[%d/%d] %-30s 已存在，跳过（-f 可强制重跑）" % (i, len(files), name), flush=True)
            summary.append((name, "skip"))
            continue

        t0 = time.time()
        r = subprocess.run(
            [PY, os.path.join(HERE, "make_teaching_plan.py"),
             os.path.join(src, fname), "--out", outdir],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=ROOT, timeout=1800)
        ok = (r.returncode == 0) and os.path.exists(pdf)
        dt = time.time() - t0
        print("[%d/%d] %-30s %s %.0fs" % (i, len(files), name, "OK" if ok else "失败", dt), flush=True)
        if not ok:
            print("  stdout:", r.stdout[-900:], flush=True)
            print("  stderr:", r.stderr[-400:], flush=True)
        summary.append((name, "OK" if ok else "FAIL"))

    print("\n===== 汇总（用时 %.0f 秒）=====" % (time.time() - t_all), flush=True)
    for name, st in summary:
        print("%-32s %s" % (name, st))
    okn = sum(1 for _, s in summary if s == "OK")
    skipn = sum(1 for _, s in summary if s == "skip")
    print("\n成功 %d / %d（跳过 %d）" % (okn, len(summary), skipn))

    json.dump(summary, open(os.path.join(out_root, "_batch_result.json"), "w",
                            encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if okn + skipn == len(summary) else 1


if __name__ == "__main__":
    sys.exit(main())
