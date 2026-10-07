#!/usr/bin/env python3
"""Numeric quality budgets for a pinned, separately built public upstream."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BUDGET_PATH=Path('runtime/cloudflare-os/quality-budget.json')
RULES={'eslint(no-shadow)','unicorn(consistent-function-scoping)','typescript(no-this-alias)','typescript(no-extraneous-class)'}
FRONTEND_KEYS={'js_count','js_bytes','js_gzip_bytes','css_count','css_bytes','css_gzip_bytes','small_js_bytes','large_js'}


class Refused(ValueError): pass


def require(value,code):
    if not value:raise Refused(code)


def number(value):
    return type(value) is int and 0<=value<=128*1024*1024


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def read_bytes(path,limit):
    path=Path(path);before=path.lstat()
    require(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode) and before.st_nlink==1 and
            not getattr(before,'st_file_attributes',0)&0x400 and before.st_size<=limit,'INPUT_FILE_REFUSED')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        opened=os.fstat(fd)
        require((opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino),'INPUT_CHANGED')
        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(limit+1)
        after=os.fstat(fd);named=path.lstat()
        require(len(data)==opened.st_size and len(data)<=limit and
                (opened.st_mtime_ns,opened.st_ctime_ns)==(after.st_mtime_ns,after.st_ctime_ns) and
                (named.st_dev,named.st_ino)==(opened.st_dev,opened.st_ino) and not stat.S_ISLNK(named.st_mode),'INPUT_CHANGED')
        return data
    finally:os.close(fd)


def parse(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'DUPLICATE_JSON_KEY');result[key]=value
        return result
    def invalid(_value):raise Refused('NONFINITE_JSON')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def read_json(path):return parse(read_bytes(path,2*1024*1024))


def timestamp(value):
    require(isinstance(value,str) and value.endswith('Z'),'TIME_INVALID')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def validate_budget(budget,*,now=None,previous=None):
    require(isinstance(budget,dict) and set(budget)=={'version','source','observed_at','valid_until','warning_limits','warning_ids','frontend_limits','measurement','review_scope'},'BUDGET_SHAPE')
    require(budget['version']==1 and type(budget['version']) is int,'BUDGET_VERSION')
    require(budget['review_scope']=='temporary_local_evaluation_only','REVIEW_SCOPE')
    pin=read_json(ROOT/'runtime/cloudflare-os/upstream-pin.json')
    old=read_json(ROOT/'runtime/cloudflare-os/local-runtime-evaluation.json')
    source_lock=read_json(ROOT/'runtime/cloudflare-os/security-overlay.json')['source']['lock']
    expected={'repository':'cloudflare/cloudflare-os','commit':pin['starter_core_gitlink']['commit'],
              'tree':pin['starter_core_gitlink']['tree'],'lock_sha256':source_lock['canonical_sha256'],'lock_line_endings':'LF',
              'node':old['toolchain']['node'],'pnpm':old['toolchain']['pnpm'],'dependency_graph':'original_pinned_no_overlay'}
    require(budget['source']==expected,'BASELINE_MISMATCH')
    observed,expires=timestamp(budget['observed_at']),timestamp(budget['valid_until'])
    current=now or datetime.now(timezone.utc)
    require(observed<=current<expires and 0<(expires-observed).total_seconds()<=45*86400,'REVIEW_EXPIRED_OR_INVALID')
    limits={}
    for row in budget['warning_limits']:
        require(set(row)=={'package','rule','origin','max','owner'} and row['rule'] in RULES and
                re.fullmatch(r'(packages/[a-z0-9-]+|scripts)',row['package']) and row['origin'] in {'source','generated','vendor'} and
                row['owner']=='cloudflare_upstream' and number(row['max']),'WARNING_LIMIT_INVALID')
        key=(row['package'],row['rule'],row['origin']);require(key not in limits,'DUPLICATE_WARNING_BUCKET');limits[key]=row['max']
    ids=budget['warning_ids']
    require(isinstance(ids,list) and len(ids)==len(set(ids))==sum(limits.values())<=old['verification']['lint']['warnings'] and
            all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in ids),'WARNING_ID_COVERAGE')
    frontend=budget['frontend_limits']
    require(set(frontend)==FRONTEND_KEYS and all(number(v) for k,v in frontend.items() if k!='large_js') and
            0<frontend['js_count']<=4096 and frontend['small_js_bytes']<=500000,'FRONTEND_LIMIT_INVALID')
    require(isinstance(frontend['large_js'],dict) and len(frontend['large_js'])<=16,'LARGE_CHUNK_INVALID')
    for key,value in frontend['large_js'].items():
        require(re.fullmatch('[a-zA-Z0-9_.-]+',key) and set(value)=={'count','bytes','gzip_bytes'} and
                all(number(v) for v in value.values()),'LARGE_CHUNK_INVALID')
    measurement=budget['measurement']
    require(set(measurement)=={'lint_files','lint_rules','lint_input_sha256','asset_set_sha256','cold_build_ms','navigation_load_ms','interactive_ready','provider_verified'},'MEASUREMENT_SHAPE')
    require(measurement['interactive_ready'] is False and measurement['provider_verified'] is False,'QUALITY_IS_NOT_ACCEPTANCE')
    require(number(measurement['lint_files']) and number(measurement['lint_rules']) and number(measurement['cold_build_ms']) and
            len(measurement['navigation_load_ms'])==3 and all(number(v) for v in measurement['navigation_load_ms']) and
            all(re.fullmatch('[a-f0-9]{64}',measurement[k]) for k in ('lint_input_sha256','asset_set_sha256')),'MEASUREMENT_INVALID')
    if previous is not None:
        require(previous['version']==budget['version'],'BUDGET_VERSION_CHANGED')
        prior={(r['package'],r['rule'],r['origin']):r['max'] for r in previous['warning_limits']}
        require(all(value<=prior.get(key,0) for key,value in limits.items()),'WARNING_BUDGET_INCREASED')
        for key,value in frontend.items():
            if key!='large_js':require(value<=previous['frontend_limits'][key],'CHUNK_BUDGET_INCREASED')
        for key,value in frontend['large_js'].items():
            before=previous['frontend_limits']['large_js'].get(key,{})
            require(all(n<=before.get(field,0) for field,n in value.items()),'CHUNK_EXCEPTION_INCREASED')
    return limits


def warning_summary(lint):
    counts=Counter();ids=[];errors=0
    require(isinstance(lint,dict) and isinstance(lint.get('diagnostics'),list) and len(lint['diagnostics'])<=10000,'LINT_SHAPE')
    for row in lint['diagnostics']:
        require(row['severity'] in {'warning','error'},'LINT_SEVERITY')
        if row['severity']=='error':errors+=1;continue
        filename=row['filename'].replace('\\','/')
        require(not filename.startswith('/') and ':' not in filename and '..' not in filename.split('/'),'LINT_PATH')
        package='/'.join(filename.split('/')[:2]) if filename.startswith('packages/') else 'scripts'
        origin='vendor' if '/vendor/' in filename or '/node_modules/' in filename else 'generated' if '/generated/' in filename or '/dist/' in filename or filename.endswith('.gen.ts') else 'source'
        counts[(package,row['code'],origin)]+=1
        ids.append(sha({'file':filename,'rule':row['code'],'spans':[v.get('span') for v in row.get('labels',[])]}))
    require(len(ids)==len(set(ids)),'DUPLICATE_WARNING')
    return errors,counts,sorted(ids)


def asset_summary(directory):
    root=Path(directory).resolve(strict=True);assets=[]
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(),'ASSET_LINK_REFUSED')
        if not path.is_file():continue
        name=path.relative_to(root).as_posix()
        require(len(assets)<4096 and path.resolve().is_relative_to(root),'ASSET_SCOPE')
        if path.suffix not in {'.js','.css'}:continue
        raw=read_bytes(path,32*1024*1024)
        assets.append({'name':name,'bytes':len(raw),'gzip_bytes':len(gzip.compress(raw,mtime=0)),'sha256':hashlib.sha256(raw).hexdigest()})
    return assets


def compare(budget,lint,assets):
    limits=validate_budget(budget)
    errors,counts,ids=warning_summary(lint)
    require(errors==0,'LINT_ERRORS')
    require(all(value<=limits.get(key,0) for key,value in counts.items()),'WARNING_GROWTH')
    require(set(ids)<=set(budget['warning_ids']),'UNREVIEWED_WARNING')
    require(isinstance(assets,list) and assets and len(assets)<=4096,'ASSET_SET')
    frontend=budget['frontend_limits'];large=Counter();names=set()
    for row in assets:
        require(set(row)=={'name','bytes','gzip_bytes','sha256'} and row['name'] not in names and
                number(row['bytes']) and number(row['gzip_bytes']) and row['bytes']>0 and row['gzip_bytes']>0 and
                re.fullmatch('[a-f0-9]{64}',row['sha256']),'ASSET_INVALID');names.add(row['name'])
        require(re.fullmatch(r'assets/[a-zA-Z0-9_.-]+\.(js|css)',row['name']),'ASSET_NAME')
        if row['name'].endswith('.js') and row['bytes']>frontend['small_js_bytes']:
            logical=re.sub(r'-[A-Za-z0-9_-]{8}\.js$','',Path(row['name']).name)
            allowed=frontend['large_js'].get(logical)
            require(allowed is not None and row['bytes']<=allowed['bytes'] and row['gzip_bytes']<=allowed['gzip_bytes'],'CHUNK_GROWTH')
            large[logical]+=1
    require(all(count<=frontend['large_js'][key]['count'] for key,count in large.items()),'CHUNK_EXCEPTION_COUNT')
    for suffix in ('js','css'):
        group=[row for row in assets if row['name'].endswith('.'+suffix)]
        require(len(group)<=frontend[suffix+'_count'] and sum(r['bytes'] for r in group)<=frontend[suffix+'_bytes'] and
                sum(r['gzip_bytes'] for r in group)<=frontend[suffix+'_gzip_bytes'],'ASSET_TOTAL_GROWTH')
    require(any(row['name'].endswith('.js') for row in assets),'ASSET_SET')
    return {'status':'WITHIN_NUMERICAL_LIMITS','warnings':sum(counts.values()),'errors':0,
            'review_identity_verified':False,'provider_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget',type=Path,default=ROOT/BUDGET_PATH)
    parser.add_argument('--previous-git-ref')
    parser.add_argument('--lint-json',type=Path)
    parser.add_argument('--dist',type=Path)
    parser.add_argument('--core-repo',type=Path)
    args=parser.parse_args()
    try:
        previous=None
        if args.previous_git_ref:
            require(re.fullmatch('[a-f0-9]{40}',args.previous_git_ref),'BASE_REF_INVALID')
            available=subprocess.run(['git','cat-file','-e',args.previous_git_ref+'^{commit}'],cwd=ROOT,capture_output=True,timeout=10)
            require(available.returncode==0,'BASE_COMMIT_UNAVAILABLE')
            prior=subprocess.run(['git','show',args.previous_git_ref+':'+BUDGET_PATH.as_posix()],cwd=ROOT,capture_output=True,timeout=10)
            if prior.returncode==0:previous=parse(prior.stdout)
            else:
                # Distinguish the first introduction from a missing/corrupt blob.
                tree=subprocess.run(['git','ls-tree',args.previous_git_ref,'--',BUDGET_PATH.as_posix()],cwd=ROOT,capture_output=True,timeout=10,check=True)
                require(not tree.stdout.strip(),'PREVIOUS_BUDGET_UNAVAILABLE')
        budget=read_json(args.budget);limits=validate_budget(budget,previous=previous)
        require((args.lint_json is None)==(args.dist is None),'OBSERVATION_PAIR_REQUIRED')
        if args.dist is not None:
            require(args.core_repo is not None,'SOURCE_CHECKOUT_REQUIRED')
            core=args.core_repo.resolve(strict=True)
            require(args.dist.resolve(strict=True)==(core/'packages/workshop-frontend/dist').resolve(strict=True),'DIST_SCOPE')
            def git(*parts):
                return subprocess.run(['git',*parts],cwd=core,capture_output=True,timeout=15,check=True).stdout
            require(git('rev-parse','HEAD').decode().strip()==budget['source']['commit'] and
                    git('rev-parse','HEAD^{tree}').decode().strip()==budget['source']['tree'],'SOURCE_CHECKOUT_CHANGED')
            git('diff','--no-ext-diff','--quiet','HEAD')
            require(hashlib.sha256(git('show','HEAD:pnpm-lock.yaml')).hexdigest()==budget['source']['lock_sha256'],'LOCK_CHANGED')
        result=compare(budget,read_json(args.lint_json),asset_summary(args.dist)) if args.lint_json else {
            'status':'BUDGET_CONTRACT_VALID','warning_ceiling':sum(limits.values()),'fresh_build_verified':False,
            'review_identity_verified':False,'provider_verified':False}
        result['fresh_build_verified']=False
        result['source_checkout_matches_pin']=args.dist is not None
        print(json.dumps(result,sort_keys=True));return 0
    except Refused as exc:
        print(json.dumps({'status':'REFUSED','reason':str(exc)}));return 1
    except (OSError,ValueError,TypeError,KeyError,RecursionError,subprocess.SubprocessError):
        print(json.dumps({'status':'REFUSED','reason':'QUALITY_BUDGET_OR_OBSERVATION_INVALID'}));return 1


if __name__=='__main__':raise SystemExit(main())
