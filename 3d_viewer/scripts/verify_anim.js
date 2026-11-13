#!/usr/bin/env node
/**
 * 玄机 3D 动作验收脚本（自动判定 PASS/FAIL）
 *
 * 原理：用本机 headless Chrome 加载 3d_viewer/index.html，走 CDP：
 *   1. 等模型加载完成（window.__xuanji3d.getBones() 返回骨架）；
 *   2. 采集「待机」基线手臂世界坐标；
 *   3. 调用 playAction(<action>) 触发外部 .vmd 动作；
 *   4. 连续采样手臂骨骼世界坐标，计算位移幅度；
 *   5. 位移 > 阈值 → PASS（动作真的动起来了），否则 FAIL。
 * 同时把页面 console 里 [MMD]/[ACT] 链路日志原样打印出来，定位「卡在哪一环」。
 *
 * 依赖：node >= 22（自带 WebSocket/fetch）、google-chrome。无第三方包、不联网。
 * 用法：node scripts/verify_anim.js [action=wave] [阈值=1.0] [采样秒=5]
 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const ACTION = process.argv[2] || 'wave';
const ROT_THRESHOLD = parseFloat(process.argv[3] || '0.10');   // 局部 rotation 偏离阈值(rad)，~6°，明显高于呼吸/眨眼噪声
const SAMPLE_SEC = parseFloat(process.argv[4] || '8');

const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.json': 'application/json', '.pmx': 'application/octet-stream',
  '.vmd': 'application/octet-stream', '.glb': 'model/gltf-binary',
  '.wasm': 'application/wasm', '.wav': 'audio/wav', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.tga': 'application/octet-stream', '.spa': 'application/octet-stream',
};

function log(...a) { console.log('[verify]', ...a); }

// ─── 静态服务器 ───
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

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ─── CDP 客户端（node 22 内置 WebSocket）───
function connectCDP(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const pending = new Map();
    const handlers = new Map();
    let id = 0;
    ws.onopen = () => resolve({
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const mid = ++id;
          pending.set(mid, { res, rej });
          ws.send(JSON.stringify({ id: mid, method, params }));
        });
      },
      on(method, h) { (handlers.get(method) || handlers.set(method, []).get(method)).push(h); },
      close() { ws.close(); },
    });
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id); pending.delete(msg.id);
        msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
      } else if (msg.method && handlers.has(msg.method)) {
        for (const h of handlers.get(msg.method)) h(msg.params);
      }
    };
    ws.onerror = (e) => reject(new Error('CDP ws error'));
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
  throw new Error('找不到 Chrome page target');
}

// ─── 主流程 ───
(async () => {
  const srvPort = await startServer();
  log(`静态服务器: http://127.0.0.1:${srvPort}`);
  const cdpPort = 19000 + Math.floor(Math.random() * 500);
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-verify-'));
  const chrome = spawn('google-chrome', [
    '--headless=new', '--no-sandbox', '--disable-gpu-sandbox',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist',
    // 小窗口 + 强制帧率，避免 SwiftShader 软件渲染把 rAF 拖慢（否则动画被时间拉长，测不准）
    '--disable-frame-rate-limit', '--run-all-compositor-stages-before-draw',
    '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
    `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${userDataDir}`,
    '--window-size=200,200', '--force-device-scale-factor=0.5', '--no-first-run', 'about:blank',
  ], { stdio: 'ignore' });

  try {
    const page = await getTarget(cdpPort);
    const cdp = await connectCDP(page.webSocketDebuggerUrl);
    const consoleLines = [];
    cdp.on('Runtime.consoleAPICalled', (p) => {
      const txt = (p.args || []).map(a => a.value ?? a.description ?? '').join(' ');
      consoleLines.push(`[console.${p.type}] ${txt}`);
    });
    cdp.on('Runtime.exceptionThrown', (p) => {
      const d = p.exceptionDetails;
      consoleLines.push(`[EXCEPTION] ${d.text} ${(d.exception && d.exception.description) || ''}`);
    });
    cdp.on('Log.entryAdded', (p) => {
      consoleLines.push(`[log.${p.entry.level}] ${p.entry.text}`);
    });
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${srvPort}/index.html` });

    const evalJS = async (expr) => {
      const r = await cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true });
      if (r.exceptionDetails) return { __err: (r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text };
      return r.result.value;
    };

    // WebGL 探测
    const gl = await evalJS(`(function(){try{var c=document.createElement('canvas');return c.getContext('webgl2')?'webgl2-ok':(c.getContext('webgl')?'webgl1-ok':'NO-WEBGL');}catch(e){return 'ERR:'+e.message;}})()`);
    log(`WebGL: ${JSON.stringify(gl)}`);

    // 等模型就绪
    let ready = false;
    for (let i = 0; i < 120; i++) {
      const bones = await evalJS(`window.__xuanji3d && window.__xuanji3d.getBones ? window.__xuanji3d.getBones() : null`);
      if (bones && typeof bones === 'string' && bones !== 'no-skeleton' && bones.includes('"total"')) { ready = true; break; }
      await sleep(500);
    }
    if (!ready) {
      console.log('\n[verify] RESULT = FAIL  页面/模型未就绪（module 脚本可能崩溃或 WebGL 失败）');
      console.log('──── console 日志（截取）────');
      for (const l of consoleLines) console.log('  ' + l);
      return;
    }
    const bonesInfo = await evalJS(`window.__xuanji3d.getBones()`);
    log(`模型就绪: ${bonesInfo}`);

    const parseArm = (s) => { try { return JSON.parse(s); } catch { return null; } };
    const parseRot = (s) => { try { return JSON.parse(s); } catch { return null; } };

    const sampleWorld = async () => parseArm(await evalJS(`window.__xuanji3d.getArmWorld()`));
    const sampleRot = async () => parseRot(await evalJS(`window.__xuanji3d.getArmState()`));

    // 采集待机基线（局部 rotation 是固定值；世界坐标只有呼吸级微动）
    const baseRot = [], baseWorld = [];
    await evalJS(`window.__xuanji3d.setArmLock(true)`);   // 锁住待机摆臂，拿到纯净的待机姿态
    await evalJS(`window.__xuanji3d.stopAction()`);
    await sleep(400);
    for (let i = 0; i < 8; i++) { const r = await sampleRot(); if (r) baseRot.push(r); const w = await sampleWorld(); if (w) baseWorld.push(w); await sleep(120); }
    const baseDisp = maxDisp(baseWorld);
    log(`待机基线 手臂世界位移幅度 = ${baseDisp.toFixed(4)} 单位（应≈0）`);

    // 触发动作
    const ret = await evalJS(`window.__xuanji3d.playAction('${ACTION}')`);
    log(`playAction('${ACTION}') 返回 = ${JSON.stringify(ret)}`);

    // 采样播放过程（局部 rotation + 世界坐标）
    const duringRot = [], duringWorld = [];
    const t0 = Date.now();
    const intervalMs = Math.max(80, (SAMPLE_SEC * 1000) / 60);
    while (Date.now() - t0 < SAMPLE_SEC * 1000) {
      const r = await sampleRot(); if (r) duringRot.push(r);
      const w = await sampleWorld(); if (w) duringWorld.push(w);
      await sleep(intervalMs);
    }
    const disp = maxDisp(duringWorld);
    const rotDev = maxRotDev(baseRot, duringRot);
    const moved = rotDev >= ROT_THRESHOLD;
    console.log('\n================ 验收结果 ================');
    console.log(`  动作: ${ACTION}`);
    console.log(`  待机 世界位移幅度: ${baseDisp.toFixed(4)} 单位`);
    console.log(`  播放 世界位移幅度: ${disp.toFixed(4)} 单位   (样本 ${duringWorld.length})`);
    console.log(`  播放 局部rotation最大偏离: ${rotDev.toFixed(4)} rad (${(rotDev * 180 / Math.PI).toFixed(1)}°)   阈值 ${ROT_THRESHOLD} rad`);
    if (duringWorld.length) {
      const h = duringWorld[duringWorld.length - 1].rHand || duringWorld[duringWorld.length - 1].lHand;
      if (h) console.log(`  末帧手部世界坐标: x=${h.x} y=${h.y} z=${h.z}`);
    }
    console.log(`  RESULT = ${moved ? 'PASS' : 'FAIL'}   ${moved ? '动作确实在驱动骨骼' : '播放期间骨骼没有实质位移'}`);
    console.log('==========================================\n');

    console.log('──── 页面 console 链路日志（[MMD]/[ACT]/异常）────');
    for (const l of consoleLines) {
      if (/\[MMD\]|\[ACT\]|\[Xuanji3D\]|EXCEPTION|Error|error|Morph|加载/.test(l)) console.log('  ' + l);
    }

    process.exitCode = moved ? 0 : 1;
  } finally {
    try { chrome.kill(); } catch {}
    try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
    process.exit();
  }

  function maxDisp(samples) {
    if (samples.length < 2) return 0;
    const keys = ['lUpper', 'lElbow', 'lHand', 'rUpper', 'rElbow', 'rHand'];
    let best = 0;
    for (const k of keys) {
      for (let i = 0; i < samples.length; i++) {
        for (let j = i + 1; j < samples.length; j++) {
          const a = samples[i][k], b = samples[j][k];
          if (!a || !b) continue;
          const d = Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
          if (d > best) best = d;
        }
      }
    }
    return best;
  }

  function maxRotDev(base, during) {
    if (!base.length || !during.length) return 0;
    const keys = ['lUpper', 'lElbow', 'lHand', 'rUpper', 'rElbow', 'rHand'];
    const ref = base[0];
    let best = 0;
    for (const k of keys) {
      const rb = ref[k]; if (!rb) continue;
      for (const s of during) {
        const rs = s[k]; if (!rs) continue;
        const d = Math.max(Math.abs(rs.x - rb.x), Math.abs(rs.y - rb.y), Math.abs(rs.z - rb.z));
        if (d > best) best = d;
      }
    }
    return best;
  }
})();
