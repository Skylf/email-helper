# Bug: 正文插入的图片发送后收件端看不到

**日期**: 2026-08-23
**版本**: v0.0.1F
**优先级**: 高

## 现象
在 GUI 普通模式正文中用「图片」按钮插入图片后，发送邮件，收件端（QQ 等客户端）看不到该图。

## 根因
两层叠加导致图片丢失：
1. GUI 原 `onInsertImage` 使用 `QTextCursor.insertImage(QImage)` 插入图片，PyQt 会把图片序列化为
   **base64 的 `data:` URI** 写入 `toHtml()` 产出的 HTML（`<img src="data:image/png;base64,...">`）。
   多数邮件客户端（尤其 QQ）不解析 `data:` URI 形式的内嵌图。
2. GUI 的 `onSend` 从未调用 `LEmail.setInlineImage`（`inline_image_path` 恒为空），
   因此 `buildMessage()` 中 `if self.inline_image_path:` 为假，
   邮件只走 `alternative` 结构，根本不构建 `related`，图片自然无法作为邮件附件随信发送。

## 修复
改为标准「cid 引用 + related 结构」方案，统一 content-id 规则：
- **MainGUI.onInsertImage**：改用 `QTextImageFormat.setName('cid:文件名')` 插入图片，并
  用 `QTextDocument.addResource(ImageResource, QUrl('cid:文件名'), image)` 让编辑器内能显示；
  `toHtml()` 由此输出 `<img src="cid:文件名">`（已实测验证）。同时把内嵌图片维护为
  `{content_id: 文件路径}` 映射（`onInsertImage` 支持重名唯一化），并经 `onSend` 传参。
- **MainGUI.onSend**：把 `inline_image_paths` 映射传给 `NormalMode.setConfig`。
- **MainEmail.setInlineImage / buildRelated**：支持 `dict{content_id: 路径}` 形式接收内嵌图片，
  并按映射生成 `Content-ID`，保证与 HTML 中 `cid:` 引用完全一致（原列表形式仍兼容，cid 用文件名）。

## 验证
1. 离线端到端脚本：构造「两张 cid 图片的 HTML + 映射」→ `buildMessage()` 结果为
   `subtype=related`，实际 `Content-ID = ['<tmp_a.png>','<tmp_b.png>']`，与 HTML 中
   `cid:` 引用集合完全一致（MATCH=True）。
2. `py_compile` 全通过。建议再做一次 GUI 实际发信真人验证。