# Project Skillsをworkerへ渡す

通常のCLI workerの`research`、`summarize`、`develop`、`write_file`に、operatorが
選んだproject-localの手順本文を渡します。既定は選択なしです。Task本文からの
自動選択、host全体のcatalog検索、pluginの有効化、権限の追加は行いません。

仕事workspaceのGitへ`.agents/skills/<name>/SKILL.md`をcommitし、設定の
`worker.projectSkills`へactionごとの名前を指定します。

```json
{
  "worker": {
    "projectSkills": {
      "research": ["project-research"],
      "write_file": ["shareable-invitation"]
    }
  }
}
```

これは既存設定への追加部分です。`worker.actions`によるgrant、既存Task owner、
Sourceの現在版・閲覧範囲、Linuxでの書込みと独立検証の条件を満たす必要があります。
設定変更は起動中の選択を差し替える操作ではありません。進行中の仕事を確認し、
新しい設定でruntimeを再起動します。

各actionは最大4個、名前は64文字以下の小文字英数字と単一の区切りハイフンです。
同じaction内の重複、未対応action、path指定は拒否します。選択した`SKILL.md`だけを
読み、リンク先・scripts・references・別Skillは自動で追加しません。本文がそれらを
必要とする場合、今回のTask内で実行できるか別途判断します。

複数の操作を一つのTaskへまとめた場合は、主actionと`requiredActions`の手順を
合わせて渡します。主actionを先頭に、requiredActionsの記載順でactionを重複除去し、
各actionの設定順でSkill名を重複除去します。同じSkillを複数actionへ設定しても本文は
一度だけ渡します。requiredActionsは対応する4種だけの配列で、最大4要素です。
すべてのactionに既存grantが必要で、この組合せによって実行権限は増えません。
合計のSkill数は最大16個で、下記のbytes上限は組合せ全体へ適用します。

本文は1個64 KiB、合計128 KiB、JSONへ整形したSkill入力部分は256 KiBまでです。
UTF-8を厳密に読み、portable frontmatterの`name`が選択名と一致し、空でない
`description`が一つずつあることを確認します。名前は未引用・単引用・二重引用を
使えます。descriptionは単一行のplain string、YAMLの単引用文字列、JSON互換の
二重引用文字列を扱い、末尾commentは空白で区切ります。引用内の`#`は文字列に残し、
単引用内の`''`は一つの引用符として解釈します。空白だけ・空引用・commentだけの値、
未引用のnull/boolean/number、collection、tag、alias、`>`や`|`による複数行scalarは
拒否します。それらを文字列として使う場合は対応する引用形式で記述します。
UTF-8 BOM、名前の重複、未完成のfrontmatterは拒否します。
通常ファイル以外、symlinkを含むpath、hard link、未commit・欠落・過大な本文を
拒否し、途中までの本文を送って成功としません。Git checkout filterは書込み経路の
既存検査に従い、Skill本文のcommit照合ではfilterを実行しません。

読取workerは設定workspaceのHEADと作業ファイルが同じbytesであることを確認します。
選択があるworkspaceはGit repositoryのrootに限定します。書込workerはHEADから
作った既存の隔離worktree内のcommit版を渡すので、元workspaceの未commitなSkill
や資料は引き継ぎません。設定した名前、Skill bytes、対象HEADをモデル起動前と
結果採用前に再確認し、差替えがあれば結果を採用しません。書込workerが選択中の
Skill自身を変更した場合も採用を拒否します。その更新は別の仕事へ分けます。

CLIのstdinへ`PROJECT_SKILLS`として、名前・版・digest・手順全文を渡します。
手順はTaskを進める方法であり、依頼、Human Decision、追加の実行権限ではありません。
既存の`apps`、`plugins`、`multi_agent`、画像生成・web検索の無効設定を保持します。

モデルの子プロセスを開始する前に、既存成果directoryの`input-receipt.json`へ
`prepared`を保存します。本文やprivate pathは含めず、次の情報を記録します。

- 選択元`operator_action_config`、主action、選択した全actionの`selectedActions`、設定digest、HEAD revision。
- 同じTask IDとTask/Source revision、渡したSource contextのdigest。
- Skill名、本文のSHA-256、bytes、合計bytes。
- 実際にstdinへ渡すUTF-8 bytesのSHA-256と長さ、出力schemaのSHA-256。

CLIから結果を得て現在版の照合が通ると、既存Taskのresult receiptの`skillDelivery`
へ同じ情報を返します。選択ありは`submitted_to_cli`、選択なしは`none_selected`です。
`prepared`だけでは送信・成功を証明しません。子プロセスへ入力した証拠は、モデルが
手順を守った証拠でも、hostが暗黙にSkillを読み込んだ証拠でもありません。
`modelObedience=not_evaluated`、`hostSkillDiscovery=not_observed`を保持します。
成果の有用性と要件充足、独立review、provider・Discord・人による受入は別に確かめます。

fallbackを使う場合も同じ入力と起動前の照合を使います。失敗やdriftで最終receiptが
作られなかったとき、残った`prepared`を完了証拠へ読み替えません。
`create_company_pack`、`swarm_research`、analyzer、Dots plugin、要件brief専用bridgeは
この入力経路の対象外です。

```text
node --test tests/project-skill-input.test.mjs
pnpm check
```

この試験は一時Git repositoryと実際の合成CLI子プロセスを使い、受け取ったstdinの
bytes、起動前receipt、commit照合、欠落・特殊file・driftの拒否を確認します。
書込み検証器はtest doubleです。実モデルのSkill選択・推論品質・実Docker隔離・
live providerの受入を証明しません。
