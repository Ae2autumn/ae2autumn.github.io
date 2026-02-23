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
DOCS_DIR = os.path.join(BASE_DIR, "docs") # docs 目录
ARTICLE_DIR = os.path.join(DOCS_DIR, "article")
OMD_DIR = os.path.join(BASE_DIR, "O-MD")
OMD_JSON = os.path.join(OMD_DIR, "articles.json")
BASE_YAML_OUT = os.path.join(BASE_DIR, "base.yaml")

# 新增：本地 Posts 目录 (位于 docs 目录下)
LOCAL_POSTS_DIR = os.path.join(DOCS_DIR, "posts")

DEFAULT_ARTICLE_TEMPLATE = "article.html"
DEFAULT_HOME_TEMPLATE = "home.html"

# 创建输出目录
os.makedirs(ARTICLE_DIR, exist_ok=True)
os.makedirs(OMD_DIR, exist_ok=True)
# 创建本地 posts 目录（如果不存在）
os.makedirs(LOCAL_POSTS_DIR, exist_ok=True)


class VaLogGenerator:
    def __init__(self):
        print("=" * 50)
        print("🚀 VaLog Generator 初始化中...")

        # 加载配置
        self.config = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
        
        # 读取数据源模式
        self.data_source_mode = self.config.get('data_source_mode', 'dual').lower()
        print(f"📋 数据源模式: {self.data_source_mode}")

        self.article_template_name = self.config.get('templates', {}).get(
            'VaLog-default-article', DEFAULT_ARTICLE_TEMPLATE
        )
        self.home_template_name = self.config.get('templates', {}).get(
            'VaLog-default-index', DEFAULT_HOME_TEMPLATE
        )

        # 加载并迁移缓存
        self.cache = self._load_and_migrate_cache()

        # Jinja2 模板引擎
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )
        # --- 优化点 2: 预加载模板 ---
        self.article_template = self.env.get_template(self.article_template_name)
        self.home_template = self.env.get_template(self.home_template_name)

    def _load_and_migrate_cache(self):
        """加载缓存并处理旧格式到新格式的迁移"""
        cache = {}
        if os.path.exists(OMD_JSON):
            try:
                with open(OMD_JSON, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            except Exception as e:
                print(f"⚠️ 缓存加载失败: {e}")
        
        # 检查并迁移旧格式缓存
        # 旧格式: { "issue_number": "updated_at_string" }
        # 新格式: { "id": { "type": "issue|local_file", "last_modified": "..." } }
        migrated = False
        for key, value in list(cache.items()): # 使用 list() 避免在迭代时修改字典
            # 如果值是字符串，说明是旧格式 (一定是 issue)
            if isinstance(value, str):
                print(f"🔄 迁移旧缓存条目: #{key}")
                cache[key] = {
                    "type": "issue",
                    "last_modified": value
                }
                migrated = True
        
        if migrated:
            print("💾 保存迁移后的缓存...")
            with open(OMD_JSON, 'w', encoding='utf-8') as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        
        return cache

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

    def get_issues_articles(self):
        """从 GitHub Issues 获取文章数据"""
        repo = os.getenv("REPO")
        token = os.getenv("GITHUB_TOKEN")
        if not repo or not token:
            print("❌ 错误: 请设置环境变量 REPO (如 user/repo) 和 GITHUB_TOKEN")
            return [], set()

        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

        try:
            url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            issues = [i for i in resp.json() if not i.get("pull_request")]
            print(f"✅ 成功获取 {len(issues)} 篇 GitHub Issues 文章")
            
            # 返回 issues 列表和 ID 集合
            return issues, {str(i['number']) for i in issues}
        except Exception as e:
            print(f"❌ GitHub API 请求失败: {e}")
            return [], set()

    def get_local_files_articles(self):
        """从本地 docs/posts 目录获取文章数据"""
        local_articles = []
        local_ids = set()

        if not os.path.isdir(LOCAL_POSTS_DIR):
            print(f"⚠️ 本地文章目录不存在: {LOCAL_POSTS_DIR}")
            return local_articles, local_ids

        md_files = [f for f in os.listdir(LOCAL_POSTS_DIR) if f.lower().endswith('.md')]
        print(f"📁 在本地目录 {LOCAL_POSTS_DIR} 找到 {len(md_files)} 个 Markdown 文件")
        
        for filename in md_files:
            file_path = os.path.join(LOCAL_POSTS_DIR, filename)
            file_id = os.path.splitext(filename)[0] # 去掉 .md 后缀作为 ID
            local_ids.add(file_id)
            
            # --- 优化点 3 & 5: 获取并缓存 mtime 和 iso 时间 ---
            try:
                mtime = os.path.getmtime(file_path)
                updated_at_iso = datetime.fromtimestamp(mtime).isoformat()
            except OSError as e:
                print(f"⚠️ 无法访问本地文件 {file_path}: {e}, 跳过")
                continue
            
            # 为本地文件创建一个类似 issue 的结构，方便后续处理
            local_article = {
                "id": file_id,
                "title": file_id, # 默认标题为文件名
                "created_at": updated_at_iso, # 使用修改时间作为创建时间
                "updated_at": updated_at_iso,
                "body": self._read_file_with_fallback(file_path), # 读取文件内容
                "labels": [] # 本地文件默认无标签
            }
            local_articles.append(local_article)
        
        return local_articles, local_ids

    def _read_file_with_fallback(self, file_path, encodings=['utf-8', 'gbk', 'latin-1']):
        """尝试多种编码读取文件"""
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ValueError(f"无法使用常见编码读取文件: {file_path}")

    def run(self):
        # 根据配置决定数据源
        all_issues = []
        all_local_articles = []
        remote_ids = set()
        local_ids = set()

        if self.data_source_mode in ['issues_only', 'dual']:
            all_issues, remote_ids = self.get_issues_articles()
        if self.data_source_mode in ['local_only', 'dual']:
            all_local_articles, local_ids = self.get_local_files_articles()
        
        # 合并所有活跃 ID
        all_active_ids = remote_ids | local_ids

        # === 🔄 清理逻辑：移除已不存在的源所对应的生成物 ===
        # 获取本地所有“已知”的项目 ID 集合
        known_from_html = {
            f.replace('.html', '') 
            for f in os.listdir(ARTICLE_DIR) 
            if f.endswith('.html')
        }
        known_from_cache = set(self.cache.keys())
        all_known_ids = known_from_html | known_from_cache

        # 确定待删除列表
        to_delete = all_known_ids - all_active_ids
        
        for item_id in to_delete:
            print(f"🗑️ 清理已移除的文章: #{item_id}")
            # --- 优化点 5: 缓存路径 ---
            html_path = os.path.join(ARTICLE_DIR, f"{item_id}.html")
            # 删除 HTML 文件
            if os.path.exists(html_path):
                os.remove(html_path)
            
            # 删除 O-MD 中的 Markdown 文件 (仅适用于原来源为 Issue 的文章)
            cache_entry = self.cache.get(item_id)
            # 现在 cache_entry 一定是字典格式
            if cache_entry and cache_entry.get('type') == 'issue':
                 omd_md_path = os.path.join(OMD_DIR, f"{item_id}.md")
                 if os.path.exists(omd_md_path):
                     os.remove(omd_md_path)
            
            # 删除缓存记录
            if item_id in self.cache:
                del self.cache[item_id]


        # === 🔧 准备处理逻辑 ===
        to_process_issues = set()
        to_process_local = set()

        # --- 处理 Issues ---
        if self.data_source_mode in ['issues_only', 'dual']:
            for issue in all_issues:
                iid = str(issue['number'])
                updated_at = issue['updated_at']
                
                # --- 优化点 4: 使用预生成的集合检查 ---
                html_exists = iid in known_from_html
                
                # 获取缓存项并检查类型和时间
                cached_info = self.cache.get(iid)
                cache_is_issue_type = cached_info and cached_info.get('type') == 'issue'
                cache_time_matches = cached_info and cached_info.get('last_modified') == updated_at

                # 之前缓存了 issue，但 HTML 丢失了
                if cache_is_issue_type and cache_time_matches and not html_exists:
                    print(f"⚠️ Issue #{iid} HTML 丢失，将重建")
                    to_process_issues.add(iid)
                # 之前没缓存过
                elif not cached_info:
                    print(f"🆕 新 Issue 或缓存丢失: #{iid}")
                    to_process_issues.add(iid)
                # 缓存存在但时间不匹配（内容更新）
                elif cache_is_issue_type and not cache_time_matches:
                    print(f"🔄 Issue 内容已更新: #{iid}")
                    to_process_issues.add(iid)

        # --- 处理本地文件 ---
        if self.data_source_mode in ['local_only', 'dual']:
            for local_article in all_local_articles:
                lid = local_article['id']
                # 注意：这里必须实时获取mtime，因为文件可能在此期间被修改
                file_path = os.path.join(LOCAL_POSTS_DIR, f"{lid}.md")
                
                try:
                    current_mtime = os.path.getmtime(file_path)
                    current_mtime_iso = datetime.fromtimestamp(current_mtime).isoformat()
                except OSError:
                    print(f"⚠️ 无法访问本地文件 {file_path}, 跳过: #{lid}")
                    continue
                
                # --- 优化点 4: 使用预生成的集合检查 ---
                html_exists = lid in known_from_html
                
                # 获取缓存项并检查类型和时间
                cached_info = self.cache.get(lid)
                cache_is_local_type = cached_info and cached_info.get('type') == 'local_file'
                cache_time_matches = cached_info and cached_info.get('last_modified') == current_mtime_iso

                # 之前缓存了 local_file，但 HTML 丢失了
                if cache_is_local_type and cache_time_matches and not html_exists:
                    print(f"⚠️ 本地文件 #{lid} HTML 丢失，将重建")
                    to_process_local.add(lid)
                # 之前没缓存过
                elif not cached_info:
                    print(f"🆕 新本地文件: #{lid}")
                    to_process_local.add(lid)
                # 缓存存在但时间不匹配（文件更新）
                elif cache_is_local_type and not cache_time_matches:
                    print(f"🔄 本地文件内容已更新: #{lid}")
                    to_process_local.add(lid)

        # === 📝 开始处理需要生成的文章 ===
        all_articles = []
        specials = []
        special_tags = self.config.get('special_tags', [])

        # --- 优化点 1: 引入临时缓存字典用于批量更新 ---
        new_cache_updates = {}

        # --- 处理 Issues 文章 ---
        for issue in all_issues:
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

            if iid in to_process_issues:
                print(f"📝 处理 Issue 文章: #{iid} - {issue['title']}")
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

                # --- 优化点 5: 缓存路径 ---
                html_file_path = os.path.join(ARTICLE_DIR, f"{iid}.html")
                # 渲染 HTML
                # --- 优化点 2: 使用预加载的模板 ---
                with open(html_file_path, "w", encoding="utf-8") as f:
                    f.write(self.article_template.render(article=article_data, blog=self.config.get('blog', {})))

                # 保存原始 Markdown (仅 Issue)
                # --- 优化点 5: 缓存路径 ---
                omd_md_file_path = os.path.join(OMD_DIR, f"{iid}.md")
                with open(omd_md_file_path, "w", encoding="utf-8") as f:
                    f.write(issue.get('body') or "")

                # --- 优化点 1: 将缓存更新加入临时字典 ---
                new_cache_updates[iid] = {
                    "type": "issue",
                    "last_modified": issue['updated_at']
                }
                # self.cache[iid] = { "type": "issue", "last_modified": issue['updated_at'] } # 原代码

            # 添加到对应列表
            if is_special:
                specials.append(list_item)
            else:
                all_articles.append(list_item)

        # --- 处理本地文件文章 ---
        for local_article in all_local_articles:
            lid = local_article['id']
            # 本地文件默认无标签，所以不考虑 special
            is_special = False 

            # 构建列表项所需数据
            metadata = self.extract_metadata_and_body(local_article.get('body', ''))
            v_title = metadata["vertical_title"] or local_article['title'] or "Blog"
            list_item = {
                "id": lid,
                "title": local_article['title'],
                "date": local_article['created_at'][:10],
                "tags": local_article.get('labels', []), # 本地文件标签为空
                "content": metadata["summary"],
                "url": f"article/{lid}.html",
                "verticalTitle": v_title
            }

            if lid in to_process_local:
                print(f"📝 处理本地文件文章: #{lid} - {local_article['title']}")
                processed_html = self.process_body(metadata["body"])

                article_data = {
                    "id": lid,
                    "title": local_article['title'],
                    "date": local_article['created_at'][:10],
                    "tags": local_article.get('labels', []),
                    "content": processed_html,
                    "url": f"article/{lid}.html",
                    "verticalTitle": v_title,
                    "summary": metadata["summary"]
                }

                # --- 优化点 5: 缓存路径 ---
                html_file_path = os.path.join(ARTICLE_DIR, f"{lid}.html")
                # 渲染 HTML
                # --- 优化点 2: 使用预加载的模板 ---
                with open(html_file_path, "w", encoding="utf-8") as f:
                    f.write(self.article_template.render(article=article_data, blog=self.config.get('blog', {})))

                # --- 优化点 1: 将缓存更新加入临时字典 ---
                # file_path = os.path.join(LOCAL_POSTS_DIR, f"{lid}.md") # 这个变量在循环外已定义
                # current_mtime_iso = datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat() # 这个变量在循环外已计算
                new_cache_updates[lid] = {
                    "type": "local_file",
                    "last_modified": local_article['updated_at'] # 使用预计算好的 iso 时间
                }
                # self.cache[lid] = { "type": "local_file", "last_modified": current_mtime_iso } # 原代码

            # 添加到对应列表 (本地文件目前不支持 special 标签)
            if is_special:
                specials.append(list_item)
            else:
                all_articles.append(list_item)

        # --- 优化点 1: 统一应用缓存更新 ---
        self.cache.update(new_cache_updates)

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

        # 保存状态 (新格式)
        with open(OMD_JSON, 'w', encoding='utf-8') as f:
            # --- 优化点 1: 写入的是已合并更新的 self.cache ---
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
            # --- 优化点 2: 使用预加载的模板 ---
            # tmpl = self.env.get_template(self.home_template_name) # 原代码
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
                # --- 优化点 2: 使用预加载的模板 ---
                f.write(self.home_template.render(**ctx))
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