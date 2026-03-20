#!/usr/bin/env python3
"""Kindle本をスクリーンショット＋OCRでテキスト化するツール"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

from PIL import Image
import imagehash

# 定数
DEFAULT_DELAY = 1.5
DEFAULT_STALE_THRESHOLD = 3
DEFAULT_START_DELAY = 3.0
DEFAULT_HASH_THRESHOLD = 5
COMPLETION_SOUND = "/System/Library/Sounds/Glass.aiff"
SCREENSHOT_PATH = os.path.join(tempfile.gettempdir(), "kindle_capture.png")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OCR_HELPER = os.path.join(SCRIPT_DIR, "ocr_helper.swift")

# 矢印キーコード
KEY_CODES = {"left": 123, "right": 124}


def activate_kindle(start_delay: float) -> None:
    """Kindleアプリをアクティブにしてフルスクリーンにする"""
    print("Kindleアプリをアクティブにしています...")
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Amazon Kindle" to activate'],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        print(
            "エラー: Kindleアプリを起動できませんでした。"
            "Kindleがインストールされているか確認してください。"
        )
        sys.exit(1)

    time.sleep(1)

    # フルスクリーンにする
    print("フルスクリーンモードにしています...")
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to tell process "Amazon Kindle" '
                'to set value of attribute "AXFullScreen" of window 1 to true',
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        # フォールバック: Cmd+Ctrl+F キーストローク
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to keystroke "f" '
                    "using {command down, control down}",
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            print(
                "警告: フルスクリーンに切り替えられませんでした。\n"
                "ターミナルにアクセシビリティ権限を付与してください:\n"
                "  システム設定 > プライバシーとセキュリティ > アクセシビリティ"
            )

    print(f"Kindleの準備を待っています ({start_delay}秒)...")
    time.sleep(start_delay)


def take_screenshot(crop_region: tuple = None) -> Image.Image:
    """スクリーンショットを撮影してPIL Imageとして返す"""
    subprocess.run(
        ["screencapture", "-x", SCREENSHOT_PATH],
        check=True,
        capture_output=True,
    )

    # 画面収録権限のチェック
    if not os.path.exists(SCREENSHOT_PATH) or os.path.getsize(SCREENSHOT_PATH) == 0:
        print(
            "エラー: スクリーンショットを撮影できませんでした。\n"
            "ターミナルに画面収録権限を付与してください:\n"
            "  システム設定 > プライバシーとセキュリティ > 画面収録"
        )
        sys.exit(1)

    img = Image.open(SCREENSHOT_PATH)
    if crop_region:
        img = img.crop(crop_region)
    return img


def extract_text(image_path: str, language: str) -> str:
    """SwiftのVision Frameworkヘルパーを使ってOCRでテキストを抽出する"""
    try:
        result = subprocess.run(
            ["swift", OCR_HELPER, image_path, language],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(f"  警告: OCR処理でエラーが発生しました: {stderr}")
            return ""
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("  警告: OCR処理がタイムアウトしました")
        return ""
    except Exception as e:
        print(f"  警告: OCR処理でエラーが発生しました: {e}")
        return ""


def turn_page(forward_key: str) -> None:
    """ページをめくる（矢印キーを送信）"""
    key_code = KEY_CODES[forward_key]
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'tell application "System Events" to key code {key_code}',
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        print(
            "エラー: ページめくりに失敗しました。\n"
            "ターミナルにアクセシビリティ権限を付与してください:\n"
            "  システム設定 > プライバシーとセキュリティ > アクセシビリティ"
        )
        sys.exit(1)


def compute_hash(image: Image.Image):
    """パーセプチュアルハッシュを計算する"""
    return imagehash.phash(image)


def is_page_unchanged(current_hash, previous_hash, threshold: int) -> bool:
    """ページが変化していないか判定する"""
    if previous_hash is None:
        return False
    distance = current_hash - previous_hash
    return distance <= threshold


def play_completion_sound() -> None:
    """終了音を再生する"""
    subprocess.run(["afplay", COMPLETION_SOUND], capture_output=True)


def save_text(text: str, output_path: str) -> None:
    """テキストをファイルに保存する"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"保存完了: {output_path} ({len(text)}文字)")


