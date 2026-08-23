# -*- coding: utf-8 -*-
# 业务逻辑：群发收件人批量导入（文件解析 + 合并）
# 作者：LF
# 创建时间：2026-08-23
# 说明：本模块为「收件人选择器」按钮响应之后的业务处理层，与 UI 解耦。
#       负责从 Excel/TXT 中读取并识别收件人邮箱、校验格式、去重合并。

import os
import re

# 常用邮箱分隔符（逗号/分号/制表符/换行）用于拆分“一行含多个邮箱”的场景
SEPARATOR_RE = re.compile(r'[,;\t，；]+')
# 邮箱提取正则：从任意文本中匹配邮箱地址（可同时命中单元格中多个邮箱）
EMAIL_FIND_RE = re.compile(
    r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
)


def isValidEmail(text):
    """判断字符串是否完全等于一个合法邮箱地址

    参数：
        text<str>：待校验字符串

    返回：
        bool：是否为合法邮箱
    """
    return bool(EMAIL_FIND_RE.fullmatch(text.strip()))


def extractEmails(text):
    """从任意文本中提取所有邮箱地址（可命中一行/一格内的多个邮箱）

    参数：
        text<str>：原始文本

    返回：
        list<str>：提取出的邮箱列表（保持出现顺序，不做去重）
    """
    if not text:
        return []
    return EMAIL_FIND_RE.findall(text)


def parseRecipientFile(path):
    """从 Excel(*.xlsx/*.xls) 或 TXT 文件读取并识别所有收件人邮箱

    约定：建议用户在文件内只放置收件人邮箱；即使误混入表头/说明文字，
          也会自动提取其中的邮箱、忽略其余内容。识别结果去重、保持顺序。

    参数：
        path<str>：收件人文件路径

    返回：
        list<str>：识别出的收件人邮箱列表（去重、保持原顺序）

    异常：
        ValueError：文件类型不支持时抛出
    """
    if not path:
        return []
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xls'):
        return _parseExcel(path)
    if ext in ('.txt', '.csv'):
        # TXT 与 CSV 均为按分隔符逐行读取的文本，走同一套提取逻辑
        return _parseTxt(path)
    raise ValueError('不支持的文件类型：%s（仅支持 Excel/CSV/TXT）' % ext)


def _parseTxt(path):
    """解析 TXT：逐行提取邮箱（一行可能含多个用分隔符隔开的邮箱）

    参数：
        path<str>：TXT 文件路径

    返回：
        list<str>：识别出的邮箱列表
    """
    emails = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as fobj:
        for line in fobj:
            # 按分隔符拆分后逐段提取邮箱，避免同一行内多个邮箱被合并吞掉
            for seg in SEPARATOR_RE.split(line):
                emails.extend(extractEmails(seg))
    return _dedupKeepOrder(emails)


def _parseExcel(path):
    """解析 Excel(*.xlsx/*.xls)：读取首张工作表所有单元格，提取邮箱

    参数：
        path<str>：Excel 文件路径

    返回：
        list<str>：识别出的邮箱列表
    """
    emails = []
    xlsx = path.lower().endswith('.xlsx')
    if xlsx:
        emails = _parseXlsx(path)
    else:
        emails = _parseXls(path)
    return _dedupKeepOrder(emails)


def _parseXlsx(path):
    """解析 .xlsx：使用 openpyxl 读取所有工作表全部单元格值并提取邮箱

    参数：
        path<str>：xlsx 文件路径

    返回：
        list<str>：单元格中提取出的邮箱列表（跨 sheet 汇总）
    """
    import openpyxl
    found = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        # 遍历所有工作表（sheet），避免邮箱分布在非首个 sheet 时漏读
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for cell in row or ():
                    if cell is None:
                        continue
                    text = str(cell).strip()
                    found.extend(extractEmails(text))
    finally:
        wb.close()
    return found


def _parseXls(path):
    """解析 .xls（旧版二进制）：优先用 xlrd，失败时回退提示

    参数：
        path<str>：xls 文件路径

    返回：
        list<str>：单元格中识别出的邮箱列表
    """
    found = []
    try:
        import xlrd
        wb = xlrd.open_workbook(path)
        # 遍历所有工作表，避免邮箱分布在非首个 sheet 时漏读
        for ws in wb.sheets():
            for r in range(ws.nrows):
                for c in range(ws.ncols):
                    val = ws.cell_value(r, c)
                    if val is None:
                        continue
                    text = str(val).strip()
                    found.extend(extractEmails(text))
    except ImportError:
        # xlrd 未安装时给出更友好的提示
        raise ValueError('解析旧版 .xls 需要安装 xlrd 库；建议另存为 .xlsx 后重新选择。')
    return found


def _dedupKeepOrder(items):
    """对列表去重（保持首次出现顺序）

    参数：
        items<list<str>>：原始列表

    返回：
        list<str>：去重后的列表
    """
    seen, result = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            result.append(it)
    return result


def splitRecipients(text):
    """按分隔符拆分收件人输入框文本为片段列表（滤空、去两侧空白）

    单一数据源约定：输入框文本是收件人的唯一事实来源，所有「查看/管理」操作
    都以拆分结果为基准，避免输入框与列表状态不一致。

    参数：
        text<str>：收件人输入框当前文本

    返回：
        list<str>：非空片段列表（仍保持原始顺序）
    """
    if not text:
        return []
    return [tok.strip() for tok in SEPARATOR_RE.split(text) if tok.strip()]


def validateRecipients(tokens):
    """校验一组收件人片段，区分为合法与非法两类

    用于识别用户手误删除字符导致的非法邮箱，便于上层标红提示。

    参数：
        tokens<list<str>>：收件人片段列表

    返回：
        tuple<list<str>, list<str>>：(合法邮箱列表, 非法片段列表)，均保持原始顺序
    """
    valid, invalid = [], []
    for tok in tokens:
        if isValidEmail(tok):
            valid.append(tok)
        else:
            invalid.append(tok)
    return valid, invalid


def mergeRecipients(current_text, selected):
    """合并已有收件人文本与勾选新增收件人，返回合并后的收件人串

    逻辑：拆分已有文本（兼容中英文逗号/分号）→ 追加勾选新增（去重、滤空）→ 用分号拼接。

    参数：
        current_text<str>：收件人框当前文本
        selected<list<str>>：本次勾选的新增收件人

    返回：
        str：合并后的收件人串（分号分隔）；无任何有效项时返回空串
    """
    # 拆分已有文本：兼容英文/中文逗号与分号（与拼接时统一使用的中文分号/英文逗号对应）
    existing = [tok for tok in (t.strip() for t in SEPARATOR_RE.split(current_text)) if tok]
    new_part = [e for e in selected if e not in existing]
    return '; '.join(existing + new_part)


def sortRecipients(emails, by_letter=False):
    """按首字母（A-Z，不区分大小写）对收件人列表排序

    参数：
        emails<list<str>>：收件人邮箱列表
        by_letter<bool>：True 按首字母排序；False 保持原顺序

    返回：
        list<str>：排序后的列表
    """
    if not by_letter:
        return list(emails)
    return sorted(emails, key=lambda e: e.lower())


def filterRecipients(emails, keyword=''):
    """按关键字筛选收件人，保留包含该关键字（忽略大小写）的邮箱

    参数：
        emails<list<str>>：收件人邮箱列表
        keyword<str>：筛选关键字；为空时返回全部

    返回：
        list<str>：筛选中含关键字的邮箱列表
    """
    kw = (keyword or '').strip()
    if not kw:
        return list(emails)
    return [e for e in emails if kw.lower() in e.lower()]