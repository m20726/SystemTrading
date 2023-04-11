from handle_json import *
# function overloading
from multipledispatch import dispatch
import requests
import datetime
import time

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
    # 모든 주식의 어제 20이평선 업데이트
    # def update_stocks_info_yesterday_20ma(self):
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
    def get_buy_1_quantity(self, code):
        return int(self.buy_1_invest_money / self.stocks[code]['buy_1_price'])    
    
    ##############################################################    
    # 2차 매수가 = 1차 매수가 - 10%
    def get_buy_2_price(self, code):
        return int(self.stocks[code]['buy_1_price'] * 0.9)

    ##############################################################
    # 2차 매수 수량 = 2차 매수 금액 / 매수가
    def get_buy_2_quantity(self, code):
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
        # 보유 수량 업데이트
        self.update_stockholdings(code)

    ##############################################################
    # 매도 완료 시 호출
    # 매도는 항상 전체 수량 매도 기반
    def set_sell_done(self, code):
        self.stocks[code]['sell_done'] = True
        self.clear_buy_sell_info(code)
    
    ##############################################################    
    # 매도 완료등으로 매수/매도 관려 정보 초기화 시 호출
    def clear_buy_sell_info(self, code):
        self.stocks[code]['yesterday_20ma'] = 0
        self.stocks[code]['buy_1_price'] = 0
        self.stocks[code]['buy_2_price'] = 0
        self.stocks[code]['buy_1_quantity'] = 0
        self.stocks[code]['buy_2_quantity'] = 0
        self.stocks[code]['buy_1_done'] = False
        self.stocks[code]['buy_2_done'] = False
        self.stocks[code]['avg_buy_price'] = 0
        self.stocks[code]['sell_target_price'] = 0
        self.stocks[code]['stockholdings'] = 0
        # sell_done 은 매도 완료 시에서 처리
        # self.stocks[code]['sell_done'] = 0
        
    ##############################################################
    # 보유 수량 업데이트
    # 매수 완료, 매도 완료등으로 보유 수량 변경 시 호출 됨
    def update_stockholdings(self, code):
        # TODO
        #self.stocks[code]['stockholdings'] = get_stockhodings(code)
        return None

    ##############################################################
    # 계좌 조회하여 해당 종목의 보유 수량 리턴
    def get_stockhodings(self, code):
        #TODO
        stockhodings = 0
        return stockhodings
        
    ##############################################################
    # 평균 단가
    # 1차 매수가 안된 경우
    #   평균 단가 = 1차 매수가
    # 2차 매수까지 된 경우
    #   평균 단가 = ((1차 매수가 * 1차 매수량) + (2차 매수가 * 2차 매수량)) / (1차 + 2차 매수량)
    def get_avg_buy_price(self, code):
        if self.stocks[code]['buy_1_done'] == True and self.stocks[code]['buy_2_done'] == True:
            # 2차 매수까지 된 경우
            tot_buy_1_money = self.stocks[code]['buy_1_price'] * self.stocks[code]['buy_1_quantity']
            tot_buy_2_money = self.stocks[code]['buy_2_price'] * self.stocks[code]['buy_2_quantity']
            tot_buy_qty = self.stocks[code]['buy_1_quantity'] + self.stocks[code]['buy_2_quantity']
            avg_buy_price = int((tot_buy_1_money + tot_buy_2_money) / tot_buy_qty)   
        else:
            # 1차 매수만 됐거나 1차 매수도 안된 경우
            avg_buy_price = self.stocks[code]['buy_1_price']
        return avg_buy_price

    ##############################################################
    # 목표가 = 평균 단가 * (1 + 목표%)
    def get_sell_target_price(self, code):
        sell_target_p = self.to_percent(self.stocks[code]['sell_target_p'])
        return int(self.stocks[code]['avg_buy_price'] * (1 + sell_target_p))
    
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
            self.stocks[code]['PER'] = float(res.json()['output']['per'])
            self.stocks[code]['EPS'] = int(float(res.json()['output']['eps']))
            self.stocks[code]['BPS'] = int(float(res.json()['output']['bps']))
            self.stocks[code]['curr_price'] = int(float(res.json()['output']['stck_prpr']))
            self.stocks[code]['capitalization'] = res.json()['output']['hts_avls']         # 시가 총액(억)
            self.stocks[code]['total_stock_count'] = res.json()['output']['lstn_stcn']     # 상장 주식 수
        else:
            self.send_message(f"[update_stock_invest_info failed]{str(res.json())}")
            
        ########## 저평가 TODO
        self.stocks[code]['undervalue'] = 0
        # BPS > 현재가
        if self.stocks[code]['BPS'] > self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] += 2
        elif self.stocks[code]['BPS'] * 1.3 < self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] -= 2
        # EPS * 10 > 현재가
        if self.stocks[code]['EPS'] * 10 > self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] += 2
        elif self.stocks[code]['EPS'] * 3 < self.stocks[code]['curr_price']:
            self.stocks[code]['undervalue'] -= 2
        # PER 업종 PER 대비 TODO
        if self.stocks[code]['PER'] < 10:
            self.stocks[code]['undervalue'] += 1
        elif self.stocks[code]['PER'] > 20:
            self.stocks[code]['undervalue'] -= (self.stocks[code]['PER'] / 10)

        self.stocks[code]['undervalue'] = int(self.stocks[code]['undervalue'])
        ########## 저평가
        
    ##############################################################
    # 주식 정보 업데이트
    # 1,2차 매수가, 평단가, 20일선, 저평가 등등
    def update_stocks_info(self):
        t_now = datetime.datetime.now()
        t_exit = t_now.replace(hour=15, minute=30, second=0,microsecond=0)
        for key in self.stocks.keys():
            #### 순서 변경 금지
            # ex) 목표가를 구하기 위해선 평균 단가가 먼저 있어야한다
            # yesterday 20이평선
            # 15:30 장마감 후는 금일기준으로 20이평선 구한다
            if t_exit < t_now:
                past_day = 0        # 장마감 후는 금일 기준
            else:
                past_day = 1        # 어제 기준
            self.stocks[key]['yesterday_20ma'] = self.get_20ma(self.stocks[key]['code'], past_day)
            # 1차 매수가
            self.stocks[key]['buy_1_price'] = self.get_buy_1_price(self.stocks[key]['code'])
            # 1차 매수 수량
            self.stocks[key]['buy_1_quantity'] = self.get_buy_1_quantity(self.stocks[key]['code'])
            # 2차 매수가
            self.stocks[key]['buy_2_price'] = self.get_buy_2_price(self.stocks[key]['code'])
            # 2차 매수 수량
            self.stocks[key]['buy_2_quantity'] = self.get_buy_2_quantity(self.stocks[key]['code'])
            # 평균 단가
            self.stocks[key]['avg_buy_price'] = self.get_avg_buy_price(self.stocks[key]['code'])
            # 목표가 = 평균 단가에서 목표% 수익가
            self.stocks[key]['sell_target_price'] = self.get_sell_target_price(self.stocks[key]['code'])
            # 보유 수량 TODO
            
            # 종목 투자 정보 업데이트(시가 총액, 상장 주식 수, 저평가, BPS, PER, EPS)
            self.update_stock_invest_info(self.stocks[key]['code'])
            # 호가 단위로 수정
            self.stocks[key]['buy_1_price'] = self.get_stock_asking_price(self.stocks[key]['buy_1_price'])
            self.stocks[key]['buy_2_price'] = self.get_stock_asking_price(self.stocks[key]['buy_2_price'])
            self.stocks[key]['sell_target_price'] = self.get_stock_asking_price(self.stocks[key]['sell_target_price'])

        print(json.dumps(self.stocks, indent=4))
        
    ##############################################################
    # 매수 여부 판단
    def is_ok_to_buy(self, code):
        # if 오늘 매수주문 안했다 and 2차매수 이하:
        #     if 최근 매도 date 있나:
        #         if 매도 후 종가 > 20ma:
        #             return True
        #         else:
        #             return False
        #     else:
        #         return True
        # else:
        #     return False
        return False

    ##############################################################
    # 20이평선 가격 리턴
    # param
    #   code            종목 코드
    #   past_day        20이평선 가격 기준
    #                   ex) 0 : 금일 20이평선, 1 : 어제 20이평선
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
        
        value_20ma = sum_end_price / 20                             # 20이평선 가격
        return int(value_20ma)
        
    ##############################################################
    # 어제 기준 20이평선 가격 리턴
    def get_yesterday_20ma(self, code:str):
        return self.get_20ma(code, 1)

    ##############################################################
    def send_message(self, msg):
        """디스코드 메세지 전송"""
        now = datetime.datetime.now()
        message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
        #requests.post(DISCORD_WEBHOOK_URL, data=message)
        print(message)
    
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
    def buy(self, code:str, qty:str):
        """주식 시장가 매수"""
        PATH = "uapi/domestic-stock/v1/trading/order-cash"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        data = {
            "CANO": self.config['CANO'],
            "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
            "PDNO": code,
            "ORD_DVSN": "01",
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": "0",
        }
        headers = {"Content-Type":"application/json", 
            "authorization":f"Bearer {self.access_token}",
            "appKey":self.config['APP_KEY'],
            "appSecret":self.config['APP_SECRET'],
            "tr_id":self.config['TR_ID_BUY'],
            "custtype":"P",
            "hashkey" : self.hashkey(data)
        }
        res = requests.post(URL, headers=headers, data=json.dumps(data))
        if self.is_request_ok(res) == True:
            self.send_message(f"[매수 성공]{str(res.json())}")
            return True
        else:
            self.send_message(f"[매수 실패]{str(res.json())}")
            return False

    ##############################################################
    def sell(self, code:str, qty:str):
        """주식 시장가 매도"""
        PATH = "uapi/domestic-stock/v1/trading/order-cash"
        URL = f"{self.config['URL_BASE']}/{PATH}"
        data = {
            "CANO": self.config['CANO'],
            "ACNT_PRDT_CD": self.config['ACNT_PRDT_CD'],
            "PDNO": code,
            "ORD_DVSN": "01",
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
            self.send_message(f"[매도 성공]{str(res.json())}")
            return True
        else:
            self.send_message(f"[매도 실패]{str(res.json())}")
            return False