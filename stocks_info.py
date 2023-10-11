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

##############################################################
# 검증
#   1차 매수 후 당일 2차 매수 : OK
#   1차 매도 후 당일 2차 매도 : OK
#   손절 후 당일 매수 주문 : OK
##############################################################

def is_simulation():
    if INVEST_TYPE == "sim_invest":
        return True
    return False

##############################################################
#                       Config                               #
##############################################################
# 매수/매도 전략
# BUY
#   1 : 매수 목표가 매수
#   2 : 트레일링스탑 매수
#       손절 후 매수
#       손절가 -5% 에 1차 매수
#       손절가 상승 돌파 시 매수?(todo)
# SELL
#   1 : 목표가 전량 매도
#   2 : 트레일링스탑 전량 매도
#   3 : 목표가에 반 매도(2전략 트레일링스탑). 단, 매도가가 5일선 이하면 전량 매도
#       나머지는 15:15이후 현재가가 5일선 or 목표가 이탈 시 매도
BUY_STRATEGY = 2
SELL_STRATEGY = 3

INVEST_TYPE = "real_invest"                 # sim_invest : 모의 투자, real_invest : 실전 투자
# INVEST_TYPE = "sim_invest"                  # sim_invest : 모의 투자, real_invest : 실전 투자    #test
BUY_1_P = 40                                # 1차 매수 40%
BUY_2_P = 60                                # 2차 매수 60%

UNDER_VALUE = 1                             # 저평가가 이 값 미만은 매수 금지
GAP_MAX_SELL_TARGET_PRICE_P = 1             # 목표주가GAP 이 이 값 미만은 매수 금지
SUM_UNDER_VALUE_SELL_TARGET_GAP = 3         # 저평가 + 목표주가GAP 이 이 값 미만은 매수 금지
LOSS_CUT_P = 5                              # 2차 매수에서 x% 이탈 시 손절
MAX_PER = 30                                # PER가 이 값 이상이면 매수 금지

SMALL_TAKE_PROFIT_P = -1                    # 작은 익절가 %
BIG_TAKE_PROFIT_P = -2                      # 큰 익절가 %

BUY_MARGIN_P = 0.5                          # ex) 최저가 + 0.5% 에서 매수

if is_simulation():
    MAX_MY_STOCK_COUNT = 10                      # MAX 보유 주식 수
    INVEST_MONEY_PER_STOCK = 2000000            # 종목 당 투자 금액(원)
else:
    MAX_MY_STOCK_COUNT = 4                      # temp, 두산로보틱스
    INVEST_MONEY_PER_STOCK = 300000            # 종목 당 투자 금액(원)

BUYABLE_GAP = 10                                # "현재가 - 매수가 GAP" 가 X% 미만 경우만 매수 가능 종목으로 처리

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

# ex) 20130414
TODAY_DATE = f"{datetime.datetime.now().strftime('%Y%m%d')}"

# 주문 구분
ORDER_TYPE_LIMIT_ORDER = "00"               # 지정가
ORDER_TYPE_MARGET_ORDER = "01"              # 시장가
ORDER_TYPE_MARKETABLE_LIMIT_ORDER = "03"    # 최유리지정가
ORDER_TYPE_IMMEDIATE_ORDER = "04"           # 최우선지정가

API_DELAY_S = 0.05                          # 초당 API 20회 제한

# 체결 미체결 구분 코드
TRADE_ANY_CODE = "00"           # 체결 미체결 전체
TRADE_DONE_CODE = "01"          # 체결
TRADE_NOT_DONE_CODE = "02"      # 미체결
    
##############################################################