def parse_crop(crop_str: str) -> tuple:
    """クロップ領域の文字列をパースする"""
    try:
        parts = [int(x.strip()) for x in crop_str.split(",")]
        if len(parts) != 4:
            raise ValueError
        left, top, right, bottom = parts
        if left >= right or top >= bottom:
            print(
                f"エラー: クロップ領域が不正です (left={left}, top={top}, right={right}, bottom={bottom})\n"
                "  left < right かつ top < bottom である必要があります。\n"
                "  例: --crop 200,150,2800,1800\n"
                "       (左上が200,150 右下が2800,1800 の矩形を切り出す)"
            )
            sys.exit(1)
        return tuple(parts)
    except (ValueError, AttributeError):
        print(
            "エラー: --crop は left,top,right,bottom の形式で指定してください"
            " (例: 200,150,2800,1800)"
        )
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="Kindle本をスクリーンショット＋OCRでテキスト化するツール"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="book.txt",
        help="出力ファイルパス (デフォルト: book.txt)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"ページめくり後の待機秒数 (デフォルト: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "-l",
        "--language",
        default="ja",
        help="OCR言語 (カンマ区切りで複数指定可, デフォルト: ja)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="最大ページ数 (未指定時は自動検知で終了)",
    )
    parser.add_argument(
        "--stale-threshold",
        type=int,
        default=DEFAULT_STALE_THRESHOLD,
        help=f"変化なし連続回数の終了閾値 (デフォルト: {DEFAULT_STALE_THRESHOLD})",
    )
    parser.add_argument(
        "--forward-key",
        choices=["left", "right"],
        default="left",
        help="ページ送りキー (日本語書籍: left, 英語書籍: right, デフォルト: left)",
    )
    parser.add_argument(
        "--crop",
        default=None,
        help="クロップ領域 left,top,right,bottom (例: 100,150,1800,1000)",
    )
    parser.add_argument(
        "--no-fullscreen",
        action="store_true",
        help="フルスクリーン化をスキップする",
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=DEFAULT_START_DELAY,
        help=f"Kindle起動後の初期待機秒数 (デフォルト: {DEFAULT_START_DELAY})",
    )
    parser.add_argument(
        "--hash-threshold",
        type=int,
        default=DEFAULT_HASH_THRESHOLD,
        help=f"ページ変化判定のハミング距離閾値 (デフォルト: {DEFAULT_HASH_THRESHOLD})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # クロップ領域のパース
    crop_region = parse_crop(args.crop) if args.crop else None

    # OCR言語文字列（カンマ区切りのままSwiftに渡す）
    language = args.language

    # Kindleアクティブ化
    if not args.no_fullscreen:
        activate_kindle(args.start_delay)
    else:
        print("フルスクリーン化をスキップしました。")
        print(f"開始待機中 ({args.start_delay}秒)...")
        time.sleep(args.start_delay)

    # メインループ
    all_text = []
    previous_hash = None
    stale_count = 0
    page_number = 0

    print("テキスト抽出を開始します...")
    print("-" * 50)

    try:
        while True:
            # スクリーンショット撮影
            img = take_screenshot(crop_region)

            # ページ変化チェック
            current_hash = compute_hash(img)
            if is_page_unchanged(current_hash, previous_hash, args.hash_threshold):
                stale_count += 1
                print(
                    f"  ページ変化なし ({stale_count}/{args.stale_threshold})"
                )
                if stale_count >= args.stale_threshold:
                    print("\n本の終わりを検知しました。")
                    break
            else:
                stale_count = 0

            # OCRでテキスト抽出
            # クロップした場合は一時ファイルに保存してOCRに渡す
            if crop_region:
                img.save(SCREENSHOT_PATH)

            text = extract_text(SCREENSHOT_PATH, language)
            all_text.append(text)
            page_number += 1

            char_count = len(text)
            print(f"ページ {page_number}: {char_count}文字抽出")

            # 最大ページ数チェック
            if args.max_pages and page_number >= args.max_pages:
                print(f"\n最大ページ数 ({args.max_pages}) に到達しました。")
                break

            # ページめくり
            previous_hash = current_hash
            turn_page(args.forward_key)
            time.sleep(args.delay)

    except KeyboardInterrupt:
        print(f"\n\n中断されました。{page_number}ページ分のテキストを保存します...")

    finally:
        # 一時ファイルのクリーンアップ
        if os.path.exists(SCREENSHOT_PATH):
            os.remove(SCREENSHOT_PATH)

    # テキスト保存
    if all_text:
        combined_text = "\n\n".join(all_text)
        save_text(combined_text, args.output)
    else:
        print("抽出されたテキストがありませんでした。")

    # 終了音
    print("-" * 50)
    print(f"完了: {page_number}ページ処理しました。")
    play_completion_sound()


if __name__ == "__main__":
    main()
