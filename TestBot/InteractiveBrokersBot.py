#Imports
import ibapi
from ibapi.client import EClient
from ibapi.common import BarData
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import *
import ta
import numpy as np
import pandas as pd
import pytz
import math
from datetime import datetime, timedelta
import threading
import time

#Variables
orderId = 1

#Class for Interactive Brokers Connection
class IBApi(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

    def historicalData(self, reqId: int, bar: BarData):
        try:
            bot.on_bar_update(reqId, bar, False)
        except Exception as e:
            print(e)

    #On realtime bar after historical data finishes
    def historicalDataUpdate(self, reqId: int, bar: BarData):
        try:
            bot.on_bar_update(reqId, bar, True)
        except Exception as e:
            print(e)

    #On historical data end
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        print(reqId)

    #Get next order ID we can use
    def nextValidId(self, nextorderId: int):
        global orderId
        orderId = nextorderId

    #Listen for realtime bars
    def realtimeBar(self, reqID, time, open, high, low, close, volume, wap, count):
        super().realtimeBar(reqID, time, open, high, low, close, volume, wap, count)
        try:   
            bot.on_bar_update(reqID, time, open, high, low, close, volume, wap, count)
        except Exception as e:
            print(e)

    def error(self, id, errorCode, errorMsg):
        print(errorCode)
        print(errorMsg)

#Bar object
class Bar:
    open = 0
    low = 0
    high = 0
    close = 0
    volume = 0
    date = ''
    
    def __init__(self):
        self.open = 0
        self.low = 0
        self.close = 0
        self.volume = 0
        self.date = ''

#Bot logic
class Bot:
    ib = None
    barSize = 1
    currentBar = Bar()
    bars = []
    reqId = 1
    global orderId
    smaPeriod = 50
    symbol = ""
    initialBartime = datetime.now().astimezone(pytz.timezone("America/New_York"))
    def __init__(self):
        #connect to IB on init
        self.ib = IBApi()
        self.ib.connect("127.0.0.1", 7497, 1)
        ib_thread = threading.Thread(target=self.run_loop, daemon=True)
        ib_thread.start()
        time.sleep(1)
        currentBar = Bar()
        #Get symbol
        symbol = input("Enter the symbol you want to trade: ")
        #Get bar size
        self.barSize = input("Enter the barsize you want to trade in minutes: ")
        mintext = " min"
        if (int(self.barsize) > 1):
            mintext = " mins"
        queryTime = (datetime.now().astimezone(pytz.timezone("America/New_York")) - timedelta(days = 1)).replace(hours = 16, minute = 0, second = 0, microsecond = 0).strftime("%Y%m%d %H:%M:%S")

        #Create IB contract object
        contract = Contract()
        contract.symbol = self.symbol.upper()
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        self.ib.reqIds(-1)
        #Request realtime data
        #self.ib.reqRealTimeBars(0, contract, 5, "TRADES", 1, [])
        self.ib.reqHistoricalData(self.reqId, contract, "", "2 D", str(self.barSize) + mintext, "TRADES", 1, 1, True, [])

    #seperate thread
    def run_loop(self):
        self.ib.run()

    #Bracket order setup
    def bracketOrder(self, parentOrderId, action, quantity, profitTarget, stoploss):
        #Create IB contract object
        contract = Contract()
        contract.symbol = self.symbol.upper()
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        #Create parent order
        parent = Order()
        parent.orderId = parentOrderId
        parent.orderType = "MKT"
        parent.action = action
        parent.totalQuantity = quantity
        parent.transmit = False
        #Profit target
        profitTargetOrder = Order()
        profitTargetOrder.orderId = parent.orderId + 1
        profitTargetOrder.orderType = "LMT"
        profitTargetOrder.action = "SELL"
        profitTargetOrder.totalQuantity = quantity
        profitTargetOrder.lmtPrice = round(profitTarget, 2)
        profitTargetOrder.transmit = False
        #Stop Loss 
        stopLossOrder = Order()
        stopLossOrder.orderId = parent.orderId + 2
        stopLossOrder.orderType = "STP"
        stopLossOrder.action = "SELL"
        stopLossOrder.totalQuantity = quantity
        stopLossOrder.auxPrice = round(stoploss, 2)
        stopLossOrder.transmit = True

        bracketOrders = [parent, profitTargetOrder, stopLossOrder]
        return bracketOrders


    #Pass realtime bar data back to our bot object
    def on_bar_update(self, reqID, bar, realtime):
        global orderId
        #Historical data to catch up
        if (realtime == False):
            self.bars.append(bar)
        else:
            bartime = datetime.strptime(bar.date, "%Y%m%d %H:%M:%S").astimezone(pytz.timezone("America/New_York"))
            minutes_diff = (bartime - self.initialBartime).total_seconds() / 60.0
            self.currentBar.date = bartime
            #On Bar Close
            if (minutes_diff > 0 and math.floor(minutes_diff) % self.barSize == 0):
                #Entry - If we have higher high and higher low and we cross 50 SMA
                #Calculate SMA
                closes = []
                for bar in self.bars:
                    closes.append(bar.close)

                self.close_array = pd.Series(np.asarray(closes))
                self.sma = ta.trend.sma(self.close_array, self.smaPeriod, True)
                print("SMA: " + str(self.sma[len(self.sma) - 1]))
                #Calculate Higher highs and lows
                lastLow = self.bars[len(self.bars) - 1].low
                lastHigh = self.bars[len(self.bars) - 1].high
                lastClose = self.bars[len(self.bars) - 1].close
                lastBar = self.bars[len(self.bars) - 1]
                #Check Criteria
                if (bar.close > lastHigh 
                    and self.currentBar.low > lastLow 
                    and bar.close > str(self.sma[len(self.sma) - 1])
                    and lastClose < str(self.sma[len(self.sma) - 2])):
                    #Bracket Order 2% profit target 1% stop loss
                    profitTarget = bar.close*1.02
                    stopLoss = bar.close*.99
                    quantity = 1
                    bracket = self.bracketOrder(orderId, "BUY", quantity, profitTarget, stopLoss)
                    #Create IB contract object
                    contract = Contract()
                    contract.symbol = self.symbol.upper()
                    contract.secType = "STK"
                    contract.exchange = "SMART"
                    contract.currency = "USD"
                    #place bracket order
                    for o in bracket:
                        o.ocaGroup = "OCA_" + str(orderId)
                        o.ocaType = 2
                        self.ib.placeOrder(o.orderId, o.contract, o)
                    orderId += 3
                #Bar closed append
                self.currentBar.close = bar.close
                if (self.currentBar.date != lastBar.date):
                    print("New Bar!")
                    self.bars.append(self.currentBar)
                self.currentBar.open = bar.open
        #Build realtime bar
        if (self.currentBar.open == 0):
            self.currentBar.open = bar.open
        if(self.currentBar.high == 0 or bar.high > self.currentBar.high):
            self.currentBar.high = bar.high
        if(self.currentBar.low == 0 or bar.low > self.currentBar.low):
            self.currentBar.low = bar.low


#start bot
bot = Bot()
