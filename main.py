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
        self.stocks = dict()                # 모든 종목의 정보
        self.invest_type = "sim_invest"     # sim_invest : 모의 투자, real_invest : 실전 투자
        self.config = dict()                # 투자 관련 설정 정보
        # 어제 20 이평선 지지선 기준으로 오늘의 지지선 구하기 위한 상수
        # ex) 오늘의 지지선 = 어제 20 이평선 지지선 * 0.993
        self.margin_20ma = 0.993
        self.access_token = ""
        
    
    # self.invest_type 에 맞는 config 설정
    def init_config(self, file_path):
        configs = read_json_file(file_path)
        self.config = configs[self.invest_type]

    
    def get_stock(self, code: str):
        try:
            return self.stocks[code]
        except KeyError:
            print(f'KeyError : {code} is not found')
            return None


    def load_stock_info(self, file_path):
        self.stocks = read_json_file(file_path)


    def save_stock_info(self, file_path):
        write_json_file(self.stocks, file_path)
        
        
    @dispatch(str, str, object)
    def update_stock_info(self, code:str, key:str, value):
        try:
            self.stocks[code][key] = value
            print(self.stocks[code])
        except KeyError:
            print(f'KeyError : {code} is not found')


    @dispatch(dict)
    def update_stock_info(self, stock:dict):
        print(stock)

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


    # 20이평선 가격 리턴
    # param
    #   code            종목 코드
    #   past_day        20이평선 가격 기준
    #                   ex) 0 : 금일 20이평선, 1 : 어제 20이평선
    def get_20ma(self, code:str, past_day):
        # todo
        value_20ma = 0
        return value_20ma
        
        
    # 어제 기준 20이평선 가격 리턴
    def get_yesterday_20ma(self, code:str):
        return self.get_20ma(code, 1)


    def send_message(self, msg):
        """디스코드 메세지 전송"""
        now = datetime.datetime.now()
        message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
        #requests.post(DISCORD_WEBHOOK_URL, data=message)
        print(message)
    
    
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


    def get_target_price(self, code:str):
        """변동성 돌파 전략으로 매수 목표가 조회"""
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
        "fid_org_adj_prc":"1",
        "fid_period_div_code":"D"
        }
        res = requests.get(URL, headers=headers, params=params)
        stck_oprc = int(res.json()['output'][0]['stck_oprc']) #오늘 시가
        stck_hgpr = int(res.json()['output'][1]['stck_hgpr']) #전일 고가
        stck_lwpr = int(res.json()['output'][1]['stck_lwpr']) #전일 저가
        target_price = stck_oprc + (stck_hgpr - stck_lwpr) * 0.5
        return target_price
    
   
    def get_stock_balance(slef):
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
        if res.json()['rt_cd'] == '0':
            self.send_message(f"[매수 성공]{str(res.json())}")
            return True
        else:
            self.send_message(f"[매수 실패]{str(res.json())}")
            return False


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
        if res.json()['rt_cd'] == '0':
            self.send_message(f"[매도 성공]{str(res.json())}")
            return True
        else:
            self.send_message(f"[매도 실패]{str(res.json())}")
            return False    
    

##############################################################

def main():
    try:
        stocks_info = Stocks_info()
        stocks_info.load_stock_info(STOCK_INFO_FILE_PATH)
        # print(json.dumps(stocks_info.stocks, indent=4))
        stocks_info.init_config(CONFIG_FILE_PATH)
        # print(json.dumps(stocks_info.config, indent=4))
        
        stocks_info.access_token = stocks_info.get_access_token()
        
        stocks_info.send_message("===국내 주식 자동매매 프로그램을 시작합니다===")
        t_now = datetime.datetime.now()
        t_start = t_now.replace(hour=9, minute=0, second=0, microsecond=0)
        t_exit = t_now.replace(hour=15, minute=20, second=0,microsecond=0)
        today = datetime.datetime.today().weekday()
        if today == 5 or today == 6:  # 토요일이나 일요일이면 자동 종료
            stocks_info.send_message("주말이므로 프로그램을 종료합니다.")
            return

        while True:
            t_now = datetime.datetime.now()
            if t_start <= t_now:
                # todo 장 시작
                pass
            
            if t_exit < t_now:  # PM 03:20 ~ :프로그램 종료
                stocks_info.send_message("프로그램을 종료합니다.")
                break
            
    except Exception as e:
        stocks_info.send_message(f'[exception]{e}')
        time.sleep(1)

if __name__ == "__main__":
    main()