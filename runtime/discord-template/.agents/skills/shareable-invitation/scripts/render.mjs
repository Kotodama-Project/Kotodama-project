import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
const [input,output]=process.argv.slice(2);
if(!input||!output)throw new Error('Usage: render.mjs input.md output.html');
const source=await readFile(input,'utf8');
const escape=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const blocks=source.trim().split(/\r?\n\s*\r?\n/).map(block=>{
  if(/^# /.test(block))return '<h1>'+escape(block.slice(2))+'</h1>';
  if(/^## /.test(block))return '<h2>'+escape(block.slice(3))+'</h2>';
  if(block.split(/\r?\n/).every(s=>s.startsWith('- ')))return '<ul>'+block.split(/\r?\n/).map(s=>'<li>'+escape(s.slice(2))+'</li>').join('')+'</ul>';
  return '<p>'+escape(block).replaceAll('\n','<br>')+'</p>';
}).join('\n');
const title=escape(source.split(/\r?\n/)[0].replace(/^# /,''));
await mkdir(path.dirname(output),{recursive:true});
await writeFile(output,`<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>${title}</title><style>body{margin:0;background:#f5f3ed;color:#222b32;font-family:system-ui,sans-serif;line-height:1.9}main{max-width:760px;margin:40px auto;padding:40px;background:white;border-top:8px solid #16786b;border-radius:12px}h1{font-size:clamp(26px,5vw,40px);line-height:1.4}h2{font-size:21px;margin-top:36px;color:#11665b}p,li{overflow-wrap:anywhere}li{margin:.6em 0}@media(max-width:600px){main{margin:14px;padding:22px}}@media print{body{background:white}main{margin:0;border:0}}</style><main>${blocks}</main></html>`, 'utf8');
console.log(JSON.stringify({output,bytes:Buffer.byteLength(blocks)}));
