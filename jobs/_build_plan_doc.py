"""生成《询价记录与产品库 SPU 关联方案》Word 文档到桌面。"""
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.stdout.reconfigure(encoding="utf-8")

FONT = "微软雅黑"
MONO = "新宋体"
OUT = Path.home() / "Desktop" / "询价记录与产品库SPU关联方案.docx"

doc = Document()

# ---------- 页面与默认字体 ----------
sec = doc.sections[0]
sec.page_width = Cm(21)
sec.page_height = Cm(29.7)
sec.left_margin = Cm(2.2)
sec.right_margin = Cm(2.2)
sec.top_margin = Cm(2.2)
sec.bottom_margin = Cm(2.0)


def set_font(run, name=FONT, size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


normal = doc.styles["Normal"]
normal.font.name = FONT
normal.font.size = Pt(10.5)
normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
normal.paragraph_format.space_after = Pt(4)
normal.paragraph_format.line_spacing = 1.35

for lvl in (1, 2, 3):
    st = doc.styles[f"Heading {lvl}"]
    st.font.name = FONT
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    st.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    st.font.size = Pt({1: 16, 2: 13, 3: 11.5}[lvl])
    st.font.bold = True
    st.paragraph_format.space_before = Pt({1: 14, 2: 10, 3: 8}[lvl])
    st.paragraph_format.space_after = Pt(6)


def para(text="", size=10.5, bold=False, color=None, space_after=4, align=None):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    if text:
        set_font(p.add_run(text), size=size, bold=bold, color=color)
    return p


def bullet(text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Cm(0.7)
    set_font(p.add_run(text), size=size)
    return p


def shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:color"), "auto")
    el.set(qn("w:fill"), hex_color)
    tcPr.append(el)


def table(headers, rows, widths, header_bg="1F3A5F", font_size=9.5, zebra=True):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.width = Cm(widths[i])
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(2)
        set_font(p.add_run(h), size=font_size, bold=True, color=(0xFF, 0xFF, 0xFF))
        shade(c, header_bg)
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for i, val in enumerate(row):
            c = cells[i]
            c.width = Cm(widths[i])
            c.text = ""
            p = c.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            set_font(p.add_run(str(val)), size=font_size, bold=(i == 0))
            if zebra and ri % 2 == 1:
                shade(c, "F2F5F9")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def code_block(lines):
    p = doc.add_paragraph()
    # shd 必须先于 spacing/ind 插入，否则不符合 pPr 的元素顺序
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), "F4F6F8")
    p._p.get_or_add_pPr().append(shading)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.left_indent = Cm(0.5)
    for i, line in enumerate(lines):
        r = p.add_run(line + ("\n" if i < len(lines) - 1 else ""))
        set_font(r, name=MONO, size=9)
    return p


# ==================== 封面 ====================
para("询价记录与产品库（SPU）关联方案", size=22, bold=True, color=(0x1F, 0x3A, 0x5F),
     space_after=6, align=WD_ALIGN_PARAGRAPH.CENTER)
para("数据分类 · 自动化与人工分工 · 合并设计", size=12, color=(0x5A, 0x6B, 0x7F),
     space_after=20, align=WD_ALIGN_PARAGRAPH.CENTER)

table(
    ["项目", "内容"],
    [
        ["文档日期", "2026-10-19"],
        ["数据来源", "线上 parts_database（5603 条） + OA oa_yixiuti（3966 条已完成询价）"],
        ["关联模型", "parts（SPU）1 : N 询价记录，询价记录作为子表关联到 SPU"],
        ["核对方式", "全部为只读查询，未写入任何数据"],
        ["当前阶段", "方案讨论，未开始建表与写入"],
    ],
    [4.0, 12.0],
    font_size=10,
)

# ==================== 一、结论摘要 ====================
doc.add_heading("一、结论摘要", level=1)
para("1. OA 的“型号”字段（ele_type）在 3966 条询价中 100% 为空，无法作为关联键；"
     "真正可用的是“规格”（goods_spec），需先拆分为型号 token 再与 parts.model 比对。")
para("2. 产品名称（product_name）在线上只有 706 种，本质是品类名，只能用于缩小范围或消歧，"
     "不能作为唯一关联键。")
para("3. 按线上数据实测，3966 条询价可分为三档：")

