---
name: teaching-plan-handwriting
description: 用你自己的手写字体，出一条两页 A4 的手写版教学设计 PDF。
version: 1.0.0
author: lijing
license: MIT
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [手写, 教学设计, 教案, 手写字体, pdf, 教学]
    category: productivity
---

# 教学设计手写 PDF（用你自己的字体）

把一份教案内容，写成一张**学校两页表格 + 手写笔迹**的教学设计，直接打印上交。

版式已固定：A4 纵向、两页、表格线原样保留、字号统一 43 号、教学过程行距 1.26、
正文首行缩进 2 字、标点画成手写笔点。**你只需要提供内容和自己的字体。**

## 什么时候用

- 「写一份 XX 课的教学设计 / 教案 / 备课稿」
- 「用我的字体写教学设计」
- 「把手写的教学设计打印出来」

## 先决条件：你的手写字体

这个工具**不含字体**（字体有版权，也应当是你自己的笔迹）。你需要一份自己的手写 TTF：

1. 去 [萝卜工坊 beautifulcarrot.com](https://beautifulcarrot.com) 上传手写样本，生成自己的定制字体并下载 TTF
   （或直接用任何你喜欢的手写体，只要覆盖你要写的字）
2. 把字体文件放到仓库根目录的 `assets/` 下：

```
teaching-plan-handwriting/
  assets/
    我的字体.ttf        ← 放这里，文件名随意
```

也可以用环境变量指定：

```bash
export HWSIM_FONT=/path/to/我的字体.ttf
```

**字体覆盖率要求**：一份教学设计约用 300~400 个不同汉字。字体缺字会渲染成方框。
先跑一次覆盖检查：

```bash
python scripts/check_font.py "内容.json"
```

它会告诉你缺哪些字——缺字请回萝卜工坊补字或换字体。

## 安装

```bash
pip install -r requirements.txt
```

只需要 numpy、Pillow、img2pdf（PyMuPDF 可选，用于页数自检）。

## 用法

### 一条命令

```bash
python scripts/make_teaching_plan.py my_lesson.json
```

产出：

```
output/my_lesson/教学设计_手写.pdf      ← 打印这个
output/my_lesson/教学设计_第1页.png    ← 预览
output/my_lesson/教学设计_第2页.png
```

### 内容怎么写

复制 `examples/教学设计_内容模板.json` 改内容即可。字段：

| 字段 | 含义 | 字数上限 |
| --- | --- | --- |
| `grade` `subject` `unit` `lesson` | 年级/学科/单元/课时 | 短 |
| `author` | 主备人 | 短 |
| `prep_date` `polish_date` | 备课/磨课时间 | **留空**，让老师手填 |
| `topic` | 课题 | ≤16 |
| `type` | 课型 | ≤4 |
| `duration` | 教学时间 | ≤4 |
| `objectives` | 教学目标 | **99** |
| `keypoints` | 教学重难点及解决办法 | **82** |
| `methods` | 教法设计 / 学法指导 | **27** |
| `tools` | 教具准备 | **8** |
| `steps` | 教学环节（左侧竖栏，`\n` 分隔，3~4 项，每项 ≤4 字） | — |
| `process` | 教学过程（第1页） | **266** |
| `steps_col2` | 第2页环节竖栏 | — |
| `process_cont` | 教学过程（第2页续） | **254** |
| `homework` | 作业设计 | **52** |
| `blackboard` | 板书设计（`\n` 分条） | **55** |
| `reflection` | 教学反思 | **53** |
| `beifen1` `beifen2` | 二次备课红字批注（字符串数组，每条 ≤6 字） | — |

**超字数会直接中止并告诉你每栏要删几个字**——这是故意的，缩放字号会毁掉整页观感。
超了就精简文案：真人手写一页也就写这么多。

内容量建议打在容量附近（`process` 235~265 字、`process_cont` 195~250 字），
写得太少页面上会空一大片，一眼看出偷工。

### 批量出一整章

```bash
python scripts/batch_plans.py ./my_contents/
```

把多个 `.json` 丢进一个目录，逐节生成。每节约 70~100 秒。

## 版式规格（已固化，不需要调）

| 规格 | 值 |
| --- | --- |
| 页面 | A4 纵向，2 页 |
| 字号 | 全表统一，基准取教学过程，上限 43 |
| 教学过程行距 | 1.26 |
| 缩进 | 正文每段首行缩进 2 字，环节标题顶格 |
| 标点 | 手写笔点（叠笔路径画的墨渍，不是字体标点） |
| 教法学法 | 左对齐；课时/课型/教具居中 |
| 二次备课 | 红笔批注，不带 ①②③ / 圆点 |
| 笔迹扰动 | 单字大小、旋转、基线、字距均有极小随机；已做视觉尺寸归一化，不会忽大忽小 |

## 输出质量自检

脚本跑完会打印每栏实际字号和尺寸。**必须确认**：

1. 页数是 2（不是 1 也不是 3）
2. 没有 `!!` 报警行
3. 打开 `教学设计_第1页.png` / `第2页.png` 看一眼：末行有没有被切、缩进对不对

## 常见问题

**满页空心方框** → 字体缺字。跑 `python scripts/check_font.py` 确认。

**字看起来忽大忽小很刻意** → 这是老版本的 bug，已修（`GLYPH_FILL`/`SIZE_JITTER` 视觉归一化）。
如果你改过 `handwrite_v4.py`，别把 `SIZE_JITTER` 调到 0.02 以上。

**字太淡/太细** → 调 `handwrite_v4.py` 的 `STROKE_GAIN`。实测对照：

| STROKE_GAIN | 笔画粗细 | 感觉 |
| --- | --- | --- |
| 1.18 | 0.40~0.67mm | 偏细，像 0.38 笔 |
| 1.45 | 0.49~0.82mm | **默认**，0.5mm 签字笔偏粗 |
| 1.95 | — | 接近中性笔重压 |

**想换成别的版式** → `templates/tpl_p0.png`、`tpl_p1.png` 是版式本身（200dpi 的 A4 扫描图）。
换成你们学校的模板，然后改 `scripts/fill_template_v3.py` 里的 `P1` / `P2` 格子坐标常量。
坐标怎么测见 `docs/坐标测量.md`。

## 目录结构

```
teaching-plan-handwriting/
  assets/                     ← 你的字体放这里（不含在仓库里）
  examples/教学设计_内容模板.json
  templates/tpl_p0.png         ← 版式第1页（200dpi A4）
  templates/tpl_p1.png         ← 版式第2页
  scripts/
    make_teaching_plan.py      ← 主入口
    fill_template_v3.py        ← 模板填空渲染
    handwrite_v4.py            ← 手写笔画引擎
    hand_diagram.py            ← 二次备课手绘示意图
    batch_plans.py             ← 批量
    check_font.py              ← 字体覆盖率检查
  docs/坐标测量.md
```

## 许可

代码 MIT。`templates/` 里的表格版式图来自公开的学校教学设计模板，仅作格式参考；
字体文件不随仓库分发，请使用你自己的字体。
