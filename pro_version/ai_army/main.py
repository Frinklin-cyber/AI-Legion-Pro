"""AI军团 - 指挥中心 FastAPI 服务 v3.0 (四层金字塔架构)

提供REST API供Dashboard调用，9名AI战士就位。
四层金字塔：行业基因库 → 全知感知网 → 因果决策脑 → 自主行动体
启动: python main.py
"""

import json

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Query, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from config.env import (
    DASHBOARD_HOST, DASHBOARD_PORT, CHROMA_PERSIST_DIR,
    ARM_COMMAND_API_KEY, ARM_AUTH_ENABLED,
)
from src.command.dispatcher import CommandDispatcher
from config.industry_genome import list_genomes, get_genome, get_loader, infer_genome_from_poi_type
# 智能定位引擎 v3.1（POI 搜索 → 地理编码 → 行政区降级）
from src.shop.geo import resolve_address_to_coord
# 对话式入驻向导 v1.0
from src.shop.onboarding import onboarding_manager
# 用户管理与数据隔离 v4.0
from src.admin.user_manager import (
    get_or_create_user, get_user, update_user_profile,
    get_all_users, is_admin, increment_user_record_count,
)
from src.auth.wechat import (
    jwt_required as _jwt_required, jwt_optional as _jwt_optional,
    get_openid_from_token,
)
from src.auth.merchant_auth import verify_token as verify_merchant_token
from src.db import async_session
from src.db.models import Merchant, BusinessData


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan 事件处理器"""
    # 启动时
    logger.info("🚀 AI军团指挥中心正在启动...")
    init_all_soldiers()
    init_knowledge_base()  # 后台线程运行，不阻塞
    init_scheduler()
    # 初始化数据库
    from src.db import init_db
    await init_db()
    logger.info("🗄️ 数据库已就绪")

    logger.info("-" * 50)
    logger.info("🎯 指挥中心就绪，全体战士待命！")
    yield
    # 关闭时
    global scheduler
    if scheduler:
        scheduler.stop()
    logger.info("👋 AI军团指挥中心已关闭")


app = FastAPI(
    title="AI军团指挥中心",
    description="企业AI改革加速引擎 - 四层金字塔AI-SOP商业操作系统",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====== 鉴权中间件 ======
@app.middleware("http")
async def api_key_auth_middleware(request: Request, call_next):
    """全局API Key鉴权检查。
    
    跳过白名单路径：GET /（Dashboard页面）、/static/（静态资源）、
    /api/status（健康检查）、/openapi.json（文档）。
    鉴权通过 X-API-Key 请求头 或 ?api_key= URL参数传递。
    """
    # 白名单：无需鉴权的路径
    whitelist_prefixes = ["/static/", "/openapi.json", "/docs", "/redoc"]
    path = request.url.path

    # Dashboard 页面和静态资源直接放行
    if request.method == "GET" and (path == "/" or any(path.startswith(p) for p in whitelist_prefixes)):
        return await call_next(request)

    # 健康检查接口也放行
    if path == "/api/status":
        return await call_next(request)

    # 微信登录接口放行（不需要 API Key）
    if path == "/api/auth/wx-login":
        return await call_next(request)

    # 小程序 Dashboard 摘要接口放行
    if path == "/api/dashboard/summary":
        return await call_next(request)

    # 商家数据管理接口放行（小程序用户录入数据）
    if path.startswith("/api/store/merchant-data"):
        return await call_next(request)

    # 经营诊断接口放行（小程序触发分析）
    if path == "/api/store/diagnosis":
        return await call_next(request)

    # 商家登录注册 API 放行
    if path.startswith("/auth/"):
        return await call_next(request)

    # 商家后台页面放行
    if request.method == "GET" and path in ("/login", "/dashboard", "/admin-login"):
        return await call_next(request)

    # 平台管理员 API 放行（自带 admin 认证）
    if path.startswith("/api/admin/"):
        return await call_next(request)

    # v2.0 编排引擎接口放行（内置可选租户认证：商家 JWT / 指挥中心双模式共用）
    if path.startswith("/api/v2/"):
        return await call_next(request)

    # 鉴权检查
    if ARM_AUTH_ENABLED:
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if api_key != ARM_COMMAND_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "未授权访问，缺少有效的 API Key。请在请求头中添加 X-API-Key，或通过 ?api_key=xxx 传参。"},
            )

    return await call_next(request)

# ====== 静态文件 ======
dashboard_dir = Path(__file__).parent / "src" / "command" / "dashboard"
if dashboard_dir.exists():
    app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static")

# ====== 商家管理系统路由 ======
from src.routers.auth_routes import router as auth_router
from src.routers.merchant_routes import router as merchant_dashboard_router
from src.routers.admin_routes import router as admin_router

app.include_router(auth_router)
app.include_router(merchant_dashboard_router)
app.include_router(admin_router)

# ====== Pro 版（AI 店长）增量层路由 ======
# 新增「主代理 + 编排引擎 + 质检/审批」三层，现有五大模块一行不改
from src.command.pro.routes import pro_router
app.include_router(pro_router)

# ====== v2.0 进阶版（多过程编排引擎）增量路由 ======
# 意图识别 → 画像补全 → 工具调用深度推理 → 多方案对比 → 执行指引
from src.orchestrator.routes import router as v2_router
app.include_router(v2_router)

# ====== 全局实例 ======
dispatcher = CommandDispatcher()
scheduler = None  # 延迟初始化
rag_engine = None  # 延迟初始化

# 战士引用
summarizer = None
data_analyst = None
content_creator = None
code_generator = None
quality_checker = None

# 店铺模块战士
store_manager = None    # 店长助理
customer_service = None # 智能客服
local_intel = None      # 本地情报官
attribution_analyzer = None  # 归因分析师


def init_all_soldiers():
    """初始化并注册全部9名AI战士"""
    global summarizer, data_analyst, content_creator, code_generator, quality_checker
    global store_manager, customer_service, local_intel, attribution_analyzer

    logger.info("=" * 50)
    logger.info("🎖️ AI军团 - 全体战士报到中...")
    logger.info("=" * 50)

    # 1. 侦察兵 - 情报摘要官
    try:
        from src.scouts.summarizer import IntelligenceSummarizer
        summarizer = IntelligenceSummarizer()
        dispatcher.register_soldier(summarizer)
    except Exception as e:
        logger.warning(f"⚠️ 侦察兵报到失败: {e}")

    # 2. 参谋 - 数据分析师
    try:
        from src.staff.data_agent import DataAnalyst
        data_analyst = DataAnalyst()
        dispatcher.register_soldier(data_analyst)
    except Exception as e:
        logger.warning(f"⚠️ 数据分析师报到失败: {e}")

    # 3. 特种 - 内容创作官
    try:
        from src.special_forces.content_gen import ContentCreator
        content_creator = ContentCreator()
        dispatcher.register_soldier(content_creator)
    except Exception as e:
        logger.warning(f"⚠️ 内容创作官报到失败: {e}")

    # 4. 特种 - 代码工程师
    try:
        from src.special_forces.code_gen import CodeGenerator
        code_generator = CodeGenerator()
        dispatcher.register_soldier(code_generator)
    except Exception as e:
        logger.warning(f"⚠️ 代码工程师报到失败: {e}")

    # 5. 指挥 - 质量审核官
    try:
        from src.command.quality_checker import QualityChecker
        quality_checker = QualityChecker()
        dispatcher.register_soldier(quality_checker)
    except Exception as e:
        logger.warning(f"⚠️ 质量审核官报到失败: {e}")

    # 6. 知识库 - 检索增强官 (RAG)
    try:
        from src.knowledge.rag_engine import RAGEngine
        global rag_engine
        rag_engine = RAGEngine()
        dispatcher.register_soldier(rag_engine)
    except Exception as e:
        logger.warning(f"⚠️ 检索增强官报到失败: {e}")

    # ====== 店铺管理模块（新增3名战士） ======
    # 7. 🏪 店长助理
    try:
        from src.shop.store_manager import StoreManager
        store_manager = StoreManager()
        dispatcher.register_soldier(store_manager)
    except Exception as e:
        logger.warning(f"⚠️ 店长助理报到失败: {e}")

    # 8. 💬 智能客服
    try:
        from src.shop.customer_service import CustomerService
        customer_service = CustomerService()
        dispatcher.register_soldier(customer_service)
    except Exception as e:
        logger.warning(f"⚠️ 智能客服报到失败: {e}")

    # 9. 📡 本地情报官
    try:
        from src.shop.competitor_monitor import LocalIntel
        local_intel = LocalIntel()
        dispatcher.register_soldier(local_intel)
    except Exception as e:
        logger.warning(f"⚠️ 本地情报官报到失败: {e}")

    # 10. 🔍 归因分析师（因果决策脑核心）
    try:
        from src.staff.attribution_analyzer import AttributionAnalyzer
        attribution_analyzer = AttributionAnalyzer()
        dispatcher.register_soldier(attribution_analyzer)
    except Exception as e:
        logger.warning(f"⚠️ 归因分析师报到失败: {e}")

    logger.info(f"🎯 最终报到人数: {len(dispatcher._soldiers)}/10 名战士")


def init_knowledge_base():
    """初始化知识库，添加示例文档（后台线程运行，不阻塞启动）"""
    global rag_engine
    if rag_engine is None:
        return

    def _init():
        try:
            from src.knowledge.vector_store import VectorStore
            store = VectorStore()

            status = store.get_status()
            if status["total_documents"] == 0:
                sample_docs = [
                    {
                        "text": (
                            "企业AI改革三步法：第一步诊断（找出效率瓶颈），第二步试点"
                            "（选一个环节做MVP），第三步推广（全公司复制）。关键成功因素包括："
                            "高层支持、员工培训、数据质量保障、持续迭代。"
                        ),
                        "meta": {"source": "AI改革方法论", "category": "方法", "author": "指挥官"},
                    },
                    {
                        "text": (
                            "DeepSeek-V3模型特点：671B参数MoE架构，支持128K上下文，"
                            "中文理解能力业界领先。API定价为输入1元/百万tokens，输出2元/百万tokens。"
                            "相比OpenAI GPT-4节省约95%成本，是中小企业AI化的最佳选择。"
                        ),
                        "meta": {"source": "DeepSeek技术文档", "category": "工具", "author": "侦察兵"},
                    },
                    {
                        "text": (
                            "自动化实施路径：第一步选择高重复低判断的任务（如数据录入、"
                            "邮件分类、信息收集），第二步引入RAG+LLM做知识问答，第三步端到端"
                            "流程自动化。每次只改造一个环节，验证效果后再扩展。"
                        ),
                        "meta": {"source": "自动化实施指南", "category": "方法", "author": "参谋部"},
                    },
                    {
                        "text": (
                            "AI内容创作最佳实践：1) 用衡水模式指导内容策略；"
                            "2) 长文控制在3000字以内，每500字一个信息锚点；"
                            "3) 短视频脚本：3秒钩子+15秒核心+5秒行动呼吁；"
                            "4) 朋友圈文案遵循FAB法则。"
                        ),
                        "meta": {"source": "内容创作规范", "category": "方法", "author": "特种兵"},
                    },
                    {
                        "text": (
                            "竞品分析框架：1) 产品维度：功能对比、用户体验、定价策略；"
                            "2) 市场维度：份额、增速、用户口碑；3) 技术维度：专利、团队、"
                            "技术栈；4) 制定对策：差异化定位、快速跟进、降维打击。"
                        ),
                        "meta": {"source": "竞品分析模板", "category": "方法", "author": "参谋部"},
                    },
                    {
                        "text": (
                            "AI代码生成规范：先写清晰需求描述再生成代码，生成后必须人工审查"
                            "逻辑正确性，使用类型注解提高质量，单元测试覆盖率需达80%以上。"
                        ),
                        "meta": {"source": "代码生成规范", "category": "规范", "author": "特种兵"},
                    },
                    {
                        "text": (
                            "企业微信机器人接入：在群设置中添加机器人获取Webhook URL，"
                            "支持文本/Markdown/图片/图文消息类型，每天最多20条。"
                        ),
                        "meta": {"source": "企业微信开发文档", "category": "工具", "author": "后勤兵"},
                    },
                    {
                        "text": (
                            "质量控制三层体系：第一层自动规则检查（长度、禁用词、格式完整性），"
                            "第二层AI评审（5维度打分），第三层人工抽检。低于60分需人工审核，"
                            "80分以上自动放行。"
                        ),
                        "meta": {"source": "质量控制标准", "category": "规范", "author": "指挥中心"},
                    },
                ]

                import uuid
                texts = [d["text"] for d in sample_docs]
                metas = [d["meta"] for d in sample_docs]
                ids_list = [str(uuid.uuid4())[:12] for _ in sample_docs]

                store.add_texts(texts, metas, ids_list)
                logger.info(f"📚 知识库初始化完成: 已添加 {len(sample_docs)} 篇示例文档")
            else:
                logger.info(f"📚 知识库已存在: {status['total_documents']} 篇文档, 跳过初始化")

        except Exception as e:
            logger.warning(f"⚠️ 知识库初始化失败: {e}")

    # 后台线程运行，避免ChromaDB模型下载阻塞服务启动
    import threading
    t = threading.Thread(target=_init, daemon=True, name="kb-init")
    t.start()
    logger.info("📚 知识库后台初始化中（首次需下载嵌入模型约79MB）...")


def init_scheduler():
    """初始化定时任务调度器"""
    global scheduler
    try:
        from src.logistics.task_scheduler import TaskScheduler, ScheduledTask

        scheduler = TaskScheduler()

        # 每日8点情报简报
        scheduler.add_task(ScheduledTask(
            name="daily_briefing",
            func=daily_briefing_job,
            trigger_type="cron",
            trigger_config={"cron": "0 8 * * *"},
            description="每日情报简报（8:00）",
        ))

        # # 每日18点工作总结
        # scheduler.add_task(ScheduledTask(
        #     name="daily_summary",
        #     func=daily_summary_job,
        #     trigger_type="cron",
        #     trigger_config={"cron": "0 18 * * *"},
        #     description="每日工作总结（18:00）",
        # ))

        # # 每4小时竞品监控
        # scheduler.add_task(ScheduledTask(
        #     name="competitor_check",
        #     func=competitor_check_job,
        #     trigger_type="interval",
        #     trigger_config={"hours": 4},
        #     description="竞品监控（每4小时）",
        # ))

        scheduler.start()
        logger.info("⏰ 定时任务调度器已启动")

        # Pro 版周期任务复用同一调度器
        from src.command.pro.scheduler_pro import bind_scheduler, restore_schedules
        bind_scheduler(scheduler)
        restore_schedules()  # 重启后自动恢复已启用的 Pro 周期任务
        logger.info("⏰ Pro 周期任务已绑定调度器")
    except Exception as e:
        logger.warning(f"⚠️ 调度器初始化失败: {e}")


# ====== 定时任务函数 ======
def daily_briefing_job():
    """每日情报简报定时任务"""
    from src.scouts.crawler import crawl_all
    from src.scouts.summarizer import IntelligenceSummarizer
    from src.scouts.push import push_briefing

    logger.info("[定时任务] 开始生成每日情报简报...")
    items = crawl_all()
    if items:
        s = IntelligenceSummarizer()
        result = s.execute({"items": items})
        push_briefing(result["briefing"])
        logger.info(f"[定时任务] 简报生成完成: {result['item_count']} 条情报")


def daily_summary_job():
    """每日工作总结"""
    logger.info("[定时任务] 生成每日工作总结...")


def competitor_check_job():
    """竞品监控"""
    logger.info("[定时任务] 执行竞品监控...")


# ====== Dashboard ======
@app.get("/")
async def root():
    """指挥中心面板"""
    html_path = dashboard_dir / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {"message": "AI军团指挥中心已启动", "version": "2.0.0"}


# ====== 商家管理页面 ======
@app.get("/login")
async def merchant_login_page():
    """商家登录/注册页面"""
    html_path = dashboard_dir / "login.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {"status": "error", "message": "页面未找到"}


@app.get("/dashboard")
async def merchant_dashboard_page():
    """商家管理后台"""
    html_path = dashboard_dir / "merchant_dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {"status": "error", "message": "页面未找到"}


@app.get("/merchant")
async def merchant_dashboard_alias():
    """商家管理后台（/merchant 别名）"""
    html_path = dashboard_dir / "merchant_dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {"status": "error", "message": "页面未找到"}


@app.get("/admin-login")
async def admin_login_page():
    """平台管理员后台"""
    html_path = dashboard_dir / "admin_dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {"status": "error", "message": "页面未找到"}


# ====== 全局状态 API ======
@app.get("/api/status")
async def get_status():
    """获取全局状态"""
    status = dispatcher.get_all_status()
    # 追加调度器状态
    if scheduler:
        status["scheduler"] = scheduler.get_status()
    # 追加知识库状态
    if rag_engine:
        try:
            status["knowledge"] = rag_engine.get_status()
        except Exception:
            status["knowledge"] = {"error": "获取失败"}
    # 追加行业基因组状态
    try:
        loader = get_loader()
        status["genome_count"] = loader.count()
    except Exception:
        status["genome_count"] = 0
    return status


@app.get("/api/missions")
async def get_missions(limit: int = Query(20, ge=1, le=100)):
    """获取任务列表"""
    status = dispatcher.get_all_status()
    missions = status.get("recent_missions", [])[-limit:]
    return {"total": status["missions_total"], "missions": missions}


@app.get("/api/soldiers")
async def get_soldiers():
    """获取所有AI战士信息"""
    return dispatcher.list_soldiers()


# ====== 情报简报 API ======
@app.post("/api/briefing/generate")
async def generate_briefing(
    store_type: str = Query("", description="店铺行业类型（可选），传入后AI将聚焦该行业情报"),
    store_name: str = Query("", description="店铺名称（可选），用于个性化行业上下文"),
    products: str = Query("", description="主营产品/服务（可选），用于精准聚焦"),
):
    """手动触发情报简报生成，支持行业聚焦。

    传入 store_type 后，AI 将根据行业特性筛选和解读情报。
    例如：餐饮行业 → 重点关注外卖平台、竞品营销、供应链等维度的情报。
    """
    try:
        from src.scouts.crawler import crawl_all
        from src.scouts.summarizer import IntelligenceSummarizer

        # 构建行业上下文
        industry_context = _build_industry_context(store_type, store_name, products)

        items = crawl_all()
        if not items:
            return {"status": "no_data", "message": "今日无新情报"}

        s = IntelligenceSummarizer()
        task: dict = {"items": items}
        if industry_context:
            task["focus_keywords"] = industry_context["keywords"]
            task["industry_context"] = industry_context["context"]
        result = s.execute(task)

        return {
            "status": "success",
            "briefing": result["briefing"],
            "item_count": result["item_count"],
            "tokens_used": result["tokens_used"],
            "industry": industry_context.get("name", "") if industry_context else "",
        }
    except Exception as e:
        logger.error(f"简报生成失败: {e}")
        return {"status": "error", "message": str(e)}


def _build_industry_context(store_type: str, store_name: str, products: str) -> dict | None:
    """根据店铺类型构建行业上下文，用于情报聚焦。（行业基因组驱动）

    Returns:
        dict: {name, keywords, context} 或 None
    """
    if not store_type:
        return None

    genome = get_genome(store_type)
    if genome.id == "custom" and store_type != "custom":
        return None

    competitor_focus = genome.competitor_focus
    marketing = genome.marketing_scenarios

    # 从竞品关注维度、营销场景、KPI中提取关键词
    keywords = list(competitor_focus) if competitor_focus else []
    for mkt in marketing[:3]:
        keywords.append(mkt.get("name", ""))
    for kpi_name in list(genome.kpi_formulas.keys())[:3]:
        keywords.append(kpi_name)

    # 去重去空
    keywords = list(set(filter(None, keywords)))

    # 构建行业上下文描述
    context_parts = [f"当前店铺行业: {genome.name}"]
    if store_name:
        context_parts.append(f"店铺名称: {store_name}")
    if products:
        context_parts.append(f"主营产品/服务: {products}")
    context_parts.append(f"竞品关注维度: {'、'.join(competitor_focus[:5])}" if competitor_focus else "")
    context_parts.append(f"核心KPI: {'、'.join(list(genome.kpi_formulas.keys())[:3])}")
    context_parts.append(f"营销场景: {'、'.join([m.get('name', '') for m in marketing[:3]])}" if marketing else "")

    return {
        "name": genome.name,
        "keywords": keywords,
        "context": " | ".join(filter(None, context_parts)),
    }


# ====== 内容创作 API ======
@app.post("/api/content/generate")
async def generate_content(content_type: str = Query("article"),
                           topic: str = Query(""),
                           audience: str = Query("通用"),
                           style: str = Query("专业")):
    """内容创作 API"""
    global content_creator
    if content_creator is None:
        return {"status": "error", "message": "内容创作官未就位"}

    try:
        task = {
            "type": content_type,
            "topic": topic or "AI如何助力企业效率提升",
            "target_audience": audience,
            "style": style,
        }

        result = content_creator.execute(task)
        return {
            "status": "success",
            "content": result.get("content", ""),
            "tokens_used": result.get("tokens_used", 0),
        }
    except Exception as e:
        logger.error(f"内容生成失败: {e}")
        return {"status": "error", "message": str(e)}


# ====== AI探店视频生成 API ======
@app.post("/api/video/explore/generate")
async def generate_explore_video(
    request: Request,
    store_name: str = Query(""),
    store_type: str = Query(""),
    store_desc: str = Query(""),
    style: str = Query("casual"),
    duration: str = Query("60"),
    images: str = Query("[]"),  # JSON array of base64 strings
):
    """AI探店视频生成：根据店铺信息和图片生成短视频脚本"""
    global content_creator
    if content_creator is None:
        return {"status": "error", "message": "内容创作官未就位"}

    try:
        from config.prompts.content_prompts import EXPLORE_VIDEO_PROMPT

        # 风格中文映射
        style_map = {
            "casual": "轻松探店风",
            "professional": "专业测评风",
            "story": "故事叙事风",
            "humor": "幽默搞笑风",
        }
        style_cn = style_map.get(style, style)

        # 构建用户消息
        user_msg = f"""店铺名称：{store_name}
