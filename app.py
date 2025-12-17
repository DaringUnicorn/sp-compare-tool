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

# --- CSS Stilleri (Genel Arayüz) ---
st.markdown("""
<style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; transition: all 0.3s ease; }
    .stTextInput>div>div>input { border-radius: 5px; }
    
    /* Breadcrumb Stili */
    .breadcrumb {
        background-color: #f8f9fa;
        padding: 12px 20px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-family: 'Segoe UI', sans-serif;
        font-size: 15px;
        color: #31333F;
        border: 1px solid #e9ecef;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .breadcrumb span { display: inline-flex; align-items: center; }
    .breadcrumb .separator { margin: 0 12px; color: #adb5bd; font-weight: bold; }
    .breadcrumb .current { font-weight: 600; color: #0d6efd; }
</style>
""", unsafe_allow_html=True) 


# --- 1. Güvenlik ve Giriş Fonksiyonları ---
def check_login(username, password):
    # Hardcoded Kullanıcılar
    VALID_USERS = {"admin": "Banka123!", "stajyer": "1234", "": ""}

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
    candidate_drivers = [
        "ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server",
        "ODBC Driver 13 for SQL Server", "SQL Server Native Client 11.0", 
        "SQL Server Native Client 10.0", "SQL Server"
    ]
    last_error = None
    
    for driver_name in candidate_drivers:
        try:
            conn_str_parts = [
                f"DRIVER={{{driver_name}}}",
                f"SERVER={server}",
                "TrustServerCertificate=yes"
            ]
            if database: conn_str_parts.append(f"DATABASE={database}")

            if not username or not password:
                conn_str_parts.append("Trusted_Connection=yes")
            else:
                conn_str_parts.append(f"UID={username}")
                conn_str_parts.append(f"PWD={password}")

            conn = pyodbc.connect(";".join(conn_str_parts), timeout=10)
            return conn
        except Exception as e:
            last_error = e
            continue
    
    print(f"KRİTİK HATA: Hiçbir sürücü ile bağlanılamadı. Hata: {last_error}")
    return None

def get_databases(server, username, password):
    conn = get_connection(server, "master", username, password)
    if not conn: return []
    try:
        df = pd.read_sql("SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name", conn)
        conn.close()
        return df['name'].to_list()
    except:
        return []

@st.cache_data(ttl=300)
def get_all_sps_secure(_conn):
    query = """
    SELECT SCHEMA_NAME(schema_id) + '.' + name + ' | ' + FORMAT(modify_date, 'yyyy-MM-dd HH:mm') as DisplayText,
           SCHEMA_NAME(schema_id) as SchemaName, name as SpName 
    FROM sys.procedures ORDER BY DisplayText
    """
    try:
        return pd.read_sql(query, _conn)
    except:
        return pd.DataFrame()

