# 002281 MA10 策略 — 阿里云部署指南

## 一、首次部署

### 1.1 拉取代码

```bash
cd /opt
git clone https://github.com/Ellery1/grid-threshold-backtest.git
```

### 1.2 安装 Python 3.13 及依赖

```bash
# 编译安装 Python 3.13（如已有则跳过）
sudo yum install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel
cd /tmp
wget https://mirrors.aliyun.com/python-release/source/Python-3.13.0.tgz
tar -xzf Python-3.13.0.tgz
cd Python-3.13.0
./configure --enable-optimizations
make -j$(nproc)
sudo make altinstall

# 安装 pip 包
python3.13 -m pip install tushare pandas python-dotenv -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
```

### 1.3 配置 .env（tushare token）

```bash
echo "TUSHARE_TOKEN=你的tushare_token" > /opt/grid-threshold-backtest/.env
```

### 1.4 配置邮箱密码

```bash
cp /opt/grid-threshold-backtest/002281/email_config.example.py /opt/grid-threshold-backtest/002281/email_config.py
vim /opt/grid-threshold-backtest/002281/email_config.py
```

### 1.5 手工跑一次验证

```bash
cd /opt/grid-threshold-backtest/002281
python3.13 alert.py
```

首次运行会立即执行一次检查并发送邮件，然后打印 `下次执行: 20xx-xx-xx 09:00:00`。如果收到邮件说明一切正常，按 `Ctrl+C` 停掉。

---

## 二、启动守护进程（长期运行）

```bash
cd /opt/grid-threshold-backtest/002281
mkdir -p logs
nohup python3.13 alert.py >> logs/alert.log 2>&1 &
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
cd /opt/grid-threshold-backtest
git pull origin master
```

然后重启守护进程：

```bash
pkill -f alert.py
cd /opt/grid-threshold-backtest/002281
nohup python3.13 alert.py >> logs/alert.log 2>&1 &
```

---

## 四、工作原理

```
python3.13 alert.py 启动
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

## 五、常见问题

### Q1: 邮件发不出去

- 确认 QQ 邮箱已开启 SMTP（设置 → 账户 → POP3/IMAP/SMTP）
- 授权码不是 QQ 密码，是生成的 16 位码
- 阿里云 ECS 587 端口通常可用

### Q2: 怎么停掉守护进程？

```bash
pkill -f alert.py
```

### Q3: 节假日会不会发不必要的邮件？

周末自动跳过，法定节假日会照常运行但邮件内容是"继续持有/观望"，无害。

### Q4: 安装依赖超时？

用清华镜像：
```bash
python3.13 -m pip install tushare pandas python-dotenv -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
```
