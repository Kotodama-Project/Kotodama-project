# kotodama-core 配布候補

公開Python配布物は`kotodama-core`、importは`kotodama_core`、診断CLIは
`kotodama-core`です。Nodeの`kotodama` CLIと並存します。PyPIへの公開は未実施です。

## APIと互換性

最初の公開APIは`__version__`、`canonical(value)`、`digest(value)`、`SwarmError`です。
`canonical`はstring keyのdict、list、有限数、bool、null、有効なUnicode文字列だけを受け、
key順、空白なし、Unicodeを保持した文字列へ変換し、
`digest`はそのUTF-8 bytesのSHA-256を返します。不正な値は`SwarmError`で拒否します。
object keyの暗黙変換、tuple、循環、64段を超える入れ子は拒否します。serializer／hashは
既存Task swarmの実装を同じsourceから収録し、public入口でこの入力制約を検査します。

`kotodama_core.task_swarm`以下の実行APIはexperimentalです。既存Task ownerの
scope・取消・source・budgetを引き続き要求し、package installで権限を作りません。
MCP／process機能には`swarm` extraと既存のhash付き依存lockが必要です。
別のpeer用Pythonを指定した場合も、serverはこのartifactの実ファイルから起動します。
peer側には従来どおりpeer依存だけを入れ、同じcore distributionの重複installを要求しません。
`tools/task_swarm.py`のdemoやrepoのexamplesは配布APIに含めません。

`0.2.0.dev0`は開発候補です。1.0前の破壊変更はminor版を上げ、patch版は互換修正のみとします。
1.0以降はSemVerに従います。experimental APIのconsumerは版だけでなくartifact SHA-256と
source commitを固定します。privateの`runtime`／`ktdm`互換、実consumer inventory、
canary／rollbackは#26の別の受入であり、このpackageからprivateをimportしません。

## ビルドと確認

Python 3.12の新しいvenvに、`requirements-package-ci.txt`を`--require-hashes`で入れます。
次に`python -m build --no-isolation`でwheelとsdistを作ります。
配布対象は明示した2packages、package README、MIT licenseとbuild metadataだけです。
source checkoutには既存の`runtime/task_swarm`を残し、wheel内だけnamespaceを付けます。
setuptoolsの[明示package mapping](https://setuptools.pypa.io/en/latest/userguide/package_discovery.html)
を使い、二つ目の実装を保守しません。

installした環境では`python -m kotodama_core`、`kotodama-core`、`kotodama-core --version`
が外部接続なしで動作します。`kotodama`／`ktdm`というconsole scriptは作りません。
この候補のbuild、検査、local installはrelease・private pin切替・本番利用の受入ではなく、
Public Betaは`NO_GO_UNPUBLISHED`です。
