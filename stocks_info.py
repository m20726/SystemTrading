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


##############################################################
#                           전략                             #
##############################################################
# 매수
#   트레일링스탑 매수
#   1차 매수 : envelope 지지
#   2차 매수 : 불타기, 1차 매수가에서 2% 이상 상승 시
# 매도
#   목표가에 반 매도
#   나머지는 익절가 이탈 시 전량 매도
#   목표가 올려가며 남은 물량의 1/2 매도
#      N차 매도가 : N-1차 매도가 * 1.03 (N>=2)
# 손절
#   last차 매수가 - 5% 종가 이탈
#   오늘 > 최근 매수일 + x days, 즉 x 일 동안 매수 없고
#   1차 매도가 안됐고 last차 매수까지 안된 경우 손절


##############################################################
#                       Config                               #
##############################################################
# 분할 매수 횟수
BUY_SPLIT_COUNT = 2

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

LOSS_CUT_P = 4                              # x% 이탈 시 손절

TAKE_PROFIT_P = 0.5                         # 익절가 %

BUY_MARGIN_P = 1                            # ex) 최저가 + x% 에서 매수
SELL_MARGIN_P = 2                           # ex) 목표가 + x% 에서 매도

INVEST_TYPE = "real_invest"                 # sim_invest : 모의 투자, real_invest : 실전 투자
# INVEST_TYPE = "sim_invest"

if INVEST_TYPE == "real_invest":
    MAX_MY_STOCK_COUNT = 7
    INVEST_MONEY_PER_STOCK = 500000         # 종목 당 투자 금액(원)
else:
    MAX_MY_STOCK_COUNT = 10                 # MAX 보유 주식 수
    INVEST_MONEY_PER_STOCK = 2000000        # 종목 당 투자 금액(원)

# "현재가 - 매수가 GAP" 이 X% 미만 경우만 매수 가능 종목으로 처리
# GAP 이 클수록 종목이 많아 실시간 처리가 느려진다
BUYABLE_GAP = 8
BUYABLE_COUNT = 30                          # 상위 몇개 종목까지 매수 가능 종목으로 유지

# 빠른 익절 전략
# 1차 매도 후 나머지 물량은 익절선을 높여 빠르게 익절한다
TAKE_PROFIT_STRATEGY_FAST = 0
# 느린 익절(수익 길게) 전략
# 1차 매도 후 나머지 물량은 익절선을 낮추어 길게 간다
TAKE_PROFIT_STRATEGY_SLOW = 1

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

API_DELAY_S = 0.07                          # 초당 API 20회 제한

# 체결 미체결 구분 코드
TRADE_ANY_CODE = "00"           # 체결 미체결 전체
TRADE_DONE_CODE = "01"          # 체결
TRADE_NOT_DONE_CODE = "02"      # 미체결

# 추세선
TREND_DOWN = 0      # 하락
TREND_SIDE = 1      # 보합
TREND_UP = 2        # 상승

# 이평선 배열
MA_STATUS_NEGATIVE = 0      # 역배열
MA_STATUS_SOSO = 1          # 정배열도 역배열도 아님
MA_STATUS_POSITIVE = 2      # 정배열

# sort by
SORT_BY_NAME = 0
SORT_BY_UNDER_VALUE = 1

LOSS_CUT_MARKET_OPEN = 0        # 장중 손절
LOSS_CUT_MARKET_CLOSE = 1       # 종가 손절
##############################################################

