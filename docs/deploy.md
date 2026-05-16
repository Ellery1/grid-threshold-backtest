# 量化策略平台 — 部署指南

## 一、环境准备

### 1.1 安装 Python 3.13

```bash
sudo yum install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel
cd /tmp
wget https://mirrors.aliyun.com/python-release/source/Python-3.13.0.tgz
tar -xzf Python-3.13.0.tgz
cd Python-3.13.0
./configure --enable-optimizations
make -j$(nproc)
sudo make altinstall
```

### 1.2 安装依赖

```bash
python3.13 -m pip install tushare pandas numpy python-dotenv \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn
```

## 二、配置

### 2.1 Tushare Token

```bash
echo "TUSHARE_TOKEN=你的tushare_token" > /opt/grid-threshold-backtest/.env
```

### 2.2 邮件配置

```bash
cp config/email.example.py config/email.py
vim config/email.py
```

填写 SMTP 服务器、端口、发件人邮箱、授权码、收件人。

### 2.3 股票策略参数

每只股票在 `stocks/{code}/config.py` 中有专属配置。如需调整回测日期、佣金率等，编辑对应文件。

## 三、运行回测

```bash
# 冠捷科技 — 完整回测 + 生成报告
python main.py backtest --code 000727

# 指定日期范围
python main.py backtest --code 000727 --start 2025-01-01 --end 2026-05-07

# 多参数对比
python main.py compare --code 000727 \
  --params "最优,2.59,2.71" "实战,2.60,2.75" "宽幅,2.60,2.80"
```

报告默认输出到 `stocks/{code}/reports/`。

## 四、启动邮件守护进程

```bash
# 监控冠捷科技，标注已持仓
nohup python -u main.py daemon \
  --stocks "000727,GridThresholdStrategy,true" \
  >> logs/daemon.log 2>&1 &

# 监控多只股票
nohup python -u main.py daemon \
  --stocks "000727,GridThresholdStrategy,true" "002281,MATrendStrategy,false" \
  >> logs/daemon.log 2>&1 &
```

启动后会立即执行一次检查，之后每个交易日早上 9:00 自动运行。周末自动跳过。

### 停止守护进程

```bash
pkill -f "main.py daemon"
```

## 五、工作原理

```
main.py daemon 启动
    ↓
立即拉数据 → 计算信号 → 发邮件（每只股票）
    ↓
sleep 到下一个交易日 9:00
    ↓
拉数据 → 计算信号 → 发邮件
    ↓
循环...
```

不同股票使用各自策略计算信号，邮件独立发送。

## 六、添加新股

```bash
mkdir -p stocks/000001/reports
touch stocks/000001/__init__.py

# 1. 创建 stocks/000001/config.py（股票信息 + 参数配置）
# 2. 创建 stocks/000001/strategy.py（继承 BaseStrategy，实现 4 个方法）
# 3. 运行回测验证: python main.py backtest --code 000001
# 4. 加入守护: 在 --stocks 中添加 "000001,YourStrategy,false"
```

## 七、常见问题

### Q1: tushare 数据拉取失败

- 确认 `.env` 中 TUSHARE_TOKEN 有效
- 免费账户每分钟限 200 次，单次回测不要重复拉取

### Q2: 邮件发不出去

- 确认 QQ 邮箱已开启 SMTP（设置 → 账户 → POP3/IMAP/SMTP）
- 授权码不是 QQ 密码，是生成的 16 位码
- 阿里云 ECS 587 端口通常可用

### Q3: 节假日邮件

周末自动跳过。法定节假日会照常运行但邮件内容显示持有/观望，无害。
