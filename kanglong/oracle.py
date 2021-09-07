# -*- coding: utf-8 -*-

"""简单的每日回测工具脚本"""

import bisect
from jqdata import get_all_trade_days
from datetime import datetime, timedelta

class KLYHStrategy(object):

    # 期望年化收益率15%
    EXPECTED_EARN_RATE = 0.15

    # 期望5年达到平均收益
    EXPECTED_EARN_YEAR = 5

    def __init__(self, index_stock):
        self._index_stock = index_stock
        self._pe, self._pb, self._roe = self._index_stock.get_index_beta_factor()
        self._history_factors = self._index_stock.get_index_beta_history_factors()

    def get_trading_position(self, national_debt_rate=0.035):
        """
        根据pe, pb的绝对值以及相对历史估值决定买入或卖出仓位，规则如下：

        买入条件:
            市场出现系统性低估机会可以买入 (市场出现PE<7、PB<1、股息率>5% (ROE>18%)的品种)，此时满仓(100%)
            单一标的PE、PB 处于历史30%以下可以买入
            PE处于历史30%以下，且PB<1.5可以买入
            PB处于历史30%以下，且PE<10 或 1/PE<十年期国债利率X2，可以买入

        卖出条件:
            市场出现系统性高估机会可以卖出 (市场整体50 PE，整体PB>4.5)，此时清仓(-100%)
            单一标的PE、PB 处于历史70%以上可以卖出
            PE处于历史70%以上，且PB>2可以卖出
            PB处于历史70%以上，且PE>25可以卖出
            1/PE<市场能找到的最小无风险收益率(简单的用国债利率X3)，可以卖出置换

        input:
            national_debt_rate: 当前国债利率

        output:
            -1 ~~ 1, -1代表清仓，0代表持仓不动， 1代表全仓买入； -0.5代表清半仓，0.5代表半仓买入
        """
        pe_quantile = self._index_stock.get_quantile_of_history_factors(
                                        self._pe, self._history_factors['pe'])
        pb_quantile = self._index_stock.get_quantile_of_history_factors(
                                        self._pb, self._history_factors['pb'])

        avg_roe = self._history_factors['roe'].mean()

        debug_msg = "当前PE:{:.2f},百分位:{:.2f}，当前PB{:.2f},百分位:{:.2f},平均ROE:{:.2f}, 国债利率:{},推荐仓位:".format(self._pe,
                               pe_quantile, self._pb, pb_quantile, avg_roe, national_debt_rate)

        # 当市场出现系统性机会时，满仓或清仓
        if self._pe<7.0 and self._pb<1.0 and self._pb/self._pe>0.18:
            print(debug_msg + '1.0')
            return 1.0

        if self._pe>50.0 or self._pb>4.5:
            print(debug_msg + '-1.0')
            return -1.0

        if (pe_quantile<0.3 and pb_quantile<0.3 and self._pb<2) or \
           (pb_quantile<0.3 and 1.0/self._pe>national_debt_rate*3) or \
           (pe_quantile<0.1 and pb_quantile<0.1):
            position =  self.kelly(self._pe, avg_roe, national_debt_rate, action=1)
            print("{}{:.2f}".format(debug_msg, position))
            return position

        if (pe_quantile>0.7 and pb_quantile>0.7) or \
           (1.0/self._pe<national_debt_rate*2):
            position = self.kelly(self._pe, avg_roe, national_debt_rate, action=0)
            print("{}{:.2f}".format(debug_msg, position))
            return position
        print(debug_msg)
        return 0

    def kelly(self, pe, history_avg_roe, national_debt_rate, action=1):
        """
        买入时用凯利公式计算仓位：https://happy123.me/blog/2019/04/08/zhi-shu-tou-zi-ce-lue/
        卖出时简单的用 70% 清仓0.5成， 80%清仓2成，90%清仓3成

        input:
            pe: 当前pe
            history_avg_roe: 历史平均roe
            history_pes: 历史PE数据集合
            national_debt_rate: 当前国债利率
            action=1代表买， action=0代表卖
        """


        pe_quantile = self._index_stock.get_quantile_of_history_factors(
                                        pe, self._history_factors['pe'])
        position = 0
        if action == 0:
            if pe_quantile>=0.8 and pe_quantile<0.85:
                position = -0.02
            elif pe_quantile>=0.85 and pe_quantile<0.9:
                position = -0.1
            elif pe_quantile>=0.9 and pe_quantile<0.95:
                position = -0.3
            elif pe_quantile>=0.95 and pe_quantile<0.97:
                position = -0.5
            elif pe_quantile>=0.97 and pe_quantile<0.99:
                position = -0.7
            elif pe_quantile>=0.99:
                position = -1
            else:
                pass
            return position
        else:
            odds = pow(1 + self.EXPECTED_EARN_RATE, self.EXPECTED_EARN_YEAR)
            except_sell_pe = odds / pow(1+history_avg_roe, self.EXPECTED_EARN_YEAR) * pe

            win_rate = 1.0 - self._index_stock.get_quantile_of_history_factors(except_sell_pe,
                                                                               self._history_factors['pe'])
            print('历史平均roe:{},期待pe:{}, 胜率:{}, 赔率:{}'.format(history_avg_roe, except_sell_pe, win_rate, odds))

            position = (odds * win_rate - (1.0 - win_rate)) * 1.0 / odds
            return position if position > 0 else 0

