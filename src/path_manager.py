import sys
from pathlib import Path


class PathManager:
    """开发/打包环境自适应路径管理器（兼容 Windows / macOS / Linux）"""

    @staticmethod
    def root() -> Path:
        """
        用户数据根目录（日志、用户配置、数据文件等）
        开发时：项目根目录（本文件所在目录的上一级，即 src 的父目录）
        打包后 Windows：main.exe 所在目录
        打包后 macOS：~/Library/Application Support/<应用名>（.app 的 Bundle 内部默认只读，故放用户库）
        """
        if getattr(sys, 'frozen', False):
            # macOS：用户可写数据放到 ~/Library/Application Support/，避免写入只读的 .app Bundle
            if sys.platform == 'darwin':
                root_dir = Path.home() / 'Library' / 'Application Support' / 'EmailHelper'
                # 确保用户数据目录存在，供后续日志/数据库/设置写入
                root_dir.mkdir(parents=True, exist_ok=True)
                return root_dir
            # Windows / Linux：可执行文件所在目录
            return Path(sys.executable).parent
        return Path(__file__).parent.parent

    @staticmethod
    def source_root() -> Path:
        """
        源码包根目录（用于 sys.path 定位「GUI」「Email」等包）
        开发时：src 目录（本文件所在目录）
        打包后：PyInstaller 解压的 _MEIPASS 目录（包结构已被收集到顶层）
        """
        if getattr(sys, 'frozen', False):
            return Path(sys._MEIPASS)
        return Path(__file__).parent

    @staticmethod
    def internal() -> Path:
        """
        程序内部资源目录（只读，如默认配置、模板等）
        开发时：项目根目录
        打包后：PyInstaller 解压的 _MEIPASS 临时目录
        """
        if getattr(sys, 'frozen', False):
            return Path(sys._MEIPASS)
        return Path(__file__).parent