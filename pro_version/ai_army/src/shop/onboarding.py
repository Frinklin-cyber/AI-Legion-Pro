"""对话式入驻向导 (Onboarding Concierge) v1.0

用聊天方式采集商家信息，取代复杂表单。
针对县级市场商家，使用大白话问答，让AI自动理解和整理信息。

工作流程：
  1. START → AI用大白话打招呼，开始问第一个问题
  2. CHAT  → 商家用口语回答，AI判断回答了什么，追问下一个问题
  3. DONE  → 所有关键信息收集完毕，AI整理成完整档案 + 经营建议

信息采集维度（用大白话覆盖）：
  ① 你是谁 → 店名、卖什么
  ② 你在哪 → 地址、周边环境
  ③ 你做了多久 → 经营年限、规模
  ④ 生意怎么样 → 收入情况、客流
  ⑤ 你的客人是谁 → 客户画像
  ⑥ 你的困难是什么 → 痛点、需求
  ⑦ 竞争对手情况 → 周边竞品
"""

import json, time, os
from typing import Any
from dataclasses import dataclass, field
from loguru import logger

from src.core import BaseSoldier


# ── 数据结构 ──

@dataclass
class OnboardingSession:
    """一次入驻对话的会话状态"""
    session_id: str
    store_type: str = ""           # 行业类型ID
    store_type_name: str = ""      # 行业中文名
    started_at: float = 0.0
    phase: int = 0                 # 当前进度：0=等待选类型, 1=对话中, 2=完成
    history: list[dict] = field(default_factory=list)  # [{role, content}]
    collected: dict = field(default_factory=dict)       # AI提取的结构化信息
    needs_followup: bool = False   # 是否需要在当前话题追问
    followup_topic: str = ""       # 当前追问的话题


# ── 各行业通俗引导问题 ──

