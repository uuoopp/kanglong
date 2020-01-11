# -*- coding: utf-8 -*-

import bisect
import math
from statistics import mean
import pandas as pd
from jqdata import get_all_trade_days
from jqdata import bond
from datetime import datetime, timedelta

# 低于110元的转债我们看作低估
UNDERRATE_PRICE = 110

# 聚宽的可转债数据从2018-09-13开始记录
JQDATA_BEGIN_DATE = '2018-09-13'

# 默认可转债赔率为2.3
KELLY_ODDS = 2.3


class BoudStrategy(object):

    # 期望年化收益率10
    EXPECTED_EARN_RATE = 0.1

    # 期望5年达到平均收益
    EXPECTED_EARN_YEAR = 5

    def __init__(self, index_bond):
        self._index_bond = index_bond
        self._total_market, self._underrate_market, self._avg_price, self._avg_premium_ratio = self._index_bond.get_bonds_factors()
        self._history_factors = self._index_bond.get_bonds_history_factors()

    def get_win_rate(self):
        """
        根据110元之下转债存量比例, 平均溢价率相对历史估值以及平均收益率决定买入或卖出仓位，规则如下：
                1. 计算当前市场上所有的转债存量，比如是3000亿元，计算当前面值110元以下的存量，比如2100亿元，计算胜率为2100/3000=0.7
                2. 采用等权方式计算当前可转债指数的转债平均价格历史百分位，比如处在历史价格20%的时候，计算胜率为1-0.2=0.8
                3. 采用等权方式计算当前可转债指数的转债平均溢价率历史百分位，比如处在历史溢价10%的时候，计算胜率为1-0.1=0.9
                取其中数字最小的那个值作为胜率；比如这里的胜率就是0.7

        """
        cheap_bond_quantile = self._underrate_market / self._total_market
        premium_ratio_quantile = self._index_bond.get_quantile_of_history_factors(
                                        self._avg_premium_ratio, self._history_factors['avg_premium_ratios'])

        avg_price_quantile = self._index_bond.get_quantile_of_history_factors(
                                        self._avg_price, self._history_factors['avg_prices'])

        win_rate = min([cheap_bond_quantile, 1-premium_ratio_quantile, 1-avg_price_quantile])

        debug_msg = "当前转债存量:{:.2f}, 低估转债存量:{:.2f}，百分比:{:.2f}, 当前平均价格:{:.2f}, 百分位:{:.2f}, 当前溢价率{:.2f},百分位:{:.2f}, 胜率:{:.2f}".format(
                     self._total_market, self._underrate_market, cheap_bond_quantile,
                     self._avg_price, avg_price_quantile,
                     self._avg_premium_ratio, premium_ratio_quantile, win_rate)

        print(debug_msg)
        return win_rate

    def kelly(self):
        """
        买入时用凯利公式计算仓位:赔率固定

        买入条件:
            转债市场整体平均价格<120
            转债市场整体平均溢价率<30%
            然后我们再用胜率计算仓位


        卖出条件:
            整体收益率>30% (人工判断，目前不自动化)
            平均溢价率相对历史估值>70% (人工判断，目前不自动化)
            凯利公式仓位计算为负数

        output:
            -1 ~~ 1, -1代表清仓，0代表持仓不动， 1代表全仓买入； -0.5代表清半仓，0.5代表半仓买入

        """

        win_rate = self.get_win_rate()
        position = (KELLY_ODDS * win_rate - (1.0 - win_rate)) * 1.0 / KELLY_ODDS

        if position > 0:
            # 加仓
            if self._avg_price < 120 and self._avg_premium_ratio < 0.3:
                return position
            else:
                return 0
        else:
            # 减仓
            return position


