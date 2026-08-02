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
- [Company pack customization checklist](docs/CUSTOMIZATION-CHECKLIST.md)
- [Company pack review bundle](docs/REVIEW-BUNDLE.md)
- [Candidate-bound review workflow](docs/REVIEW-WORKFLOW.md)
- [Compose / Proxmox installation lifecycle](docs/INSTALLATION-LIFECYCLE.md)
- [Compose minimum runbook](docs/COMPOSE-MINIMUM-RUNBOOK.md)
- [Proxmox segmented runbook](docs/PROXMOX-SEGMENTED-RUNBOOK.md)
- [Compose minimum data-plane skeleton](runtime/compose-minimum/README.md)
- [資格情報非開示のResolved Compose Candidate](docs/RESOLVED-COMPOSE-CANDIDATE.md)
- [read-only Compose Image Availability Preflight](docs/IMAGE-AVAILABILITY-PREFLIGHT.md)
- [Protected Compose Evidence Attestation](docs/PROTECTED-COMPOSE-EVIDENCE-ATTESTATION.md)
- [One-Use Compose Attestation Evaluation](docs/ONE-USE-COMPOSE-ATTESTATION-EVALUATION.md)
- [Attestation Nonce Store Checkpoint](docs/ATTESTATION-NONCE-STORE-CHECKPOINT.md)
- [Attestation Nonce Store Checkpoint Chain](docs/ATTESTATION-NONCE-STORE-CHECKPOINT-CHAIN.md)
- [テンプレートカタログ](templates/README.md)
- [Governed Record カタログ](templates/records/README.md)
- [動くCompany starter example](examples/company-starter/README.md)
- [テンプレート検証方法](docs/VALIDATION.md)

## Try the starter

Python以外の追加dependencyは不要です。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools/create_company_pack.py my-company work/my-company
python tools/check_company_pack_customization.py work/my-company
python tools/validate_template_pack.py examples/company-starter
python tools/validate_installation_lifecycle.py examples/installation-lifecycle/compose-minimum.json
python tools/validate_installation_lifecycle.py examples/installation-lifecycle/proxmox-segmented.json
python tools/validate_compose_minimum_skeleton.py runtime/compose-minimum
python -m unittest discover -s tests -v
```

initializerは元exampleや既存targetを上書きせず、pack IDと3 MOCを再束縛し、22文書を`draft`にしてからvalidatorを通します。customization checkerは残る19の組織固有placeholderと46のreview項目、静的には証明できない5のevidence項目を分離します。placeholderを閉じた後は`python tools/build_company_pack_review_bundle.py work/my-company`で、manifest・Blocks・MOCs・Recordsの全22ファイルをSHA-256へ固定したreview候補を作れます。保存したbundleは`python tools/verify_company_pack_review_bundle.py BUNDLE_JSON PACK_DIRECTORY`で再照合できます。MATCHも承認やPublic Beta GOではありません。starterには、Source IntakeからPromotion Decision Recordまでの9 Block、その出力を受け取る9種のGoverned Recordテンプレート、3つのnavigation-only MOCが含まれます。Capability GrantなしのChange、Human evidenceなしのPromotion Decisionをflow contractが拒否し、Block順序、入出力、MOCの完全順序・目的別部分列、Block出力とRecordの一対一対応をvalidatorで検査できます。Compose minimum / Proxmox segmentedについては、secret-freeな6フェーズのinstallation lifecycle契約とrunbookを公開しています。ComposeにはCompany DB / Evidence metadata Storeの実行候補skeletonがあります。private process environmentで設定を解決し、password、image repository、host pathを出さずにproject namespace、image digest、network、volume、migrationを候補JSONへ固定するCLIもあります。設定解決済み候補はruntime preflightへの入力であり、image取得・起動・migration・restoreのlive receiptではありません。最初の編集方法は[Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)を参照してください。

Compose候補の設定解決には、別途Docker CLI / Compose pluginとprivate process environmentが必要です。手順は[Resolved Compose Candidate](docs/RESOLVED-COMPOSE-CANDIDATE.md)を参照してください。既存local imageのdigest一致だけをread-onlyで確認する場合は[Compose Image Availability Preflight](docs/IMAGE-AVAILABILITY-PREFLIGHT.md)を使えます。imageがなくても自動取得や起動はしません。保存snapshotの再検査はhistorical self-digest/candidate bindingだけで、署名された真正性、freshness、複数queryのatomicity、current stateを証明しません。外部runnerが報告したclean-install/migration結果を安全なhash bindingへまとめる場合は[Clean Install / Migration Evidence Candidate](docs/CLEAN-INSTALL-MIGRATION-EVIDENCE-CANDIDATE.md)を使えます。[Protected Compose Evidence Attestation](docs/PROTECTED-COMPOSE-EVIDENCE-ATTESTATION.md)はOpenSSH署名とpoint-in-time policyを検査し、[One-Use Compose Attestation Evaluation](docs/ONE-USE-COMPOSE-ATTESTATION-EVALUATION.md)は同一bound SQLite store内でnonceを一度だけ原子的に予約します。[Attestation Nonce Store Checkpoint](docs/ATTESTATION-NONCE-STORE-CHECKPOINT.md)はprivate storeの署名済みpoint-in-time snapshotと直前checkpointへの1リンクを検証し、[Attestation Nonce Store Checkpoint Chain](docs/ATTESTATION-NONCE-STORE-CHECKPOINT-CHAIN.md)は独立pinと一致する`ssh-keygen` exact bytesを使って、self-contained private bundle内のGenesis-to-current path全体とopened-object copyで照合したstoreのlogical equivalenceを再帰検証します。それでもbinary vendor authority、外部anchorの権威、trusted clock、authoritative complete history、parallel branch不存在、actual store continuity、restore実行、reported executionの真実性、current state、Public Beta GOは証明しません。

## Public Beta まで

Voice runtime の候補は fail-closed で検証中です。実際の公開には、15分単位の文字起こし投稿、話者 attribution、保持期限内の削除、独立検証、対象候補に対する Final Human GO が必要です。

公開プレビューは閲覧できますが、現時点で音声を送信したり Discord Bot を招待したりしないでください。

## License

ライセンスはまだ決定していません。明示的なライセンスが追加されるまで、再利用・再配布の許諾を意味しません。
