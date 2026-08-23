# -*- coding: utf-8 -*-
# 生成收件人批量导入的测试文件（TXT + XLSX）
# 用途：验证 activity.recipient_bulk.parseRecipientFile 能正确识别邮箱，
#       并容忍表头/说明等非邮箱内容的混入。生成的文件放于本 test 目录。
# 说明：本脚本生成的邮箱均为同域（example.com / testcorp.com）虚构地址，
#       仅用于本地检测逻辑验证，不会实际外发邮件。

import os
import random

# 保证可独立运行：把项目 src 加入 sys.path 以便导入
import sys
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 输出目录即当前 test 目录
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def buildRecipientList(count, seed=42):
    """构造 count 个去重的虚构邮箱列表（固定随机种子保证可复现）

    参数：
        count<int>：期望邮箱数量
        seed<int>：随机种子

    返回：
        list<str>：虚构邮箱列表
    """
    random.seed(seed)
    domains = ['example.com', 'testcorp.com', 'mail.cn', 'demo.org']
    users = ('user', 'staff', 'client', 'dev', 'sales', 'hrmail', 'support')
    emails, seen = [], set()
    while len(emails) < count:
        u = '%s%d' % (random.choice(users), random.randint(1, 99999))
        e = '%s@%s' % (u, random.choice(domains))
        if e not in seen:
            seen.add(e)
            emails.append(e)
    return emails


def genTxt(path, emails):
    """生成 TXT 收件人文件

    每行一个邮箱，另混入表头注释、空行与一行多邮箱（逗号分隔）用于验证鲁棒性。
    """
    lines = [
        '# 收件人列表（请仅放置收件人邮箱）',
        '## 以下为测试邮箱，共 %d 个' % len(emails),
        '',
    ]
    # 故意让前 6 个邮箱里有两个挤在同一行，测“一行多邮箱”的提取
    for i in range(0, len(emails), 2):
        if i + 1 < len(emails):
            lines.append('%s, %s' % (emails[i], emails[i + 1]))
        else:
            lines.append(emails[i])
    lines += ['', '# 结束']
    with open(path, 'w', encoding='utf-8') as fobj:
        fobj.write('\n'.join(lines))


def genXlsx(path, emails):
    """生成 XLSX 收件人文件：首列每个邮箱一格，并混入非邮箱单元格验证提取"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = '收件人'
    ws.append(['收件人邮箱列表'])
    ws.append(['请仅放置收件人邮箱'])
    for e in emails:
        ws.append([e])
    # 额外混入一个非法文本（不应被识别为邮箱）
    ws.append(['这不是邮箱 123456'])
    wb.save(path)


def main():
    """主入口：生成 TXT 与 XLSX 两份测试文件"""
    emails = buildRecipientList(1000)  # 生成 1000 个邮箱
    txt_path = os.path.join(OUT_DIR, 'recipients_test.txt')
    xlsx_path = os.path.join(OUT_DIR, 'recipients_test.xlsx')
    genTxt(txt_path, emails)
    genXlsx(xlsx_path, emails)
    print('已生成测试文件：')
    print('  TXT :', txt_path, '（含 %d 个邮箱）' % len(emails))
    print('  XLSX:', xlsx_path, '（含 %d 个邮箱）' % len(emails))
    return txt_path, xlsx_path


if __name__ == '__main__':
    main()