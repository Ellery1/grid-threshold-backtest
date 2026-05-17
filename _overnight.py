import subprocess, re, os, sys
from datetime import datetime

ROOT = r'E:\python\grid-threshold-backtest'
CANDIDATES_MD = os.path.join(ROOT, 'A类股_网格搜索_原始个股名录.md')

dry_run = '--dry-run' in sys.argv

with open(CANDIDATES_MD, encoding='utf-8') as f:
    content = f.read()

codes = []
for line in content.split('\n'):
    if '🔲' in line and line.strip().startswith('|'):
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 4:
            code = parts[2]
            if code.isdigit() and len(code) == 6:
                codes.append(code)

print(f"待回测: {len(codes)} 只", flush=True)
print(f"首批: {codes[:5]}", flush=True)
print(f"末批: {codes[-3:]}", flush=True) if len(codes) > 3 else None

if dry_run:
    import sys; sys.exit(0)

batches = [codes[i:i+10] for i in range(0, len(codes), 10)]
BATCH_START = 3
total_batches = len(batches)

LOG_DIR = os.path.join(ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

master_log = os.path.join(LOG_DIR, '_master.log')
with open(master_log, 'w', encoding='utf-8') as f:
    f.write(f"Start: {datetime.now()}\n{len(codes)} stocks, {total_batches} batches\n\n")

success = 0
for batch_idx, batch_codes in enumerate(batches):
    batch_num = BATCH_START + batch_idx
    codes_str = ','.join(batch_codes)
    log_file = os.path.join(LOG_DIR, f'batch_{batch_num:03d}.log')

    ts = datetime.now().strftime('%H:%M:%S')
    msg = f"[{ts}] batch {batch_num}/{BATCH_START+total_batches-1}"
    print(f"{msg}  {codes_str[:40]}...", flush=True)

    cmd = f'python main.py batch --codes "{codes_str}" --batch {batch_num} --start 2024-06-01'

    try:
        with open(log_file, 'w', encoding='utf-8') as lf:
            lf.write(f"{msg}\n{'='*60}\n")
            result = subprocess.run(cmd, shell=True, cwd=ROOT,
                                    stdout=lf, stderr=subprocess.STDOUT, timeout=7200)
        print(f"  -> OK", flush=True)
        success += 1
    except subprocess.TimeoutExpired:
        print(f"  -> TIMEOUT", flush=True)
    except Exception as e:
        print(f"  -> {e}", flush=True)

    with open(master_log, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] batch {batch_num}: done\n")

print(f"\n{'='*40}\nDone. {success}/{total_batches} OK\n{'='*40}", flush=True)
