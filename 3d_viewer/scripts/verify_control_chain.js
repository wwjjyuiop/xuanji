#!/usr/bin/env node
/**
 * 玄机 3D 动作控制链 验收脚本（三合一：真动 / 真停 / 播完自动回待机）
 * 原理：headless Chrome 加载页面，用「局部骨骼 rotation + 页面状态回读」客观判定。
 *   A 真动： playAction('nature') 后，上臂 lUpper.z / rUpper.z 明显偏离待机基准。
 *   B 真停： stopAction() 后，上臂 rotation 稳定回到待机基准，且 getState().playingVmd=false。
 *   C 自动回待机：一次性动作 playAction('wave') 自然播完后，无需手动 stop 也回到待机。
 * 用法：node scripts/verify_control_chain.js
 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.pmx': 'application/octet-stream', '.vmd': 'application/octet-stream', '.wasm': 'application/wasm', '.wav': 'audio/wav' };
const log = (...a) => console.log('[verify]', ...a);
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

// 上臂 rotation 偏离基准的最大绝对值（rad）
function armDev(base, samples) {
  if (!base || !base.lUpper || !samples.length) return 0;
  let best = 0;
  for (const s of samples) {
    if (!s || !s.lUpper) continue;
    const d = Math.max(Math.abs(s.lUpper.z - base.lUpper.z), Math.abs(s.rUpper.z - base.rUpper.z));
    if (d > best) best = d;
  }
  return best;
}

(async () => {
  const srvPort = await startServer();
  const cdpPort = 19000 + Math.floor(Math.random() * 500);
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-vcc-'));
  const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox', '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--disable-frame-rate-limit', '--run-all-compositor-stages-before-draw', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${udd}`, '--window-size=300,300', '--force-device-scale-factor=0.5', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  const wd = setTimeout(() => { log('!! watchdog 90s'); process.exit(9); }, 90000);
  try {
    const page = await getTarget(cdpPort);
    const cdp = await connectCDP(page.webSocketDebuggerUrl);
    const consoleLines = [];
    cdp.on('Runtime.consoleAPICalled', (p) => consoleLines.push((p.args || []).map(a => a.value ?? a.description ?? '').join(' ')));
    cdp.on('Runtime.exceptionThrown', (p) => { const d = p.exceptionDetails; consoleLines.push('EXCEPTION ' + d.text); });
    await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${srvPort}/index.html` });
    const ev = async (e) => { const r = await cdp.send('Runtime.evaluate', { expression: e, returnByValue: true }); if (r.exceptionDetails) return { __err: r.exceptionDetails.text }; return r.result.value; };
    const rot = async () => { try { return JSON.parse(await ev('window.__xuanji3d.getArmState()')); } catch { return null; } };
    const state = async () => { const s = await ev('window.__xuanji3d.getState ? window.__xuanji3d.getState() : "no-getState"'); return s; };

    // 等模型
    let ready = false;
    for (let i = 0; i < 120; i++) { const b = await ev('window.__xuanji3d&&window.__xuanji3d.getBones?window.__xuanji3d.getBones():null'); if (b && typeof b === 'string' && b.includes('"total"')) { ready = true; break; } await sleep(500); }
    if (!ready) { log('模型未就绪 FAIL'); process.exit(4); }
    log('模型就绪');

    // 待机基线
    await ev('window.__xuanji3d.stopAction()'); await sleep(400);
    const base = []; for (let i = 0; i < 5; i++) { const r = await rot(); if (r) base.push(r); await sleep(120); }
    const b0 = base[0];
    log(`待机基线 lUpper.z=${b0.lUpper.z} rUpper.z=${b0.rUpper.z}  getState=${await state()}`);

    // A 真动
    const ra = await ev("window.__xuanji3d.playAction('nature')");
    await sleep(2500);
    const mid = []; for (let i = 0; i < 6; i++) { const r = await rot(); if (r) mid.push(r); await sleep(120); }
    const devA = armDev(b0, mid);
    log(`A真动 playAction('nature')=${JSON.stringify(ra)}  上臂Z最大偏离=${devA.toFixed(3)} rad`);

    // B 真停
    const rb = await ev('window.__xuanji3d.stopAction()');
    await sleep(300);
    const after = []; for (let i = 0; i < 6; i++) { const r = await rot(); if (r) after.push(r); await sleep(120); }
    const devB = armDev(b0, after);
    const stB = await state();
    log(`B真停 stopAction()=${JSON.stringify(rb)}  停后上臂Z偏离=${devB.toFixed(3)} rad  getState=${stB}`);

    // C 自动回待机（一次性动作自然播完）——以页面状态回读 getState() 为主判据（避免软件渲染 stall 干扰骨骼采样）
    // 用 standup(1.4s) 这个真正短的一次性动作来测；wave 长 93.6s 不适合做"播完"观测。
    // 轮询 getState 直到 playingVmd=false（自然播完→finished→stopAction），最多 ~8.4s；
    // 若期间 rAF 冻结(frameCount 停滞>1.5s 而 playingVmd 仍 true)，判定为 headless 渲染 stall，清场重试一次。
    const CNAME = 'standup';
    let rc = null, stC = null, stCobj = null;
    for (let attempt = 0; attempt < 2; attempt++) {
        rc = await ev("window.__xuanji3d.playAction('" + CNAME + "')");
        let prevFc = -1, frozenMs = 0;
        for (let i = 0; i < 28; i++) {           // 28 × 300ms ≈ 8.4s
            await sleep(300);
            stC = await state();
            try { stCobj = JSON.parse(stC); } catch { stCobj = null; }
            if (stCobj && stCobj.playingVmd === false) break;
            if (stCobj && stCobj.frameCount !== undefined) {
                if (stCobj.frameCount === prevFc) frozenMs += 300; else { frozenMs = 0; prevFc = stCobj.frameCount; }
                if (frozenMs >= 1500) { log(`C阶段 rAF 冻结 ${frozenMs}ms → headless 渲染 stall，清场重试`); break; }
            }
        }
        if (stCobj && stCobj.playingVmd === false) break;
        await ev('window.__xuanji3d.stopAction()'); await sleep(300);
    }
    let devC = 0, rotC = null;
    for (let i = 0; i < 3; i++) { const r = await rot(); if (r) { rotC = r; break; } await sleep(150); }
    if (rotC) devC = armDev(b0, [rotC]);
    const CstateOK = !!(stCobj && stCobj.playingVmd === false && stCobj.activeBoneAction === 'idle' && stCobj.curVmdAction === null);
    log(`C自动回待机 playAction('${CNAME}')=${JSON.stringify(rc)}  播完回读 getState=${stC}  上臂Z偏离=${devC.toFixed(3)} rad`);

    const A = devA > 0.15;          // 上臂Z偏离 > ~9° 算真动
    const B = devB < 0.08;          // 停后回到待机(±~5°内)
    const C = CstateOK && devC < 0.08;   // 状态回 idle + 上臂回到待机Z
    console.log('\n================ 验收结果 ================');
    console.log(`  A 说跳就真跳(跳舞上臂Z偏离0.15rad):  ${A ? 'PASS' : 'FAIL'}  实测偏离=${devA.toFixed(3)}`);
    console.log(`  B 说停就真停(停后回待机<0.08rad):   ${B ? 'PASS' : 'FAIL'}  实测偏离=${devB.toFixed(3)}`);
    console.log(`  C 播完自动回待机(状态idle且Z<0.08): ${C ? 'PASS' : 'FAIL'}  状态OK=${CstateOK} 偏离=${devC.toFixed(3)}`);
    console.log('========================================\n');
    console.log('──── 页面 console 链路日志 ────');
    for (const l of consoleLines) if (/\[MMD\]|\[ACT\]|\[Xuanji3D\]|EXCEPTION/.test(l)) console.log('  ' + l);
    process.exit(A && B && C ? 0 : 1);
  } catch (e) { log('异常: ' + e.message); process.exit(5); }
  finally { clearTimeout(wd); try { chrome.kill(); } catch {} try { fs.rmSync(udd, { recursive: true, force: true }); } catch {} }
})();
