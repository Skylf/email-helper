# email-helper

邮件发送助手（Python + PyQt6）。

## 版本
v0.1A 开发版

## 功能（普通模式）
- 图形化邮件编辑（主题 / 收件人 / 抄送 / 密送）
- HTML 正文排版
- 附件上传（上限 15MB / 100 个）
- 内嵌图片（标准 cid+related MIME）
- 大文件分享链接插入
- SMTP 发送（阿里云邮件推送，30s 超时 + 3 次重试）
- 草稿箱 / 已发送 / 已删除（保留 30 天自动清理）本地记录

## 运行
```bash
pip install -r requirements.txt
python src/main.py
```

## 配置
复制 `config.example` 为 `config.local`，填入你的 SMTP 账号与授权码：

```bash
cp config.example config.local
```

`config.local` 不会被提交到版本库，请勿将真实凭据写入其他文件。