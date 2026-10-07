# 出典とConceptの版を固定する

#53の最初の部分として、[閉じたmetadata契約](../schemas/knowledge-lineage.schema.json)と
read-onlyの検査を提供します。[既存KB](KNOWLEDGE-BASE.md)のproseやTask ownerを置き換えません。
逆引き・影響計算もmetadataから再構築します。current pointerのローカル参照ownerと、
既存v2 Context Packを利用する直前の版・出典・取消検査へ接続しています。

## Bindingの意味

Sourceはmutableなpathから独立したsource_id、immutableなbindingのrevision_ref、
provider等のrevision_kind/valueとcontent_sha256を持ちます。observed_at/observer、
authority scope、custodian、access policy/state、retention、legal hold、invalidation keyは
別fieldです。任意のlines/JSON Pointer/event spanで主張の位置を示せます。

同じprovider revisionで違うdigestは矛盾として拒否します。同じbytesでも観測・権限・retention等が
変わればsource-set digestが変わります。bindingのrevision_refはその全metadataの版であり、
後続のownerで同じrefの異なる内容を上書きしません。provider revision自体とは区別します。
このread-only検査だけでは、別snapshot間のimmutabilityや観測者の本人性を証明しません。

ConceptはOKFのlogical path IDを維持し、外側のmetadataにrevision/parent、文書全bytesのdigest、
source-set digest、generator invocation、policy/intent revisionを記録します。
hashをprose内に埋めて自己参照を作りません。親の別Conceptへの付替えと親循環を拒否します。

non-nullの親がsnapshot外の場合は`parent_resolution: external_unresolved`を明記し、CLIは
NEEDS_RESOLUTIONと未解決refを返します。完全に照合した親鎖とは扱いません。既存revision ownerへ
差分を登録する場合も、そこで親の存在とlogical IDを照合する必要があります。resolved relationは
外部targetでも固定revisionを必須にします。public locatorのcase衝突も、platformを問わず拒否します。

型付きrelationは相手のlogical IDと固定revision、必須/任意、validity/resolution、evidenceを
保持します。source/conceptが見つからない場合はunresolvedと明記し、resolvedの偽装を拒否します。
Goal等の外部owner参照が構文上妥当なことは、そのownerへの照合成功ではありません。
catalog/graph/search、Context Pack/metric input、Task/evidence/riskのprojectionも、入力revisionを
参照します。これらの一覧に独自の権限やCurrent Truthはありません。

## 公開面と未確認

public locatorは限定されたrepository-relative pathです。絶対path、URL、path traversalを
受理しません。remote/private sourceは承認済みopaque refとdigestを使い、ここではfetchしません。
opaqueがあるだけではaccessを認めず、readbackはNEEDS_RESOLUTIONです。
provider revisionを安全なtokenとして表せない場合、値を加工して同じETag等だと主張せず、
content_digest bindingを用い、provider側の対応を既存ownerに残します。

access_stateはownerからの申告で、認証済みgrantではありません。LOCAL_METADATA_PASSは
契約の整合と対象ローカルbytesの一致だけです。利用者へのdelivery、実際のaccess、current pointer、
真正性、Promotion、Company truthやHuman GOを証明しません。

## 合成例を検査する

[snapshot](../examples/knowledge-lineage/snapshot.json)は2つの短い合成ファイルをpinします。
実在のprivate source、会話、provider情報を含みません。

```text
python -B tools/knowledge_lineage.py validate --snapshot examples/knowledge-lineage/snapshot.json
python -B tools/knowledge_lineage.py readback --snapshot examples/knowledge-lineage/snapshot.json --root examples/knowledge-lineage
python -m unittest tests.test_knowledge_lineage -v
```

検査はファイルへ書き込みません。呼出側はreadbackのinput_bindingsを実際の使用まで維持し、
sourceやowner状態が変われば再取得します。後続の取消・CASを未実装のまま成立したと扱いません。

## 逆引きと変更・失効の影響

```text
python -B tools/knowledge_lineage.py index --snapshot examples/knowledge-lineage/snapshot.json
python -B tools/knowledge_lineage.py impact --before examples/knowledge-lineage/snapshot.json --snapshot examples/knowledge-lineage/snapshot.json
```

Source revisionからConceptとcatalog/graph/search、Context Pack/metric inputへ、Conceptから各
projectionへ、Goal/KGI/InitiativeからConcept・Task・evidence・riskへ、invalidation keyから
影響する全nodeへ逆引きします。宣言入力からの計算で、欠けたreceiptやTaskを推測しません。

before/afterの両方の依存を用いるため、削除されたSourceや古いConceptへの参照も影響範囲に
残ります。同一bytesでもaccess/観測/retentionやrelationが変われば更新です。同じ入力はNO_CHANGEの
receiptになり、再生成を必要としません。ただし既にrevokedの入力はno-opでもquarantineに残ります。

必須の依存は推移的にquarantineへ伝え、optionalの参照は別の一覧へ報告します。
supersedes/invalidatesは対象を、conflicts_withは両側をquarantineにし、依存の辺とは分けます。
欠落・未解決・失効した必須関係、依存循環は利用可能な状態にしません。optionalを含む循環も
別に報告します。外部ownerのtargetは構文上のresolved申告だけでは解決済みにしません。

既定の上限はdepth 32、768 nodes、4096 edgesです。呼出側は下げられますが引き上げられません。
node/edge超過は拒否し、depth超過はcomplete=false / BUDGET_EXCEEDEDとなり全nodeをquarantineへ
置きます。部分的な影響範囲を完全な結果として使いません。計算receiptのdigestは入力・予算・
affected/optional/quarantine集合を結びます。これをowner認証や実際の取消・配送の証明へ使いません。

