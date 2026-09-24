## 目的 / Purpose

<!-- 何を、なぜ変えるか。対応する Issue があれば `Closes #N` を書く。 -->

## 変更点と変えていないこと / What changed and what did not

## 実行した検証 / Validation actually run

<!-- 実行したコマンドと結果。未実行の確認は「未実行」と書く。Do not paste secrets. -->

## 未検証・影響範囲 / Not verified and impact

<!-- local PASS を live / deployed / Public Beta / Human approval と呼ばない。 -->

<details>
<summary>外部状態に触れる PR のチェック（workflow、runtime、provider、公開設定、secret を変える場合のみ）</summary>

- [ ] No live credential, session, private locator, customer data, or unredacted production evidence appears in commits, logs, screenshots, comments, or generated files.
- [ ] New inputs and external responses are bounded, validated, and fail closed where a permissive fallback could create security or cost exposure.
- [ ] Repository GitHub Actions use reviewed full commit SHAs, and `docker://` actions use reviewed sha256 image digests rather than mutable tags.
- [ ] Generated/SSOT files were updated through their authoritative generator rather than edited inconsistently by hand.
- [ ] Relevant negative cases were tested, not only the successful path.
- [ ] A rollback or disablement path is documented for production-affecting changes.
- [ ] Provider-side settings, deployment revision, branch protection, DNS, billing controls, and secrets will be read back after mutation rather than inferred from the submitted source.
- [ ] Publication, repository transfer, production deployment, or paid capability enablement remains blocked until its explicit human/administrative gate is satisfied.

</details>
