"""Actual Gadget client in Chromium with synthetic RPC; NOT native OS or live Codex E2E."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "runtime/cloudflare-os-kotodama/blueprints/kotodama-requirements/files/client.js"
PERSONAS = [("経営者", "意思決定"), ("業務管理者", "担当引継ぎ"), ("営業", "顧客提案"),
            ("顧客対応", "回答案"), ("経理", "月次照合"), ("人事", "入社案内"),
            ("PM", "優先順位の訂正"), ("開発者", "独立レビュー"), ("運用", "停止確認"),
            ("契約審査", "未回答事項"), ("調査", "根拠の版"), ("外部協力者", "担当範囲")]
STATES = ("not_connected", "ready_to_request", "awaiting_approval", "approval_unknown", "rejected", "running", "ready", "failed", "interrupted", "unknown_state")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    client = args.root / RELATIVE
    records = []
    with sync_playwright() as pw:
        executable = os.environ.get("CHROMIUM_EXECUTABLE")
        browser = pw.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
        def page(script, width=360):
            p = browser.new_page(viewport={"width": width, "height": 800})
            p.route("**/*", lambda route: route.abort())
            p.goto("about:blank"); p.evaluate(script); p.add_script_tag(path=str(client))
            # Drain the RPC promise/microtasks; no fixed sleep is the success oracle.
            p.wait_for_function("document.getElementById('source')?.textContent !== '確認しています…'")
            return p
        def add(case_id, expected, actual, condition, family):
            records.append({"id": case_id, "family": family, "expected": expected,
                            "actual": actual, "status": "PASS" if condition else "FAIL"})
        for i, (role, goal) in enumerate(PERSONAS):
            for state, inconsistent in ((s, f) for s in STATES for f in (False, True)):
                source = f"{role}の依頼: {goal}。未確定な条件を勝手に合格にしない。"
                result = {"objective": goal, "deliverable": "合成の成果物候補", "constraints": ["外部送信しない"],
                          "acceptance_criteria": ["未検証を完了と表示しない"], "open_questions": ["追加確認が必要"]}
                payload = {"state": state, "source": {"overview": source}, "result": result if state == "ready" or inconsistent else None}
                script = "window.mutations=0;window.gadget={getState:async()=>(" + json.dumps(payload,ensure_ascii=False) + "),requestBrief:async()=>{mutations++;throw Error('not requested')}}"
                p = page(script)
                actual = p.evaluate("({source:document.getElementById('source').textContent, enabled:!document.getElementById('run').disabled, visible:!document.getElementById('result').hidden, text:document.getElementById('result').textContent, mutations})")
                okay = actual["source"] == source and actual["enabled"] == (state == "ready_to_request") and actual["visible"] == (state == "ready") and actual["mutations"] == 0
                if state == "ready": okay = okay and all(t in actual["text"] for t in (goal, "外部送信しない", "未検証を完了と表示しない", "追加確認が必要"))
                add(f"persona-{i}/{state}/{'inconsistent-candidate' if inconsistent else 'normal'}", "Only a ready candidate is shown; only ready_to_request enables execution; no implicit RPC mutation", actual, okay, "inconsistent-candidate-visibility" if inconsistent else "normal-state-visibility")
                p.close()
            for width in (320, 360, 390, 768, 1280):
                source = goal + " https://example.invalid/" + "x"*512
                p = page("window.gadget={getState:async()=>({state:'ready_to_request',source:{overview:"+json.dumps(source)+"}}),requestBrief:async()=>{throw Error('not used')}}", width)
                actual = p.evaluate("({viewport:innerWidth,scroll:document.documentElement.scrollWidth})")
                add(f"persona-{i}/width-{width}", "No horizontal viewport overflow", actual, actual["scroll"] <= width, "responsive-layout")
                if args.evidence_dir and i == 0 and width == 360:
                    args.evidence_dir.mkdir(parents=True,exist_ok=True);p.screenshot(path=str(args.evidence_dir/"native-mobile.png"),full_page=True)
                p.close()
        p = page("""window.calls=0;window.gadget={getState:()=>{calls++;if(calls===2)return new Promise(r=>window.oldRead=r);return Promise.resolve({state:'ready_to_request',source:{overview:calls===1?'FIRST':'LATEST'}})},requestBrief:async()=>{throw Error('not used')}}""")
        p.locator('#reload').click(); p.wait_for_function('calls===2'); p.locator('#reload').click()
        p.evaluate("oldRead({state:'ready_to_request',source:{overview:'OBSOLETE'}})")
        p.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
        actual=p.evaluate("({calls,source:document.getElementById('source').textContent})")
        add("manual-recheck-supersedes-hung-read", "LATEST survives delayed obsolete response; recheck is not inert", actual, actual['source']=='LATEST' and actual['calls']==3, "read-ordering")
        p.close()
        p = page("""window.calls=0;window.mutations=0;window.gadget={getState:()=>{calls++;if(calls===2)return new Promise(r=>window.oldRead=r);return Promise.resolve({state:'ready_to_request',source:{overview:'OLD'}})},requestBrief:async()=>{mutations++;throw Error('revoked')}}""")
        p.locator('#reload').click();p.wait_for_function('calls===2')
        # A pending recheck must remove stale execution affordance; no forced click.
        actual=p.evaluate("({disabled:document.getElementById('run').disabled,mutations})")
        add("pending-read-not-actionable", "Old ready state cannot authorize a click during recheck",actual,actual['disabled'] and actual['mutations']==0,"read-action-boundary")
        p.close()
        p=page("""window.calls=0;window.mutations=0;window.gadget={getState:async()=>{calls++;return {state:'ready_to_request',source:{overview:'OLD'}}},requestBrief:()=>{mutations++;return new Promise((r,j)=>window.failRequest=j)}}""")
        p.locator('#run').click();p.wait_for_function('window.failRequest !== undefined')
        # A queued duplicate DOM event must not create a second mutation.
        p.locator('#run').dispatch_event('click');p.locator('#reload').click()
        p.evaluate("failRequest(Error('revoked'))")
        p.wait_for_function("document.getElementById('status').classList.contains('error') || window.calls>1")
        actual=p.evaluate("({calls,mutations,source:document.getElementById('source').textContent,disabled:document.getElementById('run').disabled})")
        add("failure-and-double-click", "One mutation only; failure is not overwritten by automatic old-state read",actual,actual['mutations']==1 and actual['calls']==1 and actual['disabled'] and actual['source']!='OLD',"mutation-ordering")
        p.close()
        p=page("window.gadget={getState:async()=>({state:'ready',source:{overview:'<img src=x onerror=alert(1)>'},result:{objective:'<script>boom</script>',deliverable:'candidate',constraints:[],acceptance_criteria:[],open_questions:[]}})}")
        actual=p.evaluate("({images:document.querySelectorAll('main img').length,scripts:document.querySelectorAll('main script').length,text:document.getElementById('result').textContent})")
        add("literal-untrusted-text-and-empty-criteria", "Text is inert; missing criteria are not presented as no more questions",actual,actual['images']==0 and actual['scripts']==0 and '確認済みという意味ではありません' in actual['text'],"inert-and-unknown")
        p.close();browser.close()
    counts={s:sum(r['status']==s for r in records) for s in ('PASS','FAIL')}
    report={"scope":__doc__,"client_sha256":hashlib.sha256(client.read_bytes()).hexdigest(),"counts":counts,
            "personas":12,"variant_count_not_independent_journeys":len(records),"behavior_families":sorted({r['family'] for r in records}),
            "claims":{"native_os_integration":False,"real_authentication":False,"actual_codex_inference":False},"cases":records}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if counts['FAIL'] else 0

if __name__=='__main__':
    raise SystemExit(main())