店铺类型：{store_type or '未指定'}
店铺描述/主营产品：{store_desc}
视频风格：{style_cn}
视频时长：{duration}秒
"""
        
        # 获取本地区域上下文
        region_context_text = _get_region_context_for_diagnosis(
            await get_user_id_from_request(request) or ""
        )
        if region_context_text:
            user_msg += f"""
## 🌍 本地化上下文（系统获取的本地信息，请内化后自然融入脚本）
{region_context_text}

## 本地化要求
1. 脚本中自然地融入本地元素：地标、商圈、本地人熟悉的地名
2. 口播语言中体现本地特色表达方式
3. 不要生硬堆砌数据，要像本地探店博主一样自然地介绍
4. 让本地人看了觉得"这是我们这的"，外地人看了觉得"好地道"
"""

        # 如果有图片，简单描述（实际图片分析需多模态模型，这里提示用户上传了图片）
        try:
            img_list = json.loads(images) if images else []
        except Exception:
            img_list = []
        if img_list and len(img_list) > 0:
            user_msg += f"\n用户上传了 {len(img_list)} 张店铺图片（门头/环境/产品/服务等），请结合店铺类型和描述，在画面中合理想象图片内容。"

        system_prompt = EXPLORE_VIDEO_PROMPT

        # 调用内容创作官生成
        content, tokens = content_creator.chat(
            system_prompt,
            user_msg,
            temperature=0.85,  # 视频创作需要更高创意
            max_tokens=4000,
        )

        # 解析JSON结果
        result = {}
        try:
            # 尝试直接解析
            result = json.loads(content)
        except json.JSONDecodeError:
            # 如果返回有markdown代码块，提取JSON部分
            import re
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                # 尝试提取第一个 { ... } 块
                json_match = re.search(r'(\{.*\})', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(1))
                else:
                    raise ValueError("无法解析返回的JSON")

        return {
            "status": "success",
            "result": {
                "title": result.get("title", ""),
                "script": result.get("script", ""),
                "voiceover": result.get("voiceover", ""),
                "subtitles": result.get("subtitles", ""),
                "music": result.get("music", ""),
                "image_prompts": result.get("image_prompts", []),
            },
            "tokens_used": tokens,
        }
    except Exception as e:
        logger.error(f"探店视频生成失败: {e}")
        return {"status": "error", "message": f"生成失败: {str(e)}"}


# ====== 即梦配图生成 API ======
@app.post("/api/video/image/generate")
async def generate_video_image(
    prompt: str = Query(""),
    size: str = Query("2K"),
    watermark: bool = Query(True),
):
    """调用即梦/Doubao Seedream 模型生成探店视频配图"""
    if not prompt.strip():
        return {"status": "error", "message": "提示词不能为空"}

    try:
        from src.special_forces.image_gen import get_image_generator

        generator = get_image_generator()
        result = generator.generate(
            prompt=prompt.strip(),
            size=size,
            watermark=watermark,
        )
        return result
    except Exception as e:
        logger.error(f"配图生成失败: {e}")
        return {"status": "error", "message": f"生成失败: {str(e)}"}


# ====== 代码生成 API ======
@app.post("/api/code/generate")
async def generate_code(language: str = Query("python"),
                        requirement: str = Query("")):
    """代码生成 API"""
    global code_generator
    if code_generator is None:
        return {"status": "error", "message": "代码工程师未就位"}

    try:
        task = {
            "operation": "generate",
            "language": language,
            "requirement": requirement or "打印Hello World",
        }

        result = code_generator.execute(task)
        return {
            "status": "success",
            "code": result.get("code", result.get("content", "")),
            "tokens_used": result.get("tokens_used", 0),
        }
    except Exception as e:
        logger.error(f"代码生成失败: {e}")
        return {"status": "error", "message": str(e)}


# ====== 数据分析 API ======
@app.post("/api/data/analyze")
async def analyze_data(question: str = Query(""),
                       analysis_type: str = Query("general")):
    """数据分析 API"""
    global data_analyst
    if data_analyst is None:
        return {"status": "error", "message": "数据分析师未就位"}

    try:
        task = {
            "type": analysis_type,
            "question": question or "请分析当前数据趋势",
        }

        result = data_analyst.execute(task)
        return {
            "status": "success",
            "analysis": result.get("analysis", result.get("content", "")),
            "tokens_used": result.get("tokens_used", 0),
        }
    except Exception as e:
        logger.error(f"数据分析失败: {e}")
        return {"status": "error", "message": str(e)}


# ====== 质量审查 API ======
@app.post("/api/quality/review")
async def review_quality(content: str = Query(""),
                         content_type: str = Query("article"),
                         task_description: str = Query("")):
    """质量审查 API"""
    global quality_checker
    if quality_checker is None:
        return {"status": "error", "message": "质量审核官未就位"}

    try:
        if not content:
            return {"status": "error", "message": "请提供待审核内容"}

        result = quality_checker.review_output(
            content=content,
            task_type=content_type,
            task_description=task_description or "内容审查",
        )
        return {
            "status": "success",
            **result,
        }
    except Exception as e:
        logger.error(f"质量审查失败: {e}")
        return {"status": "error", "message": str(e)}


# ====== 知识库 API ======
@app.get("/api/knowledge/status")
async def knowledge_status():
    """获取知识库状态"""
    try:
        from src.knowledge.vector_store import VectorStore
        store = VectorStore()
        return store.get_status()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/knowledge/search")
async def knowledge_search(query: str = Query(""), top_k: int = Query(5)):
    """纯向量检索（不调AI）"""
    try:
        from src.knowledge.vector_store import VectorStore
        store = VectorStore()
        results = store.search(query, top_k)
        return {
            "query": query,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/knowledge/ask")
async def knowledge_ask(
    question: str = Query(""),
    top_k: int = Query(5),
    store_type: str = Query("", description="行业类型，用于加载行业基准对比"),
):
    """RAG增强问答（检索 + AI生成 + 行业基因组基准）"""
    global rag_engine
    if rag_engine is None:
        return {"status": "error", "message": "检索增强官未就位"}

    try:
        if not question:
            return {"status": "error", "message": "请提供问题"}

        result = rag_engine.execute({"question": question, "top_k": top_k, "store_type": store_type})
        return {
            "status": "success",
            "answer": result["answer"],
            "sources": result["sources"],
            "tokens_used": result["tokens_used"],
        }
    except Exception as e:
        logger.error(f"RAG问答失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/knowledge/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传文档到知识库"""
    try:
        from src.knowledge.vector_store import VectorStore

        content = await file.read()
        text = content.decode("utf-8", errors="ignore")

        if len(text.strip()) < 10:
            return {"status": "error", "message": "文件内容太少"}

        store = VectorStore()
        store.add_texts(
            texts=[text],
            metadata=[{"source": file.filename, "filename": file.filename}],
        )

        return {
            "status": "success",
            "message": f"文档 '{file.filename}' 已添加到知识库",
            "chars": len(text),
        }
    except Exception as e:
        logger.error(f"文档上传失败: {e}")
        return {"status": "error", "message": str(e)}