class Trade_strategy:
    def __init__(self) -> None:
        self.invest_risk = INVEST_RISK_LOW                      # 투자 전략, high : 공격적, middle : 중도적, low : 보수적
        self.under_value = 0                                    # 저평가가 이 값 미만은 매수 금지
        self.gap_max_sell_target_price_p = 0                    # 목표가GAP 이 이 값 미만은 매수 금지
        self.sum_under_value_sell_target_gap = 0                # 저평가 + 목표가GAP 이 이 값 미만은 매수 금지
        self.max_per = 80                                       # PER가 이 값 이상이면 매수 금지
        self.buyable_market_cap = 20000                         # 시총 X 미만 매수 금지(억)
        self.buy_split_strategy = BUY_SPLIT_STRATEGY_UP         # 2차 분할 매수 전략(물타기, 불타기)
        self.take_profit_strategy = TAKE_PROFIT_STRATEGY_SLOW   # 익절 전략
        self.buy_trailing_stop = True                           # 매수 시 트레일링 스탑으로 할지
        self.sell_trailing_stop = False                         # 매도 시 트레일링 스탑으로 할지
        self.trend = TREND_UP                                   # 추세선이 이거 이상이여야 매수
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
        self.buy_done_event = threading.Event()
        # 매도 완료 시 handle_sell_stock 은 set_sell_done 완료까지 대기해야
        self.sell_done_event = threading.Event()
        # self.my_stocks 를 for loop 으로 접근하는 동안 main thread 에서 update_my_stocks() 등으로 self.my_stocks 를 변경하면 오류 발생한다.
        # 따라서 for loop 끝날 때까지 self.my_stocks 를 변경하지 못하도록 처리        
        self.my_stocks_event = threading.Event()
        self.buyable_stocks_event = threading.Event()
        

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
            self.init_trade_strategy()                # 매매 전략 세팅
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 전략 출력
    ##############################################################
    def print_strategy(self):
        PRINT_DEBUG('===============================')
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
            PRINT_DEBUG(f'2차 매수 물타기')
        elif self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_UP:
            PRINT_DEBUG(f'2차 매수 불타기')

        trend_msg = dict()
        trend_msg[TREND_DOWN] = "하락 추세"
        trend_msg[TREND_SIDE] = "보합 추세"
        trend_msg[TREND_UP] = "상승 추세"
        PRINT_DEBUG(f'60일선 {trend_msg[self.trade_strategy.trend]} 이상 매수')

        if BUY_QTY_1 == True:
            PRINT_DEBUG('1주만 매수')
        PRINT_DEBUG('===============================')

    ##############################################################
    # Print and send discode
    ##############################################################
    def send_msg(self, msg, send_discode:bool = False, err:bool = False):
        result = True
        ex_msg = ""
        try:
            REQUESTS_POST_MAX_SIZE = 2000

            msg = str(msg)

            # 메세지 실행 func, line 출력
            f = inspect.currentframe()
            if send_discode == True and err == True:
                i = inspect.getframeinfo(f.f_back.f_back)
            else:
                i = inspect.getframeinfo(f.f_back)
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

            if err == True:
                PRINT_ERR(f"{msg}")
            elif send_discode == True:
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

    def send_msg_err(self, msg):
        self.send_msg(msg, True, True)
        
    ##############################################################
    # 네이버 증권 기업실적분석 정보 얻기
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
                self.send_msg_err(msg)

    ##############################################################
    # 네이버 증권 기업실적분석 년도 가져오기
    #   2024년이지만 2024.02 현재 2024.12(E) 데이터 없는 경우 많다. 2023.12(E) 까지만 있다
    #   따라서 최근 data, index 3 의 데이터를 기준으로 한다
    #   2023년 기준 2023.12(E)
    #   2023년 기준 2022.12, 작년 데이터 얻기
    #   2023년 기준 2021.12, 재작년 데이터 얻기                
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
                self.send_msg_err(msg)

    ##############################################################
    # requests 성공 여부
    ##############################################################
    def is_request_ok(self, res):
        if res.json()['rt_cd'] == '0':
            return True
        else:
            return False

    ##############################################################
    # percent 값으로 변경
    #   ex) to_per(10) return 0.1
    ##############################################################
    def to_percent(self, percent):
        return percent / 100

    ##############################################################
    # 주식 호가 단위로 가격 변경
    # 5,000원 미만                      5원
    # 5,000원 이상 10,000원 미만       10원
    # 10,000원 이상 50,000원 미만	   50원
    # 50,000원 이상 100,000원 미만	  100원
    # 100,000원 이상 500,000원 미만   500원
    # 500,000원 이상                 1000원
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
        return int(int((price / unit) + 0.5) * unit)      # 반올림

    ##############################################################
    # self.invest_type 에 맞는 config 설정
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
                self.send_msg_err(msg)        

    ##############################################################
    # stocks 에서 code 에 해당하는 stock 리턴
    ##############################################################
    def get_stock(self, code: str):
        try:
            return self.stocks[code]
        except KeyError:
            self.send_msg_err(f'KeyError : {code} is not found')
            return None

    ##############################################################
    # stocks file 에서 stocks 정보 가져온다
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
                self.send_msg_err(msg)

    ##############################################################
    # stocks 정보를 stocks file 에 저장
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
                self.send_msg_err(msg)

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
            if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:
                # 물타기
                buy_margin = 0.9
            else:
                # 불타기
                buy_margin = 1.02

            # 1차 매수 안된 경우 envelope 기반으로 매수가 세팅
            if self.stocks[code]['buy_done'][0] == False:
                envelope_p = self.to_percent(self.stocks[code]['envelope_p'])
                envelope_support_line = self.stocks[code]['yesterday_20ma'] * (1 - envelope_p)

                # 1차 매수가는 단기간에 급락한 가격 이하여야한다.
                self.stocks[code]['buy_price'][0] = min(int(envelope_support_line * MARGIN_20MA), self.get_plunge_price(code))

                # 1 ~ (BUY_SPLIT_COUNT-1)
                for i in range(1, BUY_SPLIT_COUNT):
                    #   2차 매수 : 1차 매수가 - 10%
                    #   3차 매수 : 2차 매수가 - 10%
                    self.stocks[code]['buy_price'][i] = int(self.stocks[code]['buy_price'][i-1] * buy_margin)
            else:
                # N차 매수 된 경우 실제 매수가 기반으로 세팅
                # done_nth 차 매수 bought_price 가격에 완료
                # 실제 bought_price 를 기반으로 업데이트
                if done_nth > 0 and bought_price > 0:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] {done_nth}차 매수 {bought_price}원 완료, 매수가 업데이트")
                    self.stocks[code]['buy_price'][done_nth-1] = bought_price
                    for i in range(done_nth, BUY_SPLIT_COUNT):
                        self.stocks[code]['buy_price'][i] = int(self.stocks[code]['buy_price'][i-1] * buy_margin)
                        PRINT_INFO(f"[{self.stocks[code]['name']}] {i+1}차 매수가 {self.stocks[code]['buy_price'][i]}원")
                        
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매수 수량 세팅
    ##############################################################
    def set_buy_qty(self, code):
        result = True
        msg = ""
        try:
            for i in range(BUY_SPLIT_COUNT):
                if self.stocks[code]['buy_price'][i] > 0:
                    # 매수 완료 차수는 업데이트 하지 않는다
                    if self.stocks[code]['buy_done'][i] == True:
                        continue

                    if BUY_QTY_1 == True:
                        # 매수량은 항상 1주만
                        self.stocks[code]['buy_qty'][i] = 1
                    else:
                        # 최소 1주 매수
                        qty = max(1, int(self.buy_invest_money[i] / self.stocks[code]['buy_price'][i]))
                        self.stocks[code]['buy_qty'][i] = qty
                else:
                    self.stocks[code]['buy_qty'][i] = 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

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
            PRINT_INFO(f"[{self.stocks[code]['name']}] 매수가 {bought_price}원")
            if bought_price <= 0:
                self.send_msg_err(f"[{self.stocks[code]['name']}] 매수가 오류 {bought_price}원")

            # 매수 완료됐으니 평단가, 목표가 업데이트
            self.update_my_stocks()
            
            self.stocks[code]['buy_order_done'] = False
            
            tot_buy_qty = 0
            for i in range(BUY_SPLIT_COUNT):
                tot_buy_qty += self.stocks[code]['buy_qty'][i]
                # n차 매수 완료 조건 : 보유 수량 >= 1 ~ n차 매수량 경우 
                if self.stocks[code]['buy_done'][i] == False:
                    if self.stocks[code]['stockholdings'] >= tot_buy_qty:
                        self.stocks[code]['buy_done'][i] = True
                        # 매수 완료 후 실제 매수가로 N차 매수 업데이트
                        self.set_buy_price(code, i + 1, bought_price)
                        # 실제 매수가로 qty 업데이트
                        self.set_buy_qty(code)
                        break

            # N차 매수에 따라 목표가 % 변경은 물타기 경우만
            if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:
                # N차 매수에 따라 목표가 % 변경
                #   ex)
                #   1차 매수까지 경우 : 평단가 * 5%
                #   2차 매수까지 경우 : 평단가 * 4%
                for i in range(1, BUY_SPLIT_COUNT): # 1 ~ (BUY_SPLIT_COUNT-1)
                    if self.stocks[code]['buy_done'][BUY_SPLIT_COUNT-i] == True:
                        self.stocks[code]['sell_target_p'] -= -1
                        break
                # 최소 목표가
                if self.stocks[code]['sell_target_p'] < 4:
                    self.stocks[code]['sell_target_p'] = 4

            # 다음 매수 조건 체크위해 allow_monitoring_buy 초기화
            self.stocks[code]['allow_monitoring_buy'] = False
            self.my_cash = self.get_my_cash()
            self.stocks[code]['loss_cut_done'] = False
            # 매수일 업데이트            
            self.stocks[code]['recent_buy_date'] = date.today().strftime('%Y-%m-%d')         
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg) 

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
            PRINT_INFO(f"[{self.stocks[code]['name']}] 매도가 {sold_price}원")
            if sold_price <= 0:
                self.send_msg_err(f"[{self.stocks[code]['name']}] 매도가 오류 {sold_price}원")

            self.stocks[code]['sell_order_done'] = False
            if self.is_my_stock(code) == True:
                if self.stocks[code]['sell_1_done'] == False:
                    # 1차 매도 완료 상태
                    self.stocks[code]['sell_1_done'] = True
                self.stocks[code]['recent_sold_price'] = sold_price
                self.update_my_stocks()
                self.send_msg(f"[{self.stocks[code]['name']}] 일부 매도", True)
                PRINT_INFO(f"[{self.stocks[code]['name']}] 다음 목표가 {self.stocks[code]['sell_target_price']}원")
            else:
                # 전량 매도 상태는 보유 종목에 없는 상태
                if self.is_my_stock(code) == False:
                    self.stocks[code]['sell_done'] = True
                    # 매도 완료 후 종가 > 20ma 체크위해 false 처리
                    self.stocks[code]['end_price_higher_than_20ma_after_sold'] = False
                    self.update_my_stocks()
                    if self.stocks[code]['loss_cut_order'] == True:
                        self.set_loss_cut_done(code)
                    else:
                        self.clear_buy_sell_info(code)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg) 

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
            self.stocks[code]['loss_cut_done'] = True
            self.stocks[code]['loss_cut_order'] = False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg) 

    ##############################################################
    # 매도 완료등으로 매수/매도 관려 정보 초기화 시 호출
    ##############################################################
    def clear_buy_sell_info(self, code):
        result = True
        msg = ""
        try:            
            self.stocks[code]['yesterday_20ma'] = 0

            self.stocks[code]['buy_price'] = list()
            self.stocks[code]['buy_qty'] = list()
            self.stocks[code]['buy_done'] = list()
            for i in range(BUY_SPLIT_COUNT):
                self.stocks[code]['buy_price'].append(0)
                self.stocks[code]['buy_qty'].append(0)
                self.stocks[code]['buy_done'].append(False)

            self.stocks[code]['sell_target_p'] = 0
            self.stocks[code]['sell_target_price'] = 0
            self.stocks[code]['stockholdings'] = 0
            self.stocks[code]['allow_monitoring_buy'] = False
            self.stocks[code]['allow_monitoring_sell'] = False
            self.stocks[code]['highest_price_ever'] = 0
            self.stocks[code]['sell_1_done'] = False
            # 매도 완료 후 매도 체결 조회 할 수 있기 때문에 초기화하지 않는다
            # self.stocks[code]['avg_buy_price'] = 0
            self.stocks[code]['loss_cut_price'] = 0
            self.stocks[code]['loss_cut_done'] = False
            self.stocks[code]['recent_buy_date'] = None
            self.stocks[code]['ma_trend'] = TREND_DOWN
            self.stocks[code]['recent_sold_price'] = 0
            self.stocks[code]['first_sell_target_price'] = 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 목표가 = 평단가 * (1 + 목표%)
    ##############################################################
    def get_sell_target_price(self, code):
        result = True
        msg = ""
        price = 0
        try:
            if self.stocks[code]['sell_1_done'] == False:
                # 1차 매도 안된 경우
                sell_target_p = self.to_percent(self.stocks[code]['sell_target_p'])
                if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:
                    # 물타기 경우
                    price = self.stocks[code]['avg_buy_price'] * (1 + sell_target_p)
                else:
                    # 불타기 경우
                    # 1차 매수 시 목표가 유지
                    # 2,3차 매수 했다고 목표가 업데이트하지 않는다.
                    if self.stocks[code]['sell_target_price'] == 0 or self.stocks[code]['buy_done'][0] == False:
                        price = self.stocks[code]['avg_buy_price'] * (1 + sell_target_p)
                    else:
                        price = self.stocks[code]['sell_target_price']
            else:
                # 1차 매도 완료 경우
                # N차 매도가 : N-1차 매도가 * x (N>=2)
                price = self.stocks[code]['recent_sold_price'] * 1.025
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            # 주식 호가 단위로 가격 변경
            return self.get_stock_asking_price(int(price))

    ##############################################################
    # 현재가 리턴
    #   return : 성공 시 현재가, 실패 시 0 리턴
    ##############################################################
    def get_curr_price(self, code):
        return self.get_price(code, 'stck_prpr')

    ##############################################################
    # 저가 리턴
    #   return : 성공 시 저가, 실패 시 0 리턴
    ##############################################################
    def get_lowest_price(self, code):
        return self.get_price(code, 'stck_lwpr')

    ##############################################################
    # 고가 리턴
    #   return : 성공 시 고가, 실패 시 0 리턴
    ##############################################################
    def get_highest_price(self, code):
        return self.get_price(code, 'stck_hgpr')

    ##############################################################
    # 종가 리턴
    #   return : 성공 시 종가, 실패 시 0 리턴
    ##############################################################
    def get_close_price(self, code):
        return self.get_price(code, 'stck_clpr')

    ##############################################################
    # 시가총액(market capitalization) 리턴
    #   return : 성공 시 시가총액, 실패 시 0 리턴
    ##############################################################
    def get_market_cap(self, code):
        return self.get_price(code, 'hts_avls')
    
    ##############################################################
    # 주식현재가 시세 리턴
    #   return : 성공 시 요청한 시세, 실패 시 0 리턴
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
            time.sleep(API_DELAY_S * 2) # to fix max retries exceeded
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                price = int(float(res.json()['output'][type]))
            else:
                raise Exception(f"[get_price failed]]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                msg = self.stocks[code]['name'] + " " + msg
                self.send_msg_err(msg)
            return price

    ##############################################################
    # 매수가 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수가 리턴
    #   2차 매수까지 완료면 0 리턴
    ##############################################################
    def get_buy_target_price(self, code):
        result = True
        msg = ""
        try:
            # last차까지 매수 완료 경우
            buy_target_price = 0

            for i in range(BUY_SPLIT_COUNT):
                if self.stocks[code]['buy_done'][i] == False:
                    buy_target_price = self.stocks[code]['buy_price'][i]
                    break

            return int(buy_target_price)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매수 수량 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수 수량 리턴
    #   2차 매수까지 완료면 0 리턴
    ##############################################################
    def get_buy_target_qty(self, code):
        result = True
        msg = ""
        try:
            # last차까지 매수 완료 경우
            buy_target_qty = 0

            for i in range(BUY_SPLIT_COUNT):
                if self.stocks[code]['buy_done'][i] == False:
                    buy_target_qty = self.stocks[code]['buy_qty'][i]
                    break

            return int(buy_target_qty)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 네이버 증권에서 특정 값 얻기
    #   ex) https://finance.naver.com/item/main.naver?code=005930
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
                self.send_msg_err(msg)

    ##############################################################
    # 주식 투자 정보 업데이트(시가 총액, 상장 주식 수, 저평가, BPS, PER, EPS)
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
            time.sleep(API_DELAY_S)
            res = requests.get(URL, headers=headers, params=params)
            total_stock_count = 0
            if self.is_request_ok(res) == True:
                # 현재 PER
                self.stocks[code]['PER'] = float(res.json()['output']['per'].replace(",",""))
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
            self.stocks[code]['PER_E'] = float(annual_finance[recent_year_column_text]['PER(배)'].replace(",",""))
            
            check_year_column_text = recent_year_column_text

            if self.stocks[code]['PER_E'] == 0:
                # _E 자료 없는 경우 작년 데이터로 대체
                check_year_column_text = last_year_column_text
                self.stocks[code]['PER_E'] = float(annual_finance[check_year_column_text]['PER(배)'].replace(",",""))

            self.stocks[code]['EPS_E'] = int(annual_finance[check_year_column_text]['EPS(원)'].replace(",",""))
            self.stocks[code]['BPS_E'] = int(annual_finance[check_year_column_text]['BPS(원)'].replace(",",""))
            self.stocks[code]['ROE_E'] = float(annual_finance[check_year_column_text]['ROE(지배주주)'].replace(",",""))

            self.stocks[code]['industry_PER'] = float(self.crawl_naver_finance_by_selector(code, "#tab_con1 > div:nth-child(6) > table > tbody > tr.strong > td > em").replace(",",""))
            self.stocks[code]['operating_profit_margin_p'] = float(annual_finance[check_year_column_text]['영업이익률'])
            self.stocks[code]['sales_income'] = int(annual_finance[check_year_column_text]['매출액'].replace(",",""))                   # 올해 예상 매출액, 억원
            self.stocks[code]['last_year_sales_income'] = int(annual_finance[last_year_column_text]['매출액'].replace(",",""))         # 작년 매출액, 억원
            self.stocks[code]['the_year_before_last_sales_income'] = int(annual_finance[the_year_before_last_column_text]['매출액'].replace(",",""))       # 재작년 매출액, 억원
            self.stocks[code]['curr_profit'] = int(annual_finance[check_year_column_text]['당기순이익'].replace(",",""))
            # 목표 주가 = 미래 당기순이익(원) * PER_E / 상장주식수
            if total_stock_count > 0:
                self.stocks[code]['max_target_price'] = int((self.stocks[code]['curr_profit'] * 100000000) * self.stocks[code]['PER_E'] / total_stock_count)
            # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가
            # + : 저평가
            # - : 고평가
            if self.stocks[code]['sell_target_price'] > 0:
                self.stocks[code]['gap_max_sell_target_price_p'] = int(100 * (self.stocks[code]['max_target_price'] - self.stocks[code]['sell_target_price']) / self.stocks[code]['sell_target_price'])
            self.set_stock_undervalue(code)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return result

    ##############################################################
    # 저평가 계산
    ##############################################################
    def set_stock_undervalue(self, code):
        result = True
        msg = ""
        try:            
            self.stocks[code]['undervalue'] = 0
            curr_price = self.get_curr_price(code)
            
            if curr_price > 0:
                # BPS_E > 현재가
                if self.stocks[code]['BPS_E'] > curr_price:
                    self.stocks[code]['undervalue'] += 2
                elif self.stocks[code]['BPS_E'] * 1.3 < curr_price:
                    self.stocks[code]['undervalue'] -= 2

                # EPS_E * 10 > 현재가
                if self.stocks[code]['EPS_E'] * 10 > curr_price:
                    self.stocks[code]['undervalue'] += 2
                elif self.stocks[code]['EPS_E'] * 3 < curr_price:
                    self.stocks[code]['undervalue'] -= 2
                elif self.stocks[code]['EPS_E'] < 0:
                    self.stocks[code]['undervalue'] -= 10

                # ROE_E
                if self.stocks[code]['ROE_E'] < 0 and self.stocks[code]['EPS_E'] < 0:
                    self.stocks[code]['undervalue'] -= 4
                else:
                    if self.stocks[code]['ROE_E'] * self.stocks[code]['EPS_E'] > curr_price:
                        self.stocks[code]['undervalue'] += 2
                    elif self.stocks[code]['ROE_E'] * self.stocks[code]['EPS_E'] * 1.3 < curr_price:
                        self.stocks[code]['undervalue'] -= 2
                    if self.stocks[code]['ROE_E'] > 20:
                        self.stocks[code]['undervalue'] += (self.stocks[code]['ROE_E'] / 10)

            # PER
            if self.stocks[code]['PER'] > 0 and self.stocks[code]['PER'] <= 10:
                if self.stocks[code]['industry_PER'] > 0:
                    self.stocks[code]['undervalue'] += int((1 - self.stocks[code]['PER'] / self.stocks[code]['industry_PER']) * 4)
                else:
                    self.stocks[code]['undervalue'] += 2
            elif self.stocks[code]['PER'] >= 20:
                self.stocks[code]['undervalue'] -= 2
            elif self.stocks[code]['PER'] < 0:
                self.stocks[code]['undervalue'] -= 10

            # 영업이익률
            if self.stocks[code]['operating_profit_margin_p'] >= 10:
                self.stocks[code]['undervalue'] += 1
            elif self.stocks[code]['operating_profit_margin_p'] < 0:
                self.stocks[code]['undervalue'] -= 1

            # 매출액
            if self.stocks[code]['last_year_sales_income'] > 0 and self.stocks[code]['the_year_before_last_sales_income'] > 0:
                if self.stocks[code]['sales_income'] / self.stocks[code]['last_year_sales_income'] >= 1.1:
                    if self.stocks[code]['last_year_sales_income'] / self.stocks[code]['the_year_before_last_sales_income'] >= 1.1:
                        self.stocks[code]['undervalue'] += 2
                    else:
                        pass
                elif self.stocks[code]['sales_income'] / self.stocks[code]['last_year_sales_income'] <= 0.9:
                    if self.stocks[code]['last_year_sales_income'] / self.stocks[code]['the_year_before_last_sales_income'] <= 0.9:
                        self.stocks[code]['undervalue'] -= 2
                    else:
                        pass

            self.stocks[code]['undervalue'] = int(self.stocks[code]['undervalue'])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매수/매도 위한 주식 정보 업데이트
    #   1,2차 매수가, 20일선
    ##############################################################
    def update_stocks_trade_info(self):
        result = True
        msg = ""
        try:            
            t_now = datetime.datetime.now()
            t_exit = t_now.replace(hour=15, minute=30, second=0, microsecond=0)
            # 15:30 장마감 후는 금일기준으로 20일선 구한다
            if t_exit < t_now:
                past_day = 0        # 장마감 후는 금일 기준
            else:
                past_day = 1        # 어제 기준

            for code in self.stocks.keys():
                # 순서 변경 금지
                # ex) 목표가를 구하기 위해선 평단가가 먼저 있어야한다
                # 시가 총액
                self.stocks[code]['market_cap'] = self.get_market_cap(code)
                
                # yesterday 20일선
                self.stocks[code]['yesterday_20ma'] = self.get_ma(code, 20, past_day)

                # 1차 매수 안된 경우만 업데이트
                if self.stocks[code]['buy_done'][0] == False:
                    self.stocks[code]['sell_target_p'] = 5

                    self.stocks[code]['envelope_p'] = self.get_envelope_p(code)

                    # 매수가 세팅
                    self.set_buy_price(code)
                    # 매수 수량 세팅
                    self.set_buy_qty(code)

                # 손절가
                self.stocks[code]['loss_cut_price'] = self.get_loss_cut_price(code)
                # 어제 종가
                self.stocks[code]['yesterday_end_price'] = self.get_end_price(code, past_day)

                # 매도 완료 후 "어제 종가 > 어제 20ma" 여야 재매수 가능
                if self.stocks[code]['sell_done'] == True:
                    # 어제 종가 > 어제 20ma
                    if self.stocks[code]['yesterday_end_price'] > self.stocks[code]['yesterday_20ma']:
                        # 재매수 가능
                        self.stocks[code]['end_price_higher_than_20ma_after_sold'] = True
                        self.stocks[code]['sell_done'] = False

                # 보유 주식 아닌 경우에 업데이트
                if self.is_my_stock(code) == False:
                    # 평단가 = 1차 매수가
                    self.stocks[code]['avg_buy_price'] = self.stocks[code]['buy_price'][0]
                    # 목표가
                    self.stocks[code]['sell_target_price'] = self.get_sell_target_price(code)

                # 주식 투자 정보 업데이트(상장 주식 수, 저평가, BPS, PER, EPS)
                self.stocks[code]['stock_invest_info_valid'] = self.update_stock_invest_info(code)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 보유 주식 정보 업데이트
    #   보유 주식은 stockholdings > 0
    #   return : 성공 시 True , 실패 시 False    
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
            time.sleep(API_DELAY_S)
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                stocks = res.json()['output1']
                self.my_stocks.clear()
                for stock in stocks:
                    if int(stock['hldg_qty']) > 0:
                        code = stock['pdno']
                        if code in self.stocks.keys():
                            # 보유 수량
                            self.stocks[code]['stockholdings'] = int(stock['hldg_qty'])
                            # 평단가
                            self.stocks[code]['avg_buy_price'] = int(float(stock['pchs_avg_pric']))    # 계좌내 실제 평단가
                            # 목표가
                            self.stocks[code]['sell_target_price'] = self.get_sell_target_price(code)
                            # 1차 목표가 유지
                            self.stocks[code]['first_sell_target_price'] = self.get_first_sell_target_price(code)
                            # self.my_stocks 업데이트
                            temp_stock = copy.deepcopy({code: self.stocks[code]})
                            self.my_stocks[code] = temp_stock[code]
                        else:
                            # 보유는 하지만 DB 에 없는 종목 제외 ex) 공모주
                            # self.send_msg(f"DB 에 없는 종목({stock['prdt_name']})은 업데이트 skip")
                            pass
            else:
                raise Exception(f"[계좌 조회 실패]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            self.my_stocks_event.set()
            return result

    ##############################################################
    # 매수가능 주식 수 리턴
    #   보유 현금 / 종목당 매수 금액
    #   ex) 총 보유금액이 300만원이고 종목당 총 100만원 매수 시 총 2종목 매수
    ##############################################################
    def get_available_buy_stock_count(self):
        result = True
        msg = ""
        try:
            ret = 0
            if INVEST_MONEY_PER_STOCK > 0:
                ret = int(self.my_cash / INVEST_MONEY_PER_STOCK)
            return ret
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 보유 종목인지 체크
    ##############################################################
    def is_my_stock(self, code):
        result = True
        msg = ""
        try:
            if code in self.my_stocks.keys():
                return True
            else:
                return False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매수 가능 종목인지 체크
    ##############################################################
    def is_buyable_stock(self, code):
        result = True
        msg = ""
        try:
            if code in self.buyable_stocks.keys():
                return True
            else:
                return False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매수 여부 판단
    ##############################################################
    def is_ok_to_buy(self, code, print_msg=False):
        result = True
        msg = ""
        try:
            #### 이미 내 주식이지만 체크할 조건
            # 오늘 주문 완료 시 금지
            if self.already_ordered(code, BUY_CODE) == True:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 오늘 주문 완료")
                return False

            # last차 매수까지 완료 시 금지
            if self.stocks[code]['buy_done'][BUY_SPLIT_COUNT-1] == True:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, last차 매수까지 완료")                
                return False
            ####
            
            # 이미 내 주식은 매수
            # ex) 2차, 3차 매수
            if self.is_my_stock(code) == True:
                return True
            
            # 매수 가능 종목은 매수
            if self.is_buyable_stock(code) == True:
                return True

            # 주식 투자 정보가 valid 하지 않으면 매수 금지
            if self.stocks[code]['stock_invest_info_valid'] == False:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 주식 투자 정보가 not valid")                   
                return False

            # 저평가 조건(X미만 매수 금지)
            if self.stocks[code]['undervalue'] < self.trade_strategy.under_value:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 저평가 조건")                  
                return False
            
            # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가 < X% 미만 매수 금지
            if self.stocks[code]['gap_max_sell_target_price_p'] < self.trade_strategy.gap_max_sell_target_price_p:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 목표 주가 GAP")                 
                return False

            # 저평가 + 목표가GAP < X 미만 매수 금지
            if (self.stocks[code]['undervalue'] + self.stocks[code]['gap_max_sell_target_price_p']) < self.trade_strategy.sum_under_value_sell_target_gap:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 저평가 + 목표가GAP < {self.trade_strategy.sum_under_value_sell_target_gap}")
                return False
            
            # PER 매수 금지
            if self.stocks[code]['PER'] < 0 or self.stocks[code]['PER'] >= self.trade_strategy.max_per or self.stocks[code]['PER_E'] < 0:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, PER")
                return False
            
            # EPS_E 매수 금지
            if self.stocks[code]['EPS_E'] < 0:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, EPS_E")                
                return False

            # 보유현금에 맞게 종목개수 매수
            #   ex) 총 보유금액이 300만원이고 종목당 총 100만원 매수 시 총 2종목 매수
            if (self.get_available_buy_stock_count() == 0 or len(self.my_stocks) >= MAX_MY_STOCK_COUNT) and self.is_my_stock(code) == False:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 보유현금({self.my_cash})에 맞게 종목개수 매수")                   
                return False
            
            # 매도 후 종가 > 20ma 체크
            if self.stocks[code]['sell_done'] == True:
                # 어제 종가 <= 어제 20ma 상태면 매수 금지
                if self.stocks[code]['end_price_higher_than_20ma_after_sold'] == False:
                    if print_msg:
                        PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 매도 후 종가 > 20ma 체크")                       
                    return False
            else:
                pass
            
            # 시총 체크
            if self.stocks[code]['market_cap'] < self.trade_strategy.buyable_market_cap:
                if print_msg:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 시총 체크")                 
                return False

            # 이평선 정배열 체크는 공격적 전략이 아닐 때
            if self.trade_strategy.invest_risk != INVEST_RISK_HIGH:
                if self.get_multi_ma_status(code, [60,90]) != MA_STATUS_POSITIVE:
                    if print_msg:
                        PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 이평선 정배열 아님")
                    return False
            
            # 하락 추세는 매수 금지
            if self.stocks[code]['ma_trend'] < self.trade_strategy.trend:
                PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, 하락 추세")
                return False

            return True
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 금일(index 0) 기준 100건의 종가 리스트 리턴
    # param :
    #   code            종목 코드
    #   period          D : 일, W : 주, M : 월, Y : 년
    ##############################################################
    def get_end_price_list(self, code: str, period="D"):
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
            time.sleep(API_DELAY_S)
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == False:
                raise Exception(f"[get_ma_trend failed]]{str(res.json())}")
            
            for i in range(len(res.json()['output2'])):
                end_price_list.append(int(res.json()['output2'][i]['stck_clpr']))   # 종가

        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
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
            end_price_list = self.get_end_price_list(code, period)

            # x일 이평선 구하기 위해 x일간의 종가 구한다
            days_last = past_day + ma
            if days_last >= len(end_price_list):
                raise Exception(f"Can't get more than {len(end_price_list)} days data, days_last:{days_last}, past_day:{past_day}, ma:{ma}") 
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
                self.send_msg_err(msg)
            return int(value_ma)

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
        try:
            end_price = 0

            if past_day > 99:
                PRINT_INFO(f'can read over 99 data. make past_day to 99')
                past_day = 99
                
            end_price_list = self.get_end_price_list(code)
            end_price = int(end_price_list[past_day])
            return end_price   # 종가
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
                return end_price

    ##############################################################
    # 토큰 발급
    ##############################################################
    def get_access_token(self):
        result = True
        msg = ""
        try:            
            headers = {"content-type": "application/json"}
            body = {"grant_type": "client_credentials",
                    "appkey": self.config['APP_KEY'],
                    "appsecret": self.config['APP_SECRET']}
            PATH = "oauth2/tokenP"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            time.sleep(API_DELAY_S)
            res = requests.post(URL, headers=headers, data=json.dumps(body))
            return res.json()["access_token"]
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 암호화
    ##############################################################
    def hashkey(self, datas):
        result = True
        msg = ""
        try:            
            PATH = "uapi/hashkey"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {
                'content-Type': 'application/json',
                'appKey': self.config['APP_KEY'],
                'appSecret': self.config['APP_SECRET'],
            }
            time.sleep(API_DELAY_S)
            res = requests.post(URL, headers=headers, data=json.dumps(datas))
            hashkey = res.json()["HASH"]
            return hashkey
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 주식 잔고조회
    ##############################################################
    def get_stock_balance(self, send_discode:bool = False):
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
            time.sleep(API_DELAY_S)
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == False:
                raise Exception(f"[get_stock_balance failed]]{str(res.json())}")
            stock_list = res.json()['output1']
            evaluation = res.json()['output2']
            data = {'종목명':[], '수익률(%)':[], '수량':[], '평가금액':[], '손익금액':[], '평단가':[], '현재가':[], '목표가':[], '손절가':[]}
            self.send_msg(f"==========주식 보유잔고==========", send_discode)
            for stock in stock_list:
                if int(stock['hldg_qty']) > 0:
                    data['종목명'].append(stock['prdt_name'])
                    data['수익률(%)'].append(float(stock['evlu_pfls_rt'].replace(",","")))
                    data['수량'].append(stock['hldg_qty'])
                    data['평가금액'].append(int(stock['evlu_amt'].replace(",","")))
                    data['손익금액'].append(stock['evlu_pfls_amt'])
                    data['평단가'].append(int(float(stock['pchs_avg_pric'].replace(",",""))))
                    data['현재가'].append(int(stock['prpr'].replace(",","")))                    
                    code = stock['pdno']
                    if code in self.stocks.keys():
                        data['목표가'].append(int(self.stocks[code]['sell_target_price']))
                        data['손절가'].append(int(self.get_loss_cut_price(code)))
                    else:
                        # 보유는 하지만 DB 에 없는 종목 표시
                        data['목표가'].append(0)
                        data['손절가'].append(0)

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'r'  # 우측 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            self.send_msg(f"{table}", send_discode)
            self.send_msg(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원", send_discode)
            self.send_msg(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원", send_discode)
            self.send_msg(f"총 평가 금액: {evaluation[0]['tot_evlu_amt']}원", send_discode)            
            return stock_list
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
                return []

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
            time.sleep(API_DELAY_S)
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == False:
                raise Exception(f"[get_my_cash failed]]{str(res.json())}")
            cash = res.json()['output']['ord_psbl_cash']
            # self.send_msg(f"주문 가능 현금 잔고: {cash}원")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return int(cash)

    ##############################################################
    # 매수
    #   return : 성공 시 True , 실패 시 False
    #   param :
    #       code            종목 코드
    #       price           매수 가격
    #       qty             매수 수량
    #       order_type      매수 타입(지정가, 최유리지정가,...)
    ##############################################################
    def buy(self, code: str, price: str, qty: str, order_type:str = ORDER_TYPE_LIMIT_ORDER):
        result = True
        msg = ""
        try:
            if self.is_ok_to_buy(code) == False:
                return False
            
            # 종가 매매 처리
            t_now = datetime.datetime.now()
            # 장 종료 15:30
            t_market_end = t_now.replace(hour=15, minute=30, second=0, microsecond=0)
            if t_now >= t_market_end:
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
            time.sleep(API_DELAY_S)
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            if self.is_request_ok(res) == True:
                self.send_msg(f"[매수 주문 성공] [{self.stocks[code]['name']}] {price}원 {qty}주 {order_string}")
                return True
            else:
                self.send_msg_err(f"[매수 주문 실패] [{self.stocks[code]['name']}] {price}원 {qty}주 {order_string} {str(res.json())}")
            return False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매도
    #   return : 성공 시 True , 실패 시 False
    #   param :
    #       code            종목 코드
    #       price           매도 가격
    #       qty             매도 수량
    #       order_type      매도 타입(지정가, 최유리지정가,...)
    #       do_sell         조건 안따지고 매도 경우 True, 조건 따지면 False
    ##############################################################
    def sell(self, code: str, price: str, qty: str, order_type:str = ORDER_TYPE_LIMIT_ORDER, do_sell=False):
        result = True
        msg = ""
        try:
            # 종가 매매 처리
            t_now = datetime.datetime.now()
            # 장 종료 15:30
            t_market_end = t_now.replace(hour=15, minute=30, second=0, microsecond=0)
            if t_now >= t_market_end:
                order_type = ORDER_TYPE_AFTER_MARKET_ORDER

            # 지정가 이외의 주문은 가격을 0으로 해야 주문 실패하지 않는다.
            # 업체 : 장전 시간외, 장후 시간외, 시장가 등 모든 주문구분의 경우 1주당 가격을 공란으로 비우지 않고
            # "0"으로 입력 권고드리고 있습니다.
            if order_type != ORDER_TYPE_LIMIT_ORDER:
                price = 0

            if do_sell == False:
                # 당일 매도 주문 완료 후 체결 안됐는데 또 매도 금지
                if self.already_ordered(code, SELL_CODE) == True:
                    PRINT_INFO(f"[{self.stocks[code]['name']}] 당일 매도 주문 완료 후 체결 안됐는데 또 매도 금지")
                    return False
                
                # 시장가 주문은 조건 안따진다
                if order_type != ORDER_TYPE_MARKET_ORDER:
                    if self.stocks[code]['allow_monitoring_sell'] == False:
                        PRINT_INFO(f"[{self.stocks[code]['name']}]  allow_monitoring_sell == False sell 금지")
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
            time.sleep(API_DELAY_S)
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            if self.is_request_ok(res) == True:
                self.send_msg(f"[매도 주문 성공] [{self.stocks[code]['name']}] {price}원 {qty}주 {order_string}")
                return True
            else:
                self.send_msg_err(f"[매도 주문 실패] [{self.stocks[code]['name']}] {price}원 {qty}주 {order_string} {str(res.json())}")
            return False
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
                return False

    ##############################################################
    # 주문 성공 후 처리
    #   return : 성공 시 True , 실패 시 False
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
            self.show_order_list()
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매수 처리
    ##############################################################
    def handle_buy_stock(self):
        result = True
        msg = ""
        try:
            # check_ordered_stocks_trade_done 완료까지 handle_buy_stock 대기
            self.buy_done_event.wait()
            # 매수 가능 종목내에서만 매수
            t_now = datetime.datetime.now()
            t_buy = t_now.replace(hour=15, minute=15, second=0, microsecond=0)
            
            for code in self.buyable_stocks.keys():
                curr_price = self.get_curr_price(code)
                if curr_price == 0:
                    continue

                buy_target_price = self.get_buy_target_price(code)

                if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:
                    # 물타기
                    if self.stocks[code]['allow_monitoring_buy'] == False:
                        # 목표가 왔다 -> 매수 감시 시작
                        if curr_price <= buy_target_price:
                            # 1차 매수 경우 RSI 조건 추가
                            if self.stocks[code]['buy_done'][0] == False:
                                rsi = self.get_rsi(code)
                                buy_rsi = self.get_buy_rsi(code)
                                if rsi > 0 and rsi < buy_rsi:
                                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 감시 시작, {curr_price}(현재가) <= {buy_target_price}(매수 목표가)")
                                    self.stocks[code]['allow_monitoring_buy'] = True
                                else:
                                    # PRINT_INFO(f"Not buy [{self.stocks[code]['name']}] RSI:{rsi} >= BUY RSI:{buy_rsi}")
                                    pass
                            else:
                                # 2차 매수 이상 경우
                                PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 감시 시작, {curr_price}(현재가) {buy_target_price}(매수 목표가)")
                                self.stocks[code]['allow_monitoring_buy'] = True
                    else:
                        # buy 모니터링 중
                        # "현재가 >= 저가 + BUY_MARGIN_P%" 에서 매수
                        # "15:15" 까지 매수 안됐고 "현재가 <= 매수가"면 매수
                        # "현재가 > 매수가"면 매수
                        lowest_price = self.get_lowest_price(code)
                        buy_margin = 1 + self.to_percent(BUY_MARGIN_P)
                        if ((lowest_price > 0) and curr_price >= (lowest_price * buy_margin)) \
                            or (t_now >= t_buy and curr_price <= buy_target_price) \
                            or (curr_price > buy_target_price):
                            if self.stocks[code]['buy_order_done'] == False:
                                # 1차 매수 상태에서 allow_monitoring_buy 가 false 안된 상태에서 2차 매수 들어갈 때
                                # 1차 매수 반복되는 문제 수정
                                PRINT_INFO(f"[{self.stocks[code]['name']}] {curr_price}(현재가) {buy_target_price}(매수가) {lowest_price}(저가)")
                                if lowest_price <= buy_target_price:
                                    buy_target_qty = self.get_buy_target_qty(code)
                                    if self.buy(code, curr_price, buy_target_qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                        self.set_order_done(code, BUY_CODE)
                                        if curr_price >= int(lowest_price * buy_margin):
                                            PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매수 주문, {buy_target_qty}주 {curr_price}(현재가) >= {int(lowest_price * buy_margin)}({lowest_price}(저가) * {buy_margin})")
                                        else:
                                            PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매수 주문, {buy_target_qty}주 {curr_price}(현재가) > {buy_target_price}(매수 목표가)")
                else:
                    # 불타기
                    if self.stocks[code]['buy_done'][0] == False:
                        # 1차 매수 안된 경우 매수가 이하에서 매수
                        if self.stocks[code]['allow_monitoring_buy'] == False:
                            # 목표가 왔다 -> 매수 감시 시작
                            if curr_price <= buy_target_price:
                                # 1차 매수 경우 RSI 조건 추가
                                rsi = self.get_rsi(code)
                                buy_rsi = self.get_buy_rsi(code)
                                if rsi > 0 and rsi < buy_rsi:
                                    PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 감시 시작, {curr_price}(현재가) {buy_target_price}(매수 목표가)")
                                    self.stocks[code]['allow_monitoring_buy'] = True
                                else:
                                    # PRINT_INFO(f"Not buy [{self.stocks[code]['name']}] RSI:{rsi} >= BUY RSI:{buy_rsi}")
                                    pass
                        else:
                            # buy 모니터링 중
                            # "현재가 >= 저가 + BUY_MARGIN_P%" 에서 매수
                            # "15:15" 까지 매수 안됐고 "현재가 <= 매수가"면 매수
                            # "현재가 >= 매수가"면 매수
                            lowest_price = self.get_lowest_price(code)
                            buy_margin = 1 + self.to_percent(BUY_MARGIN_P)
                            if ((lowest_price > 0) and curr_price >= (lowest_price * buy_margin)) \
                                or (t_now >= t_buy and curr_price <= buy_target_price) \
                                or (curr_price > buy_target_price):
                                if self.stocks[code]['buy_order_done'] == False:
                                    # 1차 매수 상태에서 allow_monitoring_buy 가 false 안된 상태에서 2차 매수 들어갈 때
                                    # 1차 매수 반복되는 문제 수정
                                    PRINT_DEBUG(f"[{self.stocks[code]['name']}] {curr_price}(현재가) {buy_target_price}(매수가) {lowest_price}(저가)")
                                    if lowest_price <= buy_target_price:
                                        buy_target_qty = self.get_buy_target_qty(code)
                                        if self.buy(code, curr_price, buy_target_qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                            self.set_order_done(code, BUY_CODE)
                                            if curr_price >= int(lowest_price * buy_margin):
                                                PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매수 주문, {buy_target_qty}주 {curr_price}(현재가) >= {int(lowest_price * buy_margin)}({lowest_price}(저가) * {buy_margin})")
                                            else:
                                                PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매수 주문, {buy_target_qty}주 {curr_price}(현재가) > {buy_target_price}(매수 목표가)")                                            
                    else:
                        # 불타기는 2차 매수까지만 진행
                        # 상승 추세 경우만 불타기
                        if self.stocks[code]['buy_done'][1] == False and self.stocks[code]['ma_trend'] == TREND_UP:
                            self.stocks[code]['allow_monitoring_buy'] = True
                            # 1차 매수 완료 경우 평단가 2~2.5% 사이에서 2차 매수(불타기)
                            if self.stocks[code]['buy_order_done'] == False:
                                if curr_price >= (self.stocks[code]['avg_buy_price'] * 1.02) and curr_price <= (self.stocks[code]['avg_buy_price'] * 1.025):
                                    buy_target_qty = self.get_buy_target_qty(code)
                                    if self.buy(code, curr_price, buy_target_qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                        self.set_order_done(code, BUY_CODE)
                                        PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매수 주문, {buy_target_qty}주 {curr_price}(현재가) >= {int(self.stocks[code]['avg_buy_price'] * 1.02)}(평단가+2%)")                    
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            self.buyable_stocks_event.set()

    ##############################################################
    # 매도 처리
    ##############################################################
    def handle_sell_stock(self, order_type:str = ORDER_TYPE_LIMIT_ORDER):
        result = True
        msg = ""
        try:
            # check_ordered_stocks_trade_done 완료까지 handle_sell_stock 대기
            self.sell_done_event.wait()
            sell_margin = 1 + self.to_percent(SELL_MARGIN_P)

            self.my_stocks_event.wait()
            for code in self.my_stocks.keys():
                curr_price = self.get_curr_price(code)
                if curr_price == 0:
                    continue

                if self.trade_strategy.loss_cut_time == LOSS_CUT_MARKET_CLOSE:
                    # 종가 손절
                    # 전날 종가로 손절 안된 경우 처리
                    # 손절 주문 완료 했으면 다시 주문하지 않는다
                    if self.stocks[code]['loss_cut_order'] == True and self.already_ordered(code, SELL_CODE) == False:
                        t_now = datetime.datetime.now()
                        t_loss_cut = t_now.replace(hour=9, minute=1, second=0, microsecond=0)
                        # 장 시작시 "시가 > 손절가"인데도 주문 나간다. 09:01 후에 하자
                        if t_now >= t_loss_cut:
                            loss_cut_price = self.get_loss_cut_price(code)
                            if curr_price < loss_cut_price:
                                self.stocks[code]['allow_monitoring_sell'] = True
                                stockholdings = self.stocks[code]['stockholdings']
                                # 손절 주문 시 조건 안따지고 무조건 주문낸다
                                if self.sell(code, curr_price, stockholdings, ORDER_TYPE_MARKET_ORDER, True) == True:
                                    PRINT_INFO(f"[{self.stocks[code]['name']}] 전날 종가 손절 안된 경우 손절 주문 성공, 현재가({curr_price}) < 손절가({loss_cut_price})")
                                    self.set_order_done(code, SELL_CODE)
                                    self.stocks[code]['loss_cut_order'] = True
                                else:
                                    self.send_msg_err(f"[{self.stocks[code]['name']}] 손절 주문 실패")

                if self.stocks[code]['sell_1_done'] == False:
                    # 1차 매도 안된 상태
                    sell_target_price = self.my_stocks[code]['sell_target_price']

                    if self.trade_strategy.sell_trailing_stop == True:
                        if self.stocks[code]['allow_monitoring_sell'] == False:
                            # 목표가 왔다 -> 매도 감시 시작
                            if curr_price >= sell_target_price and sell_target_price > 0:
                                PRINT_INFO(f"[{self.stocks[code]['name']}] 매도 감시 시작, {curr_price}(현재가) 매도 목표가({sell_target_price})")
                                self.stocks[code]['allow_monitoring_sell'] = True
                        else:
                            # 익절가 이하 시 매도
                            # 현재가 >= 목표가 + SELL_MARGIN_P% 면 매도
                            take_profit_price = self.get_take_profit_price(code)
                            if (take_profit_price > 0 and curr_price <= take_profit_price) \
                                or (curr_price >= (sell_target_price * sell_margin)):
                                qty = max(1, int(self.my_stocks[code]['stockholdings'] / 2))

                                if self.sell(code, curr_price, qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                    self.set_order_done(code, SELL_CODE)
                                    if curr_price >= (sell_target_price * sell_margin):
                                        PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매도 주문, {qty}주 {curr_price}(현재가) >= 목표가 + {SELL_MARGIN_P}% : {int(sell_target_price * sell_margin)}")
                                    else:
                                        PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매도 주문, {qty}주 {curr_price}(현재가) <= {take_profit_price}(익절가) {self.stocks[code]['highest_price_ever']}(최고가)")
                    else:
                        if curr_price >= sell_target_price and sell_target_price > 0:
                            self.stocks[code]['allow_monitoring_sell'] = True
                            qty = max(1, int(self.my_stocks[code]['stockholdings'] / 2))
                            # 지정가 매도
                            if self.sell(code, curr_price, qty, ORDER_TYPE_LIMIT_ORDER) == True:
                                self.set_order_done(code, SELL_CODE)
                                PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매도 주문, {qty}주 {curr_price}(현재가) >= {sell_target_price}(목표가)")
                else:
                    # 반 매도된 상태
                    # N차 매도가 : N-1차 매도가 * x (N>=2)
                    sell_target_price = self.my_stocks[code]['sell_target_price']

                    if self.trade_strategy.take_profit_strategy == TAKE_PROFIT_STRATEGY_SLOW:
                        # "현재가 >= 목표가" 경우 매도
                        # 익절은 handle_loss_cut 에서 처리
                        if curr_price >= sell_target_price and sell_target_price > 0:        
                            # 1차 매도 후 다음날 매도 가능하게
                            self.stocks[code]['allow_monitoring_sell'] = True
                            qty = max(1, int(self.my_stocks[code]['stockholdings'] / 2))
                            if self.sell(code, curr_price, qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                self.set_order_done(code, SELL_CODE)
                                PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매도 주문, {qty}주 {curr_price}(현재가) >= {sell_target_price}(목표가)")
                    else:
                        # "현재가 >= 목표가" or "현재가 <= 1차 목표가" 경우 매도
                        if (curr_price >= sell_target_price and sell_target_price > 0) or curr_price <= self.stocks[code]['first_sell_target_price']:
                            # 1차 매도 후 다음날 매도 가능하게
                            self.stocks[code]['allow_monitoring_sell'] = True                            
                            if curr_price <= self.stocks[code]['first_sell_target_price']:
                                # "현재가 <= 1차 목표가" 경우 전량 매도
                                qty = int(self.my_stocks[code]['stockholdings'])
                            else:
                                qty = max(1, int(self.my_stocks[code]['stockholdings'] / 2))
                            if self.sell(code, curr_price, qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                self.set_order_done(code, SELL_CODE)
                                if curr_price >= sell_target_price:
                                    PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매도 주문, {qty}주 {curr_price}(현재가) >= {sell_target_price}(목표가)")
                                elif curr_price <= self.stocks[code]['first_sell_target_price']:
                                    PRINT_DEBUG(f"[{self.stocks[code]['name']}] 매도 주문, {qty}주 {curr_price}(현재가) <= {self.stocks[code]['first_sell_target_price']}(first_sell_target_price)")
            
            # 장중 손절
            if self.trade_strategy.loss_cut_time == LOSS_CUT_MARKET_OPEN:
                self.handle_loss_cut()
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 주문 번호 리턴
    #   return : 성공 시 True 주문 번호, 실패 시 False  ""
    #               취소 주문은 True, ""
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
            for stock in order_list:           
                if stock['pdno'] == code:
                    # 취소 주문은 제외
                    if stock['cncl_yn'] == 'Y':
                        return True, ""
                    if stock['sll_buy_dvsn_cd'] == buy_sell:
                        if trade_done == TRADE_DONE_CODE:
                            # 체결, 주문수량 == 총체결수량
                            if stock['ord_qty'] == stock['tot_ccld_qty']:
                                return True, stock['odno']
                            else:
                                return False, ""
                        elif trade_done == TRADE_NOT_DONE_CODE:
                            # 미체결, 주문수량 > 총체결수량
                            if stock['ord_qty'] > stock['tot_ccld_qty']:
                                return True, stock['odno']
                            else:
                                return False, ""
                        else:
                            return True, stock['odno']
            return False, ""
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 주식 주문 전량 취소
    #   종목코드 매수/매도 조건에 맞는 주문 취소
    #   단, 모의 투자 미지원
    #   return : 성공 시 True, 실패 시 False
    #   param :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    ##############################################################
    def cancel_order(self, code, buy_sell: str):
        result = True
        msg = ""
        try:            
            ret = False
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
                time.sleep(API_DELAY_S)
                res = requests.post(URL, headers=headers, params=params)
                if self.is_request_ok(res) == True:
                    self.send_msg(f"[주식 주문 전량 취소 주문 성공]")
                    if buy_sell == BUY_CODE:
                        self.stocks[code]['buy_order_done'] = False
                    else:
                        self.stocks[code]['sell_order_done'] = False
                    ret = True
                else:
                    if self.config['TR_ID_MODIFY_CANCEL_ORDER'] == "VTTC0803U":
                        self.send_msg_err(f"[주식 주문 전량 취소 주문 실패] [{self.stocks[code]['name']}] 모의 투자 미지원")
                    else:
                        self.send_msg_err(f"[주식 주문 전량 취소 주문 실패] [{self.stocks[code]['name']}] {str(res.json())}")
                    ret = False
            else:
                self.send_msg_err(f"[cancel_order failed] [{self.stocks[code]['name']}] {buy_sell}")
                ret = False            
            return ret
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 매수/매도 체결 여부 체크
    # Return    : 첫번째 return 값
    #               주문 수량 전체 체결 시 True, 아니면 False
    #               이미 체결 완료된 주문이면 return False
    #             두번째 return 값
    #               첫번째 return 값이 True면 평균 체결가, 아니면 0
    # Parameter :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    ##############################################################
    def check_trade_done(self, code, buy_sell: str):
        result = True
        msg = ""
        try:
            if code not in self.stocks.keys():
                # 보유는 하지만 DB 에 없는 종목 제외 ex) 공모주
                return False, 0
            order_list = self.get_order_list()
            for stock in order_list:
                if stock['pdno'] == code:
                    # 이미 체결 완료 처리한 주문은 재처리 금지
                    if buy_sell == BUY_CODE:
                        if stock['odno'] in self.buy_done_order_list:
                            return False, 0
                    elif buy_sell == SELL_CODE:
                        if stock['odno'] in self.sell_done_order_list:
                            return False, 0
                    else:
                        if stock['odno'] in self.buy_done_order_list or stock['odno'] in self.sell_done_order_list:
                            return False, 0

                    if stock['sll_buy_dvsn_cd'] == buy_sell:
                        if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                            buy_sell_order = "매수"
                        else:
                            buy_sell_order = "매도"
                        # 주문 수량
                        order_qty = int(stock['ord_qty'])
                        # 총 체결 수량
                        tot_trade_qty = int(stock['tot_ccld_qty'])
                        
                        # 전량 매도 됐는데 일부만 매도된걸로 처리되는 버그 처리
                        # 잔고 조회해서 보유잔고 없으면 전량 매도 처리   
                        self.update_my_stocks()

                        if order_qty == tot_trade_qty:
                            # 전량 체결 완료
                            if stock['sll_buy_dvsn_cd'] == SELL_CODE:
                                self.sell_done_order_list.append(stock['odno'])
                                # 매도 체결 완료 시, 손익, 수익률 표시
                                gain_loss_money = (int(stock['avg_prvs']) - self.stocks[code]['avg_buy_price']) * int(stock['tot_ccld_qty'])
                                if self.stocks[code]['avg_buy_price'] > 0:
                                    gain_loss_p = round(float((int(stock['avg_prvs']) - self.stocks[code]['avg_buy_price']) / self.stocks[code]['avg_buy_price']) * 100, 2)     # 소스 3째 자리에서 반올림                  
                                    self.send_msg(f"[{self.stocks[code]['name']}] {stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {buy_sell_order} 전량 체결 완료, 손익:{gain_loss_money} {gain_loss_p}%", True)
                            else:
                                # 체결 완료 체크한 주문은 다시 체크하지 않는다
                                # while loop 에서 반복적으로 체크하는거 방지
                                self.buy_done_order_list.append(stock['odno'])                                
                                nth_buy = 0
                                for i in range(BUY_SPLIT_COUNT):
                                    if self.stocks[code]['buy_done'][i] == False:
                                        nth_buy = i + 1
                                        break
                                self.send_msg(f"[{self.stocks[code]['name']}] {stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {nth_buy}차 {buy_sell_order} 전량 체결 완료", True)

                            return True, int(stock['avg_prvs'])
                        elif tot_trade_qty == 0:
                            # 미체결
                            return False, 0
                        elif order_qty > tot_trade_qty:
                            # 일부 체결
                            if self.stocks[code]['stockholdings'] < tot_trade_qty:
                                for i in range(BUY_SPLIT_COUNT):
                                    if self.stocks[code]['buy_done'][i] == False:
                                        # 일부만 매수된 경우, 다음날 매수 위해 매수량 업데이트
                                        self.stocks[code]['buy_qty'][i] -= tot_trade_qty
                                        break

                                raise Exception(f"[{self.stocks[code]['name']}] {stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {buy_sell_order} 체결")
                else:
                    # 해당 종목 아님
                    pass

            return False, 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
                return result, 0

    ##############################################################
    # 체결 여부 체크
    #   주문 종목에서 매수 체결 여부 확인
    ##############################################################
    def check_ordered_stocks_trade_done(self):
        result = True
        msg = ""
        try:
            before_trade_done_my_stock_count = self.get_my_stock_count()
            after_trade_done_my_stock_count = before_trade_done_my_stock_count
            is_trade_done = False

            order_list = self.get_order_list()
            for stock in order_list:
                code = stock['pdno']
                if code in self.stocks.keys():
                    buy_sell = stock['sll_buy_dvsn_cd']                    
                    ret, trade_done_avg_price = self.check_trade_done(code, buy_sell)
                    if ret == True:
                        is_trade_done = True
                        # 평균 체결가
                        avg_price = int(stock['avg_prvs'])
                        if avg_price == 0:
                            self.send_msg_err(f"[{stock['prdt_name']}] 평균 체결가 오류 {avg_price} [{self.stocks[code]['name']}]")
                            # check_trade_done 에서의 체결가로 사용
                            avg_price = trade_done_avg_price

                        if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                            self.set_buy_done(code, avg_price)
                        else:
                            self.set_sell_done(code, avg_price)
                else:
                    # 보유는 하지만 DB 에 없는 종목 제외 ex) 공모주
                    pass                       

            # check_ordered_stocks_trade_done 완료까지 handle_sell_stock, handle_buy_stock는 대기
            self.buy_done_event.set()
            self.sell_done_event.set()
            
            # 여러 종목 체결되도 결과는 한 번만 출력
            if is_trade_done == True:
                self.show_trade_done_stocks(BUY_CODE)
                self.show_trade_done_stocks(SELL_CODE)
                # 종목 체결로 종목 수 변경된 경우 관련 정보 업데이트
                after_trade_done_my_stock_count = self.get_my_stock_count()
                if before_trade_done_my_stock_count != after_trade_done_my_stock_count:
                    self.init_trade_strategy()
                    self.update_buyable_stocks()
                # 계좌 잔고 조회
                self.get_stock_balance()
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
            self.buy_done_event.set() # exception 빠진 경우에 handle_buy_stock 대기되지 않게
            self.sell_done_event.set() # exception 빠진 경우에 handle_sell_stock 대기되지 않게
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 주식 일별 주문 체결 조회 종목 정보 리턴
    # Return    : 주문 체결/미체결 조회 종목 리스트
    # Parameter :
    #       trade          전체("00"), 체결("01"), 미체결("02")
    ##############################################################
    def get_order_list(self, trade="00"):
        result = True
        msg = ""
        order_list = list()
        try:
            # ex) 20130414
            TODAY_DATE = f"{datetime.datetime.now().strftime('%Y%m%d')}"

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
            time.sleep(API_DELAY_S)
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                order_list = res.json()['output1']
            else:
                raise Exception(f"[update_order_list failed]]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
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
            PRINT_DEBUG(f"============주문 조회============")
            order_list = self.get_order_list()
            for stock in order_list:
                # 주문 수량
                order_qty = int(stock['ord_qty'])
                # 총 체결 수량
                tot_trade_qty = int(stock['tot_ccld_qty'])
                # 전량 체결 완료 주문은 제외
                if order_qty > tot_trade_qty:
                    not_traded_stock_count += 1
                    if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                        buy_sell_order = "매수 주문"
                    else:
                        buy_sell_order = "매도 주문"
                    curr_price = self.get_curr_price(stock['pdno'])
                    PRINT_DEBUG(f"{stock['prdt_name']} {buy_sell_order} {stock['ord_unpr']}원 {stock['ord_qty']}주, 현재가 {curr_price}원")
            PRINT_DEBUG(f"=================================\n")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
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
            if buy_sell == BUY_CODE:
                buy_sell_order = "매수"
                data = {'종목명':[], '매수/매도':[], '체결평균가':[], '수량':[], '현재가':[]}
            else:
                buy_sell_order = "매도"
                data = {'종목명':[], '매수/매도':[], '체결평균가':[], '평단가':[], '손익':[], '수익률(%)':[], '수량':[], '현재가':[]}

            order_list = self.get_order_list()
            if len(order_list) == 0:
                return None

            PRINT_DEBUG(f"========={buy_sell_order} 체결 조회=========")
            for stock in order_list:
                if int(stock['tot_ccld_qty']) > 0:
                    code = stock['pdno']
                    if code in self.stocks.keys():
                        if buy_sell == stock['sll_buy_dvsn_cd']:
                            gain_loss_p = 0
                            if buy_sell == SELL_CODE:
                                gain_loss_money = (int(stock['avg_prvs']) - self.stocks[code]['avg_buy_price']) * int(stock['tot_ccld_qty'])
                                if self.stocks[code]['avg_buy_price'] > 0:
                                    gain_loss_p = round(float((int(stock['avg_prvs']) - self.stocks[code]['avg_buy_price']) / self.stocks[code]['avg_buy_price']) * 100, 2)     # 소스 3째 자리에서 반올림                  
                            
                            curr_price = self.get_curr_price(code)
                            
                            data['종목명'].append(stock['prdt_name'])
                            data['매수/매도'].append(buy_sell_order)
                            data['체결평균가'].append(int(float(stock['avg_prvs'])))
                            if buy_sell == SELL_CODE:
                                data['평단가'].append(self.stocks[code]['avg_buy_price'])
                                data['손익'].append(gain_loss_money)
                                data['수익률(%)'].append(gain_loss_p)
                            data['수량'].append(stock['tot_ccld_qty'])
                            data['현재가'].append(curr_price)
                    else:
                        # 보유는 하지만 DB 에 없는 종목 제외 ex) 공모주
                        pass

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'r'  # 우측 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            PRINT_DEBUG(table)
            return None
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 이미 주문한 종목인지 체크
    #   1차 매수/매도 2차 매수/매도 구분하기 위해 총 매수/매도 금액 비교
    #   총 매수/매도 금액이 해당 차수 금액이여야 같은 주문이다
    # Return    : 이미 주문한 종목이면 Ture, 아니면 False
    # Parameter :
    #       code        종목코드
    #       buy_sell    "01" : 매도, "02" : 매수
    ##############################################################
    def already_ordered(self, code, buy_sell: str):
        result = True
        msg = ""
        try:
            ret = False
            if buy_sell == BUY_CODE:
                ret = self.stocks[code]['buy_order_done']
            else:
                ret = self.stocks[code]['sell_order_done']
            return ret
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 종목 정보 출력
    # Parameter :
    #       sort_by     SORT_BY_NAME : 이름순 오름차순
    #                   SORT_BY_UNDER_VALUE : undervalue 내림차순
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

            # sorted_data = dict(sorted(temp_stocks.items(), key=lambda x: x[1]['undervalue'], reverse=True))
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
            
            self.send_msg(table, send_discode)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 저평가 높은 순으로 출력
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
            
            self.send_msg(table, send_discode)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # stocks 변경있으면 save stocks_info.json
    # Return    : 현재 stocks 정보
    # Parameter :
    #       pre_stocks  이전 stocks 정보
    ##############################################################
    def check_save_stocks_info(self, pre_stocks:dict):
        result = True
        msg = ""
        try:                
            if pre_stocks != self.stocks:
                self.save_stocks_info(STOCKS_INFO_FILE_PATH)
                pre_stocks.clear()
                pre_stocks = copy.deepcopy(self.stocks)

            return pre_stocks
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

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
            for stock in order_list:
                # 주문 수량
                order_qty = int(stock['ord_qty'])
                # 총 체결 수량
                tot_trade_qty = int(stock['tot_ccld_qty'])
                if tot_trade_qty == order_qty:
                    # 체결 완료 주문 번호
                    if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                        self.buy_done_order_list.append(stock['odno'])
                    elif stock['sll_buy_dvsn_cd'] == SELL_CODE:
                        self.sell_done_order_list.append(stock['odno'])
                    else:
                        self.send_msg_err(f"{stock['prdt_name']} not support sll_buy_dvsn_cd {stock['sll_buy_dvsn_cd']}")

        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 손절가
    #   last차 매수가 -x%
    ##############################################################
    def get_loss_cut_price(self, code):
        result = True
        msg = ""
        price = 0
        try:
            if self.trade_strategy.buy_split_strategy == BUY_SPLIT_STRATEGY_DOWN:
                # 물타기
                last_split_buy_index = len(self.stocks[code]['buy_price']) - 1
                price = self.stocks[code]['buy_price'][last_split_buy_index] * (1 - self.to_percent(LOSS_CUT_P))
            else:
                # 불타기 경우 2차 매수까지 완료 됐으면 -2% 이탈 시 손절
                if self.stocks[code]['buy_done'][1] == True:
                    price = self.stocks[code]['avg_buy_price'] * 0.98
                else:
                    # 1차 매수 후 손절은 -5% 이탈 시
                    price = self.stocks[code]['avg_buy_price'] * (1 - self.to_percent(LOSS_CUT_P))
            
            # N차 매도 후 나머지 물량은 익절선을 낮추어 길게 간다
            if self.trade_strategy.take_profit_strategy == TAKE_PROFIT_STRATEGY_SLOW:
                if self.stocks[code]['sell_1_done'] == True:
                    # 익절가 = 평단가과 최근 매도가의 중간
                    price = self.stocks[code]['avg_buy_price'] + (self.stocks[code]['recent_sold_price'] - self.stocks[code]['avg_buy_price']) / 2
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            # 주식 호가 단위로 가격 변경
            return self.get_stock_asking_price(int(price))
        
    ##############################################################
    # 손절 처리
    #   현재가 < 손절가 면 손절 처리
    #   오늘 > 최근 매수일 + x day, 즉 x 일 동안 매수 없고
    #       1차 매도가 안됐고 last차 매수까지 안된 경우 손절
    # Return :
    #   손절 주문 시 True, 손절 주문 없을 시 False
    ##############################################################
    def handle_loss_cut(self):
        result = True
        msg = ""
        ret = False
        try:
            today = date.today()
            no_buy_days = 10
            for code in self.my_stocks.keys():
                # PRINT_INFO(f"[{self.stocks[code]['name']}] 손절 체크")
                # 손실 상태에서 x일간 지지부진하면 손절
                # 오늘 > 최근 매수일 + x day, 즉 x 일 동안 매수 없고
                # 1차 매도가 안됐고 last차 매수까지 안된 경우 손절
                do_loss_cut = False

                recent_buy_date = date.fromisoformat(self.stocks[code]['recent_buy_date'])
                if recent_buy_date == None:
                    continue

                # 1차 매도 된 경우는 시간지났다고 손절 금지
                if self.stocks[code]['sell_1_done'] == False:
                    days_diff = (today - recent_buy_date).days
                    # 손실 상태에서 x일간 지지부진하면 손절
                    if days_diff > no_buy_days:
                        # 손실 상태 체크
                        if self.stocks[code]['avg_buy_price'] < self.get_end_price(code):
                            if self.stocks[code]['sell_1_done'] == False and self.stocks[code]['buy_done'][BUY_SPLIT_COUNT-1] == False:
                                do_loss_cut = True
                                PRINT_INFO(f'{recent_buy_date} 매수 후 {today}까지 {days_diff} 동안 매수 없어 손절')

                curr_price = self.get_curr_price(code)
                loss_cut_price = self.get_loss_cut_price(code)
                # PRINT_DEBUG(f"[{self.stocks[code]['name']}] {curr_price}(현재가) {loss_cut_price}(손절가) {self.stocks[code]['loss_cut_order']}(loss_cut_order)")
                if do_loss_cut or (curr_price > 0 and curr_price < loss_cut_price):
                    self.stocks[code]['allow_monitoring_sell'] = True
                    stockholdings = self.stocks[code]['stockholdings']
                    # 손절 주문 안된 경우만 주문
                    if self.stocks[code]['loss_cut_order'] == False:
                        # 손절 주문 시 조건 안따지고 무조건 주문낸다
                        if self.sell(code, curr_price, stockholdings, ORDER_TYPE_MARKET_ORDER, True) == True:
                            self.send_msg(f"[{self.stocks[code]['name']}] 손절 주문 성공, 현재가({curr_price}) < 손절가({loss_cut_price})")
                            self.set_order_done(code, SELL_CODE)
                            self.stocks[code]['loss_cut_order'] = True
                        else:
                            self.send_msg_err(f"[{self.stocks[code]['name']}] 손절 주문 실패")

                if self.stocks[code]['loss_cut_order'] == True:
                    ret = True
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return ret

    ##############################################################
    # 매수 후 여지껏 최고가 업데이트
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
                self.send_msg_err(msg)

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

            for code in self.stocks.keys():
                if (self.is_my_stock(code) and self.stocks[code]['buy_done'][BUY_SPLIT_COUNT-1] == False) or self.is_ok_to_buy(code, True):
                    curr_price = self.get_curr_price(code)
                    if curr_price == 0:
                        continue
                    buy_target_price = self.get_buy_target_price(code)
                    if buy_target_price > 0:
                        gap_p = int((curr_price - buy_target_price) * 100 / buy_target_price)
                        # 현재가 - 매수가 GAP < X%
                        # 1차 매수 후 n차 매수 안된 종목은 무조건 매수 가능 종목으로 편입
                        need_buy = False
                        if self.stocks[code]['buy_done'][0] == True:
                            for i in range(1, BUY_SPLIT_COUNT):
                                if self.stocks[code]['buy_done'][i] == False:
                                    need_buy = True
                                    break

                        if gap_p < BUYABLE_GAP or need_buy == True:
                            temp_stock = copy.deepcopy({code: self.stocks[code]})
                            temp_buyable_stocks[code] = temp_stock[code]
                        else:
                            PRINT_INFO(f"[{self.stocks[code]['name']}] 매수 금지, buyable gap({gap_p})")
                time.sleep(0.001)   # context switching between threads

            # handle_buy_stock() 등에서 self.buyable_stocks 사용 중이면 사용 완료까지 대기
            self.buyable_stocks_event.wait()
            self.buyable_stocks.clear()
            self.buyable_stocks = copy.deepcopy(temp_buyable_stocks)
            
            # '저평가'값이 큰 순으로 최대 x개 까지만 유지하고 나머지는 제외
            buyable_count = min(BUYABLE_COUNT, len(self.buyable_stocks))
            # 단, '저평가'값이 0 이상이면 buyable_stocks 에 포함
            sorted_list = sorted(self.buyable_stocks.items(), key=lambda x: x[1]['undervalue'], reverse=True)
            while buyable_count < len(self.buyable_stocks) and sorted_list[buyable_count][1]['undervalue'] > 0:
                buyable_count = buyable_count + 1
            self.buyable_stocks = dict(sorted_list[:buyable_count])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)            

    ##############################################################
    # 매수 가능 종목 출력
    ##############################################################
    def show_buyable_stocks(self):
        result = True
        msg = ""
        try:
            temp_stocks = copy.deepcopy(self.buyable_stocks)
            sorted_data = dict(sorted(temp_stocks.items(), key=lambda x: x[1]['undervalue'], reverse=True))
            data = {'종목명':[], '저평가':[], '목표가GAP(%)':[], '매수가':[], '현재가':[], '매수가GAP(%)':[], 'Envelope':[], 'RSI':[], 'BUY_RSI':[], '60일선추세':[]}
            for code in sorted_data.keys():
                curr_price = self.get_curr_price(code)
                buy_target_price = self.get_buy_target_price(code)
                if buy_target_price > 0:
                    gap_p = int((curr_price - buy_target_price) * 100 / buy_target_price)
                else:
                    gap_p = 0
                data['종목명'].append(sorted_data[code]['name'])
                data['저평가'].append(sorted_data[code]['undervalue'])
                data['목표가GAP(%)'].append(sorted_data[code]['gap_max_sell_target_price_p'])
                data['매수가'].append(buy_target_price)
                data['현재가'].append(curr_price)
                data['매수가GAP(%)'].append(gap_p)
                data['Envelope'].append(sorted_data[code]['envelope_p'])
                if gap_p <= 0:
                    data['RSI'].append(self.get_rsi(code))
                else:
                    data['RSI'].append(0)
                data['BUY_RSI'].append(self.get_buy_rsi(code))
 
                trend_str = ""             
                if sorted_data[code]['ma_trend'] == TREND_DOWN:
                    trend_str = '하락'
                elif sorted_data[code]['ma_trend'] == TREND_SIDE:
                    trend_str = '보합'
                elif sorted_data[code]['ma_trend'] == TREND_UP:
                    trend_str = '상승'
                data['60일선추세'].append(trend_str)

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'r'  # 우측 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            
            PRINT_DEBUG("==========매수 가능 종목==========")
            PRINT_DEBUG(table)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

    ##############################################################
    # 익절가 리턴
    #   여지껏 최고가 - 익절가%
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
                self.send_msg_err(msg)
            return int(price)

    ##############################################################
    # 장 종료 후 clear
    #   전날에 조건에 맞았지만 체결안된 경우 다음 날 다시 조건 검사부터 한다.
    ##############################################################
    def clear_after_market(self):
        result = True
        msg = ""
        try:
            for code in self.stocks.keys():
                self.stocks[code]['allow_monitoring_buy'] = False
                self.stocks[code]['allow_monitoring_sell'] = False
                # 종가 손절 전략에서 종가로 손절 안된 경우 다음 날 처리 위해 True 유지위해
                # 종가 손절 전략에서는 시장 종료 후 self.stocks[code]['loss_cut_order'] 를 False 처리하지 않는다
                if self.trade_strategy.loss_cut_time != LOSS_CUT_MARKET_CLOSE:                    
                    self.stocks[code]['loss_cut_order'] = False
                self.stocks[code]['buy_order_done'] = False
                self.stocks[code]['sell_order_done'] = False
                if self.stocks[code]['sell_done'] == True:
                    self.stocks[code]['avg_buy_price'] = 0
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
 
    ##############################################################
    # 금일 기준 X 일 내 최고 종가 리턴
    # param :
    #   code        종목 코드
    #   days        X 일. ex) 21 -> 금일 기준 21일 내(영업일 기준 약 한 달)
    ##############################################################
    def get_highest_end_pirce(self, code, days=21):
        result = True
        msg = ""
        highest_end_price = 0
        try:
            if days > 99:
                PRINT_INFO(f'can read over 99 data. make days to 99')
                days = 99

            end_price_list = self.get_end_price_list(code)
            highest_end_price = max(end_price_list[:days])
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return highest_end_price

    ##############################################################
    # 기간 내 최고 종가에서 급락 가격 리턴
    #   1차 매수가는 이 가격 이하로
    #   단기간에 급락해야 매수하기 위함
    #   ex) 한 달 내 최고 종가 - x%
    # param :
    #   code        종목 코드
    ##############################################################
    def get_plunge_price(self, code):
        result = True
        msg = ""
        try:
            price = 0
            # 한 달은 약 21일
            highest_end_price = self.get_highest_end_pirce(code, 21)
            # 최고 종가에서 최소 X% 폭락 가격
            margine_p = self.to_percent(max(18, self.stocks[code]['envelope_p'] * 1.5))
            price = highest_end_price * (1 - margine_p)
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
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
            time.sleep(API_DELAY_S)
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                stocks = res.json()['output1']
                for stock in stocks:
                    if int(stock['hldg_qty']) > 0:
                        my_stocks_count += 1
            else:
                raise Exception(f"[계좌 조회 실패]{str(res.json())}")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
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

            my_stock_count = self.get_my_stock_count()

            if my_stock_count <= MAX_MY_STOCK_COUNT * 1/3:
                self.trade_strategy.invest_risk = INVEST_RISK_HIGH 
            elif my_stock_count <= MAX_MY_STOCK_COUNT * 2/3:
                self.trade_strategy.invest_risk = INVEST_RISK_MIDDLE
            else:
                self.trade_strategy.invest_risk = INVEST_RISK_LOW

            self.trade_strategy.max_per = 80                                # PER가 이 값 이상이면 매수 금지            
            
            if self.trade_strategy.invest_risk == INVEST_RISK_HIGH:
                self.trade_strategy.under_value = -5                       # 저평가가 이 값 미만은 매수 금지
                self.trade_strategy.gap_max_sell_target_price_p = 0         # 목표가GAP 이 이 값 미만은 매수 금지
                self.trade_strategy.sum_under_value_sell_target_gap = 0     # 저평가 + 목표가GAP 이 이 값 미만은 매수 금지
                self.trade_strategy.buyable_market_cap = 10000               # 시총 X 미만 매수 금지(억)
                self.trade_strategy.trend = TREND_SIDE                      # 추세선이 이거 이상이여야 매수          
            elif self.trade_strategy.invest_risk == INVEST_RISK_MIDDLE:
                self.trade_strategy.under_value = 0
                self.trade_strategy.gap_max_sell_target_price_p = 3
                self.trade_strategy.sum_under_value_sell_target_gap = 5
                self.trade_strategy.buyable_market_cap = 10000
                self.trade_strategy.trend = TREND_SIDE
            else:   # INVEST_RISK_LOW
                self.trade_strategy.under_value = 2
                self.trade_strategy.gap_max_sell_target_price_p = 3
                self.trade_strategy.sum_under_value_sell_target_gap = 8
                self.trade_strategy.buyable_market_cap = 20000    
                self.trade_strategy.trend = TREND_UP
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            self.print_strategy()

    ##############################################################
    # get RSI
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
            end_price_list = self.get_end_price_list(code)

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
                self.send_msg_err(msg)
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
        try:
            buy_rsi = int(490 / self.stocks[code]['envelope_p'])
            market_cap = max(1, int(self.stocks[code]['market_cap'] / 10000))

            if self.stocks[code]['ma_trend'] == TREND_UP:
                # 조단위 시총
                # 시총에 따라 buy rsi 변경
                buy_rsi += min(8, market_cap*2)
            elif self.stocks[code]['ma_trend'] == TREND_SIDE:
                buy_rsi += min(6, market_cap)
            # 최소 buy_rsi
            buy_rsi = max(37, buy_rsi)
            return buy_rsi
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)

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
    ##############################################################
    def get_ma_trend(self, code: str, past_day=1, ma=60, consecutive_days=10, period="D"):
        result = True
        msg = ""
        ma_trend = TREND_DOWN
        try:
            # x일 연속 상승,하락인지 체크 그외 보합
            trand_up_count = 0
            trand_down_count = 0
            ma_price = self.get_ma(code, ma, past_day, period)
            start_day = past_day+1
            last_day = past_day+consecutive_days

            # 이평선 기울기 구하기 위해 last, recent ma price 구한다
            recent_ma_price = ma_price
            last_ma_price = self.get_ma(code, ma, consecutive_days + past_day - 1, period)
            ma_diff = abs(1 - (recent_ma_price/last_ma_price))
            trend_up_down_diff = 0.02       # ex) 기울기 2% 이상되어야 추세 up dwon
            
            for i in range(start_day, last_day):
                if i < last_day:
                    yesterdat_ma_price = self.get_ma(code, ma, i, period)
                    if ma_price > yesterdat_ma_price:
                        trand_up_count += 1
                    elif ma_price < yesterdat_ma_price:
                        trand_down_count += 1
                    ma_price = yesterdat_ma_price
            
            if trand_up_count >= (consecutive_days - 1) and ma_diff > trend_up_down_diff:
                ma_trend = TREND_UP
            elif trand_down_count >= (consecutive_days - 1) and ma_diff > trend_up_down_diff:
                ma_trend = TREND_DOWN
            else:
                ma_trend = TREND_SIDE
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return ma_trend

    ##############################################################
    # 2개 이상의 이평선의 배열 상태 리턴
    #   ex) "60 이평선 가격 > 90 이평선 가격 > 120 이평선 가격" 이면 정배열, 반대면 역배열
    #       그 외는 SOSO
    # param :
    #   code                종목 코드
    #   ma_list             이평선 리스트   ex) [60,90]
    #                       주의, 이평선 입력은 오름차순
    #   period              D : 일, W : 주, M : 월, Y : 년
    ##############################################################
    def get_multi_ma_status(self, code: str, ma_list:list, period="D"):
        result = True
        msg = ""
        ma_status = MA_STATUS_SOSO
        try:
            ma_price_list = []
            for ma in ma_list:
                ma_price_list.append(self.get_ma(code, ma, 1, period))

            positive_count = 0
            negative_count = 0
            
            ma_price_list_len = len(ma_price_list)
            for i in range(ma_price_list_len):
                if i+1 >= ma_price_list_len:
                    break
                if ma_price_list[i] > ma_price_list[i+1]:
                    positive_count += 1
                else:
                    negative_count += 1

            if positive_count >= (ma_price_list_len-1):
                ma_status = MA_STATUS_POSITIVE
            elif negative_count >= (ma_price_list_len-1):
                ma_status = MA_STATUS_NEGATIVE
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return ma_status

    ##############################################################
    # 1차 목표가 리턴
    ##############################################################
    def get_first_sell_target_price(self, code):
        result = True
        msg = ""
        price = self.stocks[code]['first_sell_target_price']
        try:
            # 1차 매도 안됐다 -> sell_target_price 가 1차 목표가이다.
            if self.stocks[code]['sell_1_done'] == False:
                price = self.stocks[code]['sell_target_price']
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return self.get_stock_asking_price(int(price))
        
    ##############################################################
    # 상황에 따른 envelope_p 계산하여 리턴
    ##############################################################
    def get_envelope_p(self, code):
        result = True
        msg = ""
        try:
            envelope_p = 20

            # ex) 시총 >= 40조 면 10
            if self.stocks[code]['market_cap'] >= 200000:
                envelope_p = 10
            elif self.stocks[code]['market_cap'] >= 100000:
                envelope_p = 11
            elif self.stocks[code]['market_cap'] >= 20000:
                envelope_p = 13
            else:
                envelope_p = 18

            self.stocks[code]['ma_trend'] = self.get_ma_trend(code)

            if self.stocks[code]['ma_trend'] == TREND_UP:
                # 60일선 상승 추세
                PRINT_DEBUG(f"[{self.stocks[code]['name']}]")
            elif self.stocks[code]['ma_trend'] == TREND_SIDE:
                # 60일선 보합 추세
                envelope_p += 1            # envelope up
                PRINT_DEBUG(f"[{self.stocks[code]['name']}]")
            else:
                # 60일선 하락 추세
                envelope_p += 3            # envelope up
                PRINT_INFO(f"[{self.stocks[code]['name']}] 60일선 하락 추세, envelope +3")

            # 공격적 전략상태에서 60,90일선 정배열 아니면 envelope up
            # 매수 금지 대신 좀더 보수적으로 매수
            if self.trade_strategy.invest_risk == INVEST_RISK_HIGH:
                if self.get_multi_ma_status(code, [60,90]) != MA_STATUS_POSITIVE:
                    envelope_p += 1

            # PER
            if self.stocks[code]['PER'] >= 50:
                envelope_p += 3
                PRINT_INFO(f"[{self.stocks[code]['name']}] PER {self.stocks[code]['PER']}, envelope +3")
        except Exception as ex:
            result = False
            msg = "{}".format(traceback.format_exc())
        finally:
            if result == False:
                self.send_msg_err(msg)
            return envelope_p
        
    ##############################################################
    # 주문가 문자열 리턴  
    ##############################################################
    def get_order_string(self, order_type):
        result = True
        msg = ""
        try:
            order_string = ""
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
                self.send_msg_err(msg)
            return order_string      