from stocks_info import *
from handle_json import *
# function overloading
from multipledispatch import dispatch
import requests
import datetime
import time

STOCKS_INFO_FILE_PATH = './stocks_info.json'
# APP_KEY, APP_SECRET 등 투자 관련 설정 정보
CONFIG_FILE_PATH = './config.json'


##############################################################
def main():
    try:
        stocks_info = Stocks_info()
        stocks_info.load_stocks_info(STOCKS_INFO_FILE_PATH)
        # print(json.dumps(stocks_info.stocks, indent=4))
        stocks_info.init_config(CONFIG_FILE_PATH)
        # print(json.dumps(stocks_info.config, indent=4))
        
        stocks_info.access_token = stocks_info.get_access_token()
        
        # total_cash = stocks_info.get_balance() # 보유 현금 조회
        # stock_dict = stocks_info.get_stock_balance()  # 보유 주식 조회
        # print(stocks_info.get_current_price(stocks_info.stocks["068270"]["code"]))
        
        # print(stocks_info.get_yesterday_20ma(stocks_info.stocks["005930"]["code"]))
        
        # 모든 주식의 어제 20이평선 업데이트
        # stocks_info.update_stocks_info_yesterday_20ma()
        
        stocks_info.update_stocks_info()
        
        # stocks_info.send_message("===국내 주식 자동매매 프로그램을 시작합니다===")
        # t_now = datetime.datetime.now()
        # t_start = t_now.replace(hour=9, minute=0, second=0, microsecond=0)
        # t_exit = t_now.replace(hour=15, minute=20, second=0,microsecond=0)
        # today = datetime.datetime.today().weekday()
        # if today == 5 or today == 6:  # 토요일이나 일요일이면 자동 종료
        #     stocks_info.send_message("주말이므로 프로그램을 종료합니다.")
        #     return

        # while True:
        #     t_now = datetime.datetime.now()
        #     if t_start <= t_now:
        #         # todo 장 시작
        #         pass

        # 매수 완료 여부
        # TODO 매수 주문 후 매수 완료 여부 체크하여 세팅
        #     if check_buy_done() == True:
        #       stocks_info.set_set_buy_done(self.stocks[key]['code'])
        #     if check_sell_done() == True:
        #       stocks_info.set_set_sell_done(self.stocks[key]['code'])

        #     if t_exit < t_now:  # PM 03:20 ~ :프로그램 종료
        #         stocks_info.send_message("프로그램을 종료합니다.")
        #         break
        
        # save stocks_info.json
        stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
    except Exception as e:
        stocks_info.send_message(f'[exception]{e}')
        time.sleep(1)

if __name__ == "__main__":
    main()