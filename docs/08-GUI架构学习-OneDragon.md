# 08 · OneDragon GUI 构造方法学习笔记

> 学习对象：`OneDragon-Anything/ZenlessZoneZero-OneDragon`（绝区零一条龙）
> 目的：理解它 **GUI 是怎么"搭"出来的**，判断哪些结构值得搬到本项目的
> Tkinter 控制台（**不引入 Qt**）。
> 参考源码（2026-11 主干）：
> - `src/one_dragon/`（框架核心，无 Qt）
> - `src/one_dragon_qt/`（可复用 Qt GUI 框架）
> - `src/zzz_od/gui/`（具体游戏应用的界面装配）

---

## 一、三层分区：核心 / GUI 框架 / 应用装配

| 层 | 目录 | 职责 | 依赖方向 |
|---|---|---|---|
| 核心 | `src/one_dragon/` | context（配置、事件总线）、operation（应用状态机）、visual（OCR/模板）、envs | 不依赖 GUI |
| GUI 框架 | `src/one_dragon_qt/` | 窗口基类、界面基类、通用控件、服务层、样式 | 只依赖核心 |
| 应用装配 | `src/zzz_od/`（`gui/app.py` + `gui/view/*`） | 用框架拼出"主页/一条龙/设置/资源"等页面 | 依赖上面两层 |

**要点**：GUI 框架层是**独立可复用**的（连 README 都只有 95B），游戏应用只写
"装配 + 具体页面"，不重复造窗口/导航/日志卡。

本项目对应：`src/core`（配置/日志）→ `src/vision|devices` → `src/game` →
`src/gui`。层级方向一致，但我们的 `src/gui` 目前**只有 app.py 控制器 +
widgets.py 渲染**，没有"界面单元"抽象。

---

## 二、窗口构造链：四层继承，每层只加一件事

```
PhosWindow            (one_dragon_qt/windows/window.py)
  └ AppWindowBase     (自定义标题栏 + 导航栏 + StackedWidget + 启动图)
      └ MainAppWindowBase  (注入 ctx、服务层、事件→信号桥、返回按钮)
          └ AppWindow      (zzz_od/gui/app.py 里，注册具体页面)
```

### AppWindowBase：**固定的装配顺序**（这段最值得抄）

```python
def __init__(...):
    PhosWindow.__init__(self, parent=parent)   # 1. 造窗壳（标题栏/导航/堆栈）
    self.setWindowTitle(win_title)             # 2. 标题、图标
    self.splashScreen = SplashScreen(...)      # 3. 先盖启动图
    self.init_window()                         # 4. 尺寸/居中等"外观"钩子
    self.show()                                # 5. **先显示窗口**（再建页面）
    self.stackedWidget.beforeCurrentChanged.connect(self._on_before_interface_changed)
    self.stackedWidget.currentChanged.connect(self.init_interface_on_shown)
    self.create_sub_interface()                # 6. 子类在这里注册页面
    self.splashScreen.finish()                 # 7. 关启动图
```

三个关键点：
1. **先 show 再建页面**：用户立刻看到窗口，页面构建慢也不黑屏。
2. **导航与页面解耦**：`add_sub_interface(interface)` 从 interface 自己身上取
   `nav_icon/nav_text/objectName` 去建导航按钮——页面不用知道导航栏存在。
3. **切换生命周期钩子**：`beforeCurrentChanged` → 旧页 `on_interface_leave()`；
   `currentChanged` → 旧页 `on_interface_hidden()`、新页 `on_interface_shown()`。

### MainAppWindowBase：窗口 = 页面容器 + 服务宿主

- 持有 `ctx`（全局 context）；
- 持有 **服务对象**：`AppSettingManager`、`DownloadQueueService`、
  `ResourceUpdateCoordinator`（下载队列、资源检查都不在页面里）；
- **线程安全桥**：`ctx.listen_event(...)` 回调在后台线程 → 不直接改 UI，
  而是 `self.context_notify_signal.emit(...)` → 主线程槽函数弹 InfoBar；
- 导航栏"返回"按钮由窗口统一管理，二级页面状态变化通过
  `secondary_state_changed` 信号通知窗口。

### 应用层 AppWindow：只剩"注册表"

```python
def create_sub_interface(self):
    super().create_sub_interface()                  # 先加返回按钮等基础件
    self.home_interface = HomeInterface(self.ctx, parent=self)
    self.add_sub_interface(self.home_interface)     # 顶部导航
    ...
    self.add_sub_interface(LikeInterface(self.ctx, parent=self),
                           position=NavigationItemPosition.BOTTOM)  # 底部导航
    self.add_nav_widget(PipButton(self.ctx, parent=self))           # 自定义按钮
```

**页面全部惰性 import**（函数内 `from zzz_od.gui.view.home.home_interface import ...`），
避免启动即加载全部页面依赖。这一点和我们 `app.py` 里"对 run.py 的 import 放函数内"
是同一条经验。

---

## 三、界面单元契约：BaseInterface（最重要的抽象）

