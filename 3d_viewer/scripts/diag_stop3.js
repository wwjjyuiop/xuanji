#!/usr/bin/env node
/** 最小取证：只用 getArmState()（局部 rotation，轻量），确认「跳舞中→喊停」后骨骼是否真停并回待机。 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.pmx': 'application/octet-stream', '.vmd': 'application/octet-stream', '.wasm': 'application/wasm' };
const log = (...a) => console.log('[diag3]', ...a);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function startServer() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://x');
      let fp = path.join(ROOT, decodeURIComponent(url.pathname));
      if (fp.endsWith('/') || url.pathname === '/') fp = path.join(ROOT, 'index.html');
      fs.readFile(fp, (err, buf) => { if (err) { res.writeHead(404); res.end('404'); return; } res.writeHead(200, { 'Content-Type': MIME[path.extname(fp).toLowerCase()] || 'application/octet-stream' }); res.end(buf); });
    });
    srv.listen(0, '127.0.0.1', () => resolve(srv.address().port));
  });
}
function connectCDP(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const pending = new Map(); const handlers = new Map(); let id = 0;
    ws.onopen = () => resolve({
      send(method, params = {}) { return new Promise((res, rej) => { const mid = ++id; const t = setTimeout(() => { if (pending.has(mid)) { pending.delete(mid); rej(new Error('CDP timeout ' + method)); } }, 12000); pending.set(mid, { res: (v) => { clearTimeout(t); res(v); }, rej: (e) => { clearTimeout(t); rej(e); } }); ws.send(JSON.stringify({ id: mid, method, params })); }); },
      on(method, h) { (handlers.get(method) || handlers.set(method, []).get(method)).push(h); },
      close() { ws.close(); },
    });
    ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); } else if (m.method && handlers.has(m.method)) for (const h of handlers.get(m.method)) h(m.params); };
    ws.onerror = () => reject(new Error('ws error'));
  });
}
async function getTarget(port) { for (let i = 0; i < 50; i++) { try { const l = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); const p = l.find(t => t.type === 'page'); if (p) return p; } catch {} await sleep(100); } throw new Error('no target'); }

(async () => {
  const srvPort = await startServer();
  const cdpPort = 19000 + Math.floor(Math.random() * 500);
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-d3-'));
  const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox', '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--disable-frame-rate-limit', '--run-all-compositor-stages-before-draw', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${udd}`, '--window-size=300,300', '--force-device-scale-factor=0.5', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  const wd = setTimeout(() => { log('!! watchdog'); process.exit(9); }, 80000);
  try {
    const page = await getTarget(cdpPort);
    const cdp = await connectCDP(page.webSocketDebuggerUrl);
    const consoleLines = [];
    cdp.on('Runtime.consoleAPICalled', (p) => consoleLines.push((p.args || []).map(a => a.value ?? a.description ?? '').join(' ')));
    await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${srvPort}/index.html` });
    const ev = async (e) => { const r = await cdp.send('Runtime.evaluate', { expression: e, returnByValue: true }); if (r.exceptionDetails) return { __err: r.exceptionDetails.text }; return r.result.value; };
    const rot = async () => { try { return JSON.parse(await ev('window.__xuanji3d.getArmState()')); } catch { return null; } };

    for (let i = 0; i < 120; i++) { const b = await ev('window.__xuanji3d&&window.__xuanji3d.getBones?window.__xuanji3d.getBones():null'); if (b && typeof b === 'string' && b.includes('"total"')) break; await sleep(500); }
    log('模型就绪');

    await ev('window.__xuanji3d.stopAction()'); await sleep(400);
    const base = []; for (let i = 0; i < 5; i++) { const r = await rot(); if (r) base.push(r); await sleep(120); }
    log('待机基线 lUpper.z=' + (base[0] && base[0].lUpper ? base[0].lUpper.z : '?') + ' rUpper.z=' + (base[0] && base[0].rUpper ? base[0].rUpper.z : '?'));

    const rp = await ev("window.__xuanji3d.playAction('nature')"); log('playAction(nature)=' + JSON.stringify(rp));
    await sleep(2500);
    const mid = []; for (let i = 0; i < 6; i++) { const r = await rot(); if (r) mid.push(r); await sleep(120); }
    log('跳舞中样本 ' + mid.length + ' 组 lUpper.z=' + (mid[0] && mid[0].lUpper ? mid[0].lUpper.z : '?'));

    const rs = await ev('window.__xuanji3d.stopAction()'); log('stopAction()=' + JSON.stringify(rs));
    await sleep(300);
    const after = []; for (let i = 0; i < 6; i++) { const r = await rot(); if (r) after.push(r); await sleep(120); }
    log('喊停后样本 ' + after.length + ' 组 lUpper.z=' + (after[0] && after[0].lUpper ? after[0].lUpper.z : '?'));

    const zof = (s) => s.lUpper ? s.lUpper.z : null;
    console.log('\n================ 结果 ================');
    console.log('  待机 lUpper.z 基准: ' + zof(base[0]));
    console.log('  跳舞中 lUpper.z 范围: ' + (mid.map(zof).filter(v => v !== null).join(', ')));
    console.log('  喊停后 lUpper.z 范围: ' + (after.map(zof).filter(v => v !== null).join(', ')));
    const baseZ = zof(base[0]); const afterZ = after.map(zof).filter(v => v !== null);
    const back = afterZ.length && baseZ !== null && Math.abs(afterZ[afterZ.length - 1] - baseZ) < 0.15;
    console.log('  喊停后是否回到待机Z: ' + (back ? 'PASS(回待机)' : 'FAIL(没回待机)'));
    console.log('======================================\n');
    console.log('──── console ────');
    for (const l of consoleLines) if (/\[MMD\]|\[ACT\]|EXCEPTION/.test(l)) console.log('  ' + l);
    process.exit(0);
  } catch (e) { log('异常: ' + e.message); process.exit(5); }
  finally { clearTimeout(wd); try { chrome.kill(); } catch {} try { fs.rmSync(udd, { recursive: true, force: true }); } catch {} }
})();
