# 抖音直播录制高光标记工具

这个项目采用成熟开源项目组合的方式实现：

- [biliup](https://github.com/biliup/biliup)：负责抖音直播录制到本地。
- [dycast](https://github.com/skmcj/dycast)：负责抖音直播弹幕/礼物采集，并通过 WebSocket 转发。
- 本项目：接收 dycast 转发事件，统一写入 `events.jsonl`，再根据弹幕密度、关键词、大礼物生成 `markers.json` 和 `markers.csv`。

这样可以避免在本项目里直接维护抖音 WebSocket 签名、protobuf 解析等高变动逻辑，把主要精力放在录制时间轴和高光标记上。

## 安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

同时需要按各自官方说明安装并确认可运行：

- biliup
- dycast

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
biliup server
```

需要先按 biliup 官方文档安装并确认本机可用。不同版本的 biliup 命令行不完全一致，可以在 `[biliup] args` 里调整实际启动参数。

## 一条命令启动流水线

在 `config.toml` 的 `[dycast]` 里填入本机启动 dycast 的命令，例如：

```toml
[biliup]
enabled = true
command = "biliup"
args = ["server"]
config_path = "biliup.config.toml"
output_dir = "recordings"

[dycast]
enabled = true
command = ["npm", "run", "dev"]
cwd = "/path/to/dycast"
host = "127.0.0.1"
port = 8765
events_output = "events.jsonl"
streamer = "example_streamer"
skip_gift_repeats = true
```

然后运行：

```bash
douyin-marker run-pipeline -c config.toml
```

这个命令会：

- 生成 biliup 配置并启动 biliup。
- 启动配置里的 dycast 命令。
- 在 `ws://127.0.0.1:8765` 接收 dycast 转发消息。
- 实时写入 `events.jsonl`。
- 实时更新 `markers.json` 和 `markers.csv`。

如果 dycast 需要手动在网页里输入直播间和转发地址，仍需在 dycast 界面里把转发地址填成：

```text
ws://127.0.0.1:8765
```

## 本地 Web UI

也可以启动本项目自己的控制台页面：

```bash
douyin-marker ui
```

然后打开：

```text
http://127.0.0.1:8787/
```

页面里填写：

- 主播名字
- 抖音直播 URL。推荐使用 `https://live.douyin.com/数字房间号` 这种直播间链接；短链接如果已失效或无法解析，会提示错误。
- 保存到电脑的位置

点击“启动录制”后，后端会启动 biliup、dycast 和高光标记器。页面会自动打开带参数的 dycast，不需要再手动输入 dycast 的房间号和转发地址。dycast 只接受房间号，本项目会尝试把 `https://live.douyin.com/...` 或 `https://v.douyin.com/...` 解析成房间号。

页面会记住上一次成功点击“启动录制”时填写的主播名字、直播 URL 和保存位置。第一次打开且没有历史记录时，输入框为空。

页面状态说明：

- `未启动`：当前没有录制，等待填写信息并点击“启动录制”。
- `启动中`：正在启动 biliup、dycast 和高光标记器。
- `录制中`：录制流水线正在运行；此时仍需确认右侧 dycast 页面已成功连接直播间。
- `已停止`：用户点击停止或流水线已经结束。
- `出错`：启动或运行过程中有错误，页面会显示错误信息。

## 采集弹幕/礼物事件

启动本项目的 dycast 接收端：

```bash
douyin-marker collect-dycast --host 127.0.0.1 --port 8765 -o events.jsonl --streamer example_streamer
```

然后启动 dycast，连接抖音直播间，并把 dycast 的转发地址填写为：

```text
ws://127.0.0.1:8765
```

dycast 转发的 `WebcastChatMessage` 会被转换成 `danmaku` 事件，`WebcastGiftMessage` 会被转换成 `gift` 事件并写入 `events.jsonl`。礼物默认会跳过 dycast 标记为重复的推送；如需保留，可加 `--include-gift-repeats`。

## 分析事件并生成标记

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

如果后续 dycast 不再适合使用，可以新增其它采集适配器。只要新适配器持续写入同样格式的 JSONL 事件，标记分析逻辑无需修改。
