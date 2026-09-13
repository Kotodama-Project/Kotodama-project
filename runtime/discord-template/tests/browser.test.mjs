import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {chromium} from 'playwright-core';
import {BrowserCli} from '../src/browser.mjs';
const executable=process.env.CHROME_BIN??(process.platform==='win32'?path.join(process.env.ProgramFiles??'', 'Google/Chrome/Application/chrome.exe'):'/usr/bin/chromium');
test('real browser refuses coordinate Token reset, login and secret-area capture',{skip:!existsSync(executable)},async t=>{
  const server=http.createServer((_req,res)=>res.end('<button id="token"><span>Reset Token</span></button><label id="safe">Message Content<input type="checkbox"></label>'));
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
  const browser=await chromium.launch({executablePath:executable,headless:true});t.after(async()=>{await browser.close();await new Promise(r=>server.close(r));});const page=await browser.newPage();const cli=new BrowserCli({allowedOrigins:[base]});cli.browser=browser;
  const url=base+'/developers/applications/100000000000000001/bot';await page.goto(url);const box=await page.locator('#token span').boundingBox();await assert.rejects(cli.click(0,{x:box.x+2,y:box.y+2,expectedUrl:url}),/HUMAN_CREDENTIAL_REQUIRED/);
  await assert.rejects(cli.screenshot(0,'unused.png'),/SAFE_CAPTURE_REGION_REQUIRED/);await assert.rejects(cli.screenshot(0,'unused.png','body'),/SENSITIVE_CAPTURE_REGION/);
  await cli.setChecked(0,{selector:'#safe',checked:true,expectedUrl:url});assert(await page.locator('#safe input').isChecked());await assert.rejects(cli.click(0,{selector:'#safe',expectedUrl:base}),/BROWSER_TARGET_CHANGED/);
  await page.goto(base+'/login');await assert.rejects(cli.click(0,{selector:'#token',expectedUrl:base+'/login'}),/HUMAN_LOGIN_REQUIRED/);await assert.rejects(cli.screenshot(0,'unused.png','#safe'),/HUMAN_SCREEN_CAPTURE_REFUSED/);
});
