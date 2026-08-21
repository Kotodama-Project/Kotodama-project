# Kotodama 5-minute tour

このページは、初めてKotodamaを見る人が **clone → 1 command → 結果を読む**
までを約5分で試すための最短導線です。外部provider、Discord、Docker、
Proxmoxへ接続せず、OSのtemporary workspaceだけで公開Company Packの候補導線を
確認します。

このtourは`read-only/candidate-only`です。実行してもHuman approval、実行権限、
runtime、Promotion、Current Truth、Final Human GO、Public Beta GOは作られません。

## 1. Cloneしてrepository rootへ移動する

PowerShell:

```powershell
git clone https://github.com/Kotodama-Project/Kotodama-project.git
Set-Location Kotodama-project
```

POSIX shell:

```bash
git clone https://github.com/Kotodama-Project/Kotodama-project.git
cd Kotodama-project
```

必要なのはGitとPythonだけです。このtourではpackage install、credential、
environment variable、network service、runtime profileを追加しません。

## 2. One-command smokeを実行する

PowerShell:

```powershell
python -S -B tools/smoke_company_pack_review_chain.py
```

POSIX shell:

```bash
python3 -S -B tools/smoke_company_pack_review_chain.py
```

`-S`はsite packageを読み込まず、`-B`は`.pyc`を書きません。commandはOSの
temporary workspaceで公開済みの13 stepsを順番に実行し、workspaceを削除して
から一行JSONだけをstdoutへ返します。caller directoryへCompany Packやreview
artifactを保存しません。

## 3. PASSを読む

成功時は、次の観測可能な境界を含む一行JSONが返ります。表示順や空白ではなく、
fieldと値を確認してください。

```json
{
  "status": "PASS",
  "temporary_workspace_deleted": true,
  "artifacts_persisted": false,
  "public_beta": "NO_GO_UNPUBLISHED"
}
```

さらに、`steps`は次の13件で、すべて`PASS`になります。

```text
create → validate → catalog → customization → public_preview → next_steps
→ review_bundle → review_bundle_verify → review_request → review_response
→ review_response_verify → decision_handoff → decision_handoff_verify
```

`claims`の各値はすべて`false`です。これは失敗ではなく、このsmokeがreviewer
identity、execution authority、Human approval、runtime、Promotion、Current Truth、
Final Human GOを証明しないという正しい境界です。

## REFUSEDだった場合

`REFUSED`はsafe stopです。途中まで成功したbundle、approval、runtime evidenceと
して扱わないでください。`failed_step`と固定された`refusal_reason`を確認し、
[Company Pack CLI Reference](COMPANY-PACK-CLI-REFERENCE.md)から該当commandの入力と
次のhandoffを確認します。temporary child outputやartifactを保存・再利用する
必要はありません。

## 4. 次に一つだけ選ぶ

| 目的 | 次に読む | 作用 |
|---|---|---|
| Company Template、Blocks、Records、MOCsの関係を知る | [Company Pack Catalog](COMPANY-PACK-CATALOG.md) | 読むだけ |
| 自分の作業candidateを作る | [Starter Walkthrough](STARTER-WALKTHROUGH.md) | local working copyを生成 |
| 14 CLIの入力・状態・handoffを調べる | [Company Pack CLI Reference](COMPANY-PACK-CLI-REFERENCE.md) | helpまたはlocal candidate検査 |
| 現在できることと未完を確認する | [STATUS](../STATUS.md) / [ROADMAP](../ROADMAP.md) | 読むだけ |

runtime profileを検討する場合も、最初に
[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)でcandidate runbookとlive receipt
の違いを確認してください。このtourからdeploy、provider接続、Discord設定、
credential/permission変更へは進みません。

## このtourが証明しないもの

- Voice capture、ASR、話者 attribution、15分rotation、Discord post、delete receipt
- Compose/Proxmoxのinstall、image pull、migration、health、restart、rollback、restore
- provider connection、protected reconciliation、独立したHuman Decision
- Promotion、Current Truth、Final Human GO、Public Beta access

公開面は引き続き`NO_GO_UNPUBLISHED`です。このtourの`PASS`は、固定された公開
Company Pack candidate chainがlocal temporary workspaceで完走したことだけを
示します。
