"""采集结算链 5 状态的原生截图（victory_blank/next_preview/settle_confirm/
run_settle/reward_overlay），用于模板匹配评估。"""
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
from run import Config, build_ctx, setup_logger  # noqa: E402

log = setup_logger("mjs", "runtime")
cfg = Config.load()
ctx = build_ctx(cfg, log)

from src.game.runner import STATE_DONE, STATE_STOP, AutoRunner  # noqa: E402

r = AutoRunner(ctx=ctx, log=log)

TARGETS = {"victory_blank", "next_preview", "settle_confirm",
           "run_settle", "reward_overlay"}
captured = set()
log.info("开始采集结算链状态截图…")
for i in range(80):
    img, items = r._state_items()
    state = r.classify(items)
    if state in TARGETS and state not in captured:
        path = f"runtime/shots/cal_settle_{state}.png"
        r._save(img, f"cal_settle_{state}")
        captured.add(state)
        log.info("已采集 %s → %s（%d/5）", state, path, len(captured))
    if len(captured) == len(TARGETS):
        log.info("=== 5 个状态全部采集完成 ===")
        break
    status, msg = r.step()
    log.info("[%d] %s: %s", i + 1, status, msg)
    if status in (STATE_STOP, STATE_DONE):
        log.error("状态机停住：%s", msg)
        break
log.info("采集结果: %s", captured)