# ====== 调度器 API ======
@app.get("/api/scheduler/status")
async def scheduler_status():
    """获取调度器状态"""
    global scheduler
    if scheduler is None:
        return {"status": "inactive", "tasks": [], "message": "调度器未启动"}
    return {"status": "active", "tasks": scheduler.get_status()}


@app.post("/api/scheduler/pause")
async def scheduler_pause(task_name: str = Query("")):
    """暂停定时任务"""
    global scheduler
    if scheduler and task_name:
        ok = scheduler.pause_task(task_name)
        return {"status": "success" if ok else "error", "task": task_name}
    return {"status": "error", "message": "调度器未启动或任务名缺失"}


@app.post("/api/scheduler/resume")
async def scheduler_resume(task_name: str = Query("")):
    """恢复定时任务"""
    global scheduler
    if scheduler and task_name:
        ok = scheduler.resume_task(task_name)
        return {"status": "success" if ok else "error", "task": task_name}
    return {"status": "error", "message": "调度器未启动或任务名缺失"}


# ====== 店铺管理 API（实体店铺接入） ======

async def _get_merchant_config_from_db(tenant_id: str) -> dict | None:
    """从数据库读取商家配置（供指挥中心使用）"""
    try:
        from sqlalchemy import select
        async with async_session() as db:
            r = await db.execute(select(Merchant).where(Merchant.tenant_id == tenant_id))
            merchant = r.scalar_one_or_none()
            if not merchant:
                return None
            r2 = await db.execute(
                select(BusinessData).where(
                    BusinessData.tenant_id == tenant_id,
                    BusinessData.data_type == "store_info",
                )
            )
            store_info = r2.scalar_one_or_none()
            si = {}
            if store_info and store_info.content:
                try:
                    si = json.loads(store_info.content)
                except Exception:
                    pass
            return {
                "type": si.get("type", "custom"),
                "type_name": si.get("type_name", "自定义店铺"),
                "name": si.get("store_name", merchant.name),
                "products": si.get("products", ""),
                "address": si.get("address", merchant.region or ""),
                "hours": si.get("hours", "10:00-22:00"),
                "phone": si.get("phone", merchant.phone or ""),
                "location_feature": si.get("location_feature", ""),
                "faq_knowledge": si.get("faq_knowledge", ""),
                "latitude": si.get("latitude", 0) or si.get("lat", 0) or 0,
                "longitude": si.get("longitude", 0) or si.get("lng", 0) or 0,
                "search_radius": si.get("search_radius", 2000),
                "kpi_values": {},
            }
    except Exception:
        return None


