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
# Mengambil kredensial Google dari st.secrets Dashboard Streamlit Cloud
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
    st.error("⚠️ Konfigurasi Google (ID/Secret) belum lengkap di Dashboard Secrets.")
    st.stop()

# Nama unik untuk koleksi Firestore Anda
app_id = "omnicloud-v1"

@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            # PRIORITAS: Membaca dari Secrets Dashboard
            if "FIREBASE_SECRET" in st.secrets:
                # Membersihkan spasi atau karakter tak terlihat di sekitar string
                raw_json = st.secrets["FIREBASE_SECRET"].strip()
                secret_dict = json.loads(raw_json)
                cred = credentials.Certificate(secret_dict)
                firebase_admin.initialize_app(cred)
                return firestore.client()
            
            # FALLBACK: Jika dijalankan lokal dengan file fisik
            elif os.path.exists('serviceAccountKey.jso.json'):
                cred = credentials.Certificate('serviceAccountKey.jso.json')
                firebase_admin.initialize_app(cred)
                return firestore.client()
            
            else:
                st.error("❌ FIREBASE_SECRET tidak ditemukan di Dashboard Secrets.")
                return None
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
        
        # Ambil daftar file dari Google Drive
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
                # Simpan metadata ke Firestore
                manager.add_file_metadata(
                    name=item['name'], 
                    size=size_str, 
                    source="Google Drive", 
                    file_type="file" if size_raw else "folder", 
                    icon="🟢"
                )
        return True
    except Exception as e:
        st.error(f"Gagal sinkronisasi data: {e}")
        return False

# --- 5. FIRESTORE MANAGER ---
class FirestoreManager:
    def __init__(self, user_id):
        self.user_id = user_id
        # Path sesuai aturan: artifacts/{appId}/users/{userId}/{collectionName}
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
                # Menyuntikkan data ke JavaScript di index.html
                html = html.replace("files: [", f"files: {json.dumps(files)}, \n _old: [")
                html = html.replace('id="login-overlay"', 'id="login-overlay" style="display:none;"')
            return html
    return "<h1>index.html tidak ditemukan di repository.</h1>"

# --- 7. MAIN LOGIC (OAUTH HANDLER) ---
if "code" in st.query_params and not st.session_state.user:
    try:
        flow = get_google_auth_flow()
        flow.fetch_token(code=st.query_params["code"])
        creds = flow.credentials
        
        # Simpan sesi user sementara
        st.session_state.user = {
            "uid": creds.client_id[:15], 
            "name": "User Terverifikasi"
        }
        st.session_state.google_token = json.loads(creds.to_json())
        
        # Bersihkan URL dari parameter code
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Gagal memproses login: {e}")

# Render tampilan utama
components.html(load_ui(), height=850, scrolling=False)

# Sidebar Kontrol
with st.sidebar:
    st.title("☁️ OmniCloud")
    st.markdown("---")
    
    if not st.session_state.user:
        st.info("Silakan login untuk mengelola cloud Anda.")
        auth_url, _ = get_google_auth_flow().authorization_url(prompt='consent', access_type='offline')
        st.markdown(f'''
            <a href="{auth_url}" target="_self" 
            style="text-decoration:none; color:white; background:#4285F4; 
            padding:12px 20px; border-radius:8px; display:block; text-align:center; font-weight:bold;">
            🔑 Login dengan Google
            </a>
        ''', unsafe_allow_html=True)
    else:
        st.success(f"Masuk sebagai: {st.session_state.user['name']}")
        if st.button("🔄 Sinkronkan Google Drive"):
            with st.spinner("Mengambil metadata..."):
                if sync_google_drive_files(st.session_state.google_token):
                    st.toast("Metadata berhasil diperbarui!")
                    st.rerun()
        
        st.markdown("---")
        if st.button("🚪 Keluar (Logout)"):
            st.session_state.user = None
            st.session_state.google_token = None
            st.rerun()

    # Status Indikator Database
    if db:
        st.sidebar.caption("✅ Database Terhubung")
    else:
        st.sidebar.caption("❌ Database Terputus")
