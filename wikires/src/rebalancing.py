# -*- coding: utf-8 -*-

"""doctopt 资产动态再平衡回测小工具

Usage:
  rebalancing.py <csvfile> <begin> <up> <down>

Options:
  -h --help                                             Show this screen.
  --version                                             Show version.

Example:

    该工具模拟完全不相干的两类资产根据比例动态再平衡的收益, 默认初始采用70%的现金+30%的高波动风险资产

    从2019-01-01开始，回测动态再平衡的收益率， 平衡条件为某一方资产(增加或减少)偏离总资产净值的15%时进行动态再平衡

    csv文件格式:
        date,price
        2012-7-4,6.50
        2012-7-5,6.70


    示例：

    比特币投资动态再平衡：
    从2018年1月1日开始初始配置，每次比特币价格上涨对整体净值影响+10%的时候，以及价格下跌，对整体净值影响-15%的时候，再平衡
    python rebalancing.py bitcoin.csv 2018-01-01 10 15



    茅台投资动态再平衡：
    从2002年1月1日开始初始配置，每次茅台价格上涨对整体净值影响+10%的时候，以及价格下跌，对整体净值影响-15%的时候，再平衡
    python rebalancing.py bitcoin.csv 2002-01-04 10 15



    最优比例：

    大量回测表明，55动态再平衡的效果最好；但是这需要忍受巨大的回撤，没有几个人能耐住
"""

import csv
from datetime import datetime
from docopt import docopt

INITIAL_ASSET = 10000.0


# 初始投入资产占比
INITIAL_ASSET_UP_DOWN = 0.3

# 资产价格涨的时候调整资产占比
ASSETA_UP = 0.3

# 资产价格跌的时候调整资产占比
ASSETA_DOWN = 0.3


UP = float(15.0) / 100
DOWN = float(15.0) / 100


def load_market_data(file_path):
    with open(file_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        market_data = list(reader)
        for i in market_data:
            i['price'] = float(i['price'])
            i['date'] = datetime.strptime(i['date'], '%Y-%m-%d')
        return market_data


def get_market_data(market_data, date):
    for i, market_data_unit in enumerate(market_data):
        if market_data_unit['date'] == datetime.strptime(date, '%Y-%m-%d'):
            return market_data[i:]
    else:
        return None


def do_balancing(market_data_unit, rebalance_asset):
    current_risk_asset = rebalance_asset[-1]['risk_asset_unit'] * market_data_unit['price']

    last_risk_asset = rebalance_asset[-1]['risk_asset']
    last_cash_asset = rebalance_asset[-1]['cash_asset']

    if market_data_unit['price'] < 0.1:
        return

    if ((current_risk_asset > last_risk_asset) and (
            (current_risk_asset - last_risk_asset) / (last_risk_asset + last_cash_asset) > UP)):
        cash_asset = (current_risk_asset + last_cash_asset) * (1 - ASSETA_UP)
        risk_asset = (current_risk_asset + last_cash_asset) * ASSETA_UP
        risk_asset_unit = risk_asset / market_data_unit['price']
    elif ((current_risk_asset < last_risk_asset) and (
            (last_risk_asset - current_risk_asset) / (last_risk_asset + last_cash_asset) > DOWN)):
        cash_asset = (current_risk_asset + last_cash_asset) * (1 - ASSETA_DOWN)
        risk_asset = (current_risk_asset + last_cash_asset) * ASSETA_DOWN
        risk_asset_unit = risk_asset / market_data_unit['price']

    else:
        return

    rebalance_asset.append(
        {
            'date': market_data_unit['date'],
            'cash_asset': cash_asset,
            'risk_asset': risk_asset,
            'risk_asset_unit': risk_asset_unit,
        }
    )


if __name__ == '__main__':
    arguments = docopt(__doc__, version='rebalancing 1.0')

    cash_asset = INITIAL_ASSET * (1 - INITIAL_ASSET_UP_DOWN)
    risk_asset = INITIAL_ASSET * INITIAL_ASSET_UP_DOWN

    csvfile = arguments['<csvfile>']
    begin_date = arguments['<begin>']
    UP = float(arguments['<up>']) / 100
    DOWN = float(arguments['<down>']) / 100

    rebalance_asset = [
        {
            'date': datetime.strptime(begin_date, '%Y-%m-%d'),
            'cash_asset': cash_asset,
            'risk_asset': risk_asset,
            'risk_asset_unit': risk_asset,
        }
    ]

    market_data = load_market_data(csvfile)
    market_data = get_market_data(market_data, begin_date)
    rebalance_asset[-1]['risk_asset_unit'] = rebalance_asset[-1]['risk_asset'] / float(market_data[0]['price'])

    for market_data_unit in market_data:
        do_balancing(market_data_unit, rebalance_asset)

    for i in rebalance_asset:
        i['asset_price'] = i['risk_asset'] / i['risk_asset_unit']
        i['total_asset'] = i['cash_asset'] + i['risk_asset']
        print(i)
