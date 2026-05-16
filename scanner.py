import os, sys, json, time, random
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from dotenv import load_dotenv
import tushare as ts

load_dotenv()
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

NEAR_START = '2025-01-01'
FAR_START = '2021-06-01'
END = '2026-05-16'
MIN_DAYS = 120
HAS_DIR_THRESHOLD = 15
AMP_THRESHOLD = 20
PAUSE_AT = 50
SAMPLE_SIZE = 5

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_NEAR = os.path.join(ROOT, '_scan_near.json')
OUT_FAR = os.path.join(ROOT, '_scan_far.json')
CPT = os.path.join(ROOT, '_scan_checkpoint.txt')
LOG = os.path.join(ROOT, '_scan_log.txt')
PAUSE_FLAG = os.path.join(ROOT, '_scan_pause.txt')

log_f = open(LOG, 'w', encoding='utf-8')
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_f.write(line + '\n')
    log_f.flush()

def classify(df):
    close = df['close'].values
    n = len(close)
    ma60 = np.full(n, np.nan)
    for i in range(59, n):
        ma60[i] = np.mean(close[i-59:i+1])
    ma_valid = ma60[59:]
    cl_valid = close[59:]
    med_ma = float(np.median(ma_valid))
    ma_slope = (ma_valid[-1] - ma_valid[0]) / med_ma * 100
    avg_dev = float(np.mean(np.abs(cl_valid - ma_valid) / ma_valid * 100))
    has_dir = abs(ma_slope) > HAS_DIR_THRESHOLD

    max_60d_gain = 0.0
    for i in range(60, n):
        gain = close[i] / min(close[max(0,i-60):i]) - 1
        if gain > max_60d_gain:
            max_60d_gain = gain

    lo, hi = float(df['low'].min()), float(df['high'].max())
    p50 = float(np.median(close))
    vol_mean = float(df['vol'].mean())

    if has_dir:
        if ma_slope > 0:
            ctype = 'C' if max_60d_gain > 1.0 else 'B'
        else:
            ctype = 'D'
    else:
        ctype = 'A' if avg_dev < AMP_THRESHOLD else 'E'

    return ctype, {
        'rows': n, 'p50': round(p50, 2), 'lo': round(lo, 2), 'hi': round(hi, 2),
        'ma_slope': round(ma_slope, 1), 'dev': round(avg_dev, 1),
        'max60d': round(max_60d_gain * 100), 'avg_vol': int(vol_mean),
    }

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_checkpoint():
    if os.path.exists(CPT):
        with open(CPT, 'r') as f:
            return set(f.read().strip().split(','))
    return set()

def save_checkpoint(scanned):
    with open(CPT, 'w') as f:
        f.write(','.join(sorted(scanned)))

def get_stock_list():
    raw = pro.stock_basic(exchange='', list_status='L',
                           fields='ts_code,symbol,name,area,industry,list_date')
    if raw is None or raw.empty:
        raise RuntimeError("获取股票列表失败")
    raw = raw[~raw['name'].str.contains('ST', na=False)]
    raw = raw[raw['ts_code'].str.endswith('.SZ') | raw['ts_code'].str.endswith('.SH')]
    cutoff = (datetime.now() - timedelta(days=180)).strftime('%Y%m%d')
    raw = raw[raw['list_date'] < cutoff]
    raw = raw.sort_values('ts_code').reset_index(drop=True)
    return raw

def fetch_one(ts_code, start, end):
    raw = pro.daily(ts_code=ts_code,
                    start_date=start.replace('-', ''),
                    end_date=end.replace('-', ''), adj='qfq')
    if raw is None or raw.empty:
        return None
    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    raw = raw.sort_values('trade_date').set_index('trade_date')
    df = raw[['open', 'close', 'high', 'low', 'vol', 'pct_chg']]
    if len(df) < MIN_DAYS:
        return None
    return df

def scan_near(stock_list, scanned):
    near = load_json(OUT_NEAR)
    scanned = scanned | set(near.keys())
    save_checkpoint(scanned)

    for _, row in stock_list.iterrows():
        symbol = str(row['symbol'])
        if symbol in scanned:
            continue

        df = fetch_one(row['ts_code'], NEAR_START, END)
        scanned.add(symbol)

        if df is None:
            save_checkpoint(scanned)
            time.sleep(0.15)
            continue

        ctype, info = classify(df)
        info['name'] = str(row['name'])
        info['industry'] = str(row.get('industry', ''))
        info['ts_code'] = str(row['ts_code'])
        info['type'] = ctype

        near[symbol] = info
        save_json(OUT_NEAR, near)
        save_checkpoint(scanned)

        if ctype == 'A':
            a_count = sum(1 for v in near.values() if v.get('type') == 'A')
            log(f"  [A:{a_count:>3}] {symbol} {info['name']:<8} dev={info['dev']:.1f}% p50={info['p50']:.2f}  {info['industry']}")

            if a_count == PAUSE_AT:
                log(f"\n===== 已发现 {PAUSE_AT} 只A类候选，暂停 =====")
                candidates = [(k, v) for k, v in near.items() if v.get('type') == 'A']
                sample = random.sample(candidates, min(SAMPLE_SIZE, len(candidates)))
                log(f"随机抽取 {len(sample)} 只供验证：\n")
                for sym, info in sample:
                    log(f"  {sym} {info['name']:<8} {info['ts_code']}  dev={info['dev']:.1f}% p50={info['p50']:.2f}  "
                        f"近窗 lo={info.get('lo','?')} hi={info.get('hi','?')}  {info['industry']}")
                log(f"\n请在行情软件中核实上述股票近2年K线是否为窄幅箱体震荡。")
                log(f"确认后删除 {PAUSE_FLAG} 文件继续扫描。\n")

                with open(PAUSE_FLAG, 'w') as pf:
                    pf.write(json.dumps([s for s, _ in sample], ensure_ascii=False))
                return 'paused'

        if len(scanned) % 200 == 0:
            total = len(stock_list)
            a_total = sum(1 for v in near.values() if v.get('type') == 'A')
            log(f"  ...进度 {len(scanned)}/{total} ({len(scanned)/total*100:.0f}%), A类累计 {a_total}")

        time.sleep(0.15)

    return 'done_near'

