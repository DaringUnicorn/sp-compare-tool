import streamlit as st
import pandas as pd
import pyodbc
import difflib
import streamlit.components.v1 as components
import time

# --- Sayfa ve Güvenlik Ayarları ---
st.set_page_config(layout="wide", page_title="SQL SP Compare Tool v3.0")

# Oturum Durumu Kontrolü
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

# --- CSS İLE GÜZELLEŞTİRME (Modern Arayüz) ---
st.markdown("""
<style>
    /* Genel font iyileştirmeleri */
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    /* Butonları modernleştir */
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
</style>
""", unsafe_allow_html=True)


# --- 1. GÜVENLİK VE GİRİŞ FONKSİYONLARI ---

def check_login(username, password):
    """ Basit kimlik doğrulama. """
    VALID_USERS = {
        "admin": "Banka123!",
        "stajyer": "1234"
    }

    if username in VALID_USERS and VALID_USERS[username] == password:
        st.session_state["authenticated"] = True
        st.session_state["user"] = username
        st.success("Giriş Başarılı! Yönlendiriliyorsunuz...")
        time.sleep(0.5)
        st.rerun()
    else:
        st.error("Hatalı Kullanıcı Adı veya Şifre")

def logout():
    st.session_state["authenticated"] = False
    st.rerun()


# --- 2. VERİTABANI BAĞLANTI FONKSİYONLARI ---

def get_connection(server, database, username, password):
    """
    SQL Server Bağlantı Oluşturucu (Akıllı Sürücü Seçimi).
    """
    available_drivers = pyodbc.drivers()
    
    # Mac ve Windows için ortak sürücü listesi
    candidate_drivers = [
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server" # Windows Legacy
    ]

    last_error = None
    
    for driver_name in candidate_drivers:
        # Sistemde olmayan sürücüyü deneme
        if driver_name not in available_drivers:
            continue

        try:
            conn_str_parts = [
                f"DRIVER={{{driver_name}}}",
                f"SERVER={server}",
                "TrustServerCertificate=yes"
            ]

            if database:
                conn_str_parts.append(f"DATABASE={database}")

            if not username or not password:
                conn_str_parts.append("Trusted_Connection=yes")
            else:
                conn_str_parts.append(f"UID={username}")
                conn_str_parts.append(f"PWD={password}")

            conn_str = ";".join(conn_str_parts)
            
            return pyodbc.connect(conn_str, timeout=5)

        except Exception as e:
            last_error = e
            continue
    
    # Hata durumunda loga yaz
    print(f"KRİTİK HATA: Bağlantı kurulamadı. Son hata: {last_error}")
    return None
    

def get_databases(server, username, password):
    conn = get_connection(server, "master", username, password)
    if not conn: return []

    query = "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name" 

    try:
        df = pd.read_sql(query, conn)
        conn.close()
        return df['name'].tolist()
    except Exception as e:
        st.error("Veritabanı listesi çekilemedi.")
        return []


@st.cache_data(ttl=300)
def get_all_sps_secure(_conn):
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
    except:
        return pd.DataFrame()


def get_sp_content_secure(conn, schema, sp_name):
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


# --- 3. BEYOND COMPARE STİLİ HIGHLIGHT FONKSİYONU ---

