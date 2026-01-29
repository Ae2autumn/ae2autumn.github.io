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

        # 2. 加载状态缓存
        self.cache = {}
        if os.path.exists(OMD_JSON):
            try:
                with open(OMD_JSON, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except:
                self.cache = {}

        # 3. 初始化渲染引擎
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=False, trim_blocks=True, lstrip_blocks=True
        )
        
        self.md = markdown.Markdown(extensions=[
            'extra', 'fenced_code', 'tables', 'nl2br', 'sane_lists', 
            'codehilite', 'attr_list', 'toc'
        ], extension_configs={
            'codehilite': {'linenums': False, 'guess_lang': False, 'pygments_style': 'github'},
            'toc': {'permalink': True, 'baselevel': 2}
        }, output_format='html5')

    def extract_metadata_and_body(self, body):
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
        if not body: return ""
        html = self.md.convert(body)
        html = re.sub(r'<pre><code(?!\s*class=)', '<pre><code class="language-plaintext"', html)
        html = re.sub(r'(<table[^>]*>.*?</table>)', r'<div class="table-wrapper">\1</div>', html, flags=re.DOTALL)
        return html

    def run(self):
        repo = os.getenv("REPO")
        token = os.getenv("GITHUB_TOKEN")
        if not repo or not token:
            print("错误: 缺少环境变量 REPO 或 GITHUB_TOKEN"); return

        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        try:
            url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            issues = [i for i in resp.json() if not i.get("pull_request")]
        except Exception as e:
            print(f"GitHub API 请求失败: {e}"); return

        remote_ids = {str(i['number']) for i in issues}
        
        # 1. 同步清理
        for cid in list(self.cache.keys()):
            if cid not in remote_ids:
                for path in [os.path.join(ARTICLE_DIR, f"{cid}.html"), os.path.join(OMD_DIR, f"{cid}.md")]:
                    if os.path.exists(path): os.remove(path)
                del self.cache[cid]

        all_articles = []
        specials = []
        
        blog_cfg = self.config.get('blog', {})
        theme_cfg = self.config.get('theme', {})
        special_cfg = self.config.get('special', {})
        special_tags = self.config.get('special_tags', [])

        # 2. 遍历处理
        for issue in issues:
            iid = str(issue['number'])
            updated_at = issue['updated_at']
            body = issue.get('body', '') or ''
            tags = [l['name'] for l in issue.get('labels', [])]
            
            metadata = self.extract_metadata_and_body(body)
            v_title = metadata["vertical_title"] or issue['title'] or "Blog"
            
            if iid not in self.cache or self.cache[iid] != updated_at:
                print(f"处理内容: #{iid}")
                p_content = self.process_body(metadata["body"])
                a_info = {
                    "id": iid, "title": issue['title'], "date": issue['created_at'][:10],
                    "tags": tags, "content": p_content, "url": f"article/{iid}.html",
                    "verticalTitle": v_title, "summary": metadata["summary"]
                }
                tmpl = self.env.get_template(self.article_template_name)
                with open(os.path.join(ARTICLE_DIR, f"{iid}.html"), "w", encoding="utf-8") as f:
                    f.write(tmpl.render(article=a_info, blog={**blog_cfg, "theme": theme_cfg}))
                with open(os.path.join(OMD_DIR, f"{iid}.md"), "w", encoding="utf-8") as f:
                    f.write(body)
                self.cache[iid] = updated_at

            list_item = {
                "id": iid, "title": issue['title'], "date": issue['created_at'][:10],
                "tags": tags, "content": metadata["summary"], "url": f"article/{iid}.html",
                "verticalTitle": v_title
            }
            
            if 'special' in tags or 'top' in tags or any(t in tags for t in special_tags):
                specials.append(list_item)
            else:
                all_articles.append(list_item)

        # 3. [保底逻辑] 如果没有Special文章，根据config.yml填充
        if not specials and special_cfg.get('view'):
            view = special_cfg.get('view', {})
            run_date_str = view.get('Total_time', '2023.01.01')
            try:
                run_date = datetime.strptime(run_date_str, '%Y.%m.%d')
                days_running = (datetime.now() - run_date).days
                days_text = f"运行天数: {days_running} 天"
            except:
                days_text = "运行天数: 计算中..."
            
            specials.append({
                "id": "0", "title": "", "date": "", "tags": [],
                "content": [
                    view.get('RF_Information', ''),
                    view.get('Copyright', ''),
                    days_text,
                    view.get('Others', '')
                ],
                "url": "", "verticalTitle": "Special"
            })
            print("已从配置文件生成 Special 信息")

        all_articles.sort(key=lambda x: x['date'], reverse=True)

        # 4. 落地数据
        with open(OMD_JSON, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)
            
        base_data = {
            "blog": {**blog_cfg, "theme": theme_cfg},
            "articles": all_articles, "specials": specials,
            "floating_menu": self.config.get('floating_menu', []),
            "special_config": special_cfg
        }
        with open(BASE_YAML_OUT, 'w', encoding='utf-8') as f:
            yaml.dump(base_data, f, allow_unicode=True, sort_keys=False)

        self.generate_index(all_articles, specials)

    def generate_index(self, articles, specials):
        print("渲染最终首页...")
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
            print("首页生成完毕。")
        except Exception as e:
            print(f"首页生成错误: {e}")

if __name__ == "__main__":
    try:
        gen = VaLogGenerator()
        gen.run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        exit(1)