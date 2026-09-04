"""特种部队 - AI辅助代码生成器

用途：
- 根据需求描述快速生成Python代码
- 代码审查与优化建议
- 生成测试用例
"""

from typing import Any

from loguru import logger

from src.core import BaseSoldier
from config.prompts.content_prompts import CODE_GEN_PROMPT

CODE_REVIEW_PROMPT = """你是一位代码审查专家。对以下代码进行审查：

## 审查维度
1. **逻辑正确性**：边界条件、异常情况
2. **性能**：时间复杂度、空间使用、不必要的操作
3. **安全性**：SQL注入、敏感信息泄露、输入验证
4. **可维护性**：命名、注释、函数长度、耦合度
5. **Python惯例**：PEP8、类型注解、docstring

## 待审查代码
```python
{code}
```

## 输出格式
### 📊 总体评分：X/10

### 🔴 严重问题（必须修复）
- ...

### 🟡 改进建议（建议修复）
- ...

### 🟢 亮点（做得好的地方）
- ...

### ✨ 优化后代码
```python
# 优化后的代码
```
"""


class CodeGenerator(BaseSoldier):
    """AI代码生成器"""

    name = "特种兵-代码工程师"
    role = "special_forces_coder"
    temperature = 0.3
    max_tokens = 3000

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """生成代码

        Args:
            task: {
                "action": str,    # generate / review / test
                "spec": str,      # 需求描述（generate时）
                "code": str,      # 待审查代码（review时）
                "language": str,  # 编程语言（默认Python）
            }

        Returns:
            {"result": str, "tokens_used": int}
        """
        action = task.get("action", "generate")

        if action == "generate":
            spec = task.get("spec", "")
            lang = task.get("language", "Python")
            system_prompt = CODE_GEN_PROMPT
            user_message = CODE_GEN_PROMPT.format(task_spec=spec)
        elif action == "review":
            code = task.get("code", "")
            system_prompt = CODE_REVIEW_PROMPT
            user_message = CODE_REVIEW_PROMPT.format(code=code)
        elif action == "test":
            code = task.get("code", "")
            system_prompt = "你是一个测试工程师。请为以下代码生成全面的测试用例（pytest格式）。"
            user_message = f"为以下代码生成测试用例：\n```python\n{code}\n```"
        else:
            raise ValueError(f"不支持的操作: {action}")

        logger.info(f"[代码工程师] 任务: {action}")
        result, tokens = self.chat(system_prompt, user_message)
        return {"result": result, "tokens_used": tokens, "action": action}

    def generate_code(self, spec: str, language: str = "Python") -> str:
        """快捷方法：生成代码"""
        return self.execute({"action": "generate", "spec": spec, "language": language})["result"]

    def review_code(self, code: str) -> str:
        """快捷方法：代码审查"""
        return self.execute({"action": "review", "code": code})["result"]

    def generate_tests(self, code: str) -> str:
        """快捷方法：生成测试"""
        return self.execute({"action": "test", "code": code})["result"]


# ====== 使用示例 ======
if __name__ == "__main__":
    coder = CodeGenerator()

    # 示例1：生成代码
    print("=" * 60)
    print("💻 代码生成器测试")
    print("=" * 60)

    spec = """写一个Python函数 batch_process_files：
    - 输入：文件夹路径、处理函数
    - 对文件夹中所有.csv文件并行调用处理函数
    - 返回成功/失败统计
    - 使用concurrent.futures
    - 错误处理：单个文件失败不影响其他文件
    """

    print("\n📝 需求：")
    print(spec)
    print("\n💡 生成结果：")
    print(coder.generate_code(spec))

    # 示例2：代码审查
    bad_code = '''
def get_data(id):
    import sqlite3
    conn = sqlite3.connect("db.sqlite3")
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM users WHERE id = {id}")
    return cursor.fetchall()
'''
    print("\n\n--- 代码审查测试 ---\n")
    print(f"原始代码:\n{bad_code}")
    print("\n审查结果：")
    print(coder.review_code(bad_code))
