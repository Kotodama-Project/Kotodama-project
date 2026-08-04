# Guided Company Pack Initialization

Company starterを初めて使う人が、22 JSONを開いて19箇所を手編集せずに、静的placeholderを閉じた`draft`候補を作るための導線です。既存の2引数initializerはそのまま使えます。3つのguided optionをすべて渡した場合だけ、次の19項目を一括反映します。

- governed Human Intent locator: 1
- 9 Blocksの`authority.expires_at`: 9
- 9 Recordsの`retention.policy_ref`: 9

これは静的customizationを安全に機械化するだけです。Human Intentの真正性、role/ownerの承認、retention policyの存在や実行、Promotion、Current Truth、runtime、Public Beta GOは作りません。

## Recommended one-command path

`work/`は自分の作業directoryです。targetがすでに存在する場合、initializerは上書きしません。

### PowerShell

```powershell
New-Item -ItemType Directory -Force work | Out-Null
$expiresAt = python -c "from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc) + timedelta(days=7)).isoformat().replace('+00:00', 'Z'))"
python tools/create_company_pack.py my-company work/my-company `
  --human-intent-ref human-intent:governed-alpha-v1 `
  --authority-expires-at $expiresAt `
  --retention-policy-ref retention-policy:governed-v1
```

### Bash

```bash
mkdir -p work
expires_at="$(python3 -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc) + timedelta(days=7)).isoformat().replace("+00:00", "Z"))')"
python3 tools/create_company_pack.py my-company work/my-company \
  --human-intent-ref human-intent:governed-alpha-v1 \
  --authority-expires-at "$expires_at" \
  --retention-policy-ref retention-policy:governed-v1
```

成功時はexit code `0`です。creation reportの主要値は次のようになります。

```json
{
  "status": "PASS",
  "validated_files": 22,
  "draft_documents": 22,
  "static_customizations_applied": 19,
  "customization_status": "READY_FOR_GOVERNED_REVIEW",
  "public_beta": "NO_GO_UNPUBLISHED"
}
```

実際のreportはclosed contractで、[`company-pack-creation-report.schema.json`](../schemas/company-pack-creation-report.schema.json)に従います。`claims`はすべてfalseです。

## Three inputs

| Option | Accepted input | Not accepted or proven |
|---|---|---|
| `--human-intent-ref` | `human-intent:`から始まるlowercaseのsecret-free locator | Human Intent本文、token、参照先の存在・真正性・承認 |
| `--authority-expires-at` | timezone-aware ISO-8601で、実行時のlocal UTC clockより未来かつ30日以内 | trusted clock、実際のrole assignment、authorityの承認・行使 |
| `--retention-policy-ref` | `retention-policy:`から始まるlowercaseのsecret-free locator | policy本文、policyの採用・適用・削除実行 |

3 optionはall-or-noneです。1つまたは2つだけ指定した場合はusage error `2`で停止し、targetを作りません。不正locator、placeholder、secretらしい値、期限切れ、30日超はexit code `1`で拒否します。拒否reportは不正値やtarget pathを反射しません。

locatorは参照名であり、本文やcredentialを入れる場所ではありません。CLI引数は同じmachineのprocess listingから見える場合があるため、secret、個人情報、private source bodyを渡さないでください。このtoolはnetwork接続や公開を行いません。

## Safe filesystem behavior

initializerは次の順でfail closedします。

1. pack IDとguided inputを検査する。
2. shipped starterを変更前に検証する。
3. 既存target、starter内target、存在しないparentを拒否する。
4. 新規targetだけを作り、pack ID、3 MOC、22 status、指定時の19項目を反映する。
5. 22文書をvalidatorへ通す。
6. customization checkerが、通常pathでは`CUSTOMIZATION_REQUIRED`、guided pathでは`READY_FOR_GOVERNED_REVIEW`であることをpost-checkする。
7. 途中失敗では新規targetを残さず、shipped starterと既存targetを変更しない。

## Incremental path remains available

3値をまだ決めていない場合は、従来どおり2引数で作成します。

```powershell
python tools/create_company_pack.py my-company work/my-company
python tools/check_company_pack_customization.py work/my-company
python tools/plan_company_pack_next_steps.py work/my-company --format markdown
```

```bash
python3 tools/create_company_pack.py my-company work/my-company
python3 tools/check_company_pack_customization.py work/my-company
python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown
```

このpathは`19/46/5`を返し、guided plannerで現在地を確認してから組織内で値を決められます。既存targetをguided modeで更新する機能ではありません。guided modeを使う場合は、別の未使用target名へ新規生成し、必要ならexact bytesをreviewしてください。

## Ideal flow and current boundary

| Stage | Ideal use | Current public implementation |
|---|---|---|
| Draft creation | sourceを保ち、組織固有の静的値を安全に設定 | guided initializerが1回で22 draft文書と19置換を生成・検証 |
| Candidate binding | review対象をimmutableなbytesへ固定 | `build_company_pack_review_bundle.py`が22 fileのSHA-256/sizeを束縛 |
| Governed review | owner、role、profile、Human Intent、retentionをauthorityのある人が確認 | checkerは46 review項目と5 evidence項目を残す。承認は自動化しない |
| Promotion | candidate-bound Human Decision後に別processでCurrent Truthへ反映 | 未実装・未実行。creation reportのclaimsはfalse、Public BetaはNO_GO |

次は[Company Pack Customization Checklist](CUSTOMIZATION-CHECKLIST.md)で`0/46/5`を確認し、[Company Pack Review Bundle](REVIEW-BUNDLE.md)でexact bytesを固定します。保存bundleを照合した後は[Company Pack Review Request](REVIEW-REQUEST.md)で46件を手転記なしのpending requestへ束縛できます。`READY_FOR_GOVERNED_REVIEW`、bundle `MATCH`、pending requestはいずれもapprovalではありません。
