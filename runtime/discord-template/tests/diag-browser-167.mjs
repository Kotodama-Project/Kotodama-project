// TEMPORARY diagnostic for #167. Not a test; removed before merge.
// Repeats the steps of tests/browser.test.mjs with per-step timings to find
// where the real-browser test spends its time on CI runners.
import {existsSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {chromium} from 'playwright-core';
import {BrowserCli} from '../src/browser.mjs';

const executable=process.env.CHROME_BIN??(process.platform==='win32'?path.join(process.env.ProgramFiles??'','Google/Chrome/Application/chrome.exe'):'/usr/bin/chromium');
const iterations=Number(process.env.DIAG_ITERATIONS??10);
const variants=(process.env.DIAG_VARIANTS??'default,disable-gpu').split(',');
const argsFor={
  'default':[],
  'disable-gpu':['--disable-gpu'],
  'swiftshader':['--use-angle=swiftshader','--enable-unsafe-swiftshader'],
};
if(!existsSync(executable)){console.log(JSON.stringify({skip:'no browser',executable}));process.exit(0);}
const server=http.createServer((_req,res)=>res.end('<button id="token"><span>Reset Token</span></button><label id="safe">Message Content<input type="checkbox"></label>'));
await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
const now=()=>Number(process.hrtime.bigint()/1000000n);
const withTimeout=(p,ms)=>Promise.race([p.then(v=>({ok:true,v}),e=>({ok:false,e:String(e?.message??e).split('\n')[0]})),new Promise(r=>setTimeout(()=>r({ok:false,e:'DIAG_TIMEOUT'}),ms))]);
console.log(JSON.stringify({meta:{platform:process.platform,cpus:os.cpus().length,cpuModel:os.cpus()[0]?.model,load:os.loadavg(),mem:Math.round(os.totalmem()/2**30),node:process.version,executable}}));
for(const variant of variants){
  for(let i=0;i<iterations;i++){
    const t={variant,i};let mark=now();const lap=k=>{const n=now();t[k]=n-mark;mark=n;};
    const browser=await chromium.launch({executablePath:executable,headless:true,args:argsFor[variant]??[]});lap('launch');
    try{
      if(i===0){const s=await browser.newBrowserCDPSession();const info=await withTimeout(s.send('SystemInfo.getInfo'),20000);
        const g=info.ok?info.v.gpu:null;const aux=g?.auxAttributes??{};
        console.log(JSON.stringify({gpu:{variant,version:browser.version(),error:info.ok?undefined:info.e,devices:g?.devices?.map(d=>`${d.vendorString}|${d.deviceString}|${d.driverVersion}`),featureStatus:g?.featureStatus,glRenderer:aux.glRenderer,glImplementationParts:aux.glImplementationParts,displayType:aux.displayType,softwareRendering:aux.softwareRendering}}));await s.detach();mark=now();}
      const page=await browser.newPage();lap('newPage');const cli=new BrowserCli({allowedOrigins:[base]});cli.browser=browser;
      const url=base+'/developers/applications/100000000000000001/bot';await page.goto(url);lap('goto');
      t.visibility=await page.evaluate(()=>document.visibilityState);t.focus=await page.evaluate(()=>document.hasFocus());lap('state');
      const raf=await withTimeout(page.evaluate(()=>new Promise(r=>{const s=performance.now();requestAnimationFrame(()=>requestAnimationFrame(()=>r(performance.now()-s)));})),30000);lap('firstFrames');t.rafInPage=raf.ok?Math.round(raf.v):raf.e;
      const box=await page.locator('#token span').boundingBox();lap('boundingBox');
      const r1=await withTimeout(cli.click(0,{x:box.x+2,y:box.y+2,expectedUrl:url}),30000);lap('coordinateRefusal');t.r1=r1.ok?'NOT_REFUSED':r1.e.slice(0,40);
      const r2=await withTimeout(cli.screenshot(0,'unused.png'),30000);const r3=await withTimeout(cli.screenshot(0,'unused.png','body'),30000);lap('captureRefusals');
      const raf2=await withTimeout(page.evaluate(()=>new Promise(r=>{const s=performance.now();requestAnimationFrame(()=>requestAnimationFrame(()=>r(performance.now()-s)));})),30000);lap('framesBeforeClick');t.raf2=raf2.ok?Math.round(raf2.v):raf2.e;
      const moves=await withTimeout(page.evaluate(()=>new Promise(r=>{const e=document.querySelector('#safe');const boxes=[];const step=()=>{const b=e.getBoundingClientRect();boxes.push([b.x,b.y,b.width,b.height].join(','));if(boxes.length<6)requestAnimationFrame(step);else r(new Set(boxes).size);};requestAnimationFrame(step);})),30000);lap('labelBoxes');t.distinctBoxes=moves.ok?moves.v:moves.e;
      const c=await withTimeout(page.locator('#safe').click({timeout:30000}),35000);lap('labelClick');t.click=c.ok?'ok':c.e.slice(0,60);
      await page.goto(base+'/login');lap('gotoLogin');
      const r4=await withTimeout(cli.click(0,{selector:'#token',expectedUrl:base+'/login'}),30000);lap('loginRefusal');
    }catch(e){t.error=String(e?.message??e).split('\n')[0];}
    const cl=await withTimeout(browser.close(),30000);lap('close');if(!cl.ok)t.closeError=cl.e;
    console.log(JSON.stringify({row:t}));
  }
}
server.close();
