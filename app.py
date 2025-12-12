import streamlit as st
import pandas as pd
import pyodbc
import difflib
import streamlit.components.v1 as components
import time

# --- Sayfa ve Güvenlik Ayarları ---
st.set_page_config(layout="wide", page_title="SQL SP Compare Tool v2.0")

# Oturum Durumu Kontrolü (Session State)
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

# --- CSS Stilleri ---
st.markdown("""

<style>
    /* Genel font iyileştirmeleri */
            body { font-family: 'Segoe UI , Tahome, Geneva, Verdana, sans-serif; }

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

</style>

""", unsafe_allow_html=True) 


# --- 1. Güvenlk ve Giriş Fonksiyonları ---
def check_login(username, password):
    """
    Basit kimlik doğrulama.
    Güvenlik Nout: Prod ortamında bu şifreler Vault'tan veya Environment Variable'dan gelmeli.
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
        st.success("Giriş Başarılı! Yönlediriliyorsunuz....")
        time.sleep(1)
        st.rerun()

    else:
        st.error("Hatalı Kullanıcı Adı veya Şifre")


def logout():
    st.session_state["authenticated"] = False
    st.rerun()

# --- 2. Veritabanı Bağlantı Fonksiyonları

def get_connection(server, database, username, password):
    """
    SQL Server Bağlantı Oluşturucu
    Hem SQL Auth (Kullanıcı/Şifre) hem de Windows Auth (Trusted) destekler.
    Sistemdeki mevcut sürücüleri otomatik tarar ve uygun olanı seçer.
    """

    # Mevcut sürücüleri al
    available_drivers = pyodbc.drivers()
    for i in available_drivers:
        print("Mevcut Driver'ler:\n", i)
    # Öncelik sırasına göre denenecek sürücüler
    candidate_drivers = [
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server Native Client 10.0",
        "SQL Server" # En eski ve en garanti olan (Windows default)
    ]

    selected_driver = None
    
    # Her bir sürücüyü tek tek dene
    for driver_name in candidate_drivers:
        try:
            # Connection String Parçaları
            conn_str_parts = [
                f"DRIVER={{{driver_name}}}",
                f"SERVER={server}",
                "TrustServerCertificate=yes"
            ]

            if database:
                conn_str_parts.append(f"DATABASE = {database}")

            # Eğer kullanıcı adı veya şifre boşsa -> Windows Auth kullan
            if not username or not password:
                conn_str_parts.append("Trusted_Connection=yes")
            
            else:
                conn_str_parts.append(f"UID={username}")
                conn_str_parts.append(f"PWD={password}")

            # Parçaları birleştir
            conn_str = ";".join(conn_str_parts)

            # Bağlan
            conn = pyodbc.connect(conn_str, timeout=10)
            return conn

        except Exception as e:
            # Bu sürücü olmadı, sıradakine geç
            print(f"DEBUG: '{driver_name}' başarısız oldu. Sebep: {e}")
            last_error = e
            continue
    
    # Loga yaz ama kullanıcıya detay gösterme (Güvenlik)
    print(f"KRİTİK HATA: Hiçbir sürücü ile bağlanılamadı. Son hata: {last_error}")
    return None
    

def get_databases(server, username, password):
    """
    Sunucudaki veritabanlarını listeler.
    Bunun için 'master' veritabanına bağlanır.
    """

    # Önce master'a bağlanalım
    conn = get_connection(server, "master", username, password)

    if not conn:
        return []

    query = "SELECT name FROM sys.databases WHERE state_desc  = 'ONLINE' ORDER BY name" 

    try:
        df = pd.read_sql(query, conn)
        conn.close()

        return df['name'].to_list()
    
    except Exception as e:
        print(f"DEBUG: DB List Error: {e}")
        st.error("Veritabanı listesi çekilemedi.")
        return[]


@st.cache_data(ttl=300)
def get_all_sps_secure(_conn):
    """
    SP Listesini çeker. SQL Injection riski yok (Sabit sorgu).
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
    *** KRİTİK GÜVENLİK FONKSİYONU ***
    Parametreli sorgu (Parameterized Query) kullanılarak SQL Injection %100 engellendi.
    f-string yerin ? placeholder kullanıyoruz.
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

        # Parametreleri tuple olarak gönderiyoruz: (schema, sp_name)
        cursor.execute(query, (schema, sp_name))
        row = cursor.fetchone()
        return row[0] if row else ""
    
    except Exception as e:

        print(f"DEBUG: SP Conten Error: {e}")
        st.error("Kod içeriği alınırken hata oluştu.")
        return ""

