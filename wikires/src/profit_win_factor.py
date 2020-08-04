# -*- coding: utf-8 -*-

"""
    计算指定时间段内对某项资产持有不动至指定时间点的胜率，如以下数据:

    market_data.csv

    date,       price
    '2018-01-01',1000
    '2018-01-02',900
    '2018-01-03',1001
    '2018-01-04',950
    '2018-01-05',1100
    '2018-01-06',1010

    在任意时间点，持有3天的胜率是100%
    在任意时间点，持有1天的胜率是40%
"""

import csv
import sys


def load_market_data(file_path):
    with open(file_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        return list(reader)


def caculate_profie_win_factor(market_data, hold_time_slot=30):
    if hold_time_slot > len(market_data):
        return 0

    win_factors = []
    for i, row in enumerate(market_data[:-hold_time_slot]):
        if float(row['price']) <= float(market_data[i + hold_time_slot]['price']):
            win_factors.append(1)  # win
        else:
            win_factors.append(0)

    return sum(win_factors) * 1.0 / len(win_factors)


if __name__ == '__main__':
    market_data = load_market_data(sys.argv[1])

    for hold_time_slot in [3, 30, 60, 90, 120, 180, 360, 720, 1080]:
        factor = caculate_profie_win_factor(market_data, hold_time_slot)
        print("持有{}天的胜率为{}".format(hold_time_slot, factor))