```python
class BaseInterface(QWidget):
    def __init__(self, object_name, nav_text_cn, nav_icon, parent=None):
        QWidget.__init__(self, parent=parent)
        self.nav_text = gt(nav_text_cn)   # 导航文字（i18n 入口）
        self.nav_icon = nav_icon
        self.setObjectName(object_name)   # 导航唯一键 + 样式选择器

    def on_interface_leave(self):  pass   # 切换前：恢复 margin/标题栏等视觉态
    def on_interface_shown(self):  pass   # 显示时：懒加载、订阅事件
    def on_interface_hidden(self): pass   # 隐藏时：退订事件、停刷新
    def show_info_bar(self, title, content, ...): ...  # 统一提示
```

**每个页面只回答三件事**：我叫什么（objectName）、我在导航上显示什么
（nav_text/nav_icon）、我显示/隐藏时要做什么（钩子）。窗口负责其余全部。

运行页 `AppRunInterface` 是这套契约的典型实现：
- 组合通用控件：状态文字 + 开始/停止按钮 + **日志卡 LogDisplayCard**；
- `AppRunner(QThread)` 跑 `ctx.run_context.run_application(app_id)`；
- 运行状态由 `run_context` 的状态机 + 事件总线（START/PAUSE/STOP/RESUME）
  驱动，UI 只订阅 `state_changed` 信号刷新按钮与文字；
- 页面隐藏时 `unlisten_all_event`，避免隐藏页继续吃事件。
- 还有 `SplitAppRunInterface` 左右分栏变体：左边自定义内容、右边复用运行区。

---

## 四、启动流程（main）

```python
app = QApplication(sys.argv)
_ctx = ZContext()                       # 只构造，不初始化
setTheme(...)
w = AppWindow(_ctx); w.show()           # 窗口先出来
CtxInitRunner(_ctx, w).start()          # 后台线程 ctx.init() → w.on_ctx_ready()
app.exec()                              # 事件循环
_ctx.after_app_shutdown()               # 统一收尾
```

- `ctx.init()`（加载配置、探测设备、下载资源）**在后台线程**，完成后回调
  `on_ctx_ready()` 再让 UI 扫描设置/检查更新；
- 版本检查、首次运行提示、资源更新全部挂在窗口的"启动后"定时任务里，
  不阻塞首帧。

---

## 五、可搬到本项目的 6 条（Tkinter 同样适用）

| # | 结构 | 我们的现状 | 建议 |
|---|---|---|---|
| 1 | **界面单元基类**（objectName + nav 文字/图标 + 三个生命周期钩子） | 无，`app.py` 一个类里堆全部控件 | 新增 `src/gui/page.py::PageBase`，把"运行页/设置页/日志页/开发页"拆成页面类 |
| 2 | **导航注册表**：页面自描述，窗口只 `add_page()` | 手写 grid/place 编排 | 用 `ttk.Notebook` 或自绘侧栏 + `add_page(page)` |
| 3 | **切换生命周期**：shown/hidden/leave 钩子 | 无（全靠轮询） | 页面显示时启动定时刷新、隐藏时 `after_cancel` 停掉 |
| 4 | **事件总线 → UI 队列**：后台线程只发事件，UI 线程消费 | 已有 `queue` + `after()` 轮询（方向对） | 补成 `CtxEventBus`：`emit(event)` → 队列 → 页面按需订阅 |
| 5 | **运行上下文状态机**：`run_context` 管 开始/暂停/继续/停止 + 状态文案 | `run_auto()` 线程 + 标志位分散在 app.py | 抽出 `RunContext`（状态枚举 + 事件 + `run_status_text`），按钮全部走状态机 |
| 6 | **服务层**：下载队列/主题/资源检查放在窗口级服务 | 无（无此需求） | 只在需要时再加；不要为"对齐架构"造空服务 |

**明确不搬**（与 `docs/07` 第三节结论一致）：Qt/qfluentwidgets 重写、Flunet 主题
体系、多语言 `gt()` 框架、插件市场、多账号/多实例。

---

## 六、如果要做，最小改造顺序（建议）

1. **抽 `PageBase` + 导航注册**（不动业务逻辑，纯 GUI 重组）：
   `src/gui/pages/run_page.py`（运行控制+日志+状态）、`settings_page.py`、
   `devtools_page.py`；`app.py` 只留窗口装配 + 启动/停止编排。
2. **抽 `RunContext`**：把 `_running/_paused/_stop_flag` 收进一个状态机，
   UI 只订阅变化；顺带给 CLI `run.py auto` 复用同一状态机。
3. **事件总线**：日志/状态/进度统一走 `CtxEventBus`，页面订阅自己关心的。
4. 每步都要**离线测试**（页面纯函数 + 状态机迁移），真机点一遍回归。

---

## 七、一句话总结

它 GUI 的核心不是 Qt，而是三件事：
**① 页面是有契约的单元（自描述 + 生命周期钩子）；
② 窗口只做装配与服务宿主；
③ 后台线程永远不摸控件，只发事件/信号。**
这三点用 Tkinter 一样能做，而且正是我们现在缺的。
