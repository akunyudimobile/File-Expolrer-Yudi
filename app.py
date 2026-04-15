import streamlit as st
import streamlit.components.v1 as components
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="OmniCloud - Unified Storage Manager",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CONFIG & SECRETS ---
try:
    CLIENT_CONFIG = {
        "web": {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "project_id": "file-explorer-nmsa",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "redirect_uris": [
                "https://file-expolrer-yudi.streamlit.app", 
                "http://localhost:8501"
            ]
        }
    }
except Exception as e:
    st.error("⚠️ Konfigurasi Google belum lengkap di Dashboard Secrets.")
    st.stop()

app_id = "omnicloud-v1"

@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            if "FIREBASE_SECRET" in st.secrets:
                raw_json = st.secrets["FIREBASE_SECRET"].strip()
                secret_dict = json.loads(raw_json)
                cred = credentials.Certificate(secret_dict)
                firebase_admin.initialize_app(cred)
                return firestore.client()
            elif os.path.exists('serviceAccountKey.jso.json'):
                cred = credentials.Certificate('serviceAccountKey.jso.json')
                firebase_admin.initialize_app(cred)
                return firestore.client()
        except Exception as e:
            st.error(f"❌ Firebase Error: {str(e)}")
            return None
    return firestore.client()

db = init_firebase()

# --- 3. MANAJEMEN SESI ---
if 'user' not in st.session_state: 
    st.session_state.user = None
if 'google_token' not in st.session_state: 
    st.session_state.google_token = None

# --- 4. LOGIKA GOOGLE DRIVE ---
def get_google_auth_flow():
    return Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=[
            'https://www.googleapis.com/auth/drive.readonly', 
            'openid', 
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ],
        redirect_uri=CLIENT_CONFIG["web"]["redirect_uris"][0]
    )

def sync_google_drive_files(token):
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_info(token)
        service = build('drive', 'v3', credentials=creds)
        
        # Ambil user info untuk identitas
        user_info = service.about().get(fields="user").execute()
        user_name = user_info.get('user', {}).get('displayName', 'User Google')
        
        results = service.files().list(
            pageSize=25, 
            fields="files(id, name, size, mimeType)"
        ).execute()
        items = results.get('files', [])
        
        if db and st.session_state.user:
            manager = FirestoreManager(st.session_state.user['uid'])
            for item in items:
                size_raw = item.get('size')
                size_str = f"{int(size_raw) // 1024} KB" if size_raw else "Folder"
                manager.add_file_metadata(
                    name=item['name'], 
                    size=size_str, 
                    source="Google Drive", 
                    file_type="file" if size_raw else "folder", 
                    icon="🟢"
                )
        return user_name
    except Exception as e:
        st.error(f"Gagal sinkronisasi: {e}")
        return None

# --- 5. FIRESTORE MANAGER ---
class FirestoreManager:
    def __init__(self, user_id):
        self.user_id = user_id
        self.collection_path = f"artifacts/{app_id}/users/{self.user_id}/files"

    def get_user_files(self):
        if not db: return []
        try:
            docs = db.collection(self.collection_path).stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            return []

    def add_file_metadata(self, name, size, source, file_type, icon):
        if not db: return
        file_id = f"file_{int(datetime.now().timestamp())}_{name[:10].replace(' ', '_')}"
        db.collection(self.collection_path).document(file_id).set({
            "id": file_id,
            "name": name,
            "size": size,
            "source": source,
            "type": file_type,
            "icon": icon,
            "created_at": datetime.now().isoformat()
        })

# --- 6. RENDER UI ---
def load_ui():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
            if st.session_state.user:
                manager = FirestoreManager(st.session_state.user['uid'])
                files = manager.get_user_files()
                html = html.replace("files: [", f"files: {json.dumps(files)}, \n _old: [")
                html = html.replace('id="login-overlay"', 'id="login-overlay" style="display:none;"')
            return html
    return "<h1>index.html tidak ditemukan.</h1>"

# --- 7. PENANGANAN LOGIN OTOMATIS (Setelah Redirect) ---
if "code" in st.query_params and not st.session_state.user:
    try:
        flow = get_google_auth_flow()
        flow.fetch_token(code=st.query_params["code"])
        creds = flow.credentials
        
        # Simpan token
        token_data = json.loads(creds.to_json())
        st.session_state.google_token = token_data
        
        # Buat identitas sementara untuk Firestore
        st.session_state.user = {
            "uid": creds.client_id[:15] if creds.client_id else "user_default",
            "name": "Menghubungkan..."
        }
        
        # Sinkronisasi awal untuk mengambil nama user asli
        real_name = sync_google_drive_files(token_data)
        if real_name:
            st.session_state.user["name"] = real_name
            
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Login Gagal: {e}")

# Tampilkan HTML Utama
components.html(load_ui(), height=850, scrolling=False)

# Sidebar Kontrol
with st.sidebar:
    st.title("☁️ OmniCloud")
    st.markdown("---")
    
    if not st.session_state.user:
        st.info("Penyimpanan belum terhubung.")
        auth_url, _ = get_google_auth_flow().authorization_url(prompt='consent', access_type='offline')
        st.markdown(f'''
            <a href="{auth_url}" target="_self" 
            style="text-decoration:none; color:white; background:#4285F4; 
            padding:12px 20px; border-radius:8px; display:block; text-align:center; font-weight:bold;">
            🔑 Hubungkan Google Drive
            </a>
        ''', unsafe_allow_html=True)
    else:
        st.success(f"Terkoneksi: {st.session_state.user['name']}")
        if st.button("🔄 Segarkan Data Drive"):
            with st.spinner("Sinkronisasi..."):
                sync_google_drive_files(st.session_state.google_token)
                st.rerun()
        
        if st.button("🚪 Putuskan Koneksi"):
            st.session_state.user = None
            st.session_state.google_token = None
            st.rerun()

    st.markdown("---")
    if db:
        st.caption("🟢 Cloud Database Active")
    else:
        st.caption("🔴 Database Offline")
