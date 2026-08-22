# -*- coding: utf-8 -*-
"""统一日志记录模块。

提供全局 Logger 单例，支持：
- 文件日志（按日期轮转，文件名 ``mydesk_debug_YYYYMMDD.log``）
- 内存环形缓冲（供调测工具 UI 实时展示）
- 自动捕获调用栈中的文件名、行号、函数名
- 线程安全（threading.Lock）

日志级别：DEBUG < INFO < WARNING < ERROR < CRITICAL
"""

import os
import sys
import threading
import traceback
from collections import deque
from datetime import datetime


# 日志级别常量
DEBUG = 'DEBUG'
INFO = 'INFO'
WARNING = 'WARNING'
ERROR = 'ERROR'
CRITICAL = 'CRITICAL'

# 级别排序（用于级别过滤）
_LEVEL_ORDER = {DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4}

# 项目根目录（utils/ 的上两级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 日志目录
_LOG_DIR = os.path.join(_PROJECT_ROOT, 'logs')

# 内存缓冲最大条数
_MAX_BUFFER = 2000


class _LogEntry:
    """单条日志记录（内存缓冲区元素）"""

    __slots__ = ('timestamp', 'level', 'source', 'message', 'traceback')

    def __init__(self, timestamp, level, source, message, traceback_str=None):
        self.timestamp = timestamp  # datetime 对象
        self.level = level          # DEBUG / INFO / WARNING / ERROR / CRITICAL
        self.source = source        # "filename.py:lineno funcname"
        self.message = message      # 日志正文
        self.traceback = traceback_str  # 异常 traceback 字符串（可选）

    def format(self):
        """格式化为单行显示文本（供 UI 展示）"""
        ts = self.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        line = f"[{ts}] [{self.level}] [{self.source}] {self.message}"
        if self.traceback:
            line += "\n" + self.traceback
        return line


class Logger:
    """全局日志记录器（单例）"""

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, log_dir=None, log_level=DEBUG):
        """初始化日志器（仅首次创建时执行）

        Args:
            log_dir: 日志目录路径，None 时使用默认 logs/ 目录
            log_level: 最低记录级别（低于此级别的日志不记录）
        """
        self._log_dir = log_dir or _LOG_DIR
        self._min_level = _LEVEL_ORDER.get(log_level, 0)
        self._buffer = deque(maxlen=_MAX_BUFFER)
        self._write_lock = threading.Lock()
        self._current_log_file = None
        self._current_log_date = None
        # 确保日志目录存在
        try:
            os.makedirs(self._log_dir, exist_ok=True)
        except OSError:
            pass

    @classmethod
    def get_instance(cls):
        """获取 Logger 单例（线程安全）"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = Logger()
        return cls._instance

    # ========== 公开 API ==========
    def debug(self, msg):
        self._log(DEBUG, msg)

    def info(self, msg):
        self._log(INFO, msg)

    def warning(self, msg):
        self._log(WARNING, msg)

    def error(self, msg, exc_info=False):
        """记录错误日志

        Args:
            msg: 错误消息
            exc_info: True 时自动捕获当前异常的 traceback（需在 except 块中调用）
        """
        tb_str = None
        if exc_info:
            tb_str = self._format_exception()
        self._log(ERROR, msg, traceback_str=tb_str)

    def critical(self, msg, exc_info=False):
        """记录致命错误日志（通常用于未捕获异常）"""
        tb_str = None
        if exc_info:
            tb_str = self._format_exception()
        self._log(CRITICAL, msg, traceback_str=tb_str)

    def get_recent_logs(self, level_filter=None, keyword=None, limit=500):
        """查询内存缓冲中的日志

        Args:
            level_filter: 允许的级别集合，如 {'ERROR', 'WARNING'}；None 表示全部
            keyword: 关键词过滤（不区分大小写），None 表示不过滤
            limit: 最多返回条数（从最新向前取）

        Returns:
            list[_LogEntry]: 日志条目列表（按时间正序）
        """
        with self._write_lock:
            entries = list(self._buffer)

        result = []
        for entry in entries:
            # 级别过滤
            if level_filter and entry.level not in level_filter:
                continue
            # 关键词过滤（匹配消息或来源）
            if keyword:
                kw_lower = keyword.lower()
                if kw_lower not in entry.message.lower() and kw_lower not in entry.source.lower():
                    continue
            result.append(entry)

        # 取最后 limit 条
        if limit and len(result) > limit:
            result = result[-limit:]
        return result

    def clear_display_buffer(self):
        """清空内存缓冲（仅影响 UI 显示，不影响文件日志）"""
        with self._write_lock:
            self._buffer.clear()

    def get_buffer_count(self):
        """返回当前内存缓冲区条数"""
        with self._write_lock:
            return len(self._buffer)

    def get_log_file_path(self):
        """返回当前日志文件路径"""
        self._ensure_log_file()
        return self._current_log_file

    def get_log_dir(self):
        """返回日志目录路径"""
        return self._log_dir

    # ========== 内部方法 ==========
    def _log(self, level, message, traceback_str=None):
        """记录一条日志（核心方法）"""
        # 级别过滤
        if _LEVEL_ORDER.get(level, 0) < self._min_level:
            return

        timestamp = datetime.now()
        source = self._get_caller_info()
        entry = _LogEntry(timestamp, level, source, message, traceback_str)

        with self._write_lock:
            # 写入内存缓冲
            self._buffer.append(entry)

        # 写入文件
        self._write_to_file(entry)

    def _get_caller_info(self):
        """获取调用栈中调用方的文件名、行号、函数名

        跳过 Logger 自身的方法帧（_log / debug / info / warning / error / critical）
        """
        try:
            stack = traceback.extract_stack()
            # 从栈顶往下找第一个不在本文件中的帧
            for frame in reversed(stack):
                if frame.filename != __file__ and 'logger.py' not in frame.filename:
                    filename = os.path.basename(frame.filename)
                    return f"{filename}:{frame.lineno} {frame.name}"
            return "unknown"
        except Exception:
            return "unknown"

    def _format_exception(self):
        """格式化当前异常的 traceback 字符串"""
        exc_type, exc_value, exc_tb = sys.exc_info()
        if exc_tb is None:
            return None
        lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        return ''.join(lines).rstrip()

    def _ensure_log_file(self):
        """确保日志文件已打开且日期正确（按天轮转）"""
        today = datetime.now().strftime('%Y%m%d')
        if self._current_log_date != today or self._current_log_file is None:
            self._current_log_date = today
            self._current_log_file = os.path.join(
                self._log_dir, f'mydesk_debug_{today}.log')

    def _write_to_file(self, entry):
        """将日志条目写入文件（每次打开-写入-关闭，避免文件句柄泄漏）"""
        try:
            self._ensure_log_file()
            line = entry.format() + '\n'
            with open(self._current_log_file, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            # 日志写入失败不应影响主程序
            pass
