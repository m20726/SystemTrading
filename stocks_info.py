import copy
import time
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from prettytable import PrettyTable
from handle_json import *
from libs.debug import *
import datetime
import traceback
from datetime import date, timedelta
import inspect
import threading
from define import *
from concurrent.futures import ThreadPoolExecutor

# 2025.03.05 기준 원금 460만원

#TODO: 한투MTS 에서 주문 취소 경우 처리
# self.stocks[code]['buy_order_done'] = False
# self.stocks[code]['sell_order_done'] = False

##############################################################
#                           전략                             #
##############################################################
# 매수
#   1차 매수
#       1. 20,60,90 정배열
#       2. Envelope X 값 이하에서 트레일링스탑 1차 매수
# 매도
#   목표가에 반 매도
#   나머지는 익절가 이탈 시 전량 매도
#       목표가 올려가며 남은 물량의 1/2 매도
#       N차 매도가 : N-1차 매도가 * 1.0x (N>=2)
# 손절
#   1. last차 매수가 -5% 장중 이탈
#   2. 오늘 > 최근 매수일 + x day, 즉 x 일 동안 매수 없고
#       1차 매도가 안됐고 last차 매수까지 안된 경우 손절


##############################################################
#                       Config                               #
##############################################################
# 분할 매수 횟수
BUY_SPLIT_COUNT = 2
# 분할 매도 획수
SELL_SPLIT_COUNT = 2

# 2차 매수 물타기
BUY_SPLIT_STRATEGY_DOWN = 0
# 2차 매수 불타기
BUY_SPLIT_STRATEGY_UP = 1

# 매수량 1주만 매수 여부
BUY_QTY_1 = False

# 투자 전략 리스크
INVEST_RISK_LOW = 0
INVEST_RISK_MIDDLE = 1
INVEST_RISK_HIGH = 2

LOSS_CUT_P = 5                              # x% 이탈 시 손절
LOSS_CUT_P_BUY_2_DONE = 2                   # 불타기에서 2차 매수 완료 후 x% 이탈 시 손절
SELL_TARGET_P = 6                           # 1차 매도 목표가 %
NEXT_SELL_TARGET_MARGIN_P = 6               # N차 매도가 : N-1차 매도가 * (1 + MARGIN_P) (N>=2), ex) 2%
MIN_SELL_TARGET_P = 4                       # 최소 목표가 %

TAKE_PROFIT_P = 1                           # 익절가 %
BUY_MARGIN_P = 1                            # ex) 최저가 + x% 에서 매수
# SELL_MARGIN_P = 2                           # ex) 목표가 + x% 에서 매도

INVEST_TYPE = "real_invest"                 # sim_invest : 모의 투자, real_invest : 실전 투자
# INVEST_TYPE = "sim_invest"

if INVEST_TYPE == "real_invest":
    MAX_MY_STOCK_COUNT = 6
    INVEST_MONEY_PER_STOCK = 800000         # 종목 당 투자 금액(원)
else:
    MAX_MY_STOCK_COUNT = 10                 # MAX 보유 주식 수
    INVEST_MONEY_PER_STOCK = 2000000        # 종목 당 투자 금액(원)

# "현재가 - 매수가 gap" 이 X% 이하 경우만 매수 가능 종목으로 처리
# gap 이 클수록 종목이 많아 실시간 처리가 느려진다
BUYABLE_GAP_MAX = 15
BUYABLE_GAP_MIN = -20  # 액면 분할 후 거래 해제날 buyable gap 이 BUYABLE_GAP_MAX 보다 낮은 현상으로 매수되는 것 방지 위함

# 상위 몇개 종목까지 매수 가능 종목으로 유지
BUYABLE_COUNT = 10

# # 1차 매수 시 전일 대비율(현재 등락율)이 MAX_PRICE_CHANGE_RATE_P % 미만에서 매수
# # ex) -6% 미만
# MAX_PRICE_CHANGE_RATE_P = -4

# # 1차 매수 시 시가총액(억) 미만 경우 MAX_PRICE_CHANGE_RATE_P % 미만에서 매수
# PRICE_CHANGE_RATE_CHECK_MARKET_CAP = 50000

# 1차 매수 시 하한가 매수 금지 위해 전일 대비율(현재 등락율)이 MIN_PRICE_CHANGE_RATE_P % 이상에서 매수
MIN_PRICE_CHANGE_RATE_P = -20

##############################################################

STOCKS_INFO_FILE_PATH = './stocks_info.json'    # 주식 정보 file
CONFIG_FILE_PATH = './config.json'              # APP_KEY, APP_SECRET 등 투자 관련 설정 정보

# 어제 20 이평선 지지선 기준으로 오늘의 지지선 구하기 위한 상수
# ex) 오늘의 지지선 = 어제 20 이평선 지지선 * 0.993
MARGIN_20MA = 0.993

# 주식 일별 주문 체결 조회, 매도 매수 구분 코드
BUY_SELL_CODE = "00"    # 매수/매도 전체
SELL_CODE = "01"        # 매도
BUY_CODE = "02"         # 매수

# 주문 구분
ORDER_TYPE_LIMIT_ORDER = "00"               # 지정가
ORDER_TYPE_MARKET_ORDER = "01"              # 시장가
ORDER_TYPE_MARKETABLE_LIMIT_ORDER = "03"    # 최유리지정가
ORDER_TYPE_IMMEDIATE_ORDER = "04"           # 최우선지정가
ORDER_TYPE_BEFORE_MARKET_ORDER = "05"       # 장전 시간외(08:20~08:40)
ORDER_TYPE_AFTER_MARKET_ORDER = "06"        # 장후 시간외(15:30~16:00)

API_DELAY_S = 0.05                          # 실전 투자 계좌 : 초당 API 20회 제한, 모의 투자 계좌 초당 2회

# 체결 미체결 구분 코드
TRADE_ANY_CODE = "00"           # 체결 미체결 전체
TRADE_DONE_CODE = "01"          # 체결
TRADE_NOT_DONE_CODE = "02"      # 미체결

# 추세선
TREND_DOWN = 0      # 하락
TREND_SIDE = 1      # 보합
TREND_UP = 2        # 상승

# 이평선 배열
MA_DOWN_TREND = 0   # 역배열
MA_SIDE_TREND = 1   # 정배열도 역배열도 아님, 횡보
MA_UP_TREND = 2     # 정배열

# sort by
SORT_BY_NAME = 0
SORT_BY_UNDER_VALUE = 1

LOSS_CUT_MARKET_OPEN = 0        # 장중 손절
LOSS_CUT_MARKET_CLOSE = 1       # 종가 손절

MAX_REQUEST_RETRY_COUNT = 3         # request 실패 시 최대 retry 횟수

# ex) 20130414
TODAY_DATE = f"{datetime.datetime.now().strftime('%Y%m%d')}"

# 60이평선 상승 추세 판단 기울기
TREND_UP_DOWN_DIFF_60MA_P = 0.8     # ex) (recent ma - last ma) 기울기 x% 이상되어야 추세 up down
TREND_UP_CONSECUTIVE_DAYS = 10      # ex) 최근 5일 연속 상승 추세여야 매수 가능

# 90이평선 상승 추세 판단 기울기
TREND_UP_DOWN_DIFF_90MA_P = 0.3       # ex) 0.3%

MA_DIFF_P = 0.5                     # 이평선 간의 이격 ex) 60, 90 이평선 간에 1% 이격이상 있어야 정배열
DEFAULT_ENVELOPE_P = 15             # 1차 매수 시 envelope value
PRICE_TYPE_CLOSE = "stck_clpr"      # 종가
PRICE_TYPE_LOWEST = "stck_lwpr"     # 최저가

# 시장 시간 상태
BEFORE_MARKET = 0     # 장 전
MARKET_ING = 1        # 장 중
AFTER_MARKET = 2      # 장 후

##############################################################

class Trade_strategy:
    def __init__(self) -> None:
        self.invest_risk = INVEST_RISK_LOW                      # 투자 전략, high : 공격적, middle : 중도적, low : 보수적
        self.old_invest_risk = INVEST_RISK_LOW                  # 종목 체결로 보유 종목 수 변경 시 update_byable_stocks 실행은 old_invest_risk != invest_risk 일 때
        self.under_value = 0                                    # 저평가가 이 값 미만은 매수 금지
        self.gap_max_sell_target_price_p = 0                    # 목표가GAP 이 이 값 미만은 매수 금지
        self.sum_under_value_sell_target_gap = 0                # 저평가 + 목표가GAP 이 이 값 미만은 매수 금지
        self.max_per = 0                                        # PER가 이 값 이상이면 매수 금지
        self.buyable_market_cap = 10000                         # 시총 X 미만 매수 금지(억)
        self.buy_split_strategy = BUY_SPLIT_STRATEGY_DOWN       # 2차 분할 매수 전략(물타기, 불타기)
        self.buy_trailing_stop = False                          # 매수 시 트레일링 스탑으로 할지
        self.sell_trailing_stop = False                         # 매도 시 트레일링 스탑으로 할지
        self.trend_60ma = TREND_UP                              # 추세선이 이거 이상이여야 매수
        self.trend_90ma = TREND_UP                              # 추세선이 이거 이상이여야 매수
        self.use_trend_60ma = False                             # 60이평선 추세선 사용 여부
        self.use_trend_90ma = False                             # 90이평선 추세선 사용 여부
        self.loss_cut_time = LOSS_CUT_MARKET_OPEN               # 손절은 언제 할지
        
