#!/usr/bin/env node
/**
 * 诊断脚本 v2（取证用，不改代码）：用「页内采样」避免多次 CDP 往返卡死。
 * 每阶段用一次 Runtime.evaluate + awaitPromise，让页面自己按间隔采样 getArmWorld/getArmState。
 * 覆盖：待机基线 / 跳舞中 / 中途喊停 / 一次性动作播完自动回待机。
 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.pmx': 'application/octet-stream', '.vmd': 'application/octet-stream', '.wasm': 'application/wasm', '.wav': 'audio/wav', '.png': 'image/png' };
const log = (...a) => console.log('[diag]', ...a);
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
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const mid = ++id;
          const t = setTimeout(() => { if (pending.has(mid)) { pending.delete(mid); rej(new Error('CDP send timeout: ' + method)); } }, 15000);
          pending.set(mid, { res: (v) => { clearTimeout(t); res(v); }, rej: (e) => { clearTimeout(t); rej(e); } });
          ws.send(JSON.stringify({ id: mid, method, params }));
        });
      },
      on(method, h) { (handlers.get(method) || handlers.set(method, []).get(method)).push(h); },
      close() { ws.close(); },
    });
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.rej(new Error(msg.error.message)) : p.res(msg.result); }
      else if (msg.method && handlers.has(msg.method)) for (const h of handlers.get(msg.method)) h(msg.params);
    };
    ws.onerror = () => reject(new Error('CDP ws error'));
  });
}
async function getTarget(port) {
  for (let i = 0; i < 50; i++) {
    try { const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); const p = list.find(t => t.type === 'page'); if (p) return p; } catch {}
    await sleep(100);
  }
  throw new Error('no chrome page target');
}

const KEYS = ['lUpper', 'lElbow', 'lHand', 'rUpper', 'rElbow', 'rHand'];
function disp(samples) {
  if (samples.length < 2) return 0;
  let best = 0;
  for (const k of KEYS) for (let i = 0; i < samples.length; i++) for (let j = i + 1; j < samples.length; j++) {
    const a = samples[i][k], b = samples[j][k]; if (!a || !b) continue;
    const d = Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z); if (d > best) best = d;
  }
  return best;
}
function mean(samples) {
  const out = {};
  for (const k of KEYS) { const xs = [], ys = [], zs = []; for (const s of samples) if (s && s[k]) { xs.push(s[k].x); ys.push(s[k].y); zs.push(s[k].z); } if (xs.length) out[k] = { x: xs.reduce((a, b) => a + b, 0) / xs.length, y: ys.reduce((a, b) => a + b, 0) / ys.length, z: zs.reduce((a, b) => a + b, 0) / zs.length }; }
  return out;
}
function dist(a, b) {
  let best = 0, kk = '';
  for (const k of KEYS) if (a && b && a[k] && b[k]) { const d = Math.hypot(a[k].x - b[k].x, a[k].y - b[k].y, a[k].z - b[k].z); if (d > best) { best = d; kk = k; } }
  return { d: best, k: kk };
}

(async () => {
  const srvPort = await startServer();
  const cdpPort = 19000 + Math.floor(Math.random() * 500);
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-diag2-'));
  const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox', '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--disable-frame-rate-limit', '--run-all-compositor-stages-before-draw', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${userDataDir}`, '--window-size=200,200', '--force-device-scale-factor=0.5', '--no-first-run', 'about:blank'], { stdio: 'ignore' });

  const watchdog = setTimeout(() => { log('!! WATCHDOG 60s 强制退出'); process.exit(3); }, 60000);

  try {
    const page = await getTarget(cdpPort);
    const cdp = await connectCDP(page.webSocketDebuggerUrl);
    const consoleLines = [];
    cdp.on('Runtime.consoleAPICalled', (p) => { consoleLines.push((p.args || []).map(a => a.value ?? a.description ?? '').join(' ')); });
    cdp.on('Runtime.exceptionThrown', (p) => { const d = p.exceptionDetails; consoleLines.push('EXCEPTION ' + d.text + ' ' + ((d.exception && d.exception.description) || '')); });
    await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${srvPort}/index.html` });

    const evalJS = async (expr, awaitPromise = false) => {
      const r = await cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise });
      if (r.exceptionDetails) return { __err: (r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text };
      return r.result.value;
    };

    // 页内采样：返回 {world:[...], rot:[...]}
    const SAMPLE_FN = `function(){
      var w=[], r=[];
      function one(){ try { w.push(JSON.parse(window.__xuanji3d.getArmWorld())); } catch(e){} try { r.push(JSON.parse(window.__xuanji3d.getArmState())); } catch(e){} }
      return new Promise(function(resolve){
        var n = N, gap = G, i = 0;
        (function step(){ if (i >= n) return resolve({world:w, rot:r}); one(); i++; setTimeout(step, gap); })();
      });
    }`;
    const sampleIn = async (N, G) => {
      const expr = `(${SAMPLE_FN.replace('var n = N', 'var n = ' + N).replace('gap = G', 'gap = ' + G)})()`;
      return await evalJS(expr, true);
    };

    // 等模型
    let ready = false;
    for (let i = 0; i < 120; i++) {
      const b = await evalJS('window.__xuanji3d && window.__xuanji3d.getBones ? window.__xuanji3d.getBones() : null');
      if (b && typeof b === 'string' && b !== 'no-skeleton' && b.includes('"total"')) { ready = true; break; }
      await sleep(500);
    }
    if (!ready) { log('模型未就绪'); process.exit(4); }
    log('模型就绪');

    // 阶段1：待机基线
    await evalJS('window.__xuanji3d.stopAction()'); await sleep(500);
    const baseS = await sampleIn(6, 150); const base = baseS.world || []; const baseDisp = disp(base);
    log(`[阶段1] 待机基线 位移=${baseDisp.toFixed(4)}  n=${base.length}`);

    // 阶段2：跳舞
    const rPlay = await evalJS("window.__xuanji3d.playAction('nature')");
    log(`[阶段2] playAction('nature')=${JSON.stringify(rPlay)}`);
    await sleep(2000);
    const duringS = await sampleIn(8, 150); const during = duringS.world || []; const duringDisp = disp(during);
    log(`[阶段2] 跳舞中 位移=${duringDisp.toFixed(4)}  离基线=${dist(mean(base), mean(during)).d.toFixed(3)}`);

    // 阶段3：喊停
    const rStop = await evalJS('window.__xuanji3d.stopAction()');
    log(`[阶段3] stopAction()=${JSON.stringify(rStop)}`);
    await sleep(300);
    const afterS = await sampleIn(8, 150); const after = afterS.world || []; const afterDisp = disp(after);
    const back = dist(mean(base), mean(after));
    log(`[阶段3] 喊停后 位移=${afterDisp.toFixed(4)}  离基线=${back.d.toFixed(3)}@${back.k}`);

    // 阶段4：一次性动作播完自动回待机
    const rWave = await evalJS("window.__xuanji3d.playAction('wave')");
    log(`[阶段4] playAction('wave')=${JSON.stringify(rWave)}`);
    await sleep(6000);
    const waveS = await sampleIn(8, 150); const wave = waveS.world || []; const waveDisp = disp(wave);
    const waveBack = dist(mean(base), mean(wave));
    log(`[阶段4] 一次性动作播完6s后 位移=${waveDisp.toFixed(4)}  离基线=${waveBack.d.toFixed(3)}@${waveBack.k}`);

    console.log('\n================ 诊断判定 ================');
    const danceOK = duringDisp > 1.0;
    const stopOK = afterDisp < 0.4 && back.d < 0.6;
    const autoIdleOK = waveDisp < 0.4 && waveBack.d < 0.6;
    console.log(`  阶段2 跳舞真动:        ${danceOK ? 'PASS' : 'FAIL'} (位移=${duringDisp.toFixed(3)})`);
    console.log(`  阶段3 喊停真停+回待机: ${stopOK ? 'PASS' : 'FAIL'} (停后位移=${afterDisp.toFixed(3)}, 离基线=${back.d.toFixed(3)})`);
    console.log(`  阶段4 播完自动回待机:  ${autoIdleOK ? 'PASS' : 'FAIL'} (播完位移=${waveDisp.toFixed(3)}, 离基线=${waveBack.d.toFixed(3)})`);
    console.log('==========================================\n');
    console.log('──── console 关键日志 ────');
    for (const l of consoleLines) if (/\[MMD\]|\[ACT\]|\[Xuanji3D\]|EXCEPTION|Error|error/.test(l)) console.log('  ' + l);
    process.exit(danceOK && stopOK && autoIdleOK ? 0 : 1);
  } catch (e) {
    log('异常: ' + e.message);
    process.exit(5);
  } finally {
    clearTimeout(watchdog);
    try { chrome.kill(); } catch {}
    try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  }
})();
