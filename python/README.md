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
`python -m kotodama_core.task_swarm.closed_loop --help`で、既存ownerへ束縛する
閉ループの実験入口を確認できます。現在は明示local simulationのみで、実provider・
planner生成は未接続です。詳細は`docs/TASK-SWARM-CLOSED-LOOP.md`を参照してください。
`python -m kotodama_core.task_swarm.learning_reuse --help`は、一つの学びを独立reviewと
既存owner判断を経て次のTaskへ渡す限定入口です。会社のCurrent Truthへ昇格せず、
実providerも呼びません。入力と判断は`docs/TASK-LEARNING-REUSE.md`を参照してください。

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
時刻、mode、ownerを正規化します。OSで異なる生成metadataの改行をLFに統一し、wheel
RECORDのhash／sizeを再生成して検査します。package sourceとLICENSEのbytesは変更しません。

SHA256SUMS、source commit／tree、各source digest、tool版、正規化方法、artifact digest、
buildとoptional swarm用lockのCycloneDX inventoryを出力します。lock inventoryは全条件の
配布候補を含み、実installのSBOMや第三者license受入を主張しません。基本packageのruntime
外部依存はゼロです。raw build logとstagingは診断用で、公開artifactには含めません。

専用CIはLinuxとWindowsで各2回buildし、digestを照合して両artifactを新venvへinstallします。
さらに両OSからdownloadした実bytesとreceiptを比較します。
receiptは未署名のbuilder観測です。署名とdownload検証は既存のrelease workflowのowner
採用方針およびtag/release受入を必要とし、PRのartifact uploadをreleaseの署名と呼びません。

builder自体、SBOM generator、実行記録ツール、workflow、probe、依存lockもcommitへ照合し、
開始・完了時のHEADと入力bytesの変化を拒否します。`builder_inputs`がそのdigest一覧です。
専用CIは別のexecution receiptへworkflow ref/SHA、run/attempt、実job ID、artifact IDと
archive digestをGitHubの読み取りAPIで照合して記録します。PRのevent headと実buildの
merge commitは別欄で保持します。この記録は未署名で、release承認やsigner受入ではありません。

tagで起動するrelease workflowは、tagを`v`+pyprojectのversionと完全一致させ、wheel、
sdist、packageのSBOM、builder receipt、checksumも既存のattestationとdraft prereleaseへ
含めます。過去のsource-only tagを新しいpackage版へ読み替えません。実tagのpushはownerが
版・署名者・private consumer条件を受け入れた後に行い、この変更だけでは起動しません。
