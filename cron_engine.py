"""
玄机 · 定时任务引擎 cron_engine.py（Windows 端，独立实现）
============================================================
让玄机能定时干活（借鉴 Hermes/OpenClaw 的 cron 思想，但用玄机自己的
Python 环境实现，纯 Windows 端，不依赖 WSL 任何东西）。

能力：
  - 一次性定时："5分钟后提醒我" / "明天早上8点"
  - 周期任务："每天""每小时""每周一"
  - 动作：调玄机 dispatched 手脚干活 / 记录结果

存储：
  - D:\\yuxuanji\\xuanji-gui\\_cron_jobs.json  （任务清单）
  - 后台线程每 60 秒 tick 检查到期任务

用法：
  import cron_engine
  cron_engine.add_job("每天早上8点", "定时", "早上好")
  cron_engine.start()          # 启动调度线程
  cron_engine.stop()           # 停止
"""

import os
import json
import threading
import time
from datetime import datetime, timedelta


_JOBS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cron_jobs.json")
_LOCK = threading.Lock()
_TICK_INTERVAL = 60  # 秒


# ─── 任务存储 ─────────────────────────────────────
def _load_jobs() -> list:
    try:
        if os.path.isfile(_JOBS_FILE):
            with open(_JOBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_jobs(jobs: list):
    try:
        with open(_JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[cron] 保存失败: " + str(e))


# ─── 解析时间描述 → 到期时间(schedule) ────────────
def parse_schedule(desc: str):
    """把自然语言时间描述转成 (type, 数据)。

    支持：一次性("5分钟后"->5m / "明天8点")、周期("每天"->daily)等。
    返回 (kind, payload)：
      ("once", timestamp)    一次性，到期时间戳
      ("daily", "HH:MM")     每天
      ("hourly", None)       每小时
      ("interval", seconds)   每 N 秒
    """
    desc = (desc or "").strip().lower()
    now = datetime.now()
    # 相对时间：X 分钟后
    import re
    m = re.search(r"(\d+)\s*(秒|秒钟|分|分钟|小|小时|时|天)", desc)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if "秒" in unit:
            return ("interval", num)
        if "分" in unit:
            return ("once", time.time() + num * 60)
        if "小" in unit or "时" in unit:
            return ("once", time.time() + num * 3600)
        if "天" in unit:
            return ("daily", now.strftime("%H:%M"))  # 简化：明天同刻
    # 周期：每天 / 每小时
    if "每天" in desc or "每日" in desc:
        m2 = re.search(r"(\d{1,2})[::点时](\d{1,2})?", desc)
        if m2:
            hh = int(m2.group(1)); mm = int(m2.group(2) or 0)
            return ("daily", f"{hh:02d}:{mm:02d}")
        return ("daily", now.strftime("%H:%M"))
    if "每小时" in desc or "每小时" in desc:
        return ("hourly", None)
    # 默认：5 分钟后一次性
    return ("once", time.time() + 300)


def add_job(desc, title, action=None):
    """添加一个定时任务。返回 job dict。"""
    kind, payload = parse_schedule(desc)
    job = {
        "id": str(int(time.time() * 1000)),
        "title": title,
        "desc": desc,
        "action": action or title,
        "kind": kind,
        "payload": payload,
        "created": datetime.now().isoformat(timespec="seconds"),
        "last_run": None,
        "disabled": False,
    }
    with _LOCK:
        jobs = _load_jobs()
        jobs.append(job)
        _save_jobs(jobs)
    print(f"[cron] 已添加定时任务: {title} ({desc}) kind={kind}")
    return job


def list_jobs():
    return _load_jobs()


def remove_job(job_id):
    with _LOCK:
        jobs = _load_jobs()
        jobs = [j for j in jobs if j.get("id") != job_id]
        _save_jobs(jobs)


# ─── 到期判断 + 执行 ─────────────────────────────
def _is_due(job) -> bool:
    kind = job.get("kind")
    try:
        if kind == "once":
            return time.time() >= float(job["payload"])
        if kind == "interval":
            last = job.get("last_run")
            if not last:
                return time.time() >= float(job["payload"])
            return time.time() - float(last) >= float(job["payload"])
        if kind == "hourly":
            return True  # 每分钟 tick 都触发（简化：每小时阈值由上层控制）
        if kind == "daily":
            hh, mm = job["payload"].split(":")
            cur = datetime.now()
            return (cur.hour == int(hh) and cur.minute == int(mm))
    except Exception:
        return False
    return False


def _run_job(job):
    """执行任务动作：尽力而为，失败不阻塞。"""
    try:
        action = job.get("action") or job.get("title") or ""
        # 尽量调 dispatch 的 hermes 来执行（通用）
        try:
            import sys
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if root not in sys.path:
                sys.path.insert(0, root)
            import dispatch
            r = dispatch.run("hermes", {"cmd": action, "timeout": 120})
            result = r.get("result") or r.get("error") or "done"
            print(f"[cron] 任务执行: {job['title']} -> {str(result)[:80]}")
        except Exception as e:
            print(f"[cron] 任务执行失败: {job['title']} ({e})")
    except Exception:
        pass
    finally:
        # 更新 last_run（interval 用）
        with _LOCK:
            jobs = _load_jobs()
            for j in jobs:
                if j.get("id") == job.get("id"):
                    j["last_run"] = time.time()
                    break
            _save_jobs(jobs)
        # 一次性任务执行后删除
        if job.get("kind") == "once":
            remove_job(job.get("id"))


# ─── 调度线程 ────────────────────────────────────
_thread = None
_running = False


def start():
    global _thread, _running
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    print("[cron] 定时任务引擎已启动")


def stop():
    global _running
    _running = False


def _loop():
    while _running:
        try:
            with _LOCK:
                jobs = _load_jobs()
            for job in jobs:
                if job.get("disabled"):
                    continue
                if job.get("kind") == "hourly":
                    # 每小时：记录上次运行小时，避免重复
                    last = job.get("last_run")
                    if last and (time.time() - float(last)) < 3600:
                        continue
                if _is_due(job):
                    _run_job(job)
        except Exception as e:
            print("[cron] tick 异常: " + str(e))
        time.sleep(_TICK_INTERVAL)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 自测：添加一个 20 秒后的一次性任务
        add_job("20秒后", "自测定时", "回复: 玄机定时生效")
        print("任务清单:", list_jobs())
        print("开始 25 秒观察…")
        start()
        time.sleep(25)
        print("最终清单:", list_jobs())
        stop()
