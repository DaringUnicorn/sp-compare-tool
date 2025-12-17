import streamlit as st
import pandas as pd
import pyodbc
import difflib
import streamlit.components.v1 as components
import time
import os, sys

# --- Sayfa ve Güvenlik Ayarları ---
st.set_page_config(layout="wide", page_title="SQL SP Compare Tool v2.0")

# Oturum Durumu Kontrolü (Session State)
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

# --- CSS Stilleri ---
st.markdown("""
<style>
    /* Genel font iyileştirmeleri */
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }

    /* Butonları modernleştirir */
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }

    /* Input alanlarını netleştir */
    .stTextInput>div>div>input {
        border-radius: 5px;
    }
    
    /* Breadcrumb Stili */
    .breadcrumb {
        background-color: #f0f2f6;
        padding: 10px 15px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-family: 'Segoe UI', sans-serif;
        font-size: 15px;
        color: #31333F;
        border: 1px solid #e0e0e0;
    }
    .breadcrumb span {
        display: inline-flex;
        align-items: center;
    }
    .breadcrumb .separator {
        margin: 0 10px;
        color: #ff4b4b; 
        font-weight: bold;
    }
    .breadcrumb .current {
        font-weight: bold;
        color: #000;
        text-decoration: underline;
    }
</style>
""", unsafe_allow_html=True) 


# --- 1. Güvenlik ve Giriş Fonksiyonları ---
def check_login(username, password):
    """
    Basit kimlik doğrulama.
    Güvenlik Notu: Prod ortamında bu şifreler Vault'tan veya Environment Variable'dan gelmeli.
    """
    # Şimdilik Hardcoded (Eğitim Amaçlı)
    VALID_USERS = {
        "admin": "Banka123!",
        "stajyer": "1234",
        "": ""
    }

    if username in VALID_USERS and VALID_USERS[username] == password:
        st.session_state["authenticated"] = True
        st.session_state["user"] = username
        st.success("Giriş Başarılı! Yönlendiriliyorsunuz...")
        time.sleep(1)
        st.rerun()
    else:
        st.error("Hatalı Kullanıcı Adı veya Şifre")

def logout():
    st.session_state["authenticated"] = False
    st.rerun()

# --- 2. Veritabanı Bağlantı Fonksiyonları ---
def get_connection(server, database, username, password):
    """
    SQL Server Bağlantı Oluşturucu
    Sistemdeki mevcut sürücüleri otomatik tarar ve uygun olanı seçer.
    """
    # Öncelik sırasına göre denenecek sürücüler
    candidate_drivers = [
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server Native Client 10.0",
        "SQL Server" # En eski ve en garanti olan
    ]

    last_error = None
    
    # Her bir sürücüyü tek tek dene
    for driver_name in candidate_drivers:
        try:
            conn_str_parts = [
                f"DRIVER={{{driver_name}}}",
                f"SERVER={server}",
                "TrustServerCertificate=yes"
            ]

            if database:
                conn_str_parts.append(f"DATABASE={database}")

            # Eğer kullanıcı adı veya şifre boşsa -> Windows Auth kullan
            if not username or not password:
                conn_str_parts.append("Trusted_Connection=yes")
            else:
                conn_str_parts.append(f"UID={username}")
                conn_str_parts.append(f"PWD={password}")

            conn_str = ";".join(conn_str_parts)
            conn = pyodbc.connect(conn_str, timeout=10)
            return conn

        except Exception as e:
            last_error = e
            continue
    
    print(f"KRİTİK HATA: Hiçbir sürücü ile bağlanılamadı. Son hata: {last_error}")
    return None
    

def get_databases(server, username, password):
    """
    Sunucudaki veritabanlarını listeler (master DB üzerinden).
    """
    conn = get_connection(server, "master", username, password)

    if not conn:
        return []

    query = "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name" 

    try:
        df = pd.read_sql(query, conn)
        conn.close()
        return df['name'].to_list()
    except Exception as e:
        st.error("Veritabanı listesi çekilemedi.")
        return []


@st.cache_data(ttl=300)
def get_all_sps_secure(_conn):
    """
    SP Listesini çeker. SQL Injection riski yok.
    """
    query = """
    SELECT
        SCHEMA_NAME(schema_id) + '.' + name + ' | ' + FORMAT(modify_date, 'yyyy-MM-dd HH:mm') as DisplayText,
        SCHEMA_NAME(schema_id) as SchemaName,
        name as SpName
    FROM sys.procedures
    ORDER BY DisplayText
    """
    try:
        df = pd.read_sql(query, _conn)
        return df
    except Exception as e:
        return pd.DataFrame()

