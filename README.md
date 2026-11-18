# 教学设计手写 PDF 生成器

用**你自己的手写字体**，把一份教案内容排成学校那两页表格的手写版教学设计，输出可直接打印的 PDF。

> 版式固定、字号统一、标点为手写笔点、笔迹带自然起伏。
> 你只需要：一、写好内容 JSON；二、把自己的手写字体放进 `assets/`。

---

## 效果

输入（JSON）：

```json
{
  "topic": "动物体的结构层次",
  "objectives": "1. 生命观念：说出四种基本组织的名称、特点与功能...",
  "process": "一、情境导入（5分钟）\n出示鱼由受精卵发育成小鱼的组图..."
}
```

输出：两页 A4 手写版教学设计 PDF。

---

## 快速开始

### 1. 装依赖

```bash
pip install -r requirements.txt
```

### 2. 放字体

把你自己的手写字体放到 `assets/`：

```bash
cp ~/Downloads/我的手写字体.ttf assets/
```

**没有自己的字体？** 去 [萝卜工坊](https://beautifulcarrot.com) 上传 40~50 个手写汉字，
它能生成覆盖 3500 常用字的定制 TTF，下载后放进 `assets/` 即可。

当前仓库默认不带字体（字体有版权，也应当是你本人的笔迹）。
若 `assets/` 里没字体，程序会直接告诉你该放哪。

### 3. 写内容

```bash
cp examples/教学设计_内容模板.json my_lesson.json
# 编辑 my_lesson.json
```

各栏有字数上限（见 `SKILL.md`），超了程序会告诉你每栏删几个字。

### 4. 生成

```bash
python scripts/make_teaching_plan.py my_lesson.json
```

产物在 `output/my_lesson/`：
- `教学设计_手写.pdf` ← 打印这个
- `教学设计_第1页.png`、`第2页.png` ← 预览

---

## 为什么字看起来像真人写的

不是简单套字体，而是三层处理：

1. **笔画级渲染**：从字体轮廓提取骨架，按走向做粗细调制——横画梭子形、撇捺出锋、墨色沿笔画渐变。
2. **手写标点**：`，。、；：` 不用字体字形，改用叠笔路径画出的墨渍（不规则、带飞白）。
3. **视觉尺寸归一化**：字体本身各字字形框大小不齐（「入」101px vs「等」123px），
   这里按最长边把每个字拉到统一视觉字面，只保留 ±5% 的自然起伏——
   看得出手写，又不会忽大忽小显得刻意。

---

## 版式可换

`templates/tpl_p0.png` / `tpl_p1.png` 是版式本身（200dpi A4 图）。
换成你们学校的模板，再改 `scripts/fill_template_v3.py` 里的格子坐标常量即可。
测量方法见 `docs/坐标测量.md`。

---

## 目录

```
assets/              你的字体（.ttf/.otf），不进版本库
examples/            内容模板
templates/           两页版式图
scripts/
  make_teaching_plan.py   主入口（核字数→渲染→自检→输出）
  fill_template_v3.py     模板填空
  handwrite_v4.py         手写笔画引擎
  hand_diagram.py         二次备课手绘示意图
  batch_plans.py          批量
  check_font.py           字体覆盖率检查
docs/
```

---

## 许可

代码 MIT。字体请自备。
