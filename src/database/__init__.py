# -*- coding: utf-8 -*-
# 数据库包：邮件数据持久化（SQLite）
# 功能：对外提供邮件记录的增删改查、搜索、分类移动、统计等 API。
#       所有分类常量、MailDatabase 类与单例便捷函数均在此导出。

from .database import (
    MailDatabase,
    getDb,
    CATEGORY_DRAFT,
    CATEGORY_SENT,
    CATEGORY_DELETED,
    CATEGORY_JUNK,
    DEFAULT_DB_FILENAME,
)

__all__ = [
    'MailDatabase',
    'getDb',
    'CATEGORY_DRAFT',
    'CATEGORY_SENT',
    'CATEGORY_DELETED',
    'CATEGORY_JUNK',
    'DEFAULT_DB_FILENAME',
]