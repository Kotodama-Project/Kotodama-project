# 固定coreに対する依存・OAuth修正候補

Issue #12の別候補です。従来の `security-overlay.json` と採用pinは保持します。
[`candidate.json`](candidate.json) に入力、patch、生成結果、検査のdigestと未達条件を記録します。
[`candidate.patch`](candidate.patch) は固定coreの3ファイルだけを変更します。
生成lockを手で変更するpatchは含めません。

- nanoid 3.3.18、browsers 3.0.4に加え、seroval 1.6.3、source-map-js 1.2.2、MCP client 2.2.0を親限定で指定。
- 保存したclient／token／discoveryのissuerを、読出し・refresh・revocation前に照合。
- SDKのissuerをcallbackで失わず、未刻印の旧credentialは再認証へ返す。通常の参照拒否で保存値を消さない。
- 同じgenerationでも新しいcredentialsが保存されたら、古いrefreshの成功・拒否から上書き／期限切れ通知をしない。

## 再現手順

このディレクトリのmanifestは最初のWindows観測を保持しています。後続のLinux評価では
[build・上流全suite](../linux-runtime-evaluation-2026-10-08.json)と
[限定HTTP／停止試験](../linux-http-evaluation-2026-10-08.json)が成功しました。
元のWindows失敗flagと、validatorのその記録に対する結果は過去観測の検査であり、
最新Linuxの失敗を示すものではありません。採用・providerの未受入は引き続き区別します。

配布物の整合性、任意の固定source、適用／lock生成後のbytesをそれぞれ検査できます。
これは読み取りだけで、patch適用・install・auditやtestの再実行・採用は行いません。

```text
python -S -B tools/validate_cloudflare_security_patch.py
python -S -B tools/validate_cloudflare_security_patch.py --source-core <pinned-core>
python -S -B tools/validate_cloudflare_security_patch.py --materialized-core <patched-core>
```

新しい作業コピーを `bf7f762d7fa73553284d731ab6a978d3ea17be24` へ固定し、
tracked treeがcleanで入力hashが一致することを確認します。既存の稼働copyには適用しません。
Node 24.19.0とpnpm 11.9.0を用意し、本人のprovider設定を継承しない評価環境で行います。

```text
git -C <clean-pinned-core> apply --check --index --unidiff-zero <absolute-candidate.patch>
git -C <clean-pinned-core> apply --index --unidiff-zero <absolute-candidate.patch>
pnpm install --lockfile-only --prefer-offline --ignore-scripts --no-frozen-lockfile --registry=https://registry.npmjs.org/
pnpm install --frozen-lockfile --ignore-scripts
pnpm audit --prod --json
pnpm --filter @gadgets/mcp-shared types:check
pnpm --filter @gadgets/mcp-shared test
pnpm build
```

pnpmの各commandはcore copyのrootで実行します。workspace／生成lock／sourceのbytesは
candidate.jsonと照合し、違えば観測を記録して止めます。specを書き換えて合わせません。
pnpmの生成はregistry metadataの変化でもbytesが変わるため、過去のhashを現在の証明に使いません。

## 現在の検査と残件

現物のscripts-disabled frozen install、production audit全severity 0、MCPの通常／test型検査、
19 files・251 tests、seroval／source-map／nanoidの正常API確認、recursive buildは成功しました。
buildは26 projectsを対象とし、25 build scriptsの完了を確認しています。Windowsの既存C#評価shimは
無変更で使用しており、正式なWindows supportの証拠ではありません。

**全upstream suiteはPASSしていません。** Windowsのscheduler facet試験がlocal workerdの
internal errorで失敗しました。新候補と旧2-selector overlayで同じscope試験が失敗することを
確認しましたが、共通のbaseline失敗を成功扱いしません。Linux／runtimeでの受入、ownerの
採用と独立性の受入は残ります。実credential操作、provider配備、Public Betaは行っていません。

## ライセンス

patchは [Cloudflare OSの固定公開source](https://github.com/cloudflare/cloudflare-os/tree/bf7f762d7fa73553284d731ab6a978d3ea17be24)
に対する変更で、このディレクトリの [`LICENSE`](LICENSE)（Apache-2.0）が該当します。
sourceの文脈を含むpatchと、その修正部分をApache-2.0の範囲で提供します。
Kotodama側のlicenseを上流sourceへ適用するものではありません。元のcopyright／noticeは保持します。