class Stocks_info:
    def __init__(self) -> None:
        self.stocks = dict()                            # 모든 종목의 정보
        self.my_stocks = dict()                         # 보유 종목
        self.buyable_stocks = dict()                    # 매수 가능 종목
        self.config = dict()                            # 투자 관련 설정 정보
        self.access_token = ""                  
        self.my_cash = 0                                # 주문 가능 현금 잔고

        # 분할 매수 비중(%), BUY_SPLIT_COUNT 개수만큼 세팅 
        self.buy_split_p = []
        for i in range(BUY_SPLIT_COUNT):
            self.buy_split_p.append(100/BUY_SPLIT_COUNT)

        self.buy_invest_money = list()
        self.buy_done_order_list = list()               # 매수 체결 완료 주문 list
        self.sell_done_order_list = list()              # 매도 체결 완료 주문 list
        self.this_year = datetime.datetime.now().year
        self.trade_strategy = Trade_strategy()

        # 매수 완료 시 handle_buy_stock 은 set_buy_done 완료까지 대기해야
        # 2차 매수 후 self.stocks[code]['buy_done'][1] = True 되기전에 
        # handle_buy_stock 가 실행 되어 추가로 매수되는거 방지할 수 있다
        self.buy_done_lock = threading.Lock()

        # 매도 완료 시 handle_sell_stock 은 set_sell_done 완료까지 대기해야
        self.sell_done_lock = threading.Lock()

        # self.my_stocks 를 for loop 으로 접근하는 동안 main thread 에서 update_my_stocks() 등으로 self.my_stocks 를 변경하면 오류 발생한다.
        # 따라서 for loop 끝날 때까지 self.my_stocks 를 변경하지 못하도록 처리
        self.my_stocks_lock = threading.Lock()

        self.buyable_stocks_lock = threading.Lock()

        self.request_lock = threading.Lock()

        self.before_trade_done_my_stock_count = 0       # 체결 전 보유 종목 수
        self.after_trade_done_my_stock_count = 0        # 체결 후 보유 종목 수
        self.my_stock_count = 0             # 보유 종목 수

        self.lowest_market_profit_p = 0         # 금일 최저 코스피 수익률
        self.market_profit_p = 0                # 코스피 수익률
        self.market_crash_profit_p = -4         # 주식 시장 폭락 기준% ex) -4 == -4%

        self.buy_sell_msg = dict()
        self.buy_sell_msg[BUY_SELL_CODE] = "매수/매도"
        self.buy_sell_msg[SELL_CODE] = "매도"
        self.buy_sell_msg[BUY_CODE] = "매수"

        self.request_retry_count = 0            # request 실패 시 retry 횟수
        # "005930" : 삼성전자
        # "477080" : RISE CD금리액티브
        # "010120" : LS ELECTRIC
        self.not_handle_stock_list = ["005930", "477080", "010120"]       # 매수,매도 등 처리하지 않는 종목, ex) 보유하지만 처리에서 제외 종목

        # 매수/매도에 의해 보유 현금이 변경되어 매수 가능/불가가 변경된 경우 매수 가능 종목 업데이트위해 판단
        self.available_buy_new_stock_count = 0
        self.old_available_buy_new_stock_count = 0

        self.str_trend = {0: "하락", 1: "보합", 2: "상승"}

    ##############################################################
    # 초기화 시 처리 할 내용
    ##############################################################
    def initialize(self):
        result = True
        msg = ""
        try:
            for i in range(BUY_SPLIT_COUNT):
                self.buy_invest_money.append(int(INVEST_MONEY_PER_STOCK * (self.buy_split_p[i] / 100)))

            self.load_stocks_info(STOCKS_INFO_FILE_PATH)
            self.init_config(CONFIG_FILE_PATH)
            self.access_token = self.get_access_token()
            self.my_cash = self.get_my_cash()       # 보유 현금 세팅
            self.init_trade_done_order_list()
            self.my_stock_count = self.get_my_stock_count()
            self.init_trade_strategy()                # 매매 전략 세팅
            self.market_profit_p = self.get_market_profit_p()
            self.available_buy_new_stock_count = self.get_available_buy_new_stock_count()
            self.old_available_buy_new_stock_count = self.available_buy_new_stock_count
            
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 전략 출력
    ##############################################################
    def print_strategy(self):
        PRINT_DEBUG('===============================')
        PRINT_INFO(f'Envelope {DEFAULT_ENVELOPE_P} 매매')
        invest_risk_msg = dict()
        invest_risk_msg[INVEST_RISK_LOW] = "보수적 전략"
        invest_risk_msg[INVEST_RISK_MIDDLE] = "중도적 전략"
        invest_risk_msg[INVEST_RISK_HIGH] = "공격적 전략"
        PRINT_INFO(f'{invest_risk_msg[self.trade_strategy.invest_risk]}')
        PRINT_DEBUG(f'저평가 {self.trade_strategy.under_value} 이상')
        PRINT_DEBUG(f'목표가GAP {self.trade_strategy.gap_max_sell_target_price_p} 이상')
        PRINT_DEBUG(f'저평가+목표가GAP {self.trade_strategy.sum_under_value_sell_target_gap} 이상')
        PRINT_DEBUG(f'시총 {self.trade_strategy.buyable_market_cap/10000}조 이상')
        if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:
            PRINT_DEBUG(f'{BUY_SPLIT_COUNT}차 매수 물타기')
        elif self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_UP:
            PRINT_DEBUG(f'{BUY_SPLIT_COUNT}차 매수 불타기')
        
        # 목표가 출력
        for i in range(BUY_SPLIT_COUNT):
            if i == 0:
                target_p = SELL_TARGET_P
                PRINT_DEBUG(f'{i + 1}차 목표가 {target_p} %')
            else:
                target_p = SELL_TARGET_P + (NEXT_SELL_TARGET_MARGIN_P * i)
                PRINT_DEBUG(f'{i + 1}차 목표가 {target_p} %')

        trend_msg = dict()
        trend_msg[TREND_DOWN] = "하락 추세"
        trend_msg[TREND_SIDE] = "보합 추세"
        trend_msg[TREND_UP] = "상승 추세"

        if self.trade_strategy.use_trend_60ma == True:
            PRINT_DEBUG(f'60일선 {trend_msg[self.trade_strategy.trend_60ma]} 이상 매수')

        if self.trade_strategy.use_trend_90ma == True:
            PRINT_DEBUG(f'90일선 {trend_msg[self.trade_strategy.trend_90ma]} 이상 매수')

        if BUY_QTY_1 == True:
            PRINT_DEBUG('1주만 매수')
        PRINT_DEBUG('===============================')

    ##############################################################
    # SEND_MSG_XXX
    #   send msg macro
    ##############################################################
    def SEND_MSG_DEBUG(self, msg, send_discode:bool = False):
        self.send_msg(msg, PRINT_LEVEL_DEBUG, send_discode, False)
        
    def SEND_MSG_INFO(self, msg, send_discode:bool = False):
        self.send_msg(msg, PRINT_LEVEL_INFO, send_discode, False)
        
    def SEND_MSG_ERR(self, msg, send_discode:bool = True):
        self.send_msg(msg, PRINT_LEVEL_ERROR, send_discode, True)

    ##############################################################
    # Print and send discode
    # Parameter :
    #       msg             출력 메세지
    #       print_level     PRINT LEVEL(DEBUG, INFO, ERR)
    #       send_discode    discode 전송 여부
    #       err             error 여부
    ##############################################################
    def send_msg(self, msg, print_level=PRINT_LEVEL_DEBUG, send_discode:bool = False, err:bool = False):
        result = True
        ex_msg = ""
        try:
            REQUESTS_POST_MAX_SIZE = 2000

            msg = str(msg)

            # 메세지 실행 func, line 출력
            f = inspect.currentframe()
            i = inspect.getframeinfo(f.f_back.f_back)
            msg = '[' + i.function + '] [' + str(i.lineno) + '] ' + msg

            if send_discode == True:
                # 데이터를 REQUESTS_POST_MAX_SIZE 바이트씩 나누기
                # ex) post message length 가 2000 보다 크면 에러
                chunks = [msg[i:i + REQUESTS_POST_MAX_SIZE] for i in range(0, len(msg), REQUESTS_POST_MAX_SIZE)]

                # 나눈 데이터를 순회하면서 POST 요청 보내기
                for chunk in chunks:
                    message = {"content": f"{chunk}"}
                    response = requests.post(self.config['DISCORD_WEBHOOK_URL'], data=message)
                    # 에러 처리 ex) message length 가 2000 보다 크면 에러
                    if response.status_code < 200 or response.status_code > 204:
                        PRINT_ERR(f'requests.post err {response.status_code}')

            if print_level >= PRINT_LEVEL_ERROR or err == True:
                PRINT_ERR(f"{msg}")
            elif print_level == PRINT_LEVEL_INFO:
                PRINT_INFO(f"{msg}")
            else:
                PRINT_DEBUG(f"{msg}")
        except Exception as ex:
            result = False
            ex_msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                PRINT_ERR(ex_msg)
                message = {"content": f"{ex_msg}"}
                requests.post(self.config['DISCORD_WEBHOOK_URL'], data=message)
        
    ##############################################################
    # 네이버 증권 기업실적분석 정보 얻기
    # param :
    #   code            종목 코드
    ##############################################################
    def crawl_naver_finance(self, code):
        result = True
        msg = ""
        try:
            req = requests.get('https://finance.naver.com/item/main.nhn?code=' + code)
            page_soup = BeautifulSoup(req.text, 'lxml')
            finance_html = page_soup.select_one('div.cop_analysis')
            th_data = [item.get_text().strip()
                    for item in finance_html.select('thead th')]
            # 2023 기준
            # ['2020.12', '2021.12', '2022.12', '2023.12(E)']
            annual_date = th_data[3:7]
            quarter_date = th_data[7:13]
            # ['주요재무정보', '최근 연간 실적', '최근 분기 실적', '매출액', '영업이익', '당기순이익', '영업이익률', '순이익률', 'ROE(지배주주)', '부채비율', '당좌비율', '유보율', 'EPS(원)', 'PER(배)', 'BPS(원)', 'PBR(배)', '주당배당금(원)', '시가배당률(%)', '배당성향(%)']
            finance_index = [item.get_text().strip() for item in finance_html.select('th.h_th2')][3:]
            finance_data = [item.get_text().strip() for item in finance_html.select('td')]
            # 숫자에 , 를 없애야 int() 처리 가능
            for i in range(len(finance_data)):
                # 공백 데이터는 '0'으로 처리
                if finance_data[i] == '':
                    finance_data[i] = '0'
                else:
                    finance_data[i] = finance_data[i].replace(',', '')
            finance_data = np.array(finance_data)
            finance_data.resize(len(finance_index), 10)
            finance_date = annual_date + quarter_date
            finance = pd.DataFrame(data=finance_data[0:, 0:], index=finance_index, columns=finance_date)
            annual_finance = finance.iloc[:, :4]
            return annual_finance
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 네이버 증권 기업실적분석 년도 가져오기
    #   2024년이지만 2024.02 현재 2024.12(E) 데이터 없는 경우 많다. 2023.12(E) 까지만 있다
    #   따라서 최근 data, index 3 의 데이터를 기준으로 한다
    #   2023년 기준 2023.12(E)
    #   2023년 기준 2022.12, 작년 데이터 얻기
    #   2023년 기준 2021.12, 재작년 데이터 얻기
    # param :
    #   code            종목 코드
    ##############################################################
    def get_naver_finance_year_column_texts(self, code):
        result = True
        msg = ""
        try:
            recent_year_column_text = ""
            last_year_column_text = ""
            the_year_before_last_column_text = ""

            annual_finance = self.crawl_naver_finance(code)
            recent_year_index = 3
            for i, key in enumerate(annual_finance.columns):
                if i == recent_year_index:
                    recent_year_column_text = key
                    break
                # 매출액 1년 전, 2년 전 구하기 위함
                elif i == (recent_year_index - 1):
                    # 1년 전 ex) 2023 기준 2022.12
                    last_year_column_text = key
                elif i == (recent_year_index - 2):
                    # 2년 전 ex) 2023 기준 2021.12
                    the_year_before_last_column_text = key
                else:
                    pass
            return recent_year_column_text, last_year_column_text, the_year_before_last_column_text
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # requests 성공 여부
    # param :
    #   res         response object
    ##############################################################
    def is_request_ok(self, res):
        if res.json()['rt_cd'] == '0':
            return True
        else:
            return False

    ##############################################################
    # percent 값 리턴
    #   ex) to_percent(10) return 0.1
    # param :
    #   percent         이 값을 %로 변경
    ##############################################################
    def to_percent(self, percent):
        return percent / 100

    ##############################################################
    # 주식 호가 단위로 가격 변경
    #   5,000원 미만                    5원
    #   5,000원 이상 10,000원 미만      10원
    #   10,000원 이상 50,000원 미만	    50원
    #   50,000원 이상 100,000원 미만	100원
    #   100,000원 이상 500,000원 미만   500원
    #   500,000원 이상                 1000원
    # param :
    #   price       주식 호가 단위로 변경할 가격
    ##############################################################
    def get_stock_asking_price(self, price):
        if price < 5000:
            unit = 5
        elif price >= 5000 and price < 10000:
            unit = 10
        elif price >= 10000 and price < 50000:
            unit = 50
        elif price >= 50000 and price < 100000:
            unit = 100
        elif price >= 10000 and price < 500000:
            unit = 500
        elif price > 500000:
            unit = 1000
        return int(round(price / unit) * unit)      # 소수 첫째 자리에서 반올림

    ##############################################################
    # self.invest_type 에 맞는 config 설정
    # param :
    #   file_path       config file path
    ##############################################################
    def init_config(self, file_path):
        result = True
        msg = ""
        try:        
            configs = read_json_file(file_path)
            self.config = configs[INVEST_TYPE]
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)        

    ##############################################################
    # stocks file 에서 stocks 정보 가져온다
    # param :
    #   file_path       stock file path    
    ##############################################################
    def load_stocks_info(self, file_path):
        result = True
        msg = ""
        try:         
            self.stocks = read_json_file(file_path)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # stocks 정보를 stocks file 에 저장
    # param :
    #   file_path       stock file path      
    ##############################################################
    def save_stocks_info(self, file_path):
        result = True
        msg = ""
        try:         
            write_json_file(self.stocks, file_path)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 공격적인 매수 가능 환경이면 1차 매수가를 공격적으로 세팅
    #   ex) 90일선 상승추세 and 시총 > 1조 and 매수가 > 90일선
    # Parameter :
    #       code            종목 코드
    # Return : 공격적 매수가격 세팅했으면 True, 아니면 False
    ##############################################################
    def set_aggressive_first_buy_price(self, code):
        result = True
        msg = ""
        ret = False
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            # 1차 매수가 이미 됐으면 리턴
            if stock['buy_done'][0] == True:
                return False
            
            # 공격적 매수 시 시총 기준
            AGREESIVE_BUY_MARKET_CAP = 10000    # 단위:억

            if self.trade_strategy.use_trend_90ma == True:
                # 90일선 상승 추세 and 시총 체크
                if stock['trend_90ma'] == TREND_UP and stock['market_cap'] > AGREESIVE_BUY_MARKET_CAP:
                    # 공격적 매수가를 위해 envelope 는 기존 전략에 비해 적다
                    # 더 일찍 매수
                    AGREESIVE_BUY_ENVELOPE = 10
                    # 공격적 매수 시 급락 가격은 한달 내 최고 종가에서 x% 빠졌을 때
                    AGREESIVE_BUY_PLUNGE_PRICE_MARGIN_P = 20

                    envelope_p = self.to_percent(AGREESIVE_BUY_ENVELOPE)
                    envelope_support_line = stock['yesterday_20ma'] * (1 - envelope_p)

                    # 1차 매수가는 단기간에 급락한 가격 이하여야한다.
                    aggresive_buy_price = min(int(envelope_support_line * MARGIN_20MA), self.get_plunge_price(code, self.to_percent(AGREESIVE_BUY_PLUNGE_PRICE_MARGIN_P)))

                    # 1차 매수가 정할 때 비교되는 90일선은 장중, 장전/장후 에 따라 다르다
                    # 장 중 : 금일 90일선
                    # 장 전 or 장 마감 후 : 금일 90일선 * 보정값으로 
                    # 장 전(08:40) self.get_ma(code, 90) == self.get_ma(code, 90, 1) == 어제 90일선
                    # 장마감 후 self.get_ma(code, 90, 1) 값은 어제 90일선이다.
                    price_90ma = self.get_ma(code, 90)
                    if self.get_market_time_state() != MARKET_ING:
                        MARGIN_TOMORROW_UP_90MA = 1.0009
                        price_90ma = int(price_90ma * MARGIN_TOMORROW_UP_90MA)

                    # 공격적 매수가가 90일선 보다 높으면 공격적 매수 가능
                    if aggresive_buy_price > price_90ma:
                        PRINT_INFO(f"[{stock['name']}] 공격적 매수가 세팅, {aggresive_buy_price}(매수가) > {price_90ma}(90일선)")
                        stock['buy_price'][0] = aggresive_buy_price
                        ret = True
                    else:
                        ret = False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ret

    ##############################################################
    # 매수가 세팅
    #   분할 매수 개수만큼 리스트
    #   ex) 5차 분할 매수 [1000, 950, 900, 850, 800]
    # Parameter :
    #       code            종목 코드
    #       done_nth        N차 매수 완료(ex: 1차매수 경우 1)
    #       bought_price    N차 매수 체결가, 0 인 경우
    ##############################################################
    def set_buy_price(self, code, done_nth=0, bought_price=0):
        result = True
        msg = ""
        try:
            if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:   # 물타기
                buy_margin = 0.9
            else:   # 불타기
                buy_margin = 1.02

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            # 1차 매수 안된 경우 envelope 기반으로 매수가 세팅
            if stock['buy_done'][0] == False:
                if self.set_aggressive_first_buy_price(code) == False:
                    # 공격적인 매수 전략 사용 아닌 경우 기존 방식
                    envelope_p = self.to_percent(stock['envelope_p'])
                    envelope_support_line = stock['yesterday_20ma'] * (1 - envelope_p)

                    # 1차 매수가는 min(envelope 가격, 90일선)
                    # stock['buy_price'][0] = min(int(envelope_support_line * MARGIN_20MA), self.get_ma(code, 90))

                    # 1차 매수가는 단기간에 급락한 가격 이하여야한다.
                    stock['buy_price'][0] = min(int(envelope_support_line * MARGIN_20MA), self.get_plunge_price(code))

                # 1 ~ (BUY_SPLIT_COUNT-1)
                for i in range(1, BUY_SPLIT_COUNT):
                    #   2차 매수 : 1차 매수가 - 10%
                    #   3차 매수 : 2차 매수가 - 10%
                    stock['buy_price'][i] = int(stock['buy_price'][i-1] * buy_margin)
            else:
                # N차 매수 된 경우 실제 매수가 기반으로 세팅
                # done_nth 차 매수 bought_price 가격에 완료
                # 실제 bought_price 를 기반으로 업데이트
                if done_nth > 0 and bought_price > 0:
                    # PRINT_INFO(f"[{stock['name']}] {done_nth}차 매수 {bought_price}원 완료, 매수가 업데이트")
                    stock['buy_price'][done_nth-1] = bought_price
                    for i in range(done_nth, BUY_SPLIT_COUNT):
                        stock['buy_price'][i] = int(stock['buy_price'][i-1] * buy_margin)
                        PRINT_INFO(f"[{stock['name']}] {i+1}차 매수가 {stock['buy_price'][i]}원")
                        
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 매수 수량 세팅
    # param :
    #   code            종목 코드
    ##############################################################
    def set_buy_qty(self, code):
        result = True
        msg = ""
        try:
            # 비중 조절(가중치)
            buy_invest_money_weight = self.get_invest_money_weight(code)

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            for i in range(BUY_SPLIT_COUNT):
                if stock['buy_price'][i] > 0:
                    # 매수 완료 차수는 업데이트 하지 않는다
                    if stock['buy_done'][i] == True:
                        continue

                    if BUY_QTY_1 == True:
                        # 매수량은 항상 1주만
                        stock['buy_qty'][i] = 1
                    else:
                        # 최소 1주 매수
                        qty = max(1, int((self.buy_invest_money[i] + buy_invest_money_weight) / stock['buy_price'][i]))
                        stock['buy_qty'][i] = qty
                else:
                    stock['buy_qty'][i] = 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 매수 완료 시 호출
    #   n차 매수 완료 조건 : 보유 수량 >= 1 ~ n차 매수량 경우 
    #   ex) 1차 매수 10주 매수 주문했는데 5개만 매수된 경우는 매수 완료 아니다
    # Return    : None
    # Parameter :
    #       code            종목 코드
    #       bought_price    체결가     
    ##############################################################
    def set_buy_done(self, code, bought_price):
        result = True
        msg = ""
        try:
            self.buy_done_lock.acquire()

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            # PRINT_INFO(f"[{stock['name']}] 매수가 {bought_price}원")
            if bought_price <= 0:
                self.SEND_MSG_ERR(f"[{stock['name']}] 매수가 오류 {bought_price}원")

            # 매수 완료됐으니 평단가, 목표가 업데이트
            self.update_my_stocks()
            
            # 매수 완료됐으니 주문 완료 초기화하여 재주문 방지 가능하게
            stock['buy_order_done'] = False
            
            tot_buy_qty = 0
            for i in range(BUY_SPLIT_COUNT):
                tot_buy_qty += stock['buy_qty'][i]
                # n차 매수 완료 조건 : 보유 수량 >= 1 ~ n차 매수량 경우 
                if stock['buy_done'][i] == False:
                    if stock['stockholdings'] >= tot_buy_qty:
                        stock['buy_done'][i] = True
                        stock['status'] = f"{i+1}차 매수 완료"
                        # 매수 완료 후 실제 매수가로 N차 매수 업데이트
                        self.set_buy_price(code, i + 1, bought_price)
                        # 실제 매수가로 qty 업데이트
                        self.set_buy_qty(code)
                        break

            # N차 매수에 따라 목표가 % 변경은 물타기 경우만
            if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:
                # 2차 매수 한 경우 목표가 낮추어 빨리 빠져나온다
                for i in range(1, BUY_SPLIT_COUNT): # 1 ~ (BUY_SPLIT_COUNT-1)
                    if stock['buy_done'][i] == True:
                        stock['sell_target_p'] = MIN_SELL_TARGET_P
                        break

                # # N차 매수에 따라 목표가 낮추어 변경하여 빨리 빠져나온다
                # #   ex)
                # #   1차 매수까지 경우 : 평단가 * 5%
                # #   2차 매수까지 경우 : 평단가 * 4%
                # for i in range(1, BUY_SPLIT_COUNT): # 1 ~ (BUY_SPLIT_COUNT-1)
                #     if stock['buy_done'][BUY_SPLIT_COUNT-i] == True:
                #         stock['sell_target_p'] = stock['sell_target_p'] - 1
                #         break
                # # 최소 목표가
                # if stock['sell_target_p'] < MIN_SELL_TARGET_P:
                #     stock['sell_target_p'] = MIN_SELL_TARGET_P

            # 다음 매수 조건 체크위해 allow_monitoring_buy 초기화
            stock['allow_monitoring_buy'] = False
            self.my_cash = self.get_my_cash()
            stock['loss_cut_done'] = False
            # 매수일 업데이트
            stock['recent_buy_date'] = date.today().strftime('%Y-%m-%d')

            # 매수 완료 -> 분할 매도 수량 세팅
            self.set_sell_qty(code)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.buy_done_lock.release()

    ##############################################################
    # 매도 완료 시 호출
    #   매도는 항상 전체 수량 매도 기반
    # Parameter :
    #       code            종목 코드
    #       sold_price      체결가     
    ##############################################################
    def set_sell_done(self, code, sold_price):
        result = True
        msg = ""
        try:
            self.sell_done_lock.acquire()

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            # PRINT_INFO(f"[{stock['name']}] 매도가 {sold_price}원")
            if sold_price <= 0:
                self.SEND_MSG_ERR(f"[{stock['name']}] 매도가 오류 {sold_price}원")

            # 매도 완료됐으니 주문 완료 초기화하여 재주문 가능하게
            stock['sell_order_done'] = False

            # 매도 완료됐으니 모니터링은 초기화
            stock['allow_monitoring_sell'] = False

            if self.is_my_stock(code) == True:
                # update sell_done
                for i in range(SELL_SPLIT_COUNT):
                    if stock['sell_done'][i] == False:
                        stock['sell_done'][i] = True
                        stock['status'] = f"{i+1}차 매도 완료"
                        break
                stock['recent_sold_price'] = sold_price
                self.update_my_stocks()
                self.SEND_MSG_INFO(f"[{stock['name']}] 일부 매도", True)
                PRINT_INFO(f"[{stock['name']}] 다음 목표가 {stock['sell_target_price']}원")
            else:
                # 전량 매도 상태는 보유 종목에 없는 상태
                if self.is_my_stock(code) == False:
                    stock['sell_all_done'] = True
                    # 매도 완료 후 종가 > 20ma 체크위해 false 처리
                    stock['end_price_higher_than_20ma_after_sold'] = False
                    self.update_my_stocks()
                    if stock['loss_cut_order'] == True:
                        self.set_loss_cut_done(code)
                    else:
                        self.clear_buy_sell_info(code)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.sell_done_lock.release()

    ##############################################################
    # 손절 완료 시 호출
    # Return    : None
    # Parameter :
    #       code            종목 코드
    ##############################################################
    def set_loss_cut_done(self, code):
        result = True
        msg = ""
        try:
            self.clear_buy_sell_info(code)

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            stock['loss_cut_done'] = True
            # 매도가 > 평단가 -> 익절
            # 매도가 <= 평단가 -> 손절
            if stock['recent_sold_price'] > stock['avg_buy_price']:
                stock['status'] = "익절 완료"
            else:
                stock['status'] = "손절 완료"
            stock['loss_cut_order'] = False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg) 

    ##############################################################
    # 매도 완료등으로 매수/매도 관려 정보 초기화 시 호출
    # param :
    #   code            종목 코드    
    ##############################################################
    def clear_buy_sell_info(self, code):
        result = True
        msg = ""
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            stock['yesterday_20ma'] = 0

            stock['buy_price'] = list()
            stock['buy_qty'] = list()
            stock['buy_done'] = list()
            for i in range(BUY_SPLIT_COUNT):
                stock['buy_price'].append(0)
                stock['buy_qty'].append(0)
                stock['buy_done'].append(False)

            stock['sell_target_p'] = 0
            stock['sell_target_price'] = 0
            stock['stockholdings'] = 0
            stock['allow_monitoring_buy'] = False
            stock['allow_monitoring_sell'] = False
            stock['highest_price_ever'] = 0
            # 매도 완료 후 매도 체결 조회 할 수 있기 때문에 초기화하지 않는다
            # stock['avg_buy_price'] = 0
            stock['loss_cut_price'] = 0
            stock['loss_cut_done'] = False
            stock['recent_buy_date'] = None
            stock['trend_60ma'] = TREND_DOWN
            stock['trend_90ma'] = TREND_DOWN
            stock['recent_sold_price'] = 0
            stock['first_sell_target_price'] = 0

            stock['sell_qty'] = list()
            stock['sell_done'] = list()
            for i in range(SELL_SPLIT_COUNT):
                stock['sell_qty'].append(0)
                stock['sell_done'].append(False)
            
            stock['status'] = ""
            stock['lowest_price_1'] = 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 목표가 = 평단가 * (1 + 목표%)
    # param :
    #   code            종목 코드
    ##############################################################
    def get_sell_target_price(self, code):
        result = True
        msg = ""
        price = 0
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            if stock['sell_done'][0] == False:
                # 1차 매도 안된 경우
                sell_target_p = self.to_percent(stock['sell_target_p'])
                if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:   # 물타기
                    price = stock['avg_buy_price'] * (1 + sell_target_p)
                else:   # 불타기
                    # 1차 매수 시 목표가 유지
                    # 2,3차 매수 했다고 목표가 업데이트하지 않는다.
                    if stock['sell_target_price'] == 0 or stock['buy_done'][0] == False:
                        price = stock['avg_buy_price'] * (1 + sell_target_p)
                    else:
                        price = stock['sell_target_price']
            else:
                # 1차 매도 완료 경우
                # N차 매도가 : N-1차 매도가 * x (N>=2)
                price = stock['recent_sold_price'] * (1 + self.to_percent(NEXT_SELL_TARGET_MARGIN_P))
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            # 주식 호가 단위로 가격 변경
            return self.get_stock_asking_price(int(price))

    ##############################################################
    # 현재가 리턴
    # param :
    #   code            종목 코드
    # Return : 성공 시 현재가, 실패 시 0 리턴
    ##############################################################
    def get_curr_price(self, code):
        return self.get_price(code, 'stck_prpr')

    ##############################################################
    # 금일 기준 X 일 내 최저가 리턴
    #   수행 시간 약 570ms
    # param :
    #   code        종목 코드
    #   days        X 일
    #               ex) 1 : 금일 최저가
    #                   22 : 금일 기준 22일 내(영업일 기준 약 한 달)
    ##############################################################
    def get_lowest_pirce(self, code, days=1):
        result = True
        msg = ""
        lowest_lowest_price = 0
        try:
            if days == 1:
                lowest_lowest_price = self.get_price(code, 'stck_lwpr')
            else:
                if days > 99:
                    PRINT_INFO(f'can read over 99 data. make days to 99')
                    days = 99
                lowest_price_list = self.get_price_list(code, "D", PRICE_TYPE_LOWEST, days)
                lowest_lowest_price = min(lowest_price_list[:days])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return int(lowest_lowest_price)
        
    ##############################################################
    # 고가 리턴
    # param :
    #   code            종목 코드
    # Return : 성공 시 고가, 실패 시 0 리턴
    ##############################################################
    def get_highest_price(self, code):
        return self.get_price(code, 'stck_hgpr')

    ##############################################################
    # 종가 리턴
    # param :
    #   code            종목 코드
    #   past_day        가져올 날짜 기준
    #                   ex) 0 : 금일 종가, 1 : 어제 종가
    ##############################################################
    def get_end_price(self, code: str, past_day=0):
        result = True
        msg = ""
        end_price = 0
        try:
            if past_day > 99:
                PRINT_INFO(f'can read over 99 data. make past_day to 99')
                past_day = 99
                
            end_price_list = self.get_price_list(code, "D", PRICE_TYPE_CLOSE, past_day+1)
            end_price = end_price_list[past_day]
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return int(end_price)

    ##############################################################
    # 시가총액(market capitalization) 리턴
    # param :
    #   code            종목 코드
    # Return : 성공 시 시가총액, 실패 시 0 리턴
    ##############################################################
    def get_market_cap(self, code):
        return self.get_price(code, 'hts_avls')
    
    ##############################################################
    # 특정 타입의(현재가, 시가, 고가) 주식 가격 리턴
    #   Return : 성공 시 요청한 시세, 실패 시 0 리턴
    #   Parameter :
    #       code            종목 코드
    #       type            요청 시세(현재가, 시가, 고가, ...)
    ##############################################################
    def get_price(self, code:str, type:str):
        result = True
        msg = ""
        price = 0
        try:
            PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": "FHKST01010100"}
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": code,
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == True:
                price = float(res.json()['output'][type])
            else:
                raise Exception(f"[get_price failed]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                # request 실패 시 retry
                # ex) {'rt_cd': '1', 'msg_cd': 'EGW00201', 'msg1': '초당 거래건수를 초과하였습니다.'}
                if self.request_retry_count < MAX_REQUEST_RETRY_COUNT:
                    time.sleep(1)
                    self.request_retry_count = self.request_retry_count + 1
                    PRINT_ERR(f"get_price failed retry count({self.request_retry_count})")
                    self.get_price(code, type)
                else:
                    self.request_retry_count = 0
                    msg = self.stocks[code]['name'] + " " + msg
                    self.SEND_MSG_ERR(msg)
            else:
                self.request_retry_count = 0
            return int(price)

    ##############################################################
    # 주식 시세 data(현재가, 시가, 고가 등을 포함) 리턴
    #       stck_prpr : 현재가
    #       stck_oprc : 시가
    #       stck_hgpr : 고가
    #       stck_lwpr : 저가
    #       per : PER
    #       pbr : PBR
    #       eps : EPS
    #       bps : BPS
    #       lstn_stcn : 상장 주식 수
    #       hts_avls : 시가총액
    #       acml_tr_pbmn : 누적 거래 대금
    #       acml_vol : 누적 거래량
    #   Return : 성공 시 주식 시세 data, 실패 시 0 리턴
    #   Parameter :
    #       code            종목 코드
    ##############################################################
    def get_price_data(self, code:str):
        result = True
        msg = ""
        price_data = dict()
        try:
            PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": "FHKST01010100"}
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": code,
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == True:
                price_data = res.json()['output']
            else:
                raise Exception(f"[get_price failed]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                # request 실패 시 retry
                # ex) {'rt_cd': '1', 'msg_cd': 'EGW00201', 'msg1': '초당 거래건수를 초과하였습니다.'}
                if self.request_retry_count < MAX_REQUEST_RETRY_COUNT:
                    time.sleep(1)
                    self.request_retry_count = self.request_retry_count + 1
                    PRINT_ERR(f"get_price_data failed retry count({self.request_retry_count})")
                    self.get_price_data(code, type)
                else:
                    self.request_retry_count = 0
                    msg = self.stocks[code]['name'] + " " + msg
                    self.SEND_MSG_ERR(msg)
            else:
                self.request_retry_count = 0
            return price_data

    ##############################################################
    # 매수가 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수가 리턴
    #   last차까지 매수 완료 경우 return 0
    # param :
    #   code            종목 코드
    ##############################################################
    def get_buy_target_price(self, code):
        result = True
        msg = ""
        # last차까지 매수 완료 경우 return 0
        buy_target_price = 0
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            for i in range(BUY_SPLIT_COUNT):
                if stock['buy_done'][i] == False:
                    buy_target_price = stock['buy_price'][i]
                    break
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return self.get_stock_asking_price(int(buy_target_price))

    ##############################################################
    # 매수 수량 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수 수량 리턴
    #   last차까지 매수 완료 경우 return 0
    # param :
    #   code            종목 코드
    ##############################################################
    def get_buy_target_qty(self, code):
        result = True
        msg = ""
        # last차까지 매수 완료 경우 return 0
        buy_target_qty = 0
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            for i in range(BUY_SPLIT_COUNT):
                if stock['buy_done'][i] == False:
                    buy_target_qty = stock['buy_qty'][i]
                    break
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return int(buy_target_qty)

    ##############################################################
    # 네이버 증권에서 특정 값 얻기
    #   ex) https://finance.naver.com/item/main.naver?code=005930
    # param :
    #   code            종목 코드
    #   selector        선택할 tag
    ##############################################################
    def crawl_naver_finance_by_selector(self, code, selector):
        result = True
        msg = ""
        try:            
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            html = requests.get(url).text
            soup = BeautifulSoup(html, "html5lib")
            return soup.select_one(selector).text
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
                return 0

    ##############################################################
    # 주식 투자 정보 업데이트(시가 총액, 상장 주식 수, 저평가, BPS, PER, EPS)
    # param :
    #   code            종목 코드
    ##############################################################
    def update_stock_invest_info(self, code):
        result = True
        msg = ""
        try:            
            PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": "FHKST01010100"}
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": code,
            }
            res = self.requests_get(URL, headers, params)

            total_stock_count = 0

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            if self.is_request_ok(res) == True:
                # 현재 PER
                stock['PER'] = float(res.json()['output']['per'].replace(",",""))
                total_stock_count = int(res.json()['output']['lstn_stcn'])     # 상장 주식 수
            else:
                raise Exception(f"[update_stock_invest_info failed]{str(res.json())}")

            annual_finance = self.crawl_naver_finance(code)
            # 값이 '-' 만 있는 경우 '-' 제거
            # 안그러면 아래 코드 float(annual_finance[...])에서 exception 발생
            # ex) ROD(%) 값이 - 로만 되어있는 경우 있다
            for i, row in annual_finance.iterrows():
                for column in annual_finance.columns:
                    if row[column] == '-':
                        row[column] = ''

            # PER_E, EPS, BPS, ROE 는 20xx.12(E) 기준
            recent_year_column_text, last_year_column_text, the_year_before_last_column_text = self.get_naver_finance_year_column_texts(code)
            stock['PER_E'] = float(annual_finance[recent_year_column_text]['PER(배)'].replace(",",""))
            
            check_year_column_text = recent_year_column_text

            if stock['PER_E'] == 0:
                # _E 자료 없는 경우 작년 데이터로 대체
                check_year_column_text = last_year_column_text
                stock['PER_E'] = float(annual_finance[check_year_column_text]['PER(배)'].replace(",",""))

            stock['EPS_E'] = int(annual_finance[check_year_column_text]['EPS(원)'].replace(",",""))
            stock['BPS_E'] = int(annual_finance[check_year_column_text]['BPS(원)'].replace(",",""))
            stock['ROE_E'] = float(annual_finance[check_year_column_text]['ROE(지배주주)'].replace(",",""))

            stock['industry_PER'] = float(self.crawl_naver_finance_by_selector(code, "#tab_con1 > div:nth-child(6) > table > tbody > tr.strong > td > em").replace(",",""))
            stock['operating_profit_margin_p'] = float(annual_finance[check_year_column_text]['영업이익률'])
            stock['sales_income'] = int(annual_finance[check_year_column_text]['매출액'].replace(",",""))                   # 올해 예상 매출액, 억원
            stock['last_year_sales_income'] = int(annual_finance[last_year_column_text]['매출액'].replace(",",""))         # 작년 매출액, 억원
            stock['the_year_before_last_sales_income'] = int(annual_finance[the_year_before_last_column_text]['매출액'].replace(",",""))       # 재작년 매출액, 억원
            stock['curr_profit'] = int(annual_finance[check_year_column_text]['당기순이익'].replace(",",""))
            # 목표 주가 = 미래 당기순이익(원) * PER_E / 상장주식수
            if total_stock_count > 0:
                stock['max_target_price'] = int((stock['curr_profit'] * 100000000) * stock['PER_E'] / total_stock_count)
            # 목표 주가 gap = (목표 주가 - 목표가) / 목표 주가
            # + : 저평가
            # - : 고평가
            if stock['sell_target_price'] > 0:
                stock['gap_max_sell_target_price_p'] = int(100 * (stock['max_target_price'] - stock['sell_target_price']) / stock['sell_target_price'])
            self.set_stock_undervalue(code)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return result

    ##############################################################
    # 저평가 계산
    # param :
    #   code            종목 코드
    ##############################################################
    def set_stock_undervalue(self, code):
        result = True
        msg = ""
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]
                     
            stock['undervalue'] = 0
            curr_price = self.get_curr_price(code)
            
            if curr_price > 0:
                # BPS_E > 현재가
                if stock['BPS_E'] > curr_price:
                    stock['undervalue'] += 2
                elif stock['BPS_E'] * 1.3 < curr_price:
                    stock['undervalue'] -= 2

                # EPS_E * 10 > 현재가
                if stock['EPS_E'] * 10 > curr_price:
                    stock['undervalue'] += 2
                elif stock['EPS_E'] * 3 < curr_price:
                    stock['undervalue'] -= 2
                elif stock['EPS_E'] < 0:
                    stock['undervalue'] -= 10

                # ROE_E
                if stock['ROE_E'] < 0 and stock['EPS_E'] < 0:
                    stock['undervalue'] -= 4
                else:
                    if stock['ROE_E'] * stock['EPS_E'] > curr_price:
                        stock['undervalue'] += 2
                    elif stock['ROE_E'] * stock['EPS_E'] * 1.3 < curr_price:
                        stock['undervalue'] -= 2
                    if stock['ROE_E'] > 20:
                        stock['undervalue'] += (stock['ROE_E'] / 10)

            # PER
            if stock['PER'] > 0 and stock['PER'] <= 10:
                if stock['industry_PER'] > 0:
                    stock['undervalue'] += int((1 - stock['PER'] / stock['industry_PER']) * 4)
                else:
                    stock['undervalue'] += 2
            elif stock['PER'] >= 20:
                stock['undervalue'] -= 2
            elif stock['PER'] < 0:
                stock['undervalue'] -= 10

            # 영업이익률
            if stock['operating_profit_margin_p'] >= 10:
                stock['undervalue'] += 1
            elif stock['operating_profit_margin_p'] < 0:
                stock['undervalue'] -= 1

            # 매출액
            if stock['last_year_sales_income'] > 0 and stock['the_year_before_last_sales_income'] > 0:
                if stock['sales_income'] / stock['last_year_sales_income'] >= 1.1:
                    if stock['last_year_sales_income'] / stock['the_year_before_last_sales_income'] >= 1.1:
                        stock['undervalue'] += 2
                    else:
                        pass
                elif stock['sales_income'] / stock['last_year_sales_income'] <= 0.9:
                    if stock['last_year_sales_income'] / stock['the_year_before_last_sales_income'] <= 0.9:
                        stock['undervalue'] -= 2
                    else:
                        pass

            stock['undervalue'] = int(stock['undervalue'])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 매수/매도 위한 주식 정보 업데이트
    #   1,2차 매수가, 20일선
    ##############################################################
    def update_stocks_trade_info(self):
        result = True
        msg = ""
        try:
            past_day = self.get_past_day()

            stocks_codes = list(self.stocks.keys())

            def process_update_stock_trade_info(code):
                try:
                    stock = self.stocks[code]
                    PRINT_DEBUG(f"[{stock['name']}]")
                    # 순서 변경 금지
                    # ex) 목표가를 구하기 위해선 평단가가 먼저 있어야한다
                    # 시가 총액
                    stock['market_cap'] = self.get_market_cap(code)
                    
                    # yesterday 20일선
                    stock['yesterday_20ma'] = self.get_ma(code, 20, past_day)

                    # 1차 매수 안된 경우만 업데이트
                    if stock['buy_done'][0] == False:
                        stock['sell_target_p'] = SELL_TARGET_P
                        stock['envelope_p'] = self.get_envelope_p(code)
                        # 매수가 세팅
                        self.set_buy_price(code)
                        # 매수 수량 세팅
                        self.set_buy_qty(code)

                    # 추세 세팅
                    if self.trade_strategy.use_trend_60ma == True:
                        # 60 이평 추세
                        stock['trend_60ma'] = self.get_ma_trend(code, past_day)             
                    if self.trade_strategy.use_trend_90ma == True:
                        # 90 이평 추세, 90 이평은 연속 최대 8일 이하만 가능
                        stock['trend_90ma'] = self.get_ma_trend(code, past_day, 90, 8, "D", TREND_UP_DOWN_DIFF_90MA_P)

                    # 손절가 세팅
                    stock['loss_cut_price'] = self.get_loss_cut_price(code)

                    # 어제 종가 세팅
                    stock['yesterday_end_price'] = self.get_end_price(code, past_day)

                    # 매도 완료 후 "어제 종가 > 어제 20ma" 여야 재매수 가능
                    if stock['sell_all_done'] == True:
                        # 어제 종가 > 어제 20ma
                        if stock['yesterday_end_price'] > stock['yesterday_20ma']:
                            # 재매수 가능
                            stock['end_price_higher_than_20ma_after_sold'] = True
                            stock['sell_all_done'] = False

                    # 보유 주식 아닌 경우에 업데이트
                    if self.is_my_stock(code) == False:
                        # 평단가 = 1차 매수가
                        stock['avg_buy_price'] = stock['buy_price'][0]
                        # 목표가
                        stock['sell_target_price'] = self.get_sell_target_price(code)

                    # 주식 투자 정보 업데이트(상장 주식 수, 저평가, BPS, PER, EPS)
                    stock['stock_invest_info_valid'] = self.update_stock_invest_info(code)

                except Exception as e:
                    PRINT_ERR(f"[{stock['name']}] 처리 중 오류: {e}")
            #################### end of process_update_stock_trade_info() ####################

            with ThreadPoolExecutor(max_workers=14) as executor:
                executor.map(process_update_stock_trade_info, stocks_codes)            
            # past_day = self.get_past_day()

            # # dict 접근을 한번만 하여 성능 향상
            # stock = self.stocks[code]

            # for code in self.stocks.keys():
            #     PRINT_DEBUG(f"[{stock['name']}]")
            #     # 순서 변경 금지
            #     # ex) 목표가를 구하기 위해선 평단가가 먼저 있어야한다
            #     # 시가 총액
            #     stock['market_cap'] = self.get_market_cap(code)
                
            #     # yesterday 20일선
            #     stock['yesterday_20ma'] = self.get_ma(code, 20, past_day)

            #     # 1차 매수 안된 경우만 업데이트
            #     if stock['buy_done'][0] == False:
            #         stock['sell_target_p'] = SELL_TARGET_P
            #         stock['envelope_p'] = self.get_envelope_p(code)
            #         # 매수가 세팅
            #         self.set_buy_price(code)
            #         # 매수 수량 세팅
            #         self.set_buy_qty(code)

            #     # 추세 세팅
            #     if self.trade_strategy.use_trend_60ma == True:
            #         # 60 이평 추세
            #         stock['trend_60ma'] = self.get_ma_trend(code, past_day)             
            #     if self.trade_strategy.use_trend_90ma == True:
            #         # 90 이평 추세, 90 이평은 연속 최대 8일 이하만 가능
            #         stock['trend_90ma'] = self.get_ma_trend(code, past_day, 90, 8, "D", TREND_UP_DOWN_DIFF_90MA_P)

            #     # 손절가 세팅
            #     stock['loss_cut_price'] = self.get_loss_cut_price(code)

            #     # 어제 종가 세팅
            #     stock['yesterday_end_price'] = self.get_end_price(code, past_day)

            #     # 매도 완료 후 "어제 종가 > 어제 20ma" 여야 재매수 가능
            #     if stock['sell_all_done'] == True:
            #         # 어제 종가 > 어제 20ma
            #         if stock['yesterday_end_price'] > stock['yesterday_20ma']:
            #             # 재매수 가능
            #             stock['end_price_higher_than_20ma_after_sold'] = True
            #             stock['sell_all_done'] = False

            #     # 보유 주식 아닌 경우에 업데이트
            #     if self.is_my_stock(code) == False:
            #         # 평단가 = 1차 매수가
            #         stock['avg_buy_price'] = stock['buy_price'][0]
            #         # 목표가
            #         stock['sell_target_price'] = self.get_sell_target_price(code)

            #     # 주식 투자 정보 업데이트(상장 주식 수, 저평가, BPS, PER, EPS)
            #     stock['stock_invest_info_valid'] = self.update_stock_invest_info(code)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 보유 주식 정보 업데이트
    #   보유 주식은 stockholdings > 0
    #   Return : 성공 시 True , 실패 시 False    
    ##############################################################
    def update_my_stocks(self):
        result = True
        msg = ""
        try:
            PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": self.config['TR_ID_GET_STOCK_BALANCE'],
                    "custtype": "P",
                    }
            params = {
                "CANO": self.config['CANO'],
                "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == True:
                my_stocks = res.json()['output1']
                self.my_stocks_lock.acquire()
                self.my_stocks.clear()
                

                for my_stock in my_stocks:
                    if int(my_stock['hldg_qty']) > 0:
                        code = my_stock['pdno']
                        if code in self.stocks.keys():
                            # dict 접근을 한번만 하여 성능 향상
                            stock = self.stocks[code]

                            # 보유 수량
                            stock['stockholdings'] = int(my_stock['hldg_qty'])
                            # 평단가
                            stock['avg_buy_price'] = int(float(my_stock['pchs_avg_pric']))    # 계좌내 실제 평단가
                            # 목표가
                            stock['sell_target_price'] = self.get_sell_target_price(code)
                            # 1차 목표가 유지
                            stock['first_sell_target_price'] = self.get_first_sell_target_price(code)
                            # self.my_stocks 업데이트
                            temp_stock = copy.deepcopy({code: stock})
                            self.my_stocks[code] = temp_stock[code]
                        else:
                            # 보유는 하지만 stocks_info.json 에 없는 종목 제외 ex) 공모주
                            pass
            else:
                raise Exception(f"[계좌 조회 실패]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.my_stocks_lock.release()
            return result

    ##############################################################
    # 매수 가능 신규 종목(미보유) 수 리턴
    #   보유 현금 / 종목당 매수 금액
    #   ex) 총 보유금액이 300만원이고 종목당 총 100만원 매수 시 총 3종목 매수
    ##############################################################
    def get_available_buy_new_stock_count(self):
        result = True
        msg = ""
        ret = 0
        try:
            if INVEST_MONEY_PER_STOCK > 0:
                ret = int((self.my_cash - self.get_invest_money_for_my_stock()) / INVEST_MONEY_PER_STOCK)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return max(ret, 0)

    ##############################################################
    # 보유 종목인지 체크
    # param :
    #   code            종목 코드    
    ##############################################################
    def is_my_stock(self, code):
        result = True
        msg = ""
        ret = False
        try:
            if code in self.my_stocks.keys():
                ret = True
            else:
                ret = False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ret
        
    ##############################################################
    # 매수 가능 종목인지 체크
    # param :
    #   code            종목 코드    
    ##############################################################
    def is_buyable_stock(self, code):
        result = True
        msg = ""
        ret = False
        try:
            if code in self.buyable_stocks.keys():
                ret = True
            else:
                ret = False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ret
    
    ##############################################################
    # 매수 여부 판단
    # param :
    #   code            종목 코드
    #   print_msg       print log 여부
    ##############################################################
    def is_ok_to_buy(self, code, print_msg=False):
        result = True
        msg = ""
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            #### 이미 보유 주식이지만 체크할 조건
            # 오늘 주문 완료 시 금지
            if self.already_ordered(code, BUY_CODE) == True:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 오늘 주문 완료")
                return False

            # last차 매수까지 완료 시 금지
            if stock['buy_done'][BUY_SPLIT_COUNT-1] == True:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, last차 매수까지 완료")                
                return False
            
            # 1차 매도된 경우 추가 매수 금지
            if stock['sell_done'][0] == True:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 1차 매도된 경우 추가 매수 금지")                
                return False
            ####
            
            # 이미 보유 종목은 매수
            # ex) 2차, 3차 매수
            if self.is_my_stock(code) == True:
                return True
            
            # 매수 가능 종목은 매수
            if self.is_buyable_stock(code) == True:
                return True

            # 주식 투자 정보가 valid 하지 않으면 매수 금지
            if stock['stock_invest_info_valid'] == False:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 주식 투자 정보가 not valid")                   
                return False

            # 저평가 조건(X미만 매수 금지)
            if stock['undervalue'] < self.trade_strategy.under_value:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 저평가 조건({stock['undervalue']})")                  
                return False
            
            # 목표 주가 gap = (목표 주가 - 목표가) / 목표가 < X% 미만 매수 금지
            if stock['gap_max_sell_target_price_p'] < self.trade_strategy.gap_max_sell_target_price_p:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 목표 주가 gap({stock['gap_max_sell_target_price_p']})")                 
                return False

            # 저평가 + 목표가GAP < X 미만 매수 금지
            if (stock['undervalue'] + stock['gap_max_sell_target_price_p']) < self.trade_strategy.sum_under_value_sell_target_gap:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 저평가 + 목표가GAP < {self.trade_strategy.sum_under_value_sell_target_gap}")
                return False
            
            # PER 매수 금지
            if stock['PER'] < 0 or stock['PER'] >= self.trade_strategy.max_per or stock['PER_E'] < 0:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, PER({stock['PER']})")
                return False
            
            # EPS_E 매수 금지
            if stock['EPS_E'] < 0:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, EPS_E({stock['EPS_E']})")                
                return False

            if self.is_my_stock(code) == False:
                # 최대 보유 종목 수 제한
                if len(self.my_stocks) >= MAX_MY_STOCK_COUNT:
                    if print_msg:
                        PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 현재 보유 종목 수({len(self.my_stocks)}) >= 최대 보유 가능 종목 수({MAX_MY_STOCK_COUNT})")
                    return False
                # 보유 현금에 맞게 종목 수 매수
                #   ex) 총 보유 금액이 300만원이고 종목 당 총 100만원 매수 시 총 3종목 매수                
                # elif self.get_available_buy_new_stock_count() <= 0:
                elif self.available_buy_new_stock_count <= 0:
                    if print_msg:
                        PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 보유 현금({self.my_cash}원) 부족")
                    return False
            
            # 매도 후 종가 > 20ma 체크
            if stock['sell_all_done'] == True:
                # 어제 종가 <= 어제 20ma 상태면 매수 금지
                if stock['end_price_higher_than_20ma_after_sold'] == False:
                    if print_msg:
                        PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 매도 후 종가 <= 20이평선")                       
                    return False
            
            # 시총 체크
            if stock['market_cap'] < self.trade_strategy.buyable_market_cap:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 시총({stock['market_cap']}억)")                 
                return False

            # 60일선 추세 체크
            if self.trade_strategy.use_trend_60ma == True:
                if stock['trend_60ma'] < self.trade_strategy.trend_60ma:
                    if print_msg:
                        PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 60일선 추세 체크({self.str_trend[stock['trend_60ma']]})")
                    return False

            # 90일선 추세 체크
            if self.trade_strategy.use_trend_90ma == True:
                if stock['trend_90ma'] < self.trade_strategy.trend_90ma:
                    if print_msg:
                        PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 90일선 추세 체크({self.str_trend[stock['trend_90ma']]})")
                    return False
            
            # # 1차 매수가 < 90일선 경우 매수 금지, 단 공격적 전략 경우 제외
            # if self.trade_strategy.invest_risk != INVEST_RISK_HIGH:
            #     ma_90 = self.get_ma(code, 90)
            #     if stock['buy_price'][0] < ma_90:
            #         if print_msg:
            #             PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 1차 매수가({stock['buy_price'][0]}) < 90일선({ma_90})")
            #         return False

            # 20,60,90 정배열 체크
            # 이평선 간에 x% 이상 차이나야 정배열
            if self.get_multi_ma_status(code, [20,60,90], "D", MA_DIFF_P) != MA_UP_TREND:
                if print_msg:
                    PRINT_DEBUG(f"[{stock['name']}] 매수 금지, 20,60,90 이평선 정배열 아님")
                return False

            return True
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
                return False

    ##############################################################
    # 금일(index 0) 기준 X건의 type 가격 리스트 리턴
    # param :
    #   code            종목 코드
    #   period          D : 일, W : 주, M : 월, Y : 년
    #   type            시가 : stck_oprc
    #                   종가 : stck_clpr
    #                   최저가 : stck_lwpr
    #                   최고가 : stck_hgpr
    #   data_cnt        몇 건의 가격을 리턴할건가
    ##############################################################
    def get_price_list(self, code: str, period="D", type=PRICE_TYPE_CLOSE, data_cnt=100):
        result = True
        msg = ""
        end_price_list = []
        try:
            # 조회 종료 날짜(오늘) 구하기
            end_day_ = datetime.datetime.today()
            end_day = end_day_.strftime('%Y%m%d')
            # 150일 전 날짜 구하기, 단 100건 까지만 구해진다
            start_day_ = (end_day_ - datetime.timedelta(days=150))
            start_day = start_day_.strftime('%Y%m%d')

            PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": "FHKST03010100"}
            params = {
                "fid_cond_mrkt_div_code": "J",
                # 조회 시작일자 ex) 20220501
                "fid_input_date_1": start_day,
                # 조회 종료일자 ex) 20220530
                "fid_input_date_2": end_day,
                "fid_input_iscd": code,
                # 0 : 수정주가반영, 1 : 수정주가미반영
                "fid_org_adj_prc": "0",
                # D : 일봉
                # W : 주봉
                # M : 월봉
                # Y : 년봉
                "fid_period_div_code": period
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == False:
                raise Exception(f"[get_ma_trend failed]{str(res.json())}")
            
            for i in range(min(len(res.json()['output2']), data_cnt)):
                end_price_list.append(int(res.json()['output2'][i][type]))   # 종가      # 최저가 stck_lwpr

        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return end_price_list

    ##############################################################
    # X일선 가격 리턴
    # param :
    #   code            종목 코드
    #   ma              X일선
    #                   ex) 20일선 : 20, 5일선 : 5
    #   past_day        X일선 가격 기준
    #                   ex) 0 : 금일 X일선, 1 : 어제 X일선
    #   period          D : 일, W : 주, M : 월, Y : 년
    ##############################################################
    def get_ma(self, code: str, ma=20, past_day=0, period="D"):
        result = True
        msg = ""
        value_ma = 0
        try:
            end_price_list = self.get_price_list(code, period, PRICE_TYPE_CLOSE)

            # x일 이평선 구하기 위해 x일간의 종가 구한다
            days_last = past_day + ma

            # days_last 가 종가 개수보다 적게 조정하여 가능한 최대한의 종가로 계산
            while days_last > len(end_price_list):
                days_last = days_last - 1
                past_day = past_day -1

            sum_end_price = 0
            for i in range(past_day, days_last):
                end_price = end_price_list[i]                   # 종가
                sum_end_price = sum_end_price + end_price       # 종가 합

            value_ma = sum_end_price / ma                       # x일선 가격
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return int(value_ma)

    ##############################################################
    # 토큰 발급
    ##############################################################
    def get_access_token(self):
        result = True
        msg = ""
        ret = None
        try:            
            headers = {"content-type": "application/json"}
            body = {"grant_type": "client_credentials",
                    "appkey": self.config['APP_KEY'],
                    "appsecret": self.config['APP_SECRET']}
            PATH = "oauth2/tokenP"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            res = requests.post(URL, headers=headers, data=json.dumps(body))
            time.sleep(API_DELAY_S)
            ret = res.json()["access_token"]
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ret

    ##############################################################
    # 암호화
    # param :
    #   data            hash key 에 사용할 data
    ##############################################################
    def hashkey(self, data):
        result = True
        msg = ""
        ret = None
        try:
            PATH = "uapi/hashkey"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {
                'content-Type': 'application/json',
                'appKey': self.config['APP_KEY'],
                'appSecret': self.config['APP_SECRET'],
            }
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            time.sleep(API_DELAY_S)
            ret = res.json()["HASH"]
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ret

    ##############################################################
    # 주식 잔고조회
    # param :
    #   send_discode        discode 로 전송 여부
    ###############################################################
    def get_stock_balance(self, send_discode:bool = False):
        result = True
        msg = ""
        stock_list = []
        try:
            PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": self.config['TR_ID_GET_STOCK_BALANCE'],
                    "custtype": "P",
                    }
            params = {
                "CANO": self.config['CANO'],
                "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == False:
                raise Exception(f"[get_stock_balance failed]{str(res.json())}")
            stock_list = res.json()['output1']
            evaluation = res.json()['output2']
            data = {'종목명':[], '수익률(%)':[], '수량':[], '평가금액':[], '손익금액':[], '평단가':[], '현재가':[], '목표가':[], '손절가':[], '상태':[]}

            for my_stock in stock_list:
                if int(my_stock['hldg_qty']) > 0:
                    data['종목명'].append(my_stock['prdt_name'])
                    data['수익률(%)'].append(float(my_stock['evlu_pfls_rt'].replace(",","")))
                    data['수량'].append(my_stock['hldg_qty'])
                    data['평가금액'].append(int(my_stock['evlu_amt'].replace(",","")))
                    data['손익금액'].append(my_stock['evlu_pfls_amt'])
                    data['평단가'].append(int(float(my_stock['pchs_avg_pric'].replace(",",""))))
                    data['현재가'].append(int(my_stock['prpr'].replace(",","")))                    
                    code = my_stock['pdno']
                    if code in self.stocks.keys():
                        # dict 접근을 한번만 하여 성능 향상
                        stock = self.stocks[code]
                        data['목표가'].append(int(stock['sell_target_price']))
                        data['손절가'].append(int(self.get_loss_cut_price(code)))
                        data['상태'].append(stock['status'])
                    else:
                        # 보유는 하지만 stocks_info.json 에 없는 종목 표시
                        data['목표가'].append(0)
                        data['손절가'].append(0)
                        data['상태'].append("")

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'r'  # 우측 정렬
            for row in zip(*data.values()):
                table.add_row(row)

            table = f"\n==========주식 보유 잔고(계좌:{self.config['CANO']})==========\n" + str(table)
            if send_discode == True:
                self.SEND_MSG_INFO(f"{table}", send_discode)
                self.SEND_MSG_INFO(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원", send_discode)
                self.SEND_MSG_INFO(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원", send_discode)
                self.SEND_MSG_INFO(f"총 평가 금액: {evaluation[0]['tot_evlu_amt']}원", send_discode)
            else:
                self.SEND_MSG_DEBUG(f"{table}", send_discode)
                self.SEND_MSG_DEBUG(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원", send_discode)
                self.SEND_MSG_DEBUG(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원", send_discode)
                self.SEND_MSG_DEBUG(f"총 평가 금액: {evaluation[0]['tot_evlu_amt']}원", send_discode)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return stock_list

    ##############################################################
    # 현금 잔고 조회
    ##############################################################
    def get_my_cash(self):
        result = True
        msg = ""
        cash = 0
        try:            
            PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": self.config['TR_ID_GET_BALANCE'],
                    "custtype": "P",
                    }
            params = {
                "CANO": self.config['CANO'],
                "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                "PDNO": "005930",
                "ORD_UNPR": "65500",
                "ORD_DVSN": "01",
                "CMA_EVLU_AMT_ICLD_YN": "Y",
                "OVRS_ICLD_YN": "Y"
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == False:
                raise Exception(f"[get_my_cash failed]{str(res.json())}")
            cash = res.json()['output']['ord_psbl_cash']
            PRINT_INFO(f"보유 현금 : {cash}원")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return int(cash)

    ##############################################################
    # 매수 주문
    #   param :
    #       code            종목 코드
    #       price           매수 가격
    #       qty             매수 수량
    #       order_type      매수 타입(지정가, 최유리지정가,...)
    #   Return : 성공 시 True , 실패 시 False
    ##############################################################
    def buy(self, code: str, price: str, qty: str, order_type:str = ORDER_TYPE_LIMIT_ORDER):
        result = True
        msg = ""
        try:
            if self.is_ok_to_buy(code) == False:
                return False
            
            # 종가 매매 처리
            t_now = datetime.datetime.now()
            if t_now >= T_MARKET_END:
                order_type = ORDER_TYPE_AFTER_MARKET_ORDER
            
            # 지정가 이외의 주문은 가격을 0으로 해야 주문 실패하지 않는다.
            # 업체 : 장전 시간외, 장후 시간외, 시장가 등 모든 주문구분의 경우 1주당 가격을 공란으로 비우지 않고
            # "0"으로 입력 권고드리고 있습니다.
            if order_type != ORDER_TYPE_LIMIT_ORDER:
                price = 0
            
            # 주식 호가 단위로 가격 변경
            price = str(price)
            price = price.replace(',', '')
            temp_price = self.get_stock_asking_price(int(price))
            price = str(temp_price)
            qty = str(int(qty))
            
            PATH = "uapi/domestic-stock/v1/trading/order-cash"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            data = {
                "CANO": self.config['CANO'],
                "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                "PDNO": code,
                "ORD_DVSN": order_type,
                "ORD_QTY": qty,
                "ORD_UNPR": price,
            }
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": self.config['TR_ID_BUY'],
                    "custtype": "P",
                    "hashkey": self.hashkey(data)
                    }
            order_string = self.get_order_string(order_type)
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            time.sleep(API_DELAY_S)

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            if self.is_request_ok(res) == True:
                PRINT_INFO(f"[매수 주문 성공] [{stock['name']}] {order_string} {price}원 {qty}주")
                return True
            else:
                self.SEND_MSG_ERR(f"[매수 주문 실패] [{stock['name']}] {order_string} {price}원 {qty}주 {str(res.json())}")
            return False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
                return False

    ##############################################################
    # 매도 주문
    #   param :
    #       code            종목 코드
    #       price           매도 가격
    #       qty             매도 수량
    #       order_type      매도 타입(지정가, 최유리지정가,...)
    #   Return : 성공 시 True , 실패 시 False
    ##############################################################
    def sell(self, code: str, price: str, qty: str, order_type:str = ORDER_TYPE_LIMIT_ORDER):
        result = True
        msg = ""
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            # 당일 매도 주문 완료 후 체결 안됐는데 또 매도 금지
            if self.already_ordered(code, SELL_CODE) == True:
                PRINT_INFO(f"[{stock['name']}] 당일 매도 주문 완료 후 체결 안됐는데 또 매도 금지")
                return False
            
            # 종가 매매 처리
            t_now = datetime.datetime.now()
            if t_now >= T_MARKET_END:
                order_type = ORDER_TYPE_AFTER_MARKET_ORDER

            # 지정가 이외의 주문은 가격을 0으로 해야 주문 실패하지 않는다.
            # 업체 : 장전 시간외, 장후 시간외, 시장가 등 모든 주문구분의 경우 1주당 가격을 공란으로 비우지 않고
            # "0"으로 입력 권고드리고 있습니다.
            if order_type != ORDER_TYPE_LIMIT_ORDER:
                price = 0

            
            # 시장가 주문은 조건 안따진다
            if order_type != ORDER_TYPE_MARKET_ORDER:
                if stock['allow_monitoring_sell'] == False:
                    PRINT_INFO(f"[{stock['name']}]  allow_monitoring_sell == False sell 금지")
                    return False

            # 주식 호가 단위로 가격 변경
            price = str(price)
            price = price.replace(',', '')
            temp_price = self.get_stock_asking_price(int(price))
            price = str(temp_price)
            qty = str(int(qty))

            PATH = "uapi/domestic-stock/v1/trading/order-cash"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            data = {
                "CANO": self.config['CANO'],
                "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                "PDNO": code,
                # 00 : 지정가
                # 01 : 시장가
                # 02 : 조건부지정가
                # 03 : 최유리지정가
                # 04 : 최우선지정가
                "ORD_DVSN": order_type,
                "ORD_QTY": qty,
                "ORD_UNPR": price,
            }
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": self.config['TR_ID_SELL'],
                    "custtype": "P",
                    "hashkey": self.hashkey(data)
                    }
            order_string = self.get_order_string(order_type)
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            time.sleep(API_DELAY_S)
            if self.is_request_ok(res) == True:
                PRINT_INFO(f"[매도 주문 성공] [{stock['name']}] {order_string} {price}원 {qty}주")
                return True
            else:
                self.SEND_MSG_ERR(f"[매도 주문 실패] [{stock['name']}] {order_string} {price}원 {qty}주 {str(res.json())}")
            return False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
                return False

    ##############################################################
    # 주문 성공 후 처리
    #   param :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    ##############################################################
    def set_order_done(self, code, buy_sell):
        result = True
        msg = ""
        try:
            if buy_sell == BUY_CODE:
                self.stocks[code]['buy_order_done'] = True
            else:
                self.stocks[code]['sell_order_done'] = True
            # self.show_order_list()
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 매수 처리
    ##############################################################
    def handle_buy_stock(self):
        result = True
        msg = ""
        try:
            # set_buy_done 완료까지 handle_buy_stock 대기   
            self.buy_done_lock.acquire()
            buy_margin = 1 + self.to_percent(BUY_MARGIN_P)

            # 매수 가능 종목내에서만 매수
            self.buyable_stocks_lock.acquire()
            buyable_codes = list(self.buyable_stocks.keys())

            # 멀티 쓰레드로 매수 처리
            def process_buy_stock(code):
                try:
                    # 매수,매도 등 처리하지 않는 종목, stocks_info.json 에 없는 종목은 제외
                    if code in self.not_handle_stock_list or code not in self.stocks.keys():
                        return
                    
                    if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:   # 물타기
                        self.handle_buy_split_strategy_down(code, buy_margin)
                    else:   # 불타기
                        self.handle_buy_split_strategy_up(code, buy_margin)

                except Exception as e:
                    PRINT_ERR(f"[{self.stocks[code]['name']}] 처리 중 오류: {e}")

            with ThreadPoolExecutor(max_workers=14) as executor:
                executor.map(process_buy_stock, buyable_codes)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.buy_done_lock.release()
            self.buyable_stocks_lock.release()

    ##############################################################
    # 매도 처리
    ##############################################################
    def handle_sell_stock(self):
        result = True
        msg = ""
        try:
            # set_sell_done 완료까지 handle_sell_stock 대기
            self.sell_done_lock.acquire()
            self.my_stocks_lock.acquire()

            for code in self.my_stocks.keys():
                # 매수,매도 등 처리하지 않는 종목
                if code in self.not_handle_stock_list:
                    continue

                # stocks_info.json 에 없는 종목은 제외
                if code not in self.stocks.keys():
                    continue

                # dict 접근을 한번만 하여 성능 향상
                stock = self.stocks[code]

                price_data = self.get_price_data(code)
                curr_price = int(price_data['stck_prpr'])
                if curr_price == 0:
                    PRINT_ERR(f"[{stock['name']}] curr_price {curr_price}원")
                    continue

                sell_target_price = self.my_stocks[code]['sell_target_price']
                if sell_target_price == 0:
                    PRINT_ERR(f"[{stock['name']}] sell_target_price {sell_target_price}원")
                    continue

                if stock['sell_done'][0] == False:  # 1차 매도 안된 상태
                    # 목표가 매도 처리
                    # 장중 익절,손절 처리 때문에 목표가 이상인 경우 매도 처리
                    if curr_price >= sell_target_price:
                        stock['allow_monitoring_sell'] = True
                        stock['status'] = "매도 모니터링"
                        qty = self.get_sell_qty(code)
                        # 지정가 매도
                        # 주문 완료 했으면 다시 주문하지 않는다
                        if self.already_ordered(code, SELL_CODE) == False and self.sell(code, curr_price, qty, ORDER_TYPE_LIMIT_ORDER) == True:
                            self.set_order_done(code, SELL_CODE)
                            PRINT_INFO(f"[{stock['name']}] 매도 주문, {qty}주 {curr_price}(현재가) >= {sell_target_price}(목표가)")
                else:   # 1차 매도된 상태
                    # ex) 2차 매도가오면 monitoring 하면서 trailing stop
                    if self.trade_strategy.sell_trailing_stop == True:
                        # 트레일링 스탑으로 매도 처리
                        if stock['allow_monitoring_sell'] == False:
                            # 목표가 왔다 -> 매도 감시 시작
                            if curr_price >= sell_target_price:
                                PRINT_INFO(f"[{stock['name']}] 매도 감시 시작, {curr_price}(현재가) 매도 목표가({sell_target_price})")
                                stock['allow_monitoring_sell'] = True
                                stock['status'] = "매도 모니터링"
                        else:
                            # 익절가 이하 시 trailing stop 전량 매도
                            take_profit_price = self.get_take_profit_price(code)
                            if (take_profit_price > 0 and curr_price <= take_profit_price):
                                qty = int(self.my_stocks[code]['stockholdings'])
                                if self.already_ordered(code, SELL_CODE) == False and self.sell(code, curr_price, qty, ORDER_TYPE_LIMIT_ORDER) == True:
                                    self.set_order_done(code, SELL_CODE)
                                    PRINT_INFO(f"[{stock['name']}] 매도 주문, {qty}주 {curr_price}(현재가) <= {take_profit_price}(익절가)")
                    else:
                        # "현재가 >= 목표가" 경우 매도
                        # 익절은 handle_loss_cut 에서 처리
                        # 장중 익절,손절 처리 때문에 목표가 이상인 경우 매도 처리
                        if curr_price >= sell_target_price:
                            # 1차 매도 후 다음날 매도 가능하게
                            stock['allow_monitoring_sell'] = True
                            stock['status'] = "매도 모니터링"
                            qty = self.get_sell_qty(code)
                            # 주문 완료 했으면 다시 주문하지 않는다
                            if self.already_ordered(code, SELL_CODE) == False and self.sell(code, curr_price, qty, ORDER_TYPE_LIMIT_ORDER) == True:
                                self.set_order_done(code, SELL_CODE)
                                PRINT_INFO(f"[{stock['name']}] 매도 주문, {qty}주 {curr_price}(현재가) >= {sell_target_price}(목표가)")

            # 장중 손절
            if self.trade_strategy.loss_cut_time == LOSS_CUT_MARKET_OPEN:
                self.my_stocks_lock.release()
                self.handle_loss_cut()
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.sell_done_lock.release()
            if self.trade_strategy.loss_cut_time == LOSS_CUT_MARKET_OPEN:
                # 이미 위에서 release 했으므로 다시 release 하지 않음
                pass
            else:
                self.my_stocks_lock.release()

    ##############################################################
    # 주문 번호 리턴
    #   Return : 성공 시 True 주문 번호, 실패 시 False  ""
    #            취소 주문은 True, ""
    #   param :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    #       trade_done      TRADE_ANY_CODE:체결/미체결 전체, 체결:TRADE_DONE_CODE, 미체결:TRADE_NOT_DONE_CODE
    ##############################################################
    def get_order_num(self, code, buy_sell: str, trade_done:str = TRADE_ANY_CODE):
        result = True
        msg = ""
        try:            
            order_list = self.get_order_list()
            for order_stock in order_list:           
                if order_stock['pdno'] == code:
                    # 취소 주문은 제외
                    if order_stock['cncl_yn'] == 'Y':
                        return True, ""
                    if order_stock['sll_buy_dvsn_cd'] == buy_sell:
                        if trade_done == TRADE_DONE_CODE:
                            # 체결, 주문수량 == 총체결수량
                            if order_stock['ord_qty'] == order_stock['tot_ccld_qty']:
                                return True, order_stock['odno']
                            else:
                                return False, ""
                        elif trade_done == TRADE_NOT_DONE_CODE:
                            # 미체결, 주문수량 > 총체결수량
                            if order_stock['ord_qty'] > order_stock['tot_ccld_qty']:
                                return True, order_stock['odno']
                            else:
                                return False, ""
                        else:
                            return True, order_stock['odno']
            return False, ""
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
                return False, ""

    ##############################################################
    # 주식 주문 전량 취소
    #   종목코드 매수/매도 조건에 맞는 주문 취소
    #   단, 모의 투자 미지원
    #   Return : 성공 시 True, 실패 시 False
    #   param :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    ##############################################################
    def cancel_order(self, code, buy_sell: str):
        result = True
        msg = ""
        ret = False
        try:            
            result, order_num = self.get_order_num(code, buy_sell)
            if result == True:
                PATH = "uapi/domestic-stock/v1/trading/order-rvsecncl"
                URL = f"{self.config['URL_BASE']}/{PATH}"
                headers = {"Content-Type": "application/json",
                        "authorization": f"Bearer {self.access_token}",
                        "appKey": self.config['APP_KEY'],
                        "appSecret": self.config['APP_SECRET'],
                        "tr_id": self.config['TR_ID_MODIFY_CANCEL_ORDER'],
                        "custtype": "P",
                        }
                params = {
                    "CANO": self.config['CANO'],
                    "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                    "KRX_FWDG_ORD_ORGNO": "",
                    "ORGN_ODNO": order_num,
                    # 00 : 지정가
                    "ORD_DVSN": "00",
                    "RVSE_CNCL_DVSN_CD": "02",
                    # 전량 주문
                    "ORD_QTY": "0",
                    "ORD_UNPR": "",
                    "QTY_ALL_ORD_YN": "Y"
                }
                res = requests.post(URL, headers=headers, params=params)
                time.sleep(API_DELAY_S)

                # dict 접근을 한번만 하여 성능 향상
                stock = self.stocks[code]

                if self.is_request_ok(res) == True:
                    PRINT_INFO(f"[주식 주문 전량 취소 주문 성공]")
                    if buy_sell == BUY_CODE:
                        stock['buy_order_done'] = False
                    else:
                        stock['sell_order_done'] = False
                    ret = True
                else:
                    if self.config['TR_ID_MODIFY_CANCEL_ORDER'] == "VTTC0803U":
                        self.SEND_MSG_ERR(f"[주식 주문 전량 취소 주문 실패] [{stock['name']}] 모의 투자 미지원")
                    else:
                        self.SEND_MSG_ERR(f"[주식 주문 전량 취소 주문 실패] [{stock['name']}] {str(res.json())}")
                    ret = False
            else:
                self.SEND_MSG_ERR(f"[cancel_order failed] [{stock['name']}] {self.buy_sell_msg[buy_sell]}")
                ret = False            
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ret

    ##############################################################
    # 매수/매도 체결 여부 체크
    # parameter :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    # return    : 첫번째 return 값
    #               주문 수량 전체 체결 시 True, 아니면 False
    #               이미 체결 완료된 주문이면 return False
    #             두번째 return 값
    #               첫번째 return 값이 True면 평균 체결가, 아니면 0
    ##############################################################
    def check_trade_done(self, code, buy_sell: str):
        result = True
        msg = ""
        try:
            if code not in self.stocks.keys():
                # 보유는 하지만 stocks_info.json 에 없는 종목 제외 ex) 공모주
                return False, 0

            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            order_list = self.get_order_list()
            for order_stock in order_list:
                if order_stock['pdno'] == code:
                    # 이미 체결 완료 처리한 주문은 재처리 금지
                    if buy_sell == BUY_CODE:
                        if order_stock['odno'] in self.buy_done_order_list:
                            return False, 0
                    elif buy_sell == SELL_CODE:
                        if order_stock['odno'] in self.sell_done_order_list:
                            return False, 0
                    else:
                        if order_stock['odno'] in self.buy_done_order_list or order_stock['odno'] in self.sell_done_order_list:
                            return False, 0

                    if order_stock['sll_buy_dvsn_cd'] == buy_sell:
                        # 주문 수량
                        order_qty = int(order_stock['ord_qty'])
                        # 총 체결 수량
                        tot_trade_qty = int(order_stock['tot_ccld_qty'])
                        
                        # 전량 매도 됐는데 일부만 매도된걸로 처리되는 버그 처리
                        # 잔고 조회해서 보유잔고 없으면 전량 매도 처리   
                        self.update_my_stocks()

                        if order_qty == tot_trade_qty:
                            # 전량 체결 완료
                            if order_stock['sll_buy_dvsn_cd'] == SELL_CODE:
                                self.sell_done_order_list.append(order_stock['odno'])
                                # 매도 체결 완료 시, 손익, 수익률 표시
                                gain_loss_money = (int(order_stock['avg_prvs']) - stock['avg_buy_price']) * int(order_stock['tot_ccld_qty'])
                                if stock['avg_buy_price'] > 0:
                                    gain_loss_p = round(float((int(order_stock['avg_prvs']) - stock['avg_buy_price']) / stock['avg_buy_price']) * 100, 2)     # 소스 3째 자리에서 반올림                  
                                    self.SEND_MSG_INFO(f"[{stock['name']}] {order_stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {self.buy_sell_msg[buy_sell]} 전량 체결 완료, 손익:{gain_loss_money} {gain_loss_p}%", True)
                            else:
                                # 체결 완료 체크한 주문은 다시 체크하지 않는다
                                # while loop 에서 반복적으로 체크하는거 방지
                                self.buy_done_order_list.append(order_stock['odno'])                                
                                nth_buy = 0
                                for i in range(BUY_SPLIT_COUNT):
                                    if stock['buy_done'][i] == False:
                                        nth_buy = i + 1
                                        break
                                self.SEND_MSG_INFO(f"[{stock['name']}] {order_stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {nth_buy}차 {self.buy_sell_msg[buy_sell]} 전량 체결 완료", True)

                            return True, int(order_stock['avg_prvs'])
                        elif tot_trade_qty == 0:
                            # 미체결
                            return False, 0
                        elif order_qty > tot_trade_qty:
                            # 일부 체결
                            if stock['stockholdings'] < tot_trade_qty:
                                for i in range(BUY_SPLIT_COUNT):
                                    if stock['buy_done'][i] == False:
                                        # 일부만 매수된 경우, 다음날 매수 위해 매수량 업데이트
                                        stock['buy_qty'][i] -= tot_trade_qty
                                        break

                                raise Exception(f"[{stock['name']}] {order_stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {self.buy_sell_msg[buy_sell]} 체결")
                else:
                    # 해당 종목 아님
                    pass

            return False, 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
                return False, 0

    ##############################################################
    # 체결 여부 체크
    #   주문 종목에서 매수 체결 여부 확인
    ##############################################################
    def check_ordered_stocks_trade_done(self):
        result = True
        msg = ""
        try:
            is_trade_done = False

            order_list = self.get_order_list()
            for order_stock in order_list:
                code = order_stock['pdno']
                if code in self.stocks.keys():
                    buy_sell = order_stock['sll_buy_dvsn_cd']                    
                    ret, trade_done_avg_price = self.check_trade_done(code, buy_sell)
                    if ret == True:
                        is_trade_done = True
                        # 평균 체결가
                        # 매도 체결가 오류 처리 : check_trade_done() 에서 체결 완료된 trade_done_avg_price 를 avg_price 로 세팅한다.
                        if trade_done_avg_price > 0:
                            avg_price = trade_done_avg_price
                        else:
                            avg_price = int(order_stock['avg_prvs'])
                        # PRINT_DEBUG(f"trade_done_avg_price : {trade_done_avg_price}, avg_price : {avg_price}")

                        if avg_price == 0:
                            # self.SEND_MSG_ERR(f"[{order_stock['prdt_name']}] 평균 체결가 오류 {avg_price} [{self.stocks[code]['name']}]")
                            # check_trade_done 에서의 체결가로 사용
                            PRINT_INFO(f"int(order_stock['avg_prvs']) == 0, use avg_price = trade_done_avg_price({trade_done_avg_price})")
                            avg_price = trade_done_avg_price

                        if buy_sell == BUY_CODE:
                            self.set_buy_done(code, avg_price)
                            # 이전에 매도 완료 후 True 된 것을 매수 완료 후 False 로 변경
                            self.stocks[code]['end_price_higher_than_20ma_after_sold'] = False
                        else:
                            self.set_sell_done(code, avg_price)
                else:
                    # 보유는 하지만 stocks_info.json 에 없는 종목 제외 ex) 공모주
                    pass                       
            
            # 여러 종목 체결되도 결과는 한 번만 출력
            if is_trade_done == True:
                self.show_trade_done_stocks(BUY_CODE)
                self.show_trade_done_stocks(SELL_CODE)
                self.available_buy_new_stock_count = self.get_available_buy_new_stock_count()

                # 종목 체결로 종목 수 변경된 경우 관련 정보 업데이트
                after_trade_done_my_stock_count = self.get_my_stock_count()
                PRINT_DEBUG(f"체결전 보유 종목수({self.my_stock_count}), 체결 후 보유 종목수({after_trade_done_my_stock_count})")
                if self.my_stock_count != after_trade_done_my_stock_count:
                    self.my_stock_count = after_trade_done_my_stock_count
                    self.init_trade_strategy()
                    # 전략이 바뀌거나 신규 매수 가능 종목 수 변경된 경우 업데이트
                    if (self.trade_strategy.old_invest_risk != self.trade_strategy.invest_risk) or (self.available_buy_new_stock_count != self.old_available_buy_new_stock_count):
                        self.update_buyable_stocks()
                        self.show_buyable_stocks()
                # 신규 매수 가능 종목 수 변경된 경우 매수 가능 종목 업데이트
                elif self.available_buy_new_stock_count != self.old_available_buy_new_stock_count:
                    self.update_buyable_stocks()
                    self.show_buyable_stocks()

                self.old_available_buy_new_stock_count = self.available_buy_new_stock_count

                # 계좌 잔고 조회
                self.get_stock_balance()
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 주식 일별 주문 체결 조회 종목 정보 리턴
    # Parameter :
    #       trade          전체("00"), 체결("01"), 미체결("02")
    # Return    : 주문 체결/미체결 조회 종목 리스트
    ##############################################################
    def get_order_list(self, trade="00"):
        result = True
        msg = ""
        order_list = list()
        try:
            PATH = "uapi/domestic-stock/v1/trading/inquire-daily-ccld"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": self.config['TR_ID_CHECK_TRADE_DONE'],
                    "custtype": "P",
                    }
            params = {
                "CANO": self.config['CANO'],
                "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                "INQR_STRT_DT": TODAY_DATE,
                "INQR_END_DT": TODAY_DATE,
                "SLL_BUY_DVSN_CD": "00",    # 00 : 전체, 01 : 매도, 02 : 매수
                "INQR_DVSN": "00",          # 조회구분 - 00 : 역순, 01 : 정순
                "PDNO": "",                 # 종목번호(6자리), 공란 : 전체 조회
                "CCLD_DVSN": trade,         # 체결구분 - 00 : 전체, 01 : 체결 , 02 : 미체결
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == True:
                order_list = res.json()['output1']
            else:
                raise Exception(f"[update_order_list failed]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return order_list

    ##############################################################
    # 주문 조회
    #   전량 체결 완료 주문은 제외
    ##############################################################
    def show_order_list(self):
        result = True
        msg = ""
        not_traded_stock_count = 0
        try:
            PRINT_DEBUG(f"=============주문 조회=============")
            order_list = self.get_order_list()
            for order_stock in order_list:
                # 주문 수량
                order_qty = int(order_stock['ord_qty'])
                # 총 체결 수량
                tot_trade_qty = int(order_stock['tot_ccld_qty'])
                # 전량 체결 완료 주문은 제외
                if order_qty > tot_trade_qty:
                    not_traded_stock_count += 1
                    curr_price = self.get_curr_price(order_stock['pdno'])
                    order_string = self.get_order_string(order_stock['ord_dvsn_cd'])
                    PRINT_DEBUG(f"[{order_stock['prdt_name']}] {self.buy_sell_msg[order_stock['sll_buy_dvsn_cd']]} {order_string} {order_stock['ord_unpr']}원 {order_stock['ord_qty']}주, 현재가 {curr_price}원")
            PRINT_DEBUG(f"===================================")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return not_traded_stock_count

    ##############################################################
    # 체결 조회
    # Parameter :
    #       code        종목코드
    #       buy_sell    "01" : 매도, "02" : 매수
    ##############################################################
    def show_trade_done_stocks(self, buy_sell:str = SELL_CODE):
        result = True
        msg = ""
        try:
            trade_done_stock_count = 0
            if buy_sell == BUY_CODE:
                data = {'종목명':[], '매수/매도':[], '체결평균가':[], '수량':[], '현재가':[]}
            else:
                data = {'종목명':[], '매수/매도':[], '체결평균가':[], '평단가':[], '손익':[], '수익률(%)':[], '수량':[], '현재가':[]}

            order_list = self.get_order_list()
            if len(order_list) == 0:
                return None

            # PRINT_DEBUG(f"========={self.buy_sell_msg[buy_sell]} 체결 조회=========")
            for order_stock in order_list:
                if int(order_stock['tot_ccld_qty']) > 0:
                    code = order_stock['pdno']
                    if code in self.stocks.keys():
                        # dict 접근을 한번만 하여 성능 향상
                        stock = self.stocks[code]

                        if buy_sell == order_stock['sll_buy_dvsn_cd']:
                            gain_loss_p = 0
                            if buy_sell == SELL_CODE:
                                gain_loss_money = (int(order_stock['avg_prvs']) - stock['avg_buy_price']) * int(order_stock['tot_ccld_qty'])
                                if stock['avg_buy_price'] > 0:
                                    gain_loss_p = round(float((int(order_stock['avg_prvs']) - stock['avg_buy_price']) / stock['avg_buy_price']) * 100, 2)     # 소스 3째 자리에서 반올림                  
                            
                            curr_price = self.get_curr_price(code)
                            
                            data['종목명'].append(order_stock['prdt_name'])
                            data['매수/매도'].append(self.buy_sell_msg[buy_sell])
                            data['체결평균가'].append(int(float(order_stock['avg_prvs'])))
                            if buy_sell == SELL_CODE:
                                data['평단가'].append(stock['avg_buy_price'])
                                data['손익'].append(gain_loss_money)
                                data['수익률(%)'].append(gain_loss_p)
                            data['수량'].append(order_stock['tot_ccld_qty'])
                            data['현재가'].append(curr_price)
                            trade_done_stock_count += 1
                    else:
                        # 보유는 하지만 stocks_info.json 에 없는 종목 제외 ex) 공모주
                        pass

            # 매수/매도 체결 종목 있는 경우만 출력
            if trade_done_stock_count > 0:
                # PrettyTable 객체 생성 및 데이터 추가
                table = PrettyTable()
                table.field_names = list(data.keys())
                table.align = 'r'  # 우측 정렬
                for row in zip(*data.values()):
                    table.add_row(row)

                table = f"\n========={self.buy_sell_msg[buy_sell]} 체결 조회=========\n" + str(table)
                PRINT_DEBUG(table)
            return None
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 이미 주문한 종목인지 체크
    #   1차 매수/매도 2차 매수/매도 구분하기 위해 총 매수/매도 금액 비교
    #   총 매수/매도 금액이 해당 차수 금액이여야 같은 주문이다
    # Parameter :
    #       code        종목코드
    #       buy_sell    "01" : 매도, "02" : 매수
    # Return    : 이미 주문한 종목이면 Ture, 아니면 False
    ##############################################################
    def already_ordered(self, code, buy_sell: str):
        result = True
        msg = ""
        ret = False
        try:
            if buy_sell == BUY_CODE:
                ret = self.stocks[code]['buy_order_done']
            else:
                ret = self.stocks[code]['sell_order_done']
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ret

    ##############################################################
    # 종목 정보 출력
    # Parameter :
    #       send_discode    discode 전송 여부  
    #       sort_by         SORT_BY_NAME : 이름순 오름차순
    #                       SORT_BY_UNDER_VALUE : undervalue 내림차순
    ##############################################################
    def show_stocks(self, send_discode = False, sort_by=SORT_BY_NAME):
        result = True
        msg = ""
        try:
            temp_stocks = copy.deepcopy(self.stocks)

            sort_by_filed = 'name'
            reverse_value = False
            if sort_by == SORT_BY_UNDER_VALUE:
                sort_by_filed = 'undervalue'
                reverse_value = True

            sorted_data = dict(sorted(temp_stocks.items(), key=lambda x: x[1][sort_by_filed], reverse=reverse_value))
            data = {'종목명':[], '저평가':[], '목표가GAP':[], 'PER':[]}
            for code in sorted_data.keys():
                if sorted_data[code]["stock_invest_info_valid"] == True:
                    data['종목명'].append(sorted_data[code]['name'])
                    data['저평가'].append(sorted_data[code]['undervalue'])
                    data['목표가GAP'].append(sorted_data[code]['gap_max_sell_target_price_p'])
                    data['PER'].append(sorted_data[code]['PER'])

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'c'  # 가운데 정렬
            for row in zip(*data.values()):
                table.add_row(row)

            table = "\n" + str(table)
            if send_discode == False:
                self.SEND_MSG_DEBUG(table, send_discode)
            else:
                self.SEND_MSG_INFO(table, send_discode)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 저평가 높은 순으로 출력
    # Parameter :
    #       send_discode    discode 전송 여부
    ##############################################################
    def show_envelope(self, send_discode = False):
        result = True
        msg = ""
        try:
            temp_stocks = copy.deepcopy(self.stocks)
            sorted_data = dict(sorted(temp_stocks.items(), key=lambda x: x[1]['undervalue'], reverse=True))
            data = {'종목명':[], 'code':[], 'envelope_p':[], 'sell_target_p':[]}
            for code in sorted_data.keys():
                data['종목명'].append(sorted_data[code]['name'])
                data['code'].append(sorted_data[code]['code'])
                data['envelope_p'].append(sorted_data[code]['envelope_p'])
                data['sell_target_p'].append(sorted_data[code]['sell_target_p'])

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'c'  # 가운데 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            
            table = "\n" + str(table)
            self.SEND_MSG_INFO(table, send_discode)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # stocks 변경있으면 save stocks_info.json
    # Parameter :
    #       pre_stocks  이전 stocks 정보
    # Return    : 현재 stocks 정보
    ##############################################################
    def check_save_stocks_info(self, pre_stocks:dict):
        result = True
        msg = ""
        try:
            if pre_stocks != self.stocks:
                self.save_stocks_info(STOCKS_INFO_FILE_PATH)
                pre_stocks.clear()
                pre_stocks = copy.deepcopy(self.stocks)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return pre_stocks

    ##############################################################
    # 금일 매수/매도 체결 완료된 주문번호로 buy_done_order_list, sell_done_order_list 초기화
    ##############################################################    
    def init_trade_done_order_list(self):
        result = True
        msg = ""
        try:
            self.buy_done_order_list.clear()
            self.sell_done_order_list.clear()

            order_list = self.get_order_list()
            for order_stock in order_list:
                # 주문 수량
                order_qty = int(order_stock['ord_qty'])
                # 총 체결 수량
                tot_trade_qty = int(order_stock['tot_ccld_qty'])
                if tot_trade_qty == order_qty:
                    # 체결 완료 주문 번호
                    if order_stock['sll_buy_dvsn_cd'] == BUY_CODE:
                        self.buy_done_order_list.append(order_stock['odno'])
                    elif order_stock['sll_buy_dvsn_cd'] == SELL_CODE:
                        self.sell_done_order_list.append(order_stock['odno'])
                    else:
                        self.SEND_MSG_ERR(f"{order_stock['prdt_name']} not support sll_buy_dvsn_cd {order_stock['sll_buy_dvsn_cd']}")

        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 손절가
    #   last차 매수가 -x%
    # param :
    #   code            종목 코드
    ##############################################################
    def get_loss_cut_price(self, code):
        result = True
        msg = ""
        price = 0
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:   # 물타기
                # 역순 참조
                # 1차 매수 경우 1차 매수가 기준
                # 2차 매수 경우 2차 매수가 기준
                for i in range(BUY_SPLIT_COUNT - 1, -1, -1):  # 역순 참조
                    if stock['buy_done'][i] == True:
                        price = stock['buy_price'][i] * (1 - self.to_percent(LOSS_CUT_P))
                        break
            else:   # 불타기
                if BUY_SPLIT_COUNT > 1:
                    # 2차 매수까지 완료 됐으면 -2% 이탈 시 손절
                    if stock['buy_done'][1] == True:
                        price = stock['avg_buy_price'] * (1 - self.to_percent(LOSS_CUT_P_BUY_2_DONE))
                    else:
                        # 1차 매수 후 손절은 -x% 이탈 시
                        price = stock['avg_buy_price'] * (1 - self.to_percent(LOSS_CUT_P))
                else:
                    price = stock['avg_buy_price'] * (1 - self.to_percent(LOSS_CUT_P))
            
            # N차 매도 후 나머지 물량은 익절선을 낮추어 길게 간다
            if stock['sell_done'][0] == True:
                # 익절가 = 평단가과 최근 매도가의 중간
                price = stock['avg_buy_price'] + (stock['recent_sold_price'] - stock['avg_buy_price']) / 2
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            # 주식 호가 단위로 가격 변경
            return self.get_stock_asking_price(int(price))
        
    ##############################################################
    # 손절 처리
    #   1. 현재가 < 손절가 면 손절 처리
    #   2. 오늘 > 최근 매수일 + x day, 즉 x 일 동안 매수 없고
    #       손실 상태에서 1차 매도가 안됐고 last차 매수까지 안된 경우 손절
    # Return :
    #   손절 주문 시 True, 손절 주문 없을 시 False
    ##############################################################
    def handle_loss_cut(self):
        result = True
        msg = ""
        ret = False
        try:
            today = date.today()
            # 주말, 공휴일 포함
            NO_BUY_DAYS = 9
            self.my_stocks_lock.acquire()

            for code in self.my_stocks.keys():
                # 매수,매도 등 처리하지 않는 종목은 보유 종목수에서 제외
                if code in self.not_handle_stock_list:
                    continue

                # stocks_info.json 에 없는 종목은 제외
                if code not in self.stocks.keys():
                    continue

                # dict 접근을 한번만 하여 성능 향상
                stock = self.stocks[code]

                do_loss_cut = False

                # thread 처리로 set_buy_done()에서 set 되기 전 오는 경우 skip
                if stock['recent_buy_date'] == None:
                    continue

                recent_buy_date = date.fromisoformat(stock['recent_buy_date'])
                if recent_buy_date == None:
                    continue

                # 1차 매도 된 경우는 시간지났다고 손절 금지
                if stock['sell_done'][0] == False:
                    days_diff = (today - recent_buy_date).days
                    # x일간 지지부진하면 손절
                    if days_diff > NO_BUY_DAYS:
                        if stock['sell_done'][0] == False and stock['buy_done'][BUY_SPLIT_COUNT-1] == False:
                            # 손절 주문 안된 경우만 체크
                            if stock['loss_cut_order'] == False:
                                do_loss_cut = True
                                PRINT_INFO(f'{recent_buy_date} 매수 후 {today} 까지 {days_diff}일 동안 매수 없어 손절')

                curr_price = self.get_curr_price(code)
                loss_cut_price = self.get_loss_cut_price(code)
                if do_loss_cut or (curr_price > 0 and curr_price < loss_cut_price):
                    if loss_cut_price > stock['avg_buy_price']:                    
                        sell_type = '익절'
                    else:
                        sell_type = '손절'

                    stock['allow_monitoring_sell'] = True
                    stock['status'] = "매도 모니터링"
                    stockholdings = stock['stockholdings']
                    # 주문 안된 경우만 주문
                    if stock['loss_cut_order'] == False:
                        # 손절은 시장가로 주문
                        if (self.already_ordered(code, SELL_CODE) == False) and (self.sell(code, curr_price, stockholdings, ORDER_TYPE_MARKET_ORDER) == True):
                            self.set_order_done(code, SELL_CODE)
                            PRINT_INFO(f"[{stock['name']}] {sell_type} 주문 성공, 현재가({curr_price}) < {sell_type}가({loss_cut_price})")
                            stock['loss_cut_order'] = True
                            stock['status'] = f"{sell_type} 주문"
                        else:
                            self.SEND_MSG_ERR(f"[{stock['name']}] {sell_type} 주문 실패")

                if stock['loss_cut_order'] == True:
                    ret = True
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.my_stocks_lock.release()
            return ret

    ##############################################################
    # 매수 후 여지껏 최고가 업데이트
    # param :
    #   code            종목 코드
    ##############################################################
    def update_highest_price_ever(self, code):
        result = True
        msg = ""
        try:
            highest_price = self.get_highest_price(code)
            self.stocks[code]['highest_price_ever'] = max(self.stocks[code]['highest_price_ever'], highest_price)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 매수 가능 종목 업데이트
    #   last차수 매수 완료 종목은 제외
    #   저평가, 목표가GAP, 현재가-매수가GAP
    ##############################################################
    def update_buyable_stocks(self):
        result = True
        msg = ""
        try:
            temp_buyable_stocks = dict()

            # 매도 체결로 보유 종목 수 변경되어 매수 가능 종목 업데이트 시 기존 정보 삭제해야 신규 전략에 맞게 업데이트 된다
            self.buyable_stocks.clear()

            for code in self.stocks.keys():
                # dict 접근을 한번만 하여 성능 향상
                stock = self.stocks[code]

                if self.is_ok_to_buy(code, True):
                    curr_price = self.get_curr_price(code)
                    if curr_price == 0:
                        PRINT_ERR(f"[{stock['name']}] curr_price {curr_price}원")
                        continue
                    buy_target_price = self.get_buy_target_price(code)
                    if buy_target_price > 0:
                        gap_p = self.get_buy_target_price_gap(code)
                        # 현재가 - 매수가 gap < X%
                        # 1차 매수 후 n차 매수 안된 종목은 무조건 매수 가능 종목으로 편입
                        need_buy = False
                        if stock['buy_done'][0] == True:
                            for i in range(1, BUY_SPLIT_COUNT):
                                if stock['buy_done'][i] == False:
                                    need_buy = True
                                    break

                        # 액면 분할 후 거래 해제날 buyable gap 이 BUYABLE_GAP_MAX 보다 낮은 현상으로 매수되는 것 방지
                        if (gap_p >= BUYABLE_GAP_MIN and gap_p <= BUYABLE_GAP_MAX) or need_buy == True:
                            temp_stock = copy.deepcopy({code: stock})
                            temp_buyable_stocks[code] = temp_stock[code]
                        else:
                            PRINT_DEBUG(f"[{stock['name']}] 매수 금지, buyable gap({gap_p})")
                time.sleep(0.001)   # context switching between threads(main thread 와 buy_sell_task 가 context switching)

            # handle_buy_stock() 등에서 for loop 으로 self.buyable_stocks 사용 중에 self.buyable_stocks 업데이트 금지
            # 완료 후 업데이트 하도록 대기
            self.buyable_stocks_lock.acquire()
            self.buyable_stocks.clear()
            self.buyable_stocks = copy.deepcopy(temp_buyable_stocks)
            
            # 기회 적어서 저평가, 목표주가GAP 을 크게 따지지 않는다 -> 목표주가GAP 내림차순으로(큰거->작은거) 정렬하여 최대 x개 까지 유지
            buyable_count = min(BUYABLE_COUNT, len(self.buyable_stocks))
            sorted_list = sorted(self.buyable_stocks.items(), key=lambda x: x[1]['gap_max_sell_target_price_p'], reverse=True)
            self.buyable_stocks = dict(sorted_list[:buyable_count])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.buyable_stocks_lock.release()

    ##############################################################
    # 매수 가능 종목 출력
    ##############################################################
    def show_buyable_stocks(self):
        result = True
        msg = ""
        try:
            temp_stocks = copy.deepcopy(self.buyable_stocks)

            # 매수가GAP 작은 순으로 정렬위해 임시로 추가
            for code in temp_stocks.keys():
                gap_p = self.get_buy_target_price_gap(code)
                temp_stocks[code]['buy_target_price_gap'] = gap_p

            # 매수가GAP 작은 순으로 정렬
            sorted_data = dict(sorted(temp_stocks.items(), key=lambda x: x[1]['buy_target_price_gap'], reverse=False))
            data = {'종목명':[], '매수가gap(%)':[], '매수가':[], '현재가':[], '저평가':[], '목표가gap(%)':[], 'Envelope':[]}
            if self.trade_strategy.use_trend_60ma == True:
                data['60일선추세'] = []
            if self.trade_strategy.use_trend_90ma == True:
                data['90일선추세'] = []
            
            data['상태'] = []

            for code in sorted_data.keys():
                curr_price = self.get_curr_price(code)
                buy_target_price = self.get_buy_target_price(code)
                data['종목명'].append(sorted_data[code]['name'])
                data['매수가gap(%)'].append(sorted_data[code]['buy_target_price_gap'])
                data['매수가'].append(buy_target_price)
                data['현재가'].append(curr_price)
                data['저평가'].append(sorted_data[code]['undervalue'])
                data['목표가gap(%)'].append(sorted_data[code]['gap_max_sell_target_price_p'])
                data['Envelope'].append(sorted_data[code]['envelope_p'])
 
                if self.trade_strategy.use_trend_60ma == True:
                    data['60일선추세'].append(self.str_trend[sorted_data[code]['trend_60ma']])

                if self.trade_strategy.use_trend_90ma == True:
                    data['90일선추세'].append(self.str_trend[sorted_data[code]['trend_90ma']])
                
                data['상태'].append(self.stocks[code]['status'])

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'r'  # 우측 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            
            table = f"\n==========매수 가능 종목(전략:Envelope{DEFAULT_ENVELOPE_P})==========\n" + str(table)
            PRINT_DEBUG(table)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 익절가 리턴
    #   여지껏 최고가 - 익절가%
    # param :
    #   code            종목 코드    
    ##############################################################
    def get_take_profit_price(self, code):
        result = True
        msg = ""
        price = 0
        try:
            self.update_highest_price_ever(code)
            price = int(self.stocks[code]['highest_price_ever'] * (1 - self.to_percent(TAKE_PROFIT_P)))
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return int(price)

    ##############################################################
    # clear after market
    #   전날에 조건에 맞았지만 체결안된 경우 다음 날 다시 조건 검사부터 한다.
    ##############################################################
    def clear_after_market(self):
        result = True
        msg = ""
        try:
            for code in self.stocks.keys():
                # dict 접근을 한번만 하여 성능 향상
                stock = self.stocks[code]
                
                stock['allow_monitoring_buy'] = False
                stock['allow_monitoring_sell'] = False                 
                stock['loss_cut_order'] = False
                stock['buy_order_done'] = False
                stock['sell_order_done'] = False
                if stock['sell_all_done'] == True:
                    stock['avg_buy_price'] = 0
                stock['lowest_price_1'] = 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
 
    ##############################################################
    # 금일 기준 X 일 내 최고 종가 리턴
    # param :
    #   code        종목 코드
    #   days        X 일
    #               ex) 1 : 금일 종가
    #                   22 : 금일 기준 22 내(영업일 기준 약 한 달)    
    ##############################################################
    def get_highest_end_pirce(self, code, days=22):
        result = True
        msg = ""
        highest_end_price = 0
        try:
            if days > 99:
                PRINT_INFO(f'can read over 99 data. make days to 99')
                days = 99
            elif days <= 0:
                days = 1

            end_price_list = self.get_price_list(code, "D", PRICE_TYPE_CLOSE, days)
            highest_end_price = max(end_price_list[:days])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return highest_end_price

    ##############################################################
    # 기간 내 최고 종가에서 급락 가격 리턴
    #   1차 매수가는 이 가격 이하로
    #   단기간에 급락해야 매수하기 위함
    #   ex) 한 달 내 최고 종가 - x%
    # param :
    #   code        종목 코드
    #   margin_p   급락 margine percent
    ##############################################################
    def get_plunge_price(self, code, margin_p=0):
        result = True
        msg = ""
        try:
            price = 0
            # 22일(영업일 기준 약 한 달)
            highest_end_price = self.get_highest_end_pirce(code, 22)

            # margin_p 가 주어지면 주어진 margin_p 사용
            if margin_p == 0:
                # TODO: 기회 너무 적으면 margin_p 줄인다
                # 최고 종가에서 최소 X% 폭락 가격
                if self.stocks[code]['market_cap'] >= 100000:   # 시총 10조 이상이면
                    margin_p = self.to_percent(23)
                else:
                    margin_p = self.to_percent(25)
          
            # # 전략에 따라 폭락 가격 조정
            # if self.trade_strategy.invest_risk == INVEST_RISK_MIDDLE:
            #     margin_p = margin_p + self.to_percent(1)
            # elif self.trade_strategy.invest_risk == INVEST_RISK_LOW:
            #     margin_p = margin_p + self.to_percent(2)

            price = highest_end_price * (1 - margin_p)
            # PRINT_DEBUG(f"[{self.stocks[code]['name']}] 최고 종가 : {highest_end_price}원, 폭락 가격 : {price}원")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return int(price)

    ##############################################################
    # 보유 주식 종목 수
    ##############################################################
    def get_my_stock_count(self):
        result = True
        msg = ""
        my_stocks_count = 0
        try:
            PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": self.config['TR_ID_GET_STOCK_BALANCE'],
                    "custtype": "P",
                    }
            params = {
                "CANO": self.config['CANO'],
                "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            res = self.requests_get(URL, headers, params)
            if self.is_request_ok(res) == True:
                stocks = res.json()['output1']
                for my_stock in stocks:
                    # 매수,매도 등 처리하지 않는 종목은 보유 종목수에서 제외
                    if my_stock['pdno'] in self.not_handle_stock_list:
                        continue

                    if int(my_stock['hldg_qty']) > 0:
                        my_stocks_count += 1
            else:
                raise Exception(f"[계좌 조회 실패]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return my_stocks_count

    ##############################################################
    # 매매 전략 세팅
    #   ex) 매매 금지 저평가 기준
    ##############################################################
    def init_trade_strategy(self):
        result = True
        msg = ""
        try:
            # 투자 전략은 보유 주식 수에 따라 자동으로 처리
            # 현재 보유 주식 수가 최대 보유 주식 수의
            # 1/3 이하 : high(공격적)
            # 2/3 이하 : middle(중도적)
            # 2/3 초과 : low(보수적)
            self.update_my_stocks()

            if self.my_stock_count == 0:
                self.my_stock_count = self.get_my_stock_count()

            self.trade_strategy.old_invest_risk = self.trade_strategy.invest_risk

            if self.my_stock_count <= MAX_MY_STOCK_COUNT * 1/3:
                self.trade_strategy.invest_risk = INVEST_RISK_HIGH
            elif self.my_stock_count <= MAX_MY_STOCK_COUNT * 2/3:
                self.trade_strategy.invest_risk = INVEST_RISK_MIDDLE
            else:
                self.trade_strategy.invest_risk = INVEST_RISK_LOW
            
            self.trade_strategy.sell_trailing_stop = True

            self.trade_strategy.buy_trailing_stop = True        # 매수 후 트레일링 스탑 사용 여부
            self.trade_strategy.use_trend_60ma = True           # 60일선 추세 사용 여부
            self.trade_strategy.use_trend_90ma = True           # 90일선 추세 사용 여부

            # 기회 적다 -> 조건을 완화하여 매수 기회 늘림
            invest_risk_high_under_value = -100
            invest_risk_high_gap_max_sell_target_price_p = -100
            invest_risk_high_sum_under_value_sell_target_gap = -100            
            
            if self.trade_strategy.invest_risk == INVEST_RISK_HIGH:
                self.trade_strategy.max_per = 100                   # PER가 이 값 이상이면 매수 금지
                # 저평가가 이 값 미만은 매수 금지
                self.trade_strategy.under_value = invest_risk_high_under_value                       
                # 목표가GAP 이 이 값 미만은 매수 금지
                self.trade_strategy.gap_max_sell_target_price_p = invest_risk_high_gap_max_sell_target_price_p         
                # 저평가 + 목표가GAP 이 이 값 미만은 매수 금지
                self.trade_strategy.sum_under_value_sell_target_gap = invest_risk_high_sum_under_value_sell_target_gap     
                # 시총 X 미만 매수 금지(억)
                self.trade_strategy.buyable_market_cap = 4000             
                # 추세선이 이거 이상이여야 매수
                self.trade_strategy.trend_60ma = TREND_SIDE
                self.trade_strategy.trend_90ma = TREND_SIDE
            elif self.trade_strategy.invest_risk == INVEST_RISK_MIDDLE:
                self.trade_strategy.max_per = 50                   # PER가 이 값 이상이면 매수 금지
                self.trade_strategy.under_value = 0
                self.trade_strategy.gap_max_sell_target_price_p = 0
                self.trade_strategy.sum_under_value_sell_target_gap = 5
                self.trade_strategy.buyable_market_cap = 10000
                self.trade_strategy.trend_60ma = TREND_UP
                self.trade_strategy.trend_90ma = TREND_SIDE
            else:   # INVEST_RISK_LOW
                self.trade_strategy.max_per = 50                   # PER가 이 값 이상이면 매수 금지
                self.trade_strategy.under_value = 5
                self.trade_strategy.gap_max_sell_target_price_p = 5
                self.trade_strategy.sum_under_value_sell_target_gap = 10
                self.trade_strategy.buyable_market_cap = 20000    
                self.trade_strategy.trend_60ma = TREND_UP
                self.trade_strategy.trend_90ma = TREND_SIDE
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.print_strategy()

    #TODO: ta lib 로 대체
    # # 1. 종가 데이터 (list)
    # closes[0] = oldest
    # closes[-1] = today
    # closes = [35200, 36250, 37250, 36400, 37000, 36650, 36650, 37450, 37750, 40500, 39750, 40400, 39800, 40600, 39850, 42900, 48850]

    # # 2. 리스트를 pandas Series로 변환
    # close_series = pd.Series(closes)

    # # 3. RSI 계산 (ta.momentum.RSIIndicator 사용)
    # rsi_indicator = ta.momentum.RSIIndicator(close=close_series, window=14)
    # rsi_values = rsi_indicator.rsi()

    ##############################################################
    # get RSI
    #   RIS 는 최초 데이터부터 계산되어야 정확하다
    #   데이터가 적을수록 RSI 값이 정확하지 않다
    # param :
    #   code        종목 코드                
    #   past_day    과거 언제 RSI 구할건지
    #               ex) 0 : 금일, 1 : 어제
    #   period      RSI 기간
    ##############################################################
    def get_rsi(self, code: str, past_day=0, period=20):
        result = True
        msg = ""
        try:
            # 종가 100건 구하기, index 0 이 금일
            end_price_list = self.get_price_list(code, "D", PRICE_TYPE_CLOSE)

            # x일간의 종가 구한다
            # 마지막 날의 상승/하락분을 위해 마지막날 이전날 데이터까지 구한다
            # ex) 20 일간의 상승/하락분을 구하려면 21일간의 데이터 필요
            data_count = len(end_price_list)
            days_last = past_day + period + 1
            if days_last > data_count:
                raise Exception(f"Can't get more than 99 days data, period:{period}, past_day:{past_day}, days_last:{days_last}")

            # 상승/하락분 구하기
            up_price_list = []      # index 0 이 금일
            down_price_list = []    # index 0 이 금일
            for i in range(data_count):  # end_price_list[0] 는 금일 종가, end_price_list[99] 는 제일 예전 종가
                # 제일 예전 종가는 이전 종가가 없어서 skip
                if i+1 >= data_count:
                    break
                # ex) 오늘 종가 - 어제 종가
                diff_price = end_price_list[i] - end_price_list[i+1]
                if diff_price > 0:
                    up_price_list.append(diff_price)
                    down_price_list.append(0)
                elif diff_price < 0:
                    up_price_list.append(0)
                    down_price_list.append(abs(diff_price))
                else:
                    # diff_price == 0
                    up_price_list.append(diff_price)
                    down_price_list.append(diff_price)

            # 상승폭 평균(AU)
            # oldest day 에서 period 동안의 AU0
            # ex) AU0 는 up_price_list[98] ~ up_price_list[79] 까지의 평균, AU79는 금일
            last_period = up_price_list[-1:-period-1:-1]    # 역순으로 마지막 period 개의 요소를 추출
            au0 = sum(last_period) / len(last_period)
            au_list = []    # index 0 이 oldest
            au_list.append(au0)

            # 그 다음 AU = (이전 AU * (period-1) + 현재 이득) / period
            # AU1 ~ AU79, up20 ~ up98
            up_price_list_len = len(up_price_list)
            for i in range(period, up_price_list_len):
                au_list.append((au_list[-1]*(period-1) + up_price_list[up_price_list_len-i-1]) / period)

            # 하락폭 평균(AD)
            # oldest day 에서 period 동안의 AD0
            # ex) AD0 는 down_price_list[98] ~ down_price_list[79] 까지의 평균
            last_period = down_price_list[-1:-period-1:-1]    # 역순으로 마지막 period 개의 요소를 추출
            ad0 = sum(last_period) / len(last_period)
            ad_list = []    # index 0 이 oldest
            ad_list.append(ad0)

            # 그 다음 AD = (이전 DU * (period-1) + 현재 손실) / period
            # AD1 ~ AD79, down20 ~ down98
            down_price_list_len = len(down_price_list)
            for i in range(period, down_price_list_len):
                ad_list.append((ad_list[-1]*(period-1) + down_price_list[down_price_list_len-i-1]) / period)

            rsi_list = []       # index 0 이 금일
            for i in range(len(au_list)):
                # RSI = AU/(AU+AD)*100
                rsi_list.insert(0, au_list[i]/(au_list[i]+ad_list[i])*100)

            return int(rsi_list[past_day])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
                return 0

    ##############################################################
    # 종목마다 매수 가능한 RSI 값 리턴
    #   ex) 시총 1조 이상은 x, 미만은 y
    # param :
    #   code        종목 코드                
    ##############################################################
    def get_buy_rsi(self, code: str):
        result = True
        msg = ""
        buy_rsi = 0
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            RSI_BASE_NUMBER = 490
            buy_rsi = int(RSI_BASE_NUMBER / stock['envelope_p'])
            market_cap = max(1, int(stock['market_cap'] / 10000))

            if stock['trend_60ma'] == TREND_UP:
                # 조단위 시총
                # 시총에 따라 buy rsi 변경
                buy_rsi += min(6, market_cap*2)
            elif stock['trend_60ma'] == TREND_SIDE:
                buy_rsi += min(4, market_cap)
            # 최소 buy_rsi
            buy_rsi = max(37, buy_rsi)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return buy_rsi

    ##############################################################
    # 이평선의 추세 리턴
    #   default 어제 기준, X일 동안 연속 상승이면 상승추세, 하락이면 하락, 그외 보합
    #   상승 : TREND_UP
    #   보합 : TREND_SIDE
    #   하락 : TREND_DOWN
    # param :
    #   code                종목 코드
    #   ma                  X일선
    #                       ex) 20일선 : 20, 5일선 : 5
    #   past_day            X일선 가격 기준
    #                       ex) 0 : 금일 X일선, 1 : 어제 X일선    
    #   consecutive_days    X일동안 연속 상승이면 상승추세, 하락이면 하락, 그외 보합
    #   period              D : 일, W : 주, M : 월, Y : 년
    #   ref_ma_diff_p       이 값(%) 이상 이평 이격 있어야 정배열
    ##############################################################
    def get_ma_trend(self, code: str, past_day=1, ma=60, consecutive_days=TREND_UP_CONSECUTIVE_DAYS, period="D", ref_ma_diff_p=TREND_UP_DOWN_DIFF_60MA_P):
        result = True
        msg = ""
        ma_trend = TREND_DOWN
        try:
            # diff 는 절대값으로 비교
            ref_ma_diff_p = abs(ref_ma_diff_p)
                        
            # x일 연속 상승,하락인지 체크 그외 보합
            trend_up_count = 0
            trend_down_count = 0
            ma_price = self.get_ma(code, ma, past_day, period)
            start_day = past_day+1
            last_day = past_day+consecutive_days

            # 이평선 기울기 구하기 위해 last, recent ma price 구한다
            recent_ma_price = ma_price
            last_ma_price = self.get_ma(code, ma, consecutive_days + past_day - 1, period)
            # diff 는 절대값으로 비교
            ma_diff_p = abs(((recent_ma_price - last_ma_price) / last_ma_price) * 100)
            
            for i in range(start_day, last_day):
                if i < last_day:
                    yesterdat_ma_price = self.get_ma(code, ma, i, period)
                    if ma_price > yesterdat_ma_price:
                        trend_up_count += 1
                    elif ma_price < yesterdat_ma_price:
                        trend_down_count += 1
                    ma_price = yesterdat_ma_price
            
            if trend_up_count >= (consecutive_days - 1) and ma_diff_p > ref_ma_diff_p:
                ma_trend = TREND_UP
            elif trend_down_count >= (consecutive_days - 1) and ma_diff_p > ref_ma_diff_p:
                ma_trend = TREND_DOWN
            else:
                ma_trend = TREND_SIDE
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ma_trend

    ##############################################################
    # 장마감전은 어제 기준, 장마감 후는 금일 기준 2개 이상의 이평선의 배열 상태 리턴
    #   ex) "60 이평선 가격 > 90 이평선 가격 > 120 이평선 가격" 이면 정배열, 반대면 역배열
    #       그 외는 soso
    # param :
    #   code                종목 코드
    #   ma_list             이평선 리스트   ex) [60,90]
    #                       주의, 이평선 입력은 오름차순
    #   period              D : 일, W : 주, M : 월, Y : 년
    #   diff_p              이평선 간 이격도 이상 벌어져야 정배열
    #                       ex) diff_p = 3 이면 20,60,90이평 간에 3% 이상 차이나야 정배열
    ##############################################################
    def get_multi_ma_status(self, code: str, ma_list:list, period="D", diff_p=0):
        result = True
        msg = ""
        ma_status = MA_SIDE_TREND
        try:
            past_day = self.get_past_day()
            ma_price_list = []
            for ma in ma_list:
                ma_price_list.append(self.get_ma(code, ma, past_day, period))

            positive_count = 0
            negative_count = 0
            
            ma_price_list_len = len(ma_price_list)
            for i in range(ma_price_list_len):
                if i+1 >= ma_price_list_len:
                    break
                if ma_price_list[i] * (1 - self.to_percent(diff_p)) > ma_price_list[i+1]:
                    positive_count += 1
                else:
                    negative_count += 1

            if positive_count >= (ma_price_list_len-1):
                ma_status = MA_UP_TREND
            elif negative_count >= (ma_price_list_len-1):
                ma_status = MA_DOWN_TREND
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return ma_status

    ##############################################################
    # 1차 목표가 리턴
    # param :
    #   code            종목 코드    
    ##############################################################
    def get_first_sell_target_price(self, code):
        result = True
        msg = ""
        # dict 접근을 한번만 하여 성능 향상
        stock = self.stocks[code]
        price = stock['first_sell_target_price']
        try:
            # 1차 매도 안됐다 -> sell_target_price 가 1차 목표가이다.
            if stock['sell_done'][0] == False:
                price = stock['sell_target_price']
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return self.get_stock_asking_price(int(price))
        
    ##############################################################
    # 상황에 따른 envelope_p 계산하여 리턴
    # param :
    #   code                종목 코드  
    #   is_market_crash     시장 폭락 여부
    #   market_profit_p     금일 코스피지수 전일 대비율(수익률)
    ##############################################################
    def get_envelope_p(self, code, is_market_crash=False, market_profit_p=0):
        result = True
        msg = ""
        envelope_p = 20
        try:
            # 시총 10조 이상이면 envelope_p = X
            if self.stocks[code]['market_cap'] >= 100000:
                envelope_p = DEFAULT_ENVELOPE_P - 2
            else:
                envelope_p = DEFAULT_ENVELOPE_P

            # 목표가GAP 에 따라 envelope_p 조정
            if self.stocks[code]['gap_max_sell_target_price_p'] < -10:
                envelope_p = envelope_p + 1

            # 시장 폭락 시 envelope 증가
            if is_market_crash == True:
                # envelope 증가 등으로 보수적으로 접근
                # ex) 지수가 4% 폭락 시 4/2+1 = 3 을 envelope 증가
                envelope_p = int(envelope_p + (abs(market_profit_p) / 2 ) + 1)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return envelope_p
        
    ##############################################################
    # 주문가 문자열 리턴
    # param :
    #   order_type      주문 타입(지정가, 최유리지정가,...)
    ##############################################################
    def get_order_string(self, order_type):
        result = True
        msg = ""
        order_string = ""
        try:
            if order_type == ORDER_TYPE_LIMIT_ORDER:
                order_string = "지정가"
            elif order_type == ORDER_TYPE_MARKET_ORDER:
                order_string = "시장가"
            elif order_type == ORDER_TYPE_MARKETABLE_LIMIT_ORDER:
                order_string = "최유리지정가"
            elif order_type == ORDER_TYPE_IMMEDIATE_ORDER:
                order_string = "최우선지정가"
            elif order_type == ORDER_TYPE_BEFORE_MARKET_ORDER:
                order_string = "장전 시간외"
            elif order_type == ORDER_TYPE_AFTER_MARKET_ORDER:
                order_string = "장후 시간외"
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return order_string

    ##############################################################
    # 시장 폭락 시 처리
    #   envelope 등을 증가시켜 매수가를 낮춘다
    ##############################################################
    def check_market_crash(self):
        result = True
        msg = ""
        try:
            self.market_profit_p = self.get_market_profit_p()
            if self.market_profit_p < self.lowest_market_profit_p:
                if self.market_profit_p <= self.market_crash_profit_p and abs(self.lowest_market_profit_p - self.market_profit_p) >= 1:
                    # 시장이 -4%, -5%, -6%, ... 폭락 시 업데이트
                    self.update_stocks_trade_info_market_crash(self.market_profit_p)
                self.lowest_market_profit_p = self.market_profit_p
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)


    ##############################################################
    # 금일 코스피 지수 수익률(%) 리턴
    #   단위 %, ex) 4% 는 4, 5.2% 는 5.2 리턴
    ##############################################################
    def get_market_profit_p(self):
        result = True
        msg = ""
        market_profit_p = 0     # 퍼센트
        try:
            market_profit_p = self.get_sector_data("0001", "BSTP_NMIX_PRDY_CTRT")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return market_profit_p

    ##############################################################
    # 국내 주식 업종 기간별 시세
    #   Return : 성공 시 요청한 시세, 실패 시 0 리턴
    #   Parameter :
    #       code            업종 코드 ex) KOSPI는 0001
    #       type            요청 시세(업종 지수 전일 대비율, 전일 지수, 업종 지수 최고가 ...)
    #       period          D : 일, W : 주, M : 월, Y : 년
    ##############################################################
    def get_sector_data(self, code:str, type:str, period="D"):
        result = True
        msg = ""
        data = 0
        try:
            PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": "FHKUP03500100"}
            params = {
                "fid_cond_mrkt_div_code": "U",
                "fid_input_iscd": code,
                # 조회 시작일자 ex) 20220501
                "fid_input_date_1": TODAY_DATE,
                # 조회 종료일자 ex) 20220530
                "fid_input_date_2": TODAY_DATE,
                "fid_period_div_code": period
            }

            res = self.requests_get(URL, headers, params)

            type = type.lower()     # element 는 소문자로 해야 동작
            if self.is_request_ok(res) == True:
                data = float(res.json()['output1'][type])
            else:
                raise Exception(f"[get_sector_data failed]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return data

    ##############################################################
    # 시장 폭락 시 처리
    #   envelope 증가 등으로 보수적으로 접근
    #   1차 매수가를 낮춘다
    # Parameter :
    #       market_profit_p       금일 코스피지수 전일 대비율(수익률)
    ##############################################################
    def update_stocks_trade_info_market_crash(self, market_profit_p):
        result = True
        msg = ""
        try:
            PRINT_INFO(F"지수 폭락({market_profit_p}%)으로 envelope 증가시켜 1차 매수가 낮춘다")

            stocks_codes = list(self.stocks.keys())

            def process_update_stock_trade_info_market_crash(code):
                try:
                    stock = self.stocks[code]

                    # 1차 매수 안된 경우만 업데이트
                    if stock['buy_done'][0] == False:
                        # envelope 증가 등으로 보수적으로 접근
                        # ex) 지수가 4% 폭락 시 4/2+1 = 3 을 envelope 증가
                        stock['envelope_p'] = self.get_envelope_p(code, True, market_profit_p)

                        # 매수가 세팅
                        self.set_buy_price(code)
                        # 매수 수량 세팅
                        self.set_buy_qty(code)                    

                    # 보유 주식 아닌 경우에 업데이트
                    if self.is_my_stock(code) == False:
                        # 평단가 = 1차 매수가
                        stock['avg_buy_price'] = stock['buy_price'][0]
                        # 목표가
                        stock['sell_target_price'] = self.get_sell_target_price(code)
                        PRINT_DEBUG(f"[{stock['name']}] new envelope {stock['envelope_p']}")

                    # time.sleep(0.001)   # context switching between threads(main thread 와 buy_sell_task 가 context switching)

                except Exception as e:
                    PRINT_ERR(f"[{stock['name']}] 처리 중 오류: {e}")
            #################### end of process_update_stock_trade_info_market_crash() ####################

            with ThreadPoolExecutor(max_workers=14) as executor:
                executor.map(process_update_stock_trade_info_market_crash, stocks_codes)
            
            # 매수 주문 후 시장 폭락으로 buy_qty 변경되었는데 변경 전 buy_qty 로 매수 완료 경우 매수 완료 처리 안되는 문제 발생
            # -> 기존 미체결 매수 주문 취소
            order_list = self.get_order_list(TRADE_NOT_DONE_CODE)
            for order_stock in order_list:
                if order_stock['sll_buy_dvsn_cd'] == BUY_CODE:
                    self.cancel_order(order_stock['pdno'], BUY_CODE)
                    self.stocks[order_stock['pdno']]['allow_monitoring_buy'] = False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 서버에 get 요청 개선
    #   REST API 호출 오류 해결
    #   세션 객체는 요청 간에 쿠키나 연결 상태를 유지합니다. 
    #   이를 통해 서버와의 지속적인 연결을 유지하고, 같은 서버로의 반복적인 요청을 효율적으로 처리할 수 있습니다.
    #   여러 번의 요청을 할 때 더 효율적이며, 특히 쿠키를 유지해야 하거나 서버와의 연결을 재사용해야 하는 경우 유리합니다.
    # param :
    #   URL             request get 할 URL
    #   headers         headers data
    #   params          params data
    ##############################################################
    def requests_get(self, URL, headers, params):
        result = True
        msg = ""
        ret = None
        try:
            self.request_lock.acquire()
            # requests.Session()을 사용하여 세션 객체를 생성하고(rs), 그 세션을 통해 get 요청을 보내는 것입니다.
            # 세션 객체는 요청 간에 쿠키나 연결 상태를 유지합니다. 이를 통해 서버와의 지속적인 연결을 유지하고, 
            # 같은 서버로의 반복적인 요청을 효율적으로 처리할 수 있습니다.
            rs = requests.session()
            # HTTPAdapter를 통해 HTTP 연결 풀의 크기 및 재시도 횟수를 설정합니다
            # pool_connections=3: 연결 풀에 최대 3개의 연결을 유지합니다.
            # pool_maxsize=10: 이 세션을 통해 최대 10개의 연결을 동시에 처리할 수 있습니다
            # max_retries=3: 요청이 실패했을 때 최대 3번 재시도합니다.
            rs.mount('https://', requests.adapters.HTTPAdapter(pool_connections=3, pool_maxsize=10, max_retries=3))
            ret = rs.get(URL, headers=headers, params=params)
            time.sleep(API_DELAY_S)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.request_lock.release()
            return ret

    ##############################################################
    # 보유 종목에 필요한 투자금 리턴
    #   ex) 보유 종목 수 2개, 2종목 모두 1차 매수 완료 2차 매수 대기 상태
    #   종목 당 2차 매수에 40만원 필요 -> 80만원 리턴
    # Return : 보유 종목에 필요한 투자금
    ##############################################################
    def get_invest_money_for_my_stock(self):
        result = True
        msg = ""
        # 보유 종목에 필요한 투자금
        need_total_invest_money = 0
        try:
            self.my_stocks_lock.acquire()
            for code in self.my_stocks.keys():
                # 매수,매도 등 처리하지 않는 종목
                if code in self.not_handle_stock_list:
                    continue

                # stocks_info.json 에 없는 종목은 제외
                if code not in self.stocks.keys():
                    continue
                
                # 보유 주식 중 투자에 필요한 금액
                for i in range(len(self.buy_invest_money)):
                    if self.stocks[code]['buy_done'][i] == False:
                        need_total_invest_money = need_total_invest_money + self.buy_invest_money[i]

        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            self.my_stocks_lock.release()
            return need_total_invest_money

    ##############################################################
    # 분할 매도 수량 세팅
    # param :
    #   code            종목 코드
    ##############################################################
    def set_sell_qty(self, code):
        result = True
        msg = ""
        try:
            # dict 접근을 한번만 하여 성능 향상
            stock = self.stocks[code]

            # 분할 매도 수량, 소수 첫째 자리에서 반올림
            qty = max(1, round(stock['stockholdings'] / SELL_SPLIT_COUNT))

            for i in range(SELL_SPLIT_COUNT):
                remain_qty = max(0, stock['stockholdings'] - (qty * i))
                if remain_qty >= qty:
                    if i == (SELL_SPLIT_COUNT - 1):
                        # 마지막 매도 수량은 나머지 수량
                        stock['sell_qty'][i] = remain_qty
                    else:
                        stock['sell_qty'][i] = qty
                else:
                    stock['sell_qty'][i] = remain_qty
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 현재 분할 매도 수량 리턴
    # param :
    #   code            종목 코드
    ##############################################################
    def get_sell_qty(self, code):
        result = True
        msg = ""
        qty = 0
        try:
            for i in range(SELL_SPLIT_COUNT):
                if self.stocks[code]['sell_done'][i] == False:
                    qty = self.stocks[code]['sell_qty'][i]
                    break
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return qty
        
    ##############################################################
    # 투자금액 가중치
    #   상황에 따라 비중 조절
    # param :
    #   code            종목 코드
    ##############################################################
    def get_invest_money_weight(self, code):
        result = True
        msg = ""
        invest_money_weight = 0
        try:
            if self.stocks[code]['market_cap'] >= 50000:
                # 시총 x조 이상이면 비중 확대
                invest_money_weight = INVEST_MONEY_PER_STOCK / 3
            elif self.stocks[code]['market_cap'] < 10000:
                # 시총 y조 미만이면 비중 축소
                invest_money_weight = -(INVEST_MONEY_PER_STOCK / 3)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return invest_money_weight
            
    ##############################################################
    # 매수가gap(%) 리턴
    # param :
    #   code            종목 코드
    ##############################################################
    def get_buy_target_price_gap(self, code):
        result = True
        msg = ""
        buy_target_price_gap = 0
        try:
            curr_price = self.get_curr_price(code)
            buy_target_price = self.get_buy_target_price(code)
            if buy_target_price > 0:
                buy_target_price_gap = int((curr_price - buy_target_price) * 100 / curr_price)
            else:
                buy_target_price_gap = 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return buy_target_price_gap
        
    ##############################################################
    # 장마감전은 어제 기준(1), 장마감 후 or 휴일은 금일 기준(0) 리턴
    #   어제 X값을 구하기위해 장마감 후인지 아닌지에 따라 다르다
    # ##############################################################
    def get_past_day(self):
        result = True
        msg = ""
        past_day = 0
        try:
            t_now = datetime.datetime.now()
            # 15:30 장마감 후는 금일기준으로 20일선 구한다
            if T_MARKET_END < t_now or (TODAY == SATURDAY or TODAY == SUNDAY):
                past_day = 0        # 장마감 후 or 휴일은 금일 기준
            else:
                past_day = 1        # 어제 기준            
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return past_day

    ##############################################################
    # 장 전, 장 중, 장 마감 후로 나누어 시장 시간 상태 리턴
    #   장 전 : BEFORE_MARKET, 장 중 : MARKET_ING, 장 마감 후 : AFTER_MARKET
    ##############################################################
    def get_market_time_state(self):
        result = True
        msg = ""
        market_time_state = BEFORE_MARKET
        try:
            t_now = datetime.datetime.now()
            if t_now < T_MARKET_START:
                market_time_state = BEFORE_MARKET
            elif T_MARKET_START <= t_now < T_MARKET_END:
                market_time_state = MARKET_ING
            elif t_now >= T_MARKET_END:
                market_time_state = AFTER_MARKET
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)
            return market_time_state

    ##############################################################
    # 매수 체크 가격
    ##############################################################
    def check_buy_price(self, curr_price, lowest_price, buy_margin):
        return (curr_price >= (lowest_price * buy_margin)) and (curr_price < (lowest_price * (buy_margin + self.to_percent(1))))

    ##############################################################
    # 물타기 매수 전략
    ##############################################################
    def handle_buy_split_strategy_down(self, code, buy_margin):
        result = True
        msg = ""
        try:
            t_now = datetime.datetime.now()

            stock = self.stocks[code]
            
            price_data = self.get_price_data(code)
            curr_price = int(price_data['stck_prpr'])
            if curr_price == 0:
                PRINT_ERR(f"[{stock['name']}] curr_price {curr_price}원")
                return

            lowest_price = int(price_data['stck_lwpr'])
            # 9시 장 시작시 lowest_price 0으로 나옴
            if lowest_price == 0:
                return

            buy_target_price = self.get_buy_target_price(code)

            if stock['allow_monitoring_buy'] == False:                        
                # 목표가 왔다 -> 매수 감시 시작
                if curr_price <= buy_target_price:
                    if self.check_buy_price(curr_price, lowest_price,buy_margin):
                        # 1차 매수 시 하한가 매수 금지 위해 전일 대비율(현재 등락율)이 MIN_PRICE_CHANGE_RATE_P % 이상에서 매수
                        if stock['buy_done'][0] == False and float(price_data['prdy_ctrt']) >= MIN_PRICE_CHANGE_RATE_P:
                            PRINT_INFO(f"[{stock['name']}] 매수 감시 시작, {curr_price}(현재가) {buy_target_price}(매수 목표가)")
                            stock['allow_monitoring_buy'] = True
                            stock['status'] = "매수 모니터링"
                            # 매수 모니터링 시작한 저가
                            stock['lowest_price_1'] = lowest_price
            else:
                # buy 모니터링 중
                # "저가 < 매수 모니터링 시작한 저가 and 현재가 >= 저가 + BUY_MARGIN_P% and 현재가 < 저가 + (BUY_MARGIN_P+1)%" 에서 매수
                # 즉, 두 번 째 최저가 + BUY_MARGIN_P 에서 매수                        
                # "15:15" 까지 매수 안됐고 "현재가 <= 매수가"면 매수
                if (lowest_price < stock['lowest_price_1']) \
                    and self.check_buy_price(curr_price, lowest_price,buy_margin) \
                    or (t_now >= T_BUY_AFTER and curr_price <= buy_target_price):
                    if stock['buy_order_done'] == False:
                        buy_target_qty = self.get_buy_target_qty(code)
                        if self.buy(code, curr_price, buy_target_qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                            self.set_order_done(code, BUY_CODE)        
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)

    ##############################################################
    # 불타기 매수 전략
    ##############################################################
    def handle_buy_split_strategy_up(self, code, buy_margin):
        result = True
        msg = ""
        try:
            t_now = datetime.datetime.now()

            stock = self.stocks[code]

            price_data = self.get_price_data(code)
            curr_price = int(price_data['stck_prpr'])
            if curr_price == 0:
                PRINT_ERR(f"[{stock['name']}] curr_price {curr_price}원")
                return

            lowest_price = int(price_data['stck_lwpr'])
            # 9시 장 시작시 lowest_price 0으로 나옴
            if lowest_price == 0:
                return

            buy_target_price = self.get_buy_target_price(code)

            if stock['buy_done'][0] == False:
                # 1차 매수 안된 경우 매수가 이하에서 매수
                if stock['allow_monitoring_buy'] == False:
                    # 목표가 왔다 -> 매수 감시 시작
                    if curr_price <= buy_target_price:
                        if self.check_buy_price(curr_price, lowest_price,buy_margin):
                            # 1차 매수 시 하한가 매수 금지 위해 전일 대비율(현재 등락율)이 MIN_PRICE_CHANGE_RATE_P % 이상에서 매수
                            if stock['buy_done'][0] == False and float(price_data['prdy_ctrt']) >= MIN_PRICE_CHANGE_RATE_P:
                                PRINT_INFO(f"[{stock['name']}] 매수 감시 시작, {curr_price}(현재가) <= {buy_target_price}(매수 목표가)")
                                stock['allow_monitoring_buy'] = True
                                stock['status'] = "매수 모니터링"
                                # 매수 모니터링 시작한 저가
                                stock['lowest_price_1'] = lowest_price                                    
                else:
                    # buy 모니터링 중
                    # "저가 < 매수 모니터링 시작한 저가 and 현재가 >= 저가 + BUY_MARGIN_P% and 현재가 < 저가 + (BUY_MARGIN_P+1)%" 에서 매수
                    # 즉, 두 번 째 최저가 + BUY_MARGIN_P 에서 매수                        
                    # "15:15" 까지 매수 안됐고 "현재가 <= 매수가"면 매수
                    if (lowest_price < stock['lowest_price_1']) \
                        and self.check_buy_price(curr_price, lowest_price,buy_margin) \
                        or (t_now >= T_BUY_AFTER and curr_price <= buy_target_price):
                        if stock['buy_order_done'] == False:
                            buy_target_qty = self.get_buy_target_qty(code)
                            if self.buy(code, curr_price, buy_target_qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                self.set_order_done(code, BUY_CODE)
            else:
                # 불타기는 2차 매수까지만 진행
                if BUY_SPLIT_COUNT > 1:
                    # 상승 추세 경우만 불타기
                    if stock['buy_done'][1] == False and stock['trend_60ma'] == TREND_UP:
                        stock['allow_monitoring_buy'] = True
                        stock['status'] = "매수 모니터링"
                        # 1차 매수 완료 경우 평단가 2~2.5% 사이에서 2차 매수(불타기)
                        if stock['buy_order_done'] == False:
                            if curr_price >= (stock['avg_buy_price'] * (1 + self.to_percent(NEXT_SELL_TARGET_MARGIN_P) - self.to_percent(0.5))) and curr_price <= (stock['avg_buy_price'] * (1 + self.to_percent(NEXT_SELL_TARGET_MARGIN_P))):
                                buy_target_qty = self.get_buy_target_qty(code)
                                if self.buy(code, curr_price, buy_target_qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                    self.set_order_done(code, BUY_CODE)      
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.SEND_MSG_ERR(msg)