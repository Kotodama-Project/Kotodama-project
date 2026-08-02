# Kotodama

会話を、監査可能な意図・仕事・学習へ。

Kotodama は、Discord をはじめとする会話や音声を入力として、人間の意図を尊重しながら、確認可能なタスク・成果物・判断記録へ変換するためのプロジェクトです。

> [!IMPORTANT]
> このリポジトリは **Incomplete Public Preview** です。Public Beta の利用受付、Discord 招待、公開 Voice Bot はまだ提供していません。

## 目指していること

- Discord Voice の音声を高精度に文字起こしする
- 発言者と発言内容を結び付ける
- 会話から確認可能な handoff を生成する
- 判断・実行・検証を追跡できる証拠鎖として残す
- ローカル優先で、音声・文字起こし・保持期間を明確に管理する

## 現在の公開範囲

現在公開しているのは、プロジェクトの方向性、状態、ロードマップ、テンプレート設計、最小Company starter、schema、validator、テストです。実音声、文字起こし corpus、認証情報、Discord の非公開識別子は含みません。

- [現在の状態](STATUS.md)
- [公開までのロードマップ](ROADMAP.md)
- [Company Template / Blocks / MOCs の使い方](docs/TEMPLATE-GUIDE.md)
- [3分で試すCompany starter](docs/STARTER-WALKTHROUGH.md)
- [テンプレートカタログ](templates/README.md)
- [Governed Record カタログ](templates/records/README.md)
- [動くCompany starter example](examples/company-starter/README.md)
- [テンプレート検証方法](docs/VALIDATION.md)

## Try the starter

Python以外の追加dependencyは不要です。

```powershell
python tools/validate_template_pack.py examples/company-starter
python -m unittest discover -s tests -v
```

starterには、Source IntakeからPromotion Decision Recordまでの9 Blockと、その出力を受け取る9種のGoverned Recordテンプレートが含まれます。Capability GrantなしのChange、Human evidenceなしのPromotion Decisionをflow contractが拒否し、Block順序、入出力、MOCの読み順、Block出力とRecordの一対一対応をvalidatorで検査できます。最初の編集方法は[Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)を参照してください。

## Public Beta まで

Voice runtime の候補は fail-closed で検証中です。実際の公開には、15分単位の文字起こし投稿、話者 attribution、保持期限内の削除、独立検証、対象候補に対する Final Human GO が必要です。

公開プレビューは閲覧できますが、現時点で音声を送信したり Discord Bot を招待したりしないでください。

## License

ライセンスはまだ決定していません。明示的なライセンスが追加されるまで、再利用・再配布の許諾を意味しません。
