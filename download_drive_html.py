import os
import json
import sys
import io
import random
import time
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ------------------------
# 服务账号配置
# ------------------------
service_account_info = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
if not service_account_info:
    print("❌ 未找到 GDRIVE_SERVICE_ACCOUNT 环境变量。")
    sys.exit(1)

try:
    service_account_info = json.loads(service_account_info)
except json.JSONDecodeError:
    print("❌ 解析 GDRIVE_SERVICE_ACCOUNT 失败。请确保它是一个有效的 JSON 字符串。")
    sys.exit(1)

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
service = build('drive', 'v3', credentials=creds)

# ------------------------
# 支持多文件夹 ID
# ------------------------
folder_ids_str = os.environ.get("GDRIVE_FOLDER_ID")
if not folder_ids_str:
    print("❌ 未找到 GDRIVE_FOLDER_ID 环境变量。")
    sys.exit(1)

FOLDER_IDS = [fid.strip() for fid in folder_ids_str.split(",") if fid.strip()]

# ------------------------
# 从 TXT 文件读取关键词
# ------------------------
keywords = []
keywords_file = "keywords.txt"
if os.path.exists(keywords_file):
    with open(keywords_file, "r", encoding="utf-8") as f:
        keywords = [line.strip() for line in f if line.strip()]

if not keywords:
    print("⚠️ keywords.txt 中没有找到关键词，将使用原始文件名。")

# ------------------------
# 记录已处理的文件 ID 和文件列表缓存
# ------------------------
processed_file_path = "processed_files.json"
cache_file_path = "files_cache.json"
CACHE_EXPIRY_HOURS = 24  # 缓存有效期（小时）

try:
    if os.path.exists(processed_file_path):
        with open(processed_file_path, "r") as f:
            processed_data = json.load(f)
    else:
        processed_data = {"fileIds": []}
except (json.JSONDecodeError, IOError) as e:
    print(f"读取 {processed_file_path} 时出错: {e}。将从一个空的已处理文件列表开始。")
    processed_data = {"fileIds": []}

def get_cached_files():
    """从缓存中读取文件列表，如果缓存过期则返回None。"""
    if os.path.exists(cache_file_path):
        try:
            with open(cache_file_path, "r") as f:
                cache_data = json.load(f)
                last_updated = cache_data.get("last_updated")
                if last_updated and (time.time() - last_updated < CACHE_EXPIRY_HOURS * 3600):
                    print("✅ 缓存未过期，正在从本地加载文件列表。")
                    return cache_data.get("files", [])
                else:
                    print(f"⏳ 缓存已过期（上次更新超过 {CACHE_EXPIRY_HOURS} 小时），将重新拉取文件列表。")
        except (json.JSONDecodeError, IOError) as e:
            print(f"读取 {cache_file_path} 时出错: {e}。将重新拉取文件列表。")
    return None

def save_files_to_cache(files):
    """将文件列表和当前时间戳保存到缓存文件。"""
    cache_data = {
        "last_updated": time.time(),
        "files": files
    }
    with open(cache_file_path, "w") as f:
        json.dump(cache_data, f, indent=4)
    print("💾 已将文件列表保存到本地缓存。")

# ------------------------
# 获取文件列表的函数
# ------------------------
def list_files(folder_id):
    """列出指定 Google Drive 文件夹中的所有文件，支持分页。"""
    all_the_files = []
    page_token = None
    query = f"'{folder_id}' in parents and (" \
            "mimeType='text/html' or " \
            "mimeType='text/plain' or " \
            "mimeType='application/vnd.google-apps.document')"
    try:
        while True:
            results = service.files().list(
                q=query,
                pageSize=1000,
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token
            ).execute()
            items = results.get('files', [])
            all_the_files.extend(items)
            page_token = results.get('nextPageToken', None)
            if page_token is None:
                break
        print(f"  - 在文件夹 {folder_id} 中总共找到 {len(all_the_files)} 个文件。")
        return all_the_files
    except Exception as e:
        print(f"列出文件时发生错误: {e}")
        return []

# ------------------------
# 下载和生成 HTML
# ------------------------
def download_and_process_file(file_id, mime_type, original_name, new_file_name):
    """
    下载文件并将其转换为一个干净的、标准的HTML文件。
    - 统一处理所有文件类型，先提取纯文本，再重建HTML。
    """
    if mime_type == 'application/vnd.google-apps.document':
        request = service.files().export_media(fileId=file_id, mimeType='text/html')
    elif mime_type == 'text/html' or mime_type == 'text/plain':
        request = service.files().get_media(fileId=file_id)
    else:
        print(f"跳过不支持的文件类型: {mime_type}")
        return

    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    content = fh.getvalue().decode('utf-8', errors='ignore')
    
    # 使用正则表达式彻底移除所有 HTML 标签，只保留纯文本
    clean_text = re.sub(r'<[^>]+>', '', content)

    # 用一个全新的、完整的HTML模板包裹纯文本内容
    html_content = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{original_name}</title></head><body><pre>{clean_text}</pre></body></html>"
    with open(new_file_name, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"✅ 已处理并保存为: {new_file_name}")

# ------------------------
# 主程序
# ------------------------
all_files = get_cached_files()

