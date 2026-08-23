# -*- coding: utf-8 -*-
# 数据库层全流程测试脚本
# 作者：LF
# 创建时间：2026-08-23
# 功能：验证 MailDatabase 的建表、插入、按分类查询、搜索、更新（再次编辑回填）、
#       移动分类、统计、物理删除、批量删除、清空分类等全流程。
#       使用独立临时数据库文件，测试完自动清理，不污染真实数据。
# 运行方式：python src/database/runTest.py

import os
import sys
import tempfile

# 将 src 加入 sys.path（以数据库包方式导入会用到 path_manager）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import (
    MailDatabase, CATEGORY_DRAFT, CATEGORY_SENT, CATEGORY_DELETED,
)


def runAll():
    """执行数据库全流程各项断言测试，任一步失败则抛出并标记失败"""
    fail_count = 0

    def check(name, cond):
        nonlocal fail_count
        mark = 'PASS' if cond else 'FAIL'
        if not cond:
            fail_count += 1
        print('[%s] %s' % (mark, name))

    # 使用临时数据库文件，避免写入真实 /data/email_helper.db
    temp_path = os.path.join(tempfile.gettempdir(), 'email_helper_test.db')
    if os.path.exists(temp_path):
        os.remove(temp_path)
    db = MailDatabase(db_path=temp_path)

    # 1. 建表 + 空查询
    check('建表后草稿箱为空', len(db.getMails(CATEGORY_DRAFT)) == 0)

    # 2. 插入草稿（供再次编辑回填/搜索）
    draft_id = db.insertMail(
        category=CATEGORY_DRAFT,
        title='项目进度周报草稿',
        recipient='leader@company.com',
        from_name='LIangkai',
        to_list=['leader@company.com'],
        cc_list=['team@company.com'],
        html_text='<p>本周进度：功能已完成。</p>',
        attachment_paths=['C:/tmp/report.pdf'],
        inline_image_paths={'p1': 'C:/tmp/p1.png'},
    )
    check('插入草稿返回自增 id', draft_id >= 1)

    # 3. 插入一条已发送（供列表展示/搜索/移动）
    sent_id = db.insertMail(
        category=CATEGORY_SENT,
        title='合作方案 v3',
        recipient='amy@company.com',
        to_list=['amy@company.com'],
        html_text='<p>请查收最新合作方案。</p>',
    )
    check('插入已发送返回 id', sent_id >= draft_id)

    # 4. 按分类查询
    drafts = db.getMails(CATEGORY_DRAFT)
    sents = db.getMails(CATEGORY_SENT)
    check('分类查询草稿 1 条', len(drafts) == 1)
    check('分类查询已发送 1 条', len(sents) == 1)
    check('草稿列表返回字段解析(收件人)', drafts[0]['to_list'] == ['leader@company.com'])
    check('草稿 json 附件解析', drafts[0]['attachment_paths'] == ['C:/tmp/report.pdf'])
    check('草稿 json 图片映射解析', drafts[0]['inline_image_paths'] == {'p1': 'C:/tmp/p1.png'})

    # 5. 搜索（主题命中）
    hit = db.searchMails('周报', CATEGORY_DRAFT)
    check('按关键词搜索主题命中', len(hit) == 1 and hit[0]['id'] == draft_id)
    # 搜索（收件人命中）
    hit2 = db.searchMails('amy', CATEGORY_SENT)
    check('按关键词搜索收件人命中', len(hit2) == 1)
    # 搜索（无命中）
    hit3 = db.searchMails('不存在关键词', CATEGORY_DRAFT)
    check('搜索无命中返回空', len(hit3) == 0)

    # 6. 更新（再次编辑回填：改主题与正文）
    upd_ok = db.updateMail(draft_id, title='项目进度周报草稿(改)', html_text='<p>改过正文</p>')
    check('更新邮件字段', upd_ok is True)
    updated = db.getMail(draft_id)
    check('更新后主题生效', updated['title'] == '项目进度周报草稿(改)')
    check('更新后正文生效', updated['html_text'] == '<p>改过正文</p>')

    # 7. 移动分类（发送成功：草稿 -> 已发送）
    mv_ok = db.moveToCategory(draft_id, CATEGORY_SENT)
    check('移动草稿到已发送', mv_ok is True)
    after_move = db.getMails(CATEGORY_SENT)
    check('已发送现含 2 条', len(after_move) == 2)
    check('草稿箱现为 0 条', len(db.getMails(CATEGORY_DRAFT)) == 0)

    # 8. 统计各分类数量
    counts = db.countByCategory()
    check('统计已发送=2', counts[CATEGORY_SENT] == 2)
    # 移一条进已删除（模拟用户从已发送删除）
    db.moveToCategory(sent_id, CATEGORY_DELETED)
    counts = db.countByCategory()
    check('统计已删除=1', counts[CATEGORY_DELETED] == 1)
    check('统计草稿=0', counts[CATEGORY_DRAFT] == 0)

    # 9. 物理删除单条（当前已发送里只有 1 条 = 原先草稿那条，删后应为 0）
    del_ok = False
    cur_sents = db.getMails(CATEGORY_SENT)
    did = cur_sents[0]['id'] if cur_sents else None
    if did:
        del_ok = db.deleteMail(did)
        check('物理删除单条', del_ok is True)
        check('删除后已发送=0', len(db.getMails(CATEGORY_SENT)) == 0)

    # 10. 批量删除
    ids = [s['id'] for s in db.getMails(CATEGORY_SENT)]
    if ids:
        n = db.deleteMails(ids)
        check('批量删除条数正确', n == len(ids))
        check('批量删除后已发送=0', len(db.getMails(CATEGORY_SENT)) == 0)

    # 11. 清空分类（已删除）
    db.moveToCategory(sent_id, CATEGORY_DELETED)
    cleared = db.clearCategory(CATEGORY_DELETED)
    check('清空分类条数', cleared >= 1)
    check('清空后已删除=0', len(db.getMails(CATEGORY_DELETED)) == 0)

    db.close()
    # 清理临时库文件
    for ext in ('', '-wal', '-shm'):
        p = temp_path + ext
        if os.path.exists(p):
            os.remove(p)

    print('\n' + '=' * 40)
    if fail_count == 0:
        print('全部数据库测试通过')
        return 0
    print('%d 项测试失败' % fail_count)
    return 1


if __name__ == '__main__':
    sys.exit(runAll())