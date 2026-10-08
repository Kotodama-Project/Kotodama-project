# kotodama-core 配布候補

公開Python配布物は`kotodama-core`、importは`kotodama_core`、診断CLIは
`kotodama-core`です。Nodeの`kotodama` CLIと並存します。PyPIへの公開は未実施です。

## APIと互換性

最初の公開APIは`__version__`、`canonical(value)`、`digest(value)`、`SwarmError`です。
`canonical`は有限JSONをkey順、空白なし、Unicodeを保持した文字列へ変換し、
`digest`はそのUTF-8 bytesのSHA-256を返します。不正な値は`SwarmError`で拒否します。
これらは既存Task swarmの実装を同じsourceから収録します。

`kotodama_core.task_swarm`以下の実行APIはexperimentalです。既存Task ownerの
scope・取消・source・budgetを引き続き要求し、package installで権限を作りません。
MCP／process機能には`swarm` extraと既存のhash付き依存lockが必要です。
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

## 同じcommitからのartifact記録（#28）

共通の`requirements-ci.txt`とpackage用`requirements-package-ci.txt`をhash付きで入れ、
cleanな対象commitで`python -B tools/build_python_candidate.py --output work/new-candidate`
を実行します。outputは未作成のディレクトリを指定します。固定commitの許可ファイルだけを
stagingへ取り出し、wheel／sdistの内容とsource・MITを照合します。ZIP／tar／gzipの順序、
時刻、mode、ownerを正規化し、wheel RECORDは変更しません。

SHA256SUMS、source commit／tree、各source digest、tool版、正規化方法、artifact digest、
buildとoptional swarm用lockのCycloneDX inventoryを出力します。lock inventoryは全条件の
配布候補を含み、実installのSBOMや第三者license受入を主張しません。基本packageのruntime
外部依存はゼロです。raw build logとstagingは診断用で、公開artifactには含めません。

専用CIはLinuxとWindowsで各2回buildし、digestを照合して両artifactを新venvへinstallします。
receiptは未署名のbuilder観測です。署名とdownload検証は既存のrelease workflowのowner
採用方針およびtag/release受入を必要とし、PRのartifact uploadをreleaseの署名と呼びません。