class IndexStockBeta(object):

    def __init__(self, index_code, index_type=0, base_date=None, history_days=365*8):
        """
        input:
            index_code: 要查询指数的代码
            index_type: 1为等权重方式计算，0为按市值加权计算
            base_date: 查询时间，格式为'yyyy-MM-dd'，默认为当天
            history_days: 默认历史区间位前八年
        """
        self._index_code = index_code
        self._index_type = index_type
        if not base_date:
            self._base_date = datetime.now().date()
        else:
            self._base_date = datetime.strptime(base_date, '%Y-%m-%d')

        self._begin_date = self._base_date - timedelta(history_days)
        self._end_date = self._base_date

        self._begin_date = self._begin_date.strftime('%Y-%m-%d')
        self._end_date = self._end_date.strftime('%Y-%m-%d')
        self._base_date = self._base_date.strftime('%Y-%m-%d')

    def get_index_beta_factor(self, day=None):
        """
        获取当前时间的pe, pb值

        input:
            day: datetime.date类型，如果为None，默认代表取当前时间

        output:
            (pe, pb, roe)
        """
        if not day:
            day = datetime.strptime(self._base_date, '%Y-%m-%d')

        stocks = get_index_stocks(self._index_code, day)
        q = query(
            valuation.pe_ratio, valuation.pb_ratio, valuation.circulating_market_cap
        ).filter(
            valuation.code.in_(stocks)
        )

        df = get_fundamentals(q, day)

        df = df[df['pe_ratio']>0]

        if len(df)>0:
            if(self._index_type == 0):
                pe = df['circulating_market_cap'].sum() / (df['circulating_market_cap']/df['pe_ratio']).sum()
                pb = df['circulating_market_cap'].sum() / (df['circulating_market_cap']/df['pb_ratio']).sum()
            else:
                pe = df['pe_ratio'].size / (1/df['pe_ratio']).sum()
                pb = df['pb_ratio'].size / (1/df['pb_ratio']).sum()
            return (pe, pb, pb/pe)
        else:
            return (None, None, None)

    def get_index_beta_history_factors(self, interval=7):
        """
        获取任意指数一段时间的历史 pe,pb 估值列表，通过计算当前的估值在历史估值的百分位，来判断当前市场的估值高低。
        由于加权方式可能不同，可能各个指数公开的估值数据有差异，但用于判断估值相对高低没有问题

        input：
            interval: 计算指数估值的间隔天数，增加间隔时间可提高计算性能

        output：
            result:  指数历史估值的 DataFrame，index 为时间，列为pe，pb,roe
        """
        all_days = get_all_trade_days()

        pes = []
        roes = []
        pbs = []
        days = []

        begin = datetime.strptime(self._begin_date, '%Y-%m-%d').date()
        end = datetime.strptime(self._end_date, '%Y-%m-%d').date()
        i = 0
        for day in all_days:
            if(day <= begin or day >= end):
                continue

            i += 1

            if(i % interval != 0):
                continue

            pe, pb, roe = self.get_index_beta_factor(day)
            if pe and pb and roe:
                pes.append(pe)
                pbs.append(pb)
                roes.append(roe)
                days.append(day)

        result = pd.DataFrame({'pe':pes,'pb':pbs, 'roe':roes}, index=days)
        return result

    def get_quantile_of_history_factors(self, factor, history_list):
        """
            获取某个因子在历史上的百分位，比如当前PE处于历史上的70%区间，意味着历史PE有70%都在当前值之下

        input:
            factor: beta因子
            history_list: 历史估值列表, DataFrame

        output:
            quantile: 历史估值百分位 (0.7)
        """
        factors = [history_list.quantile(i / 10.0)  for i in range(11)]
        idx = bisect.bisect(factors, factor)
        if idx < 10:
            quantile = idx - (factors[idx] - factor) / (factors[idx] - factors[idx-1])
            return quantile / 10.0
        else:
            return 1.0

