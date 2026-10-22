#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-science-studio 静态科普网站构建脚本 (Minimal Build Script)
仅依赖 Python 标准库与 markdown 包。
"""

import csv
import html
import os
import re
import shutil
from pathlib import Path
import markdown

PROJECT_ROOT = Path(__file__).resolve().parent
CONTENT_DIR = PROJECT_ROOT / "content"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"
DOCS_DIR = PROJECT_ROOT / "docs"


def copy_static_assets():
    """将 static 目录完整复制到 docs/static"""
    docs_static = DOCS_DIR / "static"
    if docs_static.exists():
        shutil.rmtree(docs_static)
    shutil.copytree(STATIC_DIR, docs_static)


def parse_sources_csv(sources_path: Path):
    """读取 sources.csv 文件"""
    sources = []
    if not sources_path.exists():
        return sources

    with open(sources_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            s_id = row.get("id", "").strip()
            if not s_id:
                continue
            sources.append({
                "id": s_id,
                "title": row.get("标题", "").strip(),
                "author": row.get("机构或作者", "").strip(),
                "year": row.get("年份", "").strip(),
                "link": row.get("链接", "").strip(),
                "claim": row.get("支撑的主张", "").strip(),
            })
    return sources


def load_claim_source_map(issue_content_dir: Path):
    """Map claim ids (C01) to source ids (S1). Missing file means no claim citations."""
    claims_path = issue_content_dir / "claims.yaml"
    if not claims_path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit(
            "claims.yaml exists but PyYAML is not installed. "
            "Install dependencies from requirements.txt."
        ) from exc
    with claims_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or []
    mapping = {}
    if not isinstance(data, list):
        return mapping
    for item in data:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("id", "")).strip()
        source_id = str(item.get("source", "")).strip()
        if claim_id and source_id:
            mapping[claim_id] = source_id
    return mapping


def source_anchor(source_id: str) -> str:
    """Same markup the site already uses for [S1], [S2], ..."""
    return (
        f'<a href="#{source_id}" class="source-ref" '
        f'title="查看参考文献 [{source_id}]">[{source_id}]</a>'
    )


def replace_citations(md_text: str, claim_sources: dict) -> str:
    """Turn [Cxx] and [Sx] into source anchors.

    Several claims often share one source. Adjacent citations that resolve to
    the same source become a single [Sx] link, so the page stays as it was
    when the sentence only showed that source once.
    """

    def replace_run(match):
        tokens = re.findall(r"\[(C\d+|S\d+)\]", match.group(0))
        anchors = []
        previous = None
        for token in tokens:
            if token.startswith("C"):
                source_id = claim_sources.get(token)
                if not source_id:
                    return match.group(0)
            else:
                source_id = token
            if source_id == previous:
                continue
            anchors.append(source_anchor(source_id))
            previous = source_id
        return "".join(anchors)

    return re.sub(r"(?:\[(?:C\d+|S\d+)\])+", replace_run, md_text)


def parse_data_csv(data_path: Path):
    """读取 data.csv 文件"""
    rows = []
    if not data_path.exists():
        return rows

    with open(data_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            source_raw = row.get("来源编号", "").strip()
            # 格式化来源编号链接，如 [S1] -> <a href="#S1" class="source-ref">[S1]</a>
            def format_source_link(match):
                sid = match.group(1)
                return f'<a href="#{sid}" class="source-ref">[{sid}]</a>'

            source_link_html = re.sub(r'\[(S\d+)\]', format_source_link, html.escape(source_raw))

            rows.append({
                "metric": html.escape(row.get("指标", "").strip()),
                "value": html.escape(row.get("数值", "").strip()),
                "unit": html.escape(row.get("单位", "").strip()),
                "year": html.escape(row.get("年份", "").strip()),
                "scenario": html.escape(row.get("口径或情景", "").strip()),
                "source_link": source_link_html,
            })
    return rows


def render_article_page(issue_dir_name: str):
    """渲染 issue 文章页"""
    issue_content_dir = CONTENT_DIR / issue_dir_name
    article_md_path = issue_content_dir / "article.md"
    sources_csv_path = issue_content_dir / "sources.csv"
    data_csv_path = issue_content_dir / "data.csv"

    if not article_md_path.exists():
        print(f"Warning: {article_md_path} not found.")
        return

    # 1. 读取 markdown 并转换
    with open(article_md_path, mode="r", encoding="utf-8") as f:
        md_text = f.read()

    # 提取文章标题 (首个 # 标题)
    title_match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    article_title = title_match.group(1).strip() if title_match else "科普特刊"

    # [Cxx] 先还原成对应来源的 [Sx] 链接；仍直接写 [Sx] 的句子保持原样。
    claim_sources = load_claim_source_map(issue_content_dir)
    converted_md = replace_citations(md_text, claim_sources)

    # Markdown 转 HTML
    body_html = markdown.markdown(
        converted_md,
        extensions=["fenced_code", "tables"]
    )

    # 2. 读取数据表与来源
    sources = parse_sources_csv(sources_csv_path)
    data_rows = parse_data_csv(data_csv_path)

    # 3. 组装数据表格 HTML
    data_table_rows_html = []
    for r in data_rows:
        row_str = (
            f"<tr>\n"
            f"  <td>{r['metric']}</td>\n"
            f"  <td><strong>{r['value']}</strong></td>\n"
            f"  <td>{r['unit']}</td>\n"
            f"  <td>{r['year']}</td>\n"
            f"  <td>{r['scenario']}</td>\n"
            f"  <td>{r['source_link']}</td>\n"
            f"</tr>"
        )
        data_table_rows_html.append(row_str)

    data_tbody_html = "\n".join(data_table_rows_html)

    # 4. 组装来源列表 HTML
    sources_items_html = []
    for s in sources:
        title_safe = html.escape(s['title'])
        if s['link']:
            title_part = f'<a href="{html.escape(s["link"])}" target="_blank" rel="noopener noreferrer" class="source-title">{title_safe}</a>'
        else:
            title_part = f'<span class="source-title">{title_safe}</span>'

        meta_part = f"{html.escape(s['author'])} · {html.escape(s['year'])}"
        claim_part = ""
        if s['claim']:
            claim_part = f'<div class="source-claim"><span class="source-claim-label">支撑主张：</span>{html.escape(s["claim"])}</div>'

        item_str = (
            f'<li id="{html.escape(s["id"])}" class="source-item">\n'
            f'  <div class="source-header">\n'
            f'    <span class="source-tag">[{html.escape(s["id"])}]</span>\n'
            f'    {title_part}\n'
            f'  </div>\n'
            f'  <div class="source-meta">{meta_part}</div>\n'
            f'  {claim_part}\n'
            f'</li>'
        )
        sources_items_html.append(item_str)

    sources_ol_html = "\n".join(sources_items_html)

    # 5. 加载 templates/article.html
    article_tpl_path = TEMPLATES_DIR / "article.html"
    with open(article_tpl_path, mode="r", encoding="utf-8") as f:
        article_tpl = f.read()

    # 将动态列表注入模板
    table_replacement = f"""
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>指标</th>
            <th>数值</th>
            <th>单位</th>
            <th>年份</th>
            <th>口径或情景</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>
{data_tbody_html}
        </tbody>
      </table>
    </div>
