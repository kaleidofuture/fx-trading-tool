"""
NotebookLMの学習コンテンツを一括生成・ダウンロードするスクリプト

使い方:
  python learn.py                  # 全コンテンツを生成＆ダウンロード
  python learn.py --only podcast   # ポッドキャストのみ
  python learn.py --only quiz      # クイズのみ
  python learn.py --only flashcard # フラッシュカードのみ
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Windows cp932 対策
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

SYNC_DIR = Path(__file__).parent
STATE_FILE = SYNC_DIR / ".state.json"
OUTPUT_DIR = SYNC_DIR / "output"


def get_notebook_id() -> str:
    if not STATE_FILE.exists():
        print("エラー: まず sync.py を実行してノートブックを作成してください。")
        sys.exit(1)
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return state["notebook_id"]


def run_cmd(args: list[str], desc: str) -> bool:
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"{'='*60}")
    result = subprocess.run(args, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"  [!] 失敗 (exit code: {result.returncode})")
        return False
    return True


def generate_podcast(nb_id: str):
    output_dir = OUTPUT_DIR / "podcast"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 生成（日本語で指示、完了まで待機）
    run_cmd(
        [
            "notebooklm", "generate", "audio",
            "FXトレーディングとAI戦略について、初心者にもわかりやすく解説してください。"
            "テクニカル分析の指標、リスク管理の鉄則、トレンドフォロー戦略の学術的根拠を中心に。",
            "-n", nb_id,
            "--format", "deep-dive",
            "--length", "default",
            "--language", "ja",
            "--wait",
        ],
        "ポッドキャスト生成中（数分かかります）...",
    )

    # ダウンロード
    run_cmd(
        [
            "notebooklm", "download", "audio",
            str(output_dir / "fx_learning_podcast.mp3"),
            "-n", nb_id,
        ],
        "ポッドキャスト ダウンロード中...",
    )


def generate_quiz(nb_id: str):
    output_dir = OUTPUT_DIR / "quiz"
    output_dir.mkdir(parents=True, exist_ok=True)

    run_cmd(
        [
            "notebooklm", "generate", "quiz",
            "FXの基礎知識、テクニカル指標の計算、リスク管理の原則、ポジションサイズ計算について出題してください。",
            "-n", nb_id,
            "--difficulty", "medium",
            "--quantity", "more",
            "--wait",
        ],
        "理解度クイズ生成中...",
    )

    # Markdown形式でダウンロード
    run_cmd(
        [
            "notebooklm", "download", "quiz",
            str(output_dir / "fx_quiz.md"),
            "-n", nb_id,
            "--format", "markdown",
        ],
        "クイズ ダウンロード中...",
    )


def generate_flashcards(nb_id: str):
    output_dir = OUTPUT_DIR / "flashcards"
    output_dir.mkdir(parents=True, exist_ok=True)

    run_cmd(
        [
            "notebooklm", "generate", "flashcards",
            "pips計算、ロット、レバレッジ、ポジションサイズ計算、ATR、RSI、MACD、"
            "リスクリワード比、ドローダウンなど実践で使う概念を中心に。",
            "-n", nb_id,
            "--difficulty", "medium",
            "--quantity", "more",
            "--wait",
        ],
        "フラッシュカード生成中...",
    )

    run_cmd(
        [
            "notebooklm", "download", "flashcards",
            str(output_dir / "fx_flashcards.md"),
            "-n", nb_id,
            "--format", "markdown",
        ],
        "フラッシュカード ダウンロード中...",
    )


def main():
    parser = argparse.ArgumentParser(description="NotebookLM学習コンテンツ生成")
    parser.add_argument(
        "--only",
        choices=["podcast", "quiz", "flashcard"],
        help="特定のコンテンツのみ生成",
    )
    args = parser.parse_args()

    nb_id = get_notebook_id()
    print(f"ノートブック: {nb_id}")

    tasks = {
        "podcast": generate_podcast,
        "quiz": generate_quiz,
        "flashcard": generate_flashcards,
    }

    if args.only:
        tasks[args.only](nb_id)
    else:
        for name, func in tasks.items():
            func(nb_id)

    print(f"\n{'='*60}")
    print(f"  完了！ 出力先: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