if all_files is None:
    all_files = []
    total_files_found = 0
    print("⏳ 正在从 Google Drive 拉取所有文件列表...")
    for folder_id in FOLDER_IDS:
        print(f"📂 正在获取文件夹: {folder_id}")
        files = list_files(folder_id)
        file_count = len(files)
        all_files.extend(files)
        total_files_found += file_count
        print(f"✅ 文件夹 [{folder_id}] 共找到 {file_count} 个文件。")
    save_files_to_cache(all_files)
    print(f"🚀 任务完成：总共从 {len(FOLDER_IDS)} 个文件夹中找到 {total_files_found} 个文件。")

# 新增逻辑：找出并修复缺失的文件
local_files = [f for f in os.listdir(".") if f.endswith(".html")]
local_file_names = {os.path.basename(f) for f in local_files}
processed_file_ids_set = set(processed_data["fileIds"])
cached_file_ids_set = {f['id'] for f in all_files}
 
# 找出processed_files.json中ID存在但本地文件缺失的文件
missing_files_to_reprocess = []
for file_info in all_files:
    if file_info['id'] in processed_file_ids_set:
        keyword_match = next((kw for kw in keywords if file_info['name'].startswith(kw)), None)
        # 根据关键词或者随机名称来匹配文件名
        expected_file_name = f"{keyword_match}.html" if keyword_match else None
        if not expected_file_name or expected_file_name not in local_file_names:
            # 如果文件名不匹配，则检查是否存在以文件ID命名的文件
            if not any(file_info['id'] in f for f in local_file_names):
                missing_files_to_reprocess.append(file_info)

# 找出新文件
new_files = [f for f in all_files if f['id'] not in processed_file_ids_set]
final_files_to_process = new_files + missing_files_to_reprocess

if not final_files_to_process:
    print("✅ 没有新的或缺失的文件需要处理。")
    print("重新生成所有页面的内部链接...")
else:
    print(f"发现 {len(new_files)} 个新文件，以及 {len(missing_files_to_reprocess)} 个缺失文件，本次将处理 {len(final_files_to_process)} 个文件。")
    num_to_process = min(len(final_files_to_process), 30)
    selected_files = random.sample(final_files_to_process, num_to_process)
    print(f"本次运行将处理 {len(selected_files)} 个文件。")

    available_keywords = list(keywords)
    keywords_ran_out = False

    for f in selected_files:
        if available_keywords:
            keyword = available_keywords.pop(0)
            safe_name = keyword + ".html"
        else:
            if not keywords_ran_out:
                print("⚠️ 关键词已用完，将使用原始文件名加随机后缀。")
                keywords_ran_out = True
            
            base_name = os.path.splitext(f['name'])[0]
            sanitized_name = base_name.replace(" ", "-").replace("/", "-")
            random_suffix = str(random.randint(1000, 9999))
            safe_name = f"{sanitized_name}-{random_suffix}.html"

        print(f"正在处理 '{f['name']}' -> '{safe_name}'")

        download_and_process_file(f['id'], f['mimeType'], f['name'], safe_name)
        
        # 只将真正处理过的新文件ID添加到processed_data中
        if f in new_files:
            processed_data["fileIds"].append(f['id'])

    with open(processed_file_path, "w") as f:
        json.dump(processed_data, f, indent=4)
    print(f"💾 已将新处理的文件 ID 保存到 {processed_file_path}")

    with open(keywords_file, "w", encoding="utf-8") as f:
        for keyword in available_keywords:
            f.write(keyword + "\n")
    print(f"✅ 已用剩余的关键词更新 {keywords_file}")

# ------------------------
# 生成累积的站点地图
# ------------------------
existing_html_files = [f for f in os.listdir(".") if f.endswith(".html") and f != "index.html"]
index_content = "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Reading Glasses</title></head><body>\n"
index_content += "<h1>Reading Glasses</h1>\n<ul>\n"
for fname in sorted(existing_html_files):
    index_content += f'<li><a href="{fname}">{fname}</a></li>\n'
index_content += "</ul>\n</body></html>"

with open("index.html", "w", encoding="utf-8") as f:
    f.write(index_content)
print("✅ 已生成 index.html (完整站点地图)")

# ------------------------
# 在每个页面底部添加随机内部链接
# ------------------------
all_html_files = [f for f in os.listdir(".") if f.endswith(".html") and f != "index.html"]

# 这个正则表达式会匹配并删除所有重复的 <!DOCTYPE html> 头部
doctype_pattern = re.compile(r'(<!DOCTYPE html>.*?)<!DOCTYPE html>', re.DOTALL | re.IGNORECASE)

for fname in all_html_files:
    try:
        with open(fname, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # 使用正则表达式来清理重复的 HTML 头部
        cleaned_content = re.sub(doctype_pattern, r'\1', content)

        # 接下来，我们检查并添加底部链接
        cleaned_content = re.sub(r"<footer.*?</footer>", "", cleaned_content, flags=re.DOTALL | re.IGNORECASE)
        
        other_files = [x for x in all_html_files if x != fname]
        num_links = min(len(other_files), random.randint(4, 6))

        links_html = ""
        if num_links > 0:
            random_links = random.sample(other_files, num_links)
            links_html = "<footer><ul>\n" + "\n".join([f'<li><a href="{x}">{x}</a></li>' for x in random_links]) + "\n</ul></footer>"

        if "</body>" in cleaned_content:
            final_content = cleaned_content.replace("</body>", links_html + "</body>")
        else:
            final_content = cleaned_content + links_html + "</body></html>"
        
        with open(fname, "w", encoding="utf-8") as f:
            f.write(final_content)
            
    except Exception as e:
        print(f"无法为 {fname} 处理内部链接: {e}")

print("✅ 已为所有页面更新底部随机内部链接 (每个 4-6 个，完全刷新)")
