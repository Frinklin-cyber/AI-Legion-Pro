"""多租户数据模型 - 共享表 + tenant_id 隔离"""
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, func
from src.db import Base


def _new_tenant_id() -> str:
    return uuid.uuid4().hex[:12]


class Merchant(Base):
    """商家表"""
    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(32), unique=True, nullable=False, index=True, default=_new_tenant_id)
    name = Column(String(100), nullable=False, comment="商家名称")
    account = Column(String(100), unique=True, nullable=False, index=True, comment="登录账号")
    password_hash = Column(String(256), nullable=False, comment="bcrypt 密码哈希")
    phone = Column(String(30), default="", comment="联系电话")
    region = Column(String(100), default="", comment="所在地区")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=func.now(), comment="注册时间")


class ShopUser(Base):
    """商家员工表"""
    __tablename__ = "shop_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(32), nullable=False, index=True, comment="所属商家")
    name = Column(String(100), nullable=False, comment="员工姓名")
    phone = Column(String(30), default="", comment="手机号")
    role = Column(String(50), default="operator", comment="角色: admin/operator/viewer")
    is_active = Column(Boolean, default=True, comment="是否在职")
    created_at = Column(DateTime, default=func.now())


class BusinessData(Base):
    """业务数据表 - 存储商家信息、话术、客户等"""
    __tablename__ = "business_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(32), nullable=False, index=True, comment="所属商家")
    data_type = Column(String(50), nullable=False, comment="数据类型: store_info/script/customer/content")
    content = Column(Text, default="{}", comment="JSON 格式内容")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UsageLog(Base):
    """使用记录表"""
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(32), nullable=False, index=True, comment="所属商家")
    user_name = Column(String(100), default="", comment="操作用户")
    action = Column(String(300), default="", comment="操作描述")
    feature = Column(String(100), default="", comment="功能模块")
    created_at = Column(DateTime, default=func.now())


# ============================================================
# Pro 版（AI 店长）新增表 —— 积分 / 计划 / 审批 / 周期任务
# 详见《AI军团Pro版_CodeBuddy技术需求文档》第六节 DDL
# ============================================================


class Balance(Base):
    """积分余额表"""
    __tablename__ = "balances"

    store_id = Column(String(64), primary_key=True, comment="店铺ID")
    balance = Column(Integer, default=0, nullable=False, comment="当前积分余额")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Transaction(Base):
    """积分流水表"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(String(64), nullable=False, index=True, comment="店铺ID")
    type = Column(String(20), nullable=False, comment="类型: recharge/deduct/refund/settle")
    amount = Column(Integer, nullable=False, comment="变动积分（正为入，负为出）")
    plan_id = Column(String(64), default="", comment="关联计划ID")
    remark = Column(String(200), default="", comment="备注")
    created_at = Column(DateTime, default=func.now())


class Plan(Base):
    """执行计划表"""
    __tablename__ = "plans"

    id = Column(String(64), primary_key=True, comment="计划ID")
    store_id = Column(String(64), nullable=False, index=True, comment="店铺ID")
    goal = Column(Text, nullable=False, comment="老板下达的目标")
    template_id = Column(String(64), default="", comment="快捷模板ID")
    plan_json = Column(Text, nullable=False, comment="任务树 JSON")
    estimated_cost = Column(Integer, default=0, comment="预估积分消耗")
    status = Column(String(20), default="draft", comment="draft/confirmed/running/done/failed")
    created_at = Column(DateTime, default=func.now())


class Approval(Base):
    """人工审批队列表"""
    __tablename__ = "approvals"

    id = Column(String(64), primary_key=True, comment="审批ID")
    store_id = Column(String(64), nullable=False, index=True, comment="店铺ID")
    plan_id = Column(String(64), default="", comment="计划ID")
    task_id = Column(String(64), default="", comment="任务ID")
    action = Column(String(64), default="", comment="动作: 发企微/定时发布/扣积分等")
    payload = Column(Text, default="{}", comment="待执行 payload（JSON）")
    status = Column(String(20), default="pending", comment="pending/approved/rejected")
    created_at = Column(DateTime, default=func.now())


class Schedule(Base):
    """周期任务表"""
    __tablename__ = "schedules"

    id = Column(String(64), primary_key=True, comment="任务ID")
    store_id = Column(String(64), nullable=False, index=True, comment="店铺ID")
    goal = Column(Text, nullable=False, comment="目标描述")
    cron = Column(String(64), nullable=False, comment="cron 表达式")
    template_id = Column(String(64), default="", comment="快捷模板ID")
    enabled = Column(Boolean, default=True, comment="是否启用")
    last_run_at = Column(DateTime, default=None, comment="上次运行时间")
    created_at = Column(DateTime, default=func.now())