table(
    ["档位", "条数", "占比", "处理方式", "人工核对单位"],
    [
        ["脚本自动写入", "1613", "40.7%", "型号精确且命中唯一 SPU", "0"],
        ["需要人工", "2032", "51.2%", "按型号/品类/规格值分组核对", "890"],
        ["新增产品", "321", "8.1%", "批量新增 + 查重 + 抽查", "292（抽查）"],
    ],
    [3.2, 2.2, 2.0, 5.6, 3.4],
)
para("人工核对单位已按“型号 / 规格值 / 品类”去重，实际核对 890 次，而不是 2032 条。"
     "按每次 20 秒估算约 5 小时，可分多天完成。", size=9.5, color=(0x5A, 0x6B, 0x7F))

# ==================== 二、数据核对 ====================
doc.add_heading("二、数据核对", level=1)
doc.add_heading("2.1 数据规模", level=2)
table(
    ["对象", "数量", "说明"],
    [
        ["parts 产品", "5603 条", "线上产品库"],
        ["其中 model 非空", "5582 条", "99.6% 有型号"],
        ["去重型号", "5661 个", "含 substitute_model（替代型号 478 条）"],
        ["重复型号", "334 个", "涉及 730 条产品，按型号关联会出现一对多"],
        ["product_name 去重", "706 种", "产品名高度重复，基本是品类名"],
        ["OA 已完成询价", "3966 条", "mission_type=1、mission_status=4、未删除"],
        ["其中 ele_type 非空", "0 条", "型号字段完全为空"],
        ["其中 goods_spec 非空", "3719 条", "93.8%，是唯一可用的型号来源"],
    ],
    [4.6, 2.6, 9.0],
)

doc.add_heading("2.2 规格（goods_spec）形态分布", level=2)
table(
    ["形态", "数量", "占比", "示例"],
    [
        ["纯型号（英数）", "2138", "53.9%", "AODD0302、MCTC-HCB-V1"],
        ["纯数字 / 尺寸", "776", "19.6%", "10、400*6*8、8*19S+NF-8mm"],
        ["型号 + 附加（空格/逗号）", "323", "8.1%", "SC-E05P  AC110、DILM50C，AC220"],
        ["中英混写", "261", "6.6%", "康力专用操作器，匹配如图的主板"],
        ["纯字母", "162", "4.1%", "SOP4、NKT"],
        ["空", "247", "6.2%", "—"],
        ["纯中文", "59", "1.5%", "—"],
    ],
    [5.2, 2.4, 2.2, 6.6],
)

doc.add_heading("2.3 三个必须接受的事实", level=2)
bullet("型号是唯一可用的自动关联键，且必须先做归一化（去空格、转大写、全角转半角）。")
bullet("名称不能当关联键：706 种名称覆盖 5603 条产品，一个品类对应几十上百个 SPU。")
bullet("尺寸型规格（如 400*5*10）会跨品类命中（曳引轮、导向轮），不能直接批量关联。")

# ==================== 三、数据分类 ====================
doc.add_heading("三、数据分类（8 类）", level=1)
para("按“规格能否作为型号命中 parts.model”优先判定，未命中时再按规格形态与品类名细分。"
     "各类互斥，合计 3966 条。")
table(
    ["#", "分类", "条数", "占比", "去重核对单位", "处理"],
    [
        ["1", "型号精确唯一", "1613", "40.7%", "—", "脚本自动写入"],
        ["2", "多条对多条（型号命中多个 SPU）", "212", "5.3%", "135 个型号", "人工选父 SPU"],
        ["3", "规格为空", "133", "3.4%", "133 条", "一半人工，一半新增"],
        ["4", "只有品类名相同", "1185", "29.9%", "178 个品类", "改为补型号，不逐个挂"],
        ["5", "尺寸或品类名对不上", "264", "6.7%", "214 个值", "人工判断"],
        ["6", "规格是型号但产品库没有", "321", "8.1%", "292 个值", "批量新增 + 查重"],
        ["7", "规格是描述文字", "238", "6.0%", "230 条", "人工提取型号"],
    ],
    [1.0, 5.4, 1.8, 1.8, 3.2, 3.2],
)
para("说明：第 4 类建议“补型号”后，其中大部分会自动落入第 1 类；第 6 类属于建产品而非挂关联。",
     size=9.5, color=(0x5A, 0x6B, 0x7F))

doc.add_heading("3.1 与人工初版分类的对照", level=2)
table(
    ["分类", "初版（Word）", "线上实测", "判断"],
    [
        ["型号精确唯一", "1756", "1613", "接近（口径含替代型号）"],
        ["多条对多条", "393", "212", "差异 181"],
        ["规格为空", "127", "133", "可复现"],
        ["只有品类名相同", "676", "1185", "口径不同，需确认"],
        ["品类名对不上", "61", "264", "口径不同，需确认"],
        ["型号但库中没有", "341", "321", "接近"],
        ["描述文字", "186", "238", "接近"],
        ["查不到→新增", "426", "含在 5/6/7 中", "需确认边界"],
    ],
    [4.6, 3.2, 3.2, 5.4],
)

