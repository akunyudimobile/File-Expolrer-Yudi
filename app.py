import streamlit as st
import streamlit.components.v1 as components
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="OmniCloud - Unified Storage Manager",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. INISIALISASI FIREBASE & FIRESTORE ---
# ID Aplikasi untuk pengelompokan data di Firestore
app_id = "omnicloud-v1"

@st.cache_resource
def init_firebase():
    """Inisialisasi koneksi ke Firebase (Mendukung lokal & Streamlit Cloud)."""
    if not firebase_admin._apps:
        try:
            # Skenario 1: Menjalankan di Streamlit Cloud (Menggunakan Secrets)
            if "FIREBASE_SECRET" in st.secrets:
                secret_dict = json.loads(st.secrets["FIREBASE_SECRET"])
                cred = credentials.Certificate(secret_dict)
            # Skenario 2: Menjalankan secara Lokal (Menggunakan file JSON)
            elif os.path.exists('serviceAccountKey.json'):
                cred = credentials.Certificate('serviceAccountKey.json')
            else:
                st.error("Kunci Firebase tidak ditemukan. Pastikan serviceAccountKey.json ada atau Secrets sudah dikonfigurasi.")
                return None
                
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"Gagal memuat Firebase: {e}")
            return None
    return firestore.client()

db = init_firebase()

# --- 3. MANAJEMEN SESI (STATE) ---
if 'user' not in st.session_state:
    st.session_state.user = None

# --- 4. LOGIKA DATA FIRESTORE ---
class FirestoreManager:
    def __init__(self, user_id):
        self.user_id = user_id
        # Jalur koleksi: /artifacts/{appId}/users/{userId}/files
        self.base_path = f"artifacts/{app_id}/users/{self.user_id}"

    def get_user_files(self):
        """Mengambil metadata file dari Firestore."""
        if not db: return []
        try:
            files_ref = db.collection(f"{self.base_path}/files")
            docs = files_ref.stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            st.error(f"Error Firestore: {e}")
            return []

    def add_file_metadata(self, name, size, source, file_type, icon):
        """Menyimpan data file baru ke Firestore."""
        if not db: return
        try:
            file_id = f"file_{int(datetime.now().timestamp())}"
            file_data = {
                "id": file_id,
                "name": name,
                "size": size,
                "source": source,
                "type": file_type,
                "icon": icon,
                "created_at": datetime.now().isoformat()
            }
            db.collection(f"{self.base_path}/files").document(file_id).set(file_data)
            return True
        except Exception as e:
            st.error(f"Gagal simpan ke Firestore: {e}")
            return False

# --- 5. INTEGRASI ANTARMUKA (UI) ---
def load_ui():
    """Membaca index.html dan menyuntikkan data dari Firestore."""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
            
            # Jika user sudah "login", ambil data aslinya
            if st.session_state.user:
                manager = FirestoreManager(st.session_state.user['uid'])
                files = manager.get_user_files()
                
                # Mengganti data dummy di index.html dengan data Firestore
                files_json = json.dumps(files)
                html = html.replace(
                    "files: [", 
                    f"files: {files_json}, // Disinkronkan dari Firestore\n            _old_files: ["
                )
                
                # Menyembunyikan layar login jika sesi aktif
                html = html.replace(
                    'id="login-overlay"', 
                    'id="login-overlay" style="display:none;"'
                )
            return html
    return "<h3>Sistem Error: File index.html tidak ditemukan.</h3>"

# Render HTML ke dalam aplikasi Streamlit
ui_content = load_ui()
components.html(ui_content, height=900, scrolling=False)

# --- 6. PANEL KONTROL ADMIN (SIDEBAR) ---
with st.sidebar:
    st.title("🛡️ OmniCloud Dev Mode")
    
    if not st.session_state.user:
        st.info("Gunakan tombol di bawah untuk simulasi login.")
        if st.button("Masuk sebagai Test User"):
            st.session_state.user = {"uid": "user_demo_001", "name": "Yudi User"}
            st.rerun()
    else:
        st.success(f"Aktif: {st.session_state.user['name']}")
        
        # Opsi Tambah File Cepat untuk Testing Firestore
        st.divider()
        st.subheader("Test Firestore")
        f_name = st.text_input("Nama File Baru")
        f_source = st.selectbox("Cloud", ["Google Drive", "Mega.nz", "Dropbox", "TeraBox"])
        
        if st.button("Simpan ke Cloud"):
            icons = {"Google Drive": "🟢", "Mega.nz": "🔴", "Dropbox": "🔵", "TeraBox": "🟣"}
            manager = FirestoreManager(st.session_state.user['uid'])
            if manager.add_file_metadata(f_name, "12 MB", f_source, "file", icons[f_source]):
                st.toast("Metadata berhasil disimpan ke Firestore!")
                st.rerun()

        if st.button("Logout"):
            st.session_state.user = None
            st.rerun()

    st.divider()
    if db:
        st.success("Firestore: Connected")
    else:
        st.error("Firestore: Disconnected")