def get_sp_content_secure(conn, schema, sp_name):
    query= """
    SELECT m.definition FROM sys.sql_modules m
    INNER JOIN sys.objects o ON m.object_id = o.object_id
    INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
    WHERE s.name = ? AND o.name = ?
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, (schema, sp_name))
        row = cursor.fetchone()
        return row[0] if row else ""
    except:
        return ""

# --- GÜZELLEŞTİRİLMİŞ TABLO FONKSİYONU ---
def highlight_diff(text1, text2, width=130):
    if not text1: text1 = ""
    if not text2: text2 = ""

    d = difflib.HtmlDiff(wrapcolumn=width, tabsize=4)
    # numlines=3 yerine 1000 yaparak context'i artırıyoruz ki kopukluk olmasın
    html_content = d.make_file(text1.splitlines(), text2.splitlines(), context=True, numlines=5)

    # MODERN GITHUB-LIKE CSS
    custom_css = """
        <style>
            /* Tabloyu ve Fontları Güzelleştir */
            table.diff {
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 13px;
                width: 100%;
                border-collapse: collapse;
                border: 1px solid #d0d7de;
                border-radius: 6px;
                overflow: hidden;
                table-layout: fixed; /* Sütun genişliklerini sabitler, kaymayı önler */
            }
            
            /* Başlık (Dosya isimleri vb.) */
            table.diff thead {
                display: none; /* Genelde gereksiz yer kaplar, gizledik */
            }

            /* Satır Numaraları ve Hücreler */
            table.diff td {
                padding: 4px 8px;
                vertical-align: top;
                word-wrap: break-word; /* Uzun kodların taşmasını önler */
                white-space: pre-wrap; /* Kod formatını korur ama alt satıra indirir */
                line-height: 1.5;
            }

            /* Satır Numarası Sütunu (Gri Alan) */
            .diff_header {
                background-color: #f6f8fa;
                color: #6e7781;
                text-align: right;
                width: 40px; /* Sabit genişlik */
                border-right: 1px solid #d0d7de;
                user-select: none;
            }

            /* --- RENKLENDİRME (GitHub Stili) --- */
            
            /* Değişiklik Olmayan Kodlar */
            .diff_next { background-color: #ffffff; color: #24292f; }
            
            /* Eklenen Satırlar (Yeşil) */
            .diff_add {
                background-color: #e6ffec; /* Açık Yeşil */
                color: #24292f;
            }
            .diff_add span {
                background-color: #abf2bc; /* Koyu Yeşil Vurgu */
                font-weight: 600;
            }

            /* Silinen Satırlar (Kırmızı) */
            .diff_sub {
                background-color: #ffebe9; /* Açık Kırmızı */
                color: #24292f;
            }
            .diff_sub span {
                background-color: #ff818266; /* Koyu Kırmızı Vurgu */
                text-decoration: line-through;
            }

            /* Değişen Satırlar (Sarı) */
            .diff_chg {
                background-color: #fff8c5; /* Açık Sarı */
            }
            .diff_chg span {
                background-color: #f2cc6088; /* Koyu Sarı Vurgu */
                font-weight: 600;
            }
        </style>
    """
    
    # HTML İçeriğini Temizle (Gereksiz body/head taglerini atıyoruz, sadece tablo kalsın)
    # Bu işlem Streamlit içinde daha temiz görünmesini sağlar
    return custom_css + html_content

def render_breadcrumb(server, database, sp_name):
    st.markdown(f"""
        <div class="breadcrumb">
            <span>{server}</span>
            <span class="separator">/</span>
            <span>{database}</span>
            <span class="separator">/</span>
            <span class="current">{sp_name}</span>
        </div>
    """, unsafe_allow_html=True)


# --- 3. Ana Uygulama Mantığı ---
def main_app():
    # Header
    col_h1, col_h2 = st.columns([9, 1])
    with col_h1:
        st.title("SP Karşılaştırma Aracı")
        st.caption(f"Kullanıcı: {st.session_state.get('user', 'Bilinmiyor')}")
    with col_h2:
        if st.button("Çıkış Yap"): logout()
    st.divider()

    # --- SIDEBAR ---
    with st.sidebar:
        st.header("Bağlantı Ayarları")

        # Kaynak
        with st.expander("1. Kaynak (Source)", expanded=True):
            src_ip = st.text_input("Source IP", key="src_ip")
            src_user = st.text_input("Source User", key="src_user")
            src_pass = st.text_input("Source Pass", type="password", key="src_pass")
            if st.button("DB Getir (Source)", key="btn_src_fetch"):
                with st.spinner(".."):
                    dbs = get_databases(src_ip, src_user, src_pass)
                    if dbs: st.session_state["src_db_list"] = dbs
            src_dbs = st.session_state.get("src_db_list", [])
            sel_src_db = st.selectbox("Source DB", src_dbs, key="sel_src_db") if src_dbs else None

        # Hedef
        with st.expander("2. Hedef (Target)", expanded=False):
            tgt_ip = st.text_input("Target IP", key="tgt_ip")
            tgt_user = st.text_input("Target User", key="tgt_user")
            tgt_pass = st.text_input("Target Pass", type="password", key="tgt_pass")
            if st.button("DB Getir (Target)", key="btn_tgt_fetch"):
                with st.spinner(".."):
                    dbs = get_databases(tgt_ip, tgt_user, tgt_pass)
                    if dbs: st.session_state["tgt_db_list"] = dbs
            tgt_dbs = st.session_state.get("tgt_db_list", [])
            sel_tgt_db = st.selectbox("Target DB", tgt_dbs, key="sel_tgt_db") if tgt_dbs else None
        
        st.markdown("---")
        wrap_width = st.slider("Kod Genişliği (Wrap)", 50, 300, 100, help="Satırlar çok uzunsa buradan ayarlayın")

    # --- ORTA ALAN ---
    if sel_src_db and sel_tgt_db:
        col1, col2 = st.columns(2)

        # SOL PANEL
        with col1:
            st.info(f"Kaynak: **{sel_src_db}**")
            conn_src = get_connection(src_ip, sel_src_db, src_user, src_pass)
            sel_src_display = None
            if conn_src:
                df_src = get_all_sps_secure(conn_src)
                filter_src = st.text_input("🔍 Kaynak SP Ara...", key="filter_src")
                if filter_src and not df_src.empty:
                    df_src = df_src[df_src['DisplayText'].str.contains(filter_src, case=False)]
                
                sel_src_display = st.selectbox("SP Seçiniz", df_src["DisplayText"], key="final_src_sel")
                if sel_src_display:
                    row_src = df_src[df_src["DisplayText"] == sel_src_display].iloc[0]
                    src_schema, src_name = row_src['SchemaName'], row_src['SpName']
                    render_breadcrumb(src_ip, sel_src_db, src_name)
            else: st.error("Bağlantı Yok")

        # SAĞ PANEL
        with col2:
            st.info(f"Hedef: **{sel_tgt_db}**")
            conn_tgt = get_connection(tgt_ip, sel_tgt_db, tgt_user, tgt_pass)
            sel_tgt_display = None
            if conn_tgt:
                df_tgt = get_all_sps_secure(conn_tgt)
                filter_tgt = st.text_input("🔍 Hedef SP Ara...", key="filter_tgt")
                if filter_tgt and not df_tgt.empty:
                    df_tgt = df_tgt[df_tgt['DisplayText'].str.contains(filter_tgt, case=False)]
                
                sel_tgt_display = st.selectbox("SP Seçiniz", df_tgt['DisplayText'], key="final_tgt_sel")
                if sel_tgt_display:
                    row_tgt = df_tgt[df_tgt['DisplayText'] == sel_tgt_display].iloc[0]
                    tgt_schema, tgt_name = row_tgt['SchemaName'], row_tgt['SpName']
                    render_breadcrumb(tgt_ip, sel_tgt_db, tgt_name)
            else: st.error("Bağlantı Yok")

        # --- KARŞILAŞTIRMA ---
        st.divider()
        if st.button("KODLARI KARŞILAŞTIR (COMPARE)", type="primary", use_container_width=True):
            if sel_src_display and sel_tgt_display:
                with st.spinner("Kodlar getiriliyor ve analiz ediliyor..."):
                    code_src = get_sp_content_secure(conn_src, src_schema, src_name)
                    code_tgt = get_sp_content_secure(conn_tgt, tgt_schema, tgt_name)

                    if not code_src and not code_tgt:
                        st.warning("Kod çekilemedi veya SP boş.")
                    else:
                        # Görsel İyileştirme: Legend (Açıklama) Ekleyelim
                        st.markdown("""
                        <div style="display: flex; gap: 20px; margin-bottom: 10px; font-size: 14px;">
                            <span style="background:#e6ffec; padding: 2px 8px; border-radius:4px; border:1px solid #ccc;">Eklenen (Sağda var)</span>
                            <span style="background:#ffebe9; padding: 2px 8px; border-radius:4px; border:1px solid #ccc;">Silinen (Solda var)</span>
                            <span style="background:#fff8c5; padding: 2px 8px; border-radius:4px; border:1px solid #ccc;">Değişen</span>
                        </div>
                        """, unsafe_allow_html=True)

                        html_diff = highlight_diff(code_src, code_tgt, width=wrap_width)
                        
                        # height=800 yaptık ve scrolling=True dedik ki büyük SP'lerde sayfa patlamasın
                        components.html(html_diff, height=800, scrolling=True)
            else:
                st.warning("Lütfen iki taraftan da seçim yapınız.")
    else:
        st.info("Başlamak için lütfen sol menüden veritabanlarını seçin.")

# --- Login Gate ---
if not st.session_state['authenticated']:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h2 style='text-align: center;'>Güvenli Giriş</h2>", unsafe_allow_html=True)
        u = st.text_input("Kullanıcı Adı")
        p = st.text_input("Şifre", type="password")
        if st.button("Giriş Yap", type="primary"): check_login(u, p)
        st.caption("Varsayılan: admin / Banka123!")
else:
    main_app()