#!/usr/bin/python3
"""Activate a fresh clone; instance identity is never baked into the template."""
import argparse,json,os,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--instance-id',required=True);args=p.parse_args()
if not re.fullmatch(r'[a-z][a-z0-9-]{2,62}',args.instance_id):raise SystemExit('INVALID_INSTANCE_ID')
root=Path('/opt/kotodama-os/core');marker=Path('/etc/kotodama/os-instance.json')
if marker.exists() or (root/'.wrangler/state').exists():raise SystemExit('INSTANCE_ALREADY_INITIALIZED')
head=subprocess.check_output(['runuser','-u','os-runtime','--','git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
if head!='c0b6f3e52ff0ab8d44d290647e256936e88e6b57':raise SystemExit('SOURCE_REVISION_MISMATCH')
with marker.open('x',encoding='utf-8') as f:os.chmod(marker,0o600);json.dump({'instanceId':args.instance_id,'coreRevision':head,'mode':'evaluation'},f)
subprocess.run(['systemctl','start','kotodama-cloudflare-os.service'],check=True)
print(json.dumps({'instanceActivated':True,'mode':'evaluation','agentConfigured':False}))
