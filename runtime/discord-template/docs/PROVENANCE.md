# 出典とライセンス

このテンプレートの新規ソースはMITです。既存のprivate repositoryや運用設定、会話、音声、認証情報はコピーしていません。

設計上参照した公開候補：

- [Kotodama PR #69](https://github.com/Kotodama-Project/Kotodama-project/pull/69) — チャンネル別workspaceとLive接続の契約。
- [PR #71](https://github.com/Kotodama-Project/Kotodama-project/pull/71) — 静音・発話の分離とVoice-to-Work。
- [PR #59](https://github.com/Kotodama-Project/Kotodama-project/pull/59) — 訂正と実入力の版の束縛。
- [PR #67](https://github.com/Kotodama-Project/Kotodama-project/pull/67) — CLI実行証拠と独立確認の境界。

PRの存在やCI成功を、その機能の実運用成功とは扱いません。未解決レビューのあるSwarm実装をそのまま同梱していません。

使用するライブラリはpackage.jsonとpnpm-lock.yamlで固定します。依存関係のライセンスは各packageのLICENSEと公開時の第三者表示に従います。既存Kotodama本体のMITへの整理は、出典・寄与者・第三者条件を確認した別の変更として扱います。
