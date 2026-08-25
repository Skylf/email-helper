# Bug: 高级模式富文本字体下拉列表文字不可见

**日期**: 2026-08-25
**版本**: v0.3A（开发中）
**优先级**: 中

## 现象
高级模式邮件配置页面的正文富文本编辑区，工具栏「字体」下拉列表（QFontComboBox）背景为白色、文字接近白色，几乎看不见内容，无法正常选择字体。

## 根因
在 `_buildTextToolbar`（MainGUI.py）中构建工具栏时，`font_combo`（以及同排的 `size_combo`）只做了基础创建，未显式指定任何样式。由于页面某些父级容器/全局配色影响，QFontComboBox 展开的下拉弹窗（实际是一个 QListView / QAbstractItemView）列表项的默认文字颜色异常（浅色显示于浅色背景上），造成白底白字，无法看清。
字号下拉 `size_combo` 存在同样的隐患。

## 修复
在 `src/GUI/MainGUI.py` 的 `_buildTextToolbar` 中，为 `font_combo` 与 `size_combo` 显式设置高对比样式表，强制下拉框及其弹窗列表为「白底深字」并在选中项使用蓝色高对比：
- `QComboBox`：`background:#ffffff; color:#1f2328;`
- `QComboBox QAbstractItemView`：`background:#ffffff; color:#1f2328;`
- 选中项：`selection-background-color:#1b7bf2; selection-color:#ffffff;`

这样不依赖任何父级/全局配色，保证字体、字号下拉在普通模式与高级模式下都清晰可读。

## 验证
- 修改前后文件通过 `ast.parse` 语法校验（语法 OK）。
- 下拉框与弹窗列表均强制白底深字、选中清晰高亮，任何父级配色下均可正常辨识文字。