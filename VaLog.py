import os, re, json, yaml, requests, markdown
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from bleach import clean
from bleach_whitelist import markdown_tags, markdown_attrs

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

# 创建目录
os.makedirs(ARTICLE_DIR, exist_ok=True)
os.makedirs(OMD_DIR, exist_ok=True)

def sanitize_html(html):
    """安全清洗HTML，防止脚本注入"""
    allowed_tags = markdown_tags + ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'div']
    allowed_attrs = markdown_attrs.copy()
    allowed_attrs.update({
        'span': ['style', 'class'], 
        'div': ['class', 'style'],
        'code': ['class'],
        'pre': ['class']
    })
    return clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)

class VaLogGenerator:
    def __init__(self):
        print("=" * 50)
        print("VaLog Generator 初始化...")
        
        # 1. 加载配置
        self.config = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
        
        self.article_template_name = self.config.get('templates', {}).get('VaLog-default-article', DEFAULT_ARTICLE_TEMPLATE)
        self.home_template_name = self.config.get('templates', {}).get('VaLog-default-index', DEFAULT_HOME_TEMPLATE)

        # 2. 加载状态缓存 (用于增量更新)
        self.cache = {}
        if os.path.exists(OMD_JSON):
            try:
                with open(OMD_JSON, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                print(f"成功加载状态缓存，共 {len(self.cache)} 条记录")
            except:
                self.cache = {}

        # 3. 初始化渲染引擎
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=False, trim_blocks=True, lstrip_blocks=True
        )
        
        # 增强版 Markdown 配置
        self.md = markdown.Markdown(extensions=[
            'extra', 'fenced_code', 'tables', 'nl2br', 'sane_lists', 
            'codehilite', 'attr_list', 'toc'
        ], extension_configs={
            'codehilite': {'linenums': False, 'guess_lang': False, 'pygments_style': 'github'},
            'toc': {'permalink': True, 'baselevel': 2}
        }, output_format='html5')

    def extract_metadata_and_body(self, body):
        """提取元数据并清理正文"""
        if not body:
            return {"summary": "暂无内容", "vertical_title": "", "body": ""}
        
        lines = body.split('\n')
        summary = "暂无简介"
        vertical_title = ""
        meta_indices = []
        
        # 匹配元数据 !vml-<tag><span>content</span>
        for i in range(min(len(lines), 5)): # 检查前5行
            line = lines[i].strip()
            if line.startswith('!vml-'):
                match = re.search(r'<span[^>]*>(.*?)</span>', line)
                if match:
                    content = match.group(1).strip()
                    if 'summary' in line: summary = content
                    elif 'title' in line: vertical_title = content
                    meta_indices.append(i)

        content_lines = [l for i, l in enumerate(lines) if i not in meta_indices]
        return {
            "summary": summary,
            "vertical_title": vertical_title,
            "body": "\n".join(content_lines).strip()
        }

    def process_body(self, body):
        """Markdown 转 HTML 并增强处理"""
        if not body: return ""
        html = self.md.convert(body)
        # 增强代码块和表格
        html = re.sub(r'<pre><code(?!\s*class=)', '<pre><code class="language-plaintext"', html)
        html = re.sub(r'(<table[^>]*>.*?</table>)', r'<div class="table-wrapper">\1</div>', html, flags=re.DOTALL)
        return html

    def run(self):
        repo = os.getenv("REPO")
        token = os.getenv("GITHUB_TOKEN")
        if not repo or not token:
            print("错误: 缺少环境变量 REPO 或 GITHUB_TOKEN"); return

        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        # 获取远程数据
        try:
            url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            issues = [i for i in resp.json() if not i.get("pull_request")]
        except Exception as e:
            print(f"GitHub API 请求失败: {e}"); return

        remote_ids = {str(i['number']) for i in issues}
        
        # 1. 同步删除本地失效文件
        cached_ids = list(self.cache.keys())
        for cid in cached_ids:
            if cid not in remote_ids:
                print(f"同步删除: Issue #{cid}")
                for path in [os.path.join(ARTICLE_DIR, f"{cid}.html"), os.path.join(OMD_DIR, f"{cid}.md")]:
                    if os.path.exists(path): os.remove(path)
                del self.cache[cid]

        all_articles = []
        specials = []
        
        blog_cfg = self.config.get('blog', {})
        theme_cfg = self.config.get('theme', {})
        special_cfg = self.config.get('special', {})
        special_tags = self.config.get('special_tags', [])

        # 2. 处理文章
        for issue in issues:
            iid = str(issue['number'])
            updated_at = issue['updated_at']
            body = issue.get('body', '') or ''
            tags = [l['name'] for l in issue.get('labels', [])]
            
            metadata = self.extract_metadata_and_body(body)
            v_title = metadata["vertical_title"] or issue['title'] or "Blog"
            
            need_update = iid not in self.cache or self.cache[iid] != updated_at

            if need_update:
                print(f"正在更新: #{iid} - {issue['title']}")
                processed_content = self.process_body(metadata["body"])
                
                article_info = {
                    "id": iid, "title": issue['title'],
                    "date": issue['created_at'][:10], "tags": tags,
                    "content": processed_content, "url": f"article/{iid}.html",
                    "verticalTitle": v_title, "summary": metadata["summary"]
                }
                
                # 渲染文章详情页
                try:
                    tmpl = self.env.get_template(self.article_template_name)
                    rendered_html = tmpl.render(article=article_info, blog={**blog_cfg, "theme": theme_cfg})
                    with open(os.path.join(ARTICLE_DIR, f"{iid}.html"), "w", encoding="utf-8") as f:
                        f.write(rendered_html)
                    with open(os.path.join(OMD_DIR, f"{iid}.md"), "w", encoding="utf-8") as f:
                        f.write(body)
                except Exception as e:
                    print(f"详情页渲染失败 #{iid}: {e}")
                
                self.cache[iid] = updated_at
            
            # 3. 准备索引列表数据
            list_item = {
                "id": iid, "title": issue['title'],
                "date": issue['created_at'][:10], "tags": tags,
                "content": metadata["summary"], "url": f"article/{iid}.html",
                "verticalTitle": v_title
            }
            
            is_special = 'special' in tags or 'top' in tags or any(t in tags for t in special_tags)
            if is_special:
                specials.append(list_item)
            else:
                all_articles.append(list_item)

        # 按日期逆序排列
        all_articles.sort(key=lambda x: x['date'], reverse=True)

        # 4. 保存缓存和 base.yaml
        with open(OMD_JSON, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)
            
        base_data = {
            "blog": {**blog_cfg, "theme": theme_cfg},
            "articles": all_articles,
            "specials": specials,
            "floating_menu": self.config.get('floating_menu', []),
            "special_config": special_cfg
        }
        with open(BASE_YAML_OUT, 'w', encoding='utf-8') as f:
            yaml.dump(base_data, f, allow_unicode=True, sort_keys=False)

        # 5. 生成首页
        self.generate_index(all_articles, specials)
        print("=" * 50)
        print("所有任务完成！")

    def generate_index(self, articles, specials):
        print("渲染首页中 (注入Context)...")
        try:
            tmpl = self.env.get_template(self.home_template_name)
            
            # 关键：补全所有首页模板需要的变量
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
            
            output_path = os.path.join(DOCS_DIR, "index.html")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(tmpl.render(**ctx))
            print(f"首页已生成: {output_path} (大小: {os.path.getsize(output_path)} 字节)")
            
        except Exception as e:
            print(f"首页生成失败: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    try:
        gen = VaLogGenerator()
        gen.run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        exit(1)