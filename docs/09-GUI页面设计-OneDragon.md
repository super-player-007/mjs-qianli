# 09 · OneDragon 页面设计学习笔记

> 学习对象：`OneDragon-Anything/ZenlessZoneZero-OneDragon`
> 关注点：**页面怎么排、卡片怎么拆、控件怎么和配置绑定、反馈怎么做**。
> 目的：把这套"页面设计语言"翻译成我们 Tkinter 控制台能用的东西。
> 参考源码：
> - 页面骨架：`one_dragon_qt/widgets/vertical_scroll_interface.py`、
>   `pivot_navi_interface.py`、`view/app_run_interface.py`
> - 卡片系统：`one_dragon_qt/widgets/setting_card/*`
> - 运行卡片：`one_dragon_qt/widgets/setting_card/app_run_card.py`
> - 设置页实例：`one_dragon_qt/view/setting/setting_custom_interface.py`
> - 一条龙页：`zzz_od/gui/view/one_dragon/zzz_one_dragon_interface.py`

---

## 一、页面只有三种骨架

| 骨架 | 类 | 结构 | 用在哪 |
|---|---|---|---|
| **滚动页** | `VerticalScrollInterface` | 顶部固定区（可选）+ 纵向滚动内容 | 绝大多数页面（设置、说明、资源） |
| **分栏页** | `SplitAppRunInterface` | 左：可滚动自定义内容；右：运行区（状态+按钮+日志） | 一条龙/助手页：左配置右运行 |
| **二级导航页** | `PivotNavigatorInterface` | 内部再分多个子页 + 返回按钮（`enable_page_stack=True`） | 一条龙（运行/体力计划/预设队伍/灵敏度）、实例设置 |

**滚动页的构建细节**（值得抄）：
- 布局**惰性构建**：第一次 `on_interface_shown()` 才 `_init_layout()`，启动不付代价；
- 边距规则统一：外边距 `(0, 11, 0, 0)`、滚动内容左右 11、内容末尾留 11 空白当视觉边距；
- `get_content_widget()` 由子类实现（返回内容容器），`get_fixed_top_widget()` 可选返回"不滚动的顶部条"。

---

## 二、内容 = 纵向卡片流（Column）

```python
def get_content_widget(self) -> QWidget:
    content_widget = Column(self)
    content_widget.add_widget(HelpCard(title='设置说明', content='...'))
    content_widget.add_widget(self._init_basic_group())   # 一个分组
    content_widget.add_stretch(1)
    return content_widget
```

`Column` 只做三件事：`add_widget` / `add_stretch` / 统一边距。**页面代码读起来就是
"一列卡片"**，没有一行一行摆控件的坐标。

分组用 `SettingCardGroup('外观')`，组内 `addSettingCard(...)` 顺序排列。

---

## 三、卡片系统：一个控件一种卡

`SettingCardBase` 的规格（**这就是他们的视觉基准**）：

| 属性 | 值 |
|---|---|
| 行高 | **固定 50px** |
| 图标 | 16×16，左边距 16 |
| 文本 | 两行：`title`（主）+ `content`（灰字说明，可空） |
| 内容溢出 | `elidedText` 省略号 + `tooltip` 显示全文（`content` 最大宽 500） |
| 右侧 | `addStretch(1)` 之后挂控件（开关/下拉/按钮组） |

现成的卡片种类（`widgets/setting_card/` 24 个文件）：`switch / check_box /
combo_box / editable_combo_box / multi_selection_combo_box / spin_box / slider /
text / key_value / key(按键录制) / password_switch / help / common_download /
multi_push(一排按钮) / push / app_run(运行卡) / yaml_config_adapter`。

**一个控件一个类的收益**：设置页代码只剩"选卡片 + 绑定配置"，样式/交互/校验都封在卡片里。

---

## 四、数据绑定：`init_with_adapter(配置属性适配器)`

