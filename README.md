# ai-science-studio

AI 深度科普静态网站生成系统。零外部 CDN 依赖、零前端 JavaScript 框架，纯 Python 标准库加 `markdown` 驱动，生成专供 GitHub Pages 部署的静态页面（位于 `docs/`）。

## 核心特色与规范

- **内容溯源**：正文中的文献引用标号（如 `[S1]`、`[S2]`）自动生成超链接，点击直接锚点平滑跳转至文末参考文献条目。
- **关键数据联动**：文章后附带由 `data.csv` 驱动的结构化关键数据表格，具备自适应横向滚动机制。
- **纯 CSS 变量驱动**：站点样式严格遵循 `tokens.css` 中定义的设计变量（配色、字体层级、排版网格），不引入任何未声明样式。
- **系统原生字体与移动端适配**：中文字体回退至系统默认中文字体（苹方、微软雅黑等），响应式适配手机屏与宽屏阅读。
- **确定性与无外网依赖**：不调用任何网络或 AI 接口，全离线构建。

---

## 目录结构

```text
ai-science-studio/
├── content/
│   └── issue01/
│       ├── article.md       # 正文 Markdown（严格保持原内容不变）
│       ├── sources.csv      # 参考文献与来源清单
│       └── data.csv         # 关键数据表
├── templates/
│   ├── base.html            # 页面通用骨架（页头、导航、页脚）
│   ├── article.html         # 文章页模板（含正文插槽、关键数据表区、参考文献列表区）
│   └── index.html           # 首页模板（展示特刊列表与导读）
├── static/
│   └── css/
│       ├── tokens.css       # 视觉风格设计变量（不作修改）
│       └── site.css         # 站点全局与响应式样式（仅使用 tokens.css 变量）
├── docs/                    # 生成好的网站静态文件（供 GitHub Pages 发布）
│   ├── index.html           # 网站首页
│   ├── issue01/
│   │   └── index.html       # 第 1 期文章页
│   └── static/              # 静态资源副本（css 等）
├── build.py                 # 静态网站构建脚本（Python 标准库 + markdown）
├── .gitignore               # 忽略 __pycache__、.venv、.env 等
└── README.md                # 项目运行与说明文档
```

---

## 运行环境与使用说明

### 1. 安装依赖

安装构建、证据检查和视频渲染用到的库：

```bash
pip install -r requirements.txt
```

### 2. 执行构建

在项目根目录下执行 `build.py`：

```bash
python build.py
```

> **注意（特定 Windows 环境）**：
> 若系统的 `python` 或 `py` 命令未直接绑定有效解释器，可使用指定绝对路径的 Python 3.12 解释器执行：
> ```powershell
> & "C:\Users\dell\AppData\Local\Programs\Python\Python312\python.exe" build.py
> ```

构建完成后，控制台将输出生成的静态文件路径。

正文可以写主张编号 `[C01]`。`build.py` 会按 `claims.yaml` 把它画成对应来源的 `[S1]` 链接。同一处连续几个主张如果指向同一个来源，页面上仍然只显示一个来源链接。

### 3. 检查证据包

```bash
python check.py issue01
```

脚本读取该期的 `claims.yaml`、`article.md`、`data.csv`、`sources.csv` 和分镜（如果已经写了），把结果写到 `content/issue01/review.md`。有 ERROR 时退出码为 1。WARN（草稿主张、没人引用的主张、早于 2020 年的年份）不会让退出码变成 1。

### 4. 渲染竖版视频

视频不进 git。成片写到 `out/`，该目录和 `*.mp4` 已在 `.gitignore` 里。

依赖除了上面的 Python 包，还要：

1. 本机可执行的 `ffmpeg` 和 `ffprobe`（官方构建，加入 PATH）。
2. Playwright 的 Chromium：

```bash
python -m playwright install chromium
```

然后在项目根目录执行：

```bash
python video/render.py issue01
```

只想先听时长、不截帧：

```bash
python video/render.py issue01 --audio-only
```

脚本用分镜里的 `voice`（默认 `zh-CN-YunxiNeural`）调用免费的 edge-tts，不需要 API key，但需要能访问网络。旁白和画面上的数字写成 `{C01}`、`{C01.unit}`、`{C01.year}`，由 `claims.yaml` 填入；未核实的主张不能进视频。镜头时长是配音长度再加 `tail_seconds`。字幕来自 TTS 返回的词级时间，写成 `out/issue01-vertical.srt`，并叠在画面底部。画面是一页 HTML 动画，不是把封面做平移。末卡文字固定为「本视频部分画面为 AI 生成 · 数据来源见网站第 N 期」。

> **Windows：** 用 Python 3.12 解释器运行，例如
> `& "C:\Users\dell\AppData\Local\Programs\Python\Python312\python.exe" video\render.py issue01`
> 不要用 `python` 打开应用商店，也不要用损坏的 `py`。脚本只用 `pathlib` 和参数列表调用 ffmpeg，文件以 UTF-8 读写。

### 5. 本地预览

可以直接在文件管理器中双击，或通过浏览器打开：
- 首页：`docs/index.html`
- 第 1 期文章页：`docs/issue01/index.html`
