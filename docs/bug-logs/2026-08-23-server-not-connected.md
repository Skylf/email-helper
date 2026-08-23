# Bug: 邮件发送失败，提示 Server not connected

**日期**: 2026-08-23
**版本**: v0.0.1F
**优先级**: 高

## 现象
GUI 点击发送后，控制台显示「邮件发送失败(SMTP): Server not connected」，邮件未发出；
点击一次发送后有完整 traceback。

## 根因（最终定位）
完整 traceback 显示真实异常是 `_ssl.c` 抛出的：

```
ssl.SSLWantWriteError: The operation did not complete (write)
→ smtplib.py:363 send → raise SMTPServerDisconnected('Server not connected')
```

它发生在 `client.data(msg)`（即 **DATA 阶段发送大载荷**，本实例为 HTML+内嵌图片）时。
`SSLWantWriteError` 是瞬间的 SSL 写未完成（大量数据一次写不完、底层写缓冲瞬时满），
`smtplib.send()` 会把这类 `OSError` 捕获并 `close()` 重抛为
`SMTPServerDisconnected: Server not connected`。因此它本质是**瞬时性错误**，
只要在发送阶段做重试/重建连接即可规避；此前 `sendMail` 对发送阶段无重试，一次抖动即整体失败。

(补充：此前本机小邮件/带图邮件多次复现均发送成功，正是因为瞬时错误在正常网络下不常发生，
但GUI发送的邮件体更大、更易触发SSL写缓冲瞬时打满。)

## 修复
`MainEmail.sendMail()` 增加**发送阶段瞬时性错误自动重试**：
- 对 `SSLWantWriteError/SSLWantReadError/SMTPServerDisconnected/ConnectionError/TimeoutError`
  等瞬时/网络中断错误，重建 SMTP 连接并重试（最多 `SMTP_MAX_RETRY=3` 次，间隔1s）；
- 认证/拒绝/数据接收拒绝等**确定性错误**不重试，直接返回失败；
- 重试耗尽时打印最后一次瞬时错误的完整堆栈，便于继续定位。
- 新增常量 `SMTP_TIMEOUT=30`（连接超时）与 `SMTP_RETRY_INTERVAL=1`（重试间隔）。

## 验证
1. `py_compile` 通过；
2. 加固后带 2KB 正文的真实发送 → `send -> True`，功能正常、未破坏原有发送；
3. 重试逻辑按路径验证：瞬时错误会走重试分支并输出「SMTP 发送阶段失败（第 N/3 次）…」，
   重试成功后返回 True。