"""
make_sample_pdf.py
生成测试用示例文档「员工手册.pdf」（多页、含章节标题），用于端到端演示。
用法: python scripts/make_sample_pdf.py [输出路径]
"""

import sys
from pathlib import Path

import fitz  # PyMuPDF

# 章节内容（足够长，切分后会形成多个 chunk，且标题可被章节优先切分器识别）
CONTENT = [
    ("公司简介", [
        "星云科技股份有限公司（以下简称「公司」）成立于2015年，注册资本5000万元，是一家专注于企业级人工智能与知识管理解决方案的国家高新技术企业。",
        "公司总部位于深圳南山科技园，在上海、北京设有分支机构，现有员工260余人，其中研发人员占比超过60%。",
        "公司主营业务包括：企业知识库系统、智能问答机器人、业务流程自动化平台以及私有化AI中台建设。公司坚持「数据不出域」的安全理念，所有产品均支持本地化部署。",
    ]),
    ("考勤制度", [
        "公司实行标准工作制，周一至周五工作，周末双休。夏季作息时间为上午9:00至12:00，下午14:00至18:00；冬季作息时间为上午9:00至12:00，下午13:30至17:30。",
        "员工上下班须通过企业微信进行打卡，考勤记录以系统时间为准。每月考勤周期为上月26日至当月25日。",
        "迟到或早退30分钟以内的，按每次扣发绩效分1分处理；超过30分钟的按旷工半天处理。一个月内累计迟到3次以上，取消当月全勤奖。",
        "因公外出无法打卡的，须在当日通过OA系统提交外勤申请，经直属主管审批后生效，否则视为缺勤。",
    ]),
    ("休假制度", [
        "员工依法享有年休假。入职满1年不满10年的，年休假5天；已满10年不满20年的，年休假10天；已满20年的，年休假15天。国家法定节假日不计入年休假。",
        "年休假原则上应在当年度内休完，确因工作原因无法安排的，经批准可顺延至次年第一季度。未休年休假按日工资收入的300%支付补偿。",
        "员工请事假须提前1个工作日提交申请；请病假须提供二级甲等以上医院出具的诊断证明，病假期间按当地最低工资标准的80%计发。",
        "婚假、产假、陪产假、丧假等按国家及地方有关规定执行，具体天数以当地最新政策为准。",
    ]),
    ("薪酬福利", [
        "公司实行「基本工资+岗位工资+绩效奖金」的薪酬结构，每月10日发放上月工资。遇节假日提前至最近工作日发放。",
        "公司依法为员工缴纳五险一金，缴费基数按员工上年度月平均工资核定。另有补充商业保险，覆盖员工及直系亲属的意外与医疗保障。",
        "公司设立季度绩效奖金与年度十三薪。绩效考核结果分为S/A/B/C四档，连续两个季度获得S档的员工将获得晋升优先资格。",
        "员工生日当月可享半天带薪假期及生日礼券；每年组织一次全员健康体检；重要节假日发放节日慰问品。",
    ]),
    ("保密规定", [
        "公司全体员工均须签署保密协议。客户数据、源代码、内部经营数据等属于公司核心机密，未经授权不得向任何第三方披露。",
        "涉及客户敏感数据的文档，一律存放于公司统一管理的内网存储系统，禁止通过个人网盘、聊天工具等外部渠道传输。",
        "离职员工须在离职前完成工作交接与数据清理，归还全部公司资产，并继续履行保密义务。保密义务不因劳动关系终止而解除。",
        "违反保密规定给公司造成损失的，公司将依法追究相应责任；情节严重的，移交司法机关处理。",
    ]),
]

TITLE = "员工手册"
SUBTITLE = "星云科技股份有限公司"
VERSION = "版本号：V2.1（2026年1月）"


def find_cjk_font() -> str:
    """查找系统中可用的中文字体（Windows 优先）"""
    candidates = [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise RuntimeError("未找到中文字体，请指定 fontfile 参数或安装中文字体")


def make_pdf(out_path: Path, fontfile: str = None):
    fontfile = fontfile or find_cjk_font()
    doc = fitz.open()

    # ── 封面页 ──
    page = doc.new_page(width=595, height=842)  # A4
    rect = fitz.Rect(60, 300, 535, 560)
    page.insert_textbox(rect, f"{TITLE}\n\n{SUBTITLE}\n\n{VERSION}",
                        fontname="china-s", fontfile=fontfile, fontsize=22,
                        align=fitz.TEXT_ALIGN_CENTER, color=(0.12, 0.16, 0.28))

    # ── 正文各章（每章一页）──
    for chapter, paras in CONTENT:
        page = doc.new_page(width=595, height=842)
        y = 70
        # 章标题：统一前缀 "第X章"（可被章节优先切分器识别）
        chapter_no = CONTENT.index((chapter, paras)) + 1
        cn_num = "一二三四五六七八九"[chapter_no - 1] if chapter_no <= 9 else str(chapter_no)
        heading = f"第{cn_num}章 {chapter}"
        page.insert_textbox(fitz.Rect(60, y, 535, y + 40), heading,
                            fontname="china-s", fontfile=fontfile, fontsize=18,
                            color=(0.1, 0.35, 0.75))
        y += 55
        body = "\n\n".join(paras)
        page.insert_textbox(fitz.Rect(60, y, 535, 800), body,
                            fontname="china-s", fontfile=fontfile, fontsize=12,
                            color=(0.15, 0.15, 0.15))

    doc.save(str(out_path))
    print(f"[OK] 已生成示例文档: {out_path}（{len(CONTENT) + 1} 页）")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "员工手册.pdf"
    make_pdf(out)
