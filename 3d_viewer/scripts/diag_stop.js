#!/usr/bin/env node
/**
 * 诊断脚本（不改代码，先取证）：验证「说停就真停」+「播完自动回待机」两条控制链。
 * 用法：node scripts/diag_stop.js
 * 输出：待机基线 / 跳舞中 / 喊停后 / 一次性动作播完后 各阶段手臂骨骼数据 + PASS/FAIL。
 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.json': 'application/json', '.pmx': 'application/octet-stream',
  '.vmd': 'application/octet-stream', '.glb': 'model/gltf-binary',
  '.wasm': 'application/wasm', '.wav': 'audio/wav', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.tga': 'application/octet-stream', '.spa': 'application/octet-stream',
};
function log(...a) { console.log('[diag]', ...a); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function startServer() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://x');
      let fp = path.join(ROOT, decodeURIComponent(url.pathname));
      if (fp.endsWith('/') || url.pathname === '/') fp = path.join(ROOT, 'index.html');
      fs.readFile(fp, (err, buf) => {
        if (err) { res.writeHead(404); res.end('404'); return; }
        res.writeHead(200, { 'Content-Type': MIME[path.extname(fp).toLowerCase()] || 'application/octet-stream' });
        res.end(buf);
      });
    });
    srv.listen(0, '127.0.0.1', () => resolve(srv.address().port));
  });
}

function connectCDP(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const pending = new Map(); const handlers = new Map(); let id = 0;
    ws.onopen = () => resolve({
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const mid = ++id; pending.set(mid, { res, rej });
          ws.send(JSON.stringify({ id: mid, method, params }));
        });
      },
      on(method, h) { (handlers.get(method) || handlers.set(method, []).get(method)).push(h); },
      close() { ws.close(); },
    });
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.id && pending.has(msg.id)) { const { res, rej } = pending.get(msg.id); pending.delete(msg.id); msg.error ? rej(new Error(msg.error.message)) : res(msg.result); }
      else if (msg.method && handlers.has(msg.method)) for (const h of handlers.get(msg.method)) h(msg.params);
    };
    ws.onerror = () => reject(new Error('CDP ws error'));
  });
}

async function getTarget(port) {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find(t => t.type === 'page');
      if (page) return page;
    } catch {}
    await sleep(100);
  }
  throw new Error('no chrome page target');
}

function maxDisp(samples) {
  if (samples.length < 2) return 0;
  const keys = ['lUpper', 'lElbow', 'lHand', 'rUpper', 'rElbow', 'rHand'];
  let best = 0;
  for (const k of keys) for (let i = 0; i < samples.length; i++) for (let j = i + 1; j < samples.length; j++) {
    const a = samples[i][k], b = samples[j][k];
    if (!a || !b) continue;
    const d = Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
    if (d > best) best = d;
  }
  return best;
}
function meanWorld(samples) {
  const keys = ['lUpper', 'lElbow', 'lHand', 'rUpper', 'rElbow', 'rHand'];
  const out = {};
  for (const k of keys) {
    const xs = [], ys = [], zs = [];
    for (const s of samples) if (s && s[k]) { xs.push(s[k].x); ys.push(s[k].y); zs.push(s[k].z); }
    if (!xs.length) continue;
    out[k] = { x: xs.reduce((a, b) => a + b, 0) / xs.length, y: ys.reduce((a, b) => a + b, 0) / ys.length, z: zs.reduce((a, b) => a + b, 0) / zs.length };
  }
  return out;
}
function worldDist(a, b) {
  const keys = ['lUpper', 'lElbow', 'lHand', 'rUpper', 'rElbow', 'rHand'];
  let best = 0, kk = '';
  for (const k of keys) if (a && b && a[k] && b[k]) {
    const d = Math.hypot(a[k].x - b[k].x, a[k].y - b[k].y, a[k].z - b[k].z);
    if (d > best) { best = d; kk = k; }
  }
  return { d: best, k: kk };
}

(async () => {
  const srvPort = await startServer();
  const cdpPort = 19000 + Math.floor(Math.random() * 500);
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-diag-'));
  const chrome = spawn('google-chrome', [
    '--headless=new', '--no-sandbox', '--disable-gpu-sandbox', '--enable-unsafe-swiftshader',
    '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--disable-frame-rate-limit',
    '--run-all-compositor-stages-before-draw', '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
    `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${userDataDir}`,
    '--window-size=200,200', '--force-device-scale-factor=0.5', '--no-first-run', 'about:blank',
  ], { stdio: 'ignore' });

  try {
    const page = await getTarget(cdpPort);
    const cdp = await connectCDP(page.webSocketDebuggerUrl);
    const consoleLines = [];
    cdp.on('Runtime.consoleAPICalled', (p) => { consoleLines.push((p.args || []).map(a => a.value ?? a.description ?? '').join(' ')); });
    cdp.on('Runtime.exceptionThrown', (p) => { const d = p.exceptionDetails; consoleLines.push('EXCEPTION ' + d.text + ' ' + ((d.exception && d.exception.description) || '')); });
    await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${srvPort}/index.html` });

    const evalJS = async (expr) => {
      const r = await cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true });
      if (r.exceptionDetails) return { __err: (r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text };
      return r.result.value;
    };
    const sampleWorld = async () => { const s = await evalJS('window.__xuanji3d.getArmWorld()'); try { return JSON.parse(s); } catch { return null; } };
    const sampleRot = async () => { const s = await evalJS('window.__xuanji3d.getArmState()'); try { return JSON.parse(s); } catch { return null; } };
    const sampleN = async (n, gap) => { const arr = []; for (let i = 0; i < n; i++) { arr.push(await sampleWorld()); await sleep(gap); } return arr.filter(Boolean); };

    // 等模型就绪
    let ready = false;
    for (let i = 0; i < 120; i++) {
      const b = await evalJS('window.__xuanji3d && window.__xuanji3d.getBones ? window.__xuanji3d.getBones() : null');
      if (b && typeof b === 'string' && b !== 'no-skeleton' && b.includes('"total"')) { ready = true; break; }
      await sleep(500);
    }
    if (!ready) { log('模型未就绪'); console.log('console:', consoleLines.join('\n  ')); return; }

    // ── 阶段1：待机基线（不锁臂，让 idle 摆臂自然生效） ──
    await evalJS('window.__xuanji3d.stopAction()');
    await sleep(600);
    const base = await sampleN(8, 120);
    const baseMean = meanWorld(base);
    const baseDisp = maxDisp(base);
    log(`[阶段1] 待机基线 世界位移幅度=${baseDisp.toFixed(4)}（应≈呼吸级噪声）`);

    // ── 阶段2：播一支循环舞（nature），确认真的在动 ──
    const rPlay = await evalJS("window.__xuanji3d.playAction('nature')");
    log(`[阶段2] playAction('nature') 返回=${JSON.stringify(rPlay)}`);
    await sleep(2500);
    const during = await sampleN(12, 120);
    const duringDisp = maxDisp(during);
    log(`[阶段2] 跳舞中 世界位移幅度=${duringDisp.toFixed(4)}  相对基线位移=${worldDist(baseMean, meanWorld(during)).d.toFixed(3)}（应明显 > 基线）`);

    // ── 阶段3：中途喊停 ──
    const rStop = await evalJS('window.__xuanji3d.stopAction()');
    log(`[阶段3] stopAction() 返回=${JSON.stringify(rStop)}`);
    await sleep(400);
    const after = await sampleN(12, 120);
    const afterDisp = maxDisp(after);
    const backToIdle = worldDist(baseMean, meanWorld(after));
    log(`[阶段3] 喊停后 世界位移幅度=${afterDisp.toFixed(4)}  与待机基线最大偏移=${backToIdle.d.toFixed(3)}@${backToIdle.k}（停住应≈0，回待机应≈0）`);

    // ── 阶段4：一次性动作（wave）自然播完，是否自动回待机 ──
    const rWave = await evalJS("window.__xuanji3d.playAction('wave')");
    log(`[阶段4] playAction('wave') 返回=${JSON.stringify(rWave)}`);
    await sleep(5000);   // wave 通常 2~4s，播完应自动回待机
    const waveAfter = await sampleN(12, 120);
    const waveDisp = maxDisp(waveAfter);
    const waveBack = worldDist(baseMean, meanWorld(waveAfter));
    log(`[阶段4] 一次性动作播完5s后 世界位移幅度=${waveDisp.toFixed(4)}  与待机基线最大偏移=${waveBack.d.toFixed(3)}@${waveBack.k}`);

    console.log('\n================ 诊断判定 ================');
    const stopOK = duringDisp > 0.5 && afterDisp < 0.4 && backToIdle.d < 0.6;
    const autoIdleOK = waveDisp < 0.4 && waveBack.d < 0.6;
    console.log(`  阶段2 跳舞真动:      ${duringDisp > 0.5 ? 'PASS' : 'FAIL'}  (位移=${duringDisp.toFixed(3)})`);
    console.log(`  阶段3 喊停真停+回待机: ${stopOK ? 'PASS' : 'FAIL'}  (停后位移=${afterDisp.toFixed(3)}, 离基线=${backToIdle.d.toFixed(3)})`);
    console.log(`  阶段4 播完自动回待机: ${autoIdleOK ? 'PASS' : 'FAIL'}  (播完位移=${waveDisp.toFixed(3)}, 离基线=${waveBack.d.toFixed(3)})`);
    console.log('==========================================\n');
    console.log('──── 页面 console 关键日志 ────');
    for (const l of consoleLines) if (/\[MMD\]|\[ACT\]|\[Xuanji3D\]|EXCEPTION|Error|error/.test(l)) console.log('  ' + l);
  } finally {
    try { chrome.kill(); } catch {}
    try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
    process.exit();
  }
})();
