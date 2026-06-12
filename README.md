# log-inspector — 本地服务器日志巡检工具

命令行日志巡检工具，支持 Nginx / Node.js / Python 项目日志，按规则检测异常、统计慢请求、汇总错误类型，结果存入 SQLite，可导出 JSON/CSV。

---

## 目录结构

```
task0611004/
├── log_inspector/               # 核心包
│   ├── __init__.py
│   ├── cli.py                   # Typer CLI，注册所有命令
│   ├── config.py                # YAML 加载 + Pydantic 校验
│   ├── db.py                    # SQLite 建表与 CRUD
│   ├── scanner.py               # 扫描引擎（流式读取、时区归一、规则匹配）
│   ├── parsers/
│   │   ├── base.py              # 解析器基类（插件接口）
│   │   ├── nginx.py             # Nginx combined / error log
│   │   ├── node.py              # winston / pino / PM2
│   │   └── python_log.py        # Python logging + traceback
│   ├── rules/
│   │   ├── engine.py            # 规则加载、冲突检测、匹配
│   │   └── builtin.py           # 内置规则
│   ├── scheduler.py             # APScheduler 定时任务 + 防重复锁
│   ├── exporter.py              # JSON/CSV 导出 + 失败追踪
│   ├── auth.py                  # 权限校验
│   ├── logger.py                # 运行日志
│   └── plugins.py               # 插件加载器
├── config/
│   ├── settings.yaml            # 全局设置
│   ├── rules.yaml               # 检测规则
│   └── tasks.yaml               # 定时任务
├── plugins/                     # 自定义解析器插件
│   └── example_parser.py
├── tests/                       # 测试用例
├── data/                        # SQLite 数据库（自动创建）
├── logs/                        # 工具运行日志
├── exports/                     # 导出文件
└── pyproject.toml
```

---

## 安装启动

```bash
cd task0611004
pip install -e ".[dev]"

# 验证安装
log-inspector --help
```

**Python 版本**：>= 3.9

**依赖**：typer, pyyaml, pydantic, apscheduler, rich, chardet

---

## 核心命令

### 扫描

```bash
# 扫描单个文件
log-inspector scan /var/log/nginx/access.log

# 指定解析器和时间段
log-inspector scan ./app.log --parser node --start "2026-06-10 08:00" --end "2026-06-10 12:00"

# 指定规则
log-inspector scan ./django.log --rule "http_5xx,slow_request_critical"

# 扫描整个目录
log-inspector scan /var/log/app/
```

### 报告

```bash
log-inspector report slow-requests          # 慢请求 TOP 排行
log-inspector report slow-requests --scan-id 3
log-inspector report errors                 # 错误类型汇总
```

### 导出

```bash
log-inspector export 1 --format json        # 导出到 exports/
log-inspector export 1 --format csv
log-inspector export 1 --retry 5            # 重试失败的导出
```

### 规则管理

```bash
log-inspector rules list                    # 列出所有规则
log-inspector rules check                   # 检测规则冲突
log-inspector rules add ./my_rules.yaml     # 校验新规则文件
```

### 定时巡检

```bash
log-inspector schedule list                 # 查看已配置任务
log-inspector schedule run                  # 启动调度器守护进程
log-inspector schedule add --name hourly --cron "0 * * * *" --sources "/var/log/app.log"
```

### 配置与插件

```bash
log-inspector config check                  # 校验所有 YAML
log-inspector config show                   # 显示当前配置
log-inspector plugin list                   # 列出已加载插件
```

---

## 数据库表

| 表名 | 用途 |
|------|------|
| `scans` | 扫描会话（路径、解析器、状态、统计） |
| `findings` | 匹配结果（行号、时间、级别、规则、原始行） |
| `slow_requests` | 慢请求记录（路径、方法、耗时、状态码） |
| `exports` | 导出记录（格式、文件路径、状态、错误信息） |
| `schedule_runs` | 定时执行记录（防重复锁 lock_key UNIQUE） |

关键字段详见 `log_inspector/db.py` SCHEMA 定义。

---

## 日志解析流程

```
命令输入
  │
  ▼
config.py 加载并校验 YAML
  │
  ▼
scanner.py 创建扫描会话 → 写入 scans
  │
  ▼
选择解析器（auto / nginx / node / python / 插件）
  │
  ▼
流式逐行读取（gzip 透明解压）
  │
  ├─ 编码检测：UTF-8 优先 → chardet 采样回退
  │
  ├─ 解析行 → LogEntry (timestamp, level, message, metadata)
  │
  ├─ 时间段过滤（时区归一化：aware/naive 统一为本地时间比较）
  │
  └─ 规则引擎匹配（正则 / 阈值 / 关键词）
        │
        ▼
  批量写入 findings + slow_requests（每 batch_size 行刷盘）
        │
        ▼
  更新 scans 状态 → completed / failed
```

**大文件策略**：逐行迭代不加载全文件 + 批量入库 + rich 进度条

**时区处理**：Nginx 带 `+0800` 的 aware datetime 和 CLI 传入的 naive datetime 通过 `replace(tzinfo=None)` 归一化后比较，不会 TypeError。

---

## 测试方案

```bash
# 运行全部测试
python -m pytest tests/ -v

# 带覆盖率
python -m pytest tests/ --cov=log_inspector --cov-report=term-missing
```

| 模块 | 测试文件 | 覆盖场景 |
|------|----------|----------|
| 解析器 | test_parsers.py | 各格式正确解析、畸形行容错、编码异常 |
| 扫描引擎 | test_scanner.py | 自动检测、时间过滤(含时区)、慢请求、编码回退、端到端流水线 |
| 规则引擎 | test_rules.py | 正则/阈值/关键词匹配、冲突检测、优先级、ignore 动作 |
| 导出 | test_exporter.py | JSON/CSV 输出、失败追踪、重试 |
| 调度器 | test_scheduler.py | 防重复锁、任务注册、去重、多任务列表稳定性 |
| 配置 | test_config.py | YAML 加载/校验/错误提示 |

---

## 关键设计决策

1. **时区归一化**：`scanner._normalize_for_compare()` 将 aware 和 naive datetime 统一去 tzinfo 后比较，保证跨格式日志不中断。

2. **定时任务防重复**：`schedule_runs.lock_key` 为 `task_name:YYYYMMDDHHmm` 格式，UNIQUE 约束保证同一分钟内不会重复执行。

3. **任务列表稳定**：`list_tasks()` 基于 `_jobs` 内部注册表遍历（非 scheduler job store），`add_task` 对同名任务 early return，确保永远只有一条。

4. **大文件流式处理**：逐行 yield + 批量 `executemany` 入库。

5. **编码回退**：`errors='replace'` 避免立即崩溃 → chardet 检测 → 以正确编码重新打开。

6. **规则冲突提示**：加载时成对检测同 scope 互斥规则并输出警告。
