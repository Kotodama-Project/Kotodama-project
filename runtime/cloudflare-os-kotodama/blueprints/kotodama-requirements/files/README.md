# Kotodama 要件整理

KOTODAMA_BRIEF Gatekeeperに束縛された一つの依頼を読み、Codex契約で要件案を作る。
Gadgetが保存するのはrequest locatorだけ。依頼と結果は毎回Gatekeeper経由で読み、権限を再検査する。
新しいUUIDでの自動再試行、任意prompt/command/endpoint、Task正本の完了変更、公開は行わない。
要件案はcandidateであり、人間承認や実行権限ではない。
