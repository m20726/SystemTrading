import copy
import datetime
import time

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
# function overloading
from multipledispatch import dispatch

from handle_json import *

STOCK_INFO_FILE_PATH = './stocks_info.json'
# APP_KEY, APP_SECRET 등 투자 관련 설정 정보
CONFIG_FILE_PATH = './config.json'

# 어제 20 이평선 지지선 기준으로 오늘의 지지선 구하기 위한 상수
# ex) 오늘의 지지선 = 어제 20 이평선 지지선 * 0.993
MARGIN_20MA = 0.993

# 주식 일별 주문 체결 조회, 매도 매수 구분 코드
BUY_SELL_CODE = "00"
SELL_CODE = "01"
BUY_CODE = "02"
# ex) 20130414
TODAY_DATE = f"{datetime.datetime.now().strftime('%Y%m%d')}"

##############################################################


class Stocks_info:
    def __init__(self) -> None:
        self.stocks = dict()                        # 모든 종목의 정보
        self.my_stocks = dict()                     # 보유 종목
        # sim_invest : 모의 투자, real_invest : 실전 투자
        self.invest_type = "sim_invest"
        self.config = dict()                        # 투자 관련 설정 정보
        self.access_token = ""
        self.invest_money_per_stock = 1000000       # 종목 당 투자 금액
        self.buy_1_p = 40                           # 1차 매수 40%
        self.buy_2_p = 60                           # 2차 매수 60%
        # 1차 매수 금액
        self.buy_1_invest_money = self.invest_money_per_stock * \
            (self.buy_1_p / 100)
        # 2차 매수 금액
        self.buy_2_invest_money = self.invest_money_per_stock * \
            (self.buy_2_p / 100)
        # 네이버 증권의 기업실적분석표
        self.this_year_column_text = ""                  # 2023년 기준 2023.12(E)
        # 2023년 기준 2022.12       작년 데이터 얻기
        self.last_year_column_text = ""
        # 2023년 기준 2021.12       재작년 데이터 얻기
        self.the_year_before_last_column_text = ""
        self.init_naver_finance_year_column_texts()
        self.trade_done_stocks = list()                 # 체결 완료 종목

    ##############################################################

    def send_msg(self, msg):
        """디스코드 메세지 전송"""
        now = datetime.datetime.now()
        message = {
            "content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
        # requests.post(DISCORD_WEBHOOK_URL, data=message)
        print(message)

    ##############################################################
    # 네이버 증권 기업실적분석 정보 얻기
    ##############################################################
    def crawl_naver_finance(self, code):
        req = requests.get(
            'https://finance.naver.com/item/main.nhn?code=' + code)
        page_soup = BeautifulSoup(req.text, 'lxml')
        finance_html = page_soup.select_one('div.cop_analysis')
        th_data = [item.get_text().strip()
                   for item in finance_html.select('thead th')]
        # 2023 기준
        # ['2020.12', '2021.12', '2022.12', '2023.12(E)']
        annual_date = th_data[3:7]
        quarter_date = th_data[7:13]
        # ['주요재무정보', '최근 연간 실적', '최근 분기 실적', '매출액', '영업이익', '당기순이익', '영업이익률', '순이익률', 'ROE(지배주주)', '부채비율', '당좌비율', '유보율', 'EPS(원)', 'PER(배)', 'BPS(원)', 'PBR(배)', '주당배당금(원)', '시가배당률(%)', '배당성향(%)']
        finance_index = [item.get_text().strip()
                         for item in finance_html.select('th.h_th2')][3:]
        finance_data = [item.get_text().strip()
                        for item in finance_html.select('td')]
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
        finance = pd.DataFrame(
            data=finance_data[0:, 0:], index=finance_index, columns=finance_date)
        annual_finance = finance.iloc[:, :4]
        return annual_finance

    ##############################################################
    # 네이버 증권 기업실적분석 년도 텍스트 초기화
    ##############################################################
    def init_naver_finance_year_column_texts(self):
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
        configs = read_json_file(file_path)
        self.config = configs[self.invest_type]

    ##############################################################
    # stocks 에서 code 에 해당하는 stock 리턴
    ##############################################################
    def get_stock(self, code: str):
        try:
            return self.stocks[code]
        except KeyError:
            print(f'KeyError : {code} is not found')
            return None

    ##############################################################
    # stocks file 에서 stocks 정보 가져온다
    ##############################################################
    def load_stocks_info(self, file_path):
        self.stocks = read_json_file(file_path)

    ##############################################################
    # stocks 정보를 stocks file 에 저장
    ##############################################################
    def save_stocks_info(self, file_path):
        write_json_file(self.stocks, file_path)

    ##############################################################
    # code 에 해당하는 종목의 key 에 value 로 세팅
    # ex) update_stock_info("005930", "buy_1_price", 50000)
    #       삼성전자 1차 매수가를 50000원으로 변경
    ##############################################################
    @dispatch(str, str, object)
    def update_stock_info(self, code: str, key: str, value):
        try:
            self.stocks[code][key] = value
        except KeyError:
            print(f'KeyError : {code} is not found')

    ##############################################################
    # code 에 해당하는 종목의 모든 정보를 stocks 에 업데이트
    # @dispatch(dict)
    # def update_stock_info(self, stock:dict):
    #     print(stock)

    ##############################################################
    # 모든 주식의 어제 20일선 업데이트
    # def update_stocks_trade_info_yesterday_20ma(self):
    #     for key in self.stocks.keys():
    #         yesterday_20ma = self.get_20ma(self.stocks[key]['code'], 1)
    #         # print(f"{self.stocks[key]['name']} {yesterday_20ma}")
    #         self.stocks[key]['yesterday_20ma'] = yesterday_20ma

    ##############################################################
    # 1차 매수가 구하기
    ##############################################################
    def get_buy_1_price(self, code):
        envelope_p = self.to_percent(self.stocks[code]['envelope_p'])
        envelope_support_line = self.stocks[code]['yesterday_20ma'] * (
            1 - envelope_p)
        buy_1_price = envelope_support_line * MARGIN_20MA
        return int(buy_1_price)

    ##############################################################
    # 1차 매수 수량 = 1차 매수 금액 / 매수가
    ##############################################################
    def get_buy_1_qty(self, code):
        # TEST
        return 1
        # return int(self.buy_1_invest_money / self.stocks[code]['buy_1_price'])

    ##############################################################
    # 2차 매수가 = 1차 매수가 - 10%
    ##############################################################
    def get_buy_2_price(self, code):
        #test 2차 매수 -1%
        return int(self.stocks[code]['buy_1_price'] * 0.99)
        # return int(self.stocks[code]['buy_1_price'] * 0.9)

    ##############################################################
    # 2차 매수 수량 = 2차 매수 금액 / 매수가
    ##############################################################
    def get_buy_2_qty(self, code):
        # TEST
        return 1        
        # return int(self.buy_2_invest_money / self.stocks[code]['buy_2_price'])

    ##############################################################
    # 매수 완료 시 호출
    ##############################################################
    def set_buy_done(self, code):
        if self.stocks[code]['buy_1_done'] == False:
            # 1차 매수 안된 경우는 1차 매수 완료
            self.stocks[code]['buy_1_done'] = True
        else:
            # 1차 매수 완료된 경우는 2차 매수 완료
            self.stocks[code]['buy_2_done'] = True
        # 매수 완료됐으니 평단가, 목표가 업데이트
        self.update_my_stocks_info()
        # 당일 매수 당일 매도 주문
        self.handle_today_buy_today_sell(code)
        # 계좌 잔고 조회
        self.get_stock_balance()

    ##############################################################
    # 매도 완료 시 호출
    #   매도는 항상 전체 수량 매도 기반
    ##############################################################
    def set_sell_done(self, code):
        self.stocks[code]['sell_done'] = True
        # 매도 완료 후 종가 > 20ma 체크위해 false 처리
        self.stocks[code]['end_price_higher_than_20ma_after_sold'] = False
        self.update_my_stocks_info()
        self.clear_buy_sell_info(code)
        # 계좌 잔고 조회
        self.get_stock_balance()

    ##############################################################
    # 매도 완료등으로 매수/매도 관려 정보 초기화 시 호출
    ##############################################################
    def clear_buy_sell_info(self, code):
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

    ##############################################################
    # 평단가
    # 1차 매수가 안된 경우
    #   평단가 = 1차 매수가
    # 2차 매수까지 된 경우
    #   평단가 = ((1차 매수가 * 1차 매수량) + (2차 매수가 * 2차 매수량)) / (1차 + 2차 매수량)
    ##############################################################
    def get_avg_buy_price(self, code):
        # 보유 종목이 아닌 경우 목표가 계산을 위해 평단가 필요
        is_my_stock = False
        my_stocks = self.update_my_stocks_info()
        if code in my_stocks.keys():
            is_my_stock = True

        if is_my_stock == True:
            avg_buy_price = my_stocks[code]['avg_buy_price']
        else:
            # 보유 종목 아닌 경우
            if self.stocks[code]['buy_1_done'] == True and self.stocks[code]['buy_2_done'] == True:
                # 2차 매수까지 된 경우
                tot_buy_1_money = self.stocks[code]['buy_1_price'] * self.stocks[code]['buy_1_qty']
                tot_buy_2_money = self.stocks[code]['buy_2_price'] * self.stocks[code]['buy_2_qty']
                tot_buy_qty = self.stocks[code]['buy_1_qty'] + self.stocks[code]['buy_2_qty']
                avg_buy_price = int((tot_buy_1_money + tot_buy_2_money) / tot_buy_qty)
            else:
                # 1차 매수만 됐거나 1차 매수도 안된 경우
                avg_buy_price = self.stocks[code]['buy_1_price']
        return avg_buy_price

    ##############################################################
    # 목표가 = 평단가 * (1 + 목표%)
    ##############################################################
    def get_sell_target_price(self, code):
        sell_target_p = self.to_percent(self.stocks[code]['sell_target_p'])
        return int(self.stocks[code]['avg_buy_price'] * (1 + sell_target_p))

    ##############################################################
    # 현재가 리턴
    #   성공 시 현재가, 실패 시 0 리턴
    ##############################################################
    def get_curr_price(self, code):
        curr_price = 0
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
            self.stocks[code]['curr_price'] = int(
                float(res.json()['output']['stck_prpr']))
            curr_price = self.stocks[code]['curr_price']
        else:
            self.send_msg(f"[update_stock_invest_info failed]{str(res.json())}")
        return curr_price

    ##############################################################
    # 매수가 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수가 리턴
    #   2차 매수까지 완료면 0 리턴
    ##############################################################
    def get_buy_target_price(self, code):
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

    ##############################################################
    # 매수 수량 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수 수량 리턴
    #   2차 매수까지 완료면 0 리턴
    ##############################################################
    def get_buy_target_qty(self, code):
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

    ##############################################################
    # 네이버 증권에서 특정 값 얻기
    #   ex) https://finance.naver.com/item/main.naver?code=005930
    ##############################################################
    def crawl_naver_finance_by_selector(self, code, selector):
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        html = requests.get(url).text
        soup = BeautifulSoup(html, "html5lib")
        result = soup.select_one(selector).text
        return result

    ##############################################################
    # 종목 투자 정보 업데이트(시가 총액, 상장 주식 수, 저평가, BPS, PER, EPS)
    ##############################################################
    def update_stock_invest_info(self, code):
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
            # 현재 PER
            self.stocks[code]['PER'] = float(res.json()['output']['per'])
            self.stocks[code]['curr_price'] = int(
                float(res.json()['output']['stck_prpr']))
            self.stocks[code]['capitalization'] = int(
                res.json()['output']['hts_avls'])         # 시가 총액(억)
            self.stocks[code]['total_stock_count'] = int(
                res.json()['output']['lstn_stcn'])     # 상장 주식 수
        else:
            self.send_msg(f"[update_stock_invest_info failed]{str(res.json())}")

        annual_finance = self.crawl_naver_finance(code)
        # PER_E, EPS, BPS, ROE 는 2013.12(E) 기준
        self.stocks[code]['PER_E'] = float(
            annual_finance[self.this_year_column_text]['PER(배)'])
        self.stocks[code]['EPS_E'] = int(
            annual_finance[self.this_year_column_text]['EPS(원)'])
        self.stocks[code]['BPS_E'] = int(
            annual_finance[self.this_year_column_text]['BPS(원)'])
        self.stocks[code]['ROE_E'] = float(
            annual_finance[self.this_year_column_text]['ROE(지배주주)'])
        self.stocks[code]['industry_PER'] = float(self.crawl_naver_finance_by_selector(
            code, "#tab_con1 > div:nth-child(6) > table > tbody > tr.strong > td > em"))
        self.stocks[code]['operating_profit_margin_p'] = float(
            annual_finance[self.this_year_column_text]['영업이익률'])
        self.stocks[code]['sales_income'] = int(
            annual_finance[self.this_year_column_text]['매출액'])                   # 올해 예상 매출액, 억원
        self.stocks[code]['last_year_sales_income'] = int(
            annual_finance[self.last_year_column_text]['매출액'])         # 작년 매출액, 억원
        self.stocks[code]['the_year_before_last_sales_income'] = int(
            annual_finance[self.the_year_before_last_column_text]['매출액'])       # 재작년 매출액, 억원
        self.stocks[code]['curr_profit'] = int(
            annual_finance[self.this_year_column_text]['당기순이익'])
        # 목표 주가 = 미래 당기순이익(원) * PER_E / 상장주식수
        self.stocks[code]['max_target_price'] = int(
            (self.stocks[code]['curr_profit'] * 100000000) * self.stocks[code]['PER_E'] / self.stocks[code]['total_stock_count'])
        # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가
        # + : 저평가
        # - : 고평가
        self.stocks[code]['gap_max_sell_target_price_p'] = int(
            100 * (self.stocks[code]['max_target_price'] - self.stocks[code]['sell_target_price']) / self.stocks[code]['sell_target_price'])

        self.set_stock_undervalue(code)

    ##############################################################
    # 저평가 계산
    ##############################################################
    def set_stock_undervalue(self, code):
        self.stocks[code]['undervalue'] = 0
        # BPS_E > 현재가
        if self.stocks[code]['BPS_E'] > self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] += 2
        elif self.stocks[code]['BPS_E'] * 1.3 < self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] -= 2

        # EPS_E * 10 > 현재가
        if self.stocks[code]['EPS_E'] * 10 > self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] += 2
        elif self.stocks[code]['EPS_E'] * 3 < self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] -= 2

        # ROE_E
        if self.stocks[code]['ROE_E'] * self.stocks[code]['EPS_E'] > self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] += 2
        elif self.stocks[code]['ROE_E'] * self.stocks[code]['EPS_E'] * 1.3 < self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] -= 2
        if self.stocks[code]['ROE_E'] > 20:
            self.stocks[code]['undervalue'] += (
                self.stocks[code]['ROE_E'] / 10)

        # PER 업종 PER 대비
        if self.stocks[code]['PER'] <= 10:
            self.stocks[code]['undervalue'] += int(
                (1 - self.stocks[code]['PER'] / self.stocks[code]['industry_PER']) * 5)
        elif self.stocks[code]['PER'] >= 20:
            self.stocks[code]['undervalue'] -= 5

        # 영업이익률
        if self.stocks[code]['operating_profit_margin_p'] >= 10:
            self.stocks[code]['undervalue'] += 1
        elif self.stocks[code]['operating_profit_margin_p'] < 0:
            self.stocks[code]['undervalue'] -= 1

        # 매출액
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

    ##############################################################
    # 매수/매도 위한 주식 정보 업데이트
    #   1,2차 매수가, 20일선
    ##############################################################
    def update_stocks_trade_info(self):
        print(f"update_stocks_trade_info S")
        t_now = datetime.datetime.now()
        t_exit = t_now.replace(hour=15, minute=30, second=0, microsecond=0)
        for code in self.stocks.keys():
            print(f"{self.stocks[code]['name']}")
            # 순서 변경 금지
            # ex) 목표가를 구하기 위해선 평단가가 먼저 있어야한다
            # yesterday 20일선
            # 15:30 장마감 후는 금일기준으로 20일선 구한다
            if t_exit < t_now:
                past_day = 0        # 장마감 후는 금일 기준
            else:
                past_day = 1        # 어제 기준
            self.stocks[code]['yesterday_20ma'] = self.get_20ma(self.stocks[code]['code'], past_day)

            # 1차 매수가
            self.stocks[code]['buy_1_price'] = self.get_buy_1_price(self.stocks[code]['code'])
            # 1차 매수 수량
            self.stocks[code]['buy_1_qty'] = self.get_buy_1_qty(self.stocks[code]['code'])
            # 2차 매수가
            self.stocks[code]['buy_2_price'] = self.get_buy_2_price(self.stocks[code]['code'])
            # 2차 매수 수량
            self.stocks[code]['buy_2_qty'] = self.get_buy_2_qty(self.stocks[code]['code'])
            # 어제 종가
            self.stocks[code]['yesterday_end_price'] = self.get_end_price(self.stocks[code]['code'], past_day)
            # 평단가
            self.stocks[code]['avg_buy_price'] = self.get_avg_buy_price(self.stocks[code]['code'])
            # 목표가 = 평단가에서 목표% 수익가
            self.stocks[code]['sell_target_price'] = self.get_sell_target_price(self.stocks[code]['code'])

            # 종목 투자 정보 업데이트(시가 총액, 상장 주식 수, 저평가, BPS, PER, EPS)
            self.update_stock_invest_info(self.stocks[code]['code'])
            # 호가 단위로 수정
            self.stocks[code]['buy_1_price'] = self.get_stock_asking_price(self.stocks[code]['buy_1_price'])
            self.stocks[code]['buy_2_price'] = self.get_stock_asking_price(self.stocks[code]['buy_2_price'])
            self.stocks[code]['avg_buy_price'] = self.get_stock_asking_price(self.stocks[code]['avg_buy_price'])
            self.stocks[code]['sell_target_price'] = self.get_stock_asking_price(self.stocks[code]['sell_target_price'])

        # print(json.dumps(self.stocks, indent=4, ensure_ascii=False))
        print(f"update_stocks_trade_info E")

    ##############################################################
    # 보유 주식 정보 업데이트
    #   보유 주식은 stockholdings > 0
    #   TODO 검증
    ##############################################################
    def update_my_stocks_info(self):
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
                    # 보유 수량
                    self.stocks[code]['stockholdings'] = int(stock['hldg_qty'])
                    # 평단가
                    self.stocks[code]['avg_buy_price'] = int(
                        float(stock['pchs_avg_pric']))
                    # 목표가 = 평단가에서 목표% 수익가
                    self.stocks[code]['sell_target_price'] = self.get_sell_target_price(
                        self.stocks[code]['code'])
                    # self.my_stocks 업데이트
                    temp_stock = copy.deepcopy(
                        {self.stocks[code]['code']: self.stocks[code]})
                    self.my_stocks[code] = temp_stock[code]
                    time.sleep(0.1)
        else:
            self.send_msg(f"[계좌 조회 실패]{str(res.json())}")
            return None
        return self.my_stocks

    ##############################################################
    # 매수 여부 판단
    ##############################################################
    def is_ok_to_buy(self, code):
        # 오늘 주문 완료 시 금지
        if self.already_ordered(code, BUY_CODE) == True:
            return False

        # 2차 매수까지 완료 시 금지
        if self.stocks[code]['buy_2_done'] == True:
            return False
        
        # test
        # 저평가 조건(X미만 매수 금지)
        # if self.stocks[code]['undervalue'] < 3:
        #     return False
        
        # test
        # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가
        # 8% 미만 매수 금지
        # if self.stocks[code]['gap_max_sell_target_price_p'] < 8:
        #     return False

        # 매도 후 종가 > 20ma 체크
        if self.stocks[code]['sell_done'] == True:
            # 어제 종가 > 어제 20ma
            if self.stocks[code]['yesterday_end_price'] > self.stocks[code]['yesterday_20ma']:
                self.stocks[code]['end_price_higher_than_20ma_after_sold'] = True
            # 매도 후 종가 > 20ma 넘지 못했으면 금지
            if self.stocks[code]['end_price_higher_than_20ma_after_sold'] == False:
                return False
        else:
            pass

        return True

    ##############################################################
    # 20일선 가격 리턴
    # param :
    #   code            종목 코드
    #   past_day        20일선 가격 기준
    #                   ex) 0 : 금일 20일선, 1 : 어제 20일선
    ##############################################################
    def get_20ma(self, code: str, past_day=0):
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

        # 20 이평선 구하기 위해 20일간의 종가 구한다
        days_20_last = past_day + 20
        sum_end_price = 0
        for i in range(past_day, days_20_last):
            end_price = int(res.json()['output'][i]['stck_clpr'])   # 종가
            # print(f"{i} 종가 : {end_price}")
            sum_end_price = sum_end_price + end_price               # 종가 합

        value_20ma = sum_end_price / 20                             # 20일선 가격
        return int(value_20ma)

    ##############################################################
    # 종가 리턴
    # param :
    #   code            종목 코드
    #   past_day        가져올 날짜 기준
    #                   ex) 0 : 금일 종가, 1 : 어제 종가
    ##############################################################
    def get_end_price(self, code: str, past_day=0):
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
        return int(res.json()['output'][past_day]['stck_clpr'])   # 종가

    ##############################################################
    # 토큰 발급
    ##############################################################
    def get_access_token(self):
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials",
                "appkey": self.config['APP_KEY'],
                "appsecret": self.config['APP_SECRET']}
        PATH = "oauth2/tokenP"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        res = requests.post(URL, headers=headers, data=json.dumps(body))
        return res.json()["access_token"]

    ##############################################################
    # 암호화
    ##############################################################
    def hashkey(self, datas):
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

    ##############################################################
    def get_current_price(self, code: str):
        """현재가 조회"""
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
        return int(res.json()['output']['stck_prpr'])

    ##############################################################
    def get_target_price(self, code: str):
        # """변동성 돌파 전략으로 매수 목표가 조회"""
        # PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-price"
        # URL = f"{self.config['URL_BASE']}/{PATH}"
        # headers = {"Content-Type":"application/json",
        #     "authorization": f"Bearer {self.access_token}",
        #     "appKey":self.config['APP_KEY'],
        #     "appSecret":self.config['APP_SECRET'],
        #     "tr_id":"FHKST01010400"}
        # params = {
        # "fid_cond_mrkt_div_code":"J",
        # "fid_input_iscd":code,
        # "fid_org_adj_prc":"1",
        # "fid_period_div_code":"D"
        # }
        # res = requests.get(URL, headers=headers, params=params)
        # stck_oprc = int(res.json()['output'][0]['stck_oprc']) #오늘 시가
        # stck_hgpr = int(res.json()['output'][1]['stck_hgpr']) #전일 고가
        # stck_lwpr = int(res.json()['output'][1]['stck_lwpr']) #전일 저가
        # target_price = stck_oprc + (stck_hgpr - stck_lwpr) * 0.5
        # return target_price
        return 0

    ##############################################################
    # 주식 잔고조회
    ##############################################################
    def get_stock_balance(self):
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
        stock_dict = {}
        self.send_msg(f"====주식 보유잔고====")
        for stock in stock_list:
            if int(stock['hldg_qty']) > 0:
                stock_dict[stock['pdno']] = stock['hldg_qty']
                self.send_msg(f"{stock['prdt_name']}({stock['pdno']}) 평단가 {int(float(stock['pchs_avg_pric']))} {stock['hldg_qty']}주")
                time.sleep(0.1)
        self.send_msg(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원")
        time.sleep(0.1)
        self.send_msg(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원")
        time.sleep(0.1)
        self.send_msg(f"총 평가 금액: {evaluation[0]['tot_evlu_amt']}원")
        time.sleep(0.1)
        self.send_msg(f"=================================")
        return stock_dict

    ##############################################################
    # 현금 잔고 조회
    ##############################################################
    def get_balance(self):
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
        self.send_msg(f"주문 가능 현금 잔고: {cash}원")
        return int(cash)

    ##############################################################
    # 지정가 매수
    ##############################################################
    def buy(self, code: str, price: str, qty: str):
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
            # 지정가 매수
            "ORD_DVSN": "00",
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
        self.send_msg(f"[매수 주문] {self.stocks[code]['name']} {price}원 {qty}주")
        res = requests.post(URL, headers=headers, data=json.dumps(data))
        if self.is_request_ok(res) == True:
            self.send_msg(f"[매수 주문 성공]{str(res.json())}")
            return True
        else:
            self.send_msg(f"[매수 주문 실패]{str(res.json())}")
            return False

    ##############################################################
    # 지정가 매도
    ##############################################################
    def sell(self, code: str, price: str, qty: str):
        # 오늘 주문 완료 시 금지
        if self.already_ordered(code, SELL_CODE) == True:
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
            # 지정가 매도
            "ORD_DVSN": "00",
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
            self.send_msg(f"[매도 주문 성공] {self.stocks[code]['name']} {price}원 {qty}주 {str(res.json())}")
            return True
        else:
            self.send_msg(f"[매도 주문 실패]{str(res.json())}")
            return False

    ##############################################################
    # 금일 매수 종목 매도 주문
    #   동일 종목 매도 주문 있으면 주문 취소 후 새 목표가로 매도 주문
    #   없으면 1차 목표가로 매도
    # Return    : None
    # Parameter :
    #       code                    종목 코드
    ##############################################################
    def handle_today_buy_today_sell(self, code):
        # 보유수량, 목표가 업데이트
        self.update_my_stocks_info()
        if self.already_ordered(code, SELL_CODE) == True:
            if self.cancel_order(code, SELL_CODE) == True:
                if self.sell(code, self.stocks[code]['sell_target_price'], self.stocks[code]['stockholdings']) == True:
                    self.show_order_list()
        else:
            if self.sell(code, self.stocks[code]['sell_target_price'], self.stocks[code]['stockholdings']) == True:
                self.show_order_list()

    ##############################################################
    # 매수 처리
    #   현재가 <= 매수가면 매수
    #   단, 현재가 - 1% <= 매수가 매수가에 미리 매수 주문
    ##############################################################
    def handle_buy_stock(self):
        for code in self.stocks.keys():
            curr_price = self.get_curr_price(code)
            buy_target_price = self.get_buy_target_price(code)
            buy_target_qty = self.get_buy_target_qty(code)
            if curr_price > 0 and buy_target_price > 0:
                # self.send_msg(f"매수 체크 {self.stocks[code]['name']} {buy_target_price}원 {buy_target_qty}주, 현재가 {curr_price}")
                if curr_price * 0.99 <= buy_target_price:
                    if self.is_ok_to_buy(code) == True:
                        # 매수 주문
                        if self.buy(code, buy_target_price, buy_target_qty) == True:
                            self.show_order_list()
                    else:
                        pass
                else:
                    pass
            else:
                pass
            time.sleep(0.1)

    ##############################################################
    # 매도 처리
    ##############################################################
    def handle_sell_stock(self):
        my_stocks = self.update_my_stocks_info()
        for code in my_stocks.keys():
            if self.sell(code, my_stocks[code]['sell_target_price'], my_stocks[code]['stockholdings']) == True:
                self.show_order_list()
            time.sleep(0.1)

    ##############################################################
    # 주문 번호 리턴
    #   return : 성공 시 True 주문 번호, 실패 시 False  ""
    #   param :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    ##############################################################
    def get_order_num(self, code, buy_sell: str):
        order_stock_list = self.get_order_list()
        for stock in order_stock_list:
            if stock['pdno'] == code and stock['sll_buy_dvsn_cd'] == buy_sell:
                return True, stock['odno']
        return False, ""

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
            res = requests.get(URL, headers=headers, params=params)
            if self.is_request_ok(res) == True:
                self.send_msg(f"[주식 주문 전량 취소 주문 성공]{str(res.json())}")
            else:
                if self.config['TR_ID_MODIFY_CANCEL_ORDER'] == "VTTC0803U":
                    self.send_msg(f"[주식 주문 전량 취소 주문 실패] 모의 투자 미지원")
                else:
                    self.send_msg(f"[주식 주문 전량 취소 주문 실패]{str(res.json())}")
        else:
            self.send_msg(f"[cancel_order failed] {self.stocks[code]['name']} {buy_sell}")

    ##############################################################
    # 매수/매도 체결 여부 체크
    # Return    : 주문 수량 전체 체결 시 True, 아니면 False
    # Parameter :
    #       code            종목 코드
    #       buy_sell        "01" : 매도, "02" : 매수
    ##############################################################
    def check_trade_done(self, code, buy_sell: str):
        # 이미 체결 완료 처리한 종목은 재처리 금지
        if code in self.trade_done_stocks:
            return False
        
        result = False
        order_stock_list = self.get_order_list()
        for stock in order_stock_list:            
            if stock['pdno'] == code and stock['sll_buy_dvsn_cd'] == buy_sell:
                if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                    buy_sell_order = "매수"
                else:
                    buy_sell_order = "매도"
                # 주문 수량
                order_qty = int(stock['ord_qty'])
                # 총 체결 수량
                tot_trade_qty = int(stock['tot_ccld_qty'])
                if tot_trade_qty == 0:
                    # 미체결
                    return False
                elif order_qty == tot_trade_qty:
                    # 전량 체결 완료
                    self.send_msg(f"{stock['prdt_name']} {stock['ord_unpr']}원 {tot_trade_qty}/{order_qty}주 {buy_sell_order} 전량 체결 완료")
                    # 체결 완료 체크한 종목은 다시 체크하지 않는다
                    # while loop 에서 반복적으로 체크하는거 방지
                    self.trade_done_stocks.append(code)                    
                    return True
                elif order_qty > tot_trade_qty:
                    # 일부 체결
                    self.send_msg(f"{stock['prdt_name']} {stock['ord_unpr']}원 {tot_trade_qty}/{order_qty}주 {buy_sell_order} 체결")
                    return False
        return result

    ##############################################################
    # 매수 체결 여부 체크
    #   주문 종목에서 매수 체결 여부 확인
    ##############################################################
    def check_ordered_stocks_trade_done(self):
        order_stock_list = self.get_order_list()
        for stock in order_stock_list:
            code = stock['pdno']
            buy_sell = stock['sll_buy_dvsn_cd']
            if self.check_trade_done(code, buy_sell) == True:
                if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                    self.set_buy_done(code)
                else:
                    self.set_sell_done(code)
            time.sleep(0.1)

    ##############################################################
    # 주식 일별 주문 체결 조회 stock list 리턴
    # Return    : 체결 조회 stock list
    ##############################################################
    def get_order_list(self):
        stock_list = list()
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
            "INQR_DVSN_3": "",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        res = requests.get(URL, headers=headers, params=params)
        # print("주식 일별 주문 체결 조회 API, 원주문번호 가져오기")
        # print(f"headers : {headers}")
        # print(f"params : {params}")
        if self.is_request_ok(res) == True:
            stock_list = res.json()['output1']
        else:
            self.send_msg(f"[get_order_list failed]{str(res.json())}")
        return stock_list

    ##############################################################
    # 주식 일별 주문 체결 조회
    ##############################################################
    def show_order_list(self):
        order_stock_list = self.get_order_list()
        self.send_msg(f"====주식 일별 주문 체결 조회====")
        for stock in order_stock_list:
            if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                buy_sell_order = "매수 주문"
            else:
                buy_sell_order = "매도 주문"
            curr_price = self.get_curr_price(stock['pdno'])
            self.send_msg(f"{stock['prdt_name']} {buy_sell_order} {stock['ord_unpr']}원 {stock['ord_qty']}주, {stock['tot_ccld_qty']}주 체결, 현재가 {curr_price}원")
            time.sleep(0.1)
        self.send_msg(f"=================================")

    ##############################################################
    # 이미 주문한 종목인지 체크
    # Return    : 이미 주문한 종목이면 Ture, 아니면 False
    # Parameter :
    #       code        종목코드
    #       buy_sell    "01" : 매도, "02" : 매수
    ##############################################################
    def already_ordered(self, code, buy_sell: str):
        order_stock_list = self.get_order_list()
        for stock in order_stock_list:
            if stock['pdno'] == code and stock['sll_buy_dvsn_cd'] == buy_sell:
                if stock['sll_buy_dvsn_cd'] == BUY_CODE:
                    buy_sell_order = "매수 주문"
                else:
                    buy_sell_order = "매도 주문"
                # self.send_msg(f"이미 주문한 종목 : {stock['prdt_name']} {buy_sell_order} {stock['ord_unpr']}원 {stock['ord_qty']}주")
                return True
        return False