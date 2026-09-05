import importlib.util,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_template',ROOT/'tools/render_native_proxmox_template.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class NativeTemplate(unittest.TestCase):
 def config(self):return {'template_vmid':90001,'smoke_vmid':90002,'storage':'example-zfs','clone_storage':'example-lvm','bridge':'vmbr0','hostname':'example-os-template','base_image':'local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst','base_sha256':'a'*64,'rootfs_gib':24,'memory_mib':8192,'cores':4}
 def test_native_plan_has_separate_template_and_clone_and_no_credential_input(self):
  files=m.render(self.config(),ROOT/'templates/native-proxmox/cloudflare-os');import json;p=json.loads(files['plan.json']);self.assertEqual(p['create'][:3],['pct','create','90001']);self.assertEqual(p['seal'],['pct','template','90001']);self.assertIn('--full',p['clone']);self.assertFalse(p['templateHasCredentials']);self.assertEqual(p['initialAgent'],'unconfigured');self.assertIn(b'ConditionPathExists',files['kotodama-cloudflare-os.service'])
 def test_wrong_scope_and_injection_are_refused_before_output(self):
  for key,value in [('template_vmid',90002),('bridge','vmbr0\nExecStart=bad'),('base_image','local:vztmpl/../../private'),('base_sha256',''),('memory_mib',True)]:
   c=self.config();c[key]=value
   with self.assertRaises(ValueError):m.render(c,ROOT/'templates/native-proxmox/cloudflare-os')
  c=self.config();c['token']='must-not-be-accepted'
  with self.assertRaises(ValueError):m.render(c,ROOT/'templates/native-proxmox/cloudflare-os')
if __name__=='__main__':unittest.main()
