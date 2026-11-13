"""名将杀 · 千里走单骑 自动化脚本 —— 统一入口。

子命令
------
  selfcheck            环境与设备自检（不操作游戏）
  capture              采集截图（标定用）
  analyze              对已保存的截图做离线识别（标定用，安全）
  observe              只观察不点击（dry-run），实时报告当前识别到的界面
  run                  实际执行单局自动化

示例
----
  .venv/Scripts/python.exe run.py selfcheck
  .venv/Scripts/python.exe run.py capture --count 5 --grid --tag run_map
  .venv/Scripts/python.exe run.py analyze --image assets/screenshots/xxx.png
  .venv/Scripts/python.exe run.py observe
  .venv/Scripts/python.exe run.py run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402

from src.config import Config, ROOT                      # noqa: E402
from src.core.asker import Asker                          # noqa: E402
from src.core.engine import Engine                        # noqa: E402
from src.core.logger import setup_logger                  # noqa: E402
from src.devices.adb import ADBDevice, DeviceError         # noqa: E402
from src.game.context import GameContext                   # noqa: E402
from src.game.policy import DecisionPolicy                 # noqa: E402
from src.vision.annotate import (draw_matches, draw_ocr, read_image,  # noqa: E402
                                 save)
from src.vision.matcher import TemplateMatcher             # noqa: E402
from src.vision.ocr import OCREngine                       # noqa: E402

GAME_PACKAGE = "com.ztgame.mjs"


# ===========================================================================
# 上下文构建
# ===========================================================================
def build_ctx(cfg: Config, log, need_device: bool = True,
              ocr_device: Optional[str] = None) -> GameContext:
    """装配运行时上下文。

    ``ocr_device``：``auto``/``cpu``/``dml``；GUI 可覆盖 settings.yaml 里的
    ``ocr.device``（识别设备切换，2026-11-12）。
    """
    device = ADBDevice(
        adb_path=cfg.adb_path,
        serial=cfg.serial,
        auto_connect=bool(cfg.get("device.auto_connect", True)),
        connect_host=cfg.get("device.connect_host", "127.0.0.1:5555"),
        cmd_timeout=float(cfg.get("device.cmd_timeout", 20)),
        logger=log,
    )
    if need_device:
        device.ensure_connected()
    # 真实运行时才启用 adb 自愈（单测默认关闭，见 ADBDevice.AUTO_RECOVER）
    device.AUTO_RECOVER = True

    matcher = TemplateMatcher(
        template_dir=cfg.templates_dir,
        threshold=float(cfg.get("vision.template_threshold", 0.86)),
        multi_scale=cfg.get("vision.multi_scale", [1.0]),
        nms_iou=float(cfg.get("vision.nms_iou", 0.35)),
        logger=log,
    )
    ocr = OCREngine(
        engine=cfg.get("ocr.engine", "rapidocr"),
        min_score=float(cfg.get("ocr.min_score", 0.5)),
        normalize=bool(cfg.get("ocr.normalize", True)),
        logger=log,
        device=ocr_device or cfg.get("ocr.device", "auto"),
    )
    asker = Asker(
        mode=cfg.get("decision.mode", "ask"),
        ui=cfg.get("decision.ui", "cli"),
        timeout_sec=float(cfg.get("decision.timeout_sec", 300)),
        on_timeout=cfg.get("decision.on_timeout", "abort"),
        high_risk_kinds=cfg.get("decision.high_risk_kinds", []),
        decision_dir=cfg.decision_dir,
        logger=log,
    )
    ctx = GameContext(cfg=cfg, device=device, matcher=matcher,
                      ocr=ocr, asker=asker, log=log)
    ctx.mark("_policy", DecisionPolicy(config=cfg.settings.get("policy")))
    return ctx


# ===========================================================================
# 子命令实现
# ===========================================================================
def cmd_selfcheck(args: argparse.Namespace) -> int:
    log = setup_logger("mjs", Config.load().log_dir)
    cfg = Config.load()
    print("=" * 68)
    print("环境自检")
    print("=" * 68)
    print(f"项目根目录        : {ROOT}")
    print(f"配置文件          : {ROOT / 'config'}")
    print(f"adb 路径          : {cfg.adb_path}  (存在: {Path(cfg.adb_path).exists()})")
    print(f"目标序列号        : {cfg.serial or '(自动)'}")
    print(f"基准分辨率        : {cfg.base_size[0]}x{cfg.base_size[1]}")

    matcher = TemplateMatcher(cfg.templates_dir, logger=log)
    tpls = matcher.available()
    print(f"模板素材          : 共 {len(tpls)} 个"
          + (f" -> {tpls[:8]}{'...' if len(tpls) > 8 else ''}" if tpls else " (尚无，待标定)"))

    ok = True
    # --- 设备 ---
    try:
        dev = ADBDevice(cfg.adb_path, cfg.serial,
                        bool(cfg.get("device.auto_connect", True)),
                        cfg.get("device.connect_host", "127.0.0.1:5555"),
                        logger=log)
        serial = dev.ensure_connected()
        size = dev.size
        fg = dev.foreground_activity()
        pkg = dev.current_package()
        print("-" * 68)
        print(f"[设备] 序列号      : {serial}")
        print(f"[设备] 实际分辨率  : {size[0]}x{size[1]}"
              f"  (与基准一致: {size == cfg.base_size})")
        print(f"[设备] 前台应用    : {pkg or '(未知)'}")
        print(f"[设备] 前台窗口    : {fg}")
        print(f"[设备] 游戏在前台  : {pkg == GAME_PACKAGE}")
        if size != cfg.base_size:
            print(f"  ⚠ 分辨率与基准不一致，坐标会等比缩放；若比例不同建议改 config 基准值")
    except DeviceError as exc:
        ok = False
        print(f"[设备] ✗ {exc}")

    # --- OCR ---
    print("-" * 68)
    ocr = OCREngine(logger=log)
    if ocr.available:
        print("[OCR] 引擎         : rapidocr 可用")
    else:
        ok = False
        print("[OCR] ✗ 不可用（run.py 仍可运行，但文本类判定会失效）")

    print("=" * 68)
    print("结论:", "环境就绪 ✅" if ok else "存在问题 ⚠ 请先修复上面标 ✗ 的项")
    return 0 if ok else 1


def cmd_capture(args: argparse.Namespace) -> int:
    from tools.capture import capture as _capture
    from src.config import SCREENSHOTS_DIR
    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)
    out = Path(args.out) if args.out else SCREENSHOTS_DIR
    paths = _capture(cfg, log, args.tag, args.count, args.interval,
                     args.grid, args.step, out)
    for p in paths:
        print(p)
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """离线识别：对已有截图跑一遍判定链路，画出模板/OCR 结果。"""
    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)
    img = read_image(args.image)
    if img is None:
        print("截图读取失败:", args.image)
        return 2

    ctx = build_ctx(cfg, log, need_device=False)
    from src.game.context import Frame
    from src.game.screen import build_registry

    frame = Frame(image=img, index=0, ts=time.time())
    registry = build_registry()
    print(f"图像: {args.image}  {img.shape[1]}x{img.shape[0]}")
    print("-" * 68)

    hit_any = False
    for spec in registry:
        if spec.name == "unknown":
            continue
        detail = spec.detect(ctx, frame)
        if detail:
            hit_any = True
            print(f"  命中界面: {spec.name:18s} {spec.desc}   <- {detail}")
    if not hit_any:
        print("  未命中任何已知界面（资源尚未标定，属预期）")

    # 可视化
    vis = img
    if args.ocr:
        items = ctx.ocr.read(img)
        print("-" * 68)
        print(f"OCR 共识别 {len(items)} 段文本：")
        for it in items:
            print(f"  {it.score:.2f}  {it.text}")
        vis = draw_ocr(vis, items)

    if args.templates:
        from src.vision.matcher import MatchResult
        results = []
        for name in ctx.matcher.available():
            hit = ctx.matcher.match_best(img, name)
            if hit:
                results.append(hit)
        if results:
            print("-" * 68)
            print("模板命中：")
            for r in results:
                print(f"  {r}")
            vis = draw_matches(vis, results)

    if args.save_vis:
        out = Path(args.save_vis)
        save(vis, out)
        print("已保存可视化结果:", out)
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    """只观察不点击：实时报告识别到的界面（标定阶段首选）。"""
    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)
    ctx = build_ctx(cfg, log)
    ctx.log.info("进入 observe 模式：只识别、不点击。按 Ctrl+C 退出。")
    engine = Engine(ctx, dry_run=True,
                    max_rounds=args.rounds,
                    stall_limit=int(cfg.get("timing.max_idle_rounds", 40)))
    try:
        result = engine.run()
    except KeyboardInterrupt:
        result = "interrupted"
    print("\n观察结束:", result, engine.stats)
    return 0


def cmd_enter(args: argparse.Namespace) -> int:
    """导航到「千里单骑」入口页 —— 纯固定坐标，前进 2 次点击 / 回退 2 次点击。

    默认路径：主界面 点「战役」→ 点「千里单骑」→ 到达入口页。
    不做识别，因此用 --from 声明起点；声明与实际不符时点击会落空。
    """
    from src.game.nav import chain_of, navigate

    cfg = Config.load()
    if args.ui:
        cfg.settings.setdefault("decision", {})["ui"] = args.ui
    log = setup_logger("mjs", cfg.log_dir)
    ctx = build_ctx(cfg, log)

    if not ctx.device.is_app_foreground(GAME_PACKAGE):
        log.warning("当前前台不是名将杀（%s），尝试拉起",
                    ctx.device.current_package() or "未知")
        ctx.device.launch_app(GAME_PACKAGE)
        time.sleep(8)

    log.info("导航: %s → %s（固定坐标）", args.frm, args.target)
    t0 = time.time()
    ok = navigate(ctx, target=args.target, frm=args.frm)
    log.info("导航耗时 %.1f 秒", time.time() - t0)

    # 保存到达后的画面（标定依据 + 事后核对是否真的到位）
    try:
        img = ctx.device.screenshot()
        save(img, Path(cfg.shot_dir) / f"enter_{args.target}.png")
    except Exception as exc:  # noqa: BLE001
        log.debug("落点截图保存失败: %s", exc)

    print("\n导航结果:", "成功 ✅" if ok else "失败 ❌",
          "（耗时 %.1fs）" % (time.time() - t0))
    print("可用页面:", ", ".join(chain_of(cfg)))
    return 0 if ok else 1


def cmd_hero(args: argparse.Namespace) -> int:
    """通用武将选择：搜索 → 定位 → 点选 → 校验 → 退出。

    不写死任何武将，换武将只改 --name。
    """
    from src.game.hero import select_hero

    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)
    ctx = build_ctx(cfg, log)

    if not ctx.device.is_app_foreground(GAME_PACKAGE):
        log.warning("当前前台不是名将杀（%s）", ctx.device.current_package() or "未知")

    t0 = time.time()
    ok = select_hero(ctx, name=args.name, keyword=args.keyword,
                     verify=not args.no_verify)
    log.info("选将总耗时 %.1f 秒", time.time() - t0)

    print("\n选将结果:", "成功 ✅" if ok else "失败 ❌",
          "（%s，耗时 %.1fs）" % (args.name, time.time() - t0))
    return 0 if ok else 1


def cmd_nodes(args: argparse.Namespace) -> int:
    """识别局内地图页的节点列表与类型（战斗/商店/事件/休息/武将/伙伴）。

    不点击任何东西。可用 --tap N 点击第 N 个节点（决策点，需显式指定）。
    """
    from src.game.node_icon import (NODE_LABELS, analyze_nodes, draw_nodes,
                                    load_node_templates)

    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)

    if args.image:
        img = read_image(args.image)
        src = args.image
        ctx = None
    else:
        ctx = build_ctx(cfg, log)
        if not ctx.device.is_app_foreground(GAME_PACKAGE):
            log.warning("当前前台不是名将杀（%s）", ctx.device.current_package() or "未知")
        img = ctx.device.screenshot()
        src = "(实时截图)"

    tpl_dir = Path(cfg.templates_dir) / "run_map"
    tpls = load_node_templates(tpl_dir)
    print(f"图像: {src}  {img.shape[1]}x{img.shape[0]}")
    print(f"节点模板: {', '.join(tpls) if tpls else '(无)'}  (目录 {tpl_dir})")
    print(f"范围: {'全部检出圆（--all，含已通关/假圆）' if args.all else '仅当前层节点'}")
    print("-" * 68)

    dropped: list = []

    nodes = analyze_nodes(img, templates=tpls, threshold=args.threshold,
                          only_current_layer=not args.all, dropped_out=dropped)
    if dropped:
        print(f"（已剔除 {len(dropped)} 个非当前层的圆: "
              + "  ".join(f"({x},{y})" for x, y, _ in dropped) + "）")
    if not nodes:
        print("  未检测到节点圆（可能不在局内地图页）")
    for n in nodes:
        others = "  ".join(f"{k}={s:.3f}" for k, s in n.scores[:4])
        print(f"  {n}\n      各类型分数: {others}")

    out = Path(args.save_vis) if args.save_vis else Path(cfg.shot_dir) / "nodes_vis.png"
    save(draw_nodes(img, nodes), out)
    print("-" * 68)
    print(f"节点数 {len(nodes)}；可视化已存: {out}")

    if args.tap:
        idx = int(args.tap)
        hit = next((n for n in nodes if n.index == idx), None)
        if hit is None:
            print(f"❌ 没有第 {idx} 个节点")
            return 1
        print(f"点击节点 {hit}  →  {hit.tap}")
        if args.image or ctx is None:
            print("（离线图，未真的点击）")
            return 0
        ctx.device.tap(*hit.tap)
        time.sleep(2.5)
        save(ctx.device.screenshot(), Path(cfg.shot_dir) / f"node{idx}_after.png")
        print("已点击并截图 node%d_after.png" % idx)
    print("类型说明:", ", ".join(f"{k}={v}" for k, v in NODE_LABELS.items()))
    return 0 if nodes else 2


def cmd_gift(args: argparse.Namespace) -> int:
    """赠礼决策：一级选接受谁的赠礼，二级选具体赠礼类型。

    判别依据是**赠礼武将**（规则见 ``src/game/gift.py`` 模块头注释）。
    默认只打印建议、不点击；加 ``--tap`` 才真的点。
    """
    from src.game.gift import (classify_hero, detect_gift_heroes,
                               detect_gift_options, pick_gift_hero,
                               pick_gift_options, rank_gift_types)

    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)

    def _split(s: str) -> list:
        return [v.strip() for v in s.replace("，", ",").split(",") if v.strip()]

    heroes = _split(args.heroes)
    options = _split(args.options)
    hero = args.hero
    ctx = None

    if not heroes or (not options and not hero):
        ocr = OCREngine(
            engine=cfg.get("ocr.engine", "rapidocr"),
            min_score=float(cfg.get("ocr.min_score", 0.5)),
            normalize=bool(cfg.get("ocr.normalize", True)),
            logger=log,
        )
        if args.image:
            img = read_image(args.image)
            src = args.image
        else:
            ctx = build_ctx(cfg, log)
            img = ctx.device.screenshot()
            src = "(实时截图)"
        if img is None:
            print("❌ 读取截图失败:", args.image)
            return 1
        items = ocr.read(img)
    else:
        img, items, src = None, [], "(由参数直接给出)"

    print(f"图像: {src}")
    print("=" * 70)

    idx = None
    if not heroes and hero:
        # 二级界面：顶层大标题是「<字>赠礼」，武将名需由调用方（或上一级）给出
        heroes = [hero]
        hits, tap1 = [], None
    elif not heroes:
        hits = detect_gift_heroes(items)
        if not hits:
            print("  未识别到「XX赠礼」武将标签（可能不在赠礼界面）")
            return 2
        heroes = [h for h, _ in hits]
        tap1 = hits[0][1]
        print("一级候选:", "  ".join(f"{h}@{p}" for h, p in hits))
    else:
        hits, tap1 = [], None

    idx, why = pick_gift_hero(heroes)
    if idx is None:
        print("❌ 无法判定一级选择")
        return 2
    print(f"  一级 → 选第 {idx + 1} 个「{heroes[idx]}」")
    print(f"        理由: {why}")
    if hits:
        print(f"        点击坐标: {hits[idx][1]}")

    if options:
        j, why2 = pick_gift_options(options, heroes[idx])
        print(f"  二级候选（赠礼武将={heroes[idx]}，优先级 "
              f"{' > '.join(rank_gift_types(heroes[idx]))}）")
        print(f"  二级 → 选第 {j + 1} 个「{options[j]}」")
        print(f"        理由: {why2}")
    elif items:
        opts = detect_gift_options(items)
        if opts:
            names = [o for o, _ in opts]
            j, why2 = pick_gift_options(names, heroes[idx])
            print("  二级候选:", "  ".join(f"{o}@{p}" for o, p in opts))
            print(f"  二级 → 选第 {j + 1} 个「{names[j]}」")
            print(f"        理由: {why2}")
            print(f"        点击坐标: {opts[j][1]}")
            options, tap1 = names, opts[j][1]

    print("-" * 70)
    print("  赠礼武将分类:", ", ".join(
        f"{h}={classify_hero(h) or '三类之外'}" for h in heroes))
    if not args.tap:
        print("  （只给建议，未点击；加 --tap 才会真的点）")
        return 0
    if ctx is None:
        ctx = build_ctx(cfg, log)
    if not options:
        print("  ⚠ 二级选项未知，只点一级将会进入二级界面")
    ctx.device.tap(*tap1)
    print(f"  已点击 {tap1}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    """打开自动化控制台 GUI。

    注意（2026-11-13）：默认入口 `启动控制台.vbs` 用 **pythonw.exe** 启动，
    没有控制台，stdout/stderr 是丢弃的。所以这里的异常必须**落盘 + 弹窗**，
    否则用户只会看到"双击了没反应"。
    """
    try:
        from src.gui.app import main as gui_main
        gui_main()
        return 0
    except Exception:  # noqa: BLE001 — 兜底：无控制台时也要让用户看见错误
        import traceback
        from pathlib import Path

        detail = traceback.format_exc()
        log_path = Path("runtime/gui_error.log")
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(detail + "\n")
        except OSError:
            log_path = None
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "控制台启动失败",
                f"{detail.strip().splitlines()[-1]}\n\n"
                f"完整报错已写入：{log_path}")
            root.destroy()
        except Exception:  # noqa: BLE001 — 连弹窗都失败时至少已落盘
            pass
        return 1


def cmd_auto(args: argparse.Namespace) -> int:
    """串联执行器：千里入口页 → 选将 → 循环推层 → 结算领奖。

    前提：游戏已停在千里单骑入口页（登录/进战役请用 run.py enter --target qianli）。
    """
    from src.game.runner import run_auto

    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)
    ctx = build_ctx(cfg, log)
    if not ctx.device.is_app_foreground(GAME_PACKAGE):
        log.warning("当前前台不是名将杀（%s）", ctx.device.current_package() or "未知")
    return run_auto(ctx, log, hero_name=args.hero,
                    max_steps=args.max_steps, poll_sleep=args.poll)


def cmd_run(args: argparse.Namespace) -> int:
    """实际执行单局自动化。"""
    cfg = Config.load()
    if args.ui:
        cfg.settings.setdefault("decision", {})["ui"] = args.ui
    if args.mode:
        cfg.settings.setdefault("decision", {})["mode"] = args.mode
    log = setup_logger("mjs", cfg.log_dir)
    ctx = build_ctx(cfg, log)

    # 前台检查
    if not ctx.device.is_app_foreground(GAME_PACKAGE):
        log.warning("当前前台不是名将杀（%s）。请先手动进入游戏并走到「千里单骑」内。",
                    ctx.device.current_package() or "未知")

    engine = Engine(ctx, dry_run=args.dry_run,
                    max_rounds=args.rounds,
                    stall_limit=int(cfg.get("timing.max_idle_rounds", 40)))
    try:
        result = engine.run()
    except KeyboardInterrupt:
        result = "interrupted"
    print("\n运行结束:", result)
    print("统计:", engine.stats)
    print("日志目录:", cfg.log_dir)
    return 0


# ===========================================================================
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="名将杀·千里走单骑 自动化脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selfcheck", help="环境与设备自检")

    c = sub.add_parser("capture", help="采集截图（标定用）")
    c.add_argument("--tag", default="shot")
    c.add_argument("--count", type=int, default=1)
    c.add_argument("--interval", type=float, default=1.5)
    c.add_argument("--grid", action="store_true")
    c.add_argument("--step", type=int, default=100)
    c.add_argument("--out", default="")

    a = sub.add_parser("analyze", help="对已保存截图做离线识别")
    a.add_argument("--image", required=True)
    a.add_argument("--ocr", action="store_true", help="同时输出全部 OCR 文本")
    a.add_argument("--templates", action="store_true", help="跑一遍全部模板匹配")
    a.add_argument("--save-vis", default="", help="保存可视化结果到该路径")

    o = sub.add_parser("observe", help="只观察不点击（dry-run）")
    o.add_argument("--rounds", type=int, default=60)

    e = sub.add_parser("enter", help="固定坐标导航（主页→战役→千里单骑，或反向）")
    e.add_argument("--target", default="qianli",
                   choices=["home", "campaign", "qianli"],
                   help="目标页面：home=主界面，campaign=战役页，qianli=千里单骑入口页(默认)")
    e.add_argument("--from", dest="frm", default="home",
                   choices=["home", "campaign", "qianli"],
                   help="起点页面(默认 home)。纯坐标方案不识别界面，"
                        "声明与实际不符时点击会落空")
    e.add_argument("--ui", choices=["cli", "dialog"], default="")

    h = sub.add_parser("hero", help="选择武将（通用搜索选将，支持任意武将）")
    h.add_argument("--name", required=True, help="武将名，如 钟离眜")
    h.add_argument("--keyword", default="",
                   help="搜索关键词（默认取名字前 2 字），用于规避异体字差异")
    h.add_argument("--no-verify", action="store_true", help="跳过选择结果校验")

    n = sub.add_parser("nodes", help="识别局内地图页节点与类型（不点击）")
    n.add_argument("--image", default="", help="离线识别该截图；省略则实时截图")
    n.add_argument("--threshold", type=float, default=0.70, help="类型判定阈值")
    n.add_argument("--save-vis", default="", help="可视化输出路径")
    n.add_argument("--tap", type=int, default=0, help="点击第 N 个节点（决策点，需显式指定）")
    n.add_argument("--all", action="store_true",
                   help="不筛当前层，输出全部检出圆（含已通关节点/飘浮精灵，排错用）")

    g = sub.add_parser("gift", help="赠礼决策（一级选武将 / 二级选赠礼类型），默认不点击")
    g.add_argument("--image", default="", help="离线识别该截图；省略则实时截图")
    g.add_argument("--heroes", default="", help="直接给一级候选武将，逗号分隔（跳过 OCR）")
    g.add_argument("--options", default="", help="直接给二级候选赠礼，逗号分隔（跳过 OCR）")
    g.add_argument("--hero", default="", help="直接指定赠礼武将名（配合 --options，跳过 OCR）")
    g.add_argument("--tap", action="store_true", help="按结论真的点击（默认只给建议）")

    r = sub.add_parser("run", help="执行单局自动化")
    r.add_argument("--rounds", type=int, default=400)
    r.add_argument("--dry-run", action="store_true", help="只识别不点击")
    r.add_argument("--ui", choices=["cli", "dialog"], default="")
    r.add_argument("--mode", choices=["ask", "auto", "hybrid"], default="")

    a = sub.add_parser("auto", help="串联执行器：从千里入口页一键跑完整局")
    a.add_argument("--hero", default="吕布", help="出战武将名（搜索式选将）")
    a.add_argument("--max-steps", type=int, default=2000, help="状态机最大步数")
    a.add_argument("--poll", type=float, default=0.5, help="托管等待轮询间隔（秒，快路径下 0.5 足够）")

    g = sub.add_parser("gui", help="打开自动化控制台（GUI）")

    args = p.parse_args(argv)
    handler = {
        "selfcheck": cmd_selfcheck,
        "capture": cmd_capture,
        "analyze": cmd_analyze,
        "observe": cmd_observe,
        "enter": cmd_enter,
        "hero": cmd_hero,
        "nodes": cmd_nodes,
        "gift": cmd_gift,
        "run": cmd_run,
        "auto": cmd_auto,
        "gui": cmd_gui,
    }[args.cmd]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