# 测试
# 测试

import pandas as pd
from datetime import datetime, timedelta
from jqfactor import *

import warnings
warnings.filterwarnings("ignore")


index_stocks = {
    '399902.XSHE':'中证流通',
    '000985.XSHG':'中证全指',
    '000906.XSHG':'中证800',    #515810.OF 易方达中证800ETF
    '000925.XSHG':'基本面50',   #160716.OF 嘉实基本面50指数，规模小，费率高，成分股金融地产占比太高，除非极端情况，否则不考虑
    '000016.XSHG':'上证50',     #110003.OF 易方达上证50指数, 501050,华夏上证50AH优选指数
    '000300.XSHG':'沪深300',    #000176.OF 嘉实沪深300增强

    '000905.XSHG':'中证500',    #161017.OF 富国中证500增强
    #'512260.XSHG':'低波500',    #003318.OF 景顺长城中证500低波动

    '000015.XSHG':'上证红利',
    '000919.XSHG':'300价值',    #310398.OF 申万沪深300价值
    '000922.XSHG':'中证红利',   #100032.OF 富国中证红利
    '399324.XSHE':'深证红利',   #481012.OF 工银深证红利联接
    '399702.XSHE':'深证F120',   #070023.OF 嘉实深F120基本面联接
    '399978.XSHE':'中证医药100',#001550.OF 天弘中证医药100
    '000932.XSHG':'中证消费',   #000248.OF 汇添富中证主要消费ETF联接, 只看PE百分位<30%时买入
    '000942.XSHG': '中证内地消费',
    '000807.XSHG':'食品饮料',   #001631.OF 天弘中证食品饮料
    '399006.XSHE':'创业板指',   #110026.OF 易方达创业板ETF联接
    '000992.XSHG':'全指金融',   #001469.OF 广发金融地产联接
    '399986.XSHE':'中证银行',   #001594.OF 天弘中证银行A

    # 周期性行业，长久来看价值不高，除非特别特别低 百里挑一才能入场
    '399812.XSHE':'中证养老',   #000968.OF 广发中证养老指数
    '399971.XSHE':'中证传媒',   #004752.OF 广发中证传媒ETF联接A
    '000827.XSHG':'中证环保',   #001064.OF 广发中证环保ETF联接A
    '399959.XSHE':'军工指数',   #512660.OF 国泰军工指数
    '399393.XSHE':'国证地产',   #160218.OF 国泰国证房地产行业指数
    '399975.XSHE':'中证全指证券公司' #502010.OF 易方达证券公司分级
}

for index_code, index_name in index_stocks.items():
    base_date = (datetime.now() - timedelta(1)).strftime('%Y-%m-%d')
    #base_date = '2014-05-10' # 后视镜市场低点
    #base_date = '2015-03-1'  # 退场时间
    #base_date = '2015-06-10' # 后视镜市场高点
    #base_date = '2016-01-30' # 后视镜市场低点
    #base_date = '2019-01-30' # 后视镜市场低点
    #base_date = '2018-01-01' # 后视镜市场下行之初
    #base_date = '2018-11-30' # 后视镜消费最低点
    #base_date = '2019-05-15' # 长赢抛出消费
    #base_date = '2020-03-09' # 长赢抛出创业
    #base_date = '2020-03-23' # 后视镜红利最低点
    #base_date = '2020-06-23' # 后视镜红利最低点
    #base_date = '2018-02-28' # 后视镜2018年熊市开端
    stock = IndexStockBeta(index_code, base_date=base_date, index_type=0, history_days=365*5)
    print("市值加权:{}:============{}=============".format(base_date, index_name))
    stragety = KLYHStrategy(stock)
    print(stragety.get_trading_position())

    stock = IndexStockBeta(index_code, base_date=base_date, index_type=1, history_days=365*5)
    print("市值等权{}:============{}=============".format(base_date, index_name))
    stragety = KLYHStrategy(stock)
    print(stragety.get_trading_position())

