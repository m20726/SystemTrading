from handle_json import *
# function overloading
from multipledispatch import dispatch
import requests
import datetime
import time
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np


STOCK_INFO_FILE_PATH = './stocks_info.json'
# APP_KEY, APP_SECRET 등 투자 관련 설정 정보
CONFIG_FILE_PATH = './config.json'


##############################################################
class Stocks_info:
    def __init__(self) -> None:
        self.stocks = dict()                        # 모든 종목의 정보
        self.invest_type = "sim_invest"             # sim_invest : 모의 투자, real_invest : 실전 투자
        self.config = dict()                        # 투자 관련 설정 정보
        # 어제 20 이평선 지지선 기준으로 오늘의 지지선 구하기 위한 상수
        # ex) 오늘의 지지선 = 어제 20 이평선 지지선 * 0.993
        self.margin_20ma = 0.993
        self.access_token = ""
        self.invest_money_per_stock = 1000000       # 종목 당 투자 금액
        self.buy_1_p = 40                           # 1차 매수 40%
        self.buy_2_p = 60                           # 2차 매수 60%
        # 1차 매수 금액
        self.buy_1_invest_money = self.invest_money_per_stock * (self.buy_1_p / 100)
        # 2차 매수 금액
        self.buy_2_invest_money = self.invest_money_per_stock * (self.buy_2_p / 100)
        # 네이버 증권의 기업실적분석표
        self.this_year_column_text = ""                  # 2023년 기준 2023.12(E)
        self.last_year_column_text = ""                  # 2023년 기준 2022.12       작년 데이터 얻기
        self.the_year_before_last_column_text = ""       # 2023년 기준 2021.12       재작년 데이터 얻기
        self.init_naver_finance_year_column_texts()

    ##############################################################
    def send_message(self, msg):
        """디스코드 메세지 전송"""
        now = datetime.datetime.now()
        message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
        #requests.post(DISCORD_WEBHOOK_URL, data=message)
        print(message)

    ##############################################################
    # 네이버 증권 기업실적분석 정보 얻기
    def crawl_naver_finance(self, code):
        req = requests.get('https://finance.naver.com/item/main.nhn?code=' + code)
        page_soup = BeautifulSoup(req.text, 'lxml')
        finance_html = page_soup.select_one('div.cop_analysis')
        th_data = [item.get_text().strip() for item in finance_html.select('thead th')]
        # 2023 기준
        annual_date = th_data[3:7] # ['2020.12', '2021.12', '2022.12', '2023.12(E)']
        quarter_date = th_data[7:13]
        finance_index = [item.get_text().strip() for item in finance_html.select('th.h_th2')][3:]  # ['주요재무정보', '최근 연간 실적', '최근 분기 실적', '매출액', '영업이익', '당기순이익', '영업이익률', '순이익률', 'ROE(지배주주)', '부채비율', '당좌비율', '유보율', 'EPS(원)', 'PER(배)', 'BPS(원)', 'PBR(배)', '주당배당금(원)', '시가배당률(%)', '배당성향(%)']
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

    ##############################################################
    # 네이버 증권 기업실적분석 년도 텍스트 초기화
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
    def is_request_ok(self, res):
        if res.json()['rt_cd'] == '0':
            return True
        else:
            return False
    
    ##############################################################
    # percent 값으로 변경
    # ex) to_per(10) return 0.1
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
    def init_config(self, file_path):
        configs = read_json_file(file_path)
        self.config = configs[self.invest_type]

    ##############################################################
    # stocks 에서 code 에 해당하는 stock 리턴
    def get_stock(self, code: str):
        try:
            return self.stocks[code]
        except KeyError:
            print(f'KeyError : {code} is not found')
            return None

    ##############################################################
    # stocks file 에서 stocks 정보 가져온다
    def load_stocks_info(self, file_path):
        self.stocks = read_json_file(file_path)

    ##############################################################
    # stocks 정보를 stocks file 에 저장
    def save_stocks_info(self, file_path):
        write_json_file(self.stocks, file_path)

    ##############################################################
    # code 에 해당하는 종목의 key 에 value 로 세팅
    # ex) update_stock_info("005930", "buy_1_price", 50000)
    #       삼성전자 1차 매수가를 50000원으로 변경
    @dispatch(str, str, object)
    def update_stock_info(self, code:str, key:str, value):
        try:
            self.stocks[code][key] = value
            print(self.stocks[code])
        except KeyError:
            print(f'KeyError : {code} is not found')

    ##############################################################
    # code 에 해당하는 종목의 모든 정보를 stocks 에 업데이트
    # TODO
    @dispatch(dict)
    def update_stock_info(self, stock:dict):
        print(stock)
    

    ##############################################################
    # 모든 주식의 어제 20일선 업데이트
    # def update_stocks_trade_info_yesterday_20ma(self):
    #     for key in self.stocks.keys():
    #         yesterday_20ma = self.get_20ma(self.stocks[key]['code'], 1)
    #         # print(f"{self.stocks[key]['name']} {yesterday_20ma}")
    #         self.stocks[key]['yesterday_20ma'] = yesterday_20ma

    ##############################################################
    # 1차 매수가 구하기
    def get_buy_1_price(self, code):        
        envelope_p = self.to_percent(self.stocks[code]['envelope_p'])
        envelope_support_line = self.stocks[code]['yesterday_20ma'] * (1 - envelope_p)
        buy_1_price = envelope_support_line * self.margin_20ma
        return int(buy_1_price)

    ##############################################################
    # 1차 매수 수량 = 1차 매수 금액 / 매수가
    def get_buy_1_qty(self, code):
        return int(self.buy_1_invest_money / self.stocks[code]['buy_1_price'])    
    
    ##############################################################    
    # 2차 매수가 = 1차 매수가 - 10%
    def get_buy_2_price(self, code):
        return int(self.stocks[code]['buy_1_price'] * 0.9)

    ##############################################################
    # 2차 매수 수량 = 2차 매수 금액 / 매수가
    def get_buy_2_qty(self, code):
        return int(self.buy_2_invest_money / self.stocks[code]['buy_2_price'])

    ##############################################################
    # 매수 완료 시 호출
    def set_buy_done(self, code):
        if self.stocks[code]['buy_1_done'] == False:
            # 1차 매수 안된 경우는 1차 매수 완료
            self.stocks[code]['buy_1_done'] = True
        else:
            # 1차 매수 완료된 경우는 2차 매수 완료
            self.stocks[code]['buy_2_done'] = True
        # 1차 매수 완료 후 2차 매수 위해
        self.stocks[code]['buy_order_done'] = False            
        self.update_my_stocks_info()

    ##############################################################
    # 매도 완료 시 호출
    # 매도는 항상 전체 수량 매도 기반
    def set_sell_done(self, code):
        self.stocks[code]['sell_done'] = True
        # 매도 완료 후 종가 > 20ma 체크위해 false 처리
        self.stocks[code]['end_price_higher_than_20ma_after_sold'] = False
        self.update_my_stocks_info()
        self.clear_buy_sell_info(code)
    
    ##############################################################    
    # 매도 완료등으로 매수/매도 관려 정보 초기화 시 호출
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
        # sell_done 은 매도 완료 시에서 처리
        # self.stocks[code]['sell_done'] = 0

    ##############################################################
    # 계좌 조회하여 해당 종목의 보유 수량 리턴
    def get_stockhodings(self, code):
        #TODO
        stockhodings = 0
        return stockhodings
        
    ##############################################################
    # 평단가
    # 1차 매수가 안된 경우
    #   평단가 = 1차 매수가
    # 2차 매수까지 된 경우
    #   평단가 = ((1차 매수가 * 1차 매수량) + (2차 매수가 * 2차 매수량)) / (1차 + 2차 매수량)
    def get_avg_buy_price(self, code):
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
    def get_sell_target_price(self, code):
        sell_target_p = self.to_percent(self.stocks[code]['sell_target_p'])
        return int(self.stocks[code]['avg_buy_price'] * (1 + sell_target_p))
    
    ##############################################################
    # 현재가 리턴
    #   성공 시 현재가, 실패 시 0 리턴
    def get_curr_price(self, code):
        curr_price = 0
        PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
                "authorization": f"Bearer {self.access_token}",
                "appKey":self.config['APP_KEY'],
                "appSecret":self.config['APP_SECRET'],
                "tr_id":"FHKST01010100"}
        params = {
        "fid_cond_mrkt_div_code":"J",
        "fid_input_iscd":code,
        }
        res = requests.get(URL, headers=headers, params=params)
        if self.is_request_ok(res) == True:
            self.stocks[code]['curr_price'] = int(float(res.json()['output']['stck_prpr']))
            curr_price = self.stocks[code]['curr_price']
        else:
            self.send_message(f"[update_stock_invest_info failed]{str(res.json())}")
        return curr_price

    ##############################################################
    # 매수가 리턴
    #   1차 매수, 2차 매수 상태에 따라 매수가 리턴
    #   2차 매수까지 완료면 0 리턴
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
    def get_buy_target_qty(self, code):
        if self.stocks[code]['buy_1_done'] == False:
            # 1차 매수
            buy_target_qty = self.stocks[code]['buy_1_qty']
        elif self.stocks[code]['buy_1_done'] == False:
            # 2차 매수
            buy_target_qty = self.stocks[code]['buy_2_qty']
        else:
            # 2차 매수까지 완료 상태
            buy_target_qty = 0
        return buy_target_qty

    ##############################################################
    # 네이버 증권에서 특정 값 얻기
    # ex) https://finance.naver.com/item/main.naver?code=005930
    def crawl_naver_finance_by_selector(self, code, selector):
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        html = requests.get(url).text
        soup = BeautifulSoup(html, "html5lib")
        result = soup.select_one(selector).text
        return result
        
    ##############################################################
    # 종목 투자 정보 업데이트(시가 총액, 상장 주식 수, 저평가, BPS, PER, EPS)
    def update_stock_invest_info(self, code):
        PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
                "authorization": f"Bearer {self.access_token}",
                "appKey":self.config['APP_KEY'],
                "appSecret":self.config['APP_SECRET'],
                "tr_id":"FHKST01010100"}
        params = {
        "fid_cond_mrkt_div_code":"J",
        "fid_input_iscd":code,
        }
        res = requests.get(URL, headers=headers, params=params)
        if self.is_request_ok(res) == True:
            # 현재 PER
            self.stocks[code]['PER'] = float(res.json()['output']['per'])
            self.stocks[code]['curr_price'] = int(float(res.json()['output']['stck_prpr']))
            self.stocks[code]['capitalization'] = int(res.json()['output']['hts_avls'])         # 시가 총액(억)
            self.stocks[code]['total_stock_count'] = int(res.json()['output']['lstn_stcn'])     # 상장 주식 수
        else:
            self.send_message(f"[update_stock_invest_info failed]{str(res.json())}")
    
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
        self.stocks[code]['max_target_price'] = int((self.stocks[code]['curr_profit'] * 100000000) * self.stocks[code]['PER_E'] / self.stocks[code]['total_stock_count'])
        # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가
        # + : 저평가
        # - : 고평가
        self.stocks[code]['gap_max_sell_target_price_p'] = int(100 * (self.stocks[code]['max_target_price'] - self.stocks[code]['sell_target_price']) / self.stocks[code]['sell_target_price'])
        
        self.set_stock_undervalue(code)

    ##############################################################
    # 저평가 계산
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
            self.stocks[code]['undervalue'] += (self.stocks[code]['ROE_E'] / 10)
        
        # PER 업종 PER 대비
        if self.stocks[code]['PER'] <= 10:
            self.stocks[code]['undervalue'] += int((1 - self.stocks[code]['PER'] / self.stocks[code]['industry_PER']) * 5)
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
    # 1,2차 매수가, 20일선
    def update_stocks_trade_info(self):
        t_now = datetime.datetime.now()
        t_exit = t_now.replace(hour=15, minute=30, second=0,microsecond=0)
        for code in self.stocks.keys():
            #### 순서 변경 금지
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

        print(json.dumps(self.stocks, indent=4))

    ##############################################################
    # 보유 주식 정보 업데이트
    # 보유 주식은 stockholdings > 0
    # TODO 검증
    def update_my_stocks_info(self):
        PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
            "authorization": f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":self.config['TR_ID_GET_STOCK_BALANCE'],
            "custtype":"P",
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
        my_stocks = res.json()['output1']
        for stock in my_stocks:
            if int(stock['hldg_qty']) > 0:
                code = stock['pdno']
                # 보유 수량
                self.stocks[code]['stockholdings'] = int(stock['hldg_qty'])
                # 평단가
                self.stocks[code]['avg_buy_price'] = int(stock['pchs_avg_pric'])
                time.sleep(0.1)
        return my_stocks
                
    ##############################################################
    # 매수 여부 판단
    def is_ok_to_buy(self, code):
        # 오늘 주문 완료 시 금지
        if self.stocks[code]['buy_order_done'] == True:
            return False
        
        # 2차 매수까지 완료 시 금지
        if self.stocks[code]['buy_2_done'] == True:
            return False
        
        # 저평가 조건(X미만 매수 금지)
        if self.stocks[code]['undervalue'] < 3:
            return False
        
        # 목표 주가 GAP = (목표 주가 - 목표가) / 목표가
        # 8% 미만 매수 금지
        if self.stocks[code]['gap_max_sell_target_price'] < 8:
            return False
        
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
    # param
    #   code            종목 코드
    #   past_day        20일선 가격 기준
    #                   ex) 0 : 금일 20일선, 1 : 어제 20일선
    def get_20ma(self, code:str, past_day = 0):
        PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-price"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
            "authorization": f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":"FHKST01010400"}
        params = {
        "fid_cond_mrkt_div_code":"J",
        "fid_input_iscd":code,
        # 0 : 수정주가반영, 1 : 수정주가미반영
        "fid_org_adj_prc":"0",
        # D : (일)최근 30거래일
        # W : (주)최근 30주
        # M : (월)최근 30개월
        "fid_period_div_code":"D"
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
    # param
    #   code            종목 코드
    #   past_day        가져올 날짜 기준
    #                   ex) 0 : 금일 종가, 1 : 어제 종가
    def get_end_price(self, code:str, past_day = 0):
        PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-price"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
            "authorization": f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":"FHKST01010400"}
        params = {
        "fid_cond_mrkt_div_code":"J",
        "fid_input_iscd":code,
        # 0 : 수정주가반영, 1 : 수정주가미반영
        "fid_org_adj_prc":"0",
        # D : (일)최근 30거래일
        # W : (주)최근 30주
        # M : (월)최근 30개월
        "fid_period_div_code":"D"
        }
        res = requests.get(URL, headers=headers, params=params)
        return int(res.json()['output'][past_day]['stck_clpr'])   # 종가
    
    ##############################################################
    def get_access_token(self):
        """토큰 발급"""
        headers = {"content-type":"application/json"}
        body = {"grant_type":"client_credentials",
        "appkey" : self.config['APP_KEY'],                            
        "appsecret" : self.config['APP_SECRET']}
        PATH = "oauth2/tokenP"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        res = requests.post(URL, headers=headers, data=json.dumps(body))
        return res.json()["access_token"]

    ##############################################################
    def hashkey(self, datas):
        """암호화"""
        PATH = "uapi/hashkey"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {
        'content-Type' : 'application/json',
        'appKey' : self.config['APP_KEY'],
        'appSecret' : self.config['APP_SECRET'],
        }
        res = requests.post(URL, headers=headers, data=json.dumps(datas))
        hashkey = res.json()["HASH"]
        return hashkey

    ##############################################################
    def get_current_price(self, code:str):
        """현재가 조회"""
        PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
                "authorization": f"Bearer {self.access_token}",
                "appKey":self.config['APP_KEY'],
                "appSecret":self.config['APP_SECRET'],
                "tr_id":"FHKST01010100"}
        params = {
        "fid_cond_mrkt_div_code":"J",
        "fid_input_iscd":code,
        }
        res = requests.get(URL, headers=headers, params=params)
        return int(res.json()['output']['stck_prpr'])    

    ##############################################################
    def get_target_price(self, code:str):
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
    def get_stock_balance(self):
        """주식 잔고조회"""
        PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
            "authorization":f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":self.config['TR_ID_GET_STOCK_BALANCE'],
            "custtype":"P",
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
        self.send_message(f"====주식 보유잔고====")
        for stock in stock_list:
            if int(stock['hldg_qty']) > 0:
                stock_dict[stock['pdno']] = stock['hldg_qty']
                self.send_message(f"{stock['prdt_name']}({stock['pdno']}): {stock['hldg_qty']}주")
                time.sleep(0.1)
        self.send_message(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원")
        time.sleep(0.1)
        self.send_message(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원")
        time.sleep(0.1)
        self.send_message(f"총 평가 금액: {evaluation[0]['tot_evlu_amt']}원")
        time.sleep(0.1)
        self.send_message(f"=================")
        return stock_dict

    ##############################################################
    def get_balance(self):
        """현금 잔고조회"""
        PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        headers = {"Content-Type":"application/json", 
            "authorization":f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":self.config['TR_ID_GET_BALANCE'],
            "custtype":"P",
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
        self.send_message(f"주문 가능 현금 잔고: {cash}원")
        return int(cash)
    
    ##############################################################
    # 지정가 매수
    def buy(self, code:str, price:str, qty:str):
        PATH = "uapi/domestic-stock/v1/trading/order-cash"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        data = {
            "CANO": self.config['CANO'],
            "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
            "PDNO": code,
            # 지정가 매수
            "ORD_DVSN": "00",
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": str(int(price)),
        }
        headers = {"Content-Type":"application/json", 
            "authorization":f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":self.config['TR_ID_BUY'],
            "custtype":"P",
            "hashkey" : self.hashkey(data)
        }
        self.send_message(f"[매수 주문] {self.stocks[code]['name']} {price}원 {qty}개")
        res = requests.post(URL, headers=headers, data=json.dumps(data))
        if self.is_request_ok(res) == True:
            self.send_message(f"[매수 주문 성공]{str(res.json())}")
            return True
        else:
            self.send_message(f"[매수 주문 실패]{str(res.json())}")
            return False

    ##############################################################
    # 지정가 매도
    def sell(self, code:str, qty:str):
        PATH = "uapi/domestic-stock/v1/trading/order-cash"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        data = {
            "CANO": self.config['CANO'],
            "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
            "PDNO": code,
            # 지정가 매도
            "ORD_DVSN": "00",
            "ORD_QTY": qty,
            "ORD_UNPR": "0",
        }
        headers = {"Content-Type":"application/json", 
            "authorization":f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":self.config['TR_ID_SELL'],
            "custtype":"P",
            "hashkey" : self.hashkey(data)
        }
        res = requests.post(URL, headers=headers, data=json.dumps(data))
        if self.is_request_ok(res) == True:
            self.send_message(f"[매도 주문 성공]{str(res.json())}")
            return True
        else:
            self.send_message(f"[매도 주문 실패]{str(res.json())}")
            return False

    ##############################################################
    # 매수 처리
    #   현재가 <= 매수가면 매수
    #   단, 현재가 - 1% <= 매수가 매수가에 미리 매수 주문
    def handle_buy_stock(self):
        for code in self.stocks.keys():
            curr_price = self.get_curr_price(code)
            buy_target_price = self.get_buy_target_price(code)
            buy_target_qty = self.get_buy_target_qty(code)
            if curr_price > 0 and buy_target_price > 0:
                if curr_price * 0.99 <= buy_target_price:
                    if self.is_ok_to_buy(code) == True:
                        # 매수 주문
                        self.stocks[code]['buy_order_done'] = self.buy(code, buy_target_price, buy_target_qty)
                    else:
                        pass
                else:
                    pass
            else:
                pass
            time.sleep(0.1)

    ##############################################################
    # 매도 처리
    def handle_sell_stock(self):
        my_stocks = self.update_my_stocks_info()
        for stock in my_stocks:
            code = stock['pdno']
            qty = stock['hldg_qty']
            self.sell(code, qty)
            time.sleep(0.1)