INDUSTRY_QUESTIONS = {
    "restaurant": [
        "老板，你的店叫啥名字？大概有多少个座位？",
        "主打什么菜或者什么吃的？店里最拿手的是啥？",
        "店开在哪个位置？周围是什么地方——居民区、写字楼、还是学校附近？",
        "开了多长时间了？一天大概能有多少拨客人？",
        "来的都是什么人——上班族、学生、还是附近的住户？",
        "最近生意怎么样？跟前几个月比是好了还是差了？",
        "这条街/这块区域有没有跟你做差不多生意的？他们做得咋样？",
        "你现在最头疼的是什么？是客太少、赚不到钱、还是别的什么？",
    ],
    "retail": [
        "老板，你的店叫啥名字？大概多大面积？",
        "主要卖啥东西？啥卖得最好？",
        "店开在哪个位置？周围是居民区、商业街、还是批发市场？",
        "干了多长时间了？是自己干还是有请人？",
        "来的都是啥样的客人——年轻人多还是年纪大的？男的还是女的多？",
        "最近生意怎么样？一天大概能做多少单？",
        "你附近还有卖差不多东西的吗？他们的生意比你怎么样？",
        "你现在最头疼的是什么？进货太贵、客人少、还是别的？",
    ],
    "service": [
        "老板，你的店叫啥名字？大概多大面积？有几个师傅/员工？",
        "主要做什么服务？最受欢迎的是啥项目？",
        "店开在哪个位置？周围是居民区、商业区还是别的地方？",
        "干了多长时间了？有多少固定老客人？",
        "来的都是啥样的客人——近的还是远的？女的还是男的？大概多大年纪？",
        "最近生意怎么样？跟前几个月比是好是坏？",
        "你附近还有做差不多服务的吗？收费跟你有啥不一样？",
        "你现在最头疼的是什么？客太少、招人难、还是别的？",
    ],
    "education": [
        "老板，你的机构叫啥名字？有几个老师？",
        "主要教什么？哪个科目/课程报的人最多？",
        "开在哪个地方？周围是学校多还是小区多？",
        "做了多长时间了？现在有多少学生？",
        "学生主要是哪个年龄段的？大概住在多远范围内？",
        "最近招生情况怎么样？跟前几个月比是好了还是差了？",
        "附近还有别的培训机构吗？他们的收费跟你比是贵还是便宜？",
        "你现在最头疼的是什么？招不到学生、留不住老师、还是别的？",
    ],
    "fitness": [
        "老板，你的店叫啥名字？大概多大面积？有几个教练？",
        "主要做什么项目？最火的是什么课？",
        "开在哪个位置？周围是居民区、写字楼还是商业区？",
        "做了多长时间了？现在有多少会员？",
        "来的都是啥样的客人——年轻人还是中年人？男的女的？",
        "最近生意怎么样？新办卡的多不多？",
        "附近还有健身的地方吗？他们的价格跟你比怎么样？",
        "你现在最头疼的是什么？拉新难、留不住人、还是别的？",
    ],
    "hotel": [
        "老板，你的店叫啥名字？有多少间房？",
        "主要接什么样的客人——旅游的、出差的、还是探亲的？",
        "开在哪个位置？离火车站/景区/医院近不近？",
        "做了多长时间了？入住率大概多少？",
        "客人都是从哪来的？本地的还是外地的？",
        "最近生意怎么样？跟前几个月比是好了还是差了？",
        "附近还有旅馆/酒店吗？他们的价格跟你比怎么样？",
        "你现在最头疼的是什么？空房太多、客源不稳定、还是别的？",
    ],
    "florist": [
        "老板，你的店叫啥名字？多大面积？",
        "主要卖什么花？是盆栽多肉还是鲜花切花？",
        "店开在哪个位置？是在花市里、临街店面还是线上做？",
        "干了多长时间了？是自己种还是批发来卖？",
        "来的都是什么样的客人——散客多还是批发多？",
        "最近生意怎么样？跟前几个月比是好是坏？",
        "你附近还有卖花的吗？他们的生意跟你比怎么样？",
        "你现在最头疼的是什么？进价太高、客源少、还是别的？",
    ],
    "auto": [
        "老板，你的店叫啥名字？有几个师傅/工位？",
        "主要做什么——洗车、修车、保养还是美容？",
        "开在哪个位置？靠近主路还是小区里面？",
        "干了多长时间了？一天大概能接多少辆车？",
        "来的都是老客户还是过路客？",
        "最近生意怎么样？跟前几个月比是好是坏？",
        "附近还有修车/洗车的地方吗？他们的收费跟你比怎么样？",
        "你现在最头疼的是什么？客不够、利润薄、还是别的？",
    ],
    "healthcare": [
        "老板，你的店叫啥名字？有几个医生/师傅？",
        "主要看什么病或做什么调理？",
        "开在哪个位置？周围是居民区还是商圈？",
        "做了多长时间了？一天大概能看多少人？",
        "病人/客人主要是哪类——老人、上班族还是小孩？",
        "最近生意怎么样？跟前几个月比是好了还是差了？",
        "附近还有诊所/养生馆吗？跟你比怎么样？",
        "你现在最头疼的是什么？来的少、利润薄、还是别的？",
    ],
    "entertainment": [
        "老板，你的店叫啥名字？大概多大？有几个包间/机台？",
        "主要做什么——KTV、网吧、棋牌还是别的？",
        "开在哪个位置？靠学校还是居民区？",
        "做了多长时间了？一天大概能有多少人来？",
        "来的都是什么人——学生、上班族还是附近居民？",
        "最近生意怎么样？跟以前比是好了还是差了？",
        "附近还有类似的地方吗？他们的生意跟你比怎么样？",
        "你现在最头疼的是什么？来的人少、竞争厉害、还是别的？",
    ],
    "real_estate": [
        "老板，你的店叫啥名字？有几个员工？",
        "主要做什么——二手房、租房、还是新楼盘？",
        "开在哪个位置？负责周边多大范围？",
        "做了多长时间了？一个月大概能成交几套？",
        "客户主要是买房还是租房的？",
        "最近生意怎么样？跟前几个月比是好是坏？",
        "附近还有中介吗？你们跟链家/贝壳比起来有啥不一样？",
        "你现在最头疼的是什么？没房源、没客户、还是别的？",
    ],
}

