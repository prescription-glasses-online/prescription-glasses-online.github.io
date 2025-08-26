
import os
import json
import sys
import io
import random
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ------------------------
# 服务账号配置
# ------------------------
# 从环境变量中获取服务账号信息
service_account_info = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
if not service_account_info:
    print("❌ 未找到 GDRIVE_SERVICE_ACCOUNT 环境变量。")
    sys.exit(1)

# 从 JSON 字符串加载服务账号凭证
try:
    service_account_info = json.loads(service_account_info)
except json.JSONDecodeError:
    print("❌ 解析 GDRIVE_SERVICE_ACCOUNT 失败。请确保它是一个有效的 JSON 字符串。")
    sys.exit(1)

# 定义 Google Drive 的只读权限范围
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
# 根据服务账号信息创建凭证
creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
# 构建 Google Drive API 服务
service = build('drive', 'v3', credentials=creds)

# ------------------------
# 支持多文件夹 ID
# ------------------------
# 从环境变量获取文件夹 ID
folder_ids_str = os.environ.get("GDRIVE_FOLDER_ID")
if not folder_ids_str:
    print("❌ 未找到 GDRIVE_FOLDER_ID 环境变量。")
    sys.exit(1)

# 将文件夹 ID 字符串拆分为列表，并去除多余的空格
FOLDER_IDS = [fid.strip() for fid in folder_ids_str.split(",") if fid.strip()]

# ------------------------
# 从 TXT 文件读取关键词
# ------------------------
keywords = []
keywords_file = "keywords.txt"
if os.path.exists(keywords_file):
    with open(keywords_file, "r", encoding="utf-8") as f:
        # 读取文件中的每一行，去除首尾空格，并添加到关键词列表
        keywords = [line.strip() for line in f if line.strip()]

if not keywords:
    print("⚠️ keywords.txt 中没有找到关键词，将使用原始文件名。")

# ------------------------
# 记录已处理的文件 ID
# ------------------------
processed_file_path = "processed_files.json"
try:
    if os.path.exists(processed_file_path):
        with open(processed_file_path, "r") as f:
            processed_data = json.load(f)
    else:
        # 如果文件不存在，创建一个新的数据结构
        processed_data = {"fileIds": []}
except (json.JSONDecodeError, IOError) as e:
    print(f"读取 {processed_file_path} 时出错: {e}。将从一个空的已处理文件列表开始。")
    processed_data = {"fileIds": []}


# ------------------------
# 获取文件列表的函数
# ------------------------
def list_files(folder_id):
    """列出指定 Google Drive 文件夹中的所有文件，支持分页。"""
    all_the_files = []
    page_token = None
    page_count = 0
    # 查询特定 MIME 类型的文件
    query = f"'{folder_id}' in parents and (" \
            "mimeType='text/html' or " \
            "mimeType='text/plain' or " \
            "mimeType='application/vnd.google-apps.document')"
    try:
        while True:
            page_count += 1
            print(f"  - 正在获取第 {page_count} 页文件...")
            results = service.files().list(
                q=query,
                pageSize=1000,
                # 重要：fields 必须包含 nextPageToken 才能在响应中获取它
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token
            ).execute()
            
            items = results.get('files', [])
            all_the_files.extend(items)
            
            page_token = results.get('nextPageToken', None)
            if page_token is None:
                break # 没有更多页面了，退出循环
        
        print(f"  - 在文件夹 {folder_id} 中总共找到 {len(all_the_files)} 个文件。")
        return all_the_files
        
    except Exception as e:
        print(f"列出文件时发生错误: {e}")
        return []

