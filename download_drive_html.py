import os
import json
import sys
import io
import random
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ------------------------
# 配置服务账号
# ------------------------
service_account_info = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
if not service_account_info:
    print("❌ GDRIVE_SERVICE_ACCOUNT not found")
    sys.exit(1)

service_account_info = json.loads(service_account_info)
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
service = build('drive', 'v3', credentials=creds)

# ------------------------
# 多文件夹 ID 支持
# ------------------------
folder_ids_str = os.environ.get("GDRIVE_FOLDER_ID")
if not folder_ids_str:
    print("❌ GDRIVE_FOLDER_ID not found")
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
    print("⚠️ No keywords found in keywords.txt, will use original file names")

# ------------------------
# 记录已处理文件 ID
# ------------------------
processed_file_path = "processed_files.json"
if os.path.exists(processed_file_path):
    with open(processed_file_path, "r") as f:
        processed_data = json.load(f)
else:
    processed_data = {"fileIds": []}

# ------------------------
# 获取文件列表函数
# ------------------------
def list_files(folder_id):
    query = f"'{folder_id}' in parents and (" \
            "mimeType='text/html' or " \
            "mimeType='text/plain' or " \
            "mimeType='application/vnd.google-apps.document')" 
    results = service.files().list(
        q=query,
        pageSize=1000,
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get('files', [])

# ------------------------
# 下载和生成 HTML
# ------------------------
def download_html_file(file_id, file_name):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(file_name, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    print(f"✅ Downloaded {file_name}")

def download_txt_file(file_id, file_name):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    text_content = fh.getvalue().decode('utf-8')
    html_content = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{file_name}</title></head><body><pre>{text_content}</pre></body></html>"
    with open(file_name, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"✅ TXT converted to HTML: {file_name}")

def export_google_doc(file_id, file_name):
    request = service.files().export_media(fileId=file_id, mimeType='text/html')
    fh = io.FileIO(file_name, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    print(f"✅ Exported Google Doc to HTML: {file_name}")

# ------------------------
# 主程序
# ------------------------
all_files = []
for folder_id in FOLDER_IDS:
    files = list_files(folder_id)
    # 排除已处理文件
    files = [f for f in files if f['id'] not in processed_data["fileIds"]]
    all_files.extend(files)

if not all_files:
    print("⚠️ No new files to process")
    sys.exit(0)

# 随机选 30 个文件
selected_files = random.sample(all_files, min(len(all_files), 30))

safe_files = []
for idx, f in enumerate(selected_files):
    if idx < len(keywords):
        safe_name = keywords[idx] + ".html"
    else:
        safe_name = f['name'].replace(" ", "-") + ".html"

    if f['mimeType'] == 'text/html':
        download_html_file(f['id'], safe_name)
    elif f['mimeType'] == 'text/plain':
        download_txt_file(f['id'], safe_name)
    else:
        export_google_doc(f['id'], safe_name)

    safe_files.append(safe_name)
    # 记录已处理文件 ID
    processed_data["fileIds"].append(f['id'])

# 保存 processed_files.json
with open(processed_file_path, "w") as f:
    json.dump(processed_data, f)

# ------------------------
# 生成首页累积导航（Site Map）
# ------------------------
existing_html_files = [f for f in os.listdir(".") if f.endswith(".html") and f != "index.html"]
index_content = "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Reading Glasses</title></head><body>\n"
index_content += "<h1>Reading Glasses</h1>\n<ul>\n"
for fname in sorted(existing_html_files):
    index_content += f'<li><a href="{fname}">{fname}</a></li>\n'
index_content += "</ul>\n</body></html>"

with open("index.html", "w", encoding="utf-8") as f:
    f.write(index_content)
print("✅ index.html (full site map) generated")

# ------------------------
# ------------------------
# ------------------------
# 底部随机内部链接（全量刷新 4~6 条）
# ------------------------
all_html_files = [f for f in os.listdir(".") if f.endswith(".html") and f != "index.html"]

for fname in all_html_files:
    # 使用 errors="replace" 遇到非法字符显示为 �
    with open(fname, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # 排除当前文件，随机选择 4~6 个内部链接
    other_files = [x for x in all_html_files if x != fname]
    num_links = min(len(other_files), random.randint(4, 6))
    if num_links > 0:
        random_links = random.sample(other_files, num_links)
        links_html = "<footer><ul>\n" + "\n".join([f'<li><a href="{x}">{x}</a></li>' for x in random_links]) + "\n</ul></footer>"
        content += links_html

    with open(fname, "w", encoding="utf-8") as f:
        f.write(content)

print("✅ Bottom random internal links updated for all pages (4~6 each, full refresh)")
