"""AI军团 - 店铺管理模块

包含3名新战士：
- StoreManager: 店长助理，统筹店铺经营
- CustomerService: 智能客服，自动回答FAQ
- LocalIntel: 本地情报，监控周边竞品
"""

from .store_manager import StoreManager
from .customer_service import CustomerService
from .competitor_monitor import LocalIntel

__all__ = ["StoreManager", "CustomerService", "LocalIntel"]
