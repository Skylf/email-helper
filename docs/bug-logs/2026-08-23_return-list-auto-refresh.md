# Bug: 发送/存草稿后返回列表页面不自动刷新

**日期**: 2026-08-23
**版本**: v0.0.1F
**优先级**: 高

## 现象
发送一封邮件成功后返回「已发送」页面，新发送的邮件未显示在列表中；需要用户手动重新进入一次「已发送」分类才能刷新出来。同一类的页面操作（如存草稿、取消返回）也都存在「回到列表数据过期」的问题。

## 根因
`MainWindow.showListPage` 仅实现了页面切换（`resizeEvent` 前只执行 `stack.setCurrentWidget`），**没有从数据库中重新读取当前分类的邮件列表**。

`onSendFinished` 在发送成功后调用 `self.on_back()`（即 `showListPage`），返回列表时列表页展示的仍是进入写信页之前加载的旧数据；而 `showListPage` 不触发 `_refreshListPageFor`，导致新写入「已发送」的记录无法即时显示。只有点击左栏菜单（走 `onNavItemClicked → setActiveNav → _refreshListPageFor`）才会重新读库，所以用户必须「重新进入页面」才能看到新邮件。

## 修复
修改 `ShowListPage`（src/GUI/MainGUI.py）：
- 在切换到列表页之前，先调用 `_refreshListPageFor(self._current_menu_id)` 从数据库重读当前分类的数据。
- 这样无论发送成功、存草稿、取消/返回等任何「回到列表页」的路径，都会自动刷新最新数据，无需用户重新进入分类。

## 验证
- 离屏 smoke test：先进入「已发送」空列表（0 行）→ 往数据库插入一条已发送记录 → 调用 `showListPage()` → 列表刷新为 1 行，首行标题为新插入邮件的主题。
- `py_compile` 通过。