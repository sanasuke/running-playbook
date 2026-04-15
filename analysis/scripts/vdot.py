"""Daniels VDOT ベースのトレーニングペース計算。

Daniels' Running Formula の VDOT 表に基づく参照値を保持する。
値は km あたり秒で、近似値（プロトタイプ用途）。VDOT が表の中間値の場合は
線形補間を行う。

Zones:
    E (Easy):       有酸素持久走 (範囲: min/max)
    M (Marathon):   マラソンペース
    T (Threshold):  閾値（LT）ペース
    I (Interval):   VO2max インターバルペース
    R (Repetition): レペティションペース（400m 相当）
"""

from __future__ import annotations

from dataclasses import dataclass


# 秒/km（R のみ 400m あたり秒ではなく km 換算）
# 出典: Daniels' Running Formula 3rd ed. の VDOT 表を km 換算。
VDOT_TABLE: dict[int, dict[str, float | tuple[float, float]]] = {
    40: {"E": (329, 363), "M": 289, "T": 272, "I": 248, "R": 238},
    42: {"E": (320, 352), "M": 281, "T": 264, "I": 241, "R": 231},
    44: {"E": (311, 343), "M": 273, "T": 257, "I": 234, "R": 225},
    45: {"E": (307, 339), "M": 270, "T": 253, "I": 231, "R": 221},
    46: {"E": (303, 335), "M": 266, "T": 250, "I": 228, "R": 218},
    47: {"E": (299, 331), "M": 263, "T": 247, "I": 226, "R": 215},
    48: {"E": (296, 327), "M": 259, "T": 244, "I": 223, "R": 213},
    49: {"E": (292, 323), "M": 256, "T": 241, "I": 220, "R": 210},
    50: {"E": (289, 319), "M": 253, "T": 238, "I": 217, "R": 207},
    52: {"E": (283, 312), "M": 246, "T": 232, "I": 212, "R": 202},
    54: {"E": (276, 305), "M": 240, "T": 226, "I": 207, "R": 198},
    55: {"E": (273, 302), "M": 237, "T": 223, "I": 204, "R": 195},
    56: {"E": (270, 298), "M": 234, "T": 221, "I": 201, "R": 193},
    57: {"E": (267, 295), "M": 232, "T": 218, "I": 199, "R": 191},
    58: {"E": (264, 292), "M": 229, "T": 216, "I": 196, "R": 188},
    59: {"E": (262, 289), "M": 227, "T": 213, "I": 194, "R": 186},
    60: {"E": (259, 286), "M": 224, "T": 211, "I": 192, "R": 184},
    62: {"E": (253, 280), "M": 219, "T": 206, "I": 187, "R": 180},
    65: {"E": (245, 271), "M": 212, "T": 199, "I": 181, "R": 174},
}

ZONES = ["E", "M", "T", "I", "R"]


@dataclass
class PaceZone:
    name: str
    sec_per_km: float | None = None          # 単一値ゾーン
    sec_per_km_min: float | None = None      # 範囲ゾーン (E)
    sec_per_km_max: float | None = None

    def contains(self, sec_per_km: float, tolerance_pct: float = 0.0) -> bool:
        tol = (sec_per_km * tolerance_pct / 100.0)
        if self.sec_per_km is not None:
            return abs(sec_per_km - self.sec_per_km) <= tol
        lo = (self.sec_per_km_min or 0) - tol
        hi = (self.sec_per_km_max or 9999) + tol
        return lo <= sec_per_km <= hi

    def format(self) -> str:
        if self.sec_per_km is not None:
            return format_pace(self.sec_per_km)
        return f"{format_pace(self.sec_per_km_min)}–{format_pace(self.sec_per_km_max)}"


def format_pace(sec_per_km: float | None) -> str:
    if sec_per_km is None:
        return "-"
    m = int(sec_per_km // 60)
    s = int(round(sec_per_km - m * 60))
    if s == 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}"


def _interp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lookup_raw(vdot: float, zone: str) -> float | tuple[float, float]:
    keys = sorted(VDOT_TABLE.keys())
    if vdot <= keys[0]:
        return VDOT_TABLE[keys[0]][zone]
    if vdot >= keys[-1]:
        return VDOT_TABLE[keys[-1]][zone]
    # 補間
    lo = max(k for k in keys if k <= vdot)
    hi = min(k for k in keys if k >= vdot)
    if lo == hi:
        return VDOT_TABLE[lo][zone]
    t = (vdot - lo) / (hi - lo)
    lo_v = VDOT_TABLE[lo][zone]
    hi_v = VDOT_TABLE[hi][zone]
    if isinstance(lo_v, tuple):
        return (_interp(lo_v[0], hi_v[0], t), _interp(lo_v[1], hi_v[1], t))
    return _interp(lo_v, hi_v, t)


def paces_for(vdot: float) -> dict[str, PaceZone]:
    result: dict[str, PaceZone] = {}
    for zone in ZONES:
        raw = _lookup_raw(vdot, zone)
        if isinstance(raw, tuple):
            result[zone] = PaceZone(zone, sec_per_km_min=raw[0], sec_per_km_max=raw[1])
        else:
            result[zone] = PaceZone(zone, sec_per_km=raw)
    return result


def classify_pace(sec_per_km: float, vdot: float, tolerance_pct: float = 3.0) -> str:
    """ある平均ペースがどのゾーンに最も近いかを判定する。"""
    zones = paces_for(vdot)
    # E は範囲なので範囲内なら即確定
    if zones["E"].contains(sec_per_km, tolerance_pct=0):
        return "E"
    # E より遅い場合
    if sec_per_km > zones["E"].sec_per_km_max:  # type: ignore[operator]
        return "<E"  # リカバリー/ウォームアップ相当
    # 単一ポイントゾーンに近いものを探す
    best = None
    best_diff = float("inf")
    for name in ["M", "T", "I", "R"]:
        z = zones[name]
        if z.sec_per_km is None:
            continue
        diff = abs(sec_per_km - z.sec_per_km) / z.sec_per_km * 100
        if diff < best_diff:
            best_diff = diff
            best = name
    if best and best_diff <= tolerance_pct:
        return best
    if best and best_diff <= tolerance_pct * 2:
        return f"~{best}"
    if sec_per_km < zones["R"].sec_per_km:  # type: ignore[operator]
        return ">R"
    return "?"


if __name__ == "__main__":
    import sys
    v = float(sys.argv[1]) if len(sys.argv) > 1 else 47
    print(f"VDOT {v} のトレーニングペース (min:sec/km):")
    for name, z in paces_for(v).items():
        print(f"  {name}: {z.format()}")