## 現在版のpointerをproseの外に置く

`LocalRevisionOwner`は既存ownerから渡すauthorization callbackを必須とする、ローカル参照実装です。
SQLiteをproduction DBとして採用したものではありません。databaseはrepository内の専用work領域等へ
置き、knowledge配下・外部path・link・別用途の既存DBへの混入を拒否します。callbackは毎回、
action/対象ref/current generationを受け、登録時は固定snapshot digestも受けます。literal trueだけを
許可として扱います。実grant・本人性・scopeの確認は既存ownerの責任で、callback自体は発行しません。

`register(snapshot, expected_generation=...)`はimmutableなSource/Concept metadataを登録します。
同refの内容差し替え、異なるsnapshotをまたぐ同provider版の矛盾、sourceのinvalidation key付替えを
拒否します。親版や現在版は本文へ書き込みません。現在版は`publish`でexpected generationと
expected parentを同じtransaction内で照合して更新します。後から終わった古いcandidateは、新しい
generationだけ取得しても現在版を上書きできません。旧版・eventsは消しません。

`revoke`はownerが照合したinvalidation keyとevidence refを記録し、同じkeyのread/publishを止めます。
解除や強制rollback APIはありません。required dependencyが現在版でない、未解決・循環・失効・
conflictedである場合もcurrentのreadbackを拒否します。同generationの競合更新は一つだけが成功し、
途中の失敗はtransaction全体をrollbackします。

これは**ローカルの版pointerの整合だけ**です。`current`はmetadataを返し、文書本文を配送しません。
Source access/authenticityや実際のagent入力はこのownerだけの証拠にしません。
register/publishをCompany truth・Promotion・runtime authorityや
Human GOへの採用に読み替えません。opaque sourceの真正性も別ownerへの照合が必要です。

```text
python -m unittest tests.test_knowledge_revision_owner -v
```

## Context Packを渡す直前に照合する

`LineageContextGate`は既存のKB selectorと16欄のv2 producerを使います。別のcontext本文形式を
作りません。`prepare(request)`は版・source-set・owner generation・rendered digest・期限・
使用したcode/schema bytesのbinding manifestを返します。`consume(request, manifest, consumer)`は
その入力から再構築・照合してから、同期consumerへUTF-8 bytesを渡します。

requestはactor/recipient/purpose、Task/Session/Intent/Policy/Grant refs、expiry、既存の検索filter、
Concept数/bytesの上限を閉じた形で持ちます。既存ownerの`authorize_context`を必須とし、literal true
以外は拒否します。refsが存在するだけでは認可しません。actor本人性や外部providerの真正性を、
callbackの成功だけで独立検証したと主張しません。

Concept Revisionの任意の`source_aliases`は、元のOKF `sources[].id`をSource Binding revisionへ
対応付けます。このgateで使うConceptでは全ての宣言sourceを対応付け、ちょうど同じsource-setへ
結ぶ必要があります。現在版・実Concept bytes・Policy/Intent版・public-local出典のpath/digestを
照合します。lines/JSON Pointerは固定bytes中の位置まで検査し、意味的な主張の正しさとは分けます。
event rangeは既存event ownerの`verify_event_span`を必要とし、未知のevent schemaを推測しません。

opaque出典は`verify_opaque`が元resourceとopaque bindingの対応・scope・固定版を照合します。
元resourceはこの信頼された確認先だけへ渡し、contextではopaque locatorへ置き換えます。
確認先がない、拒否・例外・不明なら利用しません。確認先は既存の認可・出典ownerへ接続する
read-only callbackであり、別のgrantやTask ownerではありません。

重要なGoal/制約と型付きrequired依存をoptionalより先に確保します。予算不足や古い依存版、
portable Markdown linkの欠落を推測で補いません。版が未登録のoptionalは省略できますが、
登録済み版と現物の矛盾やDB破損を隠して成功にしません。期限は確認callbackの後と利用直前にも
確認します。opaqueの存在だけや、古いas_ofで現在の失効・期限切れを回避できません。

同じlocal ownerのtransaction内で最後の検査とconsumer呼出しを行い、組立後の失効・更新は
generationの不一致で拒否します。callbackは有限で同期的とし、同ownerへの再帰的な書込をしません。
consumerが例外を返した場合は結果不明とし、このgateは再送しません。実際のtransport・deduplication・
配送receiptは既存のconsumer ownerに残します。外部providerの取消や、送信後のbytesの回収を
このlocal lockが保証するとは主張しません。

manifestの`projection_record`は実際のrendered bytesと選ばれたSource/Concept revisionsを結び、
既存のevidence ownerがlineage snapshotへ加えれば、Context Packも逆引きとinvalidationの対象に
できます。KBへreceiptやCompany truthを自動保存しません。code pinは検査したファイルbytesの
一致であり、OSの実行image・reviewer本人性・実providerの受入・Human GOを証明しません。

`bind_generated_projections(bundle, snapshot)`は既存catalog/graph producerの実bytesも同じ形式の
projection recordへ束縛します。全Conceptと宣言出典のcoverage、public-local bytesと対応を必須にし、
欠落・複数版・opaque未確認を拒否します。出力は再構築可能なsnapshotで、自動保存や現在版の採用は
行いません。この経路はpublic-local用で、opaque出典の認証・公開許可を推測しません。

```text
python -m unittest tests.test_knowledge_lineage_context -v
```
