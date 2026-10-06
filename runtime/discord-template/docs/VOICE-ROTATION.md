# 15分ごとの文字起こし投稿

ローカルASRの確定したSourceを、話者と区間内の時刻付きの.txtで返します。
実装・合成検証の段階で、実Discord・実音声の15分受入とPB-G2は未実施です。
原音保存用のarchive.rotationMsとは別で、Live接続や録音を15分で切断しません。

`voice.rotation.enabled`は既定falseです。有効化には`transcriptSource: local`、既存の
voiceChannelIdと、それとは別の通常テキストチャンネルを`voice.rotation.channelId`へ指定します。
設定を変更したら再起動します。実行中の対象変更は投稿を止め、別の宛先へ転送しません。
無効時はtimer・区間の行・投稿を作らず、従来の同意文とIDも変わりません。

## 区間と失敗

開始から900秒後の最初の無音境界で区間を閉じます。発話中は`maxExtendSeconds`
（既定60、0〜120秒）まで延長します。発話を分割せず、受信開始時刻で一つの区間へ
割り当て、次の区間は確定と同じ時刻から始めます。

確定後は`postWaitSeconds`（既定60、1〜120秒）までASR完了を待ちます。
Source保存の直後に参照を確定し、意図解析やTask完了を待ちません。間に合わない発話は
投稿へ含めず、次のファイルにも移しません。元のSourceは保存先の規則に従って残ります。
1区間1024入力・添付1MB・同時4区間までで、上限では部分成功とせず投稿を止めます。

切断・再参加でも時計は進みます。再起動では以前の未投稿区間をinterruptedにし、新しい
区間から始めます。SQLiteの区間記録は時刻・状態・参照件数だけで、本文は複製しません。
既存delivery記録で送信を一回予約し、Discord nonceも固定します。不明な配送はunknownにし、
自動再送しません。quiet hoursで繰り延べたり、DMへ切り替えたりもしません。

## 閲覧者と同意

有効時の同意文に非公開チャンネルへの15分投稿と宛先を含めます。participant_opt_inでは
新しいnoticeへの同意が必要です。owner_managedでは説明・同意管理を人間側が担い、本人の停止を優先します。

全guild memberを列挙する権限は追加しません。投稿先は@everyoneのViewChannelを明示拒否し、
メンバー単位の許可から閲覧者を特定できるGuildTextに限ります。ViewChannelを許可するroleや
Administrator roleは、自身のmanaged Bot roleを除いて拒否します。guild ownerも閲覧者へ含めます。
この限定は[Discordの権限規則](https://docs.discord.com/developers/topics/permissions)に沿います。

全閲覧者が全Sourceのreadersに入り、現在も元VCを読める必要があります。送信前に設定・
同意・出典の版・対象channel/rolesを再検査し、途中のアクセス変更eventや接続喪失でも止めます。
変更・撤回・停止済みのSourceは出しません。BotにはViewChannel・SendMessages・AttachFilesが
必要で、確定した適格Sourceがゼロなら投稿しません。

話者は受信trackから決め、表示名を根拠にしません。帰属不明は「話者不明」とし、accountの
対応を本文へ出しません。メンション通知は無効です。UTF-8の添付では発話中の改行を字下げし、
別の話者行と混同させません。

## 人が確認すること

非公開投稿先を準備し、処理対象者が15分以上会話して、到着時刻・話者・相対時刻・発話が
途中で切られないことを確認します。Botの切断・再参加、同意取消、投稿先権限の変更も確かめます。
結果は日時・所要時間・区間数・途切れの有無だけを#148へ記録し、音声・本文・Discord IDを
載せません。その実測を基に#156のPB-G2を判断します。