"""

    sources_replacement = f"""
    <ol class="sources-list">
{sources_ol_html}
    </ol>
"""

    # 简单稳健的标记替换
    rendered_article = article_tpl
    rendered_article = rendered_article.replace("{{ article_html }}", body_html)
    # 替换 data_rows 循环结构块
    rendered_article = re.sub(
        r'<div class="table-responsive">.*?</div>',
        table_replacement.strip(),
        rendered_article,
        flags=re.DOTALL
    )
    # 替换 sources 循环结构块
    rendered_article = re.sub(
        r'<ol class="sources-list">.*?</ol>',
        sources_replacement.strip(),
        rendered_article,
        flags=re.DOTALL
    )

    # 6. 包裹 base.html
    base_tpl_path = TEMPLATES_DIR / "base.html"
    with open(base_tpl_path, mode="r", encoding="utf-8") as f:
        base_tpl = f.read()

    full_page = (
        base_tpl.replace("{{ title }}", article_title)
        .replace("{{ root_path }}", "../")
        .replace("{{ content }}", rendered_article)
    )

    # 7. 输出到 docs/issue01/index.html
    out_dir = DOCS_DIR / issue_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "index.html"
    with open(out_file, mode="w", encoding="utf-8") as f:
        f.write(full_page)

    print(f"Rendered: {out_file.relative_to(PROJECT_ROOT)}")


def render_home_page():
    """渲染首页 docs/index.html"""
    index_tpl_path = TEMPLATES_DIR / "index.html"
    base_tpl_path = TEMPLATES_DIR / "base.html"

    with open(index_tpl_path, mode="r", encoding="utf-8") as f:
        index_content = f.read()

    index_content = index_content.replace("{{ root_path }}", "./")

    with open(base_tpl_path, mode="r", encoding="utf-8") as f:
        base_tpl = f.read()

    full_page = (
        base_tpl.replace("{{ title }}", "科普特刊列表")
        .replace("{{ root_path }}", "./")
        .replace("{{ content }}", index_content)
    )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = DOCS_DIR / "index.html"
    with open(out_file, mode="w", encoding="utf-8") as f:
        f.write(full_page)

    print(f"Rendered: {out_file.relative_to(PROJECT_ROOT)}")


def main():
    print("Building ai-science-studio...")
    copy_static_assets()
    render_article_page("issue01")
    render_home_page()
    print("Build complete!")


if __name__ == "__main__":
    main()
