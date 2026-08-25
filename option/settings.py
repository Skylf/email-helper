# -*- coding: utf-8 -*-
# 设置管理器：应用设置项的读写与持久化（Settings API 核心）
# 作者：LF
# 功能：提供一组「用户可在设置界面修改」的配置项的默认值、读取、修改与保存能力。
#       数据落在用户数据根目录的 settings.json（PathManager.root() 之下），
#       与承载 SMTP 凭据的 config.local 相互独立，设置里不含任何机密信息。
#
# 当前开放给用户的设置项（新增项请在 DEFAULTS 中补充并同步设置界面）：
#   - default_from_name ：默认发件人昵称（原 NormalMode / MainGUI 硬编码 DEFAULT_FROM_NAME）
#   - preview_batch_size：高级模式预览页批量生成邮件数（原 AdvancedPage 硬编码 PREVIEW_BATCH_SIZE）
#
# 导入路径说明：本文件可能在「项目根/option」或打包后的 _MEIPASS 下运行，
# PathManager 统一注入与回退，保证开发/打包环境下都能定位数据根目录。

import json
import os
import sys

# 统一通过 PathManager 定位用户数据根目录（开发=项目根，打包=exe 目录）
try:
    from path_manager import PathManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from path_manager import PathManager


class SettingsManager:
    """设置项管理器

    维护一份「用户可修改设置项」的内存字典（以 DEFAULTS 为基准），
    支持读取、修改、并持久化到用户数据根目录下的 settings.json。
    该字典最终被 GUI 各使用点读取，实现设置实时生效。
    """

    # 设置文件相对用户数据根目录的文件名
    SETTINGS_FILENAME = 'settings.json'
    # 全部可配置项及其默认值（新增设置项必须在设置界面对应加入控件）
    DEFAULTS = {
        'default_from_name': 'Lhack 邮箱助手',   # 默认发件人昵称
        'preview_batch_size': 5,                 # 高级模式预览页批量生成邮件数
        'data_file_encoding': 'UTF-8',           # CSV/TXT 收件人数据文件默认编码
        'mail_tracking_enabled': False,          # 邮件发信追踪开关（功能预留，统计打开率）
        'log_path': str(PathManager.root() / 'logs'),  # 日志保存路径（开发=项目根/logs，打包=安装目录/logs）
    }

    def __init__(self):
        """初始化：定位设置文件路径，先载入默认值再覆盖读取本地已有设置"""
        # 设置文件绝对路径：用户数据根目录 / settings.json
        self.file_path = os.path.join(os.fspath(PathManager.root()),
                                      self.SETTINGS_FILENAME)
        # 当前生效的设置字典（初始即为默认值，load 成功后覆盖用户修改过的项）
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        """从设置文件读取已保存的配置，逐项覆盖默认值

        文件不存在或格式非法时静默忽略，保持默认值（设置首次运行前即为默认）。
        """
        try:
            with open(self.file_path, 'r', encoding='utf-8') as fobj:
                raw = json.load(fobj)
        except (OSError, ValueError):
            # 无文件 / 非 JSON / 损坏：一律视为未配置，沿用默认值即可
            return
        if not isinstance(raw, dict):
            return
        # 仅覆盖已知设置项，忽略文件中的未知键，避免脏数据污染
        for key in self.DEFAULTS:
            if key in raw and raw[key] is not None:
                self.data[key] = raw[key]

    def get(self, key, default=None):
        """获取指定设置项当前值

        参数：
            key<str>：设置项键名（须存在于 DEFAULTS）
            default<any>：不传时返回该项默认值；传了则仅在该键未知时返回它
        返回：
            any：该项当前值
        """
        if key in self.data:
            return self.data[key]
        # 键未知：优先用传入的默认值，否则退回 DEFAULTS 中的默认值
        return default if default is not None else self.DEFAULTS.get(key)

    def set(self, key, value):
        """修改指定设置项的内存值（不落盘）

        参数：
            key<str>：设置项键名（须存在于 DEFAULTS，否则抛 KeyError）
            value<any>：新值
        """
        if key not in self.DEFAULTS:
            raise KeyError('unknown setting key: %s' % key)
        self.data[key] = value

    def save(self):
        """将当前设置持久化到设置文件

        写入失败（如磁盘只读）时静默忽略，不中断主流程；
        下次读取仍按已有文件或默认值兜底。
        """
        try:
            with open(self.file_path, 'w', encoding='utf-8') as fobj:
                json.dump(self.data, fobj, ensure_ascii=False, indent=2)
        except OSError:
            # 无法写盘：仅丢失本次设置，功能不受影响
            pass

    def all(self):
        """返回当前全部设置的副本（供设置界面逐项渲染与回填）

        返回：
            dict：当前生效的设置项键值副本
        """
        return dict(self.data)


# 模块级单例：供 GUI 多个使用点共享同一份设置状态
settings = SettingsManager()


def getSettingsInstance():
    """获取全局唯一的设置管理器单例

    返回：
        SettingsManager：当前进程的设置管理器
    """
    return settings