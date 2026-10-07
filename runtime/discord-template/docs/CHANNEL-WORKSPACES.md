# チャンネル別の作業場

`worker.channelWorkspaces`を指定すると、同じ承認済みrepositoryからチャンネル別のdetached
worktreeを作ります。声・テキストから作られたTaskは元Sourceのguild/channelで作業場を選びます。
設定しない場合は従来の単一`worker.workspace`です。Taskの状態は既存の一つのownerを使います。

```json
"channelWorkspaces": {
  "channelIds": ["100000000000000003", "100000000000000005"],
  "maxAgeSeconds": 1800,
  "generation": "initial"
}
```

これは`worker`内の設定例です。IDは合成値で、実際の設定・作業データはGit外へ置きます。
対象は最大8 channel、期限は60〜1800秒です。有効にした場合、未設定channelの仕事を
暗黙に共通workspaceへ戻さず拒否します。CLIの依頼はresult channelを使うため、そのIDも指定します。

## 利用期限と再開

同じchannelへ二つの処理を同時に入れません。期限は処理を追加するたびに延長せず、
期限切れは閉じた状態として表示します。実行中ならそのworkerの取消signalを発火し、
従来のowned process停止処理を使います。停止を確認できない場合は自動再開しません。

次の処理や期限後の再開では、次を照合してから利用します。

- 元repositoryのcanonical root/common Git directory、base commit、変更の有無、未push commitのdigest。
- channel worktreeのHEAD、tracked差分、ignoredを含むuntrackedの名前と実bytesのdigest。
- 前Taskが残した候補worktreeの同じcheckpoint。
- 前の自分の処理が終了し、現在のhost lock・設定・Task/Source scopeが一致すること。

不一致は`CHANNEL_WORKSPACE_*`の理由で止めます。reset、clean、候補や履歴の削除はしません。
指紋の確認は上限付きで、本文をログやstatusへ返しません。statusにはroomのdigest、generation、
期限、処理中/閉鎖/要照合などの状態を返します。以前のprocess終了が不明な場合は、operatorが
そのprocessの所有者と終了を確認してから回復します。PIDだけで他のprocessを停止しません。

元repositoryを更新し、古い候補を残して新しく始めたい場合は、operatorが`generation`を新しい値へ
変更してruntimeを再起動します。別のworktreeを作り、以前のデータを保持します。
終了不明の処理はgeneration変更でも迂回できません。設定変更を実行中のleaseへ黙って適用しません。

## 隔離の強さ

有効時の`worker.workspace`はGit repositoryのtop levelを指定します。subdirectoryを
黙ってrepository全体へ広げず拒否し、同じcommitを持つ別cloneへも旧leaseを流用しません。
元repositoryのignored filesは新しいworktreeへcopyしません。作業場に後から加わった
ignored filesは次の照合対象です。検査は30秒、untracked/ignoredは最大2000 files・合計20 MB
（1 file最大5 MB）に制限し、大きすぎるcandidateも成功のcheckpointにはしません。

この機能のGitコマンドだけで[hooksを無効にし](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corehooksPath)、
checkout/statusが任意programを動かすfilter属性も処理前に拒否します。利用者のGit設定は変更しません。
candidateの最終照合中もleaseを維持し、期限切れ・読み戻し失敗を成功したTask結果として返しません。
保存候補128件の上限は新規write candidateだけに適用し、read-onlyの仕事は継続できます。

directoryやGit worktreeの分離をsandboxとは呼びません。channel worktreeは参照baseで、
書込みTaskは引き続きTask/revision別のworktreeと既存の固定Docker verifierを使います。
候補を別の仕事へ自動採用せず、成果は元Taskから確認します。host credentialをworktreeへcopyしません。

| 実行場所 | この機能が保証する範囲 | 別に必要な条件 |
|---|---|---|
| 手元hostのworktree | channelの対応、期限、Git checkpoint、所有処理の取消 | OS権限とCLIのsandbox。directoryだけでは隔離しない |
| 既存container | 同じlease管理と既存Linux Docker検証 | operatorが用意したimage、mount、network、credential境界 |
| 既存VM | guest内の同じlease管理 | operatorが用意したVMとhypervisor、接続、resource境界 |

この機能はcontainer/VMの新規provision、credential移送、provider操作を行いません。
Windows/macOSのローカル書込みworkerの拒否は維持します。

## 確認範囲

一時Git repository、実worktree、実CLI fixtureとHTTP controlで、channel分離、期限、再開、
外部変更、untracked bytes、終了不明、generation切替と既存Taskへの返却を検査します。
モデル・providerへは接続しません。実host/container/VMの利用者による受入は未実施です（#143）。
