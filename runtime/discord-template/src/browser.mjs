import {chromium} from 'playwright-core';
import {check,Refused} from './common.mjs';
import {humanBoundary} from './onboarding.mjs';

export class BrowserCli {
  constructor(config){this.config=config;this.browser=null;}
  async connect(){check(this.config.cdpUrl,'CDP_NOT_CONFIGURED');const u=new URL(this.config.cdpUrl);check(['localhost','127.0.0.1','[::1]'].includes(u.hostname),'CDP_MUST_BE_LOOPBACK');this.browser=await chromium.connectOverCDP(this.config.cdpUrl);return this;}
  allow(url){const u=new URL(url);check(['https:','http:'].includes(u.protocol)&&this.config.allowedOrigins.includes(u.origin),'BROWSER_ORIGIN_NOT_ALLOWED');return u;}
  pages(){check(this.browser,'BROWSER_NOT_CONNECTED');return this.browser.contexts().flatMap(c=>c.pages());}
  page(index){const page=this.pages()[index];check(page,'BROWSER_TAB_NOT_FOUND');this.allow(page.url());return page;}
  humanBoundary(page){return humanBoundary(page.url()).code;}
  async open(url){this.allow(url);const context=this.browser.contexts()[0];check(context,'BROWSER_CONTEXT_NOT_FOUND');const page=await context.newPage();await page.goto(url,{waitUntil:'domcontentloaded'});this.allow(page.url());return this.pages().indexOf(page);}
  list(){return this.pages().map((p,index)=>({index,url:p.url()})).filter(p=>{try{this.allow(p.url);return true;}catch{return false;}});}
  async read(index){const p=this.page(index);const tokenPage=/\/developers\/applications\/\d+\/bot\/?$/.test(new URL(p.url()).pathname);return {url:p.url(),title:await p.title(),text:tokenPage?'Token画面の本文は出力しません。安全な操作ラベルだけを確認します。':await p.locator('body').innerText(),links:await p.locator('a[href]').evaluateAll(nodes=>nodes.map(a=>({text:a.innerText,href:a.href}))),regions:await p.locator('[role="dialog"],form').evaluateAll(nodes=>nodes.map(e=>({tag:e.tagName,role:e.getAttribute('role'),id:e.id,className:e.className}))),controls:await p.locator('button,input,select,[role="button"]').evaluateAll(nodes=>nodes.map(e=>({tag:e.tagName,role:e.getAttribute('role'),id:e.id,type:e.getAttribute('type'),name:e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||'',hasValue:Boolean('value' in e&&e.value),checked:typeof e.checked==='boolean'?e.checked:null,box:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}})))};}
  async click(index,{role,name,selector,x,y,expectedUrl}){const p=this.page(index);check(expectedUrl&&p.url()===expectedUrl,'BROWSER_TARGET_CHANGED');const human=this.humanBoundary(p);check(!human,human);const locator=role&&name?p.getByRole(role,{name,exact:true}):selector?p.locator(selector):null;
    const describe=e=>{const target=e?.closest('button,a,input,[role="button"],[role="checkbox"]')??e;return {text:target?.innerText??'',type:target?.getAttribute('type'),role:target?.getAttribute('role')};};
    if(!locator)check(Number.isFinite(x)&&Number.isFinite(y),'CLICK_TARGET_REQUIRED');
    const target=locator?await locator.evaluate(describe):await p.evaluate(({x,y})=>{const e=document.elementFromPoint(x,y);const target=e?.closest('button,a,input,[role="button"],[role="checkbox"]')??e;return {text:target?.innerText??'',type:target?.getAttribute('type'),role:target?.getAttribute('role')};},{x,y});
    const dialogs=await p.getByRole('dialog').allTextContents();const boundary=humanBoundary(p.url(),{...target,dialogText:dialogs.join('\n'),coordinate:!locator});check(!boundary.required,boundary.code);
    if(locator)await locator.click({timeout:10000});else{check(Number.isFinite(x)&&Number.isFinite(y),'CLICK_TARGET_REQUIRED');await p.mouse.click(x,y);}return {url:p.url()};}
  async fill(index,{label,selector,text,expectedUrl}){check((typeof label==='string'||typeof selector==='string')&&typeof text==='string','FILL_ARGUMENTS_REQUIRED');const p=this.page(index);check(expectedUrl&&p.url()===expectedUrl,'BROWSER_TARGET_CHANGED');const human=this.humanBoundary(p);check(!human,human);const locator=selector?p.locator(selector):p.getByLabel(label,{exact:true});const boundary=humanBoundary(p.url(),{dialogText:(await p.getByRole('dialog').allTextContents()).join('\n')});check(!boundary.required,boundary.code);check(await locator.getAttribute('type')!=='password','HUMAN_LOGIN_REQUIRED');await locator.fill(text,{timeout:10000});return {filled:true};}
  async setChecked(index,{selector,checked,expectedUrl}){const p=this.page(index);check(expectedUrl&&p.url()===expectedUrl,'BROWSER_TARGET_CHANGED');const human=this.humanBoundary(p);check(!human,human);const label=p.locator(selector);const input=label.locator('input[type="checkbox"]');check(await input.count()===1,'CHECKBOX_LABEL_REQUIRED');const dialogs=await p.getByRole('dialog').allTextContents();const boundary=humanBoundary(p.url(),{type:'checkbox',dialogText:dialogs.join('\n')});check(!boundary.required,boundary.code);if(await input.isChecked()!==checked)await label.click({timeout:10000});check(await input.isChecked()===checked,'CHECKBOX_STATE_NOT_CHANGED');return {checked};}
  async screenshot(index,filename,selector=null){const p=this.page(index);const url=new URL(p.url());
    check(!humanBoundary(p.url()).required,'HUMAN_SCREEN_CAPTURE_REFUSED');
    const tokenPage=/\/developers\/applications\/\d+\/bot\/?$/.test(url.pathname);
    check(!tokenPage||selector,'SAFE_CAPTURE_REGION_REQUIRED');
    const region=selector?p.locator(selector):p.locator('body');
    const sensitive=await region.evaluate(e=>{const nodes=[e,...e.querySelectorAll('input,textarea,canvas,img')];return nodes.some(n=>n.matches('input[type="password"],canvas')||(/token|secret|password|qr.?code|トークン|パスワード/i.test([n.getAttribute('name'),n.getAttribute('id'),n.getAttribute('aria-label'),n.getAttribute('alt')].join(' '))))||/Reset Token|Copy Token|トークンを(?:リセット|コピー)/i.test(e.innerText??'');});
    check(!sensitive,'SENSITIVE_CAPTURE_REGION');
    if(selector)await region.screenshot({path:filename,timeout:5000});else await p.screenshot({path:filename,fullPage:false,timeout:5000});return {path:filename};}
  async scroll(index,{selector,deltaY}){check(typeof selector==='string'&&Number.isFinite(deltaY),'SCROLL_ARGUMENTS_REQUIRED');await this.page(index).locator(selector).evaluate((e,delta)=>{e.scrollTop+=delta;},deltaY);return this.read(index);}
  async disconnect(){if(this.browser)await this.browser.close();}
}
