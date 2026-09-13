#!/usr/bin/env node
import {chromium} from 'playwright-core';
import {parseArgs} from 'node:util';
import {mkdir,readFile} from 'node:fs/promises';
import path from 'node:path';
import {check,digest,atomicJson} from '../src/common.mjs';
const {values:o}=parseArgs({options:{browser:{type:'string'},output:{type:'string',default:'docs/images/discord-01-login.png'}}});check(o.browser,'BROWSER_EXECUTABLE_REQUIRED');
const browser=await chromium.launch({executablePath:o.browser,headless:true,chromiumSandbox:true});
try{
  const context=await browser.newContext({viewport:{width:1280,height:900},locale:'ja-JP'});const page=await context.newPage();await page.goto('https://discord.com/login',{waitUntil:'domcontentloaded'});
  const email=page.locator('input[type="text"]').first(),password=page.locator('input[type="password"]');await email.waitFor({state:'visible',timeout:15000});await password.waitFor({state:'visible',timeout:15000});
  check(await email.inputValue()===''&&await password.inputValue()==='','LOGIN_FIELDS_NOT_EMPTY');const e=await email.boundingBox(),p=await password.boundingBox();check(e&&p,'LOGIN_FIELDS_NOT_VISIBLE');
  const clip={x:Math.max(0,Math.floor(e.x-18)),y:Math.max(0,Math.floor(e.y-130)),width:Math.ceil(e.width+36),height:Math.ceil(p.y+p.height+170-Math.max(0,Math.floor(e.y-130)))};
  await mkdir(path.dirname(path.resolve(o.output)),{recursive:true});await page.screenshot({path:o.output,clip});const sha256=digest(await readFile(o.output));await atomicJson(o.output+'.json',{source:'https://discord.com/login',capturedAt:new Date().toISOString(),scope:'empty login fields and explanatory labels only',excluded:['QR authentication panel','existing account information'],fieldValuesEmpty:true,sha256});console.log(JSON.stringify({captured:true,path:o.output,sha256}));
}finally{await browser.close();}
