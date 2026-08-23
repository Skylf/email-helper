# -*- coding: utf-8 -*-
# 数据库层：邮件数据持久化（SQLite）
# 作者：LF
# 创建时间：2026-08-23
# 功能：基于 SQLite 提供邮件记录的增删改查、搜索、分类移动、统计与关联附件/内嵌图片信息。
#       列表页（草稿箱 / 已发送 / 已删除 / 垃圾箱）的真实数据统一由本模块读写。
#       使用标准库 sqlite3，无第三方依赖；开发/打包环境下数据库文件位置自适应。

import json
import os
import sqlite3
import sys
from datetime import datetime

# 统一通过 PathManager 定位数据根目录（开发=项目根，打包=exe 目录）。
# 运行入口会向 sys.path 注入 src，若不成功则回退按本文件位置推算项目根。
try:
    from path_manager import PathManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from path_manager import PathManager

# 邮件分类常量（对应列表页四个菜单）
CATEGORY_DRAFT = 'draft'      # 草稿箱
CATEGORY_SENT = 'sent'        # 已发送
CATEGORY_DELETED = 'deleted'  # 已删除
CATEGORY_JUNK = 'junk'        # 垃圾箱

# 数据库默认文件名（相对数据根目录）
DEFAULT_DB_FILENAME = 'email_helper.db'


