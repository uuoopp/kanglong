#!/usr/bin/env python
# coding: utf-8

# In[1]:


import bisect
import copy
import logging
import math
from statistics import mean
import pandas as pd
from jqdata import get_all_trade_days
from jqdata import bond
from datetime import datetime, timedelta

logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s', level=logging.DEBUG)

# 低于110元的转债我们看作低估
UNDERRATE_PRICE = 110

# 聚宽的可转债数据从2018-09-13开始记录
JQDATA_BEGIN_DATE = '2018-09-13'


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
            raise_fund_volume: 发行总量(元)
            current_fund_volume: 当前存量总量(元)
            price: 收盘价格
            day_market_volume: 当日市场成交总价
            convert_premium_ratio: 转股溢价率
            convert_price: 转股价格 (如果没有下修的话就是约定转股价)
            stock_price: 正股价格
            last_cash_date: 最终兑付日(到期时间)
            double_low: 转债价格+溢价率X100
            ytm: 计算方式比较复杂，暂缺失
        """

        if date is None:
            date = datetime.strptime(self._base_date, '%Y-%m-%d').date()
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
                        'stock_code': row['company_code'],
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
                    # 未上市
                    continue

            if row['list_date'] and row['list_date'] > date:
                # 只发布了信息，还没有正式上市，暂不记入
                continue


            # 发行总量(万元)
            if not math.isnan(row['actual_raise_fund']):
                bond_info['raise_fund_volume'] = float(row['actual_raise_fund']) * 10000
            else:
                bond_info['raise_fund_volume'] = float(row['plan_raise_fund']) * 10000
            bond_info['current_fund_volume'] = bond_info['raise_fund_volume']

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
                    bond_info['current_fund_volume'] = bond_info['raise_fund_volume'] *                             (100.0 - bond_stock['acc_convert_ratio'].iloc[-1]) / 100.0

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
                bond_info['day_market_volume'] = float(bond_market['money'].iloc[-1])
            except Exception:
                # 有部分还没有公布信息的先跳过
                bond_info['price'] =  float(row['par'])
                continue

            if bond_info['price'] < 1:
                # 停牌
                continue


            # 获取正股价格
            df_stock_price = get_price(bond_info['stock_code'],
                                       count = 7,
                                       end_date= date,
                                       frequency='daily',
                                       fields=['close'])
            bond_info['stock_price'] = df_stock_price['close'][-1]
            bond_info['convert_premium_ratio'] = (bond_info['price'] - 100/bond_info['convert_price']*bond_info['stock_price']) /                                                  (100/bond_info['convert_price']*bond_info['stock_price'])
            bond_info['double_low'] = bond_info['price'] + bond_info['convert_premium_ratio'] * 100

            bond_list.append(bond_info)

        bond_list = sorted(bond_list, key=lambda x: x['double_low'])
        return bond_list


    def get_bonds_factors(self, bond_list=None):
        """
        获取当前时间的市场总量, 低估转债市场总量，指数平均价格，指数平均溢价率

        output:
             (total_market(元), underrate_market, avg_price, avg_premium_ratio)
        """

        if bond_list is None:
            bond_list = self.get_bonds()

        total_market = sum([bond['current_fund_volume'] for bond in bond_list])
        underrate_market = sum([bond['current_fund_volume'] for bond in bond_list if bond['price'] <= UNDERRATE_PRICE])
        avg_price = mean([bond['price'] for bond in bond_list])
        avg_premium_ratio = mean([bond['convert_premium_ratio'] for bond in bond_list])
        return (total_market, underrate_market, avg_price, avg_premium_ratio)




# In[2]:


class StockBeta(object):

    def __init__(self, stock_code, index_type=0, base_date=None, history_days=365*5):
        """
        input:
            index_code: 要查询指数的代码
            index_type: 1为等权重方式计算，0为按市值加权计算
            base_date: 查询时间，格式为'yyyy-MM-dd'，默认为当天
            history_days: 默认历史区间位前八年
        """
        self._stock_code = stock_code
        self._index_type = index_type
        if not base_date:
            self._base_date = datetime.now().date() - timedelta(1)
        else:
            self._base_date = datetime.strptime(base_date, '%Y-%m-%d')

        self._begin_date = self._base_date - timedelta(history_days)
        self._end_date = self._base_date

        self._begin_date = self._begin_date.strftime('%Y-%m-%d')
        self._end_date = self._end_date.strftime('%Y-%m-%d')
        self._base_date = self._base_date.strftime('%Y-%m-%d')

    def get_stock_beta_factor(self, day=None):
        """
        获取当前时间的pe, pb值

        input:
            day: datetime.date类型，如果为None，默认代表取当前时间

        output:
            (pe, pb, roe)
        """
        if not day:
            day = datetime.strptime(self._base_date, '%Y-%m-%d')

        stocks = [self._stock_code]
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

    def get_stock_beta_history_factors(self, interval=7):
        """
        获取任意指数一段时间的历史 pe,pb 估值列表，通过计算当前的估值在历史估值的百分位，来判断当前市场的估值高低。
        由于加权方式可能不同，可能公开的估值数据有差异，但用于判断估值相对高低没有问题

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

            pe, pb, roe = self.get_stock_beta_factor(day)
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


# In[3]:


