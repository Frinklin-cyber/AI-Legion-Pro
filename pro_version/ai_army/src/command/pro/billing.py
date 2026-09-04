"""积分计费模块（Pro 版 / AI 店长）

职责：预估扣费 + 多退少补。
- recharge(store_id, amount)   充值（1 元 = 1 积分，记录流水）
- deduct(store_id, cost)       预扣（余额不足抛 InsufficientBalanceError）
- settle(store_id, est, actual) 执行完结算，多退少补
- get_balance(store_id)        查询余额

存储：SQLite 表 balances + transactions（见 src/db/models.py）
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select, update

from src.db import async_session
from src.db.models import Balance, Transaction

# 默认单价（可从 config 覆盖）
UNIT_PRICES: dict[str, int] = {
    "店铺诊断": 12,
    "文案生成": 5,
    "竞品情报": 8,
    "分析报告": 15,
    "定时发布": 3,
}

# action 名 → 单价键名映射（用于预估费用，与 executor.ACTIONS 别名对齐）
ACTION_TO_PRICE_KEY: dict[str, str] = {
    "发企微": "文案生成",
    "企微推送": "文案生成",
    "推送": "文案生成",
    "存报告": "分析报告",
    "保存报告": "分析报告",
    "存入记忆": "分析报告",
    "定时发布": "定时发布",
    "安排发布": "定时发布",
    "预约发布": "定时发布",
    "生成文案": "文案生成",
    "写引流文案": "文案生成",
    "写文案": "文案生成",
    "发朋友圈": "文案生成",
    "朋友圈文案": "文案生成",
    "生成短视频脚本": "文案生成",
    "短视频脚本": "文案生成",
    "生成图文": "文案生成",
    "爬取情报": "竞品情报",
    "竞品情报": "竞品情报",
    "情报爬取": "竞品情报",
    "市场情报": "竞品情报",
    "数据分析": "分析报告",
    "数据问答": "分析报告",
    "分析报告": "分析报告",
    "生成报告": "分析报告",
    "运营报告": "分析报告",
    "店铺诊断": "店铺诊断",
    "经营诊断": "店铺诊断",
    "诊断分析": "店铺诊断",
}


class InsufficientBalanceError(Exception):
    """余额不足异常"""

    def __init__(self, store_id: str, required: int, balance: int) -> None:
        self.store_id = store_id
        self.required = required
        self.balance = balance
        super().__init__(
            f"店铺 {store_id} 积分余额不足：需要 {required}，当前 {balance}，请先充值"
        )


def price_for_action(action: str) -> int:
    """根据 action 返回单价"""
    key = ACTION_TO_PRICE_KEY.get(action, action)
    return UNIT_PRICES.get(key, 5)  # 未知动作按默认 5 积分


class Billing:
    """积分计费服务（全 async）"""

    async def recharge(self, store_id: str, amount: int, remark: str = "充值") -> int:
        """充值积分，返回最新余额"""
        async with async_session() as session:
            row = await session.get(Balance, store_id)
            if row is None:
                row = Balance(store_id=store_id, balance=0)
                session.add(row)
            row.balance += amount
            session.add(Transaction(
                store_id=store_id, type="recharge", amount=amount,
                remark=remark,
            ))
            await session.commit()
            balance = row.balance
        logger.info(f"[计费] 店铺 {store_id} 充值 +{amount}，余额 {balance}")
        return balance

    async def get_balance(self, store_id: str) -> int:
        """查询余额"""
        async with async_session() as session:
            row = await session.get(Balance, store_id)
            return row.balance if row else 0

    async def deduct(self, store_id: str, cost: int, plan_id: str = "") -> int:
        """预扣积分（SQL 原子扣减，避免并发读改写竞态），余额不足抛 InsufficientBalanceError"""
        if cost <= 0:
            return await self.get_balance(store_id)
        async with async_session() as session:
            # 原子扣减：仅当余额充足时更新生效
            result = await session.execute(
                update(Balance)
                .where(Balance.store_id == store_id, Balance.balance >= cost)
                .values(balance=Balance.balance - cost)
            )
            if result.rowcount == 0:
                await session.rollback()
                row = await session.get(Balance, store_id)
                raise InsufficientBalanceError(store_id, cost, row.balance if row else 0)
            session.add(Transaction(
                store_id=store_id, type="deduct", amount=-cost,
                plan_id=plan_id, remark="执行预扣",
            ))
            await session.commit()
            row = await session.get(Balance, store_id)
            balance = row.balance if row else 0
        logger.info(f"[计费] 店铺 {store_id} 预扣 -{cost}，余额 {balance}")
        return balance

    async def refund(self, store_id: str, amount: int, plan_id: str = "") -> int:
        """退还积分（SQL 原子操作，用于失败任务退款 / 多退少补）"""
        async with async_session() as session:
            # 记录不存在则先创建
            row = await session.get(Balance, store_id)
            if row is None:
                session.add(Balance(store_id=store_id, balance=0))
                await session.commit()
            await session.execute(
                update(Balance)
                .where(Balance.store_id == store_id)
                .values(balance=Balance.balance + amount)
            )
            session.add(Transaction(
                store_id=store_id, type="refund", amount=amount,
                plan_id=plan_id, remark="结算退还",
            ))
            await session.commit()
            row = await session.get(Balance, store_id)
            balance = row.balance if row else amount
        logger.info(f"[计费] 店铺 {store_id} 退还 +{amount}，余额 {balance}")
        return balance

    async def settle(self, store_id: str, estimated: int, actual: int, plan_id: str = "") -> int:
        """执行完结算：多退少补

        estimated 为预扣总额，actual 为实际消耗总额。
        estimated > actual → 退还差额；estimated < actual → 补扣差额（不足则抛异常）。
        """
        diff = estimated - actual
        if diff > 0:
            return await self.refund(store_id, diff, plan_id)
        if diff < 0:
            return await self.deduct(store_id, -diff, plan_id)
        return await self.get_balance(store_id)

    async def list_transactions(self, store_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """查询流水"""
        async with async_session() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.store_id == store_id)
                .order_by(Transaction.id.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [
                {
                    "id": t.id,
                    "type": t.type,
                    "amount": t.amount,
                    "plan_id": t.plan_id,
                    "remark": t.remark,
                    "created_at": t.created_at.isoformat() if t.created_at else "",
                }
                for t in rows
            ]


# 全局单例
billing = Billing()
