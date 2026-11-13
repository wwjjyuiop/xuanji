/**
 * walk-controller.js — 行走控制器
 *
 * 核心问题：MMD 的走路动作分两类
 *   A. 原地动作（in-place）—— 脚在原地迈，模型不位移
 *   B. 带位移动作（root motion）—— センター 骨骼本身就往前跑
 *
 * 两类都必须归一到 A，再由代码推动模型前进。否则：
 *   - A 不推动 → 原地踏步，像在跑步机上
 *   - B 不归零 → 位置由动画和代码双重叠加，模型会飞出去
 *
 * 另一个必须处理的点：步频要跟移动速度对上，否则滑步。
 */

import * as THREE from 'three';
import { UNIT_PER_METER } from './chinese-room.js';

/** 水平位移超过这个阈值（米）就判定为"带位移的动作"，需要归零 */
const ROOT_MOTION_THRESHOLD_M = 0.35;

export class WalkController {
  /**
   * @param {object} o
   * @param {THREE.Object3D} o.root        承载模型的外层节点（位移作用在它身上）
   * @param {THREE.AnimationClip} o.clip
   * @param {THREE.AnimationMixer} o.mixer
   * @param {object} o.bounds              {minX,maxX,minZ,maxZ} 场景单位
   * @param {number} [o.speed]             行走速度（场景单位/秒），默认 1.0 m/s
   * @param {number} [o.strideLength]      一个步态循环走的距离（米），默认 1.34（两步×0.67）
   * @param {number} [o.turnDuration]      转身耗时（秒），默认 0.55
   */
  constructor(o) {
    this.root = o.root;
    this.clip = o.clip;
    this.mixer = o.mixer;
    this.bounds = o.bounds;
    this.speed = o.speed ?? UNIT_PER_METER;          // 1 m/s
    this.strideLength = o.strideLength ?? 1.34;
    this.turnDuration = o.turnDuration ?? 0.55;

    // 🔴 先剥 root motion，再建 action —— 不依赖"绑定与轨道共用同一数组"这一实现细节
    this.rootMotionStripped = this._stripRootMotion();

    this.action = this.mixer.clipAction(this.clip);
    this.action.setLoop(THREE.LoopRepeat, Infinity);
    this.action.play();

    // 步频对齐：动作跑完一个循环应正好走 strideLength 米。
    // duration 为 0（空 clip）时不能除，否则 Infinity → timeScale 0 →
    // 动画冻住但 root 仍被推动，表现为原地滑步且不报任何错。
    const dur = (this.clip.duration && this.clip.duration > 0) ? this.clip.duration : 1;
    this.nominalSpeed = (this.strideLength * UNIT_PER_METER) / dur;
    this.action.timeScale = this.speed / this.nominalSpeed;

    this._dir = 1;                 // +1 向右，-1 向左
    this._turnT = 0;               // 转身剩余时间
    this._targetYaw = 0;
    this._yaw = 0;

    this.root.rotation.y = this._dir > 0 ? Math.PI / 2 : -Math.PI / 2;
    this._yaw = this.root.rotation.y;
    this._targetYaw = this._yaw;

    this._fwd = new THREE.Vector3();   // 复用，避免每帧 new
  }

  /**
   * 把动作里多余的位移归零，只保留上下起伏（Y）。
   * @returns {boolean} 是否真的剥掉了位移
   */
  _stripRootMotion() {
    let stripped = false;

    for (const track of this.clip.tracks) {
      if (!track.name.endsWith('.position')) continue;
      // 只处理中心骨（センター）的位移轨道。
      // 其他骨骼的 position（甩臂、裙摆、足IK）不该被钉死，否则动作会被改残。
      // 轨道名可能是 ".bones[センター].position"，也可能是修复后的 "センター.position"
      if (!track.name.includes('センター')) continue;

      const v = track.values;
      let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
      for (let i = 0; i < v.length; i += 3) {
        minX = Math.min(minX, v[i]);     maxX = Math.max(maxX, v[i]);
        minZ = Math.min(minZ, v[i + 2]); maxZ = Math.max(maxZ, v[i + 2]);
      }

      const spanX = (maxX - minX) / UNIT_PER_METER;
      const spanZ = (maxZ - minZ) / UNIT_PER_METER;

      //  горизонтальную составляющую钉在首帧值，垂直（Y，上下起伏）保持不动
      if (spanX > ROOT_MOTION_THRESHOLD_M || spanZ > ROOT_MOTION_THRESHOLD_M) {
        const x0 = v[0], z0 = v[2];
        for (let i = 0; i < v.length; i += 3) {
          v[i] = x0;
          v[i + 2] = z0;
        }
        stripped = true;
      }
    }

    return stripped;
  }

  /** 当前朝向前进方向（世界坐标），复用同一向量避免每帧分配 */
  _forward() {
    // 模型默认面朝 +Z；绕 Y 转动后，前进方向 = (sin(yaw), 0, cos(yaw))
    return this._fwd.set(Math.sin(this._yaw), 0, Math.cos(this._yaw));
  }

  _startTurn() {
    this._dir *= -1;
    this._targetYaw = this._yaw + Math.PI * this._dir;
    this._turnT = this.turnDuration;
  }

  /**
   * @param {number} dt 秒
   */
  update(dt) {
    // 自己兜底限幅：切标签页回来 dt 会突然很大，不夹住会瞬移出界
    dt = Math.min(Math.max(dt, 0), 0.1);
    const p = this.root.position;

    if (this._turnT > 0) {
      // 转身中：不前进，平滑转向
      const step = (Math.PI / this.turnDuration) * dt;
      const remain = this._targetYaw - this._yaw;
      if (Math.abs(remain) <= step) {
        this._yaw = this._targetYaw;
        this._turnT = 0;
      } else {
        this._yaw += Math.sign(remain) * step;
        this._turnT -= dt;
      }
      this.root.rotation.y = this._yaw;
      // 转身时放慢动作，像人转身会减速
      this.action.timeScale = (this.speed / this.nominalSpeed) * 0.35;
      return;
    }

    this.action.timeScale = this.speed / this.nominalSpeed;

    const fwd = this._forward();
    p.x += fwd.x * this.speed * dt;
    p.z += fwd.z * this.speed * dt;

    // 边界判定：撞到可活动范围的边就转身
    if (p.x < this.bounds.minX || p.x > this.bounds.maxX ||
        p.z < this.bounds.minZ || p.z > this.bounds.maxZ) {
      p.x = THREE.MathUtils.clamp(p.x, this.bounds.minX, this.bounds.maxX);
      p.z = THREE.MathUtils.clamp(p.z, this.bounds.minZ, this.bounds.maxZ);
      this._startTurn();
    }
  }
}