class DLowStrategy(object):

    # 双低策略转债个数
    EXPECTED_ITEMS_COUNT = 20

    def __init__(self, bond_list):
        self._bond_list = copy.deepcopy(bond_list)

    def _set_stock_info(self, bond_list):
        """增加正股估值信息

            stock_pb: pb
            stock_pe: pe
            stock_pb_quantile: pb百分位
            stock_pe_quantile: pe百分位
        """
        for bond in bond_list:
            stock = StockBeta(bond['stock_code'])
            bond['stock_pe'], bond['stock_pb'], bond['stock_roe'] = stock.get_stock_beta_factor()

            if bond['stock_pe'] is None or bond['stock_pb'] is None:
                # 正股报表有问题，剔除
                self._bond_list.remove(bond)
                continue

            history_factors = stock.get_stock_beta_history_factors()
            bond['stock_pb_quantile'] = stock.get_quantile_of_history_factors(
                                                bond['stock_pb'], history_factors['pb'])
            bond['stock_pe_quantile'] = stock.get_quantile_of_history_factors(
                                                bond['stock_pe'], history_factors['pe'])

    def _filter_pb_pe_quantile(self, bond_list):
        """筛选pb, pe历史百分位小于50%
        """
        self._set_stock_info(bond_list)
        filter_bond_list = filter(
            lambda x: x['stock_pb'] > 1.3 and x['stock_pb_quantile'] < 0.5 and x['stock_pe_quantile'] < 0.5,
            bond_list
        )
        return list(filter_bond_list)

    def _filter_pb(self, bond_list):
        """筛选PB>1.3防止下修转股价时破净限制
        """
        self._set_stock_info(bond_list)
        filter_bond_list = filter(
            lambda x: x.get('stock_pb', None) and x['stock_pb'] > 1.3,
            bond_list
        )
        return list(filter_bond_list)



    def _filter_current_fund_volume(self, bond_list):
        """剩余规模>1亿，且<10亿元的转债
        """
        filter_bond_list = filter(
            lambda x: x['current_fund_volume'] > pow(10, 8) and x['current_fund_volume'] < pow(10, 9),
            bond_list
        )
        return list(filter_bond_list)

    def _filter_current_market_volume(self, bond_list):
        """当日市场成交额>100万
        """
        filter_bond_list = filter(
            lambda x: x['day_market_volume'] > pow(10, 6),
            bond_list
        )
        return list(filter_bond_list)

    def _filter_convert_premium_ratio(self, bond_list):
        """溢价率小于15%
        """
        filter_bond_list = filter(
            lambda x: x['convert_premium_ratio'] < 0.15,
            bond_list
        )
        return list(filter_bond_list)


    def _filter_double_low(self, bond_list):
        """双低小于125
        """
        filter_bond_list = filter(
            lambda x: x['double_low'] < 125,
            bond_list
        )
        return list(filter_bond_list)

    def get_support_bonds(self, filter_pb_pe_quantile=False):
        """
        剩余规模>1亿，且<10亿元的转债

        当前成交额>100万元的转债

        溢价率小于15%,主要是防止市场下跌时杀转债溢价；正股下跌，带动转债价格下跌；溢价率低的转债安全垫更厚；
        另外要注意折价的情况，最典型的就是2020年初的英联转债，折价转债是否值得入手，这个需要仔细研究，

        到期税后收益率大于0的转债

        取双低值<125的转债

        筛选PB>1.3防止下修转股价时破净限制

        filter_pb_pe_quantile=True, 筛选pb, pe历史百分位小于50%
        """
        support_bond_list = self._bond_list

        support_bond_list = self._filter_current_fund_volume(support_bond_list)
        support_bond_list = self._filter_current_market_volume(support_bond_list)
        support_bond_list = self._filter_convert_premium_ratio(support_bond_list)
        support_bond_list = self._filter_double_low(support_bond_list)

        if filter_pb_pe_quantile:
            support_bond_list = self._filter_pb(support_bond_list)
            support_bond_list = self._filter_pb_pe_quantile(support_bond_list)

        return support_bond_list


# In[4]:


# 测试
import pandas as pd
from datetime import datetime, timedelta
from jqfactor import *

import warnings

base_date = (datetime.now() - timedelta(1)).strftime('%Y-%m-%d')
#base_date = '2019-01-10'

index_bond = ConvertBondBeta(base_date=base_date)
print(base_date)
print("=========================")

# 获取指定时间转债列表及统计值
bond_list = index_bond.get_bonds(base_date)
pd.DataFrame(bond_list)


# In[5]:


# 先不采用pe, pb百分位筛选
bond_list_a = DLowStrategy(bond_list).get_support_bonds(filter_pb_pe_quantile=False)
pd.DataFrame(bond_list_a)


# In[ ]:


# 采用pe, pb百分位筛选
bond_list_b = DLowStrategy(bond_list).get_support_bonds(filter_pb_pe_quantile=True)
pd.DataFrame(bond_list_b)


# In[ ]:


bond_list_a_text = pd.DataFrame(bond_list_a).to_html()
bond_list_b_text = pd.DataFrame(bond_list_b).to_html()


# 取得几个统计值：市场总量，小于110元转债总量，价格算术平均值，溢价率算术平均值
total_market, underrate_market, avg_price, avg_premium_ratio = index_bond.get_bonds_factors(bond_list)
total_market_text = "市场总量{}亿元, 小于110元转债总量{}亿元, 价格算术平均值{}, 溢价率算术平均值{}".format(
                                                                total_market/100000000,
                                                                underrate_market/100000000,
                                                                avg_price, avg_premium_ratio
                    )

split_text = '=================================================='
print(total_market_text)

send_message_text = "{}\r\n{}\r\n{}\r\n{}\r\n{}\r\n".format(
    bond_list_a_text, split_text, bond_list_b_text, split_text, total_market_text)
#print(send_message_text)


# In[ ]:

