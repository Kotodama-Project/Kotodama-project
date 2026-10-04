# OpenMaus / Cloudflare OS の統合契約候補

日常の入口は[OpenAI Dots](OPENAI-ALIGNMENT.md)です。この候補は、OpenMaus の agent 管理と専用画面候補の Cloudflare OS を既存の仕事へつなぐ際の設計契約を検査します。UI、connector、provider 操作、VM 管理は実装・配備しません。`PASS` はローカルの設計契約が検査に適合したという意味です。Public Beta は `NO_GO_UNPUBLISHED` です。

## 出典と適用範囲

公開候補 [#56](https://github.com/Kotodama-Project/Kotodama-project/pull/56) の head `6c6155fdfde11a7febdbf4dfc3b5e3d135810b69` から、二つの契約と schema、read-only validator、合成 fixture を現在の main 向けに再配置しました。旧 #49 の OKF registry、古い audit workflow、運用文書の写しは持ち込みません。

[#131 の判断](https://github.com/Kotodama-Project/Kotodama-project/issues/131#issuecomment-5852469259)に従い、今回は契約だけを扱います。agent の責任・route は [#34 の候補](AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md)、identity と lifecycle は [#36 の契約](PUBLIC-AGENT-LIFECYCLE-REGISTRY.md)、知識の正本と語彙は [#48](https://github.com/Kotodama-Project/Kotodama-project/pull/48) / [#61](https://github.com/Kotodama-Project/Kotodama-project/pull/61) の系統へ合わせます。独立した Task owner や知識 registry は作りません。

| 契約 | 保存した公開資料の参照 | 現在の意味 |
|---|---|---|
| OpenMaus | `milind-soni/OpenMausBot` の `600e315cb7c3f61c214488678f7e6a99a7be157d`、Apache-2.0 | #56 が読んだ公開資料の固定参照。現行 upstream との互換性や live MCP 接続は未検証 |
| Cloudflare OS | `cloudflare/cloudflare-os` の `c0b6f3e52ff0ab8d44d290647e256936e88e6b57` | #56 の歴史的な設計参照。現在の[公式 OS 採用候補](CLOUDFLARE-OS-ADOPTION.md)の選定 pin を置き換えない |
| 旧 Kotodama extension | `9a5b616c7974a37b123e024334a69dd4964ad017` の `runtime/cloudflare-os-kotodama` | 出典参照だけ。この checkout に installed extension があるという主張ではない |

第三者の出典・条件は保持します。公開候補の再配置は GUI の再配布、非公開資料の公開、第三者の権利処理完了を意味しません。[License scope](LICENSE-SCOPE.md)と[移植の出典・権利](https://github.com/Kotodama-Project/Kotodama-project/issues/25)を参照します。

## 一つの仕事と責任

OpenMaus の `primary_human_surface` は、この任意の管理構成内の論理的な表示先です。製品の日常の入口を変更する選択や、UI を配備した証拠ではありません。五つの agent group は表示と routing のための区分で、仕事と権限の独立した正本にはしません。

`canonical_owners` は [Owner Intent](OWNER-INTENT-COMPANY-AGI.md)、[#48 の知識 bundle の入口](../knowledge/index.md)、[Agent Lifecycle](PUBLIC-AGENT-LIFECYCLE-REGISTRY.md)、[Improvement Loop](IMPROVEMENT-LOOP.md) を参照します。知識の vocabulary は同 bundle の Goal / success model に合わせ、[Information Access](INFORMATION-ACCESS.md) は ACL の governing contract として扱います。ファイルの存在だけでは、実 registry や実行権限は成立しません。#48 の canonical IDs、選択済みの Task owner、route、承認の正本は、それぞれの owner に戻します。この候補は #48 の bundle 再配置を前提とします。

共有ビューは identity、authority、現在の仕事、観測時刻、verification 等の16項目と、`unknown` を含む8接続状態を必須にします。順序の変更は許容し、欠落・重複・未知の要素は拒否します。実行が止まったことと成果が検証されたことを分けます。

OpenMaus MCP の対象能力と、公開資料で未提供とされた能力は重ねません。未提供の承認、永続的な許可、データ削除、資格情報変更、VM lifecycle を成功として表示しません。Proxmox の管理面は管理 adapter に限定します。work agent の直接アクセスは契約が拒否します。

## Cloudflare の段階的な構成

Cloudflare OS は同じ論理 surface と Work identity、idempotency、停止観測を参照する任意の専用画面候補です。native Gatekeeper / Cap'n Web を使う構成を設計として保存し、iframe や別 portal による第二の管理面へ置き換えません。既存の local pilot の transport は、この契約で変更しません。

Workers / Durable Objects / Dynamic Workers、Access / Tunnel、R2、後続の Workflows / Queues / D1 / AI Gateway は段階を分けます。全 service の `enabled` は false で、provider resource は作成しません。cloud-managed OS と分離した Proxmox worker は構成候補です。production self-hosting の証明ではありません。

observation、candidate submit、apply、task completion、verification、promotion は別の状態です。表示上の identity や native approval を Kotodama の capability grant として扱いません。P0〜P3 の rollout はすべて planned で、実行・切替には対象環境に束縛した別の証拠が必要です。

## ローカル検証

```bash
python tools/validate_openmaus_integration.py --root . --format json
python tools/validate_cloudflare_os_integration.py --root .
python -m unittest discover -s tests -p 'test_openmaus_integration.py'
python -m unittest discover -s tests -p 'test_cloudflare_os_integration.py'
```

入力は [OpenMaus contract](../governance/openmaus-integration.json) / [schema](../schemas/openmaus-integration.schema.json) と [Cloudflare contract](../governance/cloudflare-os-integration.json) / [schema](../schemas/cloudflare-os-integration.schema.json) です。現在の hash-locked Python 環境で実行します。

両 validator は既存の bounded file reader と strict JSON parser を再利用します。入力ごとに256 KiB・深さ32を上限とし、非 object、重複 key、非有限値、symlink、hardlink、特殊 file を拒否します。schema の参照はローカル fragment に限定し、JSON Schema validator の構築前に検査します。入力不備は固定した failure code だけを返し、JSON / Markdown / usage diagnostics に入力値や選択した path を反映しません。

合成 fixture は形状不備、各必須表示項目、未提供能力との重複、非ローカル参照、出力境界を確認します。これらは static contract の検査です。agent 通信、native OS、provider 認証、実 VM 隔離、長時間運転、実データのアクセス取消は別の live 受入で確認します。