def finalize(near, far):
    results = []
    for sym, info in near.items():
        if info.get('type') != 'A':
            continue
        f = far.get(sym, {})
        ftype = f.get('type', '?')
        if ftype == 'A':
            status = '✅ 通过'
        elif ftype == 'D':
            status = '❌ 排除(远窗D)'
        elif ftype == 'B' or ftype == 'C':
            status = '⚠️ 谨慎(远窗=' + ftype + ')'
        elif ftype == 'E':
            status = '⚠️ 谨慎(远窗=E)'
        else:
            status = '⏳ 待校验'

        results.append({
            'symbol': sym, 'name': info['name'], 'industry': info['industry'],
            'near_dev': info['dev'], 'near_p50': info['p50'],
            'near_lo': info.get('lo', 0), 'near_hi': info.get('hi', 0),
            'far_type': ftype,
            'far_dev': f.get('dev', 0), 'far_slope': f.get('ma_slope', 0),
            'avg_vol': info.get('avg_vol', 0),
            'status': status
        })

    results.sort(key=lambda x: (0 if '✅' in x['status'] else 1 if '⚠️' in x['status'] else 2, x['near_dev']))
    return results

def main():
    log("===== A类股票全市场扫描 =====")
    log(f"近窗口: {NEAR_START} ~ {END}")
    log(f"远窗口: {FAR_START} ~ {END}")
    log(f"参数: has_dir=|ma_slope|>{HAS_DIR_THRESHOLD}%, A=not_has_dir & dev<{AMP_THRESHOLD}%")
    log(f"暂停: 每{PAUSE_AT}只A类候选，抽{SAMPLE_SIZE}只验证\n")

    stock_list = get_stock_list()
    total = len(stock_list)
    log(f"待扫描: {total} 只 (已剔除ST/次新股)\n")

    scanned = load_checkpoint()
    log(f"断点: 已扫描 {len(scanned)} 只\n")

    if os.path.exists(PAUSE_FLAG):
        log(f"检测到暂停标志 {PAUSE_FLAG}，等待验证确认...")
        log("确认后删除该文件重新运行即可继续\n")
        log_f.close()
        return

    near_done = False
    far_up_to_date = False
    while not near_done or not far_up_to_date:
        near = load_json(OUT_NEAR)
        near_scanned = len(near)
        near_done = near_scanned >= total

        if not near_done:
            result = scan_near(stock_list, scanned)
            if result == 'paused':
                log_f.close()
                return
            near = load_json(OUT_NEAR)
            near_done = len(near) >= total

        a_candidates = [(k, v) for k, v in near.items() if v.get('type') == 'A']
        far = load_json(OUT_FAR)
        unchecked = [(k, v) for k, v in a_candidates if k not in far]

        if unchecked:
            log(f"\n===== 远窗口校验 ({len(unchecked)} 只新候选) =====")
            for sym, info in unchecked:
                if sym in far:
                    continue
                ts_code = info['ts_code']
                df = fetch_one(ts_code, FAR_START, END)
                if df is None:
                    far[sym] = {'type': 'NO_DATA'}
                    save_json(OUT_FAR, far)
                    time.sleep(0.15)
                    continue
                ctype, finfo = classify(df)
                far[sym] = {'type': ctype, 'dev': finfo['dev'], 'ma_slope': finfo['ma_slope']}
                save_json(OUT_FAR, far)
                status = '✅' if ctype == 'A' else ('❌D' if ctype == 'D' else '⚠️' + ctype)
                log(f"  far: {sym} {info['name']}  near=A far={ctype} {status}")
                time.sleep(0.15)

        if near_done:
            far_up_to_date = all(k in far for k, _ in a_candidates)

        if near_done and far_up_to_date:
            break

    near = load_json(OUT_NEAR)
    far = load_json(OUT_FAR)
    results = finalize(near, far)

    passed = [r for r in results if '✅' in r['status']]
    warned = [r for r in results if '⚠️' in r['status']]
    excluded = [r for r in results if '❌' in r['status']]

    log(f"\n===== 最终结果 =====")
    log(f"  ✅ 通过(近A+远A): {len(passed)} 只")
    log(f"  ⚠️ 谨慎(近A+远非A): {len(warned)} 只")
    log(f"  ❌ 排除(近A+远D): {len(excluded)} 只\n")

    for r in passed:
        log(f"  ✅ {r['symbol']} {r['name']:<8} dev={r['near_dev']:.1f}% p50={r['near_p50']:.2f}  {r['industry']}")
    for r in warned:
        log(f"  ⚠️ {r['symbol']} {r['name']:<8} dev={r['near_dev']:.1f}% far={r['far_type']}  {r['industry']}")
    for r in excluded:
        log(f"  ❌ {r['symbol']} {r['name']:<8} dev={r['near_dev']:.1f}% far=D  {r['industry']}")

    final_path = os.path.join(ROOT, '_scan_final.json')
    save_json(final_path, results)
    log(f"\n完整结果已保存: {final_path}")
    log_f.close()

if __name__ == '__main__':
    main()
