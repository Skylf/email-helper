# Bug: 大附件发送失败（20MB→557超限，110MB→Server not connected）

**日期**: 2026-08-23
**版本**: v0.0.1F
**优先级**: 中

## 现象
- 选择 5MB 附件发送成功；
- 选择 20MB 附件发送失败：`557 The length of DATA content is achieved the maximum threshold [@sm080101]`；
- 选择 110MB 附件发送失败：DATA 阶段出现 `SSLWantWriteError` → 包装为 `Server not connected`（重试 3 次仍失败）。

## 根因
这是**阿里云邮件推送服务端的硬性大小限制**，并非代码 bug。官方《规格清单》说明：
> 附件邮件总大小不超过 **15MB**（指 SMTP 实际发送的总大小；因 base64 编码会膨胀约 1.5 倍，
> 源附件文件建议 ≤ 8MB）。

- 5MB → base64 后约 7MB，未超 15MB → 成功；
- 20MB → base64 后约 30MB，超限 → 服务器拒绝并返回 557（DATA content 达到最大阈值）；
- 110MB → base64 后约 170MB，服务器在 DATA 阶段直接掐断连接，socket 写入产生
  `SSLWantWriteError`，因此表现为 `Server not connected`（与上一次日志同链路，但触发点是服务端限额断开而非网络瞬时抖动）。

## 修复
发送前增加**邮件总大小预检**，超限直接拒绝、不建立连接：
- `MainEmail`：新增 `estimateEmailSize()`（正文 + 附件 base64 膨胀 + 头部开销）与
  `checkEmailSize()`；`sendMail()` 构建消息后先校验，超 `SMTP_MAX_EMAIL_SIZE=15MB`
  打印明确中文原因并返回 `False`，不再触发 557/断连。
- `MainGUI`：`onAddAttachment()` 把待添加文件计入后估算总大小，超限该附件直接弹窗提示
  且不加入。

大附件建议：压缩后拆分，或按阿里官方建议「以超链接方式发送」。

## 验证
1. `py_compile` 通过；
2. 12MB 附件（base64 约16MB>15MB）→ `checkEmailSize` 返回 `over=True(16.3MB)`；
   小文件（约12KB，base64约16KB）→ `over=False(0.15MB)`；
3. `.venv` 下发送 5MB 内小附件正常。