```python
def on_interface_shown(self):
    VerticalScrollInterface.on_interface_shown(self)
    self.theme_opt.init_with_adapter(self.ctx.custom_config.get_prop_adapter('theme'))
    self.ui_language_opt.init_with_adapter(
        self.ctx.custom_config.get_prop_adapter('ui_language'))
```

- **配置对象暴露 `get_prop_adapter(字段)`**（值/设置/类型/合法性 都封在适配器里）；
- 卡片拿到适配器后**双向绑定**：显示时读配置填控件，改动后写回配置；
- 页面不需要手写 `if value == ...` 的回显逻辑，也不会漏同步；
- 页面**显示时才绑定**（`on_interface_shown`），隐藏时不占资源、不误刷。

---

## 五、运行卡片：一行装下"状态 + 上次运行 + 4 个操作"

`AppRunCard`（可拖拽排序）一行 = 

```
[图标] 应用名                              [⚙] [⋯] [▶] [开关]
       上次运行 2026-11-13 17:20  ✅
```

- 状态用**图标颜色**表达：成功=蓝勾、运行中=转圈、失败=红叹号、未跑=灰信息；
- 高频动作直接给按钮（运行/开关），低频进 `⋯` 菜单（通知设置/移到顶部）；
- 整卡可拖拽调顺序，另外提供"移到顶部"菜单项兜底（拖拽在滚动区不好用时）；
- `setDisabled()` 一次性禁用卡内全部交互 —— 跑图时整页锁住的实现就靠这个。

---

## 六、反馈层：三种提示，各有分工

| 组件 | 形态 | 用途 |
|---|---|---|
| `InfoBar` | 右上角自动消失的浮动条 | 操作结果（已开启/已加入队列/错误） |
| `TeachingTip` | 指向某个控件的引导气泡 | 首次引导（"点击这里查看进度"） |
| `HelpCard` | 页内说明卡 | 整页的使用说明，常驻 |

另外两个设计点：
- **危险/高级开关加密码保护**：`PasswordSwitchSettingCard`（自定义主题色、自定义背景），
  防误触但不藏功能；
- **长任务给进度**：下载队列是窗口级服务 + 标题栏计数 + 详情弹窗，页面不各自造进度条。

---

## 七、布局常量（照抄即可）

| 项 | 值 |
|---|---|
| 主窗口 | 1140 × 760（3:2） |
| 页面外边距 | 上 11 / 左右 11 / 下 0（内容末尾补 11） |
| 卡片高度 | 50 |
| 卡片图标 | 16×16，左边距 16 |
| 卡片间距 | 0（靠卡片自身内边距分隔）+ 组间 spacing |

---

## 八、翻译到我们的 Tkinter 控制台

我们没有 Qt，但**设计语言完全可搬**。建议一屏布局（单窗口 1100×720）：

```
┌───────────────────────────────────────────────────────────────┐
│ 状态条：● 运行中 · 第 3/20 局 · 本局 4:12 · 总 18:40   [开始][暂停][停止] │
├───────────────────────┬───────────────────────────────────────┤
│ 配置卡片列（滚动）     │ 日志区（等宽、自动滚动、级别过滤）      │
│ ┌───────────────────┐ │ ┌───────────────────────────────────┐ │
│ │ 英雄        吕布 ▾ │ │ 17:20:31 [INFO] step=12 state=map  │ │
│ │ 点击间隔    0.53   │ │ 17:20:32 [INFO] 第3层 节点=#3 战斗  │ │
│ │ 轮次        20     │ │ ...                                │ │
│ │ 节点优先级  编辑…  │ │                                    │ │
│ │ 商店名单    编辑…  │ │                                    │ │
│ │ 取帧方式    adb ▾  │ │                                    │ │
│ └───────────────────┘ │ └───────────────────────────────────┘ │
│ ┌─ 统计 ────────────┐ │ [☐ 自动滚动] [级别: 全部▾] [清屏] [导出]│
│ │ 局数 3 · 战斗 9 ·  │ │                                       │
│ │ 胜 2 · 耗时 18:40  │ │                                       │
│ └───────────────────┘ │                                       │
├───────────────────────┴───────────────────────────────────────┤
│ 进度条：████████░░░░░░░░ 35%   提示：任务巡检中…               │
└───────────────────────────────────────────────────────────────┘
```

