from stocks_info import *
from handle_json import *
import datetime
import time

SATURDAY = 5
SUNDAY = 6

##############################################################
def main():
    try:
        stocks_info = Stocks_info()
        stocks_info.initialize()
        
        stocks_info.update_stocks_trade_info()
        stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        stocks_info.get_stock_balance()        
        stocks_info.update_my_stocks()            # 보유 주식 업데이트
        stocks_info.update_buyable_stocks()
        stocks_info.show_buyable_stocks()
        stocks_info.show_stocks_by_undervalue()

        # # stocks_info.json 에 추가
        # for code in stocks_info.stocks.keys():
        #     stocks_info.stocks[code]['sell_target_p_long_ma_up'] = 10
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        # # stocks_info.json 에 key 제거
        # for code in stocks_info.stocks.keys():
        #     del stocks_info.stocks[code]['long_ma_up']
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)

        # # stocks_info.json 변경
        # for code in stocks_info.stocks.keys():
        #     stocks_info.stocks[code]['envelope_p'] = 4
        #     stocks_info.stocks[code]['sell_target_p'] = 4
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        stocks_info.send_msg("===국내 주식 자동매매 프로그램을 시작===")
        pre_stocks = copy.deepcopy(stocks_info.stocks)
        t_now = datetime.datetime.now()
        t_start = t_now.replace(hour=9, minute=0, second=0, microsecond=0)
        t_exit = t_now.replace(hour=15, minute=30, second=0,microsecond=0)
        today = datetime.datetime.today().weekday()
        if today == SATURDAY or today == SUNDAY:  # 토요일이나 일요일이면 자동 종료
            stocks_info.send_msg("주말이므로 프로그램을 종료")
            return

        sell_order_done = False        
        
        while True:
            t_now = datetime.datetime.now()
            if t_start <= t_now:
                if t_exit < t_now:  # PM 03:30 ~ 장 종료
                    stocks_info.send_msg("장 종료")
                    break
            
                # # test, 시장가 매도
                # if sell_order_done == False:
                #     stocks_info.handle_sell_stock(ORDER_TYPE_MARGET_ORDER)
                #     sell_order_done = True

                if SELL_STRATEGY == 1:
                    # 장 시작 시 보유 종목 매도 주문
                    if sell_order_done == False:
                        stocks_info.handle_sell_stock()
                        sell_order_done = True
                else:
                    stocks_info.handle_sell_stock()
                
                stocks_info.handle_buy_stock()
                stocks_info.handle_loss_cut()

                # 매수/매도 체결 여부
                stocks_info.check_ordered_stocks_trade_done()
                
                # stocks 변경있으면 save stocks_info.json
                pre_stocks = stocks_info.check_save_stocks_info(pre_stocks)
                
                # 주기적으로 출력
                if (t_now.minute % 31 == 0) and (t_now.second == 0):            
                    stocks_info.show_buyable_stocks()
                    # stocks_info.get_stock_balance()
                    time.sleep(1)
        
        # 장 종료 후 처리
        stocks_info.update_my_stocks()
        stocks_info.update_buy_qty_after_market_finish()            # 일부만 매수 됐을 때 처리
        stocks_info.show_stocks_by_undervalue()                     # 저평가
        stocks_info.show_trade_done_stocks(BUY_CODE)
        stocks_info.show_trade_done_stocks(SELL_CODE)
        stocks_info.get_stock_balance(True)
        stocks_info.clear_after_market()
        stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        stocks_info.send_msg("프로그램 종료")
        
        # # test
        # while True:
        #     time.sleep(1)
            
    except Exception as e:
        stocks_info.send_msg(f'[exception]{e}')
        time.sleep(1)

if __name__ == "__main__":
    main()