# ==================== 四、脚本可实现的 ====================
doc.add_heading("四、脚本可自动实现的部分", level=1)
doc.add_heading("4.1 自动写入范围", level=2)
para("仅一类：型号精确命中且该型号在 parts 中对应唯一 SPU，共 1613 条（40.7%）。"
     "匹配时把 substitute_model 一并纳入型号字典。")
doc.add_heading("4.2 判定规则", level=2)
code_block([
    "spec   = 归一化(goods_spec)        # 去空格 / 转大写 / 全角转半角",
    "tokens = spec.split(空格 , ; 、 ， ； / |)",
    "hit    = { parts.id | 任一 token 精确等于 parts.model 或 parts.substitute_model }",
    "",
    "若 len(hit) == 1  -> 自动写入子表 part_id = 唯一 SPU",
    "若 len(hit) >  1  -> 进入人工队列（同一型号选一次父 SPU）",
    "若无命中          -> 进入分类 3~7 后续流程",
])

doc.add_heading("4.3 必须的保护措施", level=2)
table(
    ["保护", "规则", "原因"],
    [
        ["归一化", "去空格、转大写、全角括号/逗号转半角", "SC-E05P  AC110 存在双空格"],
        ["短 token 排除", "长度 < 4 或纯数字不进自动档", "“10”会命中 918 个 SPU"],
        ["幂等", "inquiry_mission_id 唯一键，脚本可重复执行", "防止重复挂载"],
        ["尺寸型标记", "纯尺寸规格标记为 match_type=3，单独抽查", "400*5*10 会跨品类命中"],
        ["不覆盖人工结果", "已有人工记录不参与自动写入", "避免覆盖核对结论"],
    ],
    [3.2, 7.6, 5.6],
)

doc.add_heading("4.4 子表结构与写入方式", level=2)
code_block([
    "CREATE TABLE part_inquiries (",
    "  id                 BIGINT AUTO_INCREMENT PRIMARY KEY,",
    "  part_id            INT NULL COMMENT '归属 SPU，NULL 表示人工判定无法关联',",
    "  inquiry_mission_id INT NOT NULL COMMENT 'OA 询价任务 ID',",
    "  order_goods_id     INT NULL COMMENT 'OA 询价商品 ID',",
    "  match_type         TINYINT NOT NULL DEFAULT 0",
    "                     COMMENT '1型号唯一 2名称收窄 3尺寸型 4人工关联 9人工忽略',",
    "  matched_key        VARCHAR(128) NOT NULL DEFAULT '' COMMENT '命中的型号 token',",
    "  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
    "  updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,",
    "  UNIQUE KEY uq_inquiry (inquiry_mission_id),",
    "  KEY idx_part (part_id, created_at)",
    ") COMMENT='SPU 关联的 OA 询价记录';",
])
para("查询子表时统一加 WHERE part_id IS NOT NULL；“忽略”用 part_id 为空表示，不额外建表。")

# ==================== 五、需要人工的 ====================
doc.add_heading("五、需要人工处理的部分", level=1)
table(
    ["分类", "条数", "核对单位", "人工动作"],
    [
        ["多条对多条", "212", "135 个型号", "从 2~4 个候选 SPU 中选 1 个，该型号下所有询价一起挂"],
        ["规格为空", "133", "133 条", "品类名对得上的选候选；对不上的转新增产品"],
        ["尺寸/品类名对不上", "264", "214 个值", "判断是否属于已有产品；不属实则新增或忽略"],
        ["描述文字", "238", "230 条", "从描述中提取型号，补进产品库或忽略"],
        ["只有品类名相同", "1185", "178 个品类", "建议改为“补型号”，不做逐个挂载"],
    ],
    [4.2, 2.0, 3.2, 7.0],
)
para("人工合计 890 个核对单位；其中 178 个品类走“补型号”，其余 712 个逐个核对。")

doc.add_heading("5.1 为什么第 4 类不建议人工挂载", level=2)
para("该类 1185 条对应 178 个品类，平均每个品类对应数十个 SPU（例如“接触器”有 364 个）。"
     "人工在几十个候选里选择，既慢又必然出错；即使选对一次，下一条同品类询价仍需再选。")
para("更省事的做法：把询价规格里的型号补到对应 SPU 的 model 或 substitute_model，"
     "之后同型号询价自动命中第 1 类，从“永久人工”变成“一次投入”。")

