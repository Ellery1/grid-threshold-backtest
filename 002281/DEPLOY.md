# 002281 MA10 策略 — 阿里云部署指南

## 一、首次部署

### 1.1 拉取代码

```bash
cd ~
git clone https://github.com/Ellery1/grid-threshold-backtest.git
cd grid-threshold-backtest
```

### 1.2 安装依赖

```bash
pip3 install tushare pandas python-dotenv
```

### 1.3 配置 .env（tushare token）

创建 `grid-threshold-backtest/.env`：

```bash
echo "TUSHARE_TOKEN=你的tushare_token" > ~/grid-threshold-backtest/.env
```

### 1.4 配置邮箱密码

复制模板并填入真实密码：

```bash
cp grid-threshold-backtest/002281/email_config.example.py grid-threshold-backtest/002281/email_config.py
vim grid-threshold-backtest/002281/email_config.py    # 改成你的邮箱和授权码
```

### 1.5 手工跑一次验证

```bash
cd ~/grid-threshold-backtest/002281
python3 alert.py
```

首次运行会立即执行一次检查并发送邮件，然后打印 `下次执行: 20xx-xx-xx 09:00:00`。如果收到邮件说明一切正常，按 `Ctrl+C` 停掉。

---

## 二、启动守护进程（长期运行）

```bash
cd ~/grid-threshold-backtest/002281
mkdir -p logs
nohup python3 alert.py >> logs/alert.log 2>&1 &
```

确认进程在跑：

```bash
ps aux | grep alert
tail -f logs/alert.log
```

**不需要配置 crontab。** 脚本内置了定时循环——启动后会一直后台运行，每个交易日早上 9:00 自动执行检查并发送邮件。周末/节假日自动跳过。

---

## 三、更新代码

```bash
cd ~/grid-threshold-backtest
git pull origin master
```

然后重启守护进程：

```bash
pkill -f alert.py
cd ~/grid-threshold-backtest/002281
nohup python3 alert.py >> logs/alert.log 2>&1 &
```

---

## 四、工作原理

```
python3 alert.py 启动
    ↓
立即执行一次检查 → 发邮件
    ↓
计算距离下一个 9:00 还有多久
    ↓
sleep 等待
    ↓
9:00 AM → 拉 tushare 数据 → 算 MA10 → 判信号 → 发邮件
    ↓
循环回到 sleep 等待明天 9:00
```

| 信号 | 条件 | 邮件内容 |
|------|------|---------|
| 🟢 买入 | 收盘上穿 MA10 | 金叉确认，建议次日开盘买入 |
| 🔴 卖出 | 收盘跌破 MA10 | 跌破均线，建议次日开盘卖出 |
| ✅ 持有 | 收盘 > MA10 | 继续持有 |
| ⏳ 观望 | 收盘 < MA10 | 等待金叉信号 |

---

## 五、邮件示例

**标题**：`[✅ 持仓中] 光迅科技(002281) MA10策略 - 2026-05-08`

**正文**包含：股票名称代码、昨日收盘及涨跌幅、MA10 值及价差、操作建议、最近 10 日走势表。

---

## 六、常见问题

### Q1: `ModuleNotFoundError: No module named 'tushare'`

```bash
pip3 install tushare pandas python-dotenv
```

### Q2: 邮件发不出去

- 确认 QQ 邮箱已开启 SMTP（设置 → 账户 → POP3/IMAP/SMTP）
- 授权码不是 QQ 密码，是生成的 16 位码
- 阿里云 ECS 587 端口通常可用，如果被封用 465（SSL）

### Q3: 怎么停掉守护进程？

```bash
pkill -f alert.py
```

### Q4: 节假日会不会发不必要的邮件？

脚本会在周末自动跳过，但法定节假日（如五一、国庆）会照常运行。当天 tushare 拉到的仍是节前最后交易日的数据，邮件会说"继续持有/观望"，无害。
