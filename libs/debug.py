import inspect
from datetime import datetime
import os
from PyQt5 import QtWidgets
import logging
import sys
from logging.handlers import RotatingFileHandler
import colorlog     # 터미널에 텍스트 color 세팅

PRINT_LEVEL_DEBUG       = 10
PRINT_LEVEL_INFO        = 20
PRINT_LEVEL_WARNING     = 30
PRINT_LEVEL_ERROR       = 40
PRINT_LEVEL_CRITICAL    = 50

# Create logger
logger = logging.getLogger()

# 로그 레벨 설정 (DEBUG, INFO, WARNING, ERROR, CRITICAL), 세팅 LEVEL 이상만 logging
logger.setLevel(logging.DEBUG)

# output format
formatter = logging.Formatter('%(message)s')

# stream handler
streamHandler = logging.StreamHandler(sys.stdout)
streamHandler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(message)s",
    log_colors={
        'DEBUG': 'white',
        'INFO': 'light_yellow',
        'WARNING': 'yellow',
        'ERROR': 'light_red',
        'CRITICAL': 'red,bg_white',
    }
))

LOG_FOLDER = '.\\log'
LOG_FILE = LOG_FOLDER + '\\SystemTrading.log'

# log 폴더 없으면 만들기
if not os.path.exists(LOG_FOLDER):
    os.mkdir(LOG_FOLDER)

# RotatingFileHandler 생성
max_bytes = 1048576     # 각 로그 파일의 최대 크기 (바이트 단위)
backup_count = 5        # 유지할 백업 로그 파일의 개수
fileHandler = RotatingFileHandler(LOG_FILE, maxBytes=max_bytes, backupCount=backup_count, mode='a')
fileHandler.setFormatter(formatter)

# add handler
logger.addHandler(streamHandler)
logger.addHandler(fileHandler)

# Suppress logs from urllib3 and requests
# urllib3 및 requests 로거의 로그 레벨을 WARNING으로 설정하여 DEBUG 및 INFO 수준의 메시지가 표시되지 않도록 합니다. 
# 이를 통해 "Starting new HTTPS connection"과 같은 메시지를 비활성화할 수 있습니다.
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

global outputh
outputh: QtWidgets.QTextBrowser = None    

def PRINT_DEBUG(msg):
    PrintMsg(msg, PRINT_LEVEL_DEBUG)
    
def PRINT_INFO(msg):
    PrintMsg(msg, PRINT_LEVEL_INFO)
    
def PRINT_WARN(msg):
    PrintMsg(msg, PRINT_LEVEL_WARNING)
    
def PRINT_ERR(msg):
    PrintMsg(msg, PRINT_LEVEL_ERROR)

def PRINT_CRITICAL(msg):
    PrintMsg(msg, PRINT_LEVEL_CRITICAL)
    
# main winodw 의 QTextBrowser widget 에 msg 출력하기위해 해당 widget 의 handle 을
# 이 module 의 다른 함수에서 사용할 수 있도록 global 로 handle 을 세팅
def SetOutputHandle(handle: QtWidgets.QTextBrowser):
    global outputh
    outputh = handle

def PrintMsg(msg: str, print_level: int):
    msg = str(msg)
    f = inspect.currentframe()
    i = inspect.getframeinfo(f.f_back.f_back)
    if print_level >= PRINT_LEVEL_ERROR:
        msg = datetime.now().strftime("[%m/%d %H:%M:%S]") + ' [' + os.path.basename(i.filename) + '] [' + i.function + '] [' + str(i.lineno) + '] [ERR] ' + msg
        if outputh != None:
            # ERR 는 red 표시
            outputh.append(f'<span style=\" color: #ff0000;\"> {msg} </span>')
    elif print_level >= PRINT_LEVEL_INFO:
        msg = datetime.now().strftime("[%m/%d %H:%M:%S]") + ' [' + os.path.basename(i.filename) + '] [' + i.function + '] [' + str(i.lineno) + '] ' + msg
        # ouput widget 에 msg 출력
        if outputh != None:
            outputh.append(msg)
    else:
        # PRINT_LEVEL_INFO 이상만 ouput widget 에 msg 출력
        msg = datetime.now().strftime("[%m/%d %H:%M:%S]") + ' [' + os.path.basename(i.filename) + '] [' + i.function + '] [' + str(i.lineno) + '] ' + msg
        # 터미널에는 출력
        # print(msg)
    
    if print_level == PRINT_LEVEL_CRITICAL:
        logger.critical(msg)
    elif print_level == PRINT_LEVEL_ERROR:
        logger.error(msg)
    elif print_level == PRINT_LEVEL_WARNING:
        logger.warning(msg)
    elif print_level == PRINT_LEVEL_INFO:
        logger.info(msg)
    elif print_level == PRINT_LEVEL_DEBUG:
        logger.debug(msg)