class MailDatabase:
    """邮件 SQLite 数据库 API

    负责创建表结构，并对邮件记录提供：插入、按 id 查询、按分类查询、搜索、
    更新（再次编辑回填）、物理删除、分类移动、数量统计、关闭连接等操作。
    """

    def __init__(self, db_path=None):
        """初始化数据库连接并确保表结构存在

        参数：
            db_path<str|Path>：数据库文件路径；缺省时使用数据根目录下的默认数据库文件
        """
        # 未指定路径时，放在数据根目录下（PathManager.root()）
        if db_path is None:
            data_dir = PathManager.root() / 'data'
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / DEFAULT_DB_FILENAME
        self.db_path = os.fspath(db_path)
        # 建立连接，检查同一线程可重入以基本保证读安全
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.ensureSchema()

    # ---------------- 表结构 ----------------
    def ensureSchema(self):
        """建表：mails（若不存在），并迁移补充新字段"""
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS mails(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    recipient TEXT DEFAULT '',
                    send_time TEXT DEFAULT '',
                    from_name TEXT DEFAULT '',
                    to_list TEXT DEFAULT '[]',
                    cc_list TEXT DEFAULT '[]',
                    bcc_list TEXT DEFAULT '[]',
                    reply_to TEXT DEFAULT '',
                    return_email TEXT DEFAULT '',
                    html_text TEXT DEFAULT '',
                    attachment_paths TEXT DEFAULT '[]',
                    inline_image_paths TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT '',
                    deleted_at TEXT DEFAULT ''
                )
            ''')
            # 常用查询字段建索引：按分类列表 + 按 id 回查
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_mails_cat ON mails(category)')
            # 轻量迁移：旧库可能缺少 deleted_at 等新增字段，缺失则补列
            self._migrateColumns()

    def _migrateColumns(self):
        """为既有数据库补充新增字段（ALTER TABLE ADD COLUMN，缺列才加）

        说明：已存在的历史库没有 deleted_at（记录进入「已删除」的时间），
        这里逐一检测补列，避免老库直接报错。
        """
        cols = {r[1] for r in self.conn.execute('PRAGMA table_info(mails)').fetchall()}
        if 'deleted_at' not in cols:
            self.conn.execute("ALTER TABLE mails ADD COLUMN deleted_at TEXT DEFAULT ''")

    # ---------------- 写入 ----------------
    def insertMail(self, category, title='', recipient='', send_time=None,
                   from_name='', to_list=None, cc_list=None, bcc_list=None,
                   reply_to='', return_email='', html_text='',
                   attachment_paths=None, inline_image_paths=None):
        """插入一条邮件记录，返回新记录 id

        返回：
            int：新插入记录的 id
        """
        now = send_time if send_time else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self.conn:
            cur = self.conn.execute(
                'INSERT INTO mails(category,title,recipient,send_time,from_name,'
                'to_list,cc_list,bcc_list,reply_to,return_email,html_text,'
                'attachment_paths,inline_image_paths,created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (category, title, recipient, now, from_name,
                 json.dumps(to_list or [], ensure_ascii=False),
                 json.dumps(cc_list or [], ensure_ascii=False),
                 json.dumps(bcc_list or [], ensure_ascii=False),
                 reply_to, return_email, html_text,
                 json.dumps(attachment_paths or [], ensure_ascii=False),
                 json.dumps(inline_image_paths or {}, ensure_ascii=False),
                 now))
        return cur.lastrowid

    # ---------------- 查询 ----------------
    def getMail(self, mail_id):
        """按 id 查询单条邮件，转成 dict（含解析后的列表/字典字段）"""
        with self.conn:
            row = self.conn.execute('SELECT * FROM mails WHERE id=?', (mail_id,)).fetchone()
        return self._rowToDict(row) if row else None

    def getMails(self, category=None):
        """按分类查询邮件列表，按保存时间倒序"""
        if category:
            sql = 'SELECT * FROM mails WHERE category=? ORDER BY datetime(send_time) DESC, id DESC'
            params = (category,)
        else:
            sql = 'SELECT * FROM mails ORDER BY datetime(send_time) DESC, id DESC'
            params = ()
        with self.conn:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._rowToDict(r) for r in rows]

    def searchMails(self, keyword, category=None):
        """按关键词在主题/收件人/正文中模糊搜索邮件"""
        like = '%' + keyword + '%'
        sql = 'SELECT * FROM mails WHERE (title LIKE ? OR recipient LIKE ? OR html_text LIKE ?)'
        params = [like, like, like]
        if category:
            sql += ' AND category=?'
            params.append(category)
        sql += ' ORDER BY datetime(send_time) DESC, id DESC'
        with self.conn:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._rowToDict(r) for r in rows]

    def queryMails(self, category=None, title='', recipient='', sender='',
                   date_from=None, date_to=None):
        """结构化查询邮件：按 主题 / 收件人 / 发件人 / 时间范围 组合筛选（暂不支持正文）

        各条件均为可选，传入非空即参与 AND 过滤；时间范围为「发送时间」的日期区间。

        参数：
            category<str|None>：限制搜索的分类（如已发送/草稿箱），None 为全部
            title<str>：主题关键词（LIKE 模糊）
            recipient<str>：收件人关键词（匹配收件人/抄送/密送的邮箱或展示名）
            sender<str>：发件人关键词（匹配发件人昵称或回信邮箱）
            date_from<str|None>：起始日期（YYYY-MM-DD）
            date_to<str|None>：截止日期（YYYY-MM-DD）

        返回：
            list<dict>：符合条件的邮件记录，按发送时间倒序
        """
        conds, params = [], []
        if category:
            conds.append('category=?')
            params.append(category)
        if title.strip():
            conds.append('title LIKE ?')
            params.append('%%%s%%' % title.strip())
        # 收件人匹配：展示列 recipient 或收件/抄送/密送任一包含关键词
        if recipient.strip():
            like = '%%%s%%' % recipient.strip()
            conds.append('(recipient LIKE ? OR to_list LIKE ? OR cc_list LIKE ? '
                         'OR bcc_list LIKE ?)')
            params.extend([like, like, like, like])
        # 发件人匹配：发件人昵称 from_name 或回信邮箱 return_email 包含关键词
        if sender.strip():
            like = '%%%s%%' % sender.strip()
            conds.append('(from_name LIKE ? OR return_email LIKE ?)')
            params.extend([like, like])
        # 时间范围：按发送时间的日期字段比较
        if date_from:
            conds.append("date(send_time) >= date(?)")
            params.append(date_from)
        if date_to:
            conds.append("date(send_time) <= date(?)")
            params.append(date_to)

        sql = 'SELECT * FROM mails'
        if conds:
            sql += ' WHERE ' + ' AND '.join(conds)
        sql += ' ORDER BY datetime(send_time) DESC, id DESC'
        with self.conn:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._rowToDict(r) for r in rows]

    def countByCategory(self):
        """统计各分类的邮件数量，返回 dict"""
        default = {CATEGORY_DRAFT: 0, CATEGORY_SENT: 0,
                   CATEGORY_DELETED: 0, CATEGORY_JUNK: 0}
        with self.conn:
            rows = self.conn.execute(
                'SELECT category, COUNT(*) AS cnt FROM mails GROUP BY category').fetchall()
        for r in rows:
            default[r['category']] = r['cnt']
        return default

    # ---------------- 更新 / 删除 ----------------
    def updateMail(self, mail_id, **fields):
        """按 id 更新邮件记录的指定字段（再次编辑回填用）"""
        list_fields = {'to_list', 'cc_list', 'bcc_list', 'attachment_paths'}
        dict_fields = {'inline_image_paths'}
        plain_fields = {'category', 'title', 'recipient', 'send_time',
                        'from_name', 'reply_to', 'return_email', 'html_text',
                        'deleted_at'}

        sets, params = [], []
        for key, value in fields.items():
            if key in plain_fields:
                sets.append('%s=?' % key)
                params.append(value)
            elif key in list_fields:
                sets.append('%s=?' % key)
                params.append(json.dumps(value or [], ensure_ascii=False))
            elif key in dict_fields:
                sets.append('%s=?' % key)
                params.append(json.dumps(value or {}, ensure_ascii=False))
            # 超出白名单的字段忽略，不更新
        if not sets:
            return False
        sets.append('created_at=created_at')
        params.append(mail_id)
        with self.conn:
            cur = self.conn.execute('UPDATE mails SET %s WHERE id=?' % ', '.join(sets), params)
        return cur.rowcount > 0

    def moveToCategory(self, mail_id, new_category):
        """移动邮件记录到新分类（如：保存草稿->已发送，删除->垃圾箱/已删除）

        移入「已删除」时记录 deleted_at（精确到分，秒统一为 00，便于 30 天整分清理）。
        """
        # 移入已删除：记下进入时间（截断到分，秒固定为 00）
        if new_category == CATEGORY_DELETED:
            return self.updateMail(
                mail_id,
                category=new_category,
                deleted_at=datetime.now().strftime('%Y-%m-%d %H:%M:00'))
        # 移出已删除（如恢复）：清空进入时间，重置 30 天计时
        return self.updateMail(mail_id, category=new_category, deleted_at='')

    def deleteMail(self, mail_id):
        """物理删除一条邮件记录"""
        with self.conn:
            cur = self.conn.execute('DELETE FROM mails WHERE id=?', (mail_id,))
        return cur.rowcount > 0

    def deleteMails(self, mail_ids):
        """批量物理删除多条邮件记录"""
        if not mail_ids:
            return 0
        placeholders = ','.join('?' for _ in mail_ids)
        with self.conn:
            cur = self.conn.execute('DELETE FROM mails WHERE id IN (%s)' % placeholders, mail_ids)
        return cur.rowcount

    def clearCategory(self, category):
        """清空某一分类下全部记录（如清空垃圾箱）"""
        with self.conn:
            cur = self.conn.execute('DELETE FROM mails WHERE category=?', (category,))
        return cur.rowcount

    def deleteExpired(self, category, days):
        """物理删除某分类下保存时间早于指定天数的记录（过期自动清理，如已删除保留30天）

        以「进入该分类的时间」(deleted_at) 为准，精度到分（秒参与比较，但进入时间
        本身秒固定为 00，故等价于整分判断）；旧数据无 deleted_at 时回退用 send_time。

        参数：
            category<str>：目标分类（如已删除）
            days<int>：保留天数，超过则该分类中这些天的旧记录被永久删除

        返回：
            int：被删除的记录条数
        """
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM mails WHERE category=? AND ("
                "CASE WHEN deleted_at <> '' THEN "
                " datetime(deleted_at) < datetime('now', '-' || ? || ' days') "
                "ELSE datetime(send_time) < datetime('now', '-' || ? || ' days') END)",
                (category, days, days))
        return cur.rowcount

    # ---------------- 工具 ----------------
    @staticmethod
    def _rowToDict(row):
        """将 sqlite3.Row 转成 dict，并解析 JSON 列表/字典字段"""
        if row is None:
            return None
        d = dict(row)
        for field in ('to_list', 'cc_list', 'bcc_list', 'attachment_paths'):
            d[field] = json.loads(d.get(field) or '[]')
        d['inline_image_paths'] = json.loads(d.get('inline_image_paths') or '{}')
        return d

    def close(self):
        """关闭数据库连接"""
        try:
            self.conn.close()
        except Exception:
            pass

    def __del__(self):
        """析构时自动关闭连接"""
        try:
            self.close()
        except Exception:
            pass


# 模块级便捷单例：便于多模块复用同一连接
_default_db = None


def getDb():
    """获取全局默认 MailDatabase 实例（懒加载单例）

    返回：
        MailDatabase：全局共享的数据库实例
    """
    global _default_db
    if _default_db is None:
        _default_db = MailDatabase()
    return _default_db