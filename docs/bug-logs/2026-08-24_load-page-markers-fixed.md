# Bug: 负载配给页标记固定死，新增标记无法配给

**日期**: 2026-08-24
**版本**: v0.2B(开发中)
**优先级**: 高

## 现象
首次从邮件配置页点击下一步进入「负载配给页」后，标记列表就被固定住了。
之后回到配置页新增新的 `$$变量$$` 标记，再次进入负载配给页，新增标记没有出现在下拉与绑定表中，无法进行数据文件配给。

## 根因
`AdvancedPage._onGoNextStep` 中，进入负载页时用 `_load_state_initialized` 标志做了「仅首次构建」控制：
- 首次进入：调用 `_rebuildLoadList()` 全量构建（会先清空 `_load_map`/`_marker_keys`）。
- 再次进入：`_load_state_initialized` 为 True，整段逻辑被跳过，负载列表完全不再更新，因此配置页新加的标记永远不会被收集进来。

即「为避免往返步骤重置而设置的防重初始化标志」同时阻止了新增标记的增量加入，导致列表固定死。

## 修复
在 `MainGUI.py` 中：
1. 新增 `_syncLoadList()`：改为「只增不减」的增量同步——
   - 保留既有 `_marker_keys`/`_marker_names`（含已绑定文件 `_load_map`，不清空、不覆盖）；
   - 仅把本次 `_collectMarkers()` 中新出现的标记 key 追加进来；
   - 重新填充下拉、刷新绑定表与进度；有新增时加载首个预览便于确认。
2. 新增 `_fillMarkerCombo(markers)`：把下拉填充逻辑从 `_rebuildLoadList` 抽取为可复用方法。
3. `_onGoNextStep` 中，首次仍走 `_rebuildLoadList()`，再次进入改走 `_syncLoadList()`，实现「只做加法、不做减法」。

## 验证
- 首次仅含 `昵称:1`；为其绑定文件后，在配置页新增 `主题:1`、`正文:1`。
- 再次进入负载页后 `_marker_keys` = `['昵称:1', '主题:1', '正文:1']`，下拉数=3。
- `昵称:1` 既有绑定文件保持不变，新增标记以未绑定状态可继续配给。
- `python -m py_compile` 通过；冒烟脚本断言全部通过（SYNC_INCREMENTAL_OK）。