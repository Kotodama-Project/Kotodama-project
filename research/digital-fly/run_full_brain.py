#!/usr/bin/env python3
"""Run the unchanged author's Brian2 model on the full, hash-verified v630 graph.
No synthetic graph or simulated success. Public research inputs only.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import importlib.metadata as md
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import urllib.request

COMMIT='91bdd1e7dcf193f3e7ca5a8933497fcef63b7960'
BASE=f'https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/{COMMIT}/'
ASSETS={
'2023_03_23_completeness_630_final.csv':(3057611,'be745f0ce054308df21accc5c4b3883aa38498f9'),
'2023_03_23_connectivity_630_final.parquet':(86630944,'8b4d9531bc0acbda7c2074ae577e6ac9e2fca166'),
'model.py':(11900,'5ba7083cf55bf6092967f8d9065e86cd677efed1'),
'example.ipynb':(10282,'bc479485c42c18ef50762d9ab50817bc96d65c8d'),
'environment_full.yml':(3445,'1428b314d40bf8b7dc2cb3991db213c12033fdfc'),
'LICENSE':(1085,'deca2d0f1e82e910d8248b0d27398eb9450976ee'),
'results/example/sugarR_100Hz.parquet':(557849,'bd76730d5e991d64b756f354a749f94ffb874c64')}
SUGAR=[720575940624963786,720575940630233916,720575940637568838,720575940638202345,
720575940617000768,720575940630797113,720575940632889389,720575940621754367,
720575940621502051,720575940640649691,720575940639332736,720575940616885538,
720575940639198653,720575940620900446,720575940617937543,720575940632425919,
720575940633143833,720575940612670570,720575940628853239,720575940629176663,720575940611875570]
MN9=720575940660219265
PRE,POST,WEIGHT='Presynaptic_Index','Postsynaptic_Index','Excitatory x Connectivity'
EXPECTED={'brian2':'2.5.1','numpy':'1.22.3','scipy':'1.8.1','pandas':'1.4.3',
'pyarrow':'11.0.0','Cython':'0.29.33','sympy':'1.12','joblib':'1.2.0'}

def emit(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    temp.replace(path)

def identity(path):
    size=path.stat().st_size;g=hashlib.sha1(f'blob {size}\0'.encode());s=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):g.update(block);s.update(block)
    return {'bytes':size,'git_blob_sha1':g.hexdigest(),'sha256':s.hexdigest()}

def acquire(out):
    raw=out/'raw';records=[]
    for name,(size,blob) in ASSETS.items():
        target=raw/name;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            for attempt in range(3):
                try:
                    req=urllib.request.Request(BASE+name,headers={'User-Agent':'DigitalFlyLab-real-brain-reproduction'})
                    partial=target.with_suffix(target.suffix+'.partial')
                    with urllib.request.urlopen(req,timeout=90) as r,partial.open('wb') as f:
                        total=0
                        for block in iter(lambda:r.read(1<<20),b''):
                            total+=len(block)
                            if total>size:raise ValueError('Data exceeds pinned size')
                            f.write(block)
                    got=identity(partial)
                    assert (got['bytes'],got['git_blob_sha1'])==(size,blob),(name,got)
                    partial.replace(target);break
                except Exception:
                    if attempt==2:raise
                    time.sleep(2*(attempt+1))
        got=identity(target)
        assert (got['bytes'],got['git_blob_sha1'])==(size,blob),(name,got)
        records.append({'path':name,'source_url':BASE+name,**got})
        print('VERIFIED_ASSET',name,got['bytes'],got['sha256'],flush=True)
        emit(out/'evidence/acquisition_progress.json',{'files':records,'complete':False})
    emit(out/'evidence/acquisition.json',{'status':'VERIFIED_REAL_BYTES','commit':COMMIT,'files':records})
    return raw

def setup(raw,out):
    global np,pd,b2,model
    import numpy as np
    import pandas as pd
    import brian2 as b2
    versions={k:md.version(k) for k in EXPECTED}
    environment={'python':platform.python_version(),'platform':platform.platform(),'versions':versions,
    'expected':EXPECTED,'original_operating_system_reproduced':False,
    'github_run_id':os.getenv('GITHUB_RUN_ID'),'github_sha':os.getenv('GITHUB_SHA')}
    emit(out/'evidence/environment.json',environment)
    assert platform.python_version()=='3.10.11',environment
    assert versions==EXPECTED,environment
    spec=importlib.util.spec_from_file_location('unchanged_upstream_model',raw/'model.py')
    model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
    with (out/'requirements-executed.txt').open('w') as f:
        subprocess.run([sys.executable,'-m','pip','freeze'],stdout=f,check=True)
    b2.prefs.legacy.refractory_timing=False
    return environment

def audit(raw,out):
    comp=pd.read_csv(raw/list(ASSETS)[0],index_col=0);con=pd.read_parquet(raw/list(ASSETS)[1])
    ids=comp.index.to_numpy()
    assert len(ids)==127400 and np.issubdtype(ids.dtype,np.integer)
    assert len(np.unique(ids))==len(ids) and ids.min()>0
    for key in (PRE,POST,WEIGHT):assert key in con,key
    pre=con[PRE].to_numpy();post=con[POST].to_numpy();w=con[WEIGHT].to_numpy()
    assert np.issubdtype(pre.dtype,np.integer) and np.issubdtype(post.dtype,np.integer)
    assert pre.min()>=0 and post.min()>=0 and pre.max()<len(ids) and post.max()<len(ids)
    assert np.isfinite(w).all()
    keys=pre.astype(np.uint64)*len(ids)+post.astype(np.uint64)
    unique_pairs=len(np.unique(keys));del keys
    arrays={'root_ids':ids.astype('<i8'),'pre':pre.astype('<i8'),'post':post.astype('<i8'),'signed_units':w.astype('<f8')}
    digest=hashlib.sha256()
    for key,a in arrays.items():digest.update(key.encode());digest.update(a.tobytes())
    np.savez_compressed(out/'graph.npz',**arrays)
    digest2=hashlib.sha256()
    with np.load(out/'graph.npz',allow_pickle=False) as saved:
        for key,a in arrays.items():
            other=saved[key]
            assert np.array_equal(other.view(np.uint8),a.view(np.uint8)),key
            digest2.update(key.encode());digest2.update(other.tobytes())
    assert digest2.hexdigest()==digest.hexdigest()
    index={int(root):i for i,root in enumerate(ids)}
    targets=np.array([index[root] for root in SUGAR],dtype=np.int32);readout=index[MN9]
    notebook=(raw/'example.ipynb').read_text()
    assert all(str(root) in notebook for root in SUGAR+[MN9])
    columns={c:{'dtype':str(con[c].dtype),'nulls':int(con[c].isna().sum())} for c in con.columns}
    comp_columns={str(c):{'dtype':str(comp[c].dtype),'nulls':int(comp[c].isna().sum()),
        'value_counts':{str(k):int(v) for k,v in comp[c].value_counts(dropna=False).items()} if comp[c].nunique(dropna=False)<20 else None} for c in comp.columns}
    report={'status':'FULL_REAL_GRAPH_AUDITED','dataset':'FlyWire v630','nodes':len(ids),'edges':len(w),
        'source_columns':columns,'completeness_columns':comp_columns,
        'positive_edges':int((w>0).sum()),'negative_edges':int((w<0).sum()),'zero_edges':int((w==0).sum()),
        'self_edges':int((pre==post).sum()),'duplicate_pair_rows':len(w)-unique_pairs,
        'neurons_with_no_outgoing':len(ids)-len(np.unique(pre)),
        'neurons_with_no_incoming':len(ids)-len(np.unique(post)),
        'min_signed_weight':float(w.min()),'max_signed_weight':float(w.max()),
        'graph_sha256':digest.hexdigest(),'graph_roundtrip_all_arrays_bitwise_equal':True,
        'nodes_excluded':0,'edges_excluded':0,'row_order_preserved':True,
        'transmitter_identities_inferred_from_sign':False,
        'upstream_preprocessing_before_distributed_files_fully_reconstructed':False,
        'complete_transmitter_annotation_audited':False,
        'stimulus_ids':[str(i) for i in SUGAR],'stimulus_indices':targets.tolist(),
        'MN9_id':str(MN9),'MN9_index':readout}
    emit(out/'evidence/graph_audit.json',report);print('GRAPH_AUDIT',json.dumps(report),flush=True)
    pd.DataFrame({'neuron_index':np.arange(len(ids)),'flywire_id':ids}).to_csv(out/'neuron_index.csv',index=False)
    del comp,con,arrays;gc.collect()
    return ids,pre,post,w,targets,readout,report

def build(raw,backend,targets,condition,ids,pre,post,w):
    b2.start_scope();b2.prefs.codegen.target=backend;b2.defaultclock.dt=0.1*b2.ms
    params=dict(model.default_params);params['r_poi']=100*b2.Hz
    neu,syn,spikes=model.create_model(raw/list(ASSETS)[0],raw/list(ASSETS)[1],params)
    assert len(neu)==len(ids) and len(syn)==len(w)
    assert np.array_equal(np.asarray(syn.i),pre) and np.array_equal(np.asarray(syn.j),post)
    expected=w*params['w_syn']
    assert np.array_equal(np.asarray(syn.w),np.asarray(expected))
    extra=[]
    if condition in ('sugar','outgoing_zero'):extra,neu=model.poi(neu,list(map(int,targets)),[],params)
    if condition=='outgoing_zero':
        model.silence(list(map(int,targets)),syn);mask=np.isin(pre,targets)
        assert np.all(np.asarray(syn.w)[mask]==0)
        assert np.array_equal(np.asarray(syn.w)[~mask],np.asarray(expected)[~mask])
    return neu,syn,spikes,extra,params

def snapshot(neu,spikes):
    return {'ticks':np.rint(np.asarray(spikes.t/b2.ms)/0.1).astype(np.int64),
        'neurons':np.asarray(spikes.i).astype(np.int32),
        'v_mv':np.asarray(neu.v/b2.mV).copy(),'g_mv':np.asarray(neu.g/b2.mV).copy()}

def check_equal(a,b):
    errors={key:float(np.max(np.abs(a[key]-b[key]))) for key in ('v_mv','g_mv')}
    seq=bool(np.array_equal(a['ticks'],b['ticks']) and np.array_equal(a['neurons'],b['neurons']))
    return {'passed':seq and all(x<=1e-9 for x in errors.values()),'spike_sequence_equal':seq,
        'max_abs_error_mv':errors,'atol_mv':1e-9,'spikes_a':len(a['ticks']),'spikes_b':len(b['ticks'])}

def parity(raw,out,data,duration_ms):
    ids,pre,post,w,targets,readout,_=data
    steps=int(round(duration_ms/0.1));tape=np.random.default_rng(0).random((steps,len(targets)))<0.01
    ticks,sources=np.nonzero(tape);np.savez_compressed(out/'parity_input.npz',events=tape,targets=targets,dt_ms=0.1)
    reports=[]
    for condition in ('normal','outgoing_zero'):
        runs=[]
        for backend in ('numpy','cython'):
            start=time.perf_counter()
            neu,syn,spikes,_,params=build(raw,backend,targets,'no_input',ids,pre,post,w)
            neu.rfc[targets]=0*b2.ms
            if condition=='outgoing_zero':model.silence(list(map(int,targets)),syn)
            source=b2.SpikeGeneratorGroup(len(targets),sources,ticks*0.1*b2.ms,name='shared_stimulus')
            stim=b2.Synapses(source,neu,on_pre='v_post += jump',namespace={'jump':params['w_syn']*params['f_poi']},name='shared_voltage_input')
            stim.connect(i=np.arange(len(targets)),j=targets)
            trace=b2.StateMonitor(neu,['v','g'],record=[readout],when='end')
            net=b2.Network(neu,syn,spikes,source,stim,trace);net.run(duration_ms*b2.ms)
            snap=snapshot(neu,spikes)
            snap['MN9_v_mv']=np.asarray(trace.v/b2.mV).copy();snap['MN9_g_mv']=np.asarray(trace.g/b2.mV).copy()
            np.savez_compressed(out/f'parity_{condition}_{backend}.npz',**snap);runs.append(snap)
            print('PARITY_RUN',condition,backend,len(snap['ticks']),time.perf_counter()-start,flush=True)
            del net,neu,syn,spikes,source,stim,trace;gc.collect()
        report=check_equal(*runs)
        report.update(condition=condition,duration_ms=duration_ms,whole_graph=True,
            MN9_trace_error_mv=max(float(np.max(np.abs(runs[0][key]-runs[1][key]))) for key in ('MN9_v_mv','MN9_g_mv')))
        report['passed'] &= report['MN9_trace_error_mv']<=1e-9
        reports.append(report)
        emit(out/'evidence/backend_parity.json',{'scope':'Two actual Brian2 backends, same original factory and identical input events. Not an independent simulator.',
        'conditions':reports,'all_passed':all(r['passed'] for r in reports)})
        assert report['passed'],report
    return reports

def experiments(raw,out,data,ntrials,duration_ms):
    ids,pre,post,w,targets,readout,_=data;results=[];replay=None
    for condition in ('sugar','no_input','outgoing_zero'):
        neu,syn,spikes,extra,params=build(raw,'cython',targets,condition,ids,pre,post,w)
        net=b2.Network(neu,syn,spikes,*extra);net.store('initial')
        (out/'spikes'/condition).mkdir(parents=True,exist_ok=True)
        for seed in range(ntrials):
            start=time.perf_counter();net.restore('initial',restore_random_state=False);b2.seed(seed)
            net.run(duration_ms*b2.ms);snap=snapshot(neu,spikes)
            np.savez_compressed(out/'spikes'/condition/f'seed_{seed:02}.npz',ticks=snap['ticks'],neurons=snap['neurons'],
                flywire_ids=ids[snap['neurons']],dt_ms=0.1,duration_ms=duration_ms,seed=seed)
            counts=np.bincount(snap['neurons'],minlength=len(ids));rate=counts[readout]/(duration_ms/1000)
            outside=int(counts.sum()-counts[targets].sum())
            row={'condition':condition,'seed':seed,'duration_ms':duration_ms,'total_spikes':int(counts.sum()),
                'active_neurons':int((counts>0).sum()),'MN9_spikes':int(counts[readout]),'MN9_rate_hz':float(rate),
                'stimulus_population_spikes':int(counts[targets].sum()),'outside_stimulus_spikes':outside,
                'wall_seconds':time.perf_counter()-start}
            if condition=='no_input':assert row['total_spikes']==0,row
            if condition=='outgoing_zero':assert outside==0 and row['stimulus_population_spikes']>0,row
            results.append(row);print('REAL_TRIAL',json.dumps(row),flush=True);emit(out/'evidence/trials.json',results)
            if condition=='sugar' and seed==0:
                np.savez_compressed(out/'native_sugar_seed0_state.npz',**snap)
                net.restore('initial',restore_random_state=False);b2.seed(seed);net.run(duration_ms*b2.ms)
                replay=check_equal(snap,snapshot(neu,spikes));emit(out/'evidence/same_seed_replay.json',replay)
                assert replay['passed'],replay
        del net,neu,syn,spikes,extra;gc.collect()
    summaries={}
    for condition in ('sugar','no_input','outgoing_zero'):
        rows=[r for r in results if r['condition']==condition];rates=np.array([r['MN9_rate_hz'] for r in rows])
        summaries[condition]={'n_trials':len(rows),'MN9_rate_mean_hz':float(rates.mean()),
            'MN9_rate_sample_std_hz':float(rates.std(ddof=1)) if len(rows)>1 else None,
            'MN9_rate_min_hz':float(rates.min()),'MN9_rate_max_hz':float(rates.max()),
            'mean_active_neurons':float(np.mean([r['active_neurons'] for r in rows])),
            'total_spikes_all_trials':sum(r['total_spikes'] for r in rows)}
    archive=pd.read_parquet(raw/'results/example/sugarR_100Hz.parquet');trials=sorted(archive['trial'].unique())
    archived=archive.loc[archive['flywire_id']==MN9].groupby('trial').size().reindex(trials,fill_value=0).to_numpy()
    archive_report={'n_trials':len(trials),'assumed_trial_duration_ms':1000,'MN9_mean_hz':float(archived.mean()),
        'MN9_sample_std_hz':float(archived.std(ddof=1)),'MN9_per_trial_hz':archived.tolist(),
        'new_minus_archive_mean_hz':summaries['sugar']['MN9_rate_mean_hz']-float(archived.mean()),
        'interpretation':'Descriptive only: unknown historical random states; no equivalence test or fitting.'}
    emit(out/'evidence/experiment_summary.json',{'native_model':'unmodified model.py','native_stimulation':'original poi() PoissonInput',
        'duration_ms':duration_ms,'dt_ms':0.1,'summaries':summaries,'archive':archive_report,'same_seed_replay':replay})
    return summaries

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('digital-fly-output'))
    p.add_argument('--trials',type=int,default=30);p.add_argument('--duration-ms',type=float,default=1000)
    p.add_argument('--parity-ms',type=float,default=1000);p.add_argument('--acquire-only',action='store_true')
    args=p.parse_args();out=args.out;out.mkdir(parents=True,exist_ok=True)
    assert 1<=args.trials<=30 and 0<args.duration_ms<=1000 and 0<args.parity_ms<=1000
    stage='acquisition';start=time.perf_counter();emit(out/'evidence/status.json',{'status':'RUNNING','synthetic_substitution':False})
    try:
        raw=acquire(out)
        if args.acquire_only:return
        stage='environment';setup(raw,out)
        stage='audit';data=audit(raw,out)
        stage='actual_brian2_backend_parity';par=parity(raw,out,data,args.parity_ms)
        stage='actual_brian2_native_trials';summaries=experiments(raw,out,data,args.trials,args.duration_ms)
        final={'status':'COMPLETED_REAL_CONNECTOME_BRIAN2','actual_data_acquired':True,'actual_brian2_executed':True,
            'nodes':data[-1]['nodes'],'edges':data[-1]['edges'],'source_commit':COMMIT,'parity':par,'summaries':summaries,
            'synthetic_substitution':False,'all_biological_behaviors_reproduced':False,'full_cell_physiology_reproduced':False,
            'complete_transmitter_annotation_audited':False,'elapsed_seconds':time.perf_counter()-start}
        emit(out/'evidence/status.json',final);print('FINAL_EVIDENCE',json.dumps(final),flush=True)
    except Exception as e:
        emit(out/'evidence/status.json',{'status':'FAILED','stage':stage,'error_type':type(e).__name__,'error':str(e),
            'synthetic_substitution':False,'traceback':traceback.format_exc()});raise

if __name__=='__main__':main()