# 自定义行业的通用问题
CUSTOM_QUESTIONS = [
    "老板你好！先告诉我你的店叫啥名字？卖什么东西或者做什么服务？",
    "店开在哪个地方？越具体越好，比如XX县XX镇XX路旁。",
    "干了多长时间了？现在一共几个人在干？",
    "主要来的都是什么样的客人？说个大概就行。",
    "最近生意咋样？跟前一阵子比是好了还是差了？",
    "你附近还有跟你做差不多生意的吗？他们现在干得怎么样？",
    "你干这行最大的困难是啥？说出来我帮你想想办法。",
]

# 最终生成档案的 Prompt
PROFILE_GENERATION_PROMPT = """你是一个擅长跟县城小老板打交道的AI顾问。现在你跟一位商家聊完了，需要把聊出来的信息整理成一份档案。

## 聊天记录
{chat_log}

## 商家所属行业
{store_type_name}

## 请做三件事：

### 第一件：整理商家档案
用大白话整理成下面这样（JSON格式）：
```json
{{
  "store_name": "店名（如果没有就问"大概叫啥"）",
  "industry": "做什么的",
  "address": "在哪里",
  "scale": "规模（几个人/多大面积/多少个座位等）",
  "history": "开了多久",
  "main_products": "主要卖什么/做什么服务",
  "customer_profile": "客人都是什么样的人",
  "business_status": "最近生意怎么样",
  "pain_points": ["最头疼的问题1", "头疼的问题2"],
  "competition": "周边竞争情况",
  "monthly_revenue_estimate": "聊到月收入的话记录下来，没有的话填'未提及'",
  "daily_customer_estimate": "聊到每天客人数的话记录下来，没有的话填'未提及'"
}}
```

### 第二件：给商家出个主意
用大白话写一段300-500字的分析，说给老板听的：
- 他的店现在最大的问题是什么？
- 结合他的具体情况（在哪、卖啥、客人是谁），给他3条实在的建议
- 建议一定要具体、能落地，不能是"提升服务品质"这种正确但没用的话
- 如果商家有当地特殊的经营条件（比如靠景区、靠学校、在花市旁边等），要充分考虑
- 像本地朋友聊天一样写，不要太书面化

### 第三件：给商家打个分
给下面的指标打个1-5分：
```json
{{
  "score_location": 评分,    // 位置好不好
  "score_product": 评分,     // 产品/服务有没有特色
  "score_customer": 评分,    // 客户资源怎么样
  "score_operation": 评分,   // 经营能力怎么样
  "score_potential": 评分    // 增长潜力大不大
}}
```

请直接输出一个JSON对象，格式：{{"profile": {{...}}, "advice": "给商家的大白话建议...", "scores": {{...}}}}"""


# ── 会话管理 ──

