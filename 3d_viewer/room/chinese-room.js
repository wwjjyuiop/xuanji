/**
 * chinese-room.js — 中式房间场景（全程序化，不依赖任何外部素材）
 *
 * 设计要点：
 *   1. 所有贴图用 Canvas 现画，无外部图片依赖，仓库里不多一个二进制文件。
 *   2. 单位换算：琳奈模型高 20.18 单位 ≈ 1.62 m，故 1 m ≈ 12.46 单位。
 *   3. 阴影是"贴地感"的唯一来源，所以主光必须投影，地板必须接收。
 *   4. 房间有明确边界，行走控制器据此限位，人不至于走进虚空。
 */

import * as THREE from 'three';

export const UNIT_PER_METER = 12.46;

/** 米 → 场景单位 */
export const m = (v) => v * UNIT_PER_METER;

/* ────────────────────────── 程序化贴图 ────────────────────────── */

function makeCanvas(size = 512) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  return { c, ctx: c.getContext('2d') };
}

/** 青砖地面：砖缝 + 颗粒噪点 + 轻微色差 */
function brickTexture() {
  const { c, ctx } = makeCanvas(512);
  const COLS = 8, ROWS = 8;
  const bw = c.width / COLS, bh = c.height / ROWS;

  ctx.fillStyle = '#4a4f52';
  ctx.fillRect(0, 0, c.width, c.height);

  for (let r = 0; r < ROWS; r++) {
    // 错缝：奇数排整体偏移半块
    const offset = (r % 2) * bw * 0.5;
    for (let col = -1; col <= COLS; col++) {
      const x = col * bw + offset + 2;
      const y = r * bh + 2;
      const w = bw - 4, h = bh - 4;

      // 每块砖的明度略有差异，避免死板
      const tone = 0.78 + Math.sin(r * 12.9898 + col * 78.233) * 0.08;
      const base = Math.floor(96 * tone);
      ctx.fillStyle = `rgb(${base}, ${base + 4}, ${base + 6})`;
      ctx.fillRect(x, y, w, h);

      // 砖面颗粒
      ctx.fillStyle = 'rgba(255,255,255,0.035)';
      for (let i = 0; i < 22; i++) {
        ctx.fillRect(x + Math.random() * w, y + Math.random() * h, 2, 2);
      }
    }
  }

  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** 墙面：米白抹灰 + 细微竖向水痕 */
function wallTexture() {
  const { c, ctx } = makeCanvas(512);
  const g = ctx.createLinearGradient(0, 0, 0, c.height);
  g.addColorStop(0, '#e9e2d4');
  g.addColorStop(0.55, '#e2d9c8');
  g.addColorStop(1, '#d3c8b4');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, c.width, c.height);

  for (let i = 0; i < 240; i++) {
    ctx.fillStyle = `rgba(150,140,120,${Math.random() * 0.05})`;
    ctx.fillRect(Math.random() * c.width, Math.random() * c.height, 1, Math.random() * 40 + 10);
  }

  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** 木纹：用于窗框、梁、踢脚线 */
function woodTexture() {
  const { c, ctx } = makeCanvas(512);
  ctx.fillStyle = '#6b4a2f';
  ctx.fillRect(0, 0, c.width, c.height);

  for (let i = 0; i < 90; i++) {
    const y = Math.random() * c.height;
    ctx.strokeStyle = `rgba(${40 + Math.random() * 40}, ${28 + Math.random() * 24}, ${16 + Math.random() * 16}, ${0.25 + Math.random() * 0.35})`;
    ctx.lineWidth = 0.6 + Math.random() * 2.2;
    ctx.beginPath();
    ctx.moveTo(0, y);
    // 木纹用二次曲线，比直线自然
    for (let x = 0; x < c.width; x += 64) {
      ctx.quadraticCurveTo(x + 32, y + (Math.random() - 0.5) * 9, x + 64, y + (Math.random() - 0.5) * 4);
    }
    ctx.stroke();
  }

  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** 地毯：深红底 + 回纹边框（用简单几何图案，不画复杂纹样） */
function carpetTexture() {
  const { c, ctx } = makeCanvas(512);
  ctx.fillStyle = '#6d2b28';
  ctx.fillRect(0, 0, c.width, c.height);

  // 外边框
  ctx.strokeStyle = '#c8a04a';
  ctx.lineWidth = 10;
  ctx.strokeRect(14, 14, c.width - 28, c.height - 28);

  // 内回纹：一圈小方块
  ctx.fillStyle = 'rgba(200,160,74,0.55)';
  const step = 32;
  for (let x = 40; x < c.width - 40; x += step) {
    ctx.fillRect(x, 40, 14, 14);
    ctx.fillRect(x, c.height - 54, 14, 14);
  }
  for (let y = 40; y < c.height - 40; y += step) {
    ctx.fillRect(40, y, 14, 14);
    ctx.fillRect(c.width - 54, y, 14, 14);
  }

  // 中心菱形
  ctx.save();
  ctx.translate(c.width / 2, c.height / 2);
  ctx.rotate(Math.PI / 4);
  ctx.strokeStyle = 'rgba(200,160,74,0.45)';
  ctx.lineWidth = 6;
  ctx.strokeRect(-78, -78, 156, 156);
  ctx.restore();

  // 织物噪点
  for (let i = 0; i < 2600; i++) {
    ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.09})`;
    ctx.fillRect(Math.random() * c.width, Math.random() * c.height, 2, 2);
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** 窗外远景：远山 + 天光渐变，贴在窗洞外侧 */
function outsideTexture() {
  const { c, ctx } = makeCanvas(512);
  const sky = ctx.createLinearGradient(0, 0, 0, c.height);
  sky.addColorStop(0, '#9fc4e8');
  sky.addColorStop(0.55, '#cfe0ee');
  sky.addColorStop(1, '#e8eef2');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, c.width, c.height);

  // 三层远山，越远越淡
  const layer = (baseY, color, amp) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(0, c.height);
    ctx.lineTo(0, baseY);
    for (let x = 0; x <= c.width; x += 32) {
      ctx.lineTo(x, baseY + Math.sin(x * 0.011 + amp) * 26 + Math.sin(x * 0.031 + amp * 2) * 11);
    }
    ctx.lineTo(c.width, c.height);
    ctx.closePath();
    ctx.fill();
  };
  layer(c.height * 0.62, 'rgba(150,175,190,0.55)', 1.0);
  layer(c.height * 0.72, 'rgba(120,150,170,0.75)', 2.3);
  layer(c.height * 0.84, 'rgba(92,120,140,0.9)', 3.7);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/* ────────────────────────── 场景构建 ────────────────────────── */

/**
 * @param {THREE.Scene} scene
 * @param {object} opts
 * @param {number} opts.width   房间宽（米），默认 7
 * @param {number} opts.depth   房间深（米），默认 6
 * @param {number} opts.height  房间高（米），默认 3.2
 * @returns {{group:THREE.Group, bounds:object, sunLight:THREE.DirectionalLight}}
 */
export function buildRoom(scene, opts = {}) {
  const W = m(opts.width ?? 7);
  const D = m(opts.depth ?? 6);
  const H = m(opts.height ?? 3.2);
  const T = m(0.12);          // 墙厚

  const group = new THREE.Group();
  group.name = 'chinese-room';

  const brickTex = brickTexture();
  brickTex.repeat.set(W / m(2.2), D / m(2.2));

  const wallTex = wallTexture();
  wallTex.repeat.set(W / m(3), H / m(3));

  const woodTex = woodTexture();
  const carpetTex = carpetTexture();

  // ── 地板 ──
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(W, D),
    new THREE.MeshStandardMaterial({ map: brickTex, roughness: 0.92, metalness: 0.02 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  floor.name = 'floor';
  group.add(floor);

  // ── 地毯（略高于地板，避免 z-fighting）──
  const carpet = new THREE.Mesh(
    new THREE.PlaneGeometry(m(3.4), m(2.6)),
    new THREE.MeshStandardMaterial({ map: carpetTex, roughness: 1.0 })
  );
  carpet.rotation.x = -Math.PI / 2;
  carpet.position.set(0, 0.6, m(0.4));
  carpet.receiveShadow = true;
  group.add(carpet);

  // ── 墙面材质 ──
  const wallMat = new THREE.MeshStandardMaterial({ map: wallTex, roughness: 0.95, side: THREE.DoubleSide });

  // 后墙
  const backWall = new THREE.Mesh(new THREE.PlaneGeometry(W, H), wallMat);
  backWall.position.set(0, H / 2, -D / 2);
  backWall.receiveShadow = true;
  group.add(backWall);

  // 左墙
  const leftWall = new THREE.Mesh(new THREE.PlaneGeometry(D, H), wallMat);
  leftWall.rotation.y = Math.PI / 2;
  leftWall.position.set(-W / 2, H / 2, 0);
  leftWall.receiveShadow = true;
  group.add(leftWall);

  // 右墙
  const rightWall = new THREE.Mesh(new THREE.PlaneGeometry(D, H), wallMat);
  rightWall.rotation.y = -Math.PI / 2;
  rightWall.position.set(W / 2, H / 2, 0);
  rightWall.receiveShadow = true;
  group.add(rightWall);

  // ── 窗（开在后墙偏左），窗框用木纹 ──
  const winW = m(2.4), winH = m(1.6);
  const winX = -W * 0.22, winY = m(1.7);

  // 窗外远景：必须贴在墙的内表面「之前」。
  // 原来放在墙外侧，整块实心后墙把它挡死，窗格里透出来的还是墙面，等于没开窗。
  // T 是墙厚，内表面在 -D/2 + T/2。
  const wallInner = -D / 2 + T / 2;
  const outside = new THREE.Mesh(
    new THREE.PlaneGeometry(winW, winH),
    new THREE.MeshBasicMaterial({ map: outsideTexture() })
  );
  outside.position.set(winX, winY, wallInner + m(0.004));
  group.add(outside);

  // 窗框：四根木条
  const woodMat = new THREE.MeshStandardMaterial({ map: woodTex, roughness: 0.75 });
  const bar = (w, h, x, y, z) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, m(0.08)), woodMat);
    mesh.position.set(x, y, z);
    // 不投影：木条离墙只有几厘米，投出来是一块块硬边纯黑方块，
    // 在房间尺度上看着像贴图坏了，不如不投。
    mesh.castShadow = false;
    return mesh;
  };
  const wf = m(0.1);
  const frameZ = wallInner + m(0.05);
  group.add(bar(winW + wf * 2, wf, winX, winY + winH / 2, frameZ));
  group.add(bar(winW + wf * 2, wf, winX, winY - winH / 2, frameZ));
  group.add(bar(wf, winH, winX - winW / 2, winY, frameZ));
  group.add(bar(wf, winH, winX + winW / 2, winY, frameZ));
  // 竖向窗棂
  group.add(bar(wf * 0.6, winH, winX, winY, frameZ));
  group.add(bar(winW, wf * 0.6, winX, winY, frameZ));

  // ── 踢脚线 ──
  const skirtMat = new THREE.MeshStandardMaterial({ map: woodTex, roughness: 0.8 });
  const skirtH = m(0.12), skirtT = m(0.04);
  const skirtBack = new THREE.Mesh(new THREE.BoxGeometry(W, skirtH, skirtT), skirtMat);
  skirtBack.position.set(0, skirtH / 2, -D / 2 + skirtT / 2);
  skirtBack.castShadow = true; skirtBack.receiveShadow = true;
  group.add(skirtBack);

  const skirtL = new THREE.Mesh(new THREE.BoxGeometry(skirtT, skirtH, D), skirtMat);
  skirtL.position.set(-W / 2 + skirtT / 2, skirtH / 2, 0);
  skirtL.castShadow = true; skirtL.receiveShadow = true;
  group.add(skirtL);

  const skirtR = new THREE.Mesh(new THREE.BoxGeometry(skirtT, skirtH, D), skirtMat);
  skirtR.position.set(W / 2 - skirtT / 2, skirtH / 2, 0);
  skirtR.castShadow = true; skirtR.receiveShadow = true;
  group.add(skirtR);

  // ── 靠近相机一侧留空（相机从这里看进来），不加墙 ──

  // ── 灯光组 ──
  // 嵌进既有场景时必须传 withLights:false：
  // 房间自带的主光是暖色强光，会把数字人原有肤色光感整片冲掉，人就不像原来的她了。
  // 关掉后由调用方原有灯光照明，人物外观零改动。
  const withLights = (opts.withLights !== false);

  // 主光：从窗外斜射，唯一投影光源
  // z 取墙外侧（-D/2 再往外），光才是"从窗外来"的，不是从屋里打出来的
  let sunLight = null;
  if (withLights) {
    sunLight = new THREE.DirectionalLight(0xfff2dc, 2.1);
    sunLight.position.set(winX + m(2.5), winY + m(2.2), -D / 2 - m(1.2));
    sunLight.target.position.set(0, m(0.9), m(0.6));
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.set(2048, 2048);
    sunLight.shadow.camera.near = m(0.5);
    sunLight.shadow.camera.far = m(18);
    sunLight.shadow.camera.left = -W * 0.75;
    sunLight.shadow.camera.right = W * 0.75;
    sunLight.shadow.camera.top = H * 1.6;
    sunLight.shadow.camera.bottom = -m(1.5);
    // 🔴 关键：改了视锥字段必须手动重算投影矩阵，
    // 否则影子相机仍是构造时的默认 ±5 小框，阴影只覆盖房间中心一小块。
    sunLight.shadow.camera.updateProjectionMatrix();
    sunLight.shadow.bias = 0.0;          // 负 bias 是 acne 放大器，靠 normalBias 抗
    sunLight.shadow.normalBias = 0.02;
    group.add(sunLight);
    group.add(sunLight.target);

    // 补光：室内 ambiente，避免暗部死黑
    group.add(new THREE.AmbientLight(0xcfd8e6, 0.55));

    // 暖色灯笼光：给中式氛围一个视觉落点
    const lanternLight = new THREE.PointLight(0xffb066, 12, m(7), 2);
    lanternLight.position.set(W * 0.28, m(2.3), -D * 0.15);
    group.add(lanternLight);
  } else {
    // 只留灯笼这点暖光做环境色，强度压到不干扰人物原有光照
    const lanternLight = new THREE.PointLight(0xffb066, 1.6, m(7), 2);
    lanternLight.position.set(W * 0.28, m(2.3), -D * 0.15);
    group.add(lanternLight);
  }

  // 灯笼实体（自发光，任何模式下都在，给中式氛围一个视觉落点）
  const lantern = new THREE.Mesh(
    new THREE.SphereGeometry(m(0.16), 20, 16),
    new THREE.MeshStandardMaterial({
      color: 0xff9a4d, emissive: 0xff7a22, emissiveIntensity: 2.4, roughness: 0.5,
    })
  );
  lantern.position.set(W * 0.28, m(2.3), -D * 0.15);
  group.add(lantern);

  scene.add(group);

  return {
    group,
    sunLight,
    /** 人可活动范围（场景单位，以房间中心为原点） */
    bounds: {
      minX: -W / 2 + m(0.8),
      maxX: W / 2 - m(0.8),
      minZ: -D / 2 + m(0.8),
      maxZ: D / 2 - m(0.8),
    },
  };
}

/** 为场景启用阴影渲染（放在 renderer 上） */
export function enableShadows(renderer) {
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
}

/** 让模型整体投影（MMD 的 SkinnedMesh 默认不投影） */
export function makeCastShadow(root) {
  root.traverse((o) => {
    if (o.isMesh || o.isSkinnedMesh) {
      o.castShadow = true;
      o.receiveShadow = false;
    }
  });
}

/**
 * 释放房间占用的 GPU 资源。
 * 本模块每次 buildRoom 都会新建 5 张 CanvasTexture 和一批 geometry/material，
 * 不释放就重复建会持续吃显存。SPA 里卸载房间时必须调这个。
 */
export function disposeRoom(group) {
  if (!group) return;

  const seenTex = new Set();
  const seenMat = new Set();

  group.traverse((o) => {
    if (o.geometry) o.geometry.dispose();

    const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
    for (const mat of mats) {
      if (seenMat.has(mat)) continue;
      seenMat.add(mat);
      for (const key of ['map', 'emissiveMap', 'normalMap', 'roughnessMap', 'metalnessMap']) {
        const tex = mat[key];
        if (tex && !seenTex.has(tex)) {
          seenTex.add(tex);
          tex.dispose();
        }
      }
      mat.dispose();
    }
  });

  if (group.parent) group.parent.remove(group);
}
