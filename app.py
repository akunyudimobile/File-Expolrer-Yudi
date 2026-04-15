import streamlit as st
import streamlit.components.v1 as components

# Konfigurasi halaman
st.set_page_config(page_title="OmniCloud", layout="wide")

# Membaca file index.html yang sudah kita buat
with open("index.html", "r", encoding="utf-8") as f:
    html_code = f.read()

# Menampilkan UI di Streamlit
# Anda bisa mengirim data dari Python ke HTML menggunakan string replacement
components.html(html_code, height=800, scrolling=True)

# Di sini nanti Anda tambahkan logika API:
# - Integrasi Google OAuth
# - Integrasi API Mega.nz
# - Integrasi API Dropbox