# ------------------------
# 下载和生成 HTML
# ------------------------
def download_html_file(file_id, file_name):
    """下载一个 HTML 文件。"""
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(file_name, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    print(f"✅ 已下载 {file_name}")

def download_txt_file(file_id, file_name, original_name):
    """下载一个文本文件并将其转换为 HTML。"""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    text_content = fh.getvalue().decode('utf-8')
    # 从文本内容创建 HTML
    html_content = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{original_name}</title></head><body><pre>{text_content}</pre></body></html>"
    with open(file_name, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"✅ TXT 已转换为 HTML: {file_name}")

def export_google_doc(file_id, file_name):
    """将 Google 文档导出为 HTML。"""
    request = service.files().export_media(fileId=file_id, mimeType='text/html')
    fh = io.FileIO(file_name, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    print(f"✅ Google 文档已导出为 HTML: {file_name}")

# ------------------------
# 主程序
# ------------------------
all_files = []
for folder_id in FOLDER_IDS:
    print(f"📂 正在从文件夹获取文件: {folder_id}")
    files = list_files(folder_id)
    # 过滤掉已经处理过的文件
    new_files = [f for f in files if f['id'] not in processed_data["fileIds"]]
    all_files.extend(new_files)

if not all_files:
    print("✅ 没有新的文件需要处理。")
    sys.exit(0)

print(f"发现 {len(all_files)} 个新文件需要处理。")

# 随机选择最多 30 个文件进行处理
num_to_process = min(len(all_files), 30)
selected_files = random.sample(all_files, num_to_process)

print(f"本次运行将处理 {len(selected_files)} 个文件。")

# 创建一个关键词的副本，用于消耗
available_keywords = list(keywords)
keywords_ran_out = False

for f in selected_files:
    # 如果还有可用的关键词，则使用第一个并将其从列表中移除
    if available_keywords:
        keyword = available_keywords.pop(0)
        safe_name = keyword + ".html"
    else:
        # **关键改动**: 关键词用完后，使用原始文件名 + 随机后缀
        if not keywords_ran_out:
            print("⚠️ 关键词已用完，将使用原始文件名加随机后缀。")
            keywords_ran_out = True
        
        # 1. 清理原始文件名，移除可能存在的扩展名
        base_name = os.path.splitext(f['name'])[0]
        sanitized_name = base_name.replace(" ", "-").replace("/", "-")
        # 2. 生成一个4位的随机数字后缀
        random_suffix = str(random.randint(1000, 9999))
        # 3. 组合成最终文件名
        safe_name = f"{sanitized_name}-{random_suffix}.html"

    print(f"正在处理 '{f['name']}' -> '{safe_name}'")

    # 根据文件的 MIME 类型下载或导出文件
    if f['mimeType'] == 'text/html':
        download_html_file(f['id'], safe_name)
    elif f['mimeType'] == 'text/plain':
        download_txt_file(f['id'], safe_name, f['name'])
    else: # 'application/vnd.google-apps.document'
        export_google_doc(f['id'], safe_name)

    # 将文件 ID 添加到已处理文件列表
    processed_data["fileIds"].append(f['id'])

# 保存更新后的已处理文件 ID 列表
with open(processed_file_path, "w") as f:
    json.dump(processed_data, f, indent=4)
print(f"💾 已将 {len(selected_files)} 个新文件 ID 保存到 {processed_file_path}")

# 将剩余的关键词写回 keywords.txt 文件
with open(keywords_file, "w", encoding="utf-8") as f:
    for keyword in available_keywords:
        f.write(keyword + "\n")
print(f"✅ 已用剩余的关键词更新 {keywords_file}")


# ------------------------
# 生成累积的站点地图
# ------------------------
# 获取目录中所有现有的 HTML 文件
existing_html_files = [f for f in os.listdir(".") if f.endswith(".html") and f != "index.html"]
index_content = "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Reading Glasses</title></head><body>\n"
index_content += "<h1>Reading Glasses</h1>\n<ul>\n"
# 为每个 HTML 文件在索引中添加一个链接
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

for fname in all_html_files:
    try:
        # 读取 HTML 文件的内容
        with open(fname, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # 从潜在链接列表中排除当前文件
        other_files = [x for x in all_html_files if x != fname]
        # 确定要添加的随机链接数量（4 到 6 个之间）
        num_links = min(len(other_files), random.randint(4, 6))

        if num_links > 0:
            # 随机选择要链接的文件
            random_links = random.sample(other_files, num_links)
            # 为页脚链接创建 HTML
            links_html = "<footer><ul>\n" + "\n".join([f'<li><a href="{x}">{x}</a></li>' for x in random_links]) + "\n</ul></footer>"
            # 将链接附加到文件内容
            content += links_html

        # 将更新后的内容写回文件
        with open(fname, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"无法为 {fname} 处理内部链接: {e}")

print("✅ 已为所有页面更新底部随机内部链接 (每个 4-6 个，完全刷新)")