doc.add_heading("5.2 第 6 类（新增产品）的保护", level=2)
bullet("新增前按 model 全库查重（含 substitute_model），已存在则挂已有 SPU。")
bullet("同型号多条询价合并为 1 个 SPU，品牌取出现最多者，其余记入备注。")
bullet("新增时写来源标记（source=inquiry + inquiry_mission_id），便于追溯与回滚。")

# ==================== 六、核对界面 ====================
doc.add_heading("六、人工核对界面方案", level=1)
para("核心原则：一行 = 一个“匹配键”（型号/规格值/品类），不是一条询价。"
     "因为 1:N 模型下，选定 SPU 后该键下所有询价一次挂载。")

doc.add_heading("6.1 队列视图", level=2)
code_block([
    "+--------------+--------+------+------+----------------+--------+----------+",
    "| 规格值        | 类型   | 询价 | 候选 | 推荐            | 状态   | 操作      |",
    "+--------------+--------+------+------+----------------+--------+----------+",
    "| M2000-S01D   | 多义   |  3   |  2   | 门机控制器(江南)| 待核对 | 核对      |",
    "| DG-265K      | 多义   |  1   |  2   | 限速器(三菱)    | 待核对 | 核对      |",
    "| 400*5*10     | 多义   |  1   | 65   | —              | 待核对 | 核对      |",
    "| AC220        | 噪音   | 18   |  —   | —              | 建议忽略| 忽略整组  |",
    "| TVVBPG       | 噪音   | 20   |  —   | —              | 建议忽略| 忽略整组  |",
    "+--------------+--------+------+------+----------------+--------+----------+",
    "排序：候选数升序（2 个最易判断） → 询价数降序",
    "筛选：类型 / 候选数区间 / 品牌 / 有无图片",
])

doc.add_heading("6.2 单组核对视图", level=2)
code_block([
    "+----------------------------+------------------------------------------+",
    "| 该型号下的询价（3 条）       | 候选 SPU（2 个）                          |",
    "+----------------------------+------------------------------------------+",
    "| #16181 门刀                 | [图] 门机控制器                          |",
    "|   spec: M2000-S01D          |  M2000-S01D · 江南嘉捷 · 门机控制器      |",
    "|   工厂: 江南嘉捷 数量: 2 台  |  已挂 3 条询价 · 更新 2026-09-12         |",
    "|   报价: 1200  2026-09-18    |  ★ 推荐：名称包含「门机控制器」           |",
    "| #16174 接触器               |  [ 关联此 SPU ]                          |",
    "|   spec: M2000-S01D          +------------------------------------------+",
    "|   工厂: 日立   数量: 1 个    | [图] 门机控制器                          |",
    "|   报价: 860   2026-09-15    |  M2000-S01D · 日立 · 门机控制器           |",
    "|                            |  已挂 0 条询价 · 更新 2025-11-03          |",
    "|                            |  [ 关联此 SPU ]                          |",
    "+----------------------------+------------------------------------------+",
    "[ X 忽略整组 ]  [ 跳过 ]      ↑↓ 选候选  Enter 关联  J/K 上一条/下一条",
])

doc.add_heading("6.3 候选卡片字段", level=2)
table(
    ["字段", "填充率", "作用"],
    [
        ["图片缩略图", "74%", "主要区分依据（多数候选文字字段相同）"],
        ["product_name", "100%", "语义判断"],
        ["model", "100%", "确认命中"],
        ["product_brand", "80%", "与询价工厂名对照"],
        ["category / product_type", "81% / 100%", "品类校验"],
        ["已挂询价数", "—", "最强信号：同型号历史询价集中在哪个 SPU"],
        ["更新时间", "100%", "判断是否活跃产品"],
    ],
    [4.2, 3.0, 9.2],
)
para("规格与价格字段不展示：全库仅 92 条产品有规格/价格数据（2%），展示为空。",
     size=9.5, color=(0x5A, 0x6B, 0x7F))

doc.add_heading("6.4 关键交互", level=2)
bullet("键盘优先：↑↓ 选候选、Enter 关联、X 忽略整组、J/K 切换上下条，关联后自动跳下一条。")
bullet("批量：选定 SPU 后，该匹配键下所有询价一次性写入。")
bullet("可撤销：关联成功后 3 秒内可撤销。")
bullet("显示推荐理由：型号精确命中 / 名称包含 / 候选已有同型号询价。")
bullet("候选无差异提示：当候选的名称、品牌、分类、类型完全相同时，提示“可能是重复产品”，"
       "并提供跳转重复产品合并的入口，避免人工盲猜。")

