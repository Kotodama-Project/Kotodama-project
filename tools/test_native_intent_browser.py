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
        p.close()
        project_brief = {"outcome": "Project独自の成果", "in_scope": ["複数行\nと絵文字🌱を保持"], "out_of_scope": [],
                         "constraints": ["公開しない"], "acceptance": ["同じProjectを読む"], "unknowns": []}
        project_state = {"state": "connected", "binding_sha256": "b"*64, "can_inspect": True,
                         "view": {"project": {"name": "Project候補", "project_id": "ref/project/fixture", "revision": 1, "brief": project_brief, "task_refs": []}, "project_digest": "a"*64}}
        script = "window.project=" + json.dumps(project_state, ensure_ascii=False) + """;
window.inspections=0;window.gadget={getState:async()=>({state:'ready',source:{overview:'原依頼'},result:{objective:'原資料の目的',deliverable:'原資料の成果物',constraints:['公開しない'],acceptance_criteria:['読戻し'],open_questions:[]}}),
getProject:async()=>project,inspectProjectChange:async input=>{inspections++;window.inspected=input;return {inspection:{expected_revision:input.expected_revision,changed_fields:['constraints'],removed_requirements:{constraints:['公開しない'],acceptance:[]},impact_task_refs:project.view.project.task_refs,applied:false}}}};
"""
        p = page(script); p.wait_for_function("!document.getElementById('project-inspect').disabled")
        p.locator('[data-field="constraints"] button').click(); p.locator('#project-reason').fill('条件の削除を検査する')
        p.locator('#project-inspect').click(); p.wait_for_function("!document.getElementById('project-inspection').hidden")
        actual = p.evaluate("({inspections,input:inspected,original:document.getElementById('result').textContent,inspection:document.getElementById('project-inspection').textContent})")
        expected_brief = dict(project_brief, constraints=[])
        add("project-inspection-preserves-separate-requirements", "Project fields and original objective/deliverable remain distinct; no implicit saving", actual,
            actual['inspections']==1 and actual['input']['brief']==expected_brief and '原資料の目的' in actual['original'] and '原資料の成果物' in actual['original'] and '保存されていません' in actual['inspection'], "project-inspection")
        p.evaluate("() => { gadget.getProject=async()=>{throw Error('revoked')}; }"); p.locator('#project-reload').click()
        p.wait_for_function("document.getElementById('project-status').textContent.includes('表示できません')")
        actual = p.evaluate("({name:document.getElementById('project-name').textContent,items:document.querySelectorAll('#project-editor textarea').length,disabled:document.getElementById('project-inspect').disabled,hidden:document.getElementById('project-inspection').hidden,inspections})")
        add("project-revocation-clears-content", "Revocation removes Project data and inspection; no retry", actual,
            actual['name']=='' and actual['items']==0 and actual['disabled'] and actual['hidden'] and actual['inspections']==1, "project-access")
        p.close()
        p = page(script); p.wait_for_function("!document.getElementById('project-inspect').disabled")
        p.evaluate("() => { window.projectReads=0;gadget.getProject=()=>{projectReads++;if(projectReads===1)return new Promise(r=>window.oldProject=r);return Promise.resolve({...project,view:{...project.view,project:{...project.view.project,name:'最新のProject'}}})}; }")
        p.locator('#project-reload').click(); p.wait_for_function('window.oldProject !== undefined'); p.locator('#project-reload').click()
        p.wait_for_function("document.getElementById('project-name').textContent.includes('最新のProject')")
        p.evaluate("oldProject(project)"); p.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
        actual = p.evaluate("({name:document.getElementById('project-name').textContent,projectReads})")
        add("project-new-read-supersedes-old", "Delayed Project read cannot replace newer result", actual, '最新のProject' in actual['name'] and actual['projectReads']==2, "project-read-ordering")
        p.close()
        large_brief = dict(project_brief)
        for key in ('in_scope', 'out_of_scope', 'constraints', 'acceptance', 'unknowns'):
            large_brief[key] = [f"{n:02}:" + '界'*997 for n in range(20)]
        large_state = dict(project_state, view=dict(project_state['view'], project=dict(project_state['view']['project'], brief=large_brief)))
        p = page(script.replace(json.dumps(project_state, ensure_ascii=False), json.dumps(large_state, ensure_ascii=False)))
        p.wait_for_function("!document.getElementById('project-inspect').disabled")
        p.locator('[data-field="outcome"] textarea').fill('編集を失わず候補を検査する'); p.locator('#project-reason').fill('サイズ上限を確認する')
        p.locator('#project-inspect').click()
        actual = p.evaluate("({inspections,status:document.getElementById('project-status').textContent,outcome:document.querySelector('[data-field=outcome] textarea').value,items:document.querySelectorAll('#project-editor textarea').length})")
        add("project-size-refusal-preserves-edits", "Input above owner transport scope is refused locally without losing edits", actual,
            actual['inspections']==0 and '上限を超えています' in actual['status'] and actual['outcome']=='編集を失わず候補を検査する' and actual['items']==101, "project-input-boundary")
        p.close()
        task_refs = [{"adapter": "discord_local_task_v1", "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 2},
                     {"adapter": "swarm_execution_v1", "task_id": "task-00000000-0000-4000-8000-000000000002", "revision": 3, "owner_ref": "ref/owner/<img src=x>", "context_digest": "e"*64}]
        typed_state = dict(project_state, view=dict(project_state['view'], project=dict(project_state['view']['project'], version=2, task_refs=task_refs)))
        p = page(script.replace(json.dumps(project_state, ensure_ascii=False), json.dumps(typed_state, ensure_ascii=False)))
        p.wait_for_function("!document.getElementById('project-inspect').disabled")
        p.locator('[data-field="constraints"] button').click(); p.locator('#project-reason').fill('Taskの参照を保持して検査する'); p.locator('#project-inspect').click()
        p.wait_for_function("!document.getElementById('project-inspection').hidden")
        actual = p.evaluate("({inspections,read:document.getElementById('project-tasks').textContent,impact:document.getElementById('project-inspection').textContent,inputKeys:Object.keys(inspected),images:document.querySelectorAll('#project-card img').length})")
        preserved = all(str(ref[key]) in actual[field] for ref in task_refs for key in ('task_id', 'revision') for field in ('read', 'impact'))
        add("project-v2-typed-refs-read-and-inspection", "Local Task and swarm input references are preserved without claiming completion or allowing reference mutation", actual,
            preserved and task_refs[1]['owner_ref'] in actual['read'] and task_refs[1]['context_digest'] in actual['impact'] and '完了を確認した表示ではありません' in actual['read'] and 'task_refs' not in actual['inputKeys'] and actual['images']==0 and actual['inspections']==1, "project-task-references")
        p.evaluate("() => { gadget.getProject=async()=>{throw Error('revoked')}; }"); p.locator('#project-reload').click()
        p.wait_for_function("document.getElementById('project-status').textContent.includes('表示できません')")
        actual = p.evaluate("({read:document.getElementById('project-tasks').textContent,impact:document.getElementById('project-inspection').textContent})")
        add("project-v2-revocation-removes-task-references", "Denied reread clears current and affected references", actual, actual['read']=='' and actual['impact']=='', "project-access")
        p.close();browser.close()
    counts={s:sum(r['status']==s for r in records) for s in ('PASS','FAIL')}
    report={"scope":__doc__,"client_sha256":hashlib.sha256(client.read_bytes()).hexdigest(),"counts":counts,
            "personas":12,"variant_count_not_independent_journeys":len(records),"behavior_families":sorted({r['family'] for r in records}),
            "claims":{"native_os_integration":False,"real_authentication":False,"actual_codex_inference":False},"cases":records}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if counts['FAIL'] else 0

if __name__=='__main__':
    raise SystemExit(main())
