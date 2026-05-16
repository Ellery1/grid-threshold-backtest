import pandas as pd
import tushare as ts


class DataFetcher:
    def __init__(self, token: str):
        ts.set_token(token)
        self._pro = ts.pro_api()

    def fetch(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        raw = self._pro.daily(
            ts_code=ts_code,
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adj='qfq',
        )

        if raw is None or raw.empty:
            raise RuntimeError(
                f"数据获取失败: {ts_code} ({start_date} ~ {end_date})，"
                f"请检查股票代码或 tushare token 是否有效"
            )

        raw['trade_date'] = pd.to_datetime(raw['trade_date'])
        raw = raw.sort_values('trade_date').set_index('trade_date')
        return raw[['open', 'close', 'high', 'low', 'vol', 'pct_chg']]
