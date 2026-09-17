"""运行日志：写入工程根目录 log/ 下的轮转文件，同时输出到控制台。

隐私边界与 server.py 的既有约定一致：只记录请求路径、任务名、状态与异常栈，
不记录查询串、请求正文、用户文档正文和任何密钥值。日志目录可用 APP_LOG_DIR 覆盖。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = 'supplier'
FILENAME = 'app.log'
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
FORMAT = '%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s'
DATEFMT = '%Y-%m-%d %H:%M:%S'

# 作为库被导入时不产生输出；setup_logging 会替换为真实处理器。
logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())


def log_directory(root=None):
    """返回日志目录，可按 APP_LOG_DIR 覆盖。"""
    if os.getenv('APP_LOG_DIR'):
        return Path(os.getenv('APP_LOG_DIR'))
    return Path(root) / 'log' if root else Path.cwd() / 'log'


def log_level():
    name = os.getenv('APP_LOG_LEVEL', 'INFO').upper()
    return getattr(logging, name, logging.INFO) if isinstance(getattr(logging, name, None), int) else logging.INFO


def setup_logging(root=None, level=None):
    """建立 log/ 与轮转日志文件，重复调用不会叠加处理器。"""
    directory = log_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level or log_level())
    logger.propagate = False
    for handler in list(logger.handlers):
        if isinstance(handler, logging.NullHandler):
            logger.removeHandler(handler)
        elif getattr(handler, '_supplier_managed', False):
            logger.removeHandler(handler)
            handler.close()
    formatter = logging.Formatter(FORMAT, DATEFMT)
    file_handler = RotatingFileHandler(directory / FILENAME, maxBytes=MAX_BYTES,
                                       backupCount=BACKUP_COUNT, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler._supplier_managed = True
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler._supplier_managed = True
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def get_logger(suffix=None):
    """取子日志器，例如 get_logger('runtime') -> supplier.runtime。"""
    return logging.getLogger(LOGGER_NAME + ('.' + suffix if suffix else ''))
