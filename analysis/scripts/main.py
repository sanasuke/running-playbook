"""エントリポイント: Garmin から新着ランを取得し、分析レポートを生成する。

使い方:
    # 直近 14 日のラン (まだレポート未生成のもの) を処理
    python analysis/scripts/main.py

    # 過去日数を指定
    python analysis/scripts/main.py --days 30

    # 特定の activity id を再分析（既存レポート上書き）
    python analysis/scripts/main.py --activity-id 12345678901

    # 生データの JSON を data/ にキャッシュする
    python analysis/scripts/main.py --save-raw
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
ANALYSIS_ROOT = HERE.parent

# スクリプト同ディレクトリからの相対 import を許容
sys.path.insert(0, str(HERE))

import fetch_garmin  # noqa: E402
from analyze_run import analyze  # noqa: E402
from generate_report import report_filename, write_report  # noqa: E402


log = logging.getLogger("garmin-analysis")


def load_config() -> dict:
    with (ANALYSIS_ROOT / "config.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def existing_activity_ids(reports_dir: Path) -> set[str]:
    ids: set[str] = set()
    for p in reports_dir.glob("*.md"):
        # ファイル名末尾の _{activity_id}.md を拾う
        stem = p.stem
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            ids.add(parts[1])
    return ids


def process_one(raw: dict, config: dict, reports_dir: Path, save_raw: Path | None) -> Path:
    if save_raw is not None:
        fetch_garmin.save_raw(raw, save_raw / f"{raw['activity_id']}.json")
    ra = analyze(raw, config)
    out = write_report(ra, reports_dir)
    log.info("レポート生成: %s", out.relative_to(REPO_ROOT))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Garmin 自動ランニング分析")
    parser.add_argument("--days", type=int, default=14, help="過去何日分を対象にするか")
    parser.add_argument(
        "--activity-id",
        type=str,
        help="特定の activity id のみ処理 (既存レポートは上書き)",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="Garmin からの生 JSON を analysis/data/ に保存",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    config = load_config()
    reports_dir = ANALYSIS_ROOT / "reports"
    data_dir = ANALYSIS_ROOT / "data" if args.save_raw else None

    client = fetch_garmin.login()

    if args.activity_id:
        log.info("単一 activity %s を処理", args.activity_id)
        raw = fetch_garmin.fetch_activity_detail(client, args.activity_id)
        process_one(raw, config, reports_dir, data_dir)
        return 0

    since = date.today() - timedelta(days=args.days)
    processed = existing_activity_ids(reports_dir)
    log.info("%s 以降のランを確認 (既存 %d 件)", since, len(processed))

    count = 0
    for summary in fetch_garmin.iter_new_activities(client, since, processed, limit=100):
        aid = summary.get("activityId")
        log.info("新規ラン検出: %s %s", aid, summary.get("activityName"))
        raw = fetch_garmin.fetch_activity_detail(client, aid)
        process_one(raw, config, reports_dir, data_dir)
        count += 1

    log.info("完了: %d 件のレポートを生成", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
