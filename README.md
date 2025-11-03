# 07_codex_runner

Render 常駐サービスとして Slack 指示を GitHub Issue に同期するランナーを実装します。

- 役割: 社長室の 24 時間対応自動化基盤
- 主な機能:
  - Slack `/codex` 指示をポーリングし GitHub Issue 化
  - 健康監視用 HTTP エンドポイント (`/healthz`)
  - 手動トリガー用同期エンドポイント (`/sync-now`)
- 運用:
  - Render の Web Service として常時稼働させる
  - 永続カーソルは `/var/data/codex-runner/state.json` に保存
  - 環境変数で Slack/GitHub トークンを注入
