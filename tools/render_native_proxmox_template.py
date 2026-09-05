"""Render a native Proxmox LXC template plan; no provider actions during rendering."""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path

CORE='c0b6f3e52ff0ab8d44d290647e256936e88e6b57'
NODE='24.19.0'
PNPM='11.17.0'
FIELDS={'template_vmid','smoke_vmid','storage','clone_storage','bridge','hostname','base_image','base_sha256','rootfs_gib','memory_mib','cores'}
def render(config:dict,assets:Path):
    if not isinstance(config,dict) or set(config)!=FIELDS:raise ValueError('template profile fields mismatch')
    for key,lo,hi in [('template_vmid',100,999999999),('smoke_vmid',100,999999999),('rootfs_gib',16,128),('memory_mib',4096,16384),('cores',2,8)]:
        value=config[key]
        if isinstance(value,bool) or not isinstance(value,int) or not lo<=value<=hi:raise ValueError('invalid numeric profile value')
    if config['template_vmid']==config['smoke_vmid']:raise ValueError('template and clone must differ')
    for key in ['storage','clone_storage','bridge','hostname']:
        if not isinstance(config[key],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}',config[key]):raise ValueError('unsafe profile identifier')
    if not re.fullmatch(r'[A-Za-z0-9_-]+:vztmpl/ubuntu-24\.04-standard_[A-Za-z0-9._-]+_amd64\.tar\.zst',str(config['base_image'])):raise ValueError('official Ubuntu 24.04 template required')
    if not re.fullmatch(r'[a-f0-9]{64}',str(config['base_sha256'])):raise ValueError('base image hash required')
    create=['pct','create',str(config['template_vmid']),config['base_image'],'--hostname',config['hostname'],'--cores',str(config['cores']),'--memory',str(config['memory_mib']),'--swap','1024','--rootfs',f"{config['storage']}:{config['rootfs_gib']}",'--unprivileged','1','--features','nesting=1','--onboot','0','--nameserver','1.1.1.1','--net0',f"name=eth0,bridge={config['bridge']},ip=dhcp,firewall=1"]
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,54}[a-z0-9]',config['hostname']):raise ValueError('hostname must leave room for clone suffix')
    clone=['pct','clone',str(config['template_vmid']),str(config['smoke_vmid']),'--full','1','--storage',config['clone_storage'],'--hostname',config['hostname']+'-smoke']
    files={name:(assets/name).read_bytes() for name in ['install.sh','activate-instance.py','seal-check.py','kotodama-cloudflare-os.service']}
    plan={'schemaVersion':'kotodama.native-proxmox-template/v1','mode':'OFFICIAL_SOURCE_EVALUATION','coreRevision':CORE,'nodeVersion':NODE,'pnpmVersion':PNPM,'sourceRepository':'https://github.com/cloudflare/cloudflare-os','baseImageSha256':config['base_sha256'],'create':create,'seal':['pct','template',str(config['template_vmid'])],'clone':clone,'profile':config,'templateHasAccounts':False,'templateHasConversationData':False,'templateHasCredentials':False,'initialAgent':'unconfigured','productionSupport':'upstream-self-host-tooling-pending','assetHashes':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()}}
    files['plan.json']=(json.dumps(plan,indent=2)+'\n').encode('utf-8')
    return files
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('profile',type=Path);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    assets=Path(__file__).resolve().parents[1]/'templates/native-proxmox/cloudflare-os'
    files=render(json.loads(args.profile.read_text(encoding='utf-8')),assets)
    args.output.mkdir(parents=True,exist_ok=False)
    for name,data in files.items():(args.output/name).write_bytes(data)
    print(json.dumps({'status':'RENDERED_ONLY','files':len(files),'providerActions':0}))
if __name__=='__main__':main()
