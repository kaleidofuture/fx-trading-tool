"""
FX学習ドキュメントをNotebookLMへ同期するスクリプト

使い方:
  python sync.py          # 初回: ノートブック作成 + ソース追加
  python sync.py --update  # 更新: 既存ノートブックのソースを差し替え
"""

import asyncio
import argparse
import json
from pathlib import Path
from notebooklm import NotebookLMClient

SYNC_DIR = Path(__file__).parent
SOURCES_DIR = SYNC_DIR.parent  # 01_理解/
PROJECT_DIR = SOURCES_DIR.parent
STATE_FILE = SYNC_DIR / ".state.json"
NOTEBOOK_TITLE = "FX × AI トレーディング学習"

# 同期対象のmdファイル（順番通り）
SOURCE_FILES = [
    SOURCES_DIR / "01_FX基礎" / "README.md",
    SOURCES_DIR / "02_テクニカル分析" / "README.md",
    SOURCES_DIR / "03_ファンダメンタルズ" / "README.md",
    SOURCES_DIR / "04_リスク管理" / "README.md",
    SOURCES_DIR / "05_AI戦略の根拠" / "README.md",
    PROJECT_DIR / "PROJECT.md",
]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def create_and_sync():
    """ノートブックを新規作成し、全ソースを追加する"""
    async with await NotebookLMClient.from_storage() as client:
        print(f"ノートブック作成中: {NOTEBOOK_TITLE}")
        nb = await client.notebooks.create(NOTEBOOK_TITLE)
        notebook_id = nb.id
        print(f"  作成完了: {notebook_id}")

        source_ids = []
        for f in SOURCE_FILES:
            if not f.exists():
                print(f"  スキップ（ファイルなし）: {f.name}")
                continue
            label = f.parent.name if f.parent != PROJECT_DIR else "PROJECT"
            print(f"  ソース追加中: {label}/{f.name}")
            src = await client.sources.add_text(
                notebook_id,
                title=label,
                content=f.read_text(encoding="utf-8"),
            )
            source_ids.append(src.id)
            print(f"    完了: {src.id}")

        save_state({
            "notebook_id": notebook_id,
            "source_count": len(source_ids),
        })

        print(f"\n同期完了！ ノートブックID: {notebook_id}")
        print(f"  ソース数: {len(source_ids)}")
        print("NotebookLM (https://notebooklm.google.com) で確認してください。")


async def update_sync():
    """既存ノートブックのソースを更新する（削除→再追加）"""
    state = load_state()
    if "notebook_id" not in state:
        print("エラー: まず引数なしで実行してノートブックを作成してください。")
        return

    notebook_id = state["notebook_id"]
    async with await NotebookLMClient.from_storage() as client:
        print(f"既存ソースを削除中 (notebook: {notebook_id})")
        sources = await client.sources.list(notebook_id)
        for src in sources:
            await client.sources.delete(notebook_id, src.id)
            print(f"  削除: {src.id}")

        source_ids = []
        for f in SOURCE_FILES:
            if not f.exists():
                continue
            label = f.parent.name if f.parent != PROJECT_DIR else "PROJECT"
            print(f"  ソース追加中: {label}/{f.name}")
            src = await client.sources.add_text(
                notebook_id,
                title=label,
                content=f.read_text(encoding="utf-8"),
            )
            source_ids.append(src.id)

        save_state({
            "notebook_id": notebook_id,
            "source_count": len(source_ids),
        })

        print(f"\n更新完了！ ソース数: {len(source_ids)}")


async def main():
    parser = argparse.ArgumentParser(description="FX学習ドキュメントをNotebookLMに同期")
    parser.add_argument("--update", action="store_true", help="既存ノートブックを更新")
    args = parser.parse_args()

    if args.update:
        await update_sync()
    else:
        await create_and_sync()


if __name__ == "__main__":
    asyncio.run(main())
