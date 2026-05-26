# 抖音直播录制与自动标记 MVP

这个项目采用“biliup 负责录制，外挂分析器负责标记”的结构。当前版本不改 biliup 源码，先提供一个稳定的本地标记流水线：读取 JSONL 弹幕/礼物事件，输出 `markers.json` 和 `markers.csv`。

## 安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 生成配置

```bash
douyin-marker init-config -o config.toml
```

编辑 `config.toml`，填入抖音直播间地址、关键词、弹幕密度阈值和礼物阈值。

## 生成 biliup 配置并录制

```bash
douyin-marker write-biliup-config -c config.toml
douyin-marker record -c config.toml
```

`record` 会执行类似下面的命令：

```bash
biliup --config biliup.config.toml start
```

需要先按 biliup 官方文档安装并确认本机可用。

## 分析弹幕/礼物事件

事件输入使用 JSONL，每行一个事件：

```json
{"type":"danmaku","timestamp":"2026-05-25T20:00:10Z","streamer":"example","user":"u1","content":"名场面来了"}
{"type":"gift","timestamp":"2026-05-25T20:00:30Z","streamer":"example","user":"u2","gift_name":"嘉年华","gift_value":3000}
```

运行分析：

```bash
douyin-marker analyze -c config.toml -i events.jsonl --started-at 2026-05-25T20:00:00Z
```

直播中持续监听事件文件：

```bash
douyin-marker watch -c config.toml -i events.jsonl --started-at 2026-05-25T20:00:00Z
```

不安装包也可以直接运行：

```bash
PYTHONPATH=src python3 -m douyin_live_marker.cli analyze -c examples/config.low-threshold.toml -i examples/events.jsonl --started-at 2026-05-25T20:00:00Z
```

输出标记包含：

- `danmaku_spike`：指定窗口内弹幕数超过阈值。
- `keyword_hit`：弹幕命中关键词。
- `gift_hit`：礼物价值超过阈值。

每条标记会包含视频时间点、建议片段起止时间、触发内容、原因和分数。

## 后续接入点

真实抖音弹幕/礼物采集层只需要持续写入同样格式的 JSONL 事件，标记分析逻辑无需修改。抖音接口可能变化，建议把采集层单独维护。