# 店铺类型列表
@app.get("/api/store/types")
async def get_store_types():
    """获取全部可选店铺类型及配置（行业基因组驱动）"""
    try:
        genomes = list_genomes()
        for g in genomes:
            genome = get_genome(g["id"])
            g["kpi_count"] = len(genome.kpi_formulas)
            g["marketing_count"] = len(genome.marketing_scenarios)
            g["faq_count"] = len(genome.faq_templates)
            g["benchmark_ready"] = bool(genome.benchmarks)
        return {"status": "success", "types": genomes}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# 获取某类型详情
@app.get("/api/store/type/{store_type}")
async def get_store_type_detail(store_type: str):
    """获取指定店铺类型的完整配置（行业基因组驱动）"""
    try:
        genome = get_genome(store_type)
        if genome.id == "custom" and store_type != "custom":
            return {"status": "error", "message": f"未知店铺类型: {store_type}"}
        return {
            "status": "success",
            "type": store_type,
            "detail": {
                "name": genome.name,
                "icon": genome.icon,
                "description": genome.description,
                "subcategories": genome.subcategories,
                "kpi_formulas": {k: {"unit": v["unit"], "importance": v["importance"], "formula": v["formula"]} for k, v in genome.kpi_formulas.items()},
                "benchmarks": genome.benchmarks,
                "red_flags": genome.red_flags,
                "marketing_scenarios": genome.marketing_scenarios,
                "faq_templates": genome.faq_templates,
                "competitor_focus": genome.competitor_focus,
                "default_search_radius": genome.default_search_radius,
            },
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ========== 统一认证辅助函数（支持 JWT + X-API-Key）==========
async def get_user_id_from_request(request: Request) -> str | None:
    """优先 JWT 认证，无 JWT 时回退到 X-API-Key（网页版 Dashboard 使用）
    当 ARM_AUTH_ENABLED=False 时直接放行，返回默认用户标识。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        openid = get_openid_from_token(auth[7:])
        if openid:
            return openid
    # 鉴权关闭时直接放行（本地开发环境）
    if not ARM_AUTH_ENABLED:
        return "web_dashboard"
    # 无 JWT 时检查 X-API-Key（网页版）
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if api_key and api_key == ARM_COMMAND_API_KEY:
        return "web_dashboard"  # 网页版统一用户标识
    return None


# 获取/设置店铺配置
@app.get("/api/store/config")
async def get_store_config(request: Request):
    """【v5.0 商家后台统一】获取当前用户的店铺配置"""
    # 优先尝试从商家 JWT 获取租户配置
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        payload = verify_merchant_token(auth.split(" ", 1)[1])
        if payload and payload.get("tenant_id"):
            config = await _get_merchant_config_from_db(payload["tenant_id"])
            if config:
                return {"status": "success", "config": config}

    # 回退到原有逻辑（store_configs.json）
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未授权访问，请先登录或提供有效的 API Key"})
    global store_manager
    if store_manager is None:
        return {"status": "error", "message": "店长助理未就位"}
    return {"status": "success", "config": store_manager.get_config(user_id)}


@app.post("/api/store/config")
async def set_store_config(
    request: Request,
    store_type: str = Query(""),
    store_name: str = Query(""),
    products: str = Query(""),
    address: str = Query(""),
    hours: str = Query(""),
    phone: str = Query(""),
    location_feature: str = Query(""),
    faq_knowledge: str = Query(""),
    latitude: float = Query(0),
    longitude: float = Query(0),
    search_radius: int = Query(0),
):
    """【v5.0 商家后台统一】设置当前用户的店铺配置"""
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未授权访问，请先登录或提供有效的 API Key"})

    if store_manager is None:
        return {"status": "error", "message": "店长助理未就位"}

    try:
        from config.store_templates import get_store_type

        if not store_type:
            return {"status": "error", "message": "请选择店铺类型"}

        tpl = get_store_type(store_type)
        if tpl is None:
            return {"status": "error", "message": f"未知店铺类型: {store_type}"}

        config = {
            "type": store_type,
            "type_name": tpl["name"],
            "name": store_name or "我的店铺",
            "products": products,
            "address": address,
            "hours": hours or "10:00-22:00",
            "phone": phone,
            "location_feature": location_feature,
            "faq_knowledge": faq_knowledge,
            "latitude": latitude,
            "longitude": longitude,
            "search_radius": search_radius if search_radius > 0 else tpl.get("default_search_radius", 2000),
            "kpi_values": {},
        }

        result = store_manager.set_config(config, user_id)

        # 同步到商家数据库（如果有JWT）
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            payload = verify_merchant_token(auth.split(" ", 1)[1])
            if payload and payload.get("tenant_id"):
                try:
                    from sqlalchemy import select
                    async with async_session() as db:
                        tenant_id = payload["tenant_id"]
                        r = await db.execute(
                            select(BusinessData).where(
                                BusinessData.tenant_id == tenant_id,
                                BusinessData.data_type == "store_info",
                            )
                        )
                        store_info = r.scalar_one_or_none()
                        if store_info:
                            content = json.loads(store_info.content or "{}")
                        else:
                            content = {}
                            store_info = BusinessData(tenant_id=tenant_id, data_type="store_info")
                            db.add(store_info)
                        content.update({
                            "type": store_type,
                            "type_name": tpl["name"],
                            "store_name": store_name,
                            "products": products,
                            "address": address,
                            "hours": hours or "10:00-22:00",
                            "phone": phone,
                            "location_feature": location_feature,
                            "faq_knowledge": faq_knowledge,
                            "latitude": latitude,
                            "longitude": longitude,
                            "search_radius": search_radius if search_radius > 0 else tpl.get("default_search_radius", 2000),
                        })
                        store_info.content = json.dumps(content, ensure_ascii=False)
                        await db.commit()
                except Exception as e:
                    logger.warning(f"同步到商家数据库失败: {e}")

        # v4.0: 同步更新用户资料
        update_user_profile(user_id, store_type=store_type, store_name=store_name or "我的店铺")

        # v4.0: 同步配置到客服和情报官（多用户隔离）
        if customer_service:
            customer_service.set_config_for_user(config, user_id)
        if local_intel:
            local_intel.set_config_for_user(config, user_id)

        return {
            "status": "success",
            "message": f"店铺 '{store_name}' 配置成功！类型: {tpl['name']}",
            "config": result,
            "kpi_fields": tpl.get("kpi_fields", {}),
            "marketing_scenarios": tpl.get("marketing_scenarios", []),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ====== 对话式入驻向导 API（小老板友好版信息录入） ======

@app.post("/api/store/onboarding/start")
async def onboarding_start(
    request: Request,
    store_type: str = Query(""),
):
    """【v1.0】开启对话式入驻 - 选好行业后，AI用大白话跟你聊"""
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "请先登录"})

    if not store_type:
        return {"status": "error", "message": "请先选择你的店铺类型"}

    try:
        from config.store_templates import get_store_type
        tpl = get_store_type(store_type)
        if tpl is None:
            return {"status": "error", "message": f"不认识的店铺类型: {store_type}"}

        store_type_name = tpl.get("name", store_type)
        questions = onboarding_manager.get_questions(store_type)
        session = onboarding_manager.start_session(user_id, store_type, store_type_name)
        first_msg = onboarding_manager.get_first_message(store_type_name, questions)

        return {
            "status": "success",
            "session_id": session.session_id,
            "message": first_msg,
            "total_questions": len(questions),
            "phase": session.phase,
            "store_type_name": store_type_name,
        }
    except Exception as e:
        logger.error(f"入驻启动失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/store/onboarding/chat")
async def onboarding_chat(
    request: Request,
    message: str = Query("", description="商家说的话（用口语随便说）"),
):
    """【v1.0】对话式入驻 - 商家说一句，AI回应+问下一个问题"""
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "请先登录"})

    session = onboarding_manager.get_session(user_id)
    if not session:
        return {"status": "error", "message": "对话还没开始，请先调用 /onboarding/start"}

    if not message.strip():
        return {"status": "error", "message": "请输入你想说的话"}

    try:
        result = await onboarding_manager.process_message(user_id, message.strip(), session)

        response = {
            "status": "success",
            "session_id": session.session_id,
            "message": result.get("message", ""),
            "phase": session.phase,
            "history_count": len(session.history),
        }

        # 如果对话完成，自动生成档案和分析
        if result.get("next_phase") == "complete":
            session.phase = 2
            profile = await onboarding_manager.generate_profile(session)
            response["phase"] = 2
            response["profile"] = profile.get("profile", {})
            response["advice"] = profile.get("advice", "")
            response["scores"] = profile.get("scores", {})

            # 自动保存为店铺配置
            try:
                await _save_onboarding_config(user_id, profile)
                response["config_saved"] = True
            except Exception as e:
                logger.warning(f"自动保存店铺配置失败: {e}")
                response["config_saved"] = False

            # 清理会话
            onboarding_manager.end_session(user_id)

        return response
    except Exception as e:
        logger.error(f"入驻对话处理失败: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/store/onboarding/complete")
async def onboarding_complete(request: Request):
    """【v1.0】手动完成入驻对话，立即生成档案"""
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "请先登录"})

    session = onboarding_manager.get_session(user_id)
    if not session:
        return {"status": "error", "message": "没有进行中的对话"}

    try:
        session.phase = 2
        profile = await onboarding_manager.generate_profile(session)

        # 自动保存
        try:
            await _save_onboarding_config(user_id, profile)
            config_saved = True
        except Exception as e:
            logger.warning(f"自动保存失败: {e}")
            config_saved = False

        onboarding_manager.end_session(user_id)

        return {
            "status": "success",
            "profile": profile.get("profile", {}),
            "advice": profile.get("advice", ""),
            "scores": profile.get("scores", {}),
            "config_saved": config_saved,
        }
    except Exception as e:
        logger.error(f"入驻完成失败: {e}")
        return {"status": "error", "message": str(e)}


async def _save_onboarding_config(user_id: str, profile: dict) -> None:
    """从入驻对话中自动提取并保存店铺配置"""
    global store_manager, customer_service, local_intel

    p = profile.get("profile", profile)
    store_name = p.get("store_name", "") or p.get("名称", "") or "我的店铺"
    industry = p.get("industry", "") or p.get("做什么的", "")

    # 尝试从产品和描述推断行业类型
    products = industry
    address = p.get("address", "") or p.get("在哪里", "") or ""

    # 构建FAQ知识
    faq_parts = []
    for key in ["scale", "history", "customer_profile", "competition", "pain_points"]:
        val = p.get(key, "")
        if val:
            if isinstance(val, list):
                faq_parts.append(f"- {key}: {', '.join(val)}")
            else:
                faq_parts.append(f"- {key}: {val}")
    faq_knowledge = f"（由AI入驻对话自动提取）\n" + "\n".join(faq_parts) if faq_parts else ""

    config = {
        "name": store_name,
        "products": products,
        "address": address,
        "hours": "10:00-22:00",
        "phone": "",
        "location_feature": "",
        "faq_knowledge": faq_knowledge,
    }

    if store_manager:
        # 检查是否已有 type 配置
        existing = store_manager.get_config(user_id)
        if existing and existing.get("type"):
            config["type"] = existing["type"]
            config["type_name"] = existing.get("type_name", "")
        else:
            config["type"] = "custom"
            config["type_name"] = "自定义店铺"

        store_manager.set_config(config, user_id)

        if customer_service:
            customer_service.set_config_for_user(config, user_id)
        if local_intel:
            local_intel.set_config_for_user(config, user_id)


# 智能客服问答
@app.post("/api/store/chat")
async def store_chat(question: str = Query("")):
    """顾客咨询问答（AI智能客服）"""
    global customer_service
    if customer_service is None:
        return {"status": "error", "message": "智能客服未就位"}

    if not question:
        return {"status": "error", "message": "请输入顾客问题"}

    try:
        result = customer_service.execute({"type": "chat", "question": question})
        return result
    except Exception as e:
        logger.error(f"客服问答失败: {e}")
        return {"status": "error", "message": str(e)}


# 店员知识问答
@app.post("/api/store/staff-question")
async def store_staff_qa(question: str = Query("")):
    """店员知识问答（含知识库检索）"""
    global customer_service
    if customer_service is None:
        return {"status": "error", "message": "智能客服未就位"}

    if not question:
        return {"status": "error", "message": "请输入问题"}

    try:
        result = customer_service.execute({"type": "staff_qa", "question": question})
        return result
    except Exception as e:
        logger.error(f"店员问答失败: {e}")
        return {"status": "error", "message": str(e)}


# 批量FAQ生成
@app.post("/api/store/batch-faq")
async def store_batch_faq():
    """根据店铺类型自动批量生成常见FAQ"""
    global customer_service
    if customer_service is None:
        return {"status": "error", "message": "智能客服未就位"}

    try:
        result = customer_service.execute({"type": "batch"})
        return result
    except Exception as e:
        logger.error(f"批量FAQ生成失败: {e}")
        return {"status": "error", "message": str(e)}


# 经营分析
@app.post("/api/store/analyze")
async def store_analyze(data: str = Query(""), question: str = Query("")):
    """店铺经营数据分析"""
    global store_manager
    if store_manager is None:
        return {"status": "error", "message": "店长助理未就位"}

    if not data and not question:
        return {"status": "error", "message": "请提供经营数据或分析问题"}

    try:
        result = store_manager.execute({
            "type": "analyze",
            "data": data,
            "question": question,
        })
        return result
    except Exception as e:
        logger.error(f"经营分析失败: {e}")
        return {"status": "error", "message": str(e)}


# 经营日报
@app.post("/api/store/daily-report")
async def store_daily_report(
    data: str = Query(""),
    weather: str = Query("未知"),
    date: str = Query(""),
):
    """生成店铺每日经营日报"""
    global store_manager
    if store_manager is None:
        return {"status": "error", "message": "店长助理未就位"}

    try:
        result = store_manager.execute({
            "type": "daily_report",
            "data": data,
            "weather": weather,
            "date": date,
        })
        return result
    except Exception as e:
        logger.error(f"日报生成失败: {e}")
        return {"status": "error", "message": str(e)}


# 营销内容生成
@app.post("/api/store/marketing")
async def store_marketing(
    scenario: str = Query(""),
    topic: str = Query(""),
    audience: str = Query("周边顾客"),
    channel: str = Query("朋友圈"),
):
    """生成店铺营销内容"""
    global store_manager
    if store_manager is None:
        return {"status": "error", "message": "店长助理未就位"}

    try:
        result = store_manager.execute({
            "type": "marketing",
            "scenario": scenario,
            "topic": topic,
            "audience": audience,
            "channel": channel,
        })
        return result
    except Exception as e:
        logger.error(f"营销内容生成失败: {e}")
        return {"status": "error", "message": str(e)}


# ── 核心诊断 API（四层金字塔输出）──
@app.post("/api/store/diagnosis")
async def store_diagnosis(
    request: Request,
    data: str = Query("", description="经营数据（JSON字符串或自由文本）"),
    store_type: str = Query("", description="行业类型"),
    file: UploadFile | None = None,
):
    """【v4.0 用户隔离】四层金字塔诊断（仅使用该商家自己的历史数据做对比）

    返回 DiagnosisResponse 五步法格式：
    observation → attribution → recommendation → expected_impact → action_items
    """
    # JWT 鉴权（必须登录才能诊断）
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未登录，请先使用微信授权登录或提供有效 API Key"})

    global attribution_analyzer, rag_engine

    try:
        genome = get_genome(store_type)
    except Exception:
        genome = get_genome("custom")

    # 1. 数据解析（感知网）
    kpi_snapshots: list[dict] = []
    red_flags: list[dict] = []
    kpi_values_for_redflag: dict[str, Any] = {}  # 供红线和历史对比用

    if file:
        try:
            from src.scouts.data_parser import DataParser
            parser = DataParser(store_type or "custom")
            content = await file.read()
            df, report = parser.parse_bytes(file.filename or "upload", content)
            validation = parser.validate_against_genome(df)
            kpi_snapshots = validation.get("kpi_snapshots", [])
            red_flags = validation.get("red_flags_triggered", [])
            # 同时填充 kpi_values_for_redflag（供历史对比）
            for s in kpi_snapshots:
                if s.get("actual") not in (None, "", 0):
                    try:
                        kpi_values_for_redflag[s["name"]] = float(s["actual"])
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning(f"数据文件解析失败: {e}")

    # 2. 如果提供了纯文本数据，解析 KPI 值并做基准对比
    if not kpi_snapshots and data:
        kpi_data = _parse_input_data(data, genome)
        if kpi_data:
            # 用户提供了真实的 KPI 数据 → 做基准对比
            for name, info in genome.kpi_formulas.items():
                actual = kpi_data.get(name)
                if actual is not None:
                    actual_num = _coerce_number(actual)
                    benchmark = genome.get_benchmark(name, "average") or genome.get_benchmark(name, "mid")
                    comparison = genome.benchmark_comparison(name, actual_num) if benchmark else "无行业基准"
                    kpi_snapshots.append({
                        "name": name,
                        "actual": actual_num if isinstance(actual_num, (int, float)) else actual,
                        "unit": info.get("unit", ""),
                        "benchmark": benchmark,
                        "comparison_text": comparison,
                    })
                    kpi_values_for_redflag[name] = float(actual_num) if isinstance(actual_num, (int, float)) else 0
                else:
                    # 用户没填的 KPI → 不创建零值快照，防止误导
                    kpi_snapshots.append({
                        "name": name,
                        "actual": None,
                        "unit": info.get("unit", ""),
                        "benchmark": genome.get_benchmark(name, "average"),
                        "comparison_text": "未提供（建议补充）",
                    })
            # 用实际数据检查红线
            if kpi_values_for_redflag:
                try:
                    red_flags = genome.check_red_flags(kpi_values_for_redflag)
                except Exception:
                    logger.warning("红线检查失败", exc_info=True)
        else:
            # 完全无法解析 → 回退到全零提示（旧行为）
            kpi_snapshots = [
                {"name": name, "actual": 0, "unit": info.get("unit", ""),
                 "benchmark": genome.get_benchmark(name, "average"),
                 "comparison_text": "请上传数据文件或手动填入KPI以获取精确对比"}
                for name, info in genome.kpi_formulas.items()
            ]

    # 3. 归因分析（因果决策脑）—— 附加历史对比上下文
    diagnosis = None
    if attribution_analyzer and kpi_snapshots:
        try:
            # 加载历史记录，构建"当天 vs 以往"的对比上下文
            daily_context = _build_daily_context(kpi_values_for_redflag, genome, user_id)
            trend_text = (data if data else "") + "\n" + daily_context if daily_context else (data or "")

            diagnosis = attribution_analyzer.build_diagnosis(
                store_type=store_type or "custom",
                kpi_snapshots=kpi_snapshots,
                red_flags=red_flags,
                trend_data=trend_text,
                region_context=_get_region_context_for_diagnosis(user_id),
            )
        except Exception as e:
            logger.error(f"归因分析失败: {e}")

    # 4. 如果归因分析师未就位或LLM调用失败，构建基本诊断
    if diagnosis is None:
        from src.models.schemas import DiagnosisResponse
        obs_parts = []
        for s in kpi_snapshots:
            actual_str = f"{s['actual']}{s.get('unit','')}" if s.get('actual') is not None else "未提供"
            obs_parts.append(f"- {s['name']}: {actual_str}，{s.get('comparison_text','暂无对比数据')}")

        # 加入历史对比（如果有）
        daily_ctx = _build_daily_context(kpi_values_for_redflag, genome, user_id)
        attr_text = daily_ctx if daily_ctx else "需要更多数据维度进行根因分析（建议上传Excel/CSV经营数据）"

        has_data = any(s.get("actual") not in (None, 0, "") for s in kpi_snapshots)
        if has_data:
            rec_text = "已基于您的数据完成行业基准对比。如需AI深度归因分析，请确保LLM API配置正确（当前回退到基础诊断模式）。"
            expected_text = "请结合行业基准和历史数据评估改进空间"
            actions = [
                "对照行业基准，锁定最需改进的1-2个指标",
                "对比历史趋势，关注异常变化的指标",
                "将上述发现转化为当天的具体运营调整",
            ]
        else:
            rec_text = "请填写KPI数据（如日营收、客单价等），或上传经营数据文件，系统将自动进行行业基准对比和归因分析"
            expected_text = "待数据上传后可量化预期收益"
            actions = ["上传Excel/CSV经营数据文件", "确保列名与行业KPI名称匹配"]

        if not obs_parts:
            obs_parts = ["请填写KPI数据或上传经营数据文件以获取诊断"]

        diagnosis = DiagnosisResponse(
            observation="\n".join(obs_parts),
            attribution=attr_text,
            recommendation=rec_text,
            expected_impact=expected_text,
            action_items=actions,
            benchmarks_used={},
            red_flags_triggered=red_flags,
        )

    return {
        "status": "success",
        "diagnosis": diagnosis.model_dump(),
        "kpi_snapshots": kpi_snapshots,
        "red_flags_triggered": red_flags,
        "industry": genome.name,
        "industry_id": genome.id,
    }


# 竞品监控
@app.post("/api/store/competitor")
async def store_competitor(request: Request, data: str = Query(""), question: str = Query("")):
    """竞品情报分析"""
    global local_intel
    if local_intel is None:
        return {"status": "error", "message": "本地情报官未就位"}

    try:
        result = local_intel.execute({
            "type": "analyze",
            "data": data,
            "question": question,
            "user_id": await get_user_id_from_request(request) or "",
        })
        return result
    except Exception as e:
        logger.error(f"竞品分析失败: {e}")
        return {"status": "error", "message": str(e)}


# 竞品监控清单
@app.get("/api/store/competitor/watchlist")
async def store_watchlist(request: Request):
    """获取竞品监控清单"""
    global local_intel
    if local_intel is None:
        return {"status": "error", "message": "本地情报官未就位"}

    try:
        result = local_intel.execute({
            "type": "watchlist",
            "user_id": await get_user_id_from_request(request) or "",
        })
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


# 周边竞品搜索
@app.post("/api/store/competitor/search")
async def store_competitor_search(
    request: Request,
    latitude: float = Query(0),
    longitude: float = Query(0),
    radius: int = Query(0),
    store_type: str = Query(""),
    products: str = Query(""),
    subcategory: str = Query(""),
):
    """基于定位搜索周边竞品

    支持传入行业类型(store_type)、主营产品(products)、细分品类(subcategory)，
    让AI自动识别行业并生成针对性的竞品分析报告。
    """
    global local_intel
    if local_intel is None:
        return {"status": "error", "message": "本地情报官未就位"}

    try:
        task = {"type": "search_nearby"}
        if latitude:
            task["latitude"] = latitude
        if longitude:
            task["longitude"] = longitude
        if radius > 0:
            task["radius"] = radius
        if store_type:
            task["store_type"] = store_type
        if products:
            task["products"] = products
        if subcategory:
            task["subcategory"] = subcategory
        task["user_id"] = await get_user_id_from_request(request) or ""

        result = local_intel.execute(task)
        return result
    except Exception as e:
        logger.error(f"周边竞品搜索失败: {e}")
        return {"status": "error", "message": str(e)}


# 手动竞品输入（用户实地观察后录入）
@app.post("/api/store/competitor/manual")
async def store_competitor_manual(
    request: Request,
    competitors: str = Query(""),
    store_type: str = Query(""),
    products: str = Query(""),
    subcategory: str = Query(""),
):
    """手动输入周边商家，AI 基于真实观察做竞品分析

    参数:
        competitors: 用户实地观察的商家列列表，用换行分隔，每行格式:
                     商家名称，类型，距离，人均，备注
    """
    global local_intel
    if local_intel is None:
        return {"status": "error", "message": "本地情报官未就位"}

    try:
        task: dict = {
            "type": "search_nearby_manual",
            "competitors": competitors,
        }
        if store_type:
            task["store_type"] = store_type
        if products:
            task["products"] = products
        if subcategory:
            task["subcategory"] = subcategory
        task["user_id"] = await get_user_id_from_request(request) or ""

        result = local_intel.execute(task)
        return result
    except Exception as e:
        logger.error(f"手动竞品分析失败: {e}")
        return {"status": "error", "message": str(e)}


# ====== 品牌联想搜索 (v3.2) ======

_brands_data: dict | None = None


def _load_brands() -> dict:
    """懒加载品牌数据库"""
    global _brands_data
    if _brands_data is not None:
        return _brands_data
    path = Path(__file__).parent / "data" / "brands.json"
    if path.exists():
        try:
            _brands_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _brands_data = {}
    else:
        _brands_data = {}
    return _brands_data


@app.get("/api/store/brand-suggest")
async def brand_suggest(
    q: str = Query("", description="搜索关键词（如：茶、蜜雪、kfc）"),
    store_type: str = Query("", description="行业类型（可选，如：restaurant）"),
    limit: int = Query(8, description="返回结果数量上限"),
):
    """品牌联想搜索，支持中文/拼音/英文模糊匹配。

    输入 "茶" → 返回 茶百道、茶颜悦色、喜茶、奈雪的茶 等
    输入 "kfc" → 返回 肯德基
    输入 "蜜雪" → 返回 蜜雪冰城
    """
    if not q or len(q.strip()) < 1:
        return {"status": "success", "suggestions": [], "query": q}

    brands = _load_brands()
    query = q.strip().lower()

    # 确定搜索范围：指定行业则只搜该行业，否则搜全部
    search_pools: list[tuple[str, list]] = []
    if store_type and store_type in brands:
        search_pools.append((store_type, brands[store_type]))
    else:
        for k, v in brands.items():
            if isinstance(v, list):
                search_pools.append((k, v))

    # 三级匹配打分
    scored: list[dict] = []
    for industry, brand_list in search_pools:
        for brand in brand_list:
            name = brand.get("name", "")
            alias_list = brand.get("alias", [])
            all_names = [name] + alias_list

            score = 0
            match_type = ""

            # 精确匹配（名称或别名完全相等）→ 最高分
            for n in all_names:
                if n.lower() == query:
                    score = 100
                    match_type = "exact"
                    break

            # 前缀匹配（"茶" → "茶百道"）→ 高分
            if score == 0:
                for n in all_names:
                    if n.lower().startswith(query):
                        score = 80
                        match_type = "prefix"
                        break

            # 包含匹配（"雪" → "蜜雪冰城"）→ 中分
            if score == 0:
                for n in all_names:
                    if query in n.lower():
                        score = 60
                        match_type = "contains"
                        break

            # 拼音/英文别名匹配 → 中低分
            if score == 0:
                for n in all_names:
                    n_lower = n.lower()
                    # 逐字匹配拼音首字母
                    if len(query) >= 2 and all(c in n_lower for c in query):
                        score = 40
                        match_type = "fuzzy"
                        break

            if score > 0:
                scored.append({
                    "name": name,
                    "alias": alias_list,
                    "category": brand.get("category", ""),
                    "scale": brand.get("scale", ""),
                    "features": brand.get("features", ""),
                    "industry": industry,
                    "score": score,
                    "match_type": match_type,
                })

    # 按分数降序，取前 limit 条
    scored.sort(key=lambda x: x["score"], reverse=True)
    suggestions = scored[:limit]

    return {
        "status": "success",
        "suggestions": suggestions,
        "query": q,
        "count": len(suggestions),
    }


# ====== 商家数据录入与历史管理 (v3.1) ======

import threading

_merchant_data_path = Path(__file__).parent / "data" / "merchant_data.json"
_merchant_data_lock = threading.Lock()  # 文件读写锁，防止并发写冲突


def _load_merchant_data() -> list[dict]:
    """加载商家历史经营数据（线程安全）"""
    if not _merchant_data_path.exists():
        return []
    try:
        return json.loads(_merchant_data_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_merchant_data(records: list[dict]):
    """持久化商家经营数据到文件（线程安全）"""
    _merchant_data_path.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再原子替换，防止写入中断导致数据损坏
    tmp_path = _merchant_data_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(_merchant_data_path)


@app.post("/api/store/merchant-data")
async def save_merchant_data(
    request: Request,
    store_type: str = Query("", description="行业类型"),
    period_label: str = Query("", description="数据周期标签（如：2024年7月、开业首月）"),
    period_start: str = Query("", description="数据起始日期 YYYY-MM-DD"),
    period_end: str = Query("", description="数据截止日期 YYYY-MM-DD"),
    description: str = Query("", description="阶段备注（如：夏季促销期间）"),
    kpi_data: str = Query("", description="KPI数据 JSON字符串，如 {\"日营收\":3500,\"客单价\":68,...}"),
    raw_input_data: str = Query("", description="原始输入数据 JSON，如 {\"翻台率\":{\"总桌数\":10,\"总批次数\":25}}"),
    file: UploadFile | None = None,
):
    """【v4.0 用户隔离】保存商家经营数据，自动关联当前用户。

    需要 Bearer Token 鉴权，数据将绑定到当前用户。
    """
    import uuid

    # JWT 鉴权（必须登录）
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未登录，请先使用微信授权登录或提供有效 API Key"})

    record: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "user_id": user_id,
        "store_type": store_type,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "description": description,
        "kpi_values": {},
        "raw_inputs": {},
        "created_at": "",
        "has_file": False,
        "file_name": "",
    }

    # 解析结构化 KPI 数据
    if kpi_data:
        try:
            parsed = json.loads(kpi_data)
            record["kpi_values"] = {k: _coerce_number(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError):
            # 尝试用简单 kv 对解析（如 "营收=3500,客单价=68"）
            record["kpi_values"] = _parse_kv_text(kpi_data)

    # 解析原始输入数据
    if raw_input_data:
        try:
            record["raw_inputs"] = json.loads(raw_input_data)
        except (json.JSONDecodeError, TypeError):
            pass

    # 处理文件上传
    if file:
        record["has_file"] = True
        record["file_name"] = file.filename or "upload"
        try:
            from src.scouts.data_parser import DataParser
            parser = DataParser(store_type or "custom")
            content = await file.read()
            df, report = parser.parse_bytes(record["file_name"], content)
            validation = parser.validate_against_genome(df)
            # 提取最后一行的 KPI 快照值
            for snap in validation.get("kpi_snapshots", []):
                if snap.get("actual") not in (None, "", 0):
                    record["kpi_values"][snap["name"]] = _coerce_number(snap["actual"])
        except Exception as e:
            logger.warning(f"文件解析失败: {e}")

    # 时间戳
    from datetime import datetime
    record["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 持久化（加锁防并发写冲突）
    with _merchant_data_lock:
        records = _load_merchant_data()
        records.insert(0, record)  # 最新在前
        _save_merchant_data(records)

    # 更新用户资料和数据计数
    if store_type:
        update_user_profile(user_id, store_type=store_type)
    increment_user_record_count(user_id)

    # KPI 数量统计
    kpi_count = len(record["kpi_values"])
    return {
        "status": "success",
        "message": f"已保存 '{period_label or '数据记录'}'（{kpi_count} 项 KPI）",
        "record": record,
    }


def _coerce_number(v: Any) -> float | int | str:
    """将值转为数值，失败返回原值"""
    if isinstance(v, (int, float)):
        return v
    try:
        s = str(v).replace(",", "").replace("，", "").replace("元", "").replace("%", "").replace("人", "").strip()
        if "." in s:
            return float(s)
        return int(s)
    except (ValueError, TypeError):
        return v if v else 0


def _parse_kv_text(text: str) -> dict[str, Any]:
    """从 '营收=3500,客单价=68,翻台率=2.5' 格式解析"""
    result: dict[str, Any] = {}
    for part in text.replace("\n", ",").replace(";", ",").replace("；", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = _coerce_number(v.strip())
        elif "：" in part:
            k, v = part.split("：", 1)
            result[k.strip()] = _coerce_number(v.strip())
        elif ":" in part:
            k, v = part.split(":", 1)
            result[k.strip()] = _coerce_number(v.strip())
    return result


def _parse_input_data(data: str, genome: Any) -> dict[str, Any]:
    """解析用户输入的 KPI 数据（支持 JSON 和 key=value 两种格式）

    Args:
        data: JSON 字符串（如 '{"日营收":3500,"客单价":68}'）或 key=value 文本
        genome: 行业基因组对象，用于 KPI 名称模糊匹配

    Returns:
        {"日营收": 3500, "客单价": 68} 或空 dict（无法解析）
    """
    if not data or not data.strip():
        return {}

    data = data.strip()

    # 尝试 JSON 解析
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    # 尝试 URL 解码后再 JSON 解析（可能经过 URL 编码）
    if parsed is None:
        from urllib.parse import unquote
        try:
            parsed = json.loads(unquote(data))
        except (json.JSONDecodeError, TypeError):
            parsed = None

    if isinstance(parsed, dict) and parsed:
        # JSON 格式 → 用行业 KPI 定义做名称模糊匹配
        result: dict[str, Any] = {}
        kpi_names = list(genome.kpi_formulas.keys()) if genome else []
        for key, val in parsed.items():
            matched = None
            # 精确匹配
            if key in genome.kpi_formulas:
                matched = key
            else:
                # 模糊匹配（用户可能用简称）
                for kpi in kpi_names:
                    if key in kpi or kpi in key:
                        matched = kpi
                        break
            result[matched or key] = val
        return result

    # 回退到 key=value 文本解析
    return _parse_kv_text(data)


def _get_region_context_for_diagnosis(user_id: str) -> str:
    """从店铺配置中提取区域上下文，供诊断分析使用"""
    try:
        from src.shop.region_enricher import enrich_region_sync, _extract_region_name
        from src.shop.store_manager import _extract_city_from_address
        
        global store_manager
        if store_manager is None:
            return ""
        
        cfg = store_manager.get_config(user_id)
        if not cfg:
            return ""
        
        address = cfg.get("address", "")
        city = _extract_city_from_address(address) if address else ""
        region_name = _extract_region_name(address, city)
        
        if not region_name:
            return ""
        
        ctx = enrich_region_sync(
            region_name=region_name,
            store_type=cfg.get("type", ""),
            products=cfg.get("products", ""),
            use_cache=True,
        )
        if ctx and not ctx.is_empty:
            return ctx.to_prompt_string()
    except Exception:
        pass
    return ""


def _build_daily_context(kpi_values: dict[str, Any], genome: Any, user_id: str = "") -> str:
    """【v4.0 用户隔离】仅加载当前用户的历史记录，构建当下 vs 过去的对比上下文。

    用于 AI 诊断时提供"当天表现 vs 自己过去表现"的对比维度。
    """
    if not kpi_values:
        return ""

    records = _load_merchant_data()
    if not records:
        return ""

    # v4.0: 仅使用当前用户的历史数据
    if user_id:
        records = [r for r in records if r.get("user_id") == user_id]

    if not records:
        return ""

    # 取最近 3 条历史记录用于对比
    recent = records[:3]

    lines: list[str] = [
        "\n## 历史对比上下文（当天 vs 该商家以往数据）",
        f"该商家共有 {len(records)} 条历史经营数据记录，以下为最近 {min(3, len(recent))} 期对比：",
    ]

    for i, rec in enumerate(recent):
        prev_kpi = rec.get("kpi_values", {})
        if not prev_kpi:
            continue
        period = rec.get("period_label", "未命名")
        changes: list[str] = [f"**{period}**"]
        has_change = False
        for kpi_name, current_val in kpi_values.items():
            if kpi_name in prev_kpi:
                try:
                    prev_val = float(prev_kpi[kpi_name])
                    cur_val = float(current_val)
                    if prev_val != 0:
                        delta_pct = round((cur_val - prev_val) / prev_val * 100, 1)
                        dir_char = "↑" if delta_pct > 0 else ("↓" if delta_pct < 0 else "→")
                        changes.append(f"  {kpi_name}: {cur_val} vs {prev_val} ({dir_char}{abs(delta_pct)}%)")
                        has_change = True
                except (ValueError, TypeError):
                    pass
        if has_change:
            lines.append("\n".join(changes))

    if len(lines) <= 3:  # 只有标题行，没有实际对比
        return ""

    return "\n".join(lines) + "\n\n请结合以上历史对比，分析当前数据的表现趋势和异常变化。"


@app.get("/api/store/merchant-data/history")
async def get_merchant_data_history(
    request: Request,
    store_type: str = Query("", description="按行业类型筛选（可选）"),
    limit: int = Query(50, description="返回记录数上限"),
):
    """【v4.0 用户隔离】获取当前用户的商家历史经营数据列表"""
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未登录，请先使用微信授权登录或提供有效 API Key"})
    records = _load_merchant_data()
    # 仅返回当前用户的数据
    records = [r for r in records if r.get("user_id") == user_id]
    if store_type:
        records = [r for r in records if r.get("store_type") == store_type]
    return {
        "status": "success",
        "count": len(records[:limit]),
        "total": len(records),
        "records": records[:limit],
    }


@app.delete("/api/store/merchant-data/{record_id}")
async def delete_merchant_data(record_id: str, request: Request):
    """【v4.0 用户隔离】删除指定商家数据记录（仅允许删除本人数据）"""
    user_id = await get_user_id_from_request(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未登录，请先使用微信授权登录或提供有效 API Key"})
    records = _load_merchant_data()
    # 验证记录属于当前用户
    target = None
    for r in records:
        if r.get("id") == record_id:
            target = r
            break
    if target is None:
        return {"status": "error", "message": "记录不存在"}
    if target.get("user_id") != user_id and not is_admin(user_id):
        return {"status": "error", "message": "无权删除他人数据"}
    with _merchant_data_lock:
        new_records = [r for r in records if r.get("id") != record_id]
        _save_merchant_data(new_records)
    return {"status": "success", "message": f"已删除记录 {record_id}"}


# ====== 地理编码API v3.1（POI搜索优先 + 多API兜底 + 坐标统一GCJ-02） ======
@app.post("/api/geocode/search")
async def geocode_search(
    address: str = Query(..., description="要查询的地址或商家名称（支持：详细地址/商家名/混合搜索）"),
    provider: str = Query("auto", description="[已弃用] 保留兼容，现统一走 POI 优先策略"),
    city: str = Query("", description="限定城市范围，提高搜索精度（可选，如：大理州 或 adcode 320100）"),
    region: str = Query("", description="限定区域（可选，如：宾川县）"),
    store_type: str = Query("", description="行业类型（如 restaurant/retail），用于 POI 类型码过滤"),
    adcode: str = Query("", description="行政区划代码（如 320100），提升 POI 搜索精度"),
):
    """智能地址/商家搜索API v3.1 —— POI优先 + 地理编码兜底 + 行政区降级。

    核心变更：地理编码 → POI 搜索优先
    
    搜索策略：
    1. 地址清洗 → 去除口语化噪音、提取店名/地标
    2. 高德POI搜索（关键词+行业类型码+city/adcode） → 腾讯POI搜索
    3. 高德地理编码（兜底） → 腾讯地理编码
    4. 行政区中心降级（保底）
    
    所有输出坐标统一为 GCJ-02 坐标系。
    每个结果附带 confidence 字段：POI=0.9 / 地理编码=0.6 / 行政区=0.1
    """
    if not address or not address.strip():
        return {"status": "error", "message": "请输入要查询的地址或商家名称"}

    address = address.strip()
    search_city = adcode or region or city

    try:
        geo_result = await resolve_address_to_coord(
            address,
            city=search_city,
            store_type=store_type,
            adcode=adcode if adcode else "",
            use_cache=True,
        )
    except Exception as e:
        logger.error(f"[Geo] resolve_address_to_coord 异常: {e}")
        return {
            "status": "error",
            "message": f"地理编码服务异常: {str(e)[:200]}",
        }

    # 完全失败
    if geo_result["status"] == "failed":
        return {
            "status": "error",
            "message": geo_result.get("error_detail", "未找到匹配的商家或地址，请尝试更具体的关键词"),
            "errors": geo_result.get("errors", []),
        }

    # 将新的 confidence + coord_sys 字段映射到旧的 results 格式
    results = geo_result.get("results", [])
    # 确保旧格式字段存在（兼容前端），并根据 POI 类型推断行业
    for r in results:
        r.setdefault("importance", r.get("confidence", 0.5))
        r.setdefault("coord_sys", "GCJ-02")
        if "inferred_store_type" not in r:
            inferred = infer_genome_from_poi_type(r.get("poi_type"))
            r["inferred_store_type"] = inferred or ""

    # 降级状态返回警告
    if geo_result["status"] == "degraded":
        return {
            "status": "success",
            "provider": geo_result.get("provider", "unknown"),
            "results": results,
            "confidence": geo_result.get("confidence", 0.0),
            "coord_sys": "GCJ-02",
            "warning": geo_result.get("error_detail", "定位置信度较低，建议补充地标信息"),
            "clean_result": geo_result.get("clean_result"),
        }

    # 成功
    return {
        "status": "success",
        "provider": geo_result.get("provider", "unknown"),
        "results": results,
        "confidence": geo_result.get("confidence", 1.0),
        "coord_sys": "GCJ-02",
        "clean_result": geo_result.get("clean_result"),
    }


# ====== 微信小程序 API ======

@app.post("/api/auth/wx-login")
async def wx_login(request: Request):
    """微信小程序登录接口

    接收小程序传来的 code，调用微信接口换取 openid，
    生成 JWT Token 返回给小程序。

    Request Body:
        {"code": "wx.login() 返回的临时 code"}

    Response:
        {
            "status": "success",
            "token": "eyJhbGciOi...",
            "openid": "oXXXX",
            "expires_in": 259200,
            "token_type": "Bearer"
        }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "请求体必须为 JSON 格式，包含 code 字段"},
        )

    code = body.get("code", "").strip()
    if not code:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少必填参数: code（请先调用 wx.login() 获取）"},
        )

    try:
        from src.auth.wechat import wechat_login
        result = wechat_login(code)

        # v4.0: 自动注册/更新用户
        openid = result.get("openid", "")
        if openid:
            # 从请求体获取昵称头像（可选）
            nickname = body.get("nickname", "")
            avatar = body.get("avatar", "")
            user = get_or_create_user(openid, nickname, avatar)
            result["is_admin"] = is_admin(openid)
            result["user_info"] = {
                "nickname": user.get("nickname", ""),
                "store_type": user.get("store_type", ""),
                "created_at": user.get("created_at", ""),
                "record_count": user.get("record_count", 0),
            }

        return result
    except RuntimeError as e:
        logger.error(f"【微信登录】失败: {e}")
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(e)},
        )
    except Exception as e:
        logger.error(f"【微信登录】未知错误: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"服务内部错误: {e}"},
        )