def highlight_diff(text1, text2, width=100):
    """
    Beyond Compare benzeri, dinamik genişlikli fark boyama.
    """
    if not text1: text1 = ""
    if not text2: text2 = ""

    d = difflib.HtmlDiff(wrapcolumn=width) 

    # Tabloyu oluştur
    html_content = d.make_file(text1.splitlines(), text2.splitlines(), context=False, numlines=3)

    # CSS ENJEKSİYONU
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
            user-select: none;
        }

        /* YEŞİL ALANLAR */
        .diff_add { background-color: #e6ffec; color: #1a1a1a; }
        .diff_add span { background-color: #acf2bd; font-weight: bold; }

        /* KIRMIZI ALANLAR */
        .diff_sub { background-color: #ffebe9; color: #1a1a1a; }
        .diff_sub span { background-color: #fdb8c0; text-decoration: line-through; }

        /* SARI ALANLAR */
        .diff_chg { background-color: #fffbdd; color: #1a1a1a; }
        .diff_chg span { background-color: #fceea6; font-weight: bold; }
        
        .diff_next { background-color: #f0f0f0; }
    </style>
    """
    
    return custom_css + html_content


# --- 4. ANA UYGULAMA MANTIĞI ---

def main_app():
    col_h1, col_h2 = st.columns([9, 1])
    
    with col_h1:
        st.title("🛡️ Banka SP Karşılaştırma Aracı")
        st.caption(f"Aktif Kullanıcı: {st.session_state.get('user', 'Bilinmiyor')}")
        
    with col_h2:
        if st.button("Çıkış Yap"):
            logout()

    st.divider()

    # --- SIDEBAR ---
    with st.sidebar:
        st.header("⚙️ Bağlantı Paneli")

        # --- Kaynak ---
        with st.expander("1. Kaynak (Prod/Source)", expanded=True):
            src_ip = st.text_input("Source IP", value="localhost", key="src_ip")
            src_user = st.text_input("Source User", key="src_user")
            src_pass = st.text_input("Source Pass", type="password", key="src_pass")

            if st.button("DB Getir (Source)", key="btn_src"):
                with st.spinner("Bağlanılıyor..."):
                    dbs = get_databases(src_ip, src_user, src_pass)
                    if dbs:
                        st.session_state["src_db_list"] = dbs
                        st.success("✅ Bağlandı")
                    else:
                        st.error("❌ Hata")
                
            src_dbs = st.session_state.get("src_db_list", [])
            sel_src_db = st.selectbox("DB Seç", src_dbs, key="sel_src_db") if src_dbs else None

        # --- Hedef ---
        with st.expander("2. Hedef (Test/Dev)", expanded=False):
            tgt_ip = st.text_input("Target IP", value="localhost", key="tgt_ip")
            tgt_user = st.text_input("Target User", key="tgt_user")
            tgt_pass = st.text_input("Target Pass", type="password", key="tgt_pass")

            if st.button("DB Getir (Target)", key="btn_tgt"):
                with st.spinner("Bağlanılıyor..."):
                    dbs = get_databases(tgt_ip, tgt_user, tgt_pass)
                    if dbs:
                        st.session_state["tgt_db_list"] = dbs
                        st.success("✅ Bağlandı")
                    else:
                        st.error("❌ Hata")

            tgt_dbs = st.session_state.get("tgt_db_list", [])
            sel_tgt_db = st.selectbox("DB Seç", tgt_dbs, key="sel_tgt_db") if tgt_dbs else None
        
        # --- AYARLAR SLIDER ---
        st.markdown("---")
        st.header("🎨 Görünüm Ayarları")
        wrap_width = st.slider("Satır Genişliği", 50, 200, 100, 10, help="Satır kesme limiti")

        st.info("Docker için `host.docker.internal` kullanın.")


    # --- ORTA ALAN ---
    if sel_src_db and sel_tgt_db:
        col1, col2 = st.columns(2)

        # SOL LİSTE
        with col1:
            st.subheader(f"📂 Kaynak: {sel_src_db}")
            conn_src = get_connection(src_ip, sel_src_db, src_user, src_pass)
            if conn_src:
                df_src = get_all_sps_secure(conn_src)
                sel_src_display = st.selectbox("Kaynak SP", df_src["DisplayText"], key="final_src_sel")
                
                if sel_src_display:
                    row_src = df_src[df_src["DisplayText"] == sel_src_display].iloc[0]
                    src_schema = row_src['SchemaName']
                    src_name = row_src['SpName']
            else:
                st.error("Bağlantı Yok")

        # SAĞ LİSTE
        with col2:
            st.subheader(f"📂 Hedef: {sel_tgt_db}")
            conn_tgt = get_connection(tgt_ip, sel_tgt_db, tgt_user, tgt_pass)
            if conn_tgt:
                df_tgt = get_all_sps_secure(conn_tgt)
                sel_tgt_display = st.selectbox("Hedef SP", df_tgt['DisplayText'], key="final_tgt_sel")
                
                if sel_tgt_display:
                    row_tgt = df_tgt[df_tgt['DisplayText'] == sel_tgt_display].iloc[0]
                    tgt_schema = row_tgt['SchemaName']
                    tgt_name = row_tgt['SpName']
            else:
                st.error("Bağlantı Yok")

        # BUTON
        st.divider()
        if st.button("🚀 Karşılaştırmayı Başlat", type="primary", use_container_width=True):
            if conn_src and conn_tgt:
                with st.spinner("Kodlar satır satır işleniyor..."):
                    code_src = get_sp_content_secure(conn_src, src_schema, src_name)
                    code_tgt = get_sp_content_secure(conn_tgt, tgt_schema, tgt_name)

                    if not code_src and not code_tgt:
                        st.warning("Veri çekilemedi.")
                    else:
                        # Slider'dan gelen wrap_width değerini kullanıyoruz
                        html_diff = highlight_diff(code_src, code_tgt, width=wrap_width)
                        
                        st.markdown("### 📊 Detaylı Fark Analizi")
                        components.html(html_diff, height=800, scrolling=True)
    else:
        st.info("👈 Başlamak için lütfen sol menüden Veritabanlarını seçin.")


# --- 5. GİRİŞ EKRANI ---
if not st.session_state['authenticated']:
    col_spacer1, col_login, col_spacer2 = st.columns([1, 2, 1])
    
    with col_login:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center;'>🔐 Güvenli Giriş</h2>", unsafe_allow_html=True)
        
        user_input = st.text_input("Kullanıcı Adı")
        pass_input = st.text_input("Şifre", type="password")

        if st.button("Giriş Yap", type="primary"):
            check_login(user_input, pass_input)

        st.markdown("<div style='text-align: center; color: gray; font-size: 12px;'>v3.0 - Mac Edition</div>", unsafe_allow_html=True)

else: 
    main_app()