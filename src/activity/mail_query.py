# -*- coding: utf-8 -*-
# 业务逻辑：邮件查询（按 主题/收件人/发件人/时间范围）的条件构建与执行
# 作者：LF
# 创建时间：2026-08-23
# 说明：本模块为「查询」按钮响应之后的业务处理层，与 UI 解耦。
#       负责把用户在前端收集到的查询条件整理后交给数据库执行。

CATEGORY_SENT = 'sent'      # 已发送（供默认判断使用）
CATEGORY_DRAFT = 'draft'    # 草稿箱
CATEGORY_DELETED = 'deleted'  # 已删除


def queryEmails(db, category, condition):
    """按条件查询邮件，返回符合的邮件记录列表

    参数：
        db：MailDatabase 实例
        category<str|None>：限定的分类；None 表示不限制（按调用方当前分类传入）
        condition<dict>：查询条件，可含 title / recipient / sender / date_from / date_to

    返回：
        list<dict>：符合条件、按发送时间倒序的邮件记录
    """
    return db.queryMails(
        category=category,
        title=condition.get('title') or '',
        recipient=condition.get('recipient') or '',
        sender=condition.get('sender') or '',
        date_from=condition.get('date_from'),
        date_to=condition.get('date_to'),
    )