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

本项目仅需安装 `markdown` 解析库：

```bash
pip install markdown
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

### 3. 本地预览

可以直接在文件管理器中双击，或通过浏览器打开：
- 首页：`docs/index.html`
- 第 1 期文章页：`docs/issue01/index.html`
