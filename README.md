# 名将杀 · 千里单骑 自动化脚本

**怎么用（三步）**：装好雷电模拟器、把《名将杀》停在「千里单骑」入口页（模拟器分辨率必须是 **1920×1080 / DPI 280**，否则点击会偏）→ 双击 `启动控制台.bat` 打开控制台（首次自动生成无黑窗启动器 `启动控制台.exe`，之后可直接双击它，全程没有黑窗口）（首次使用先按 `部署文档.md` 装好 `.venv`）→ 点「▶ 启动」；之后选难度、选将、走地图、战斗托管、商店/事件、结算、任务巡检全部自动完成，一局接一局直到你点「■ 停止」。改完配置要「先停止再启动」才生效；挂机期间把 Windows 电源计划设成「从不睡眠」（电脑睡眠会让模拟器时钟错乱、adb 失联）。

面向**个人使用**的雷电模拟器自动化工具：ADB 截屏 + 模板锚点 + OCR 识别，
自动完成《名将杀》「千里单骑」玩法从进局到结算的完整循环（默认多局连跑）。
策略决策规则全部来自用户口述并沉淀在文档与测试里，**绝不臆断**。

> ⚠️ 仅用于个人账号的日常重复操作减负，请勿商用或多开刷号。

---

## 1. 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 语言 | Python 3.12（单一 `.venv`） | 测试 / GUI / 打包全用它 |
| 设备通信 | ADB（`exec-out screencap` raw 协议） | 截图 ~0.45s/帧，PNG 兜底 |
| 页面识别 | OpenCV 模板匹配（锚点表 YAML） | 每帧 ~48ms 扫全表，先于 OCR |
| 文字识别 | RapidOCR（onnxruntime） | **GPU(DirectML)/CPU 可切换**，整屏 250ms/864ms |
| 决策引擎 | 状态机（`classify` → `_act_*`） | 每步一个状态一个动作，可单测 |
| GUI | tkinter（卡片式浅色主题） | 配置/启动暂停/指标卡/分级日志 |
| 打包 | PyInstaller onedir（已停用） | 曾用于构建未加密绿色版；2026-11-13 起改为纯源码开发，不再打包 |
| 测试 | unittest，**291 项离线** | 不依赖模拟器：纯逻辑合成数据 + 真实截图夹具 |

## 2. 全链路实现（一帧的旅程）

```
ADB raw 截图 (450ms)
   ↓
① 锚点表判页（assets/screen_info/anchors.yml，15 条目，~50ms）
   │  区域模板匹配，多区域 AND；命中 → 免整屏 OCR
   ↓ 未命中
② 整屏 OCR（GPU 250ms / CPU 864ms）→ 关键词白名单分类
   │  ⚠ 只放已标定关键词；泛关键词宁可不识别也不误判
   ↓
③ 状态机分发（runner.step → state）
   ├─ map            霍夫圆定位节点 + 节点图标模板 → 按优先级选节点
   ├─ battle_confirm 开战序列（开始对局 → 换牌取消）
   ├─ battle         托管两连击 → 快路径轮询（结算锚点优先/投降仍在=继续打）
   ├─ shop           货架解析（价格-名字同列配对）→ 想要清单决策 → 分专区保线
   ├─ gift1/gift2    赠礼两级决策（类别优先；同类别按名单顺序；无类别→中间）
   ├─ rest/event/…   事件页白名单关键词 → 固定策略
   ├─ 结算链          完胜空白 → 下一步 → 确定 → 领取奖励 → 恭喜获得
   └─ unknown        过渡帧主动探测（锚点命中即提前结束等待，12 次兜底停机）
   ↓
④ 动作：固定坐标点击（能写死就不识别）/ 模板定位点击
   ↓
⑤ 等待收口：就绪探测（锚点/节点消失）× 超时兜底，绝不瞎点
```

**健壮性设计**（每个都来自真实事故）：

- **adb 自愈**：截图连续失败 → 重启 adb 服务 → 用真实截图验证恢复；
  10 分钟等待窗口，恢复后从当前界面接上（根因：主机睡眠毁模拟器时钟）
- **托管轮询双支判定**：先查结算锚点（完胜浮层下投降仍可见的坑），再看投降
- **热重载后重应用名单**：worker reload 会重置模块级清单 → 重载后重新 apply
- **配置路径冻结感知**：gui.json 跟 exe 目录走，换目录启动不丢名单
- **决策留证**：赠礼/商店每次存截图 + 打印候选与理由，争议可回查

## 3. 目录结构

```
run.py               CLI 入口（selfcheck/enter/hero/nodes/auto/gui）
mjs_gui.py           GUI 打包入口
src/gui/             控制台（app.py 控制器 + widgets.py 渲染 + config_store）
src/game/            业务状态机（runner/nav/shop/gift/rest/task_page/...）
src/vision/          OCR 引擎（设备切换）/ 模板匹配 / 截图标注
src/devices/         ADB 设备层（raw 截图 / 自愈 recover）
src/core/            日志 / 重试 / 通用件
assets/
  screen_info/anchors.yml   锚点表（tools/_make_anchor_table.py 生成+交叉验证）
  templates/                anchors/ run_map/ task/ settle/ popup/ 真实界面裁剪
config/              coords.yaml（标定坐标）/ settings.yaml / gui.json
docs/                01-08 全套设计与规则文档
tests/               291 项离线测试 + 真实截图夹具
tools/               标定工具（probe_anchors/snap/grid_crop...）
```

## 4. 快速开始

- **日常使用**：双击 `启动控制台.exe`（首次先双击 `启动控制台.bat` 生成）→ 配置名单/优先级 → **保存配置** → ▶ 启动
- **首次部署**：见 `部署文档.md`（Python 3.11 → `.venv` → `pip install -r requirements.txt` → `run.py selfcheck` → 跑一遍测试）
- **命令行**：`.venv\Scripts\python.exe run.py auto`（全自动跑）/ `gui`（控制台）/ `selfcheck`（体检）
- 挂机注意：Windows 电源计划设「从不睡眠」（睡眠会毁模拟器时钟）

## 5. 识别资产的维护（游戏更新后）

1. `tools/probe_anchors.py <截图>` —— 逐条锚点打分，一眼定位失配项
2. `tools/snap.py <名字>` —— 抓帧存夹具 + OCR 打印按钮精确坐标
3. 重裁模板 → `tools/_make_anchor_table.py` 重新生成并**交叉验证 48 张夹具**
4. 全量测试 → `tools/_rebuild_plain.py` 重建（会自动关闭运行中的程序）

历史教训全部沉淀在 `AGENTS.md`（交付标准）与 `docs/`（设计文档）；
改动前先读，改完必须留下测试。