@app.get("/api/dashboard/summary")
async def get_dashboard_summary(request: Request):
    """【v4.0 用户隔离】小程序首页概览 - 返回该用户的定制信息

    可选鉴权：如果携带 Bearer Token，返回该用户的定制信息，
    否则返回通用概览。
    """
    # 尝试 JWT 鉴权（可选）
    from src.auth.wechat import jwt_optional
    openid = await jwt_optional(request)

    # v4.0: 获取用户信息和店铺配置
    user_info = {}
    store_config = {}
    store_name = "AI军团指挥中心"

    if openid:
        user_info = get_user(openid) or {}
        try:
            from src.shop.store_manager import StoreManager
            store_mgr = StoreManager()
            store_config = store_mgr.get_config(openid)
            store_name = store_config.get("name", "")
        except Exception:
            logger.debug("获取店铺配置失败，使用默认名称", exc_info=True)

    if not store_name:
        store_name = user_info.get("store_name", "") or user_info.get("nickname", "") or "AI军团"

    # 获取战士状态
    soldier_status = {}
    try:
        status_data = dispatcher.get_all_status()
        soldier_status = {
            "total": status_data.get("soldiers_count", 0),
            "roles": status_data.get("soldiers", []),
        }
    except Exception:
        logger.warning("获取战士状态失败", exc_info=True)

    # 获取最近任务（待办事项）
    today_tasks = []
    try:
        missions = status_data.get("recent_missions", [])[-5:]
        for m in missions:
            today_tasks.append({
                "id": m.get("id", ""),
                "title": m.get("title", "任务")[:60],
                "status": m.get("status", "pending"),
                "soldier": m.get("soldier", ""),
                "created_at": m.get("created_at", ""),
            })
    except Exception:
        today_tasks = [
            {"id": "1", "title": "今日经营分析报告", "status": "pending", "soldier": "参谋-数据分析师", "created_at": ""},
            {"id": "2", "title": "竞品动态监测", "status": "pending", "soldier": "侦察兵-情报摘要官", "created_at": ""},
            {"id": "3", "title": "营销内容生成（小红书）", "status": "pending", "soldier": "特种-内容创作官", "created_at": ""},
        ]

    # 情报摘要
    scout_briefings = []
    try:
        if summarizer:
            recent = summarizer.get_recent_briefings(limit=3)
            for b in recent:
                scout_briefings.append({
                    "title": b.get("title", "情报"),
                    "summary": b.get("summary", "")[:100],
                    "source": b.get("source", ""),
                    "time": b.get("fetched_at", ""),
                })
    except Exception:
        logger.debug("获取情报摘要失败", exc_info=True)

    # 最近诊断
    last_diagnosis = None
    try:
        if attribution_analyzer:
            last_diagnosis = {
                "has_data": True,
                "hint": "点击查看完整诊断报告",
            }
    except Exception:
        logger.warning("获取诊断数据失败", exc_info=True)
        last_diagnosis = {"has_data": False}

    result = {
        "status": "success",
        "store_name": store_name,
        "today_tasks": today_tasks,
        "scout_briefings": scout_briefings,
        "soldier_status": soldier_status,
        "last_diagnosis": last_diagnosis,
        "user_openid": openid,
        "is_admin": is_admin(openid) if openid else False,
        "user_info": {
            "nickname": user_info.get("nickname", ""),
            "store_type": user_info.get("store_type", ""),
            "record_count": user_info.get("record_count", 0),
        } if openid else None,
    }

    # 移除 None 值
    return {k: v for k, v in result.items() if v is not None}


