"""RunAnalysis から Markdown レポートを生成する。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from analyze_run import RunAnalysis
from vdot import format_pace


def _fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _slug(name: str, limit: int = 40) -> str:
    import re
    s = re.sub(r"[^\w一-龯ぁ-んァ-ヶー]+", "-", name, flags=re.UNICODE).strip("-")
    return (s[:limit] or "run").lower()


def report_filename(ra: RunAnalysis) -> str:
    try:
        dt = datetime.fromisoformat(ra.start_local.replace("Z", "+00:00"))
        date_part = dt.strftime("%Y-%m-%d_%H%M")
    except Exception:  # noqa: BLE001
        date_part = ra.activity_id
    return f"{date_part}_{_slug(ra.name)}_{ra.activity_id}.md"


def build(ra: RunAnalysis) -> str:
    lines: list[str] = []
    lines.append(f"# {ra.name}")
    lines.append("")
    lines.append(f"- **Activity ID**: {ra.activity_id}")
    lines.append(f"- **開始**: {ra.start_local}")
    lines.append(f"- **種別**: {ra.activity_type}")
    lines.append(f"- **距離**: {ra.distance_km:.2f} km")
    lines.append(f"- **時間**: {_fmt_duration(ra.duration_sec)}")
    lines.append(f"- **平均ペース**: {format_pace(ra.avg_pace_sec_per_km)} /km")
    if ra.avg_hr:
        lines.append(f"- **平均HR**: {ra.avg_hr:.0f} bpm (最大 {ra.max_hr:.0f})")
    if ra.cadence:
        lines.append(f"- **ケイデンス**: {ra.cadence:.0f} spm")
    if ra.elevation_gain_m:
        lines.append(f"- **累積標高**: {ra.elevation_gain_m:.0f} m")
    if ra.vo2max_estimate:
        lines.append(f"- **VO2max推定**: {ra.vo2max_estimate}")
    if ra.training_load:
        lines.append(f"- **Training Load**: {ra.training_load}")
    if ra.training_effect_aerobic is not None or ra.training_effect_anaerobic is not None:
        lines.append(
            f"- **TE**: 有酸素 {ra.training_effect_aerobic or 0:.1f} / "
            f"無酸素 {ra.training_effect_anaerobic or 0:.1f}"
        )
    lines.append("")

    # 計画との比較
    lines.append("## 計画との比較")
    lines.append("")
    lines.append(f"- VDOT {ra.vdot_used} ベースのゾーン判定: **{ra.zone_guess}**")
    lines.append(f"- {ra.pace_vs_plan}")
    if ra.hr_drift_pct is not None:
        lines.append(f"- HR drift: **{ra.hr_drift_pct}%** (前半→後半)")
    lines.append("")

    # ペース基準表
    lines.append("## VDOT ペース基準")
    lines.append("")
    lines.append("| Zone | Pace (/km) |")
    lines.append("| --- | --- |")
    for z in ("E", "M", "T", "I", "R"):
        if z in ra.pace_zones:
            lines.append(f"| {z} | {ra.pace_zones[z]} |")
    lines.append("")

    # HR ゾーン
    if ra.hr_zone_time_sec:
        lines.append("## HR ゾーン別時間")
        lines.append("")
        lines.append("| Zone | 時間 |")
        lines.append("| --- | --- |")
        total = sum(ra.hr_zone_time_sec.values()) or 1
        for z in sorted(ra.hr_zone_time_sec):
            secs = ra.hr_zone_time_sec[z]
            pct = secs / total * 100
            lines.append(f"| {z} | {_fmt_duration(secs)} ({pct:.0f}%) |")
        lines.append("")

    # スプリット
    if ra.splits:
        lines.append("## スプリット")
        lines.append("")
        lines.append("| # | 距離 | 時間 | ペース | HR | Zone |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for s in ra.splits:
            hr = f"{s.avg_hr:.0f}" if s.avg_hr else "-"
            lines.append(
                f"| {s.idx} | {s.distance_km:.2f}km | {_fmt_duration(s.duration_sec)} | "
                f"{format_pace(s.pace_sec_per_km)} | {hr} | {s.zone_guess} |"
            )
        lines.append("")

    # ノート
    if ra.notes:
        lines.append("## ノート・警告")
        lines.append("")
        for n in ra.notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*自動生成レポート: `analysis/scripts/main.py`*")
    return "\n".join(lines)


def write_report(ra: RunAnalysis, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / report_filename(ra)
    path.write_text(build(ra), encoding="utf-8")
    return path
