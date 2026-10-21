# 貢献する

このrepoの目的は[README](README.md)にあります。実際の仕事で確認した不足を、小さな変更で解消します。旧Company OSの機能を完成させるためのPRは受け入れません。

実装追加はまずIssueに「実際に困った仕事・既存OpenAI機能では足りなかった点・最小の変更・完了条件」を書きます。新しい基盤やAPI wrapperを先回りして作りません。

## ローカルの確認

Python 3.12以降とGitを使います。Python packageのインストールは不要です。

```sh
python -B tools/validate_repository.py
python -B -m unittest discover -s tests -v
python -B tools/check_secrets.py
git diff --check
```

秘密値検査は固定版のGitleaksを公式配布元から一時領域へ取得し、固定SHA-256で照合します。対応環境はmacOS arm64とLinux x64です。WindowsではUbuntu CIの同じ検査を必須とし、未実行を成功としません。新規ファイルを検査する前に`git add`してindexに含めてください。

検査対象はリンク、廃止入口の再導入、workflow参照、秘密ファイルと追跡sourceです。業務データの意味的な安全性や、実サービスへの移行を証明するものではありません。

## PRと統合

目的、変更、実施した検証、未確認の影響をPRへ記載します。秘密値・私有パス・個人情報を載せません。タイトルは`type: 要約`を使います。

別agent/sessionまたは既存の自動レビューが一度diffを読み、根拠のある指摘を修正します。独立した人間のレビューとagent reviewを混同しません。
必須チェックは`Trusted repository validation`、`test (ubuntu-latest)`、`test (windows-latest)`、`Dependency review`です。最新head・base・未解決reviewと全必須checkを確認し、許可された範囲で統合します。保護を迂回しません。

大量削除は一つの廃止単位なら一つのPRにまとめられます。旧固定sourceと復旧方法を示し、削除対象の実装が本番から撤去済みとは書きません。