class Stocks_info:
    def __init__(self) -> None:
        self.stocks = dict()                                        # 모든 종목의 정보
        self.my_stocks = dict()                                     # 보유 종목
        self.buyable_stocks = dict()                                # 매수 가능 종목
        self.config = dict()                                        # 투자 관련 설정 정보
        self.access_token = ""                  
        self.my_cash = 0                                            # 주문 가능 현금 잔고
        self.buy_1_invest_money = int(INVEST_MONEY_PER_STOCK * (BUY_1_P / 100))        # 1차 매수 금액
        self.buy_2_invest_money = int(INVEST_MONEY_PER_STOCK * (BUY_2_P / 100))        # 2차 매수 금액
        # 네이버 증권의 기업실적분석표
        self.this_year_column_text = ""                             # 2023년 기준 2023.12(E)
        self.last_year_column_text = ""                             # 2023년 기준 2022.12, 작년 데이터 얻기
        self.the_year_before_last_column_text = ""                  # 2023년 기준 2021.12, 재작년 데이터 얻기
        self.init_naver_finance_year_column_texts()
        self.trade_done_order_list = list()                         # 체결 완료 주문 list
        # self.order_num_list = list()                                # 매수/매도 주문번호 list
        # self.order_list = list()                                    # 주식 일별 주문 체결 조회 정보


    ##############################################################
    # 초기화 시 처리 할 내용
    ##############################################################
    def initialize(self):
        result = True
        msg = ""
        try:        
            self.load_stocks_info(STOCKS_INFO_FILE_PATH)
            self.init_config(CONFIG_FILE_PATH)
            self.access_token = self.get_access_token()
            self.my_cash = self.get_my_cash()       # 보유 현금 세팅
            self.init_trade_done_order_list()
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # Print and send discode
    ##############################################################
    def send_msg(self, msg, send_discode:bool = False, err:bool = False):
        result = True
        ex_msg = ""
        try:        
            now = datetime.datetime.now()
            if send_discode == True:
                # message = {"content": f"[{now.strftime('%H:%M:%S')}] {str(msg)}"}
                message = {"content": f"{msg}"}
                requests.post(self.config['DISCORD_WEBHOOK_URL'], data=message)
            if err == True:
                PRINT_ERR(f"{str(msg)}")
            else:
                PRINT_INFO(f"{str(msg)}")
        except Exception as ex:
            result = False
            ex_msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(ex_msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 네이버 증권 기업실적분석 년도 텍스트 초기화
    ##############################################################
    def init_naver_finance_year_column_texts(self):
        result = True
        msg = ""
        try:        
            annual_finance = self.crawl_naver_finance("005930")
            # 2023 기준 2023.12(E) 의 column index
            this_year_index = 3
            for i, key in enumerate(annual_finance.columns):
                if i == this_year_index:
                    self.this_year_column_text = key
                    break
                # 매출액 1년 전, 2년 전 구하기 위함
                elif i == (this_year_index - 1):
                    # 1년 전 ex) 2023 기준 2022.12
                    self.last_year_column_text = key
                elif i == (this_year_index - 2):
                    # 2년 전 ex) 2023 기준 2021.12
                    self.the_year_before_last_column_text = key
                else:
                    pass
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)        

    ##############################################################
    # stocks 에서 code 에 해당하는 stock 리턴
    ##############################################################
    def get_stock(self, code: str):
        try:
            return self.stocks[code]
        except KeyError:
            PRINT_ERR(f'KeyError : {code} is not found')
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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 1차 매수가 구하기
    ##############################################################
    def get_buy_1_price(self, code):
        result = True
        msg = ""
        try:
            buy_1_price = 0
            # 손절한 경우 1차 매수가는 set_loss_cut_done 에서 이미 구했다.
            if self.stocks[code]['loss_cut_done'] == True:
                buy_1_price = self.stocks[code]['buy_1_price']
            else:
                envelope_p = self.to_percent(self.stocks[code]['envelope_p'])
                envelope_support_line = self.stocks[code]['yesterday_20ma'] * (1 - envelope_p)
                buy_1_price = envelope_support_line * MARGIN_20MA
            return int(buy_1_price)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)    

    ##############################################################
    # 1차 매수 수량 = 1차 매수 금액 / 매수가
    ##############################################################
    def get_buy_1_qty(self, code):
        result = True
        msg = ""
        try:
            ret = 0
            if self.stocks[code]['buy_1_price'] > 0:
                # 중심선에서부터 떨어진 경우 1차 매수에 1주만 매수
                qty = int(self.buy_1_invest_money / self.stocks[code]['buy_1_price'])
                if self.is_buy_1_stocks_lowest(code) == False:
                    # "한 주당 매수 가격 < 1차 매수가격" 경우 1차 매수에 1주만 매수
                    ret = max(1, qty)
                else:
                    # 최소 수량 매수
                    ret = 1
            return ret
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg) 
                
    ##############################################################
    # 2차 매수가 = 1차 매수가 - 10%
    ##############################################################
    def get_buy_2_price(self, code):
        return int(self.stocks[code]['buy_1_price'] * 0.9)

    ##############################################################
    # 2차 매수 수량 = 2차 매수 금액 / 매수가
    ##############################################################
    def get_buy_2_qty(self, code):
        result = True
        msg = ""
        try:
            ret = 0
            if self.stocks[code]['buy_2_price'] > 0:
                ret = int(self.buy_2_invest_money / self.stocks[code]['buy_2_price'])        
            return ret
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)
    ##############################################################
    # 매수 완료 시 호출
    # Return    : None
    # Parameter :
    #       code            종목 코드
    ##############################################################
    def set_buy_done(self, code):
        result = True
        msg = ""
        try:            
            # 매수 완료됐으니 평단가, 목표가 업데이트
            self.update_my_stocks()
            
            self.stocks[code]['buy_order_done'] = False
            
            if self.stocks[code]['buy_1_done'] == False:
                # 1차 매수 안된 경우는 1차 매수 완료
                self.stocks[code]['buy_1_done'] = True
            else:
                # 2차 매수 완료 조건
                # 보유 수량 >= 1차 매수량 + 2차 매수량            
                if self.stocks[code]['stockholdings'] >= (self.stocks[code]['buy_1_qty'] + self.stocks[code]['buy_2_qty']):
                    self.stocks[code]['buy_2_done'] = True

            # 다음 매수 조건 체크위해 allow_monitoring_buy 초기화
            self.stocks[code]['allow_monitoring_buy'] = False
            # 당일 매수 당일 매도 주문, 매도 전략 1 일 때만 쓴다
            self.handle_today_buy_today_sell(code)
            self.my_cash = self.get_my_cash()
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg) 

    ##############################################################
    # 매도 완료 시 호출
    #   매도는 항상 전체 수량 매도 기반
    ##############################################################
    def set_sell_done(self, code):
        result = True
        msg = ""
        try:          
            self.stocks[code]['sell_order_done'] = False
            if SELL_STRATEGY == 3 and self.is_my_stock(code) == True:
                # 1차 반 매도 완료 상태
                self.stocks[code]['sell_1_done'] = True
                self.update_my_stocks()
                self.send_msg(f"{self.stocks[code]['name']} 일부 매도", True)
            else:
                # 전량 매도 상태는 보유 종목에 없는 상태
                if self.is_my_stock(code) == False:
                    self.stocks[code]['sell_done'] = True
                    # 매도 완료 후 종가 > 20ma 체크위해 false 처리
                    self.stocks[code]['end_price_higher_than_20ma_after_sold'] = False
                    # 보유 종목이 MAX_MY_STOCK_COUNT 인 상태에서 매도가되면 
                    # 매수 가능 상태가 될 수 있기때문에 매수 가능 종목 업데이트
                    if len(self.my_stocks) == MAX_MY_STOCK_COUNT:
                        self.update_buyable_stocks()
                    self.update_my_stocks()
                    if self.stocks[code]['loss_cut_order'] == True:
                        self.set_loss_cut_done(code)
                    else:
                        self.clear_buy_sell_info(code)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg) 

    ##############################################################
    # 손절 완료 시 호출
    #   손절가 -5% 에 1차 매수
    #   손절가 상승 돌파 시 매수?
    # Return    : None
    # Parameter :
    #       code            종목 코드
    ##############################################################
    def set_loss_cut_done(self, code):
        result = True
        msg = ""
        try:                
            self.stocks[code]['loss_cut_done'] = True
            self.stocks[code]['loss_cut_order'] = False
            # 손절 처리 경우 20일선 위로 올라오는거 체크하지 않는다
            self.stocks[code]['sell_done'] = False
            
            # 1차 매수가 = 손절가 -5% 에 1차 매수
            self.stocks[code]['buy_1_price'] = int(self.get_loss_cut_price(code) * 0.95)
            # 1차 매수 수량
            self.stocks[code]['buy_1_qty'] = self.get_buy_1_qty(code)
            # 2차 매수가
            self.stocks[code]['buy_2_price'] = self.get_buy_2_price(code)
            # 2차 매수 수량
            self.stocks[code]['buy_2_qty'] = self.get_buy_2_qty(code)
            self.stocks[code]['allow_monitoring_buy'] = False
            self.stocks[code]['allow_monitoring_sell'] = False
            self.stocks[code]['sell_1_done'] = False
            self.stocks[code]['buy_1_done'] = False
            self.stocks[code]['buy_2_done'] = False
            # 평단가
            self.stocks[code]['avg_buy_price'] = self.get_avg_buy_price(code)
            # 목표가 = 평단가에서 목표% 수익가
            self.stocks[code]['sell_target_price'] = self.get_sell_target_price(code)
            # 어제 종가
            self.stocks[code]['yesterday_end_price'] = self.get_end_price(code, 0)
            # 익절가%
            self.set_take_profit_percent(code)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg) 

    ##############################################################
    # 매도 완료등으로 매수/매도 관려 정보 초기화 시 호출
    ##############################################################
    def clear_buy_sell_info(self, code):
        result = True
        msg = ""
        try:            
            self.stocks[code]['yesterday_20ma'] = 0
            self.stocks[code]['buy_1_price'] = 0
            self.stocks[code]['buy_2_price'] = 0
            self.stocks[code]['buy_1_qty'] = 0
            self.stocks[code]['buy_2_qty'] = 0
            self.stocks[code]['buy_1_done'] = False
            self.stocks[code]['buy_2_done'] = False
            self.stocks[code]['avg_buy_price'] = 0
            self.stocks[code]['sell_target_price'] = 0
            self.stocks[code]['stockholdings'] = 0
            self.stocks[code]['allow_monitoring_buy'] = False
            self.stocks[code]['allow_monitoring_sell'] = False
            self.stocks[code]['highest_price_ever'] = 0
            self.stocks[code]['sell_1_done'] = False
            # real_avg_buy_price 은 매도 완료 후 매도 체결 조회 할 수 있기 때문에 초기화하지 않는다
            # self.stocks[code]['real_avg_buy_price'] = 0
            self.stocks[code]['envelope_p_long_ma_up'] = False
            self.stocks[code]['loss_cut_done'] = False
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 평단가 리턴
    #   단, 평단가는 실제 체결 평단가가 아니라 이론상 평단가
    #   1차 매수가 안된 경우
    #       평단가 = 1차 매수가
    #   2차 매수까지 된 경우
    #       평단가 = ((1차 매수가 * 1차 매수량) + (2차 매수가 * 2차 매수량)) / (1차 + 2차 매수량)
    ##############################################################
    def get_avg_buy_price(self, code):
        result = True
        msg = ""
        try:            
            if self.stocks[code]['buy_1_done'] == True and self.stocks[code]['buy_2_done'] == True:
                # 2차 매수까지 된 경우
                tot_buy_1_money = self.stocks[code]['buy_1_price'] * self.stocks[code]['buy_1_qty']
                tot_buy_2_money = self.stocks[code]['buy_2_price'] * self.stocks[code]['buy_2_qty']
                tot_buy_qty = self.stocks[code]['buy_1_qty'] + self.stocks[code]['buy_2_qty']
                if tot_buy_qty > 0:
                    avg_buy_price = int((tot_buy_1_money + tot_buy_2_money) / tot_buy_qty)
            else:
                # 1차 매수만 됐거나 1차 매수도 안된 경우
                avg_buy_price = self.stocks[code]['buy_1_price']
            return avg_buy_price
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 목표가 = 평단가 * (1 + 목표%)
    ##############################################################
    def get_sell_target_price(self, code):
        result = True
        msg = ""
        try:            
            sell_target_p = self.to_percent(self.stocks[code]['sell_target_p'])        
            return int(self.stocks[code]['avg_buy_price'] * (1 + sell_target_p))
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
    # 주식현재가 시세 리턴
    #   return : 성공 시 요청한 시세, 실패 시 0 리턴
    #   Parameter :
    #       code            종목 코드
    #       type            요청 시세(현재가, 시가, 고가, ...)
    ##############################################################
    def get_price(self, code:str, type:str):
        result = True
        msg = ""
        try:            
            price = 0
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
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                price = int(float(res.json()['output'][type]))
            else:
                self.send_msg(f"[get_price failed]{str(res.json())}")
            time.sleep(API_DELAY_S * 2) # * 2 to fix max retries exceeded
            return price
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수가 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수가 리턴
    #   2차 매수까지 완료면 0 리턴
    ##############################################################
    def get_buy_target_price(self, code):
        result = True
        msg = ""
        try:            
            if self.stocks[code]['buy_1_done'] == False:
                # 1차 매수
                buy_target_price = self.stocks[code]['buy_1_price']
            elif self.stocks[code]['buy_2_done'] == False:
                # 2차 매수
                buy_target_price = self.stocks[code]['buy_2_price']
            else:
                # 2차 매수까지 완료 상태
                buy_target_price = 0
            return buy_target_price
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수 수량 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수 수량 리턴
    #   2차 매수까지 완료면 0 리턴
    ##############################################################
    def get_buy_target_qty(self, code):
        result = True
        msg = ""
        try:            
            if self.stocks[code]['buy_1_done'] == False:
                # 1차 매수
                buy_target_qty = self.stocks[code]['buy_1_qty']
            elif self.stocks[code]['buy_2_done'] == False:
                # 2차 매수
                buy_target_qty = self.stocks[code]['buy_2_qty']
            else:
                # 2차 매수까지 완료 상태
                buy_target_qty = 0
            return buy_target_qty
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            result = soup.select_one(selector).text
            return result
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            res = requests.get(URL, headers=headers, params=params)
            total_stock_count = 0
            if self.is_request_ok(res) == True:
                # 현재 PER
                self.stocks[code]['PER'] = float(res.json()['output']['per'])
                total_stock_count = int(res.json()['output']['lstn_stcn'])     # 상장 주식 수
            else:
                self.send_msg(f"[update_stock_invest_info failed]{str(res.json())}")

            annual_finance = self.crawl_naver_finance(code)
            # PER_E, EPS, BPS, ROE 는 2013.12(E) 기준
            self.stocks[code]['PER_E'] = float(annual_finance[self.this_year_column_text]['PER(배)'])
            self.stocks[code]['EPS_E'] = int(annual_finance[self.this_year_column_text]['EPS(원)'])
            self.stocks[code]['BPS_E'] = int(annual_finance[self.this_year_column_text]['BPS(원)'])
            self.stocks[code]['ROE_E'] = float(annual_finance[self.this_year_column_text]['ROE(지배주주)'])
            self.stocks[code]['industry_PER'] = float(self.crawl_naver_finance_by_selector(code, "#tab_con1 > div:nth-child(6) > table > tbody > tr.strong > td > em"))
            self.stocks[code]['operating_profit_margin_p'] = float(annual_finance[self.this_year_column_text]['영업이익률'])
            self.stocks[code]['sales_income'] = int(annual_finance[self.this_year_column_text]['매출액'])                   # 올해 예상 매출액, 억원
            self.stocks[code]['last_year_sales_income'] = int(annual_finance[self.last_year_column_text]['매출액'])         # 작년 매출액, 억원
            self.stocks[code]['the_year_before_last_sales_income'] = int(annual_finance[self.the_year_before_last_column_text]['매출액'])       # 재작년 매출액, 억원
            self.stocks[code]['curr_profit'] = int(annual_finance[self.this_year_column_text]['당기순이익'])
            # 목표 주가 = 미래 당기순이익(원) * PER_E / 상장주식수
            if total_stock_count > 0:
                self.stocks[code]['max_target_price'] = int((self.stocks[code]['curr_profit'] * 100000000) * self.stocks[code]['PER_E'] / total_stock_count)
            # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가
            # + : 저평가
            # - : 고평가
            if self.stocks[code]['sell_target_price'] > 0:
                self.stocks[code]['gap_max_sell_target_price_p'] = int(100 * (self.stocks[code]['max_target_price'] - self.stocks[code]['sell_target_price']) / self.stocks[code]['sell_target_price'])
            self.set_stock_undervalue(code)
            time.sleep(API_DELAY_S)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            for code in self.stocks.keys():
                PRINT_INFO(f"{self.stocks[code]['name']}")
                # 순서 변경 금지
                # ex) 목표가를 구하기 위해선 평단가가 먼저 있어야한다
                # yesterday 20일선
                # 15:30 장마감 후는 금일기준으로 20일선 구한다
                if t_exit < t_now:
                    past_day = 0        # 장마감 후는 금일 기준
                else:
                    past_day = 1        # 어제 기준
                self.stocks[code]['yesterday_20ma'] = self.get_ma(code, 20, past_day)
                # 1차 매수가
                self.stocks[code]['buy_1_price'] = self.get_buy_1_price(code)
                # 1차 매수 수량
                self.stocks[code]['buy_1_qty'] = self.get_buy_1_qty(code)
                # 2차 매수가
                self.stocks[code]['buy_2_price'] = self.get_buy_2_price(code)
                # 2차 매수 수량
                self.stocks[code]['buy_2_qty'] = self.get_buy_2_qty(code)
                # # 손절가
                # self.stocks[code]['loss_cut_price'] = self.get_loss_cut_price(code)
                # 어제 종가
                self.stocks[code]['yesterday_end_price'] = self.get_end_price(code, past_day)

                # 어제 종가 > 어제 20ma 인가
                if self.stocks[code]['sell_done'] == True:
                    # 어제 종가 > 어제 20ma
                    if self.stocks[code]['yesterday_end_price'] > self.stocks[code]['yesterday_20ma']:
                        # 재매수 가능
                        self.stocks[code]['end_price_higher_than_20ma_after_sold'] = True
                        self.stocks[code]['sell_done'] = False
                
                # 평단가
                self.stocks[code]['avg_buy_price'] = self.get_avg_buy_price(code)
                # 목표가 = 평단가에서 목표% 수익가
                self.stocks[code]['sell_target_price'] = self.get_sell_target_price(code)
                # 익절가
                self.set_take_profit_percent(code)

                # 주식 투자 정보 업데이트(시가 총액, 상장 주식 수, 저평가, BPS, PER, EPS)
                self.update_stock_invest_info(code)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                stocks = res.json()['output1']
                self.my_stocks.clear()
                for stock in stocks:
                    if int(stock['hldg_qty']) > 0:
                        code = stock['pdno']
                        # DB 에 없는 종목 제외 ex) 공모주
                        if code in self.stocks.keys():
                            # 보유 수량
                            self.stocks[code]['stockholdings'] = int(stock['hldg_qty'])
                            # 평단가
                            self.stocks[code]['avg_buy_price'] = self.get_avg_buy_price(code)
                            # 계좌내 실제 평단가
                            # avg_buy_price 는 목표가 계산을 위한 이론적 평단가
                            self.stocks[code]['real_avg_buy_price'] = int(float(stock['pchs_avg_pric']))
                            # 목표가 = 평단가에서 목표% 수익가
                            self.stocks[code]['sell_target_price'] = self.get_sell_target_price(self.stocks[code]['code'])
                            # self.my_stocks 업데이트
                            temp_stock = copy.deepcopy({code: self.stocks[code]})
                            self.my_stocks[code] = temp_stock[code]
                        else:
                            # 보유는 하지만 DB 에 없는 종목
                            # self.send_msg(f"DB 에 없는 종목({stock['prdt_name']})은 업데이트 skip")
                            pass
                result = True
            else:
                self.send_msg_err(f"[계좌 조회 실패]{str(res.json())}")
                result = False
            time.sleep(API_DELAY_S)
            return result
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수가능 주식 수 리턴
    #   보유 현금 / 종목당 매수 금액
    #   ex) 총 보유금액이 300만원이고 종목당 총 100만원 매수 시 총 2종목 매수
    ##############################################################
    def get_available_buy_stock_count(self):
        result = True
        msg = ""
        try:
            result = 0
            if INVEST_MONEY_PER_STOCK > 0:
                result = int(self.my_cash / INVEST_MONEY_PER_STOCK)
            return result
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)
    ##############################################################
    # 보유 주식인지 체크
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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수 여부 판단
    ##############################################################
    def is_ok_to_buy(self, code):
        result = True
        msg = ""
        try:
            # # 오늘 주문 완료 시 금지
            # if self.already_ordered(code, BUY_CODE) == True:
            #     return False

            # # 2차 매수까지 완료 시 금지
            # if self.stocks[code]['buy_2_done'] == True:
            #     return False

            # # 보유현금에 맞게 종목개수 매수
            # #   ex) 총 보유금액이 300만원이고 종목당 총 100만원 매수 시 총 2종목 매수
            # if (self.get_available_buy_stock_count() == 0 or len(self.my_stocks) >= MAX_MY_STOCK_COUNT) and self.is_my_stock(code) == False:
            #     return False
            
            # return True    # test
        
            # 2차 매수까지 완료 시 금지
            if self.stocks[code]['buy_2_done'] == True:
                return False

            # 저평가 조건(X미만 매수 금지)
            if self.stocks[code]['undervalue'] < UNDER_VALUE:
                return False
            
            # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가 < X% 미만 매수 금지
            if self.stocks[code]['gap_max_sell_target_price_p'] < GAP_MAX_SELL_TARGET_PRICE_P:
                return False

            # 저평가 + 목표주가GAP < X 미만 매수 금지
            if (self.stocks[code]['undervalue'] + self.stocks[code]['gap_max_sell_target_price_p']) < SUM_UNDER_VALUE_SELL_TARGET_GAP:
                return False
            
            # PER 매수 금지
            if self.stocks[code]['PER'] < 0 or self.stocks[code]['PER'] >= MAX_PER or self.stocks[code]['PER_E'] < 0 or self.stocks[code]['PER'] >= self.stocks[code]['industry_PER'] * 2:
                return False
            
            # EPS_E 매수 금지
            if self.stocks[code]['EPS_E'] < 0:
                return False

            # 보유현금에 맞게 종목개수 매수
            #   ex) 총 보유금액이 300만원이고 종목당 총 100만원 매수 시 총 2종목 매수
            if (self.get_available_buy_stock_count() == 0 or len(self.my_stocks) >= MAX_MY_STOCK_COUNT) and self.is_my_stock(code) == False:
                return False
            
            # 매도 후 종가 > 20ma 체크
            if self.stocks[code]['sell_done'] == True:
                # 어제 종가 <= 어제 20ma 상태면 매수 금지
                if self.stocks[code]['end_price_higher_than_20ma_after_sold'] == False:
                    return False
            else:
                pass

            # 오늘 주문 완료 시 금지
            if self.already_ordered(code, BUY_CODE) == True:
                return False
            
            return True
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # X일선 가격 리턴
    # param :
    #   code            종목 코드
    #   days            X일선
    #                   ex) 20일선 : 20, 5일선 : 5
    #   past_day        X일선 가격 기준
    #                   ex) 0 : 금일 X일선, 1 : 어제 X일선
    #   period          D : 일, W : 주, M : 월
    ##############################################################
    def get_ma(self, code: str, days=20, past_day=0, period="D"):
        result = True
        msg = ""
        try:            
            PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-price"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": "FHKST01010400"}
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": code,
                # 0 : 수정주가반영, 1 : 수정주가미반영
                "fid_org_adj_prc": "0",
                # D : (일)최근 30거래일
                # W : (주)최근 30주
                # M : (월)최근 30개월
                "fid_period_div_code": period
            }
            res = requests.get(URL, headers=headers, params=params)

            # x일 이평선 구하기 위해 x일간의 종가 구한다
            days_last = past_day + days
            sum_end_price = 0
            for i in range(past_day, days_last):
                end_price = int(res.json()['output'][i]['stck_clpr'])   # 종가
                sum_end_price = sum_end_price + end_price               # 종가 합

            value_ma = sum_end_price / days                           # x일선 가격
            time.sleep(API_DELAY_S)
            return int(value_ma)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            if past_day > 30:
                PRINT_INFO(f'can read 30 datas. make {past_day} to 30')
                past_day = 30
                
            PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-price"
            URL = f"{self.config['URL_BASE']}/{PATH}"
            headers = {"Content-Type": "application/json",
                    "authorization": f"Bearer {self.access_token}",
                    "appKey": self.config['APP_KEY'],
                    "appSecret": self.config['APP_SECRET'],
                    "tr_id": "FHKST01010400"}
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": code,
                # 0 : 수정주가반영, 1 : 수정주가미반영
                "fid_org_adj_prc": "0",
                # D : (일)최근 30거래일
                # W : (주)최근 30주
                # M : (월)최근 30개월
                "fid_period_div_code": "D"
            }
            res = requests.get(URL, headers=headers, params=params)
            time.sleep(API_DELAY_S)
            return int(res.json()['output'][past_day]['stck_clpr'])   # 종가
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            res = requests.post(URL, headers=headers, data=json.dumps(body))
            return res.json()["access_token"]
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            res = requests.post(URL, headers=headers, data=json.dumps(datas))
            hashkey = res.json()["HASH"]
            return hashkey
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)
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
            res = requests.get(URL, headers=headers, params=params)
            stock_list = res.json()['output1']
            evaluation = res.json()['output2']
            data = {'종목명':[], '수량':[], '수익률(%)':[], '평가금액':[], '손익금액':[], '평단가':[], '현재가':[], '목표가':[], '손절가':[]}
            self.send_msg(f"==========주식 보유잔고==========", send_discode)
            for stock in stock_list:
                if int(stock['hldg_qty']) > 0:
                    data['종목명'].append(stock['prdt_name'])
                    data['수량'].append(stock['hldg_qty'])
                    data['수익률(%)'].append(float(stock['evlu_pfls_rt']))
                    data['평가금액'].append(int(stock['evlu_amt']))
                    data['손익금액'].append(stock['evlu_pfls_amt'])
                    data['평단가'].append(int(float(stock['pchs_avg_pric'])))
                    data['현재가'].append(int(stock['prpr']))
                    # DB 에 없는 종목 제외 ex) 공모주
                    code = stock['pdno']
                    if code in self.stocks.keys():
                        data['목표가'].append(int(self.stocks[code]['sell_target_price']))
                        data['손절가'].append(int(self.get_loss_cut_price(code)))
                    else:
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
            time.sleep(API_DELAY_S)
            return stock_list
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 현금 잔고 조회
    ##############################################################
    def get_my_cash(self):
        result = True
        msg = ""
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
            res = requests.get(URL, headers=headers, params=params)
            cash = res.json()['output']['ord_psbl_cash']
            # self.send_msg(f"주문 가능 현금 잔고: {cash}원")
            time.sleep(API_DELAY_S)
            return int(cash)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            if self.is_request_ok(res) == True:
                self.send_msg(f"[매수 주문 성공] [{self.stocks[code]['name']}] {price}원 {qty}주")
                result = True
            else:
                self.send_msg_err(f"[매수 주문 실패] [{self.stocks[code]['name']}] {price}원 {qty}주 type:{order_type} {str(res.json())}")
                result = False

            time.sleep(API_DELAY_S)
            return result
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매도
    #   return : 성공 시 True , 실패 시 False
    #   param :
    #       code            종목 코드
    #       price           매도 가격
    #       qty             매도 수량
    #       order_type      매도 타입(지정가, 최유리지정가,...)
    ##############################################################
    def sell(self, code: str, price: str, qty: str, order_type:str = ORDER_TYPE_LIMIT_ORDER):
        result = True
        msg = ""
        try:            
            ret = False
            
            # 지정가 이외의 주문은 가격을 0으로 해야 주문 실패하지 않는다.
            # 업체 : 장전 시간외, 장후 시간외, 시장가 등 모든 주문구분의 경우 1주당 가격을 공란으로 비우지 않고
            # "0"으로 입력 권고드리고 있습니다.
            if order_type != ORDER_TYPE_LIMIT_ORDER:
                price = 0
                            
            # 시장가 주문은 조건 안따진다
            if order_type != ORDER_TYPE_MARGET_ORDER:
                # 오늘 주문 완료 시 금지
                if self.already_ordered(code, SELL_CODE) == True:
                    return False
                
                if self.stocks[code]['allow_monitoring_sell'] == False:
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
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            if self.is_request_ok(res) == True:
                self.send_msg(f"[매도 주문 성공] [{self.stocks[code]['name']}] {price}원 {qty}주")
                ret = True
            else:
                self.send_msg_err(f"[매도 주문 실패] [{self.stocks[code]['name']}] {price}원 {qty}주 {str(res.json())}")
                ret = False
                
            time.sleep(API_DELAY_S)
            return ret
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 금일 매수 주식 매도 주문
    #   동일 주식 매도 주문 있으면 주문 취소 후 새 목표가로 매도 주문
    #   없으면 1차 목표가로 매도
    # Return    : None
    # Parameter :
    #       code                    종목 코드
    ##############################################################
    def handle_today_buy_today_sell(self, code):
        result = True
        msg = ""
        try:            
            if SELL_STRATEGY == 1:
                # 보유수량, 목표가 업데이트
                self.update_my_stocks()
                # 보유 주식인 경우만 매도 처리
                if code in self.my_stocks.keys():
                    if self.already_ordered(code, SELL_CODE) == True:
                        if self.cancel_order(code, SELL_CODE) == True:
                            if self.sell(code, self.stocks[code]['sell_target_price'], self.stocks[code]['stockholdings']) == True:
                                self.set_order_done(code, SELL_CODE)
                    else:
                        if self.sell(code, self.stocks[code]['sell_target_price'], self.stocks[code]['stockholdings']) == True:
                            self.set_order_done(code, SELL_CODE)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수 처리
    #   전략 1 :
    #       현재가 <= 매수가면 매수
    #       단, 현재가 - 1% <= 매수가 매수가에 미리 매수 주문
    #   전략 2 :
    #       현재가 < 매수가 된적이 있는 상태에서 
    #       (현재가 >= 저가+x% or 현재가 >= 매수가 + y%)면 최우선지정가 매수
    ##############################################################
    def handle_buy_stock(self):
        result = True
        msg = ""
        try:            
            if BUY_STRATEGY == 1:
                # 전략 1 : 현재가 <= 매수가면 매수
                # 매수 가능 종목내에서만 매수
                for code in self.buyable_stocks.keys():
                    curr_price = self.get_curr_price(code)
                    if curr_price == 0:
                        continue
                    buy_target_price = self.get_buy_target_price(code)
                    buy_target_qty = self.get_buy_target_qty(code)
                    if curr_price > 0 and buy_target_price > 0:                
                        if curr_price * 0.99 <= buy_target_price:
                            if self.buy(code, buy_target_price, buy_target_qty) == True:
                                self.set_order_done(code, BUY_CODE)
                                self.show_order_list()
            elif BUY_STRATEGY == 2:
                # 전략 2 : 현재가 < 매수가 된적이 있는 상태에서 (현재가 >= 저가+x% or 현재가 >= 매수가 + y%)면 최우선지정가 매수
                # 매수 가능 종목내에서만 매수
                for code in self.buyable_stocks.keys():
                    curr_price = self.get_curr_price(code)
                    if curr_price == 0:
                        continue

                    if self.stocks[code]['allow_monitoring_buy'] == False:
                        # 목표가 왔다 -> 매수 감시 시작
                        buy_target_price = self.get_buy_target_price(code)
                        if curr_price < buy_target_price:
                            self.send_msg(f"[{self.stocks[code]['name']}] 매수 감시 시작, 현재가 : {curr_price}, 매수 목표가 : {buy_target_price}")
                            self.stocks[code]['allow_monitoring_buy'] = True                        
                    else:
                        # 현재가 >= 저가 or 목표가 + BUY_MARGIN_P% 에서 매수
                        lowest_price = self.get_lowest_price(code)
                        buy_margin = 1 + self.to_percent(BUY_MARGIN_P)
                        if (lowest_price > 0) and curr_price >= (lowest_price * buy_margin):
                            # 1차 매수 상태에서 allow_monitoring_buy 가 false 안된 상태에서 2차 매수 들어갈 때
                            # 1차 매수 반복되는 문제 수정
                            buy_target_price = self.get_buy_target_price(code)
                            if lowest_price <= buy_target_price:
                                buy_target_qty = self.get_buy_target_qty(code)
                                if self.buy(code, curr_price, buy_target_qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                    self.set_order_done(code, BUY_CODE)
                                    self.send_msg(f"[{self.stocks[code]['name']}] 매수 주문, 현재가 : {curr_price} >= {lowest_price * buy_margin}(저가 : {lowest_price} * {buy_margin})")
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매도 처리
    #   전략 1 : 목표가에 매도
    #   전략 2 : 현재가 >= 목표가 된적이 있는 상태에서 (현재가 <= 여지껏 고가 - x% or 현재가 <= 목표가 - y%)면 최우선지정가 매도
    #   TODO 수익 극대화
    #       RSI 기간20,시그널9, 30/70 => 과열 시작 다음날 매도
    ##############################################################
    def handle_sell_stock(self, order_type:str = ORDER_TYPE_LIMIT_ORDER):
        result = True
        msg = ""
        try:            
            # # test 시장가 매도 처리
            # if order_type == ORDER_TYPE_MARGET_ORDER:
            #     for code in self.my_stocks.keys():
            #         if self.sell(code, self.my_stocks[code]['sell_target_price'], self.my_stocks[code]['stockholdings'], order_type) == True:
            #             self.set_order_done(code, SELL_CODE)
            #     return
            
            if SELL_STRATEGY == 1:
                # 전략 1 : 목표가에 매도
                for code in self.my_stocks.keys():
                    if self.sell(code, self.my_stocks[code]['sell_target_price'], self.my_stocks[code]['stockholdings'], order_type) == True:
                        self.set_order_done(code, SELL_CODE)
            elif SELL_STRATEGY == 2:
                # 전략 2 : 현재가 >= 목표가 된적이 있는 상태에서 (현재가 <= 여지껏 고가 - x% or 현재가 <= 목표가 - y%)면 최우선지정가 매도
                for code in self.my_stocks.keys():
                    curr_price = self.get_curr_price(code)
                    if curr_price == 0:
                        continue
                    sell_target_price = self.my_stocks[code]['sell_target_price']

                    if self.stocks[code]['allow_monitoring_sell'] == False:
                        if curr_price >= sell_target_price:
                            self.send_msg(f"[{self.stocks[code]['name']}] 매도 감시 시작, 현재가 : {curr_price}, 매도 목표가 : {sell_target_price}")
                            self.stocks[code]['allow_monitoring_sell'] = True
                    else:
                        # 익절가 이하 시 매도
                        take_profit_price = self.get_take_profit_price(code)
                        if (take_profit_price > 0 and curr_price <= take_profit_price):
                            if self.sell(code, curr_price, self.my_stocks[code]['stockholdings'], ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                self.set_order_done(code, SELL_CODE)
                                self.send_msg(f"[{self.stocks[code]['name']}] 매도 주문, 현재가 : {curr_price} <= take profit : {take_profit_price}")
            # 전략 3 : 목표가에 반 매도(2전략 트레일링스탑). 단, 매도가가 5일선 이하면 전량 매도
            #       나머지는 15:15이후 현재가가 5일선 or 목표가 이탈 시 매도                        
            elif SELL_STRATEGY == 3:
                for code in self.my_stocks.keys():
                    curr_price = self.get_curr_price(code)
                    if curr_price == 0:
                        continue
                    
                    if self.stocks[code]['sell_1_done'] == False:
                        # 하나도 매도 안된 상태
                        sell_target_price = self.my_stocks[code]['sell_target_price']

                        if self.stocks[code]['allow_monitoring_sell'] == False:
                            # 목표가 왔다 -> 매도 감시 시작
                            if curr_price >= sell_target_price:
                                self.send_msg(f"[{self.stocks[code]['name']}] 매도 감시 시작, 현재가 : {curr_price}, 매도 목표가 : {sell_target_price}")
                                self.stocks[code]['allow_monitoring_sell'] = True
                        else:
                            # 익절가 이하 시 매도
                            take_profit_price = self.get_take_profit_price(code)
                            if (take_profit_price > 0 and curr_price <= take_profit_price):
                                # 매도가가 5일선 이하면 전량 매도
                                ma_5 = self.get_ma(code, 5)
                                if curr_price <= ma_5:
                                    qty = self.my_stocks[code]['stockholdings']
                                else:
                                    if self.my_stocks[code]['stockholdings'] == 1:
                                        qty = self.my_stocks[code]['stockholdings']
                                    else:
                                        qty = int(self.my_stocks[code]['stockholdings'] / 2)
                                if self.sell(code, curr_price, qty, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                    self.set_order_done(code, SELL_CODE)
                                    self.send_msg(f"[{self.stocks[code]['name']}] 매도 주문, 현재가 : {curr_price} <= take profit : {take_profit_price}")
                    else:
                        # 반 매도된 상태에서 나머지는 15:15 이후 현재가가 5일선 미만 경우 전량 매도   
                        t_now = datetime.datetime.now()
                        t_sell = t_now.replace(hour=15, minute=15, second=0, microsecond=0)
                        ma_5 = self.get_ma(code, 5)
                        sell_target_price = self.my_stocks[code]['sell_target_price']
                        if t_now >= t_sell:
                            # 15:15 이후 현재가가 5일선 or 목표가 이탈 시 매도
                            if curr_price < ma_5 or curr_price <= sell_target_price:
                                if self.sell(code, curr_price, self.my_stocks[code]['stockholdings'], ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                    self.set_order_done(code, SELL_CODE)
                                    if curr_price < ma_5:
                                        self.send_msg(f"[{self.stocks[code]['name']}] 매도 주문, 현재가 : {curr_price} < 5일선 : {ma_5}")
                                    else:
                                        self.send_msg(f"[{self.stocks[code]['name']}] 매도 주문, 현재가 : {curr_price} <= 목표가 : {sell_target_price}")
                        else:
                            # 15:15 이전에는 5일선 -1% 이탈 시 매도
                            if curr_price < ma_5 * 0.99 or curr_price <= sell_target_price:
                                if self.sell(code, curr_price, self.my_stocks[code]['stockholdings'], ORDER_TYPE_IMMEDIATE_ORDER) == True:
                                    self.set_order_done(code, SELL_CODE)
                                    if curr_price < ma_5 * 0.99:
                                        self.send_msg(f"[{self.stocks[code]['name']}] 매도 주문, 현재가 : {curr_price} < 5일선 - 1% 이탈 : {ma_5 * 0.99}")
                                    else:
                                        self.send_msg(f"[{self.stocks[code]['name']}] 매도 주문, 현재가 : {curr_price} <= 목표가 : {sell_target_price}")
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
                self.send_msg(f"[cancel_order failed] [{self.stocks[code]['name']}] {buy_sell}")
                ret = False
                
            time.sleep(API_DELAY_S)
            return ret
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수/매도 체결 여부 체크
    # Return    : 주문 수량 전체 체결 시 True, 아니면 False
    #               이미 체결 완료된 주문이면 return False
    # Parameter :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    ##############################################################
    def check_trade_done(self, code, buy_sell: str):
        result = True
        msg = ""
        try:            
            # # 이미 체결 완료 처리한 주문은 재처리 금지
            # result, order_num = self.get_order_num(code, buy_sell)
            # if result == True:
            #     if order_num in self.trade_done_order_list:
            #         return False
            # else:
            #     return False
            
            order_list = self.get_order_list()
            for stock in order_list:
                if stock['pdno'] == code:
                    # 이미 체결 완료 처리한 주문은 재처리 금지
                    if stock['odno'] in self.trade_done_order_list:
                        return False

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
                                # 매도 체결 완료 시, 손익, 수익률 표시
                                gain_loss_money = (int(stock['avg_prvs']) - self.stocks[code]['real_avg_buy_price']) * int(stock['tot_ccld_qty'])
                                if self.stocks[code]['real_avg_buy_price'] > 0:
                                    gain_loss_p = round(float((int(stock['avg_prvs']) - self.stocks[code]['real_avg_buy_price']) / self.stocks[code]['real_avg_buy_price']) * 100, 2)     # 소스 3째 자리에서 반올림                  
                                    self.send_msg(f"[{stock['prdt_name']}] {stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {buy_sell_order} 전량 체결 완료, 손익:{gain_loss_money} {gain_loss_p}%", True)
                            else:
                                # # 1차 매수 완료된 상태에서 프로그램 재실행 시 2차 매수로 처리되는 문제
                                # # 1차 매수 완료 상태에서 주문 단가 <= 2차 매수 예정가
                                # if order_price <= self.stocks[code]['buy_2_price'] and self.stocks[code]['buy_1_done'] == True:
                                #     nth_buy = 2
                                # else:
                                #     nth_buy = 1
                                if self.stocks[code]['buy_1_done'] == False:
                                    nth_buy = 1
                                elif self.stocks[code]['buy_2_done'] == False:
                                    nth_buy = 2
                                self.send_msg(f"[{stock['prdt_name']}] {stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {nth_buy}차 {buy_sell_order} 전량 체결 완료", True)
                            # 체결 완료 체크한 주문은 다시 체크하지 않는다
                            # while loop 에서 반복적으로 체크하는거 방지
                            self.trade_done_order_list.append(stock['odno'])
                            return True
                        elif tot_trade_qty == 0:
                            # 미체결
                            return False                
                        elif order_qty > tot_trade_qty:
                            # 일부 체결
                            if self.stocks[code]['stockholdings'] < tot_trade_qty:
                                self.send_msg(f"[{stock['prdt_name']}] {stock['avg_prvs']}원 {tot_trade_qty}/{order_qty}주 {buy_sell_order} 체결", True)
                            return False
                else:
                    # 해당 종목 아님
                    pass
            return result
        except Exception as ex:
            msg = "Exception {}".format(ex)
            PRINT_ERR(msg)
            return False

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
            for stock in order_list:
                code = stock['pdno']
                buy_sell = stock['sll_buy_dvsn_cd']
                if self.check_trade_done(code, buy_sell) == True:
                    is_trade_done = True
                    if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                        self.set_buy_done(code)
                    else:
                        self.set_sell_done(code)
            
            # 여러 종목 체결되도 결과는 한 번만 출력
            if is_trade_done == True:
                self.show_trade_done_stocks(buy_sell)
                # 계좌 잔고 조회
                self.get_stock_balance()
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 주식 일별 주문 체결 조회 종목 정보 리턴
    ##############################################################
    def get_order_list(self):
        result = True
        msg = ""
        try:            
            order_list = list()
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
                "SLL_BUY_DVSN_CD": "00",    # 전체
                "INQR_DVSN": "00",
                "PDNO": "",                 # 전체
                "CCLD_DVSN": "00",          # 전체 : 체결, 미체결 조회
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                order_list = res.json()['output1']
            else:
                self.send_msg(f"[update_order_list failed]{str(res.json())}")
                
            time.sleep(API_DELAY_S)
            return order_list
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 주문 조회
    #   전량 체결 완료 주문은 제외
    ##############################################################
    def show_order_list(self):
        result = True
        msg = ""
        try:            
            self.send_msg(f"============주문 조회============")
            order_list = self.get_order_list()
            for stock in order_list:
                # 주문 수량
                order_qty = int(stock['ord_qty'])
                # 총 체결 수량
                tot_trade_qty = int(stock['tot_ccld_qty'])
                # 전량 체결 완료 주문은 제외
                if order_qty > tot_trade_qty:
                    if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                        buy_sell_order = "매수 주문"
                    else:
                        buy_sell_order = "매도 주문"
                    curr_price = self.get_curr_price(stock['pdno'])            
                    self.send_msg(f"{stock['prdt_name']} {buy_sell_order} {stock['ord_unpr']}원 {stock['ord_qty']}주, 현재가 {curr_price}원")
            self.send_msg(f"=================================\n")
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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

            self.send_msg(f"========={buy_sell_order} 체결 조회=========")
            order_list = self.get_order_list()
            for stock in order_list:
                if int(stock['tot_ccld_qty']) > 0:
                    code = stock['pdno']
                    if buy_sell == stock['sll_buy_dvsn_cd']:
                        gain_loss_p = 0
                        if buy_sell == SELL_CODE:
                            gain_loss_money = (int(stock['avg_prvs']) - self.stocks[code]['real_avg_buy_price']) * int(stock['tot_ccld_qty'])
                            if self.stocks[code]['real_avg_buy_price'] > 0:
                                gain_loss_p = round(float((int(stock['avg_prvs']) - self.stocks[code]['real_avg_buy_price']) / self.stocks[code]['real_avg_buy_price']) * 100, 2)     # 소스 3째 자리에서 반올림                  
                        
                        curr_price = self.get_curr_price(code)
                        
                        data['종목명'].append(stock['prdt_name'])
                        data['매수/매도'].append(buy_sell_order)
                        data['체결평균가'].append(int(float(stock['avg_prvs'])))
                        if buy_sell == SELL_CODE:
                            data['평단가'].append(self.stocks[code]['real_avg_buy_price'])
                            data['손익'].append(gain_loss_money)
                            data['수익률(%)'].append(gain_loss_p)
                        data['수량'].append(stock['tot_ccld_qty'])
                        data['현재가'].append(curr_price)

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'r'  # 우측 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            self.send_msg(table)
            return None
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 저평가 높은 순으로 출력
    ##############################################################
    def show_stocks_by_undervalue(self):
        result = True
        msg = ""
        try:                
            temp_stocks = copy.deepcopy(self.stocks)
            sorted_data = dict(sorted(temp_stocks.items(), key=lambda x: x[1]['undervalue'], reverse=True))
            data = {'종목명':[], '저평가':[], '목표주가GAP':[], 'PER':[]}
            for code in sorted_data.keys():
                data['종목명'].append(sorted_data[code]['name'])
                data['저평가'].append(sorted_data[code]['undervalue'])
                data['목표주가GAP'].append(sorted_data[code]['gap_max_sell_target_price_p'])
                data['PER'].append(sorted_data[code]['PER'])

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'c'  # 가운데 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            
            self.send_msg(table)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 금일 매수/매도 체결 완료된 주문번호로 trade_done_order_list 초기화
    ##############################################################    
    def init_trade_done_order_list(self):
        result = True
        msg = ""
        try:                
            self.trade_done_order_list.clear()
            order_list = self.get_order_list()
            for stock in order_list:
                # 주문 수량
                order_qty = int(stock['ord_qty'])
                # 총 체결 수량
                tot_trade_qty = int(stock['tot_ccld_qty'])
                if tot_trade_qty == order_qty:
                    # 체결 완료 주문 번호
                    self.trade_done_order_list.append(stock['odno'])
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    # ##############################################################
    # # 금일 매수/매도 주문 order_num_list 초기화
    # ##############################################################    
    # def init_order_num_list(self):
    #     self.order_num_list.clear()
    #     for stock in self.order_list:
    #         # 주문 번호
    #         self.order_num_list.append(stock['odno'])        

    ##############################################################
    # 손절가
    #   2차 매수가 -x%
    ##############################################################
    def get_loss_cut_price(self, code):
        result = True
        msg = ""
        try:                
            return int(self.stocks[code]['buy_2_price'] * (1 - self.to_percent(LOSS_CUT_P)))
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 손절 처리
    #   현재가 < 손절가 면 손절 처리
    ##############################################################
    def handle_loss_cut(self):
        result = True
        msg = ""
        try:                
            for code in self.my_stocks.keys():
                curr_price = self.get_curr_price(code)
                if curr_price == 0:
                    continue
                loss_cut_price = self.get_loss_cut_price(code)
                # # test
                # if code == "009150":
                #     self.stocks[code]['allow_monitoring_sell'] = True
                #     stockholdings = self.stocks[code]['stockholdings']
                #     if self.sell(code, curr_price, stockholdings, ORDER_TYPE_MARGET_ORDER) == True:
                #         self.send_msg(f"손절 주문 성공")
                #         self.set_order_done(code, SELL_CODE)
                #         self.stocks[code]['loss_cut_order'] = True

                if curr_price < loss_cut_price:
                    if self.already_ordered(code, SELL_CODE):
                        # 기존 매도 주문 취소
                        if self.cancel_order(code, SELL_CODE) == False:
                            continue

                    # 손절 처리(최우선지정가로 주문)
                    self.stocks[code]['allow_monitoring_sell'] = True
                    stockholdings = self.stocks[code]['stockholdings']
                    if self.sell(code, curr_price, stockholdings, ORDER_TYPE_IMMEDIATE_ORDER) == True:
                        self.send_msg(f"손절 주문 성공")
                        self.set_order_done(code, SELL_CODE)
                        self.stocks[code]['loss_cut_order'] = True
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수 가능 종목 업데이트
    #   2차 매수 완료 종목은 제외
    #   저평가, 목표주가GAP, 현재가-매수가GAP
    ##############################################################
    def update_buyable_stocks(self):
        result = True
        msg = ""
        try: 
            self.buyable_stocks.clear()
            for code in self.stocks.keys():
                if (self.is_my_stock(code) and self.stocks[code]['buy_2_done'] == False) or self.is_ok_to_buy(code):
                    curr_price = self.get_curr_price(code)
                    if curr_price == 0:
                        continue
                    buy_target_price = self.get_buy_target_price(code)
                    if buy_target_price > 0:
                        gap_p = int((curr_price - buy_target_price) * 100 / buy_target_price)
                        # 현재가 - 매수가 GAP < X%
                        if gap_p < BUYABLE_GAP:
                            temp_stock = copy.deepcopy({code: self.stocks[code]})
                            self.buyable_stocks[code] = temp_stock[code]
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 장종료 시 일부 매수만 된 경우 처리
    #   buy_1_qty = buy_1_qty - 보유 수량
    #   buy_2_qty = buy_2_qty - 보유 수량
    ##############################################################
    def update_buy_qty_after_market_finish(self):
        result = True
        msg = ""
        try:                
            for code in self.my_stocks.keys():
                if self.stocks[code]['stockholdings'] > 0:
                    if self.stocks[code]['buy_1_done'] == False:
                        # 다 매수된 경우
                        if self.stocks[code]['stockholdings'] >= self.stocks[code]['buy_1_qty']:
                            self.set_buy_done(code)
                        else:
                            # 일부만 매수된 경우
                            self.stocks[code]['buy_1_qty'] -= self.stocks[code]['stockholdings']
                    elif self.stocks[code]['buy_2_done'] == False:
                        # 다 매수된 경우
                        if (self.stocks[code]['stockholdings'] - self.stocks[code]['buy_1_qty']) >= self.stocks[code]['buy_2_qty']:
                            self.set_buy_done(code)
                        else:
                            # 일부만 매수된 경우
                            if self.stocks[code]['stockholdings'] > self.stocks[code]['buy_1_qty']:
                                self.stocks[code]['buy_2_qty'] -= (self.stocks[code]['stockholdings'] - self.stocks[code]['buy_1_qty'])
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 매수 가능 종목 출력
    ##############################################################
    def show_buyable_stocks(self):
        result = True
        msg = ""
        try:                
            temp_stocks = copy.deepcopy(self.buyable_stocks)
            sorted_data = dict(sorted(temp_stocks.items(), key=lambda x: x[1]['undervalue'], reverse=True))
            data = {'종목명':[], '저평가':[], '목표주가GAP(%)':[], '매수가':[], '현재가':[], '매수가GAP(%)':[]}
            for code in sorted_data.keys():
                curr_price = self.get_curr_price(code)
                buy_target_price = self.get_buy_target_price(code)
                if buy_target_price > 0:
                    gap_p = int((curr_price - buy_target_price) * 100 / buy_target_price)
                else:
                    gap_p = 0
                data['종목명'].append(sorted_data[code]['name'])
                data['저평가'].append(sorted_data[code]['undervalue'])
                data['목표주가GAP(%)'].append(sorted_data[code]['gap_max_sell_target_price_p'])
                data['매수가'].append(buy_target_price)
                data['현재가'].append(curr_price)
                data['매수가GAP(%)'].append(gap_p)

            # PrettyTable 객체 생성 및 데이터 추가
            table = PrettyTable()
            table.field_names = list(data.keys())
            table.align = 'r'  # 우측 정렬
            for row in zip(*data.values()):
                table.add_row(row)
            
            self.send_msg("==========매수 가능 종목==========")
            self.send_msg(table)
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 익절가 퍼센트
    #   기준가-x%
    ##############################################################
    def set_take_profit_percent(self, code):
        result = True
        msg = ""
        try:                
            if self.stocks[code]['sell_target_price'] > self.stocks[code]['yesterday_end_price']:
                if self.stocks[code]['sell_target_price'] - self.stocks[code]['yesterday_end_price'] <= 1:
                    self.stocks[code]['take_profit_p'] = BIG_TAKE_PROFIT_P
                else:
                    self.stocks[code]['take_profit_p'] = SMALL_TAKE_PROFIT_P
            else:
                if self.stocks[code]['yesterday_end_price'] - self.stocks[code]['sell_target_price'] >= 2:
                    self.stocks[code]['take_profit_p'] = BIG_TAKE_PROFIT_P
                else:
                    self.stocks[code]['take_profit_p'] = SMALL_TAKE_PROFIT_P
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 익절가 리턴
    #   여지껏 최고가 - 익절가%
    ##############################################################
    def get_take_profit_price(self, code):
        result = True
        msg = ""
        try:                
            self.update_highest_price_ever(code)
            return int(self.stocks[code]['highest_price_ever'] * (1 + self.to_percent(self.stocks[code]['take_profit_p'])))
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

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
                self.stocks[code]['loss_cut_order'] = False
                self.stocks[code]['buy_order_done'] = False
                self.stocks[code]['sell_order_done'] = False
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)
 
    ##############################################################
    # 금일 기준 X 일 내 최고 종가 리턴
    # param :
    #   code        종목 코드
    #   days        X 일. ex) 21 -> 금일 기준 21일 내(영업일 기준 약 한 달)
    #               MAX : 30
    ##############################################################
    def get_highest_end_pirce(self, code, days):
        result = True
        msg = ""
        try:                
            highest_end_price = 0
            for past_day in range(days + 1):
                end_price = self.get_end_price(code, past_day)
                if highest_end_price < end_price:
                    highest_end_price = end_price
            return highest_end_price
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)

    ##############################################################
    # 1차 매수를 최소 수량만 매수할 지 여부 체크
    #   "한 달 내 최고 종가 < (1+1.7*엔벨지지)*엔벨지지가" 경우
    #   retun True 아니면 False
    # param :
    #   code        종목 코드
    ##############################################################
    def is_buy_1_stocks_lowest(self, code):  
        result = True
        msg = ""
        try:                      
            # 한 달은 약 21일
            highest_end_price = self.get_highest_end_pirce(code, 21)
            envelope_p = self.stocks[code]['envelope_p']
            envelope_price = self.stocks[code]['buy_1_price']
            if highest_end_price < (1 + 1.7 * self.to_percent(envelope_p)) * envelope_price:
                return True
            return False
        except Exception as ex:
            result = False
            msg = "Exception {}".format(ex)
        finally:
            if result == False:
                PRINT_ERR(msg)
    