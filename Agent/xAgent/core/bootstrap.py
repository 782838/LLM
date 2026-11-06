"""首次运行的配置初始化。

当前目录（项目根）没有 config.ini 时，生成一份完整模板，
并让界面弹出对话框告诉用户改完重启。
"""
import os

from .project import find_project_root
from .settings import create_config


class BootstrapResult:
    """首次运行检查的结果。"""

    def __init__(self, created=False, path=None, error=None, existing=None):
        self.created = created        # 这次有没有新建
        self.path = path              # 新建或已有的路径
        self.error = error            # 新建失败的原因
        self.existing = existing      # 已经存在的配置路径

    @property
    def needs_restart(self):
        """是否需要用户改完配置后重启。"""
        return self.created

    def __repr__(self):
        return "BootstrapResult(created=%s, path=%r)" % (self.created, self.path)


def ensure_config(root=None, filename="config.ini"):
    """确保项目根有配置文件。

    只在**项目根**找，不去程序目录翻。因为：
        - 任务要求的就是「当前目录」的配置
        - 程序目录的配置是开发时自带的，不该让用户的空项目被它顶掉

    有就返回已有路径，没有就生成一份模板。
    """
    base = root or find_project_root()[0]
    local = os.path.join(base, filename)

    if os.path.isfile(local):
        return BootstrapResult(path=local, existing=local)

    # 项目根没有，生成一份
    ok, detail = create_config(local)
    if not ok:
        return BootstrapResult(error=detail, path=local)

    return BootstrapResult(created=True, path=local)
