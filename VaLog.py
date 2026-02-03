#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VaLog - 基于 GitHub Issues 的静态博客生成器（三端一致性增强版）
作者：你 ❤️
功能：将公开仓库的 Issues 转换为静态 HTML 博客，支持增量更新与自动修复
"""

import os
import re
import json
import yaml
import requests
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
import markdown

# ==================== 路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yml")
TEMPLATE_DIR = os.path.join(BASE_DIR, "template")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
ARTICLE_DIR = os.path.join(DOCS_DIR, "article")
OMD_DIR = os.path.join(BASE_DIR, "O-MD")
OMD_JSON = os.path.join(OMD_DIR, "articles.json")
BASE_YAML_OUT = os.path.join(BASE_DIR, "base.yaml")

DEFAULT_ARTICLE_TEMPLATE = "article.html"
DEFAULT_HOME_TEMPLATE = "home.html"

# 创建输出目录
os.makedirs(ARTICLE_DIR, exist_ok=True)
os.makedirs(OMD_DIR, exist_ok=True)


class VaLogGenerator:
    def __init__(self):
        print("=" * 50)
        print("🚀 VaLog Generator 初始化中...")

        # 加载配置
        self.config = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}

        self.article_template_name = self.config.get('templates', {}).get(
            'VaLog-default-article', DEFAULT_ARTICLE_TEMPLATE
        )
        self.home_template_name = self.config.get('templates', {}).get(
            'VaLog-default-index', DEFAULT_HOME_TEMPLATE
        )

        # 加载缓存
        self.cache = {}
        if os.path.exists(OMD_JSON):
            try:
                with open(OMD_JSON, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except Exception as e:
                print(f"⚠️ 缓存加载失败: {e}")
                self.cache = {}

        # Jinja2 模板引擎
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )

    def extract_metadata_and_body(self, body):
        """提取元数据（返回 summary 为字符串）"""
        if not body:
            return {"summary": "暂无简介", "vertical_title": "", "body": ""}

        lines = body.split('\n')
        summary = "暂无简介"
        vertical_title = ""
        meta_indices = []

        for i in range(min(len(lines), 5)):
            line = lines[i].strip()
            if line.startswith('!vml-'):
                match = re.search(r'<span[^>]*>(.*?)</span>', line)
                if match:
                    content = match.group(1).strip()
                    if 'summary' in line:
                        summary = content
                    elif 'title' in line:
                        vertical_title = content
                    meta_indices.append(i)

        content_lines = [l for i, l in enumerate(lines) if i not in meta_indices]
        return {
            "summary": summary,
            "vertical_title": vertical_title,
            "body": "\n".join(content_lines).strip()
        }

    def process_body(self, body):
        """Markdown → HTML"""
        if not body:
            return ""

        html_content = markdown.markdown(
            body,
            extensions=[
                'extra',
                'fenced_code',
                'tables',
                'nl2br',
                'sane_lists',
                'codehilite'
            ],
            extension_configs={
                'codehilite': {
                    'linenums': False,
                    'guess_lang': False,
                    'pygments_style': 'github'
                }
            },
            output_format='html5'
        )

        html_content = re.sub(
            r'<pre><code(?!\s*class=)',
            '<pre><code class="language-plaintext"',
            html_content
        )
        html_content = re.sub(
            r'(<table[^>]*>.*?</table>)',
            r'<div class="table-wrapper">\1</div>',
            html_content,
            flags=re.DOTALL
        )

        return html_content

    def run(self):
        repo = os.getenv("REPO")
        token = os.getenv("GITHUB_TOKEN")
        if not repo or not token:
            print("❌ 错误: 请设置环境变量 REPO (如 user/repo) 和 GITHUB_TOKEN")
            return

        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

        # 获取 Issues
        try:
            url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            issues = [i for i in resp.json() if not i.get("pull_request")]
            print(f"✅ 成功获取 {len(issues)} 篇公开文章")
        except Exception as e:
            print(f"❌ GitHub API 请求失败: {e}")
            return

        remote_ids = {str(i['number']) for i in issues}

        # === 🔄 三端一致性校验（Issues + 缓存 + docs）===
        to_process = set()
        to_delete = set()

        # 获取本地存在的 ID（缓存 + HTML 文件）
        local_cache_ids = set(self.cache.keys())
        local_html_ids = {
            f.replace('.html', '') 
            for f in os.listdir(ARTICLE_DIR) 
            if f.endswith('.html')
        }
        all_local_ids = local_cache_ids | local_html_ids

        # 处理远程存在的文章
        for issue in issues:
            iid = str(issue['number'])
            updated_at = issue['updated_at']
            html_exists = os.path.exists(os.path.join(ARTICLE_DIR, f"{iid}.html"))
            in_cache = iid in self.cache
            cache_time_matches = in_cache and self.cache[iid] == updated_at

            if in_cache and cache_time_matches and not html_exists:
                print(f"⚠️ HTML 丢失，将重建: #{iid}")
                to_process.add(iid)
            elif not in_cache:
                print(f"🆕 新文章或缓存丢失: #{iid}")
                to_process.add(iid)
            elif not cache_time_matches:
                print(f"🔄 内容已更新: #{iid}")
                to_process.add(iid)

        # 处理远程不存在的文章（彻底清理）
        for local_id in all_local_ids:
            if local_id not in remote_ids:
                to_delete.add(local_id)

        # 执行删除
        for cid in to_delete:
            print(f"🗑️ 删除已移除文章: #{cid}")
            for path in [
                os.path.join(ARTICLE_DIR, f"{cid}.html"),
                os.path.join(OMD_DIR, f"{cid}.md")
            ]:
                if os.path.exists(path):
                    os.remove(path)
            if cid in self.cache:
                del self.cache[cid]

        # === 开始处理需要生成的文章 ===
        all_articles = []
        specials = []
        special_tags = self.config.get('special_tags', [])

        for issue in issues:
            iid = str(issue['number'])
            tags = [label['name'] for label in issue.get('labels', [])]
            is_special = 'special' in tags or 'top' in tags or any(t in tags for t in special_tags)

            # 构建列表项所需数据（即使跳过生成也要构建）
            metadata = self.extract_metadata_and_body(issue.get('body', ''))
            v_title = metadata["vertical_title"] or issue['title'] or "Blog"
            list_item = {
                "id": iid,
                "title": issue['title'],
                "date": issue['created_at'][:10],
                "tags": tags,
                "content": metadata["summary"],
                "url": f"article/{iid}.html",
                "verticalTitle": v_title
            }

            if iid in to_process:
                print(f"📝 处理文章: #{iid} - {issue['title']}")
                processed_html = self.process_body(metadata["body"])

                article_data = {
                    "id": iid,
                    "title": issue['title'],
                    "date": issue['created_at'][:10],
                    "tags": tags,
                    "content": processed_html,
                    "url": f"article/{iid}.html",
                    "verticalTitle": v_title,
                    "summary": metadata["summary"]
                }

                # 渲染 HTML
                tmpl = self.env.get_template(self.article_template_name)
                with open(os.path.join(ARTICLE_DIR, f"{iid}.html"), "w", encoding="utf-8") as f:
                    f.write(tmpl.render(article=article_data, blog=self.config.get('blog', {})))

                # 保存原始 Markdown
                with open(os.path.join(OMD_DIR, f"{iid}.md"), "w", encoding="utf-8") as f:
                    f.write(issue.get('body', ''))

                # 更新缓存
                self.cache[iid] = issue['updated_at']

            # 添加到对应列表
            if is_special:
                specials.append(list_item)
            else:
                all_articles.append(list_item)

        # 特殊卡片保底
        if not specials and self.config.get('special', {}).get('view'):
            view = self.config['special']['view']
            run_date_str = view.get('Total_time', '2023.01.01')
            try:
                run_date = datetime.strptime(run_date_str, '%Y.%m.%d')
                days_text = f"运行天数: {(datetime.now() - run_date).days} 天"
            except:
                days_text = "运行天数: 计算中..."
            specials.append({
                "id": "0",
                "title": "",
                "date": "",
                "tags": [],
                "content": [
                    view.get('RF_Information', ''),
                    view.get('Copyright', ''),
                    days_text,
                    view.get('Others', '')
                ],
                "url": "",
                "verticalTitle": "Special"
            })
            print("ℹ️ 已从配置生成 Special 信息")

        all_articles.sort(key=lambda x: x['date'], reverse=True)

        # 保存状态
        with open(OMD_JSON, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)

        base_data = {
            "blog": self.config.get('blog', {}),
            "articles": all_articles,
            "specials": specials,
            "floating_menu": self.config.get('floating_menu', []),
            "special_config": self.config.get('special', {})
        }
        with open(BASE_YAML_OUT, 'w', encoding='utf-8') as f:
            yaml.dump(base_data, f, allow_unicode=True, sort_keys=False)

        # 生成首页
        self.generate_index(all_articles, specials)

    def generate_index(self, articles, specials):
        print("🏠 正在生成首页...")
        try:
            tmpl = self.env.get_template(self.home_template_name)
            ctx = {
                "BLOG_NAME": self.config.get('blog', {}).get('name', 'VaLog'),
                "SPECIAL_NAME": self.config.get('blog', {}).get('sname', 'Special'),
                "BLOG_DESCRIPTION": self.config.get('blog', {}).get('description', ''),
                "BLOG_AVATAR": self.config.get('blog', {}).get('avatar', ''),
                "BLOG_FAVICON": self.config.get('blog', {}).get('favicon', ''),
                "THEME_MODE": self.config.get('theme', {}).get('mode', 'dark'),
                "PRIMARY_COLOR": self.config.get('theme', {}).get('primary_color', '#e74c3c'),
                "TOTAL_TIME": self.config.get('special', {}).get('view', {}).get('Total_time', '2023.01.01'),
                "ARTICLES_JSON": json.dumps(articles, ensure_ascii=False),
                "SPECIALS_JSON": json.dumps(specials, ensure_ascii=False),
                "MENU_ITEMS_JSON": json.dumps(self.config.get('floating_menu', []), ensure_ascii=False),
                "SPECIAL_TAGS": json.dumps(self.config.get('special_tags', []), ensure_ascii=False),
            }
            with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
                f.write(tmpl.render(**ctx))
            print("✅ 首页生成完毕！")
        except Exception as e:
            print(f"❌ 首页生成错误: {e}")


if __name__ == "__main__":
    try:
        gen = VaLogGenerator()
        gen.run()
    except KeyboardInterrupt:
        print("\n🛑 用户中断")
    except Exception as e:
        import traceback
        print(f"💥 发生未预期错误:")
        traceback.print_exc()
        exit(1)
