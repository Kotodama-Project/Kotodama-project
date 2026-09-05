# 情報の分類と閲覧者の管理

機密度だけで閲覧者を決めず、**情報ID・主体ID・担当・閲覧者・review担当・期限・取消**を組にする。
この候補は既存のローカル review Gateway の実HTTP読取・reviewへ適用する。既存 Source/Task/会話台帳のACL authorityや認証基盤を置き換えない。

## 分類と既定の扱い

| 分類 | 意味 | このGatewayでの扱い |
|---|---|---|
| `unclassified` | 未確認・分類できていない | 内容を返さない |
| `public_candidate` | 公開を検討できる候補 | 明示されたreaderだけ。匿名公開・公開承認はしない |
| `internal` | 組織内部の業務情報 | 明示されたreaderだけ。全社員・全agentへの暗黙共有なし |
| `restricted` | 個人情報、特定案件、相手との合意など関係者限定 | 明示されたreaderだけ |
| `secret` | credentialや最重要機密など、通常のreview画面で扱わない情報 | 担当者を含め、この経路では内容を返さない |

分類未設定のimportは拒否する。既に未分類と記録された候補は保持するが閲覧不可。
このサービスは本文を意味解析して正しい機密度を判定するものではない。
原音・private transcript・credentialは既存projectionの許可形式に含めない。
secretの分類を設定しても、credential本文をここへ保存してよいことにはならない。

## 識別子と担当

情報には既存 `handoff_id` を使う。主体は `urn:kotodama:principal:<UUIDv4>`、
ポリシーは `urn:kotodama:access-policy:<UUIDv4>`。人名やメールをIDへ埋め込まない。
`principal.kind` はhuman / agent / service。担当 `owner_ref` と、閲覧 `readers`、
review `reviewers` は別で、reviewerはreaderにも含まれる必要がある。担当であるだけでは閲覧不可。

operatorが選んだ認証subject/emailの組を既存actor digestへ変換し、主体IDへ一意に束縛する。
生のsubject/emailはstoreへ保存せず、同一主体の別binding、同一bindingの別主体、未知のgrant先を拒否する。
digestも個人に結び付く私的なpseudonymであり、匿名化や公開安全の保証ではない。
実際の本人情報・部署・役割との対応は既存の認証/identity ownerで管理する。
このlocal catalogは明示されたoperator inputのsnapshotであり、全社の第二identity SSOTではない。
部署・役職からの自動展開、主体bindingのrotation、他storeとの整合・削除はこの版の対象外。

## 実行される検査

HTTPは最初にtrusted backendの資格情報を検査し、その後でactorを主体IDへ解決する。
requestが送った主体IDや機密度を信頼しない。GETはread権限、POST reviewはread+review権限、
分類、state、現在のOS時計に対する期限を検査する。review body受信中に取消された場合も、保存直前の検査で拒否する。

権限なし・失効・未分類・秘匿・未知の主体は、存在しない情報と同じ404。
通常応答は既存projectionのままで、ポリシー・担当/閲覧者の内部ID・actor bindingを載せない。
reviewのaccept/edit/rejectからACL変更・公開・Task実行はできない。公開用のendpointは追加していない。

## 初期入力と変更

importは閉じた `{principals, records}` object。
`principals` の各要素は `{principal_ref, kind, actor: {subject, email}}`、
`records` は `{projection, access_policy}`。具体的な合成入力は `syntheticCatalog()` を参照する。

`access_policy` は次の8フィールドのみ。

```text
policy_id, revision, classification, owner_ref, readers, reviewers, expires_at, state
```

初期revision=1、state=active/revoked、期限は `YYYY-MM-DDTHH:mm:ss.sssZ` のUTC。
主体最大128・情報最大64・全store4MiB。ポリシーは現在版と最大32件の過去版を一緒に保存する。
上限で更新を拒否し、勝手に履歴を破棄しない。次の保存形式への移行は別の明示された作業になる。

稼働中の変更はGatewayを起動した**trusted local operatorだけ**が次を呼べる。

```js
gateway.updateAccessPolicy({
  handoffId,
  expectedPolicyRevision: currentPolicy.revision,
  policy: { ...currentPolicy, revision: currentPolicy.revision + 1, state: "revoked" },
});
```

同じpolicy ID・次のrevision・既存principalを検査し、前のpolicyを履歴へ残して原子的に保存する。
古いrevisionの競合と、Gateway close後の更新を拒否する。新しいreaderへの共有も同じ明示操作を使う。
この関数をブラウザ、Gadget、モデルtoolへそのまま公開しない。実環境の権限変更では既存Work Order/identity authorityを先に検査するcallerが必要。
この関数は本人の権限確認や暗号署名を代行しない。同じOS userの悪意あるwriter、時計巻戻し、古いstoreの復元に対する保護証明でもない。

内部metadataだけを確認するCLI:

```text
node runtime/local-review-gateway/server.mjs --inspect-access --state-root work/local-review-state
```

情報ID/版・機密度・担当・閲覧/review主体ID・期限・取消とpolicy履歴を出す。
本文とactor bindingは出さないが、内部組織関係を含むため、この出力も公開資料へ貼り付けない。

## 既存データ・派生情報・公開

v1 storeは自動移行せず起動を拒否し、既存bytesを保全する。
必要な情報と担当/閲覧者を確認して新しい専用storeへv2形式で明示importする。
旧storeに再び旧実装を起動すれば新しい制限は適用されないため、運用切替には別の確認が必要。

この版は要約・embedding・結合を生成しない。将来の派生経路は元情報の制限と出典を保持し、
制限の違う情報を混ぜた結果を自動的にpublic候補へ下げない。元ACLの取消を既存Source/Session台帳の
`acl_loss`・失効処理へ接続する必要がある。この横断伝播、実OS/Discordの役割、外部共有先の削除は未接続。

用語は [CONTEXT.md](../CONTEXT.md)、起動・importの制限は [Gateway手順](../runtime/local-review-gateway/README.md)。
情報の閲覧許可、公開採否、実行権限、Public BetaのGOを区別する。
