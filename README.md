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

页面里可以添加多个主播。每个主播单独填写：

- 主播名字
- 抖音直播 URL。推荐使用 `https://live.douyin.com/数字房间号` 这种直播间链接；短链接如果已失效、只跳到抖音首页，或无法解析出 dycast 需要的短房间号，会提示错误。
- 保存到电脑的位置
- 高光关键词。多个关键词可以用空格、逗号或换行分隔；弹幕命中任意关键词就会生成 `keyword_hit` 标记。
- 大礼物标记阈值。礼物价值大于或等于这个数字时会生成 `gift_hit` 标记；默认是 `1000`。

点击“启动自动录制”后，后端会启动一个共享 dycast 页面，并为每个主播启动独立的自动检测任务。任务会循环检测开播状态：开播就录制，下播或录制结束后自动停下并回到等待检测。dycast 房间号和转发地址会自动带入，不需要用户再手动输入。dycast 只接受 `live.douyin.com` 使用的短房间号；抖音分享页里的 `reflow` 长 `room_id` 不能直接给 dycast，本项目会尝试从分享页里提取 `webRid` 后再传给 dycast。

每个主播的视频文件会写入自己保存目录下的 `recordings/` 文件夹。保存目录里仍会保留总表 `events.jsonl`、`markers.json` 和 `markers.csv`；同时，程序会在 `recordings/` 里为最新录制出来的视频生成同名标记文件，例如：

```text
recordings/主播-2026-05-26T20_00_00.flv
recordings/主播-2026-05-26T20_00_00.markers.json
recordings/主播-2026-05-26T20_00_00.markers.csv
recordings/主播-2026-05-26T20_00_00.markers.fcpxml
recordings/主播-2026-05-26T20_00_00.premiere_markers.csv
```

`markers.fcpxml` 会引用同名视频文件，适合导入 Final Cut Pro；`premiere_markers.csv` 是给 Premiere 查看/导入标记用的时间码表。`events.jsonl`、`markers.json` 和 `markers.csv` 只表示弹幕/礼物采集与标记器在运行，不代表视频已经录制成功，最终以 `recordings/` 里是否生成视频文件为准。

页面会记住上一次成功点击“启动自动录制”时填写的主播列表、直播 URL、保存位置和高光关键词。第一次打开且没有历史记录时，会默认显示一个空主播卡片，关键词使用默认值。

页面状态说明：

- `未启动`：当前没有录制，等待填写信息并点击“启动自动录制”。
- `检测中`：正在解析链接并检查主播是否开播。
- `等待开播`：主播当前未开播，程序会继续定时检测。
- `录制中`：检测到开播，视频录制、弹幕/礼物采集和高光标记器正在运行。
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
