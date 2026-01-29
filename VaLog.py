import os, re, json, yaml, requests, markdown
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

# ==================== 配置项 ====================
DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"  # 调试模式开关

# ==================== 路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yml")
TEMPLATE_DIR = os.path.join(BASE_DIR, "template")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
ARTICLE_DIR = os.path.join(DOCS_DIR, "article")
OMD_DIR = os.path.join(BASE_DIR, "O-MD")
OMD_JSON = os.path.join(OMD_DIR, "articles.json")
BASE_YAML_OUT = os.path.join(BASE_DIR, "base.yaml")

# 默认模板文件名
DEFAULT_ARTICLE_TEMPLATE = "article.html"
DEFAULT_HOME_TEMPLATE = "home.html"

# 创建必要的目录
os.makedirs(ARTICLE_DIR, exist_ok=True)
os.makedirs(OMD_DIR, exist_ok=True)


def log(message, level="INFO"):
    """条件日志输出"""
    if DEBUG_MODE or level in ["ERROR", "WARNING"]:
        prefix = f"[{level}]"
        print(f"{prefix} {message}")


class VaLogGenerator:
    def __init__(self):
        log("初始化VaLog生成器...")
        
        # 加载配置文件
        self.config = self._load_config()
        
        # 从配置中读取模板文件名
        self.article_template_name = self.config.get('templates', {}).get(
            'VaLog-default-article', DEFAULT_ARTICLE_TEMPLATE
        )
        self.home_template_name = self.config.get('templates', {}).get(
            'VaLog-default-index', DEFAULT_HOME_TEMPLATE
        )
        
        log(f"文章模板: {self.article_template_name}")
        log(f"首页模板: {self.home_template_name}")
        
        # 加载缓存
        self.cache = self._load_cache()
        
        # 创建Jinja2环境
        self.env = self._create_jinja_env()
        
        log("初始化完成")

    def _load_config(self):
        """加载配置文件"""
        if not os.path.exists(CONFIG_PATH):
            log(f"配置文件不存在: {CONFIG_PATH}", "WARNING")
            return {}
        
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            log(f"配置文件加载成功")
            return config
        except Exception as e:
            log(f"配置文件加载失败: {e}", "ERROR")
            return {}

    def _load_cache(self):
        """加载缓存文件"""
        if not os.path.exists(OMD_JSON):
            log("无缓存文件，将创建新缓存")
            return {}
        
        try:
            with open(OMD_JSON, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            log(f"缓存加载成功，条目数: {len(cache)}")
            return cache
        except Exception as e:
            log(f"缓存加载失败: {e}", "ERROR")
            return {}

    def _create_jinja_env(self):
        """创建Jinja2模板环境"""
        if not os.path.exists(TEMPLATE_DIR):
            log(f"模板目录不存在: {TEMPLATE_DIR}", "ERROR")
            raise FileNotFoundError(f"模板目录不存在: {TEMPLATE_DIR}")
        
        log(f"模板目录: {TEMPLATE_DIR}")
        env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )
        log("Jinja2环境初始化完成")
        return env

    def extract_metadata_and_body(self, body):
        """
        提取元数据并从正文中完全移除
        
        元数据格式:
        - 第一行: !vml-<span>摘要内容</span>
        - 第二行: !vml-<span>垂直标题</span>
        """
        if not body:
            return {
                "summary": ["暂无简介"],
                "vertical_title": "",
                "body": ""
            }
        
        lines = body.split('\n')
        summary = ["暂无简介"]
        vertical_title = ""
        content_start_index = 0  # 正文开始的行索引
        
        # 检查第一行是否为摘要元数据
        if len(lines) > 0 and lines[0].strip().startswith('!vml-'):
            match = re.search(r'<span[^>]*>(.*?)</span>', lines[0])
            if match:
                summary = [match.group(1).strip()]
                content_start_index = 1
                log(f"提取到摘要: {summary[0][:50]}...")
        
        # 检查第二行是否为垂直标题元数据
        if len(lines) > content_start_index and lines[content_start_index].strip().startswith('!vml-'):
            match = re.search(r'<span[^>]*>(.*?)</span>', lines[content_start_index])
            if match:
                vertical_title = match.group(1).strip()
                content_start_index += 1
                log(f"提取到垂直标题: {vertical_title}")
        
        # 跳过元数据行后的空行
        while content_start_index < len(lines) and not lines[content_start_index].strip():
            content_start_index += 1
        
        # 提取正文（从第一个非空行开始）
        clean_body = '\n'.join(lines[content_start_index:]).strip()
        
        log(f"元数据提取完成，正文长度: {len(clean_body)} 字符")
        
        return {
            "summary": summary,
            "vertical_title": vertical_title,
            "body": clean_body
        }

    def process_body(self, body):
        """
        将Markdown正文转换为HTML
        
        注意：此方法接收的是已经移除元数据的纯正文
        """
        if not body:
            log("正文为空，返回空字符串", "WARNING")
            return ""
        
        log(f"开始处理正文，长度: {len(body)} 字符")
        
        try:
            # ==================== Markdown转换配置 ====================
            # 配置扩展和选项以获得最佳渲染效果
            html_content = markdown.markdown(
                body,
                extensions=[
                    'extra',          # 包括表格、脚注、定义列表等
                    'fenced_code',    # 围栏代码块支持
                    'tables',         # 表格支持
                    'nl2br',          # 自动将换行转换为 <br>（关键！）
                    'sane_lists',     # 更智能的列表处理
                    'codehilite',     # 代码高亮
                    'toc',            # 目录生成
                ],
                extension_configs={
                    'codehilite': {
                        'linenums': False,
                        'guess_lang': False,
                    },
                    'nl2br': {
                        # 确保单个换行被转换为 <br>
                    }
                },
                output_format='html5'
            )
            
            # 确保代码块有正确的CSS类（用于语法高亮）
            html_content = re.sub(
                r'<pre><code(?!\s*class=)',
                '<pre><code class="language-plaintext"',
                html_content
            )
            
            log(f"Markdown转换成功，HTML长度: {len(html_content)} 字符")
            
            # ==================== 验证转换结果 ====================
            if not html_content.strip():
                log("警告: Markdown转换后内容为空", "WARNING")
                return self._fallback_render(body)
            
            # 检查是否至少有一些HTML标签
            if not re.search(r'<[^>]+>', html_content):
                log("警告: 转换结果不包含HTML标签", "WARNING")
                return self._fallback_render(body)
            
            return html_content
            
        except Exception as e:
            log(f"Markdown转换错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            
            # 使用备用渲染方案
            return self._fallback_render(body)

    def _fallback_render(self, body):
        """
        应急渲染方案：当Markdown转换失败时使用
        """
        log("使用应急渲染方案")
        
        # 按双换行分割段落
        paragraphs = body.split('\n\n')
        html_parts = []
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # 转义HTML特殊字符
            para = (para
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;'))
            
            # 将单换行转换为 <br>
            para = para.replace('\n', '<br>\n')
            
            html_parts.append(f'<p>{para}</p>')
        
        return '\n'.join(html_parts)

    def fetch_issues(self, repo, token):
        """获取GitHub Issues"""
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        log("开始获取GitHub Issues...")
        
        try:
            url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            issues = response.json()
            
            # 过滤掉Pull Request
            issues = [i for i in issues if not i.get("pull_request")]
            
            log(f"成功获取 {len(issues)} 个issue")
            return issues
            
        except requests.exceptions.RequestException as e:
            log(f"GitHub API请求失败: {e}", "ERROR")
            return []
        except Exception as e:
            log(f"处理Issues时出错: {e}", "ERROR")
            return []

    def process_article(self, issue, blog_cfg, theme_cfg):
        """处理单篇文章"""
        iid = str(issue['number'])
        title = issue['title']
        body = issue.get('body', '') or ''
        tags = [label['name'] for label in issue.get('labels', [])]
        created_at = issue.get('created_at', '')[:10]
        updated_at = issue['updated_at']
        
        log(f"处理文章 #{iid}: {title}")
        log(f"  标签: {tags}")
        
        # 提取元数据和正文
        metadata = self.extract_metadata_and_body(body)
        
        # 垂直标题优先级：元数据 > 文章标题 > "ABlog"
        vertical_title = metadata["vertical_title"] or title or "ABlog"
        
        # 处理正文（转换为HTML）
        html_content = self.process_body(metadata["body"])
        
        # 构建文章数据
        article_data = {
            "id": iid,
            "title": title,
            "date": created_at,
            "tags": tags,
            "content": html_content,
            "raw_content": metadata["body"],  # 保留原始内容用于调试
            "url": f"article/{iid}.html",
            "verticalTitle": vertical_title,
            "summary": metadata["summary"]
        }
        
        # 检查是否需要更新
        need_update = iid not in self.cache or self.cache[iid] != updated_at
        
        if need_update:
            log(f"  文章需要更新")
            self._save_article_html(article_data, blog_cfg, theme_cfg)
            self._save_article_markdown(iid, body)
        else:
            log(f"  文章无变化，跳过更新")
        
        return article_data, updated_at

    def _save_article_html(self, article_data, blog_cfg, theme_cfg):
        """保存文章HTML文件"""
        try:
            tmpl = self.env.get_template(self.article_template_name)
            article_html = tmpl.render(
                article=article_data,
                blog={**blog_cfg, "theme": theme_cfg}
            )
        except Exception as e:
            log(f"  模板渲染失败: {e}，使用简单模板", "WARNING")
            # 使用简单的备用模板
            article_html = self._create_simple_article_html(article_data)
        
        # 保存文章HTML
        article_path = os.path.join(ARTICLE_DIR, f"{article_data['id']}.html")
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(article_html)
        log(f"  已生成: {article_path}")

    def _create_simple_article_html(self, article_data):
        """创建简单的备用HTML模板"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{article_data['title']}</title>
    <style>
        body {{
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            line-height: 1.8;
            color: #333;
        }}
        .header {{
            border-bottom: 2px solid #e74c3c;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .title {{
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        .meta {{
            color: #666;
            font-size: 0.9rem;
        }}
        .tag {{
            display: inline-block;
            background: #f0f0f0;
            padding: 3px 10px;
            border-radius: 3px;
            margin-right: 5px;
            font-size: 0.85rem;
        }}
        .content {{
            font-size: 1rem;
        }}
        .content p {{
            margin-bottom: 1.2em;
        }}
        .content h1, .content h2, .content h3 {{
            margin-top: 1.5em;
            margin-bottom: 0.5em;
        }}
        .content pre {{
            background: #f5f5f5;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        .content code {{
            font-family: 'Consolas', 'Monaco', monospace;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1 class="title">{article_data['title']}</h1>
        <div class="meta">
            <span>📅 {article_data['date']}</span>
            <div style="margin-top: 8px;">
                {''.join(f'<span class="tag">{tag}</span>' for tag in article_data['tags'])}
            </div>
        </div>
    </div>
    <div class="content">
        {article_data['content']}
    </div>
</body>
</html>"""

    def _save_article_markdown(self, iid, body):
        """备份原始Markdown"""
        md_path = os.path.join(OMD_DIR, f"{iid}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(body)
        log(f"  已备份: {md_path}")

    def categorize_articles(self, articles, special_cfg):
        """将文章分类为普通文章和特殊文章"""
        regular_articles = []
        special_articles = []
        
        # 获取特殊标签配置
        special_top_enabled = special_cfg.get('top', True)
        special_tags = self.config.get('special_tags', [])
        
        for article in articles:
            tags = article['tags']
            is_special = False
            
            # 检查是否有 'special' 标签
            if 'special' in tags:
                is_special = True
                log(f"文章 #{article['id']} 标记为特殊 (special标签)")
            
            # 检查是否有 'top' 标签（如果启用）
            elif special_top_enabled and 'top' in tags:
                is_special = True
                log(f"文章 #{article['id']} 标记为特殊 (top标签)")
            
            # 检查其他配置的特殊标签
            else:
                for tag in special_tags:
                    if tag in tags:
                        is_special = True
                        log(f"文章 #{article['id']} 标记为特殊 ({tag}标签)")
                        break
            
            if is_special:
                special_articles.append(article)
            else:
                regular_articles.append(article)
        
        return regular_articles, special_articles

    def create_default_special(self, special_cfg):
        """创建默认的特殊文章（当没有特殊文章时）"""
        if not special_cfg.get('view'):
            return None
        
        view = special_cfg.get('view', {})
        
        # 计算运行天数
        run_date_str = view.get('Total_time', '2026.01.01')
        try:
            run_date = datetime.strptime(run_date_str, '%Y.%m.%d')
            days_running = (datetime.now() - run_date).days
            days_text = f"运行天数: {days_running} 天"
        except:
            days_text = "运行天数: 计算中..."
        
        return {
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
        }

    def save_base_yaml(self, regular_articles, special_articles, blog_cfg, theme_cfg, special_cfg):
        """保存 base.yaml 文件"""
        try:
            base_data = {
                "blog": {**blog_cfg, "theme": theme_cfg},
                "articles": regular_articles,
                "specials": special_articles,
                "floating_menu": self.config.get('floating_menu', []),
                "special_config": special_cfg
            }
            
            with open(BASE_YAML_OUT, 'w', encoding='utf-8') as f:
                yaml.dump(base_data, f, allow_unicode=True, sort_keys=False)
            
            log(f"base.yaml 已生成: {BASE_YAML_OUT}")
        except Exception as e:
            log(f"base.yaml 生成失败: {e}", "ERROR")

    def generate_index(self, regular_articles, special_articles):
        """生成首页"""
        log("开始生成首页...")
        
        home_tmpl_path = os.path.join(TEMPLATE_DIR, self.home_template_name)
        if not os.path.exists(home_tmpl_path):
            log(f"首页模板不存在: {home_tmpl_path}", "ERROR")
            return
        
        try:
            tmpl = self.env.get_template(self.home_template_name)
            
            context = {
                "BLOG_NAME": self.config.get('blog', {}).get('name', 'VaLog'),
                "SPECIAL_NAME": self.config.get('blog', {}).get('sname', 'Special'),
                "BLOG_DESCRIPTION": self.config.get('blog', {}).get('description', ''),
                "BLOG_AVATAR": self.config.get('blog', {}).get('avatar', ''),
                "BLOG_FAVICON": self.config.get('blog', {}).get('favicon', ''),
                "THEME_MODE": self.config.get('theme', {}).get('mode', 'dark'),
                "PRIMARY_COLOR": self.config.get('theme', {}).get('primary_color', '#e74c3c'),
                "TOTAL_TIME": self.config.get('special', {}).get('view', {}).get('Total_time', '2023.01.01'),
                "ARTICLES_JSON": json.dumps(regular_articles, ensure_ascii=False),
                "SPECIALS_JSON": json.dumps(special_articles, ensure_ascii=False),
                "MENU_ITEMS_JSON": json.dumps(self.config.get('floating_menu', []), ensure_ascii=False),
                "SPECIAL_TAGS": self.config.get('special_tags', ''),
            }
            
            rendered = tmpl.render(**context)
            
            index_path = os.path.join(DOCS_DIR, "index.html")
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(rendered)
            
            log(f"首页已生成: {index_path} ({len(rendered)} 字节)")
            
        except Exception as e:
            log(f"首页生成失败: {e}", "ERROR")
            import traceback
            traceback.print_exc()

    def run(self):
        """主运行流程"""
        log("=" * 60)
        log("VaLog Generator 启动")
        log("=" * 60)
        
        # 获取环境变量
        repo = os.getenv("REPO")
        token = os.getenv("GITHUB_TOKEN")
        
        if not repo or not token:
            log("错误: REPO 或 GITHUB_TOKEN 环境变量未设置", "ERROR")
            return 1
        
        log(f"GitHub仓库: {repo}")
        
        # 获取Issues
        issues = self.fetch_issues(repo, token)
        if not issues:
            log("未获取到任何文章", "WARNING")
            return 1
        
        # 获取配置
        blog_cfg = self.config.get('blog', {})
        theme_cfg = self.config.get('theme', {})
        special_cfg = self.config.get('special', {})
        
        # 处理所有文章
        all_articles = []
        new_cache = {}
        
        for issue in issues:
            try:
                article_data, updated_at = self.process_article(issue, blog_cfg, theme_cfg)
                
                # 创建列表用的简化版本（使用摘要）
                list_article = {
                    "id": article_data["id"],
                    "title": article_data["title"],
                    "date": article_data["date"],
                    "tags": article_data["tags"],
                    "content": article_data["summary"],  # 列表使用摘要
                    "url": article_data["url"],
                    "verticalTitle": article_data["verticalTitle"]
                }
                
                all_articles.append(list_article)
                new_cache[article_data["id"]] = updated_at
                
            except Exception as e:
                log(f"处理文章时出错: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                continue
        
        # 分类文章
        regular_articles, special_articles = self.categorize_articles(all_articles, special_cfg)
        
        log(f"\n文章统计:")
        log(f"  普通文章: {len(regular_articles)} 篇")
        log(f"  特殊文章: {len(special_articles)} 篇")
        log(f"  总计: {len(all_articles)} 篇")
        
        # 如果没有特殊文章，创建默认的
        if not special_articles:
            default_special = self.create_default_special(special_cfg)
            if default_special:
                special_articles.append(default_special)
                log("已添加默认特殊文章")
        
        # 保存缓存
        try:
            with open(OMD_JSON, 'w', encoding='utf-8') as f:
                json.dump(new_cache, f, indent=2, ensure_ascii=False)
            log(f"缓存已保存: {OMD_JSON}")
        except Exception as e:
            log(f"缓存保存失败: {e}", "ERROR")
        
        # 保存 base.yaml
        self.save_base_yaml(regular_articles, special_articles, blog_cfg, theme_cfg, special_cfg)
        
        # 生成首页
        self.generate_index(regular_articles, special_articles)
        
        log("=" * 60)
        log("VaLog Generator 完成")
        log("=" * 60)
        
        return 0


def main():
    try:
        generator = VaLogGenerator()
        return generator.run()
    except Exception as e:
        log(f"生成器运行失败: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
