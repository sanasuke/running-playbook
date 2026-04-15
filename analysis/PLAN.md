# Garmin Connect 自動ランニング分析システム — 計画メモ

## 概要

Garmin Connect からランニングデータを自動取得し、ラン単位で分析レポートを生成する仕組みを構築する。

## 背景・ユーザー情報

- Garmin Forerunner 965 使用
- リポジトリ: `sanasuke/running-playbook`（GitHub プライベート）
- 年間3サイクル計画でサブ2:50（VDOT 59）を目指すトレーニング中
  - サイクル1: 昭和記念公園ハーフ（2026/6/20, 目標 1:24–1:27, P=80km）
  - サイクル2: 水戸黄門漫遊フル（2026/10/25, 目標 2:53–2:56, P=95km）
  - サイクル3: 東京マラソン2027（2027/3/7, 目標サブ2:50, P=110km）
- 現在の VDOT: 47（ハーフ実績 1:38 前後）
- 週2回 Q 練習（月・木）＋ 土曜 L 走
- 左膝 ITB 症候群のリカバリー中
- ダニエルズのランニング・フォーミュラがトレーニングのベース

## データ取得方法

### python-garminconnect（非公式ライブラリ）

- PyPI: `pip install garminconnect`
- GitHub: https://github.com/cyberjunky/python-garminconnect
- 130+ API メソッド、認証はモバイル SSO フロー（MFA 対応）
- トークン自動更新あり（`~/.garminconnect/garmin_tokens.json`）

### 取得可能データ

- ペース推移・スプリット
- HR 推移・ゾーン別時間
- ケイデンス・ストライド
- Training Effect / Training Load
- VO2 Max 推定値
- GPS 座標（ルート）
- 睡眠・HRV・ストレス（補助データ）

## 分析項目

1. **VDOT ベース目標 vs 実績**: Q 練習の設定ペースと実績の乖離
2. **Q 練習達成度判定**: 月・木のワークアウトが計画通りか
3. **HR drift**: E ペース走での有酸素効率指標
4. **週間・サイクル単位の負荷トレンド**: 走行距離・TSS 的な推移
5. **ITB 再発リスクチェック**: 急激な距離増加やペースアップの検知
6. **リカバリー指標**: 睡眠スコア・HRV・安静時 HR の推移

## アーキテクチャ

### 推奨: Claude Code クラウドスケジュールタスク

```
Claude Code Scheduled Task (毎日1回)
  → python-garminconnect でデータ取得
  → 新規ランを検出（前回取得以降）
  → 分析ロジック実行
  → Markdown レポート生成
  → running-playbook リポジトリに commit（analysis/reports/ 配下）
```

- `claude.ai/code/scheduled` から作成
- PC オフでも Anthropic クラウド上で実行される
- GitHub リポジトリを接続して使う

### フォールバック: GitHub Actions

Claude Code のクラウド環境から Garmin SSO（sso.garmin.com）に接続できない場合はこちら。

```
GitHub Actions (cron 毎日1回)
  → python-garminconnect
  → 分析スクリプト
  → Markdown を commit
```

## 検証が必要な項目

1. **ネットワーク**: Claude Code クラウド環境から `sso.garmin.com`, `diauth.garmin.com` への接続可否
2. **認証**: Garmin の初回ログイン + MFA をどう処理するか（事前にトークン生成 → 環境変数 or シークレットで保存）
3. **トークン永続化**: クラウド環境での `garmin_tokens.json` の保存方法
4. **環境変数**: Garmin のメール・パスワードの安全な管理（Claude Code の環境設定 or GitHub Secrets）

## 実装状況 (このブランチで対応済み)

- ✅ `analysis/` ディレクトリ構造
- ✅ `config.json`: VDOT/ゾーン/サイクル/ITB 設定
- ✅ `vdot.py`: Daniels VDOT ペース表（補間対応）
- ✅ `fetch_garmin.py`: 認証・アクティビティ取得・wellness 取得
- ✅ `analyze_run.py`: ペース/HR drift/ゾーン分布/ITB 警告
- ✅ `generate_report.py`: Markdown レポート生成
- ✅ `main.py`: エントリポイント（新着検出・idempotent）
- ⏳ Claude Code スケジュールタスクでの接続検証
- ⏳ 週間・サイクル単位の集計レポート

## 次のステップ

1. ローカル PC で Garmin 認証トークンを生成
2. 手動実行で数本のランをレポート化し、出力を検証
3. Claude Code スケジュールタスクから実行できるかテスト
4. 問題なければスケジュール化、ダメなら GitHub Actions へ
5. 運用後、週次レポートや wellness 連動を拡張
