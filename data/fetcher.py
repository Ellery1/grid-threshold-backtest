import time
import random
import pandas as pd
import tushare as ts


class DataFetcher:
    def __init__(self):
        self._pro = ts.pro_api()

    def fetch(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        last_err = None
        for attempt in range(max_retries):
            try:
                raw = self._pro.daily(
                    ts_code=ts_code,
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', ''),
                    adj='qfq',
                )

                if raw is None or raw.empty:
                    raise RuntimeError(
                        f"数据为空: {ts_code} ({start_date} ~ {end_date})"
                    )

                raw['trade_date'] = pd.to_datetime(raw['trade_date'])
                raw = raw.sort_values('trade_date').set_index('trade_date')
                return raw[['open', 'close', 'high', 'low', 'vol', 'pct_chg']]

            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    wait = random.uniform(1.5, 3.0)
                    time.sleep(wait)

        raise RuntimeError(
            f"数据获取失败(重试{max_retries}次): {ts_code} — {last_err}"
        )