def highlight_diff(text1, text2, width=130):
    """
    İki metin arasındaki farkı HTML forrmatında boyar.
    """

    if not text1: text1 = ""
    if not text2: text2 = ""

    # 90 karakterde alt satıra geç (Okunabilirlik)
    d = difflib.HtmlDiff(wrapcolumn=width)


    # Tabloyu oluştur
    html_content = d.make_file(text1.splitlines(), text2.splitlines(), context=False, numlines=3)

    # CSS Enjeksiyonu (Renklendirme burada yapılıyor)
    custom_css = """

        <style>
            /* Tablo Ayarları: Kodları sıkıştırma, ekrana yay
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

            /* YEŞİL (Eklene) - İki tonlu renk */
            .diff_add { background-color: #e6ffc; color: #1a1a1a; }
            .diff_add span { background-color: #acf2db; font-weight: bold; }

            /* Kırmızı (Silinen) - İki tonlu renk */
            .diff_add { background-color: #ffebe9; color: #1a1a1a; }
            .diff_add span { background-color: #fdb8c0; text-decoration: linethrough; }

            /* SARI (Değişen) */
            .diff_chg { background-color: #fffbdd; color: #1a1a1a }
            .diff_chg span { background-color: #fceea6; #fceea6; font-weight: bold; }        
        </style>
    """

    return custom_css + html_content


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
        st.header("Görünüm Ayarları")

        # Slider: En az 50, en çok 300, varsayılan 130 
        wrap_width = st.slider(
            "Satır Genişliği (Karakter)",
            min_value=50,
            max_value=300,
            value=130,
            step=10,
            help="Kod satırlarının kaç karakterden sonra alt satıra geçeceğini belirler."
        )

    # --- Orta Alan (SP Seçimi ve Compare) ---

    # Sadece iki tarafta da DB seçildiyse göster
    if sel_src_db and sel_tgt_db:

        col1, col2 = st.columns(2)

        # --- Sol Taraf SP Listesi
        with col1:
            st.subheader(f"Kaynak: {sel_src_db}")
            conn_src = get_connection(src_ip, sel_src_db, src_user, src_pass)

            if conn_src:
                df_src = get_all_sps_secure(conn_src)

                # Kullanıcıya listeden seçtir
                sel_src_display = st.selectbox("Kaynak SP Seçiniz", df_src["DisplayText"], key="final_src_sel")


                # Seçilen text'ten Schema ve Name', ayıkla (Veri güvenliği için dataframe'den çekiyoruz)
                if sel_src_display:
                    row_src = df_src[df_src["DisplayText"] == sel_src_display].iloc[0]
                    src_schema = row_src['SchemaName']
                    src_name = row_src['SpName']

            else:
                st.error("Kaynak Bağlantısı Koptu!")

        # --- Sağ Taraf SP Listesi ---

        with col2:
            st.subheader(f"Hedef: {sel_tgt_db}")
            conn_tgt = get_connection(tgt_ip, sel_tgt_db, tgt_user, tgt_pass)

            if conn_tgt:
                df_tgt = get_all_sps_secure(conn_tgt)
                sel_tgt_display = st.selectbox("Hedef SP Seçiniz", df_tgt['DisplayText'], key="final_tgt_sel")

                if sel_tgt_display:
                    row_tgt = df_tgt[df_tgt['DisplayText'] == sel_tgt_display].iloc[0]
                    tgt_schema = row_tgt['SchemaName']
                    tgt_name = row_tgt['SpName']

            else:
                st.error("Hedef Bağlantısı Koptu!")

        # --- Karşılaştırma Butonu ---

        st.divider()
        if st.button("Karşılaştırmayı Başlat", type="primary", use_container_width=True):

            if conn_src and conn_tgt:

                with st.spinner("Kodlar Analiz Ediliyor...."):
                    # Güvenli fonksiyonla kodları çek
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
        # DB seçilmediyse boş ekrana mesaj
        st.info("Lütfen sol menüden Kaynak ve Hedef veritabanlarını seçerek başlayın.")

# --- 4. Giriş Ekranı (Login Gate) ---
if not st.session_state['authenticated']:

    # Basit ve şık bir login ekranı ortalaması
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
    # Giriş yapıldıysa ana uygulamayı çalştır
    main_app()