# ==================== 七、合并方案 ====================
doc.add_heading("七、合并方案", level=1)
doc.add_heading("7.1 模型", level=2)
code_block([
    "parts (SPU) 1 -------- N part_inquiries",
    "                          └── inquiry_mission_id（唯一键，一条询价只属于一个 SPU）",
])
para("一个 SPU 下可挂多条询价；线上实测：1101 个 SPU 挂 1 条、126 个挂 2 条、"
     "最多一个 SPU 挂 10 条，一对多模型成立。")

doc.add_heading("7.2 执行顺序", level=2)
table(
    ["阶段", "内容", "数据量", "是否写库"],
    [
        ["第 0 步", "规则定稿 + 全量只读核对，输出逐类明细", "3966", "否"],
        ["第 1 步", "建 part_inquiries 表（启动期幂等迁移）", "—", "是（DDL）"],
        ["第 2 步", "自动写入型号唯一档（match_type=1 / 3）", "1613", "是"],
        ["第 3 步", "人工核对台：多义、规格空、尺寸、描述文字", "712 单位", "是（逐条）"],
        ["第 4 步", "补型号（178 个品类），使部分询价自动落档", "178 单位", "是（更新产品）"],
        ["第 5 步", "新增产品（先查重），回填关联", "321", "是"],
        ["第 6 步", "校验：条数对账、抽样复核、1:N 分布检查", "—", "否"],
    ],
    [2.2, 7.8, 3.0, 3.4],
)

doc.add_heading("7.3 展示层改动", level=2)
para("销售列表（/api/sales/products）保持不变，仍并列展示两个来源；"
     "新增的只是“产品详情页的关联询价子列表”和“询价反查 SPU”。两者不冲突，"
     "待子表数据稳定后再决定是否替换现有并列展示。")

doc.add_heading("7.4 回滚", level=2)
bullet("子表可整表清空重建，不影响 parts 与 OA 数据。")
bullet("第 4 步补型号需先记录原值（写操作日志），可逐条回滚。")
bullet("第 5 步新增产品写来源标记，可按 source=inquiry 批量筛选撤销。")

# ==================== 八、风险与待确认 ====================
doc.add_heading("八、风险与待确认", level=1)
doc.add_heading("8.1 风险", level=2)
table(
    ["风险", "影响", "应对"],
    [
        ["尺寸型规格误命中", "跨品类关联错误", "标记 match_type=3 并抽查 20 条"],
        ["新增产品加剧重复", "产品库继续膨胀", "新增前全库查重，同型号合并为 1 个 SPU"],
        ["候选无差异", "人工无法判断", "提示先合并重复产品，或整组忽略"],
        ["OA 数据变动", "子表记录与 OA 不一致", "展示时实时读 OA，子表只存归属关系"],
        ["人工核对中断", "队列状态丢失", "已核对写入即落库，队列为实时计算"],
    ],
    [3.8, 5.4, 7.2],
)

doc.add_heading("8.2 待确认", level=2)
bullet("第 4 类“只有品类名相同”的 676 条，初版筛选条件是什么？")
bullet("第 5 类“品类名对不上”的 61 条，判定是否为“goods_name 在 parts 中完全查不到”？")
bullet("尺寸型规格（约 122 条）是否也纳入自动写入，还是只做标记待抽查？")
bullet("第 4 类采用“补型号”策略是否认可？这决定人工投入结构。")

# ==================== 附录 ====================
doc.add_heading("附录：口径定义", level=1)
table(
    ["术语", "定义"],
    [
        ["归一化", "去首尾与中间空格、转大写、全角括号/逗号/分号转半角"],
        ["token", "按空格、逗号、分号、顿号、斜杠切分后的单个片段"],
        ["型号精确命中", "某个 token 归一化后与 parts.model 或 parts.substitute_model 完全相等"],
        ["型号唯一", "该型号在 parts 中只对应 1 条产品记录"],
        ["核对单位", "人工需要做一次决策的最小单位（一个型号 / 一个规格值 / 一个品类）"],
        ["描述文字", "规格中含中文，无法直接作为型号使用"],
    ],
    [3.8, 12.6],
)
para("说明：本文所有数字来自线上库只读统计（parts 5603 条、询价 3966 条），"
     "与初版 Word 文档的数字存在差异，主要因统计口径与数据时点不同。",
     size=9, color=(0x5A, 0x6B, 0x7F))

doc.save(str(OUT))
print("[已生成]", OUT)
print("[大小]", round(OUT.stat().st_size / 1024, 1), "KB")