# ====== v4.0 Admin 管理后台 ======

ADMIN_DASHBOARD_DIR = Path(__file__).parent / "src" / "admin" / "dashboard"
ADMIN_DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

# 管理员 API Key（用于 Web 后台登录）
_ADMIN_KEY_PATH = Path(__file__).parent / "data" / ".admin_key"
if not _ADMIN_KEY_PATH.exists():
    import secrets
    _key = secrets.token_hex(16)
    _ADMIN_KEY_PATH.write_text(_key, encoding="utf-8")
    logger.info(f"🔑 Admin Key 已生成（仅显示一次）: {_key}")
ADMIN_KEY = _ADMIN_KEY_PATH.read_text(encoding="utf-8").strip()


@app.post("/api/admin/login")
async def admin_login(request: Request):
    """Web 管理后台登录"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "error", "message": "需要JSON请求体"})
    key = body.get("key", "")
    if key != ADMIN_KEY:
        return JSONResponse(status_code=401, content={"status": "error", "message": "密钥错误"})
    return {"status": "success", "token": ADMIN_KEY, "message": "登录成功"}


@app.get("/api/admin/check")
async def admin_check(request: Request):
    """检查 admin token 是否有效"""
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "")
    if token != ADMIN_KEY:
        return JSONResponse(status_code=401, content={"status": "error"})
    return {"status": "success"}


@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """【管理员】获取所有用户列表"""
    auth = request.headers.get("Authorization", "")
    if auth.replace("Bearer ", "") != ADMIN_KEY:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未授权"})

    users = get_all_users()
    # 统计每个用户的数据量
    all_records = _load_merchant_data()
    user_data_counts: dict[str, int] = {}
    user_latest: dict[str, str] = {}
    for r in all_records:
        uid = r.get("user_id", "")
        if uid:
            user_data_counts[uid] = user_data_counts.get(uid, 0) + 1
            if uid not in user_latest:
                user_latest[uid] = r.get("created_at", "")

    enriched = []
    for u in users:
        uid = u.get("openid", "")
        enriched.append({
            **u,
            "record_count": user_data_counts.get(uid, u.get("record_count", 0)),
            "latest_data": user_latest.get(uid, ""),
        })

    return {
        "status": "success",
        "users": enriched,
        "total": len(enriched),
    }


@app.get("/api/admin/users/{openid}/data")
async def admin_get_user_data(openid: str, request: Request):
    """【管理员】获取指定用户的所有数据"""
    auth = request.headers.get("Authorization", "")
    if auth.replace("Bearer ", "") != ADMIN_KEY:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未授权"})

    user = get_user(openid)
    records = _load_merchant_data()
    user_records = [r for r in records if r.get("user_id") == openid]

    return {
        "status": "success",
        "user": user,
        "records": user_records,
        "record_count": len(user_records),
    }


@app.get("/api/admin/stats")
async def admin_get_stats(request: Request):
    """【管理员】系统统计数据"""
    auth = request.headers.get("Authorization", "")
    if auth.replace("Bearer ", "") != ADMIN_KEY:
        return JSONResponse(status_code=401, content={"status": "error", "message": "未授权"})

    users = get_all_users()
    all_records = _load_merchant_data()
    total_records = len(all_records)

    # 按行业统计
    industry_stats: dict[str, int] = {}
    for r in all_records:
        st = r.get("store_type", "unknown")
        industry_stats[st] = industry_stats.get(st, 0) + 1

    # 战士状态
    soldier_status = {}
    try:
        status_data = dispatcher.get_all_status()
        soldier_status = {
            "total": status_data.get("soldiers_count", 0),
            "roles": [s.get("role", s.get("name", "")) for s in status_data.get("soldiers", [])],
        }
    except Exception:
        logger.warning("获取战士状态失败", exc_info=True)

    return {
        "status": "success",
        "total_users": len(users),
        "total_records": total_records,
        "industry_stats": industry_stats,
        "soldier_status": soldier_status,
        "genome_count": get_loader().count() if get_loader() else 0,
    }


@app.get("/admin")
@app.get("/admin/{path:path}")
async def admin_dashboard(path: str = ""):
    """Web 管理后台页面"""
    index_path = ADMIN_DASHBOARD_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Admin dashboard not found. Please create src/admin/dashboard/index.html"}


# ====== 启动入口 ======
if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 AI军团指挥中心启动: http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    logger.info(f"🔑 Admin Key: {ADMIN_KEY}")
    uvicorn.run(
        "main:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=False,
        log_level="info",
    )
