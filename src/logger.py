# -*- coding: utf-8 -*-
# 日志系统模块
# 作者：LF
# 创建时间：2026-08-25
# 功能：基于 Python 标准库 logging 实现分级日志（DEBUG/INFO/WARNING/ERROR/CRITICAL），
#       同时输出到文件（按日期自动轮转）和控制台。
#       日志保存路径从 option.settings 读取（用户可在设置页自定义），
#       默认开发环境为项目根/logs，打包环境为安装目录/logs。
#
# 使用方式：
#   1. 程序入口 src/main.py 调用 setupLogging() 完成全局初始化（仅需一次）。
#   2. 各模块通过 getLogger(name) 获取专属 logger 实例，调用 debug/info/warning/error/critical 写日志。
#   3. 未初始化前调用 getLogger 仅返回标准 logger（不挂 handler，日志不落盘，仅传递给 root）。

import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler

# 统一通过 PathManager 定位数据根目录（开发=项目根，打包=exe 目录）
try:
    from path_manager import PathManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from path_manager import PathManager

# ---- 日志级别常量（对应 logging 标准级别，供外部按名称引用）----
LEVEL_DEBUG = logging.DEBUG        # 调试信息：详细的内部状态、变量值等，仅开发排查时有用
LEVEL_INFO = logging.INFO          # 一般信息：正常流程关键节点（启动、发送成功等）
LEVEL_WARNING = logging.WARNING    # 警告：非致命异常（如重试、降级、配置缺失回退）
LEVEL_ERROR = logging.ERROR        # 错误：功能失败（如 SMTP 发送失败、数据库写入异常）
LEVEL_CRITICAL = logging.CRITICAL  # 严重错误：程序无法继续运行（如初始化失败）

# 日志文件名（不含路径，拼接在 log_path 之下）
LOG_FILENAME = 'app.log'
# 日志格式：时间 | 级别 | 模块名 | 函数名:行号 | 消息
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s'
# 日期格式
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
# 按天轮转，保留最近 30 天的日志文件
LOG_BACKUP_DAYS = 30

# 全局初始化标记：避免重复挂载 handler 导致日志重复输出
_logging_initialized = False


def _resolveLogPath():
    """解析日志保存目录：优先从设置读取，失败时回退到默认路径

    返回：
        str：日志目录绝对路径
    """
    # 默认路径：用户数据根目录 / logs
    default_path = os.path.join(os.fspath(PathManager.root()), 'logs')
    try:
        # 从 option.settings 读取用户自定义的日志路径（设置页可修改）
        from option.settings import settings
        user_path = settings.get('log_path')
        if user_path and isinstance(user_path, str) and user_path.strip():
            return user_path.strip()
    except Exception:
        # 设置模块不可用时静默回退默认路径
        pass
    return default_path


def setupLogging(level=LEVEL_INFO):
    """全局初始化日志系统（仅需在程序入口调用一次）

    配置 root logger：添加按日期轮转的文件 handler + 控制台 handler，
    设置统一格式与日志级别。重复调用时安全跳过（避免 handler 叠加）。

    参数：
        level<int>：全局日志级别，默认 INFO（DEBUG 会输出大量调试信息）
    """
    global _logging_initialized
    if _logging_initialized:
        # 已初始化过：避免重复挂载 handler 导致日志重复输出
        return

    # 解析日志目录并确保存在（不存在则创建）
    log_dir = _resolveLogPath()
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        # 目录创建失败时回退到用户数据根目录下的 logs
        log_dir = os.path.join(os.fspath(PathManager.root()), 'logs')
        os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, LOG_FILENAME)

    # 统一格式器
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # ---- 文件 handler：按天轮转，午夜切换，保留 30 天 ----
    file_handler = TimedRotatingFileHandler(
        log_file, when='midnight', interval=1,
        backupCount=LOG_BACKUP_DAYS, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # ---- 控制台 handler：开发时实时查看 ----
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    # 配置 root logger：清除已有 handler，挂载新的
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # 清除可能残留的 handler，避免重复输出
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 标记已初始化
    _logging_initialized = True
    # 记录启动信息（首条日志，确认日志系统已就绪）
    root_logger.info('日志系统已初始化，日志目录: %s', log_dir)


def getLogger(name=None):
    """获取模块专属 logger 实例

    各业务模块调用本函数获取以自身模块名命名的 logger，
    日志输出中会带上模块名（name）便于定位来源。

    参数：
        name<str|None>：模块名（通常传 __name__）；为 None 时返回 root logger

    返回：
        logging.Logger：logger 实例，可直接调用 debug/info/warning/error/critical
    """
    return logging.getLogger(name)


def isInitialized():
    """检查日志系统是否已初始化（供模块在写入前判断）

    返回：
        bool：已调用 setupLogging 则为 True
    """
    return _logging_initialized


def logException(logger, msg, exc_info=True):
    """便捷方法：记录异常日志（含完整堆栈）

    参数：
        logger<logging.Logger>：logger 实例
        msg<str>：异常描述
        exc_info<bool>：是否附加完整异常堆栈信息，默认 True
    """
    logger.error(msg, exc_info=exc_info)