class OnboardingManager:
    """入驻对话管理器"""

    def __init__(self):
        self._sessions: dict[str, OnboardingSession] = {}
        self._soldier: BaseSoldier | None = None

    def _get_soldier(self) -> BaseSoldier:
        if self._soldier is None:
            self._soldier = BaseSoldier()
            self._soldier.name = "入驻向导"
            self._soldier.role = "onboarding_concierge"
            self._soldier.temperature = 0.7
            self._soldier.max_tokens = 2000
        return self._soldier

    def get_questions(self, store_type: str) -> list[str]:
        """获取适用于该行业的大白话问题列表"""
        return INDUSTRY_QUESTIONS.get(store_type, CUSTOM_QUESTIONS)

    def start_session(self, user_id: str, store_type: str, store_type_name: str) -> OnboardingSession:
        """开始新的入驻对话"""
        session_id = f"{user_id}_{int(time.time())}"
        session = OnboardingSession(
            session_id=session_id,
            store_type=store_type,
            store_type_name=store_type_name,
            started_at=time.time(),
            phase=1,
            history=[],
            collected={},
        )
        self._sessions[user_id] = session
        return session

    def get_session(self, user_id: str) -> OnboardingSession | None:
        return self._sessions.get(user_id)

    def end_session(self, user_id: str):
        if user_id in self._sessions:
            del self._sessions[user_id]

    def get_first_message(self, store_type_name: str, questions: list[str]) -> str:
        """生成第一句打招呼+第一个问题"""
        first_q = questions[0] if questions else "先跟我说说你的店是做什么的吧？"
        return f"""老板你好！👋

我是你的AI经营顾问，接下来咱们随便聊聊，我问你几个简单问题，你就像跟朋友唠嗑一样回答就行。

{first_q}"""

    def _should_skip_question(self, question: str, collected: dict, store_type: str) -> bool:
        """判断某个问题是否可以跳过（已通过之前对话收集到足够信息）"""
        # 检查是否已有足够信息覆盖这个问题
        key_mapping = [
            ([], "store_name"),          # 店名
            (["main_products"], ""),     # 主营
            (["address"], ""),           # 地址
            (["history", "scale"], ""),  # 历史+规模
            (["customer_profile"], ""),  # 客户
            (["business_status", "daily_customer_estimate", "monthly_revenue_estimate"], ""),  # 生意
            (["competition"], ""),       # 竞品
            (["pain_points"], ""),       # 困难
        ]
        # 简化判断：如果某些关键信息已经有了就跳过对应问题
        return False  # 不跳过，让AI来决定是否追问

    async def process_message(self, user_id: str, user_message: str, session: OnboardingSession) -> dict:
        """处理商家的回答，判断下一步怎么走"""
        questions = self.get_questions(session.store_type)

        # 追加到对话历史
        session.history.append({"role": "user", "content": user_message})

        # 判断当前进度：历史中 assistant 说了几句话 = 已经问过几个问题
        assistant_count = sum(1 for m in session.history if m["role"] == "assistant")
        current_q_index = assistant_count  # 下一个问题索引

        # 用AI提取当前回答中的有用信息
        soldier = self._get_soldier()

        # 构建上下文让AI决定下一步
        context_lines = [
            f"## 商家行业：{session.store_type_name}",
            f"## 已问的问题数：{assistant_count}（共{len(questions)}个问题）",
            "",
            "## 预设问题列表：",
        ]
        for i, q in enumerate(questions):
            marker = "← 下一个要问" if i == current_q_index else ("✓ 已问过" if i < current_q_index else "")
            context_lines.append(f"  {i+1}. {q} {marker}")

        context_lines.append("")
        context_lines.append("## 对话记录：")
        for m in session.history:
            role_label = "商家" if m["role"] == "user" else "AI"
            context_lines.append(f"  [{role_label}] {m['content']}")

        context_text = "\n".join(context_lines)

        # 判断是否所有基础问题都覆盖了
        if current_q_index >= len(questions):
            # 所有预设问题问完了，进入最后环节
            decision_prompt = f"""{context_text}

## 任务
所有预设问题都问完了。请判断：
1. 商家说的重要信息都收集到了吗？有没有特别值得追问的点？
2. 如果没有需要追问的了，"action"填"complete"；如果还想追问什么，"action"填"followup"并写出追问的话。

请按JSON返回：{{"action":"complete 或 followup", "message":"给商家说的话", "has_critical_info": true或false}}"""
        else:
            # 还有问题要问，但可能需要先对当前回答做回应
            next_q = questions[current_q_index]
            decision_prompt = f"""{context_text}

## 当前要问的问题
{next_q}

## 任务
商家刚才说了他的回答。请你：
1. 先用大白话回应一下商家（表示你听懂了、给他一点肯定或共鸣）
2. 然后自然地引出下一个问题（已写好的问题：「{next_q}」）
3. 整段话要像朋友聊天一样自然，不要太生硬

注意：
- 如果商家的一句话回答了多个问题（比如既说了店名又说了卖什么），可以跳过已覆盖的问题
- 不要念稿子一样把问题列表读出来，要自然过渡
- 回应里可以结合当地情况（如果商家提到了具体地名）

请返回JSON：{{"action":"next", "message":"你回复商家的话（包含回应+下一个问题）"}}"""

        try:
            content, _ = soldier.chat(
                system_prompt="你是一个专门跟县城小老板聊天的AI助手。说话要亲切、接地气、用大白话。像个热心的本地朋友，不要整那些书面语。你是来帮商家把生意搞好的。",
                user_message=decision_prompt,
            )

            # 解析AI返回的JSON
            result = self._parse_ai_response(content)
            if not result:
                # 解析失败，用默认逻辑
                if current_q_index < len(questions):
                    result = {"action": "next", "message": f"明白了！那再问你一下：{questions[current_q_index]}"}
                else:
                    result = {"action": "complete", "message": "好的，信息收集得差不多了！我帮你整理一下分析报告。"}

            # 追加AI回应到历史
            session.history.append({"role": "assistant", "content": result.get("message", "")})

            # 如果是完成了，触发档案生成
            if result["action"] == "complete":
                result["next_phase"] = "complete"

            return result

        except Exception as e:
            logger.error(f"[Onboarding] AI处理失败: {e}")
            if current_q_index < len(questions):
                return {"action": "next", "message": f"嗯嗯好的！再问一下：{questions[current_q_index]}"}
            else:
                return {"action": "complete", "message": "聊得差不多了，我帮你整理一下！", "next_phase": "complete"}

    def _parse_ai_response(self, content: str) -> dict | None:
        """解析AI返回的JSON"""
        import re
        try:
            # 尝试直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试提取JSON块
        m = re.search(r'\{[^{}]*"action"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        # 尝试更宽松的匹配
        m = re.search(r'\{.*"action"\s*:\s*"(complete|next|followup)"[^}]*\}', content, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj
            except json.JSONDecodeError:
                pass

        logger.warning(f"[Onboarding] AI返回无法解析: {content[:200]}...")
        return None

    async def generate_profile(self, session: OnboardingSession) -> dict:
        """对话完成后，生成商家档案和分析建议"""
        soldier = self._get_soldier()

        # 构建聊天记录文本
        chat_log_lines = []
        for m in session.history:
            role_label = "商家" if m["role"] == "user" else "AI"
            chat_log_lines.append(f"[{role_label}] {m['content']}")
        chat_log = "\n".join(chat_log_lines)

        prompt = PROFILE_GENERATION_PROMPT.format(
            chat_log=chat_log,
            store_type_name=session.store_type_name,
        )

        try:
            content, tokens = soldier.chat(
                system_prompt="你是一个帮县城小老板分析生意的AI顾问。说话接地气、实在、不整虚的。",
                user_message=prompt,
            )

            result = self._parse_ai_response(content)
            if result:
                return result
            else:
                # 返回兜底结果
                return {
                    "profile": {"store_name": "未提取", "industry": session.store_type_name},
                    "advice": "抱歉，AI分析暂时不可用，请稍后重试。",
                    "scores": {"score_location": 3, "score_product": 3, "score_customer": 3, "score_operation": 3, "score_potential": 3},
                    "raw_content": content,
                }
        except Exception as e:
            logger.error(f"[Onboarding] 档案生成失败: {e}")
            return {
                "profile": {"store_name": "未提取"},
                "advice": "抱歉，分析生成失败，请稍后重试。",
                "scores": {},
            }


# 全局单例
onboarding_manager = OnboardingManager()
