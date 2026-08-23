# -*- coding: utf-8 -*-
# 业务逻辑：群发收件人批量导入（文件解析 + 合并）
# 作者：LF
# 创建时间：2026-08-23
# 说明：本模块为「收件人选择器」按钮响应之后的业务处理层，与 UI 解耦。
#       负责从 Excel/TXT 中读取并识别收件人邮箱、校验格式、去重合并。

import os
import re

# 常见顶部非邮箱行忽略阈值：文件前 N 行若不含邮箱则跳过表头/说明
SKIP_EMPTY_THRESHOLD = 0
# 简易邮箱正则：匹配常见邮箱格式（用于识别单元格中是否为邮箱）
EMAIL_RE = re.compile(
    r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
)
# 收件人分隔正则：匹配英文/中文逗号与分号（用于拆分收件人输入串）
SEPARATOR_RE = re.compile(r'[,;，；]+')


def isValidEmail(text):
    """判断字符串是否为合法邮箱地址

    参数：
        text<str>：待校验字符串

    返回：
        bool：是否为合法邮箱
    """
    return bool(EMAIL_RE.match(text.strip()))


def parseRecipientFile(path):
    """从 Excel(*.xlsx/*.xls) 或 TXT 文件读取并识别所有收件人邮箱

    约定：文件内只应包含收件人邮箱，读取后逐格扫描，仅保留合法邮箱；
          非邮箱文本（表头/说明/空行）自动忽略。

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
    if ext == '.txt':
        return _parseTxt(path)
    raise ValueError('不支持的文件类型：%s（仅支持 Excel/TXT）' % ext)


def _parseTxt(path):
    """解析 TXT：逐行读取，从中识别合法邮箱

    参数：
        path<str>：TXT 文件路径

    返回：
        list<str>：识别出的邮箱列表
    """
    emails = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as fobj:
        for line in fobj:
            token = line.strip()
            if isValidEmail(token):
                emails.append(token)
    return _dedupKeepOrder(emails)


def _parseExcel(path):
    """解析 Excel(*.xlsx/*.xls)：读取首张工作表所有单元格，识别合法邮箱

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
    """解析 .xlsx：使用 openpyxl 读取整个首表所有单元格值

    参数：
        path<str>：xlsx 文件路径

    返回：
        list<str>：单元格中识别出的邮箱列表
    """
    import openpyxl
    found = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        for row in ws.iter_rows(values_only=True):
            for cell in row or ():
                if cell is None:
                    continue
                # 兼容单元格为数字（如邮箱写成文本时才为字符串；数字单元格填数字串忽略）
                text = str(cell).strip()
                if isValidEmail(text):
                    found.append(text)
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
        ws = wb.sheet_by_index(0)
        for r in range(ws.nrows):
            for c in range(ws.ncols):
                val = ws.cell_value(r, c)
                if val is None:
                    continue
                text = str(val).strip()
                if isValidEmail(text):
                    found.append(text)
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