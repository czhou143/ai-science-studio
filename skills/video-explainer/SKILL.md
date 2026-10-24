---
name: video-explainer
description: Turn one issue's verified claims and article into a vertical explainer video (storyboard, HTML film, edge-tts narration, SRT, ffmpeg). Use when rendering or extending content/<issue>/storyboard.yaml or video/render.py.
---

# 竖版科普视频

把某一期已经核对过的主张和正文，做成约 60 秒、1080×1920 的竖版视频。画面是一页 HTML 动画，按时间轴逐帧截图，不是生成式视频，也不是把封面做平移。

一条片子只讲一个论证。每一镜的画面要画出这句旁白在说的关系：不能比的数字就做成被隔开的两张卡，预测就画成还没填实的柱，电网没跟上就让线停在半路。不要连续几镜都用同一张「大数字」版式。

## 输入

一期目录 `content/issueNN/` 里要有：

- `claims.yaml`：数字的唯一来源。旁白和画面文字不得手写新数字。
- `article.md`：旁白只复述这里已经讲过的话，不把不同口径拼成一笔账。
- `storyboard.yaml`：分镜。

`claims.yaml` 里用到的条目必须是 `status: verified`。

## 分镜

```yaml
format: vertical
width: 1080
height: 1920
fps: 24
voice: zh-CN-YunxiNeural
tail_seconds: 0.4
scenes:
  - id: s01
    template: opener
    text: 标题，可以在逗号处折行
    subtitle: 副题
    narration: "旁白。不要写裸数字。"
  - id: s02
    template: split          # 两个不能直接相减的单值
    left: C01
    right: C02
    left_label: 口径说明
    right_label: 另一口径
    stamp: 不能直接比
    narration: "估算大约是{C01}{C01.unit}，实测大约是{C02}{C02.unit}。"
  - id: s03
    template: bars           # 同一口径的现在与预测，柱高按两个 value 的比例
    left: C03
    right: C04
    narration: "{C03.year}年约{C03}{C03.unit}。到{C04.year}年预计{C04}{C04.unit}。"
  - id: s04
    template: race           # 没有数字的对照
    left_title: 机房
    right_title: 电网
    narration: "这里不要引入正文没有的数字。"
  - id: s05
    template: sparse         # 总数与被点亮的一部分，格子数量不写出来
    total: C26
    active: C27
    narration: "总参数{C26}{C26.unit}，每个词元只激活{C27}{C27.unit}。"
  - id: s06
    template: lines
    lines:
      - 一句没有数字的要点
    narration: "一句没有数字的要点。"
  - id: s07
    template: end
    text: "本视频部分画面为 AI 生成 · 数据来源见网站第 1 期"
    narration: "本视频部分画面为人工智能生成。数据来源见网站第一期。"
```

旁白和画面文字里的占位符：

- `{C03}` 数值
- `{C03.unit}` 单位
- `{C03.year}` 年份
- `{C03.text}` 主张原文

含有 `{` 的句子在 YAML 里必须加引号。`left` / `right` / `total` / `active` 写主张编号，渲染时读取 `value`、`unit`、`year`、`kind`、`source`。区间不能放进 `split`、`bars`、`sparse`。

末卡原文固定为：`本视频部分画面为 AI 生成 · 数据来源见网站第 N 期`。`render.py` 发现最后没有这句时会补上一镜。N 取自目录名末尾的数字。

## 步骤

1. 只从 verified 主张里选一条 60 秒能讲完的论证。估算、实测、预测不要画成同一根柱子。
2. 写 `storyboard.yaml`。旁白按正文缩写。
3. 先跑配音，看每镜时长，再改旁白。不要先截几百帧。
4. 用 `--stills` 看每镜结尾的画面，再全片合成。核对末卡原文、画面上的数字是否等于主张、字幕是否跟着声音。
5. 成片放在 `out/`，不要提交 mp4。

## 命令

在仓库根目录、Python 3.12：

```bash
pip install -r requirements.txt
python -m playwright install chromium
python video/render.py issue01 --audio-only
python video/render.py issue01 --stills
python video/render.py issue01
```

Windows 上如果 `python` 会打开应用商店，改用已安装的 Python 3.12 解释器。`ffmpeg` 和 `ffprobe` 必须在 PATH 里。edge-tts 不需要 API key。不要换付费语音，除非负责人明确同意。配音按文稿缓存在 `.cache/tts/`，句子没改就不会重新请求。

产物：

- `out/issueNN-vertical.mp4`
- `out/issueNN-vertical.srt`（由词级时间轴合成，不做语音识别）
- `out/preview/issueNN/*.png`（每镜一张接近结尾的帧）

## 画面

模板在 `video/templates/film.html`，共用 `tokens.css`。一页里按镜头硬切，页眉和字幕区保持不动。

- 画布 1080×1920，默认 24 帧。
- 海军蓝 `#1B2A41`，冷蓝 `#1F6E8C`，暖橙 `#B5452F`，米白 `#F7F4EC`，灰 `#5B6475`。
- 暖橙只留给电、被点亮的部分，和需要停下来看的结论。数字本身用米白，避免把颜色当成新的数值。
- 扁平、克制，不要霓虹和赛博光效。
- 标题和数字用衬线，界面和字幕用黑体。中文字体按 `Microsoft YaHei`、`PingFang SC`、`Noto Sans SC`、`WenQuanYi Micro Hei` 的顺序回退；衬线用 `Noto Serif CJK SC`。
- 动画由 `window.setRenderTime(t)` 控制。不要用 CSS transition，否则截图会停在过渡中间。
- 画面上不写格子个数、倍数或任何主张里没有的数。柱高和点亮比例只用来表示两个主张 value 的相对大小。

镜头时长 = 该镜 TTS 音频时长 + `tail_seconds`。

## 容易出错的地方

- 旁白和画面文字里的每个阿拉伯数字都必须出现在该句引用的主张 `value` 或 `year` 里。末卡那句是唯一例外。
- `draft` 主张不能进旁白，也不能绑到 `left` / `right` / `total` / `active`。
- 网页引用 `[Cxx]` 时，相邻且来源相同的编号会收成一个 `[Sx]` 链接。视频不走这条规则。
- YAML 里 `unit: %` 或句子以 `{` 开头时必须加引号。
- 区间（如 `325-580`）不要做成从 0 数到某个中点的动画，也不要放进柱状图。
- edge-tts 的 `offset` 单位是 100 纳秒。字幕时间要用这个单位换算，不要再跑一遍语音识别。词级事件通常不含标点，要把旁白原文按词对齐，把逗号和句号补回去，并在逗号和句号处换行。
- Windows 上调用 ffmpeg 时不要 `shell=True`。音频拼接清单里只写文件名，并把工作目录设到该文件夹，避免盘符冒号和中文路径进滤镜字符串。
- 文件读写指定 UTF-8，不要写 BOM。
- 截图分辨率要是偶数，编码使用 `yuv420p`，否则部分播放器会拒绝。
- 不要把 mp4 提交进 git。`out/` 和 `*.mp4` 已忽略。