def get_sp_content_secure(conn, schema, sp_name):
    """
    Parametreli sorgu ile güvenli kod okuma.
    """
    query= """
    SELECT m.definition
    FROM sys.sql_modules m
    INNER JOIN sys.objects o ON m.object_id = o.object_id
    INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
    WHERE s.name = ? AND o.name = ?
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, (schema, sp_name))
        row = cursor.fetchone()
        return row[0] if row else ""
    except Exception as e:
        st.error("Kod içeriği alınırken hata oluştu.")
        return ""

def highlight_diff(text1, text2, width=130):
    """
    İki metin arasındaki farkı HTML formatında boyar.
    """
    if not text1: text1 = ""
    if not text2: text2 = ""

    d = difflib.HtmlDiff(wrapcolumn=width)
    html_content = d.make_file(text1.splitlines(), text2.splitlines(), context=False, numlines=3)

    custom_css = """
        <style>
            table.diff {
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 13px;
                width: 100%;
                border-collapse: collapse;
                border: 1px solid #ddd;
                table-layout: fixed;
            }
            table.diff td {
                padding: 2px 5px;
                vertical-align: top;
                word-wrap: break-word;
            }
            .diff_header {
                background-color: #f7f7f7;
                color: #999;
                text-align: right;
                width: 30px;
            }
            .diff_add { background-color: #e6ffec; color: #1a1a1a; }
            .diff_add span { background-color: #acf2bd; font-weight: bold; }
            .diff_sub { background-color: #ffebe9; color: #1a1a1a; }
            .diff_sub span { background-color: #fdb8c0; text-decoration: line-through; }
            .diff_chg { background-color: #fffbdd; color: #1a1a1a }
            .diff_chg span { background-color: #fceea6; font-weight: bold; }        
        </style>
    """
    return custom_css + html_content

def render_breadcrumb(server, database, sp_name):
    """
    Ekranın üstüne Server > DB > SP hiyerarşisini çizer.
    """
    st.markdown(f"""
        <div class="breadcrumb">
            <span>🖥️ {server}</span>
            <span class="separator">➜</span>
            <span>🗄️ {database}</span>
            <span class="separator">➜</span>
            <span class="current">📜 {sp_name}</span>
        </div>
    """, unsafe_allow_html=True)


# --- 3. Ana Uygulama Mantığı ---
def main_app():
    # --- Üst Header ---
    col_h1, col_h2 = st.columns([9, 1])
    
    with col_h1:
        st.title("Banka SP Karşılaştırma Aracı")
        st.caption(f"Kullanıcı: {st.session_state.get('user', 'Bilinmiyor')}")
        
    with col_h2:
        if st.button("Çıkış Yap"):
            logout()

    st.divider()

    # --- SIDEBAR (Bağlantı Ayarları) ---
    with st.sidebar:
        st.header("Bağlantı Ayarları")

        # --- Kaynak (Source) ---
        with st.expander("1. Kaynak Sunucu (Source)", expanded=True):
            src_ip = st.text_input("Source IP", key="src_ip")
            src_user = st.text_input("Source User", key="src_user")
            src_pass = st.text_input("Source Pass", type="password", key="src_pass")

            # DB Listele
            if st.button("Veritabanlarını Getir (Source)", key="btn_src_fetch"):
                with st.spinner("Bağlanılıyor..."):
                    dbs = get_databases(src_ip, src_user, src_pass)
                    if dbs:
                        st.session_state["src_db_list"] = dbs
                        st.success("Bağlandı")
                    else:
                        st.error("Bağlanılamadı!")
                
            src_dbs = st.session_state.get("src_db_list", [])
            sel_src_db = st.selectbox("Source DB Seç", src_dbs, key="sel_src_db") if src_dbs else None


        # --- Hedef (Target) ---
        with st.expander("2. Hedef Sunucu (Target)", expanded=False):
            tgt_ip = st.text_input("Target IP", key="tgt_ip")
            tgt_user = st.text_input("Target User", key="tgt_user")
            tgt_pass = st.text_input("Target Pass", type="password", key="tgt_pass")

            # DB Listele Butonu
            if st.button("Veritabanlarını Getir (Target)", key="btn_tgt_fetch"):
                with st.spinner("Bağlanılıyor..."):
                    dbs = get_databases(tgt_ip, tgt_user, tgt_pass)
                    if dbs:
                        st.session_state["tgt_db_list"] = dbs
                        st.success("Bağlandı")
                    else:
                        st.error("Bağlanılamadı!")

            # DB Dropdown
            tgt_dbs = st.session_state.get("tgt_db_list", [])
            sel_tgt_db = st.selectbox("Target DB Seç", tgt_dbs, key="sel_tgt_db") if tgt_dbs else None

        # Docker Uyarısı
        st.info("Docker kullanıyorsanız IP yerine 'host.docker.internal' yazın.")
        st.markdown("---")
        
        # Görünüm Ayarları
        wrap_width = st.slider("Satır Genişliği (Karakter)", 50, 300, 130)

    # --- Orta Alan (SP Seçimi ve Compare) ---
    # Sadece iki tarafta da DB seçildiyse göster
    if sel_src_db and sel_tgt_db:
        col1, col2 = st.columns(2)

        # --- Sol Taraf SP Listesi ---
        with col1:
            st.info(f"Kaynak: **{sel_src_db}**")
            conn_src = get_connection(src_ip, sel_src_db, src_user, src_pass)
            
            sel_src_display = None
            if conn_src:
                df_src = get_all_sps_secure(conn_src)

                # -- YENİ ÖZELLİK: FİLTRELEME --
                filter_src = st.text_input("🔍 Kaynak SP Ara...", key="filter_src")
                if filter_src and not df_src.empty:
                    df_src = df_src[df_src['DisplayText'].str.contains(filter_src, case=False)]
                
                # Kullanıcıya listeden seçtir
                sel_src_display = st.selectbox("Kaynak SP Seçiniz", df_src["DisplayText"], key="final_src_sel")

                # Seçilen text'ten Schema ve Name ayıkla
                if sel_src_display:
                    row_src = df_src[df_src["DisplayText"] == sel_src_display].iloc[0]
                    src_schema = row_src['SchemaName']
                    src_name = row_src['SpName']
                    
                    # Breadcrumb
                    render_breadcrumb(src_ip, sel_src_db, src_name)
            else:
                st.error("Kaynak Bağlantısı Koptu!")

        # --- Sağ Taraf SP Listesi ---
        with col2:
            st.info(f"Hedef: **{sel_tgt_db}**")
            conn_tgt = get_connection(tgt_ip, sel_tgt_db, tgt_user, tgt_pass)
            
            sel_tgt_display = None
            if conn_tgt:
                df_tgt = get_all_sps_secure(conn_tgt)
                
                # -- YENİ ÖZELLİK: FİLTRELEME --
                filter_tgt = st.text_input("🔍 Hedef SP Ara...", key="filter_tgt")
                if filter_tgt and not df_tgt.empty:
                    df_tgt = df_tgt[df_tgt['DisplayText'].str.contains(filter_tgt, case=False)]

                sel_tgt_display = st.selectbox("Hedef SP Seçiniz", df_tgt['DisplayText'], key="final_tgt_sel")

                if sel_tgt_display:
                    row_tgt = df_tgt[df_tgt['DisplayText'] == sel_tgt_display].iloc[0]
                    tgt_schema = row_tgt['SchemaName']
                    tgt_name = row_tgt['SpName']
                    
                    # Breadcrumb 
                    render_breadcrumb(tgt_ip, sel_tgt_db, tgt_name)
            else:
                st.error("Hedef Bağlantısı Koptu!")

        # --- Karşılaştırma Butonu ---
        st.divider()
        if st.button("Karşılaştırmayı Başlat", type="primary", use_container_width=True):

            if sel_src_display and sel_tgt_display:
                with st.spinner("Kodlar Analiz Ediliyor..."):
                    code_src = get_sp_content_secure(conn_src, src_schema, src_name)
                    code_tgt = get_sp_content_secure(conn_tgt, tgt_schema, tgt_name)

                    if not code_src and not code_tgt:
                        st.warning("İki taraftan da kod çekilemedi. İzinleri kontrol edin")
                    else:
                        # Diff Al ve Göster
                        html_diff = highlight_diff(code_src, code_tgt, width=wrap_width)
                        st.markdown("### Karşılaştırma Raporu")
                        components.html(html_diff, height=1000, scrolling=True)
            else:
                st.warning("Lütfen her iki taraftan da SP seçtiğinizden emin olun.")

    else:
        # DB seçilmediyse boş ekrana mesaj
        st.info("👈 Lütfen sol menüden Kaynak ve Hedef veritabanlarını seçerek başlayın.")

# --- 4. Giriş Ekranı (Login Gate) ---
if not st.session_state['authenticated']:
    col_spacer1, col_login, col_spacer2 = st.columns([1, 2, 1])
    with col_login:
        st.markdown("<h2 style='text-align: center;'>Güvenli Giriş ;)</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>Yetkili Personel Girişi</p>", unsafe_allow_html=True)

        user_input = st.text_input("Kullanıcı Adı", placeholder="Kullanıcı adınız")
        pass_input = st.text_input("Şifre", type="password", placeholder="Şifreniz")

        if st.button("Giriş Yap", type="primary", use_container_width=True):
            check_login(user_input, pass_input)
        st.caption("Not: Varsayılan Admin -> admin / Banka123!")
else: 
    # Giriş yapıldıysa ana uygulamayı çalıştır
    main_app()