# Task workerの読取範囲

#160 / #286のworkerは、渡されたTaskとSourceだけで報告を作ります。read-onlyという
設定だけでは、host上の他のファイルを読めないことを意味しません。このhelperはLinuxの
native Codex CLIを二層のpermission profileで実行するための前提を検査します。
Task runnerへの接続とlive受入は別途必要です。

## 実行領域と認証

外側はCLI process全体をroot denyにし、native実行ファイル・system library・証明書・
DNS設定・今回のattempt・明示されたTask専用Codex homeだけを許します。
内側のmodel commandには実行用system fileと空のwork領域だけをreadで許し、networkを
無効にします。Task本文はstdinで渡します。両profileとも広いread presetを継承しません。

operatorが別途ログインしたTask専用Codex homeを明示してください。通常のCodex home、
ambient CODEX_HOME、symlink/hardlinkのauth、group/otherが読めるhome/authは拒否します。
helperはcredentialを複製・移動・リンクしません。専用CLIは専用home内で認証の更新と
実行metadataを管理し、modelの内側profileはそのhomeを読めません。専用ログインの
準備とlive有効化は、この実装や合成試験では実行していません。

user config/rules、AGENTS、memoryの注入・生成、hooks、apps/plugins、browser、image、
shell、code mode、子agent、web searchを明示的に無効化します。CLIのstrict configと
実permission probeが通らない実装では、model呼出しを始めません。native Linux ELFを
指定し、package-managerのwrapperやnative Windowsへ暗黙に切り替えません。

## 合成probeと証拠の限界

毎回model起動前に、このattemptが作った合成fileだけで二つのprofileを試します。
work内のfileを読め、外側から隣接fileを読めず、内側からattempt metadataを読めない
ことを検査します。実credentialや利用者fileをprobeの対象にしません。
receiptはこの三つの観測を示すもので、全toolの網羅試験やprovider受入の証明ではありません。
CIも固定CLIと合成authを用い、model/APIを呼びません。

設定の根拠は[公式permission profile](https://learn.chatgpt.com/docs/permissions)と
[公式config reference](https://learn.chatgpt.com/docs/config-file/config-reference)です。
profileが強制できないhostでは、host設定を緩めて試験を通さず、未対応として停止します。
