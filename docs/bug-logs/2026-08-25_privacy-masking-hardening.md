# 安全加固：日志/配置/数据库敏感信息脱敏

**日期**: 2026-08-25
**版本**: v0.3A（开发中）
**优先级**: 高

## 现象
程序在以下环节存在个人/敏感信息明留：
1. 邮件发送成功日志打印了完整的发件人账号与收件人邮箱（MainEmail.py）。
2. SMTP 账号密码存在明文回退（config.local/config.example）。
3. 高级模式任务配置（含收件人、正文、附件路径、负载映射）以明文 JSON 落库，直读数据库即可见。
4. 发送完成后，收件人/正文等预览数据仍保留在运行内存中。

## 根因
- 发送日志未做脱敏，直接拼接 `self.receivers` 与 `SMTP_USERNAME`。
- 早期为兼容未加密环境保留了明文 config 回退路径。
- tasks.config 落库时直接 `json.dumps`，未加密。
- 发送完成回调未清理内存中的预览数据缓存。

## 修复
- **日志脱敏**（MainEmail.py）：发送成功日志改为仅记录收件人数量，不打印账号与邮箱。
- **移除明文回退**（MainEmail.py `loadSmtpCredentials`）：删除 config.local/config.example 明文读取，SMTP 凭据唯一来源改为加密文件，凭据缺失/解密失败时返回空串。
- **数据库加密落库**（database.py）：
  - 新增 `encryptTaskConfig` / `decryptTaskConfig` / `_xorObfuscate`。
  - `insertTask` / `updateTask` 写入 config 前混淆加密（`enc1:` 前缀 + base64 + 逐字节异或）。
  - `_taskToDict` 读库时自动解密，兼容旧明文数据。
- **清空内存缓存**（MainGUI.py `_onAllMailSent`）：全部发送成功后清空 `_preview_mails` / `_send_ready_items` / `_send_status`，个人数据不残留内存；有失败时保留以支持「重发失败邮件」。

## 验证
- 语法校验通过（database.py / MainEmail.py / MainGUI.py）。
- 加解密闭环：密文前缀 `enc1:`、不含明文邮箱、解密还原与原文一致。
- SMTP 加密链路：移除明文回退后仍能从 `credentials.enc` 解密出账号密码（账号 lhackservice@…，密码长 11）。