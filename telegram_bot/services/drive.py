from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
import logging
from ..config import DRIVE_FOLDER_NAME

def get_or_create_folder(service, folder_name):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)', pageSize=1).execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    folder = service.files().create(body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}, fields='id').execute()
    return folder.get('id')

def auto_cleanup_drive(threshold_bytes=14 * 1024**3):
    creds = Credentials.from_authorized_user_file('token.json')
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    usage = int(service.about().get(fields="storageQuota").execute()['storageQuota']['usage'])
    if usage < threshold_bytes:
        return
    folder_id = get_or_create_folder(service, DRIVE_FOLDER_NAME)
    files = service.files().list(q=f"'{folder_id}' in parents and trashed=false", orderBy="createdTime", fields="files(id, name)").execute().get('files', [])
    for file in files:
        try:
            service.files().delete(fileId=file['id']).execute()
            logging.info(f"🗑️ Menghapus file lama: {file['name']}")
            usage = int(service.about().get(fields="storageQuota").execute()['storageQuota']['usage'])
            if usage < threshold_bytes:
                break
        except Exception as e:
            logging.error(f"❌ Gagal hapus file lama: {e}")

def upload_to_drive(file_path):
    creds = Credentials.from_authorized_user_file('token.json')
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    folder_id = get_or_create_folder(service, DRIVE_FOLDER_NAME)
    auto_cleanup_drive()

    file_name = os.path.basename(file_path)

    # ✅ Cek apakah file dengan nama yang sama sudah ada
    query = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)', pageSize=1).execute()
    files = results.get('files', [])

    if files:
        # ⚠️ File sudah ada → kirim ulang link-nya
        logging.info(f"📄 File sudah ada di Drive: {file_name}")
        file_id = files[0]['id']
    else:
        # 🚀 Upload file baru
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaFileUpload(file_path, resumable=True)
        uploaded_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        file_id = uploaded_file.get('id')
        service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        logging.info(f"✅ File diupload ke Drive: {file_name}")

    return f"https://drive.google.com/file/d/{file_id}/view"

def get_drive_usage():
    creds = Credentials.from_authorized_user_file('token.json')
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    quota = service.about().get(fields="storageQuota").execute()['storageQuota']
    limit = int(quota.get('limit', 0))
    usage = int(quota.get('usage', 0))
    free = limit - usage
    def fmt(b):
        for u in ['B', 'KB', 'MB', 'GB', 'TB']:
            if b < 1024.0:
                return f"{b:.2f} {u}"
            b /= 1024.0
        return f"{b:.2f} PB"
    return f"{fmt(free)} / {fmt(limit)}"
