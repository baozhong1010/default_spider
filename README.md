# default_spider

配置驱动的通用招投标爬虫框架（HTTP-only，异步并发，Redis 兼容输出）。

## 快速开始

1. 安装依赖

```bash
pip install .
```

如果是 Python 3.6 环境（例如 `conda fanwei`），建议使用非 editable 安装：

```bash
python -m pip install .
```

2. 配置

- 全局配置: `settings.yaml`
- 站点配置: `sites/*.yaml`

3. 运行

```bash
spider run-all
spider run-site demo_tender
spider run-site yangzhou_ggzy --local-test --local-test-output ./local_test_outputs/yangzhou_ggzy.jsonl
spider run-once --site-id demo_tender --url "https://example.com/list"
spider dry-run-config demo_tender
spider schedule

# 详细日志（建议排查时开启）
spider --verbose run-site yangzhou_ggzy --local-test
spider --log-level DEBUG run-all
```

## IDE 调试

你可以直接把项目根目录下的 `debug_cli.py` 作为调试入口，不必从 `spider/cli.py` 启动。

```bash
python debug_cli.py run-site demo_tender --local-test
```

另外，CLI 现在会在未传 `--root` 时自动向上查找项目根目录（要求目录内有 `settings.yaml` 和 `sites/`）。

## 本地测试模式

用于手工验证输出格式，不推送到正式 Redis 结果队列。

```bash
spider run-site yangzhou_zfcg --local-test --local-test-output ./local_test_outputs/yangzhou_zfcg.jsonl
```

可选参数:
- `--local-test`: 开启本地测试模式
- `--local-test-output`: 本地 JSONL 输出文件；不传时默认 `./local_test_outputs/results.jsonl`

## Redis 兼容

输出队列保持兼容:
- `zhaobiao:result:zhaobiao`
- `zhaobiao:result:zhongbiao`

输出字段保持兼容:
- `标题`
- `时间`
- `原文链接`
- `附件`
- `正文内容`
- `地区`

## 日志级别

数据追踪日志（INFO）事件：`record.trace.received`、`record.trace.ready`、`record.trace.completed`。
每条记录会带 `trace_id`、`list_source_url`、`detail_url`，并记录是否成功推送到 Redis（`push_success`、`queue`）。

日志会同时输出到控制台和项目根目录 `log/YYYY-MM-DD.log`。

默认读取 `settings.yaml` 的 `runtime.log_level`（默认 `INFO`）。
可通过 CLI 覆盖：`--verbose` 等价于 `--log-level DEBUG`。
