# Bug: GitHub Actions 构建 macOS .app 连环失败

**日期**: 2026-08-25
**版本**: v0.5.4
**优先级**: 高

## 现象
依次推送标签触发 macOS CI 构建时，连续 4 次失败：
1. `v0.5.1`：`base64: stdin: error decoding base64 input stream`（exit code 1）
2. `v0.5.2`：解密/编译/打包通过，但 `svenstaro/upload-release-action` 报 `get a release by tag name: Not Found`
3. `v0.5.3`：改 `softprops/action-gh-release` 后报 `Resource not accessible by integration` + `Unexpected input 'overwrite'`
4. `v0.5.4`：全绿

## 根因
三个独立问题叠加：

1. **base64 secret 污染**：`CRED_SETUP_SCRIPT`（2,896 字符）走 GitHub secret 在复制粘贴时混入不可见字符/换行，CI 侧 `base64 -d` 解码失败。本地验证同一值却合法，证明是粘贴环节被污染，而非值本身错误。
2. **Release 未预先存在**：`svenstaro/upload-release-action@v2` 上传时要求目标 tag 的 Release 已存在，而 `v0.5.x` 标签从未手工建过 Release，故报 Not Found。
3. **token 权限不足 + 参数名错误**：`softprops/action-gh-release@v2` 创建 Release 需 `GITHUB_TOKEN` 具备 `contents: write` 权限（默认只读），未声明则报 `Resource not accessible`；且 v2 覆盖资产参数名为 `overwrite_files`（写成 `overwrite` 为非法输入）。

## 修复
1. `.gitignore` 增加例外 `!src/security/setup_crypt.py`：`setup_crypt.py` 仅为编译脚本、不含密钥分片，从 secret 改为随仓库跟踪，消除一个 secret 失败点（secret 数量 3 → 2）。
2. `.github/workflows/build-mac.yml`：
   - 移除 `CRED_SETUP_SCRIPT` secret 依赖，直接从仓库读取 `src/security/setup_crypt.py`。
   - 上传改用 `softprops/action-gh-release@v2`，标签无 Release 时自动创建。
   - job 增加 `permissions: contents: write`。
   - 修正参数为 `overwrite_files: true`。
   - 压缩包改 ASCII 名 `EmailHelper-mac.app.zip`（规避中文文件名问题）。

## 验证
推送 v0.5.4 后 Actions 全绿，解密 C 源码 → 编译 .so → PyInstaller 打出 .app → 上传 Release 全流程通过，`EmailHelper-mac.app.zip` 成功上传到 Releases。

## 附：当前 macOS CI 依赖的 2 个 secret
- `CREDENTIALS_ENC`：base64 的 `credentials.enc`
- `CRED_FILE_KEY`：hex 的 AES 解密密钥（还原 `cred_app.c`）