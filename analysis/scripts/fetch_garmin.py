"""Garmin Connect からのアクティビティデータ取得。

python-garminconnect (cyberjunky/python-garminconnect) を利用する非公式アクセス。
認証は以下の優先順で行う:

1. GARMIN_TOKENSTORE 環境変数で指定されたディレクトリの保存済みトークン
2. GARMIN_EMAIL / GARMIN_PASSWORD 環境変数による新規ログイン (MFA 対応)

トークンは `~/.garminconnect/` (既定) に保存され、次回以降は再利用される。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
except ImportError as e:  # pragma: no cover - 実行環境で明示
    raise SystemExit(
        "garminconnect が未インストールです。`pip install -r analysis/scripts/requirements.txt` を実行してください。"
    ) from e


log = logging.getLogger(__name__)

DEFAULT_TOKENSTORE = Path.home() / ".garminconnect"


def _tokenstore_path() -> Path:
    p = os.environ.get("GARMIN_TOKENSTORE")
    return Path(p) if p else DEFAULT_TOKENSTORE


def login() -> Garmin:
    """ログイン済みの Garmin クライアントを返す。

    可能ならトークンストアから復元。失敗時のみ email/password でログインし、
    トークンを保存する。
    """
    tokenstore = _tokenstore_path()
    try:
        client = Garmin()
        client.login(str(tokenstore))
        log.info("Garmin: 保存済みトークンで認証成功 (%s)", tokenstore)
        return client
    except (FileNotFoundError, GarminConnectAuthenticationError) as e:
        log.info("Garmin: トークン認証失敗 (%s) — email/password で再ログイン", e)

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "GARMIN_EMAIL / GARMIN_PASSWORD が設定されていません。"
            "初回はローカルで実行してトークンを生成してください。"
        )

    client = Garmin(email=email, password=password, is_cn=False, prompt_mfa=_prompt_mfa)
    client.login()
    tokenstore.mkdir(parents=True, exist_ok=True)
    client.garth.dump(str(tokenstore))
    log.info("Garmin: 新規ログイン完了、トークンを %s に保存", tokenstore)
    return client


def _prompt_mfa() -> str:
    """MFA コード入力プロンプト。

    CI/スケジュール実行では MFA が通らないため、事前にローカルで
    トークンを生成しておくこと。
    """
    code = os.environ.get("GARMIN_MFA_CODE")
    if code:
        return code
    return input("Garmin MFA コードを入力してください: ").strip()


def list_activities(client: Garmin, start: date, limit: int = 50) -> list[dict[str, Any]]:
    """`start` 以降に開始されたランニング系アクティビティ一覧を返す。"""
    # Garmin の API は limit 方式のため、新しい順に最大 limit 件取得して日付で絞る
    raw = client.get_activities(0, limit)
    out = []
    for a in raw:
        type_key = (a.get("activityType") or {}).get("typeKey", "")
        if "running" not in type_key and type_key not in {"treadmill_running", "trail_running", "track_running"}:
            continue
        start_str = a.get("startTimeLocal") or a.get("startTimeGMT")
        if not start_str:
            continue
        try:
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.date() < start:
            continue
        out.append(a)
    out.sort(key=lambda x: x.get("startTimeLocal", ""))
    return out


def fetch_activity_detail(client: Garmin, activity_id: int | str) -> dict[str, Any]:
    """1 アクティビティの詳細データ一式を取得する。"""
    detail: dict[str, Any] = {"activity_id": activity_id}
    detail["summary"] = client.get_activity(activity_id)
    try:
        detail["splits"] = client.get_activity_splits(activity_id)
    except Exception as e:  # noqa: BLE001
        log.warning("splits 取得失敗 (%s): %s", activity_id, e)
        detail["splits"] = None
    try:
        detail["hr_zones"] = client.get_activity_hr_in_timezones(activity_id)
    except Exception as e:  # noqa: BLE001
        log.warning("hr_zones 取得失敗 (%s): %s", activity_id, e)
        detail["hr_zones"] = None
    try:
        # maxChartSize/maxPolylineSize は詳細時系列。取り過ぎると重いので適度に。
        detail["details"] = client.get_activity_details(activity_id, maxchart=2000, maxpoly=2000)
    except Exception as e:  # noqa: BLE001
        log.warning("details 取得失敗 (%s): %s", activity_id, e)
        detail["details"] = None
    return detail


def fetch_wellness(client: Garmin, d: date) -> dict[str, Any]:
    """リカバリー指標 (睡眠・HRV・安静時HR)。失敗時は空で返す。"""
    wellness: dict[str, Any] = {"date": d.isoformat()}
    iso = d.isoformat()
    for key, fn in [
        ("sleep", lambda: client.get_sleep_data(iso)),
        ("hrv", lambda: client.get_hrv_data(iso)),
        ("rhr", lambda: client.get_rhr_day(iso)),
        ("stress", lambda: client.get_stress_data(iso)),
    ]:
        try:
            wellness[key] = fn()
        except Exception as e:  # noqa: BLE001
            log.debug("wellness %s 取得失敗: %s", key, e)
            wellness[key] = None
    return wellness


def save_raw(data: dict[str, Any], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def iter_new_activities(
    client: Garmin,
    since: date,
    processed_ids: Iterable[str],
    limit: int = 50,
) -> Iterable[dict[str, Any]]:
    seen = set(str(x) for x in processed_ids)
    for a in list_activities(client, since, limit=limit):
        aid = str(a.get("activityId"))
        if aid in seen:
            continue
        yield a


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    c = login()
    for a in list_activities(c, date.today() - timedelta(days=7)):
        print(a.get("activityId"), a.get("startTimeLocal"), a.get("activityName"))
