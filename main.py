from stocks_info import *
from handle_json import *
# function overloading
from multipledispatch import dispatch
import datetime
import time


##############################################################
def main():
    try:
        stocks_info = Stocks_info()
        stocks_info.initialize()
        stocks_info.update_stocks_trade_info()
        stocks_info.update_my_stocks_info()            # 보유 주식 업데이트
        stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        # # stocks_info.json 에 추가
        # for code in stocks_info.stocks.keys():
        #     stocks_info.stocks[code]['tot_buy_price'] = 0
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        # # stocks_info.json 에 key 제거
        # for code in stocks_info.stocks.keys():
        #     del stocks_info.stocks[code]['buy_order_done']
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)

        pre_stocks = copy.deepcopy(stocks_info.stocks)
        stocks_info.show_stocks_by_undervalue()
        
        stocks_info.send_msg("===국내 주식 자동매매 프로그램을 시작합니다===")
        t_now = datetime.datetime.now()
        t_start = t_now.replace(hour=9, minute=0, second=0, microsecond=0)
        t_exit = t_now.replace(hour=15, minute=20, second=0,microsecond=0)
        today = datetime.datetime.today().weekday()
        if today == 5 or today == 6:  # 토요일이나 일요일이면 자동 종료
            stocks_info.send_msg("주말이므로 프로그램을 종료합니다.")
            return

        sell_order_done = False
        stocks_info.get_stock_balance()                # 보유 주식 조회
        
        while True:
            t_now = datetime.datetime.now()
            if t_start <= t_now:
            # if 1:   # test
                # 장 시작 시 보유 종목 매도 주문
                if sell_order_done == False:
                    stocks_info.handle_sell_stock()
                    sell_order_done = True

                stocks_info.handle_buy_stock()

                # 매수/매도 체결 여부
                stocks_info.check_ordered_stocks_trade_done()
                
                # stocks 변경있으면 save stocks_info.json
                pre_stocks = stocks_info.check_save_stocks_info(pre_stocks)
                
                if t_exit < t_now:  # PM 03:20 ~ :프로그램 종료
                    stocks_info.send_msg("프로그램을 종료합니다.")
                    break
    
            time.sleep(1)
        
        # 장 종료 후 금일 체결 조회, 잔고 조회
        stocks_info.show_trade_done_stocks(BUY_CODE)
        stocks_info.show_trade_done_stocks(SELL_CODE)
        stocks_info.get_stock_balance()
        
    except Exception as e:
        stocks_info.send_msg(f'[exception]{e}')
        time.sleep(1)

if __name__ == "__main__":
    main()