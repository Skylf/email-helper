# Bug: 点击高级模式进入后表单残留上一任务的旧数据

**日期**: 2026-08-24
**版本**: v0.2B(开发中)
**优先级**: 高

## 现象
从写信→高级模式进入后，所有输入框不是空的，残留了上次任务的填写内容：
`a@b.cn`、`昵称 $$昵称1$$`、`主题测试`、`正文 $$正文1$$`。

## 根因
进入高级模式走 `MainWindow.showHighModePlaceholder` → `AdvancedPage.startNewTask()`。
该方法的初始实现只重置了「任务名」与 `_current_task_id`，**没有清空表单控件与负载/预览状态**。
因此上次（或上一任务）残留在 `to_edit / nickname_edit / title_edit / body_editor` 以及
`_load_map / _marker_keys / _preview_mails / 附件 / 内嵌图片` 里的内容会原样带进新任务。

## 修复
在 `MainGUI.py` 的 `startNewTask()` 中，重置任务名与 id 之后，追加全量清空：
- 清空 `to_edit/cc_edit/bcc_edit/reply_edit/return_edit/nickname_edit/title_edit` 与 `body_editor`。
- 收起抄送/密送展开行。
- 清空固定附件路径、附件文件夹、内嵌图片映射。
- 重置 `_load_map/_marker_keys/_marker_names/_file_row_counts/_preview_mails/预览标志/负载初始化标志`。
- 回到配置页第1步并刷新变量面板(空)。
- 未直接复用父类 `clearForm()`，因高级模式缺 `from_edit` 等控件且需额外清负载/预览。

恢复草稿任务走 `_restoreTaskConfig`，不会经过本方法，故全量清空是安全的。

## 验证
- 预填 `to_edit/nickname_edit/title_edit/body_editor/_load_map/_preview_mails/附件/图片` 后调用 `startNewTask()`。
- 所有输入控件为空、`_load_map/_marker_keys/_preview_mails/附件/图片` 为空、`_load_state_initialized=False`、`step_stack` 回到第1步、任务名重置为「高级模式任务x」。
- 断言全部通过（CLEAR_ON_NEW_TASK_OK）；`python -m py_compile` 通过。