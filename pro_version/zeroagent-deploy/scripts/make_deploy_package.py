"""
临时打包脚本：将 zeroagent 构建为可分发的部署包 zeroagent-deploy/
生成内容：
  - 完整源码（剔除 __pycache__ / *.pyc / *.log / 调试脚本 / 运行时数据 data/）
  - 一键启动脚本（start_windows.bat / start_linux.sh）
  - 部署说明 README_部署说明.md
验证后由调用方删除本脚本。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # zeroagent/
OUT = ROOT.parent / "deploy" / "zeroagent-deploy"      # 打包工作目录
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
SKIP_FILES = {
    # 根目录调试日志/脚本
    "_server.log", "_server_err.log", "server_stdout.log", "server_stderr.log",
    "tmp_stdout.log", "tmp_stderr.log", "tmp2_stdout.log", "tmp2_stderr.log",
    "_debug_agents.py", "_verify_cs.py", "_verify_degraded.py",
}


def ensure_empty(dirpath: Path):
    if dirpath.exists():
        shutil.rmtree(dirpath)
    dirpath.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path):
    for item in src.iterdir():
        if item.is_dir():
            if item.name in SKIP_DIRS:
                continue
            copy_tree(item, dst / item.name)
        else:
            if item.name in SKIP_FILES:
                continue
            (dst / item.name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst / item.name)


def main():
    ensure_empty(OUT)

    # 1. 复制源码（app/、agents/、config/、scripts/ 及根文件）
    for name in ["app", "agents", "config", "scripts"]:
        copy_tree(ROOT / name, OUT / name)
    for f in ["main.py", "requirements.txt", "Dockerfile", "docker-compose.yml", "README.md"]:
        shutil.copy2(ROOT / f, OUT / f)

    # 2. 运行时数据目录占位（全新部署，无存量数据）
    for name in ["data", "data/uploads", "data/vectordb", "data/feedback"]:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "README.txt").write_text(
        "运行时数据目录：向量库(vectordb)、上传文件(uploads)、反馈(feedback)、审计日志(audit_log.jsonl) 均在此。\n"
        "交付包已清空运行时数据，部署后首次启动会在此自动生成。\n",
        encoding="utf-8",
    )

    print(f"deploy 目录已生成: {OUT}")


if __name__ == "__main__":
    main()
