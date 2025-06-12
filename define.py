#!/usr/local/bin/python3
# -*- coding: UTF-8 -*-
import datetime

# 소스에서 공통적으로 사용되는 define

############# 요일 관련 상수 정의 #############
TODAY = datetime.datetime.today().weekday()
SATURDAY = 5
SUNDAY = 6

############# 시간 관련 상수 정의 #############
T_NOW = datetime.datetime.now()
T_MARKET_START = T_NOW.replace(hour=9, minute=0, second=0, microsecond=0)   # 장 시작 9:00
T_MARKET_END = T_NOW.replace(hour=15, minute=30, second=0, microsecond=0)   # 장 종료 15:30

# "15:15" 까지 매수 안됐고 "현재가 <= 매수가"면 매수
T_BUY_AFTER = T_NOW.replace(hour=15, minute=15, second=0, microsecond=0)

# 종가 손절은 15:15분에 체크
T_LOSS_CUT = T_NOW.replace(hour=15, minute=15, second=0, microsecond=0)

# 장 종료 후 15:35분에 미체결 주문 없으면 종료 위해 
T_MARKET_END_ORDER_CHECK = T_NOW.replace(hour=15, minute=35, second=0, microsecond=0)

# 종가 매매 위해 16:00 에 종료
T_PROGRAM_EXIT = T_NOW.replace(hour=16, minute=00, second=0,microsecond=0)