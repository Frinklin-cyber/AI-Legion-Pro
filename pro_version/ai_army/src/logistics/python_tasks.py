"""后勤兵 - Python自动化任务集合

常用自动化任务：
- 邮件发送（SMTP）
- 数据备份
- 文件清理
- 企业微信消息
- 数据同步
"""

import os
import shutil
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from config.env import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    DATA_DIR,
)


def send_email(to: str, subject: str, body: str, is_html: bool = False) -> bool:
    """发送邮件

    Args:
        to: 收件人邮箱
        subject: 主题
        body: 正文
        is_html: 是否为HTML格式

    Returns:
        是否发送成功
    """
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        logger.warning("[邮件] SMTP未配置，跳过发送")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html" if is_html else "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to, msg.as_string())

        logger.info(f"[邮件] ✅ 已发送至 {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"[邮件] ❌ 发送失败: {e}")
        return False


def backup_database(source_path: str, backup_dir: str = "./data/backups",
                    keep_days: int = 30) -> str | None:
    """备份数据库文件

    Args:
        source_path: 源文件路径
        backup_dir: 备份目录
        keep_days: 保留最近N天的备份

    Returns:
        备份文件路径，失败返回None
    """
    try:
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        src = Path(source_path)
        if not src.exists():
            logger.warning(f"[备份] 源文件不存在: {source_path}")
            return None

        backup_name = f"{src.stem}_{timestamp}{src.suffix}"
        backup_path = Path(backup_dir) / backup_name
        shutil.copy2(src, backup_path)
        logger.info(f"[备份] ✅ {source_path} → {backup_path}")

        # 清理旧备份
        cutoff = datetime.now() - timedelta(days=keep_days)
        for f in Path(backup_dir).glob(f"{src.stem}_*{src.suffix}"):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                logger.info(f"[备份] 清理旧文件: {f.name}")

        return str(backup_path)
    except Exception as e:
        logger.error(f"[备份] ❌ 失败: {e}")
        return None


def clean_temp_files(directory: str = "./data/temp", max_age_hours: int = 24) -> int:
    """清理临时文件

    Args:
        directory: 临时文件目录
        max_age_hours: 超过多少小时的文件删除

    Returns:
        清理的文件数量
    """
    cleaned = 0
    cutoff = datetime.now() - timedelta(hours=max_age_hours)

    try:
        for root, dirs, files in os.walk(directory):
            for f in files:
                filepath = Path(root) / f
                if datetime.fromtimestamp(filepath.stat().st_mtime) < cutoff:
                    filepath.unlink()
                    cleaned += 1
                    logger.debug(f"[清理] 删除: {filepath}")

        # 清理空目录
        for root, dirs, files in os.walk(directory, topdown=False):
            if not files and not dirs and root != directory:
                os.rmdir(root)

        logger.info(f"[清理] 已清理 {cleaned} 个临时文件")
    except Exception as e:
        logger.error(f"[清理] 失败: {e}")

    return cleaned


def sync_csv_to_db(csv_path: str, table_name: str | None = None) -> int:
    """将CSV数据同步到SQLite数据库（轻量级数据仓库）

    Args:
        csv_path: CSV文件路径
        table_name: 表名（默认用文件名）

    Returns:
        同步的行数
    """
    import sqlite3

    path = Path(csv_path)
    if not path.exists():
        logger.warning(f"[同步] 文件不存在: {csv_path}")
        return 0

    table = table_name or path.stem
    db_path = DATA_DIR / "warehouse.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        df = pd.read_csv(csv_path)
        conn = sqlite3.connect(str(db_path))
        df.to_sql(table, conn, if_exists="replace", index=False)
        conn.close()
        logger.info(f"[同步] ✅ {csv_path} → {table} ({len(df)}行)")
        return len(df)
    except Exception as e:
        logger.error(f"[同步] ❌ 失败: {e}")
        return 0


def export_report_to_excel(data: dict[str, Any], output_path: str) -> str:
    """将分析结果导出为Excel

    Args:
        data: 包含多个DataFrame的字典，如 {"概览": df1, "明细": df2}
        output_path: 输出Excel文件路径

    Returns:
        输出路径
    """
    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            for sheet_name, df in data.items():
                if isinstance(df, pd.DataFrame):
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        logger.info(f"[导出] ✅ 已导出: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"[导出] ❌ 失败: {e}")
        return ""


def get_disk_usage(path: str = ".") -> dict[str, str]:
    """获取磁盘使用情况"""
    import shutil
    usage = shutil.disk_usage(path)
    gb = 1024 ** 3
    return {
        "total": f"{usage.total / gb:.1f} GB",
        "used": f"{usage.used / gb:.1f} GB",
        "free": f"{usage.free / gb:.1f} GB",
        "percent": f"{usage.used / usage.total * 100:.1f}%",
    }


# ====== 使用示例 ======
if __name__ == "__main__":
    print("🧹 后勤兵自动化测试\n")

    # 磁盘检查
    print("磁盘使用:", get_disk_usage())

    # 备份
    # backup_database("data/warehouse.db")

    # 清理临时文件
    cleaned = clean_temp_files("./data/temp")
    print(f"清理: {cleaned} 个文件")
