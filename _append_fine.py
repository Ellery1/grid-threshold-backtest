import os

cmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   'A类股_优秀及合格标的.md')

with open(cmp, encoding='utf-8') as f:
    lines = f.readlines()

STEP_DOWNGRADE = {0.05: 0.02, 0.1: 0.02, 0.2: 0.05, 0.5: 0.05}

already_fine = []
for line in lines:
    s = line.strip()
    if not s.startswith('|') or s.count('|') < 11:
        continue
    parts = [p.strip() for p in s.split('|')]
    code = parts[2]
    if not code.isdigit() or len(code) != 6:
        continue
    try:
        step_val = float(parts[12])
    except ValueError:
        continue
    if step_val not in STEP_DOWNGRADE:
        already_fine.append(line.rstrip())

header = '| 批 | 代码 | 名称 | 行业 | B(元) | S(元) | 收益率 | 稳定性分 | 加权分数 | 年化率% | 交易(轮) | 步长 | 合格? |'
sep   = '|:---:|---:|------|------|------:|------:|------:|------:|------:|-----:|--------:|-----:|-------|'

rows_to_add = already_fine + []

with open(cmp, 'a', encoding='utf-8') as f:
    for row in already_fine:
        f.write(row + '\n')

print(f'Appended {len(already_fine)} already-fine stocks')
