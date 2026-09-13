# Discordから招待ページを作る

仕事のworkspaceへ、このrepositoryの `.agents/skills/shareable-invitation/` を同じ相対pathで配置し、Gitへcommitする。CLI workerはHEADから隔離worktreeを作るため、未commitのスキルや資料は引き継がれない。実際のイベントや人の資料はprivate workspaceだけに置く。

Discordの `/kotodama do` で `action:write_file` を選び、次のように依頼する。

> shareable-invitationスキルを使って、指定した共有用briefから招待ページと短い送付文を作って。内部評価は載せず、参加や協力を押し付けない文章にして。成果は私へ返して。

成果は依頼者のDMへ返る。`deliverables/`直下のmd/html/txt/pdfだけをhash確認して添付する。内部のreview-notesやコード差分をまとめて第三者へ送らない。`/kotodama result task:仕事ID`でも取り出せる。

修正は仕事IDと変更したい内容を指定する。本文とHTMLを同時に直し、新しい版の成果を取り出す。第三者への送信やweb公開が必要なら、宛先・対象ファイル・共有範囲を依頼に含める。外部ログインは本人が行う。

スキルは共有可能な情報の選択、訂正の照合、ページ作成、主要な判断理由、画面確認、配送のreadbackを定義する。ブラウザや外部サービスの接続は実行ホストで利用できるCLI/API/CDP経路に依存する。スキルを置くだけで外部サービスのログインやPC操作権限は増えない。