class ConvertBondBeta(object):
    """得到指定时间的可转债基本信息，包括:
        市场总量
        低估转债(<110元)市场总量
        全部转债价格算术平均值
        全部转债溢价率算术平均值

        指定一个时间段，算出当前转债市场指标的历史百分位
    """

    def __init__(self, base_date=None, history_days=365*3):
        """
        input:
            base_date: 查询时间，格式为'yyyy-MM-dd'，默认为当天
            history_days: 默认历史区间位前3年
        """
        if not base_date:
            self._base_date = datetime.now().date()
        else:
            self._base_date = datetime.strptime(base_date, '%Y-%m-%d')

        self._begin_date = self._base_date - timedelta(history_days)
        self._end_date = self._base_date

        if self._begin_date < datetime.strptime(JQDATA_BEGIN_DATE, '%Y-%m-%d'):
            self._begin_date = datetime.strptime(JQDATA_BEGIN_DATE, '%Y-%m-%d')

        self._begin_date = self._begin_date.strftime('%Y-%m-%d')
        self._end_date = self._end_date.strftime('%Y-%m-%d')
        self._base_date = self._base_date.strftime('%Y-%m-%d')

    def get_bonds(self, date=None):
        """
        获取指定日期的可转债市场正常存续的转债的基本信息

            code: 可转债代码
            short_name: 可转债名称
            raise_fund_count: 当前存量总数量
            price: 收盘价格
            convert_premium_ratio: 转股溢价率
            convert_price: 转股价格 (如果没有下修的话就是约定转股价)
            stock_price: 正股价格
            last_cash_date: 最终兑付日(到期时间)
        """

        if date is None:
            date = self._base_date
        else:
            date = datetime.strptime(date, '%Y-%m-%d').date()

        df_bonds = bond.run_query(
                query(bond.CONBOND_BASIC_INFO).filter(
                                    bond.CONBOND_BASIC_INFO.bond_type_id == 703013,
                                    bond.CONBOND_BASIC_INFO.list_status_id.in_(['301001', '301099']),
                                    bond.CONBOND_BASIC_INFO.interest_begin_date < date,
                                    bond.CONBOND_BASIC_INFO.last_cash_date >= date
                                ).order_by('code').limit(10000)
            )

        bond_list = []

        total_market = 0.0
        for index, row in df_bonds.iterrows():
            bond_info = {
                        'code': row['code'],
                        'short_name': row['short_name'],
                        'company_code': row['company_code'],
                        'convert_price': row['convert_price'],
                        'last_cash_date': row['last_cash_date']
            }

            if str(row['list_status_id']) == '301099':
                # issue-2: CONBOND_BASIC_INO表中数据更新不及时，需要去BOND_BASIC_INFO中确认一下
                bond_basic_info = bond.run_query(
                                query(bond.BOND_BASIC_INFO).filter(
                                    bond.BOND_BASIC_INFO.code == row['code']
                                )
                              )
                if str(bond_basic_info['list_status_id'][0]) == '301099':
                    continue

            if row['list_date'] and row['list_date'] > date:
                # 只发布了信息，还没有正式上市，暂不记入
                continue

            #if bond_info['code'] == '110060':
            #    print(row)
            #else:
            #    continue

            # 发行总数量，部分转债没有实际发行价，这个时候用计划发行价来代替；一般都是100元
            if not math.isnan(row['actual_raise_fund']):
                bond_info['raise_fund_count'] = float(row['actual_raise_fund']) * 10000 / float(row['issue_par'])
            else:
                bond_info['raise_fund_count'] = float(row['plan_raise_fund']) * 10000 / float(row['issue_par'])


            # 转股信息
            bond_stock = bond.run_query(
                query(bond.CONBOND_DAILY_CONVERT).filter(
                                    bond.CONBOND_DAILY_CONVERT.code == bond_info['code'],
                                    bond.CONBOND_DAILY_CONVERT.date <= date,
                                )
            )

            # 统计转股信息，如果99%转股，就代表强赎退市，暂不记入，另外要修正存量债券数目
            if not bond_stock['acc_convert_ratio'].empty:
                if bond_stock['acc_convert_ratio'].iloc[-1] >= 99.5:
                    continue
                else:
                    bond_info['raise_fund_count'] = bond_info['raise_fund_count'] * (100.0 - bond_stock['acc_convert_ratio'].iloc[-1])

            # 先取得转股价，然后取得正股收盘价，然后计算溢价率：转股溢价=（100/转股价格）*正股收盘价-可转债收盘价）
            # 转股价如果有下修，先取得下修转股价
            if not bond_stock['convert_price'].empty:
                bond_info['convert_price'] =  float(bond_stock['convert_price'].iloc[-1])

            # 当前市场收盘价格
            bond_market = bond.run_query(
                query(bond.CONBOND_DAILY_PRICE).filter(
                                    bond.CONBOND_DAILY_PRICE.code == bond_info['code'],
                                    bond.CONBOND_DAILY_PRICE.date <= date,
                                )
            )
            try:
                bond_info['price'] =  float(bond_market['close'].iloc[-1])
            except Exception:
                # 有部分还没有公布信息的的转债用债券面值计算价格
                bond_info['price'] =  float(row['par'])




            # 获取正股价格
            df_stock_price = get_price(bond_info['company_code'],
                                       count = 7,
                                       end_date= date,
                                       frequency='daily',
                                       fields=['close'])
            bond_info['stock_price'] = df_stock_price['close'][-1]
            bond_info['convert_premium_ratio'] = (bond_info['price'] - 100/bond_info['convert_price']*bond_info['stock_price']) / (100/bond_info['convert_price']*bond_info['stock_price'])

            bond_list.append(bond_info)

        return bond_list


    def get_bonds_factors(self, bond_list=None):
        """
        获取当前时间的市场总量, 低估转债市场总量，指数平均价格，指数平均溢价率

        output:
             (total_market(元), underrate_market, avg_price, avg_premium_ratio)
        """

        if bond_list is None:
            bond_list = self.get_bonds()

        total_market = sum([bond['price'] * bond['raise_fund_count'] for bond in bond_list])
        underrate_market = sum([bond['price'] * bond['raise_fund_count'] for bond in bond_list if bond['price'] <= UNDERRATE_PRICE])
        avg_price = mean([bond['price'] for bond in bond_list])
        avg_premium_ratio = mean([bond['convert_premium_ratio'] for bond in bond_list])
        return (total_market, underrate_market, avg_price, avg_premium_ratio)


    def get_bonds_history_factors(self, interval=1):
        """
        获取任意指数一段时间的历史转债指数算术平均价格、转债指数溢价率 估值列表，通过计算当前的估值在历史估值的百分位，来判断当前市场的估值高低。
        由于加权方式可能不同，可能各个指数公开的估值数据有差异，但用于判断估值相对高低没有问题

        input：
            interval: 计算指数估值的间隔天数，增加间隔时间可提高计算性能

        output：
            result:  指数历史估值的 DataFrame，index 为时间，列为市场总量，低估转债总量，平均价格， 溢价率
        """
        all_days = get_all_trade_days()

        total_markets = []
        underrate_markets = []
        avg_prices = []
        avg_premium_ratios = []

        days = []

        begin = datetime.strptime(self._begin_date, '%Y-%m-%d').date()
        end = datetime.strptime(self._end_date, '%Y-%m-%d').date()
        i = 0
        for day in all_days:
            if(day < begin or day > end):
                continue

            i += 1

            if(i % interval != 0):
                continue

            bond_list = self.get_bonds(day)
            total_market, underrate_market, avg_price, avg_premium_ratio = self.get_bonds_factors(bond_list)
            #debug_msg = "当前转债存量:{:.2f}, 低估转债存量:{:.2f}， 当前平均价格:{:.2f}, 当前溢价率{:.2f}".format(
            #            total_market, underrate_market, avg_price, avg_premium_ratio)

            avg_prices.append(avg_price)
            avg_premium_ratios.append(avg_premium_ratio)
            total_markets.append(total_market)
            underrate_markets.append(underrate_market)
            days.append(day)

        result = pd.DataFrame(
                                {
                                    'total_markets': total_markets,
                                    'underrate_markets': underrate_markets,
                                    'avg_prices':avg_prices,
                                    'avg_premium_ratios':avg_premium_ratios
                                }, index=days
                             )
        print(result)

        return result

    def get_quantile_of_history_factors(self, factor, history_list):
        """
            获取某个因子在历史上的百分位，比如当前价格处于历史上的70%区间，意味着历史价格有70%都在当前值之下

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

import pandas as pd
from datetime import datetime, timedelta
from jqfactor import *

import warnings
warnings.filterwarnings("ignore")
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)

# 通过前一天数据计算今天仓位
base_date = (datetime.now() - timedelta(1)).strftime('%Y-%m-%d')
#base_date = datetime.now().strftime('%Y-%m-%d')
#base_date = '2018-09-13'

index_bond = ConvertBondBeta(base_date=base_date, history_days=356*3)
print(base_date)
print("=========================")

# 获取指定时间转债列表及统计值
#bond_list = index_bond.get_bonds()
#print(pd.DataFrame(bond_list))
#print(index_bond.get_bonds_factors(bond_list))

# 计算仓位
stragety = BoudStrategy(index_bond)
position = stragety.kelly()
print("推荐仓位：{}".format(position))
