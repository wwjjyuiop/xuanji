#!/usr/bin/env node
/** 取证：standup(1.4s) 播起来后，每 0.5s 采样 mixer 时间与 action 的 time/enabled/paused/loopCount，看时间是否推进、何时该 finished。 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.pmx': 'application/octet-stream', '.vmd': 'application/octet-stream', '.wasm': 'application/wasm' };
const log = (...a) => console.log('[fin]', ...a);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function startServer() { return new Promise((resolve) => { const srv = http.createServer((req, res) => { const url = new URL(req.url, 'http://x'); let fp = path.join(ROOT, decodeURIComponent(url.pathname)); if (fp.endsWith('/') || url.pathname === '/') fp = path.join(ROOT, 'index.html'); fs.readFile(fp, (err, buf) => { if (err) { res.writeHead(404); res.end('404'); return; } res.writeHead(200, { 'Content-Type': MIME[path.extname(fp).toLowerCase()] || 'application/octet-stream' }); res.end(buf); }); }); srv.listen(0, '127.0.0.1', () => resolve(srv.address().port)); }); }
function connectCDP(wsUrl) { return new Promise((resolve, reject) => { const ws = new WebSocket(wsUrl); const pending = new Map(); const handlers = new Map(); let id = 0; ws.onopen = () => resolve({ send(method, params = {}) { return new Promise((res, rej) => { const mid = ++id; const t = setTimeout(() => { if (pending.has(mid)) { pending.delete(mid); rej(new Error('TIMEOUT ' + method)); } }, 12000); pending.set(mid, { res: (v) => { clearTimeout(t); res(v); }, rej: (e) => { clearTimeout(t); rej(e); } }); ws.send(JSON.stringify({ id: mid, method, params })); }); }, on(method, h) { (handlers.get(method) || handlers.set(method, []).get(method)).push(h); }, close() { ws.close(); } }); ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); } else if (m.method && handlers.has(m.method)) for (const h of handlers.get(m.method)) h(m.params); }; ws.onerror = () => reject(new Error('ws')); }); }
async function getTarget(port) { for (let i = 0; i < 50; i++) { try { const l = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); const p = l.find(t => t.type === 'page'); if (p) return p; } catch {} await sleep(100); } throw new Error('no target'); }

(async () => {
  const srvPort = await startServer();
  const cdpPort = 19000 + Math.floor(Math.random() * 500);
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-pf-'));
  const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox', '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--disable-frame-rate-limit', '--run-all-compositor-stages-before-draw', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${udd}`, '--window-size=300,300', '--force-device-scale-factor=0.5', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  try {
    const page = await getTarget(cdpPort);
    const cdp = await connectCDP(page.webSocketDebuggerUrl);
    const consoleLines = [];
    cdp.on('Runtime.consoleAPICalled', (p) => consoleLines.push((p.args || []).map(a => a.value ?? a.description ?? '').join(' ')));
    await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${srvPort}/index.html` });
    const ev = async (e) => { const r = await cdp.send('Runtime.evaluate', { expression: e, returnByValue: true }); return r.exceptionDetails ? 'EXC:' + r.exceptionDetails.text : r.result.value; };
    for (let i = 0; i < 120; i++) { const b = await ev('window.__xuanji3d&&window.__xuanji3d.getBones?window.__xuanji3d.getBones():null'); if (typeof b === 'string' && b.includes('"total"')) break; await sleep(500); }
    log('模型就绪');
    log('playAction(standup)=' + await ev("window.__xuanji3d.playAction('standup')"));
    for (let t = 0; t <= 4000; t += 500) {
      const st = await ev('window.__xuanji3d.getState()');
      let o = null; try { o = JSON.parse(st); } catch {}
      const md = (o && o.mixerDiag) || {};
      log(`t=${(t/1000).toFixed(1)}s  playingVmd=${o && o.playingVmd}  mixerTime=${md.helperMixerTime}  acts=${JSON.stringify(md.helperActions)}`);
      await sleep(500);
    }
    console.log('\n──── console 链路 ────');
    for (const l of consoleLines) if (/\[MMD\]|\[ACT\]|EXCEPTION/.test(l)) console.log('  ' + l);
    process.exit(0);
  } catch (e) { log('异常: ' + e.message); process.exit(5); }
  finally { try { chrome.kill(); } catch {} try { fs.rmSync(udd, { recursive: true, force: true }); } catch {} }
})();
