"""种子数据脚本 - 用于初始化测试数据
运行: python seed_data.py
"""
import asyncio
import sys
sys.path.insert(0, ".")

from src.db import async_session, init_db
from src.db.models import Merchant, ShopUser, UsageLog
from src.auth.merchant_auth import hash_password


async def seed():
    await init_db()

    async with async_session() as session:
        # 检查是否已有数据
        from sqlalchemy import select, func
        r = await session.execute(select(func.count(Merchant.id)))
        count = r.scalar()
        if count and count > 0:
            print(f"Database already has {count} merchants, skipping seed.")
            return

        # 测试商家1: 茶百道
        m1 = Merchant(
            name="茶百道金牛镇店",
            account="chabaidao",
            password_hash=hash_password("123456"),
            phone="17387279430",
            region="云南大理宾川县",
        )
        session.add(m1)

        # 测试商家2: 荣达车行
        m2 = Merchant(
            name="荣达车行",
            account="rongda",
            password_hash=hash_password("123456"),
            phone="13988887777",
            region="云南大理宾川县",
        )
        session.add(m2)

        await session.flush()

        # 员工
        session.add(ShopUser(tenant_id=m1.tenant_id, name="张三", phone="13800001111", role="admin"))
        session.add(ShopUser(tenant_id=m1.tenant_id, name="李四", phone="13800002222", role="operator"))
        session.add(ShopUser(tenant_id=m2.tenant_id, name="王五", phone="13800003333", role="admin"))

        # 使用记录
        session.add(UsageLog(tenant_id=m1.tenant_id, user_name="张三", action="生成了营销文案", feature="智能营销"))
        session.add(UsageLog(tenant_id=m1.tenant_id, user_name="张三", action="分析了竞品数据", feature="竞品监控"))
        session.add(UsageLog(tenant_id=m2.tenant_id, user_name="王五", action="录入了今日营收数据", feature="数据录入"))

        await session.commit()
        print("[OK] Seed data created!")
        print(f"  - {m1.name} (account: chabaidao / password: 123456)")
        print(f"  - {m2.name} (account: rongda / password: 123456)")
        print(f"  Admin: admin / admin123")


if __name__ == "__main__":
    asyncio.run(seed())
