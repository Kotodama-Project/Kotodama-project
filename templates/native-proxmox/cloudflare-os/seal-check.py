#!/usr/bin/python3
"""Verify a clean official-source image before Proxmox template conversion."""
import hashlib,json,subprocess
from pathlib import Path
root=Path('/opt/kotodama-os/core')
for p in [root/'.wrangler/state',root/'.dev.vars',root/'.env',Path('/etc/kotodama/os-instance.json'),Path('/home/os-runtime/.config/.wrangler/config/default.toml')]:
 if p.exists():raise SystemExit('TEMPLATE_CONTAINS_INSTANCE_STATE')
for name in ['.dev.vars','.env']:
 if any(p.is_file() for p in (root/'packages').rglob(name)):raise SystemExit('TEMPLATE_CONTAINS_PROVIDER_CONFIG')
head=subprocess.check_output(['runuser','-u','os-runtime','--','git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
if head!='c0b6f3e52ff0ab8d44d290647e256936e88e6b57':raise SystemExit('SOURCE_REVISION_MISMATCH')
state=subprocess.run(['systemctl','is-active','kotodama-cloudflare-os.service'],capture_output=True,text=True).stdout.strip()
if state=='active':raise SystemExit('TEMPLATE_RUNTIME_ACTIVE')
print(json.dumps({'templateSourceClean':True,'coreRevision':head,'lockSha256':hashlib.sha256((root/'pnpm-lock.yaml').read_bytes()).hexdigest(),'runtimeActive':False,'accountsBaked':False,'conversationDataBaked':False,'providerConfigurationBaked':False}))
