# 根拠と確認範囲

[68項目へ](README.md)

本監査はREADME固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` の全文1163行、既存68項目、open Issue25件の本文とopen PR14件のhead/base/checks/review状態を確認した。後続のclosing/Qwen/Telegram/手動Task記述と現況訂正を含む現READMEは、[requirements.json](requirements.json) の `source.closing_readme` にUTF-8/LFのhash・行数を別途固定し、R03/R05/R37/R40/R41/R47/R50/R54/R67の補足として照合した。68項目の `source_url` は比較可能な元のREADME固定点の出典であり、現HEADのREADMEを指すURLとは主張しない。全private source・全PR差分・全履歴・全providerの実動作を監査したわけではない。

以下のE01–E12（E08を除く）は、この実行で保持した非公開の限定観測receiptへのhash binding。E08は個人Task管理とCompany本番を分ける説明のみで、個人Taskのbindingを公開しない。公開リンクは実装文脈を読むためのもので、private receiptそのものではない。第三者が公開ファイルだけで実環境観測を独立再現できると主張しない。E13は公開APIの読取。

<a id="e01"></a>
## E01 Company Pack / review / record-bound local execution

実ファイルによるPack生成、検証、再送拒否。入力Taskはsynthetic candidate。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/COMPANY-PACK-TASK-EXECUTION.md)

非公開receipt SHA-256: `111ea32d7ab448f692374e84ff688848c0435cb5219baeb3cbcd00f671b8798c`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e02"></a>
## E02 非公開の意図・制約保持候補

限定文法で制約・訂正・保留と出典を保持。一般的な意味理解や実Task実行ではない。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/README-IMPLEMENTATION-ASSESSMENT.md)

非公開receipt SHA-256: `111ea32d7ab448f692374e84ff688848c0435cb5219baeb3cbcd00f671b8798c`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e03"></a>
## E03 情報分類とread/review Gateway

local HTTPで主体・分類・read/review・期限・取消を検査。全社ACL未接続。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/INFORMATION-ACCESS.md)

非公開receipt SHA-256: `241af9ad3280c1ee20dd52964779d20cba6f4b9446bd54490fccc5e604b6b79d`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e04"></a>
## E04 公式OSの文書・復元評価

認証済み文書とrestart、別state restoreの限定評価。本番保証ではない。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/README-IMPLEMENTATION-ASSESSMENT.md)

非公開receipt SHA-256: `7f36a6605a80777471c2a689228dac2c3118af210ffc619418779d6877e092a6`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e05"></a>
## E05 native Gadget / Codex drafting

承認前0回、承認後1回、同画面/reload readback。既存Task owner未接続。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/runtime/codex-task-bridge/README.md)

非公開receipt SHA-256: `707fa69f307da99a7f0d6bb261d8a9bcaaaf69ff29c31572eb288eb651ff7694`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e06"></a>
## E06 Voice knowledgeと検索・本文返却

保存済み実記録の話者付き派生、引用検索、本文返却を限定検証。新録音の全自動返却・多人自然会話は未検証。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/README-IMPLEMENTATION-ASSESSMENT.md)

非公開receipt SHA-256: `352e52adda6baaec85e70e469be6c1f861fc9de770ddecb80ec5448e9b1f3aef`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e07"></a>
## E07 Voiceのファイル返却の制限

添付投稿のmetadataを確認。本体取得はCDN403で未確認、hash一致や再試行成功は主張しない。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/README-IMPLEMENTATION-ASSESSMENT.md)

非公開receipt SHA-256: `91d3eba7f7f3555ad00e1d25bcef34ca96108c45a0c3e62e0fa205670d39f530`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e08"></a>
## E08 Task管理とCompany本番の境界

個人向けTask管理候補でのlocal参照照合は、Company本番Taskの採用・同期・実行とは別。個人TaskのID、owner対応、receipt digestや記録内容はこの公開資料へ載せない。OSの自動Task接続は未実装。

[公開の契約文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/README-IMPLEMENTATION-ASSESSMENT.md)

<a id="e09"></a>
## E09 native Proxmox template / clone

空の公式source templateから別clone、起動/restart/DB検査。cloneの文書・Task受入と別host復旧は未検証。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/templates/native-proxmox/cloudflare-os/README.md)

非公開receipt SHA-256: `c356ffd1739ee4317bb9987c179e00bd61372a750eb1f6f189898c4b97259f1d`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e10"></a>
## E10 Qwen OS chat / Document readback

選択local modelの実応答、文書保存/reload/restart。手動Task metadata入力と不正blocksの人による訂正を含む。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/runtime/local-model-proxy/README.md)

非公開receipt SHA-256: `53a1976e0328514328433ac6198bfe6655352146eec35797daa6fe0cc01ce06d`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e11"></a>
## E11 PR34 special-file修正と公開readback

正規file以外のread拒否を修正しPOSIX FIFOも検証。PR34 headへの限定証拠で、このbranchへの統合ではない。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/b3e3d868ccf16d840171282f9cff2b75ba8ef1bd/tools/validate_company_pack_agent_swarm_execution_candidate.py)

非公開receipt SHA-256: `ec674671779b19d907524141c8b6ecc53c0897f971baa4d68ca75c62d10c2868`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e12"></a>
## E12 既存22 review threadsの解決

6 PRの22原指摘をcurrent headで確認して解決。独立approval・merge・Human GOは別。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project/blob/f168a2ebd52d0eb62fbd491c403effdefcb9aa97/docs/PROJECT-MAP.md)

非公開receipt SHA-256: `57ae9fd707ebe79e9ed76824443a18115a7858c9b7b09f5a99d793fd9a941d7a`。参照固定であり真正性・現行性・採用を証明しない。

<a id="e13"></a>
## E13 クロージング開始時のGitHub読取

全14 open PRのhead/base/checks/review threadsと25 open Issue本文。独立全差分監査ではない。

[公開の実装・文脈](https://github.com/Kotodama-Project/Kotodama-project)

## この変更の検証

runtime code固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` でPython 874 tests PASS / 4 skips。Node 52 tests PASSには、別途取得したmanifest-bound Document sourceによる2件を含む。通常のsource未取得runではその2件はskipになる。default Blueprint修正のNode検証は、既存Gadget instanceの実workerd拒否の証明ではない。PR34の654 testsとPOSIX FIFOは別headの証拠。最終文書変更の検証はPRのexact-head CIとprivate closing receiptを読む。

配布前レビュー後の追加修正は別のlocal/CI検証へ束縛する。旧実環境receiptを新seal/toolchain/proxyの配備証明へ流用しない。最終候補のCIと公開readbackはGitHub PRへ記録し、個人Task記録の状態更新には結び付けない。

<a id="e14"></a>
## E14 large-v3・raw保持・文脈訂正

large-v3を基本として配備し、個別話者・語時刻・raw原文を保全した。local Qwenの候補検証と聞き直し表示を設け、不確かな区間を要点に採用しない。新録音の全自動返却・多人自然会話・認識完全性は未受入。

[修正内容と制限](../VOICE-ACCURACY-2026-09-06.md) / [公開用の観測要約](voice-repair-observation.json)。公開要約 SHA-256: `abb5ea49ebf1ad9364cdfb62c42cfc7e6c3e4141b458c1a0082acfd0172de43a`。原音・発話本文・本人ID・private receiptのlocatorとdigestは公開しない。これは公開ファイルだけによる実環境の独立再現を意味しない。
