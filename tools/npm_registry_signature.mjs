/** Narrow ECDSA verifier; the Python caller binds package, key and artifact. */
import {createPublicKey, verify} from 'node:crypto';

try {
  let raw='';
  for await (const part of process.stdin) {
    raw+=part;
    if(Buffer.byteLength(raw)>16384) throw new Error('input_bound');
  }
  const value=JSON.parse(raw);
  if(Object.keys(value).sort().join(',')!=='key,message,signature') throw new Error('shape');
  for(const name of ['key','message','signature']) {
    if(typeof value[name]!=='string'||value[name].length>4096) throw new Error('shape');
  }
  const decode=text=>{
    const bytes=Buffer.from(text,'base64');
    if(bytes.toString('base64')!==text) throw new Error('base64');
    return bytes;
  };
  const key=createPublicKey({key:decode(value.key),format:'der',type:'spki'});
  if(key.asymmetricKeyType!=='ec'||key.asymmetricKeyDetails?.namedCurve!=='prime256v1') throw new Error('curve');
  const verified=verify('sha256',Buffer.from(value.message,'utf8'),key,decode(value.signature));
  process.stdout.write(JSON.stringify({verified,algorithm:'ecdsa-p256-sha256'})+'\n');
  process.exitCode=verified?0:1;
} catch {
  process.stdout.write(JSON.stringify({verified:false,reason:'REGISTRY_SIGNATURE_REFUSED'})+'\n');
  process.exitCode=1;
}