落点建议（纯 GUI 改造，不碰业务）：

| 学到的 | Tkinter 实现 |
|---|---|
| `BaseInterface` 契约 | `src/gui/page.py::PageBase`（objectName / nav_text / on_shown / on_hidden / toast） |
| `VerticalScrollInterface` 惰性布局 | `ScrollFrame`：首次 `on_shown` 才 `build()`，内部 `Canvas + Frame` 滚动 |
| `Column` 卡片流 | `CardColumn`：`add(card)` / `stretch()` |
| `SettingCardBase` 50px 两行规格 | `SettingRow`：固定高 50、标题 12px、说明 10px 灰、右侧控件位、内容超长省略+tooltip |
| 卡片种类 | `SwitchRow / ComboRow / SpinRow / TextRow / ButtonRow / HelpCard` |
| `init_with_adapter` 绑定 | `SettingRow.bind(cfg_key)`：`on_shown` 读 `config_store`，控件变更写回并存盘 |
| `InfoBar` | 状态条右侧临时文字 + 3 秒淡出（`after`） |
| `TeachingTip` | 首次启动气泡（`Toplevel` 无边框小窗，指向控件） |
| `HelpCard` | 页面顶部说明卡（灰色小字） |
| `PasswordSwitch` / 二次确认 | 危险按钮 `askyesno` 确认 |
| 运行卡片的状态图标 | 状态条 ● 颜色：绿=运行/黄=暂停/红=错误/灰=空闲 |

**不学的部分**：Fluent 主题与 Mica 效果、多语言 `gt()` 体系、卡片拖拽排序（我们配置项
少，固定顺序更简单）、折叠展开组（`ExpandSettingCardGroup`）。

---

## 九、三条设计原则（比代码更重要）

1. **页面只描述内容，不描述坐标**：一列卡片 + 分组，滚动交给容器；换分辨率不会崩。
2. **一行一个配置，行高固定**：视觉节奏统一，加配置项不破坏布局。
3. **配置与控件双向绑定，绑定发生在"页面显示时"**：既不手写回显，也不在隐藏页上白跑刷新。

---

## 十、落地记录（2026-11-13，只改前端）

按"后端优先"原则落地了 5 项，**后端（settings.yaml / Config / runner / 识别）一行未改**：

| 项 | 落点 | 说明 |
|---|---|---|
| 卡片式设置（表驱动） | `src/gui/cards.py`：`SettingRow` / `NamesBlock` / `PriorityBlock` / `section` | 行高 52px，标题+灰说明+右侧控件；6 个配置行 + 3 个名单块 + 优先级列表 |
| 日志工具条 | `src/gui/app.py::_build_log_panel` | 级别过滤（全部/警告及以上/仅错误，纯函数 `filter_log_lines`）、自动滚动开关、清屏、导出 |
| 轻提示 | `app.toast()` | 状态条右侧 2.6 秒淡出，替代弹窗（保存/停止/导出/清屏） |
| 二次确认 | `on_stop` | 运行中停止需确认 |
| 卡片内小按钮样式 | `theme.py::CardGhost.TButton` | 修截图验收时发现的"白卡上的灰方块"问题 |

未做（后端没有对应数据/业务）：运行卡片列表、下载队列、主题/多语言、密码开关、
Pivot 二级导航、`PageBase` 抽象（单页控制台，等真拆第二页再说）。

验证：全量 `311` 项测试仅剩历史遗留 `test_ambush` 断言；真实建窗冒烟（配置读写回路、
优先级上移、日志过滤、toast、自动滚动）+ 截图验收通过。
