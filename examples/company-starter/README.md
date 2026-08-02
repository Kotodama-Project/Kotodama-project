# Company Starter Example

このdirectoryは、外部依存なしのvalidatorで検証できる最小Company Template packです。

```powershell
python tools/validate_template_pack.py examples/company-starter
```

成功時はJSONで`"status": "PASS"`を返し、終了codeは`0`です。

これはsyntheticな構造例です。provider接続、runtime deployment、権限付与、Promotion、Public Beta GOは行いません。
