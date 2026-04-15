# Garmin 自動ランニング分析

Garmin Connect からランニングデータを取得し、Daniels VDOT ベースで
ラン単位の分析レポートを `analysis/reports/` に Markdown で生成する。

> 🚧 **プロトタイプ**: python-garminconnect は非公式ライブラリ。
> 認証フロー・API 仕様変更の影響を受ける可能性あり。

## 構成

```
analysis/
├── config.json            # VDOT・ゾーン閾値・サイクル目標
├── PLAN.md                # 設計メモ
├── reports/               # 自動生成レポート (commit 対象)
├── data/                  # 生 JSON キャッシュ (gitignore)
└── scripts/
    ├── requirements.txt
    ├── vdot.py            # Daniels VDOT ペース表と分類
    ├── fetch_garmin.py    # Garmin Connect クライアント
    ├── analyze_run.py     # ラン分析ロジック
    ├── generate_report.py # Markdown レポート生成
    └── main.py            # エントリポイント
```

## セットアップ

### 1. 依存パッケージ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r analysis/scripts/requirements.txt
```

### 2. Garmin 認証 (初回のみ、ローカルで実行)

```bash
export GARMIN_EMAIL="your-email@example.com"
export GARMIN_PASSWORD="your-password"
python analysis/scripts/fetch_garmin.py
```

- MFA が有効な場合、コードの入力を求められる
- 成功すると `~/.garminconnect/` にトークンが保存される
- 以降は email/password なしで実行可能

### 3. クラウド / CI で実行する場合

MFA プロンプトが動かないため、ローカルで生成したトークンファイルを
シークレットとして登録する。

- `GARMIN_TOKENSTORE` 環境変数でトークン保存ディレクトリを指定
- Claude Code スケジュールタスク / GitHub Actions のシークレットから展開

## 実行

### 直近 14 日のラン (未処理のみ)

```bash
python analysis/scripts/main.py
```

### 期間指定

```bash
python analysis/scripts/main.py --days 30
```

### 特定のアクティビティを再分析

```bash
python analysis/scripts/main.py --activity-id 12345678901
```

### 生 JSON をキャッシュ

```bash
python analysis/scripts/main.py --save-raw
```

## 設定 (`config.json`)

```jsonc
{
  "athlete": {
    "current_vdot": 47,        // 現在の VDOT — 定期的に更新
    "target_vdot": 59,         // 目標 VDOT
    "max_hr": 185,             // 実測値に更新すること
    "itb_recovery": true       // ITB リカバリーフラグ
  },
  "analysis": {
    "hr_drift_tolerance_pct": 5.0,   // 許容 HR drift
    "pace_tolerance_pct": 3.0,       // ゾーン判定の許容幅
    "e_pace_hr_ceiling_pct": 0.78    // E ペースの HR 上限比
  }
}
```

### VDOT を更新したら

VDOT を変えれば全ペースゾーンが自動で再計算される (`vdot.py`)。
ハーフ 1:28、フル 3:03 など新しいレース結果が出たら `current_vdot` を
上方修正する運用にする。

### ペース表の確認

```bash
python analysis/scripts/vdot.py 50
# VDOT 50 のトレーニングペース (min:sec/km):
#   E: 4:49–5:19
#   M: 4:13
#   T: 3:58
#   I: 3:37
#   R: 3:27
```

## 生成されるレポート例

```markdown
# 閾値走 4km x 2

- Activity ID: 123...
- 距離: 12.50 km
- 平均ペース: 4:15 /km
- 平均HR: 162 bpm

## 計画との比較

- VDOT 47 ベースのゾーン判定: **T**
- Thursday: Q (T/I/R 主体) → 実績 T (OK)
- HR drift: 1.2%
...
```

## アーキテクチャの意図

- **ラン単位の記録**: `reports/*.md` をコミットすることで Git 履歴が
  そのままトレーニング履歴になる
- **idempotent**: 既存レポートの activity_id は再処理しない
- **設定駆動**: VDOT/ゾーン/サイクル目標はコード変更なしで更新可能
- **ITB リカバリー配慮**: 距離・強度の急増をノートで警告

## 今後の拡張案

- 週間・サイクル単位の集計レポート (`weekly_YYYY-WW.md`)
- HR drift の正確な計算 (時系列データから)
- 気温/湿度を加味したペース補正
- Wellness (睡眠・HRV・RHR) を加えたリカバリー指標
- Claude Code スケジュールタスクで毎日自動実行
