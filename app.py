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
# Masukkan Client ID dan Secret yang Anda dapatkan dari Google Cloud Console
CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets.get("GOOGLE_CLIENT_ID", "PASTE_HERE_CLIENT_ID"),
        "project_id": "file-explorer-nmsa-493404",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_secret": st.secrets.get("GOOGLE_CLIENT_SECRET", "PASTE_HERE_CLIENT_SECRET"),
        "redirect_uris": ["http://localhost:8501"]
    }
}

# Inisialisasi Firebase
# app_id digunakan untuk isolasi data di Firestore sesuai aturan path
app_id = "omnicloud-v1"

@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            # 1. Coba baca dari Streamlit Secrets (untuk deployment)
            if "FIREBASE_SECRET" in st.secrets:
                secret_dict = json.loads(st.secrets["FIREBASE_SECRET"])
                cred = credentials.Certificate(secret_dict)
            # 2. Cek file lokal (sesuai nama file di repo Anda)
            elif os.path.exists('serviceAccountKey.jso.json'):
                cred = credentials.Certificate('serviceAccountKey.jso.json')
            else:
                st.error("File 'serviceAccountKey.jso.json' tidak ditemukan!")
                return None
            
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"Firebase Initialization Error: {e}")
            return None
    return firestore.client()

db = init_firebase()

# --- 3. MANAJEMEN SESI ---
if 'user' not in st.session_state: 
    st.session_state.user = None
if 'google_token' not in st.session_state: 
    st.session_state.google_token = None

# --- 4. LOGIKA GOOGLE DRIVE API ---
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
    """Mengambil daftar file dari Google Drive dan menyimpannya ke Firestore."""
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_info(token)
        service = build('drive', 'v3', credentials=creds)
        
        # Ambil 20 file terbaru
        results = service.files().list(
            pageSize=20, 
            fields="files(id, name, size, mimeType)"
        ).execute()
        items = results.get('files', [])
        
        if db and st.session_state.user:
            manager = FirestoreManager(st.session_state.user['uid'])
            for item in items:
                # Format ukuran file
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
    """Mengelola operasi database Firestore dengan path yang aman."""
    def __init__(self, user_id):
        self.user_id = user_id
        # Path: /artifacts/{appId}/users/{userId}/files
        self.collection_path = f"artifacts/{app_id}/users/{self.user_id}/files"

    def get_user_files(self):
        """Membaca semua file milik user dari database."""
        if not db: return []
        try:
            docs = db.collection(self.collection_path).stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"Error fetching files: {e}")
            return []

    def add_file_metadata(self, name, size, source, file_type, icon):
        """Menambah metadata file baru ke database."""
        if not db: return
        file_id = f"file_{int(datetime.now().timestamp())}_{name[:10].replace(' ', '_')}"
        file_data = {
            "id": file_id,
            "name": name,
            "size": size,
            "source": source,
            "type": file_type,
            "icon": icon,
            "created_at": datetime.now().isoformat()
        }
        db.collection(self.collection_path).document(file_id).set(file_data)

# --- 6. RENDER UI ---
def load_ui():
    """Membaca index.html dan menyuntikkan data dinamis dari Python."""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
            
            # Jika user sudah login, kirim data file dari Firestore ke UI
            if st.session_state.user:
                manager = FirestoreManager(st.session_state.user['uid'])
                files = manager.get_user_files()
                
                # Menyuntikkan data ke variabel 'files' di JavaScript index.html
                html = html.replace("files: [", f"files: {json.dumps(files)}, \n _old: [")
                # Sembunyikan overlay login
                html = html.replace('id="login-overlay"', 'id="login-overlay" style="display:none;"')
            
            return html
    return "<h1>Error: File index.html tidak ditemukan.</h1>"

# --- 7. ALUR LOGIKA UTAMA (MAIN APP) ---

# Cek apakah ada parameter 'code' dari Google Redirect
query_params = st.query_params
if "code" in query_params and not st.session_state.user:
    try:
        flow = get_google_auth_flow()
        flow.fetch_token(code=query_params["code"])
        creds = flow.credentials
        
        # Set session user (menggunakan ID unik dari Google)
        st.session_state.user = {
            "uid": creds.client_id[:15], 
            "name": "User Google"
        }
        st.session_state.google_token = json.loads(creds.to_json())
        
        # Bersihkan URL dari parameter code
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Gagal memproses login: {e}")

# Tampilkan UI HTML di bagian utama
components.html(load_ui(), height=850, scrolling=False)

# Navigasi Sidebar
with st.sidebar:
    st.title("☁️ OmniCloud Control")
    st.markdown("---")
    
    if not st.session_state.user:
        st.info("Silakan login untuk mengakses file Anda.")
        if st.button("🔑 Login dengan Google"):
            flow = get_google_auth_flow()
            auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
            # Gunakan link karena streamlit button tidak bisa redirect langsung
            st.markdown(f'''
                <a href="{auth_url}" target="_self" 
                style="text-decoration:none; color:white; background:#4285F4; 
                padding:12px 20px; border-radius:8px; display:block; text-align:center; font-weight:bold;">
                Konfirmasi di Google
                </a>
            ''', unsafe_allow_html=True)
    else:
        st.success(f"Aktif: {st.session_state.user['name']}")
        
        if st.button("🔄 Sinkronkan Google Drive"):
            with st.spinner("Mengambil data file..."):
                if sync_google_drive_files(st.session_state.google_token):
                    st.toast("Metadata file berhasil diperbarui!")
                    st.rerun()
        
        st.markdown("---")
        if st.button("🚪 Keluar (Logout)"):
            st.session_state.user = None
            st.session_state.google_token = None
            st.rerun()

    # Status Koneksi
    st.sidebar.markdown("### Status Sistem")
    if db:
        st.sidebar.caption("✅ Database Firestore Terhubung")
    else:
        st.sidebar.caption("❌ Database Firestore Terputus")
