from stocks_info import *
from handle_json import *
import time
from libs.debug import *
import datetime
import threading
from define import *

PERIODIC_PRINT_TIME_M = 30      # 30분마다 주기적으로 출력

##############################################################
# buy, sell 처리 thread
#   main thread 에서 돌리면 update_buyable_stocks 등의 함수에서 
#   시간이 오려 걸려 그 동안 buy, sell 처리 못한다
#   이를 방지하기 위해 buy, sell 은 thread 로 뺀다
#   단, python 의 GIL 특성 상 한 순간에 하나의 thread 만 처리된다.
#   main thread 와 buy_sell_task 가 context switching 하면서 번갈아 실행된다.
# Parameter :
#       stocks_info     Stocks_info 객체
#       stop_event      thread 종료 event 객체
##############################################################
def buy_sell_task(stocks_info: Stocks_info, stop_event: threading.Event):
    result = True
    msg = ""
    try:
        while not stop_event.is_set():
            stocks_info.handle_sell_stock()
            stocks_info.handle_buy_stock()
            time.sleep(0.001)   # context switching
    except Exception as ex:
        result = False
        msg = "{}".format(traceback.format_exc())
    finally:
        if not result:
            stocks_info.SEND_MSG_ERR(msg)

##############################################################
def main():
    result = True
    msg = ""
    try:
        PRINT_DEBUG("=== Program Start ===")

        if TODAY == SATURDAY or TODAY == SUNDAY:  # 토요일이나 일요일이면 자동 종료
            PRINT_DEBUG("=== Weekend, Program End ===")
            return
        
        t_now = datetime.datetime.now()

        stocks_info = Stocks_info()        
        stocks_info.initialize()

        # # stocks_info.json 에 추가/변경
        # for code in stocks_info.stocks.keys():
        #     stocks_info.stocks[code]['wait_buy_up_candle_date'] = None
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)
        
        # # stocks_info.json 에 key 제거
        # for code in stocks_info.stocks.keys():
        #     del stocks_info.stocks[code]['sell_qty'][3]
        #     del stocks_info.stocks[code]['sell_qty'][2]
        #     del stocks_info.stocks[code]['sell_done'][3]
        #     del stocks_info.stocks[code]['sell_done'][2]
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)

        # # 주식 정보 업데이트
        # stocks_info.update_stocks_trade_info()
        # stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)

        stocks_info.update_my_stocks()              # 보유 주식 업데이트
        # stocks_info.show_stocks(False)
        stocks_info.get_stock_balance()

        # 장 종료 후는 매수 가능 종목 불필요
        if t_now < T_MARKET_END:
            stocks_info.update_buyable_stocks()
            stocks_info.show_buyable_stocks()

        pre_stocks = copy.deepcopy(stocks_info.stocks)

        # 주기적으로 출력 여부
        allow_periodic_print = True

        # buy 와 sell 은 delay 되면 안된다. thread 에서 처리
        # thread 종료 이벤트 객체 생성
        stop_event = threading.Event()
        worker_thread = threading.Thread(target=buy_sell_task, args=(stocks_info, stop_event))

        while True:
            t_now = datetime.datetime.now()
            if T_MARKET_START <= t_now:
                if T_PROGRAM_EXIT < t_now:  # 종료
                    PRINT_DEBUG(f"=== Exit loop {t_now} ===")
                    break
                elif stocks_info.trade_strategy.loss_cut_time == LOSS_CUT_MARKET_CLOSE and T_LOSS_CUT < t_now:  # 종가 매매
                    stocks_info.handle_loss_cut()

                if T_MARKET_END_ORDER_CHECK < t_now:
                    # 미체결 주문 없으면 종료
                    if len(stocks_info.get_order_list("02")) == 0:
                        PRINT_DEBUG(f"=== Exit loop {t_now} ===")
                        break
                
                # thread start 는 한 번만 호출
                if not worker_thread.is_alive():
                    worker_thread.start()

                # 시장 폭락 시 좀 더 보수적으로 대응
                # 폭락에 가까울 때 자주 체크
                if stocks_info.market_profit_p < (stocks_info.market_crash_profit_p/2):
                    stocks_info.check_market_crash()
                else:
                    # 폭락 전에는 PERIODIC_PRINT_TIME_M 단위로 체크, 자주 체크할 필요 없다
                    if t_now.minute % PERIODIC_PRINT_TIME_M == 0:
                        stocks_info.check_market_crash()

                # 매수/매도 체결 여부
                stocks_info.check_ordered_stocks_trade_done()
                
                # stocks 변경있으면 save stocks_info.json
                pre_stocks = stocks_info.check_save_stocks_info(pre_stocks)
                
                # 주기적으로 출력
                if (t_now.minute % PERIODIC_PRINT_TIME_M == 0) and allow_periodic_print:
                    allow_periodic_print = False
                    stocks_info.show_buyable_stocks()
                    stocks_info.get_stock_balance()
                elif t_now.minute % PERIODIC_PRINT_TIME_M == 1:
                    allow_periodic_print = True

            time.sleep(0.001)   # context switching between threads(main thread 와 buy_sell_task 가 context switching)
        
        # Loop 종료
        stocks_info.check_ordered_stocks_trade_done()   # Loop 종료 후 체결 처리
        stocks_info.update_my_stocks()
        # stocks_info.show_stocks(True)
        stocks_info.show_trade_done_stocks(BUY_CODE)
        stocks_info.show_trade_done_stocks(SELL_CODE)
        stocks_info.get_stock_balance(True)
        stocks_info.clear_after_market()
        
        # 종료 이벤트 설정하여 thread 종료
        stop_event.set()
        
        if worker_thread.is_alive():
            # thread 완료까지 대기
            worker_thread.join()

        # Loop 종료 후 주식 정보 업데이트
        stocks_info.update_stocks_trade_info()
        stocks_info.save_stocks_info(STOCKS_INFO_FILE_PATH)

        stocks_info.update_buyable_stocks()
        stocks_info.show_buyable_stocks()
        
        PRINT_DEBUG("=== Program End ===")
    except Exception as ex:
        result = False
        msg = "{}".format(traceback.format_exc())
    finally:
        if not result:
            stocks_info.SEND_MSG_ERR(msg)        
        time.sleep(1)

if __name__ == "__main__":
    main()