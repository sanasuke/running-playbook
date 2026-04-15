"""単一ランの分析ロジック。

Garmin API のサマリ + スプリット + HR タイムゾーンから、
VDOT ベースのペース評価・HR drift・ゾーン分布などを算出する。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from vdot import PaceZone, classify_pace, format_pace, paces_for


@dataclass
class SplitAnalysis:
    idx: int
    distance_km: float
    duration_sec: float
    pace_sec_per_km: float
    avg_hr: float | None
    zone_guess: str


@dataclass
class RunAnalysis:
    activity_id: str
    start_local: str
    name: str
    activity_type: str
    distance_km: float
    duration_sec: float
    avg_pace_sec_per_km: float
    avg_hr: float | None
    max_hr: float | None
    cadence: float | None
    elevation_gain_m: float | None
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None
    training_load: float | None
    vo2max_estimate: float | None
    hr_drift_pct: float | None
    hr_zone_time_sec: dict[str, float] = field(default_factory=dict)
    splits: list[SplitAnalysis] = field(default_factory=list)
    zone_guess: str = "?"
    vdot_used: float = 0.0
    pace_zones: dict[str, str] = field(default_factory=dict)
    pace_vs_plan: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["splits"] = [asdict(s) for s in self.splits]
        return d


def _pace(distance_m: float | None, duration_s: float | None) -> float:
    if not distance_m or not duration_s or distance_m <= 0:
        return 0.0
    return duration_s / (distance_m / 1000.0)


def _safe(d: dict[str, Any], *keys, default=None):
    for k in keys:
        if d is None:
            return default
        d = d.get(k) if isinstance(d, dict) else default
        if d is None:
            return default
    return d


def analyze(raw: dict[str, Any], config: dict[str, Any]) -> RunAnalysis:
    summary = raw.get("summary") or {}
    splits_raw = raw.get("splits") or {}
    hr_zones_raw = raw.get("hr_zones")

    vdot = float(config["athlete"]["current_vdot"])
    pace_zones = paces_for(vdot)

    distance_m = summary.get("distance") or 0.0
    duration_s = summary.get("duration") or summary.get("movingDuration") or 0.0
    avg_pace = _pace(distance_m, duration_s)

    activity_type = _safe(summary, "activityType", "typeKey", default="running")
    name = summary.get("activityName") or "Run"
    start_local = summary.get("startTimeLocal") or ""
    activity_id = str(summary.get("activityId") or raw.get("activity_id") or "")

    # HR zones — Garmin の戻り値は配列 [{zoneNumber, secsInZone, ...}, ...]
    zone_time: dict[str, float] = {}
    if isinstance(hr_zones_raw, list):
        for entry in hr_zones_raw:
            zn = entry.get("zoneNumber")
            secs = entry.get("secsInZone") or 0.0
            if zn is not None:
                zone_time[f"Z{zn}"] = float(secs)

    # スプリット解析
    split_list: list[SplitAnalysis] = []
    lap_source = splits_raw.get("lapDTOs") if isinstance(splits_raw, dict) else None
    if lap_source:
        for i, lap in enumerate(lap_source):
            dist_m = lap.get("distance") or 0.0
            dur_s = lap.get("duration") or 0.0
            if dist_m <= 0 or dur_s <= 0:
                continue
            p = _pace(dist_m, dur_s)
            split_list.append(
                SplitAnalysis(
                    idx=i + 1,
                    distance_km=round(dist_m / 1000.0, 3),
                    duration_sec=round(dur_s, 1),
                    pace_sec_per_km=round(p, 1),
                    avg_hr=lap.get("averageHR"),
                    zone_guess=classify_pace(p, vdot, config["analysis"]["pace_tolerance_pct"]),
                )
            )

    # HR drift: 前半/後半の avg HR 比較（スプリットから推定）
    hr_drift = None
    hr_splits = [s for s in split_list if s.avg_hr]
    if len(hr_splits) >= 4:
        half = len(hr_splits) // 2
        first = sum(s.avg_hr for s in hr_splits[:half]) / half  # type: ignore[misc]
        second = sum(s.avg_hr for s in hr_splits[half : half * 2]) / half  # type: ignore[misc]
        if first:
            hr_drift = round((second - first) / first * 100.0, 2)

    zone_guess = classify_pace(avg_pace, vdot, config["analysis"]["pace_tolerance_pct"]) if avg_pace else "?"

    ra = RunAnalysis(
        activity_id=activity_id,
        start_local=start_local,
        name=name,
        activity_type=activity_type,
        distance_km=round(distance_m / 1000.0, 3) if distance_m else 0.0,
        duration_sec=round(duration_s, 1) if duration_s else 0.0,
        avg_pace_sec_per_km=round(avg_pace, 1),
        avg_hr=summary.get("averageHR"),
        max_hr=summary.get("maxHR"),
        cadence=summary.get("averageRunningCadenceInStepsPerMinute"),
        elevation_gain_m=summary.get("elevationGain"),
        training_effect_aerobic=summary.get("aerobicTrainingEffect"),
        training_effect_anaerobic=summary.get("anaerobicTrainingEffect"),
        training_load=summary.get("activityTrainingLoad") or summary.get("trainingLoad"),
        vo2max_estimate=summary.get("vO2MaxValue"),
        hr_drift_pct=hr_drift,
        hr_zone_time_sec=zone_time,
        splits=split_list,
        zone_guess=zone_guess,
        vdot_used=vdot,
        pace_zones={z: pz.format() for z, pz in pace_zones.items()},
    )

    # 計画との比較 (簡易): 曜日ベースで Q/L/E を推定
    ra.pace_vs_plan = _compare_with_plan(ra, config)

    # ノート（ITB リスク等）
    _add_notes(ra, config)

    return ra


def _weekday_name(iso: str) -> str | None:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%A")
    except Exception:  # noqa: BLE001
        return None


def _compare_with_plan(ra: RunAnalysis, config: dict[str, Any]) -> str:
    wd = _weekday_name(ra.start_local) or "?"
    sched = config.get("weekly_schedule", {})
    is_q = wd in sched.get("Q_days", [])
    is_l = wd == sched.get("L_day")

    if is_q:
        expected = "Q (T/I/R 主体)"
        ok = ra.zone_guess in {"T", "I", "R", "~T", "~I", "~R"}
        return f"{wd}: {expected} → 実績 {ra.zone_guess} ({'OK' if ok else '要確認'})"
    if is_l:
        expected = "L (E ペース長時間)"
        ok = ra.zone_guess in {"E", "<E"}
        return f"{wd}: {expected} → 実績 {ra.zone_guess} ({'OK' if ok else '要確認'})"
    expected = "E (リカバリー/有酸素)"
    ok = ra.zone_guess in {"E", "<E"}
    return f"{wd}: {expected} → 実績 {ra.zone_guess} ({'OK' if ok else '要確認'})"


def _add_notes(ra: RunAnalysis, config: dict[str, Any]) -> None:
    athlete = config.get("athlete", {})
    analysis_cfg = config.get("analysis", {})

    # HR drift 警告
    drift_tol = analysis_cfg.get("hr_drift_tolerance_pct", 5.0)
    if ra.hr_drift_pct is not None and ra.hr_drift_pct > drift_tol and ra.zone_guess in {"E", "<E"}:
        ra.notes.append(
            f"⚠ HR drift {ra.hr_drift_pct}% > 許容 {drift_tol}% — 有酸素効率低下/脱水/暑熱の可能性"
        )

    # E ペース走で HR が高すぎ
    max_hr = athlete.get("max_hr")
    ceiling = analysis_cfg.get("e_pace_hr_ceiling_pct", 0.78)
    if max_hr and ra.avg_hr and ra.zone_guess in {"E", "<E"}:
        if ra.avg_hr / max_hr > ceiling:
            ra.notes.append(
                f"⚠ E ペースなのに平均HR {ra.avg_hr:.0f} > {int(max_hr * ceiling)} "
                f"({int(ceiling*100)}% MaxHR) — 強度上げ過ぎ"
            )

    # ITB リカバリー中の警告
    if athlete.get("itb_recovery"):
        # 1 本のランで 20km 超えたらタグ
        if ra.distance_km > 20:
            ra.notes.append("ℹ ITB リカバリー中: 20km 超のラン。膝の違和感をチェック。")
        # R/I のスプリットがあると高強度なので注意
        high = [s for s in ra.splits if s.zone_guess in {"R", "I"}]
        if len(high) >= 3:
            ra.notes.append(f"ℹ ITB リカバリー中: I/R 強度スプリット {len(high)} 本 — 無理せず本数管理。")

    # Training Effect の極端値
    if ra.training_effect_aerobic and ra.training_effect_aerobic >= 4.5:
        ra.notes.append(f"ℹ 有酸素TE {ra.training_effect_aerobic} — highly impacting。翌日リカバリー推奨。")
    if ra.training_effect_anaerobic and ra.training_effect_anaerobic >= 4.0:
        ra.notes.append(f"ℹ 無酸素TE {ra.training_effect_anaerobic} — 高強度。連日高強度は避ける。")
