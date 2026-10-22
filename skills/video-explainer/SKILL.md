---
name: video-explainer
description: Turn one issue's verified claims and article into a vertical explainer video (storyboard, HTML frames, edge-tts narration, SRT, ffmpeg). Use when rendering or extending content/<issue>/storyboard.yaml or video/render.py.
---

# 竖版科普视频

把某一期已经核对过的主张和正文，做成约 60 秒、1080×1920 的竖版视频。画面是 HTML 幻灯片逐帧截图，不是生成式视频。空镜只用无文字的静帧或以后的素材库，缺文件时回退到该期封面。

## 输入

一期目录 `content/issueNN/` 里要有：

- `claims.yaml`：数字的唯一来源。旁白和分镜不得手写新数字。
- `article.md`：旁白只复述这里已经讲过的话。
- `storyboard.yaml`：分镜。
- 封面静帧：`static/img/issueNN-cover-vertical.jpg`、`static/img/issueNN-cover.jpg`。

`claims.yaml` 里用到的条目必须是 `status: verified`，并且 `excerpt` 是调研原文或来源原文里的原句。

## 分镜

```yaml
format: vertical
width: 1080
height: 1920
fps: 12
voice: zh-CN-YunxiNeural
tail_seconds: 0.5
scenes:
  - id: s01
    template: title-card
    kicker: AI 科普工作室
    text: 标题
    subtitle: 副题
    narration: "旁白。不要写裸数字。"
  - id: s02
    template: big-number
    claim: C03
    aside_claim: C04          # 可选，小字对照
    aside_label: 另一口径
    label: 这张卡片在说什么
    narration: "{C03.year}年大约是{C03}{C03.unit}。"
  - id: s03
    template: broll
    asset: static/img/issue01-cover-vertical.jpg
    pan: right                # right 或 left
    caption: 画面上的短标题
    narration: "这里不要引入正文没有的数字。"
```

旁白里的占位符：

- `{C03}` 数值
- `{C03.unit}` 单位
- `{C03.year}` 年份
- `{C03.text}` 主张原文

含有 `{` 的句子在 YAML 里必须加引号，否则解析失败。

末卡原文固定为：`本视频部分画面为 AI 生成 · 数据来源见网站第 N 期`。`render.py` 发现最后一张不是这句时会补上一张。N 取自目录名末尾的数字。

## 步骤

1. 只从 verified 主张里选 6–8 个镜头能讲完的数字。估算、实测、预测不要在一句话里说成同一笔账。
2. 写 `storyboard.yaml`。旁白按正文缩写，控制在配音加每镜 0.5 秒后总共约 60 秒。
3. 先跑配音，看每镜时长，再改旁白。不要先截几百帧。
4. 截帧并合成。检查末卡文字、大数字是否等于主张、字幕是否跟着声音。
5. 成片放在 `out/`，不要提交 mp4。

## 命令

在仓库根目录、Python 3.12：

```bash
pip install -r requirements.txt
python -m playwright install chromium
python video/render.py issue01 --audio-only
python video/render.py issue01
```

Windows 上如果 `python` 会打开应用商店，改用已安装的 Python 3.12 解释器，例如：

```powershell
& "C:\Users\dell\AppData\Local\Programs\Python\Python312\python.exe" video\render.py issue01
```

`ffmpeg` 和 `ffprobe` 必须在 PATH 里。edge-tts 不需要 API key，但要能访问网络。不要换付费语音，除非负责人明确同意。

产物：

- `out/issueNN-vertical.mp4`
- `out/issueNN-vertical.srt`（由词级时间轴合成，不做语音识别）
- `out/preview/issueNN/*.png`（每镜一张接近结尾的帧，数字应已数完）

## 画面

模板在 `video/templates/`：`title-card`、`big-number`、`broll`，共用 `tokens.css`。

- 画布 1080×1920。
- 海军蓝 `#1B2A41`，冷蓝 `#1F6E8C`，暖橙 `#B5452F`，米白 `#F7F4EC`，灰 `#5B6475`。
- 扁平、克制，不要霓虹和赛博光效。
- 空镜只做缓慢 Ken Burns。素材缺失时，按竖版封面、横版封面的顺序回退。
- 动画由 `window.setRenderTime(t)` 控制。不要用 CSS transition，否则截图会停在过渡中间。

镜头时长 = 该镜 TTS 音频时长 + `tail_seconds`。

## 容易出错的地方

- 分镜里手写数字会被 `render.py` 拒绝：旁白里的每个数都必须出现在该句引用的主张 `value` 或 `year` 里。
- `draft` 主张不能进旁白，也不能当 `big-number` 的 `claim`。
- 网页引用 `[Cxx]` 时，相邻且来源相同的编号会收成一个 `[Sx]` 链接。视频不走这条规则。
- YAML 里 `unit: %` 或句子以 `{` 开头时必须加引号。
- 区间（如 `325-580`）不要做成从 0 数到某个中点的动画。模板只对单个数字计数。
- edge-tts 的 `offset` 单位是 100 纳秒。字幕时间要用这个单位换算，不要再跑一遍语音识别。词级事件通常不含标点，要把旁白原文按词对齐，把逗号和句号补回去，并在句号处换行，避免把“太瓦时”拆成两行。
- Windows 上调用 ffmpeg 时不要 `shell=True`。音频拼接清单里只写文件名，并把工作目录设到该文件夹，避免盘符冒号和中文路径进滤镜字符串。
- 文件读写指定 UTF-8，不要写 BOM。
- 中文字体按 `Microsoft YaHei`、`PingFang SC`、`Noto Sans SC`、`WenQuanYi Micro Hei` 的顺序回退。
- 截图分辨率要是偶数，编码使用 `yuv420p`，否则部分播放器会拒绝。
- 不要把 mp4 提交进 git。`out/` 和 `*.mp4` 已忽略。
