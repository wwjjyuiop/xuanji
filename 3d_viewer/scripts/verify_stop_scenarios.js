#!/usr/bin/env node
/** 两场“喊停”实测：a) 长动作(wave 93.6s)正在播时喊停；b) 动作还在加载中喊停(_actionEpoch 作废在途回调)。 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.pmx': 'application/octet-stream', '.vmd': 'application/octet-stream', '.wasm': 'application/wasm' };
const log = (...a) => console.log('[stop]', ...a);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function startServer() { return new Promise((resolve) => { const srv = http.createServer((req, res) => { const url = new URL(req.url, 'http://x'); let fp = path.join(ROOT, decodeURIComponent(url.pathname)); if (fp.endsWith('/') || url.pathname === '/') fp = path.join(ROOT, 'index.html'); fs.readFile(fp, (err, buf) => { if (err) { res.writeHead(404); res.end('404'); return; } res.writeHead(200, { 'Content-Type': MIME[path.extname(fp).toLowerCase()] || 'application/octet-stream' }); res.end(buf); }); }); srv.listen(0, '127.0.0.1', () => resolve(srv.address().port)); }); }
function connectCDP(wsUrl) { return new Promise((resolve, reject) => { const ws = new WebSocket(wsUrl); const pending = new Map(); const handlers = new Map(); let id = 0; ws.onopen = () => resolve({ send(method, params = {}) { return new Promise((res, rej) => { const mid = ++id; const t = setTimeout(() => { if (pending.has(mid)) { pending.delete(mid); rej(new Error('CDP timeout ' + method)); } }, 12000); pending.set(mid, { res: (v) => { clearTimeout(t); res(v); }, rej: (e) => { clearTimeout(t); rej(e); } }); ws.send(JSON.stringify({ id: mid, method, params })); }); }, on(method, h) { (handlers.get(method) || handlers.set(method, []).get(method)).push(h); }, close() { ws.close(); } }); ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); } else if (m.method && handlers.has(m.method)) for (const h of handlers.get(m.method)) h(m.params); }; ws.onerror = () => reject(new Error('ws')); }); }
async function getTarget(port) { for (let i = 0; i < 50; i++) { try { const l = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); const p = l.find(t => t.type === 'page'); if (p) return p; } catch {} await sleep(100); } throw new Error('no target'); }

(async () => {
  const srvPort = await startServer();
  const cdpPort = 19000 + Math.floor(Math.random() * 500);
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-vs-'));
  const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox', '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--disable-frame-rate-limit', '--run-all-compositor-stages-before-draw', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${udd}`, '--window-size=300,300', '--force-device-scale-factor=0.5', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  const wd = setTimeout(() => { log('!! watchdog 90s'); process.exit(9); }, 90000);
  try {
    const page = await getTarget(cdpPort);
    const cdp = await connectCDP(page.webSocketDebuggerUrl);
    const consoleLines = [];
    cdp.on('Runtime.consoleAPICalled', (p) => consoleLines.push((p.args || []).map(a => a.value ?? a.description ?? '').join(' ')));
    cdp.on('Runtime.exceptionThrown', (p) => consoleLines.push('EXCEPTION ' + (p.exceptionDetails && p.exceptionDetails.text)));
    await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${srvPort}/index.html` });
    const ev = async (e) => { const r = await cdp.send('Runtime.evaluate', { expression: e, returnByValue: true }); if (r.exceptionDetails) return { __err: r.exceptionDetails.text }; return r.result.value; };
    const rot = async () => { try { return JSON.parse(await ev('window.__xuanji3d.getArmState()')); } catch { return null; } };
    const zArm = (s) => s && s.lUpper ? s.lUpper.z : null;

    for (let i = 0; i < 120; i++) { const b = await ev('window.__xuanji3d&&window.__xuanji3d.getBones?window.__xuanji3d.getBones():null'); if (typeof b === 'string' && b.includes('"total"')) break; await sleep(500); }
    log('模型就绪');
    await ev('window.__xuanji3d.stopAction()'); await sleep(400);
    const base = await rot();
    log(`待机基线 lUpper.z=${zArm(base)}`);

    // ── a) 长动作 wave(93.6s) 正在播时喊停 ──
    log('\n==== 场景a：长动作(wave)正在播时喊停 ====');
    const pa = await ev("window.__xuanji3d.playAction('wave')");
    await sleep(2000);
    const stA1 = await ev('window.__xuanji3d.getState()');
    const armA1 = await rot();
    log(`播2s后(未停) getState=${stA1}  lUpper.z=${zArm(armA1)}`);
    const sa = await ev('window.__xuanji3d.stopAction()');
    await sleep(600);
    const stA2 = await ev('window.__xuanji3d.getState()');
    const armA2 = await rot();
    log(`喊停后 getState=${stA2}  lUpper.z=${zArm(armA2)}  stopAction返回=${JSON.stringify(sa)}`);
    let aObj = null; try { aObj = JSON.parse(stA2); } catch {}
    const aOK = !!(aObj && aObj.playingVmd === false && aObj.curVmdAction === null && aObj.activeBoneAction === 'idle');
    console.log('  场景a 判定: ' + (aOK ? 'PASS（停住了）' : 'FAIL（没停住）'));

    // ── b) 动作还在加载中喊停（playAction 与 stopAction 同回合，epoch 作废在途回调）──
    log('\n==== 场景b：动作加载中喊停(_actionEpoch) ====');
    const pb = await ev("window.__xuanji3d.playAction('nature'); window.__xuanji3d.stopAction();");
    await sleep(3000);   // 等本地 VMD 加载完成（若没作废，这里会“舞又起”）
    const stB = await ev('window.__xuanji3d.getState()');
    const armB = await rot();
    log(`加载中喊停、等3s后 getState=${stB}  lUpper.z=${zArm(armB)}`);
    let bObj = null; try { bObj = JSON.parse(stB); } catch {}
    const bOK = !!(bObj && bObj.playingVmd === false && bObj.curVmdAction === null);
    console.log('  场景b 判定: ' + (bOK ? 'PASS（在途回调已作废）' : 'FAIL（舞又起）'));

    console.log('\n──── console 链路 ────');
    for (const l of consoleLines) if (/\[MMD\]|\[ACT\]|EXCEPTION/.test(l)) console.log('  ' + l);
    process.exit(aOK && bOK ? 0 : 1);
  } catch (e) { log('异常: ' + e.message); process.exit(5); }
  finally { clearTimeout(wd); try { chrome.kill(); } catch {} try { fs.rmSync(udd, { recursive: true, force: true }); } catch {} }
})();
