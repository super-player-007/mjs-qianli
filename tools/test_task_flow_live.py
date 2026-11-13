"""任务巡检实测 v2：驱动到托管战斗 → 触发巡检 → 抓取任务页 OCR 全文。"""
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
from run import Config, build_ctx, setup_logger  # noqa: E402

log = setup_logger("mjs", "runtime")
cfg = Config.load()
ctx = build_ctx(cfg, log)

from src.game.runner import (STATE_DONE, STATE_STOP, AutoRunner,
                             TRUSTEE_CHECK_REGION, _has)  # noqa: E402

r = AutoRunner(ctx=ctx, log=log)

# 抓取每次 OCR 的文本（事后找任务页那份）
ocr_log = []
orig_ocr = r._ocr


def rec_ocr(img, region=None):
    items = orig_ocr(img, region=region)
    texts = [getattr(it, "text", "") for it in items]
    ocr_log.append((region is not None, texts))
    return items


r._ocr = rec_ocr

# ① 驱动状态机直到托管生效
trustee_on = False
for i in range(45):
    img, items = r._state_items()
    state = r.classify(items)
    if state == "battle" and _has(items, "取消托管", "离开中"):
        trustee_on = True
        log.info("=== 托管生效（第 %d 步） ===", i + 1)
        break
    status, msg = r.step()
    log.info("[%d] %s: %s", i + 1, status, msg)
    if status in (STATE_STOP, STATE_DONE):
        log.error("状态机停住：%s", msg)
        break

if not trustee_on:
    log.error("未进入托管状态，测试中止")
    raise SystemExit(1)

# ② 计时巡检
taps = []
orig_tap = r._tap


def timed_tap(x, y, wait=2.0):
    t0 = time.time()
    orig_tap(x, y, wait=wait)
    taps.append(((x, y), round(time.time() - t0, 2)))


r._tap = timed_tap
t0 = time.time()
r._task_reward_flow()
log.info("=== 巡检总耗时 %.1f 秒 ===", time.time() - t0)
for pt, dur in taps:
    log.info("点击 %s（%.1fs）", pt, dur)

# ③ 打印任务页 OCR（非 region 的最长一份）
pages = [(t, r) for regionless, t in ocr_log if regionless]
if pages:
    task_page = max(pages, key=lambda x: len(x[0]))
    log.info("任务页 OCR（%d 条）: %s", len(task_page[0]), task_page[0])

# ④ 验证回到托管
img = r._shot()
region = orig_ocr(img, region=TRUSTEE_CHECK_REGION)
texts = [getattr(it, "text", "") for it in region]
log.info("返回后右上区域: %s", texts)
log.info("回到托管界面: %s", any("取消托管" in t or "离开中" in t for t in texts))
