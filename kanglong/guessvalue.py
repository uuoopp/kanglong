# -*- coding: utf-8 -*-

# 采用唐朝的估值方法演绎到指数模糊估值
# 参考:http://dwz.date/dBW3

# 在All cash is equal 的原则下，对于符合三大前提的企业，不区分行业特色，不区分历史波动区间，一律以无风险收益率的倒数作为三年后合理估值的市盈率水平。
# 无风险收益率为3%~4%之间，取值25~30倍市盈率。无风险收益率4~5%之间，取值20~25倍市盈率，依此类推
# 对于部分净利润含现金量低于100%，但其他方面都符合的企业，对净利润予以折扣处理。体现在速算中就是取稍低的市盈率，即 1× 80%× 25=1× 20。
# 三年后合理估值的50%就是理想买点；
# 当年市盈率超过 50倍，或市值超过三年后合理估值上限的 150%，就是卖点，以先到者为准；
# 期间波动不关我事，呆坐不动。
# 整个估值体系只有一个未知数：预计该企业三年后的净利润；

# 演绎：
# 对于指数可以看股息率作为利润含现金量，比如ROE0.1，股息率0.05，含现金量即为50%
# 简单粗暴指数即可以根据PE/PEG * ROE估算未来的净利润

# 指数相关指标可参考:https://danjuanapp.com/djmodule/value-center
# 这个方法可以结合我们的亢龙有悔来估算指数是否值得投资


# 指数数据可自由订制

# 2020-12-18
INDEX_INFOS = [
    {
        'name': '中证红利',
        'pe': 7.54,
        'roe': 0.1124,
        'peg': 4.01,
    },
    {
        'name': '标普价值',
        'pe': 5.58,
        'roe': 0.1011,
        'peg': 1.29,
    }

]

# 无风险利率
SAFE_RATE = 0.04

if __name__ == '__main__':
    for INDEX_INFO in INDEX_INFOS:
        # 未来三年期望盈利
        expect_profit = pow((1 + INDEX_INFO['pe'] / INDEX_INFO['peg'] / 100), 3) * INDEX_INFO['roe'] * 100

        # 未来现金类资产市盈率
        EXPECT_SAFE_PE = 1 / SAFE_RATE

        # 未来期望总市值
        expect_marketcap = expect_profit * EXPECT_SAFE_PE

        # 等价当前市值
        curr_marketcap = expect_marketcap / pow(1 + SAFE_RATE, 3)

        # 等价当前市盈率
        curr_pe = curr_marketcap / INDEX_INFO['roe'] / 100

        # 推荐买入市盈率，默认打5折
        by_pe = curr_pe / 2

        print('{}未来三年期望盈利(100元资产净利润):{}, 等价当前资产市值:{}, 推荐买入市盈率:{}'.format(
            INDEX_INFO['name'], expect_profit, curr_marketcap, by_pe))
