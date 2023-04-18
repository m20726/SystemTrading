##############################################################
#   검증 리스트
#   1차 매수
#   2차 매수
#   매도
##############################################################

from stocks_info import *
from handle_json import *
# function overloading
from multipledispatch import dispatch
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
        # print(json.dumps(stocks_info.stocks, indent=4), ensure_ascii=False)
        
        # stocks_info.json 에 추가
        # for code in stocks_info.stocks.keys():
        #     stocks_info.stocks[code]['tot_buy_price'] = 0
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        # stocks_info.json 에 key 제거
        # for code in stocks_info.stocks.keys():
        #     del stocks_info.stocks[code]['curr_price']
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)

        stocks_info.init_config(CONFIG_FILE_PATH)
        # print(json.dumps(stocks_info.config, indent=4), ensure_ascii=False)
        
        stocks_info.access_token = stocks_info.get_access_token()
        stocks_info.get_my_cash() # 보유 현금 조회
        stocks_info.get_stock_balance()  # 보유 주식 조회
        stocks_info.update_stocks_trade_info()
        stocks_info.update_my_stocks_info()     # 보유 주식 업데이트
        stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        pre_stocks = copy.deepcopy(stocks_info.stocks)
        stocks_info.show_stocks_by_undervalue()
        
        # test
        # stocks_info.check_ordered_stocks_trade_done()
        # stocks_info.handle_sell_stock()
        # stocks_info.handle_buy_stock()        
        # stocks_info.show_order_list()
        #stocks_info.check_ordered_stocks_trade_done()
        #stocks_info.cancel_order("139480", SELL_CODE)
        #stocks_info.show_order_list()
        # return
        
        stocks_info.send_msg("===국내 주식 자동매매 프로그램을 시작합니다===")
        t_now = datetime.datetime.now()
        t_start = t_now.replace(hour=9, minute=0, second=0, microsecond=0)
        t_exit = t_now.replace(hour=15, minute=20, second=0,microsecond=0)
        today = datetime.datetime.today().weekday()
        # if today == 5 or today == 6:  # 토요일이나 일요일이면 자동 종료
        #     stocks_info.send_msg("주말이므로 프로그램을 종료합니다.")
        #     return

        sell_order_done = False
        stocks_info.show_order_list()
        
        while True:
            t_now = datetime.datetime.now()
            
            #if t_start <= t_now:                
            if 1:   # test
                # 장 시작 시 보유 종목 매도 주문
                if sell_order_done == False:
                    stocks_info.handle_sell_stock()
                    sell_order_done = True

                stocks_info.handle_buy_stock()

                # 매수/매도 체결 여부
                stocks_info.check_ordered_stocks_trade_done()
                
                # stocks 변경있으면 save stocks_info.json
                # TODO check_save_stocks_info()
                if pre_stocks != stocks_info.stocks:
                    stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
                    pre_stocks.clear()
                    pre_stocks = copy.deepcopy(stocks_info.stocks)
                
                # if t_exit < t_now:  # PM 03:20 ~ :프로그램 종료
                #     stocks_info.send_msg("프로그램을 종료합니다.")
                #     break
    
            time.sleep(1)
        
        # save stocks_info.json
       # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
    except Exception as e:
        stocks_info.send_msg(f'[exception]{e}')
        time.sleep(1)

if __name__ == "__main__":
    main()