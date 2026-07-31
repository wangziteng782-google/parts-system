"""Build a deployment ZIP without local secrets, caches, or runtime state."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "deploy" / "artifacts" / "parts-system-code.zip"

ROOT_FILES = (
    "app.py",
    "requirements.txt",
    "product_classifications.json",
)
SOURCE_DIRECTORIES = (
    "parts_system",
    "static",
    "templates",
    "sql",
    "jobs",
)
DEPLOY_FILES = (
    "deploy/.env.production.example",
    "deploy/parts-system.service",
    "deploy/nginx-parts-system.conf",
    "deploy/README_BT_DEPLOY.md",
    "deploy/parts-system部署与更新手册.md",
)

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".idea",
    ".venv",
    "__pycache__",
    "artifacts",
}
EXCLUDED_FILE_NAMES = {
    ".env",
    "qiniu_config.local.json",
    "migration_target.local.json",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
}


def should_include(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
        return False
    if path.name in EXCLUDED_FILE_NAMES:
        return False
    if path.name.endswith("_state.json"):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def deployment_files() -> list[Path]:
    files: set[Path] = set()
    for relative_name in ROOT_FILES:
        path = PROJECT_ROOT / relative_name
        if path.is_file():
            files.add(path)

    for relative_name in SOURCE_DIRECTORIES:
        directory = PROJECT_ROOT / relative_name
        if not directory.exists():
            continue
        files.update(path for path in directory.rglob("*") if should_include(path))

    for relative_name in DEPLOY_FILES:
        path = PROJECT_ROOT / relative_name
        if path.is_file():
            files.add(path)

    return sorted(files, key=lambda path: path.as_posix().lower())


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 parts-system 安全部署压缩包")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = deployment_files()
    if not files:
        raise SystemExit("没有找到可打包文件")

    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in files:
            archive.write(path, path.relative_to(PROJECT_ROOT).as_posix())

    print(f"部署包生成完成：{output}")
    print(f"包含文件数：{len(files)}")
    print(f"文件大小：{output.stat().st_size / 1024:.2f} KB")
    print("已排除：.env、.venv、密钥配置、本地日志、缓存和迁移状态文件")


if __name__ == "__main__":
    main()
