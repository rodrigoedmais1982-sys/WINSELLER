
import os, time, json
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from shopee_api import auth_partner_link, get_access_token, refresh_access_token, get_order_list, get_order_detail

st.set_page_config(page_title="Shopee Sync Multi v2", page_icon="🧲", layout="wide")
st.title("🧲 Shopee — Sync Multi-conta v2 (Pedidos + Estimativa + Conciliação)")

# --- DB engine (SQLite por padrão; Postgres se DATABASE_URL definido) ---
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")
engine = create_engine(DB_URL, pool_pre_ping=True)

def init_db():
    with engine.begin() as con:
        con.execute(text("""CREATE TABLE IF NOT EXISTS shops(
            shop_id INTEGER PRIMARY KEY,
            cnpj TEXT,
            alias TEXT,
            partner_id INTEGER,
            partner_key TEXT,
            access_token TEXT,
            refresh_token TEXT,
            access_expires_at INTEGER,
            com_perc REAL DEFAULT 20.0,
            taxa_un REAL DEFAULT 4.0,
            created_at TEXT
        )"""))
        con.execute(text("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER,
            order_sn TEXT,
            item_name TEXT,
            unit_price REAL,
            qty INTEGER,
            bruto REAL,
            comissao REAL,
            taxa_fixa REAL,
            esperado REAL,
            created_time INTEGER
        )"""))
        con.execute(text("""CREATE TABLE IF NOT EXISTS releases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER,
            order_sn TEXT,
            valor_creditado REAL,
            batch TEXT,
            data_release TEXT
        )"""))

init_db()

# --- Sidebar: credenciais padrão e política default ---
with st.sidebar:
    st.header("⚙️ Credenciais padrão")
    partner_id = st.text_input("partner_id", value="")
    partner_key = st.text_input("partner_key (secret)", type="password")
    redirect_url = st.text_input("Redirect URL", value=st.secrets.get("redirect_url", "https://example.com"))

    st.header("💰 Política padrão")
    default_com = st.number_input("Comissão (%)", 0.0, 50.0, 20.0, 0.5)
    default_tax = st.number_input("Taxa fixa (R$/unidade)", 0.0, 50.0, 4.0, 0.5)

st.markdown("## 1) Conectar nova loja Shopee")
st.write("1) Gere o link, 2) autorize a loja, 3) cole `code` e `shop_id`, 4) salve.")

col1, col2 = st.columns([2,1])
with col1:
    if partner_id and partner_key:
        link = auth_partner_link(int(partner_id), partner_key, redirect_url)
        st.code(link)
        st.markdown(f"[🔗 Abrir link de autorização]({link})", unsafe_allow_html=True)
with col2:
    code = st.text_input("code (da URL)")
    shop_id_in = st.text_input("shop_id")
    cnpj = st.text_input("CNPJ (opcional)")
    alias = st.text_input("Apelido da loja (opcional)")
    com = st.number_input("Comissão (%) da loja", 0.0, 50.0, default_com, 0.5, key="com_loja")
    tax = st.number_input("Taxa (R$/unid) da loja", 0.0, 50.0, default_tax, 0.5, key="tax_loja")
    if st.button("Salvar loja"):
        try:
            tok = get_access_token(int(partner_id), partner_key, code, int(shop_id_in))
            access_token = tok.get("access_token") or tok.get("data",{}).get("access_token")
            refresh_token = tok.get("refresh_token") or tok.get("data",{}).get("refresh_token")
            exp = int(time.time()) + 4*3600  # validade padrão ~4h
            with engine.begin() as con:
                con.execute(text("""INSERT INTO shops(shop_id, cnpj, alias, partner_id, partner_key, access_token, refresh_token, access_expires_at, com_perc, taxa_un, created_at)
                                    VALUES(:shop_id,:cnpj,:alias,:partner_id,:partner_key,:access_token,:refresh_token,:exp,:com,:tax,:dt)
                                    ON CONFLICT(shop_id) DO UPDATE SET 
                                      cnpj=excluded.cnpj, alias=excluded.alias, partner_id=excluded.partner_id, partner_key=excluded.partner_key,
                                      access_token=excluded.access_token, refresh_token=excluded.refresh_token, access_expires_at=excluded.access_expires_at,
                                      com_perc=excluded.com_perc, taxa_un=excluded.taxa_un"""),
                           {"shop_id": int(shop_id_in), "cnpj": cnpj, "alias": alias, "partner_id": int(partner_id),
                            "partner_key": partner_key, "access_token": access_token, "refresh_token": refresh_token,
                            "exp": exp, "com": com, "tax": tax, "dt": datetime.utcnow().isoformat()})
            st.success("Loja conectada e salva!")
        except Exception as e:
            st.error(f"Erro ao salvar loja: {e}")

st.markdown("---")
st.markdown("## 2) Lojas conectadas (editar política)")
shops = pd.read_sql("SELECT shop_id, cnpj, alias, com_perc, taxa_un, access_expires_at FROM shops", engine)
if shops.empty:
    st.info("Nenhuma loja conectada ainda.")
else:
    now = int(time.time())
    shops["token_status"] = np.where(shops["access_expires_at"]>now, "válido", "expirar/expirado")
    st.dataframe(shops, use_container_width=True)
    st.markdown("### Editar política de uma loja")
    sid = st.selectbox("Escolha a loja", shops["shop_id"].astype(str).tolist())
    if sid:
        r = pd.read_sql("SELECT * FROM shops WHERE shop_id = :sid", engine, params={"sid": int(sid)}).iloc[0]
        new_com = st.number_input("Comissão (%)", 0.0, 50.0, float(r["com_perc"]), 0.5, key="edit_com")
        new_tax = st.number_input("Taxa (R$/unid)", 0.0, 50.0, float(r["taxa_un"]), 0.5, key="edit_tax")
        if st.button("Salvar alterações"):
            with engine.begin() as con:
                con.execute(text("UPDATE shops SET com_perc=:c, taxa_un=:t WHERE shop_id=:sid"),
                            {"c": new_com, "t": new_tax, "sid": int(sid)})
            st.success("Política atualizada!")

st.markdown("---")
st.markdown("## 3) Sincronizar pedidos (por período)")
if shops.empty:
    st.info("Conecte ao menos uma loja.")
else:
    d1 = st.date_input("De", value=datetime.utcnow().date()-timedelta(days=7))
    d2 = st.date_input("Até", value=datetime.utcnow().date())
    shop_sel = st.selectbox("Loja", shops["shop_id"].astype(str).tolist(), key="sync_shop")
    if st.button("Buscar pedidos da loja selecionada"):
        try:
            srow = pd.read_sql("SELECT * FROM shops WHERE shop_id=:sid", engine, params={"sid": int(shop_sel)}).iloc[0]
            # refresh token se expirado
            if int(srow["access_expires_at"]) < int(time.time()):
                try:
                    rt = refresh_access_token(int(srow["partner_id"]), srow["partner_key"], srow["refresh_token"], int(srow["shop_id"]))
                    new_access = rt.get("access_token") or rt.get("data",{}).get("access_token")
                    new_refresh = rt.get("refresh_token") or rt.get("data",{}).get("refresh_token") or srow["refresh_token"]
                    exp = int(time.time()) + 4*3600
                    with engine.begin() as con:
                        con.execute(text("UPDATE shops SET access_token=:a, refresh_token=:r, access_expires_at=:e WHERE shop_id=:sid"),
                                    {"a": new_access, "r": new_refresh, "e": exp, "sid": int(srow["shop_id"])})
                    srow["access_token"] = new_access
                except Exception as e:
                    st.warning(f"Falha ao renovar token, tentando com token atual: {e}")

            tf = int(datetime(d1.year,d1.month,d1.day).timestamp())
            tt = int(datetime(d2.year,d2.month,d2.day,23,59,59).timestamp())
            r = get_order_list(int(srow["partner_id"]), srow["partner_key"], srow["access_token"], int(srow["shop_id"]), tf, tt, page_size=50)
            order_sn_list = r.get("response",{}).get("order_sn_list") or r.get("data",{}).get("order_list",[])
            if isinstance(order_sn_list, list) and order_sn_list and not isinstance(order_sn_list[0], str):
                order_sn_list = [x.get("order_sn") for x in order_sn_list if isinstance(x, dict)]
            if not order_sn_list:
                st.info("Nenhum pedido retornado no período.")
            else:
                d = get_order_detail(int(srow["partner_id"]), srow["partner_key"], srow["access_token"], int(srow["shop_id"]), order_sn_list[:50])
                data = d.get("response",{}).get("order_list") or d.get("data",{}).get("order_list",[])
                rows = []
                for od in data:
                    created = int(od.get("create_time") or time.time())
                    for it in od.get("item_list",[]):
                        price = float(it.get("model_discounted_price") or it.get("model_original_price") or it.get("item_price") or 0)
                        qty = int(it.get("model_quantity_purchased") or it.get("order_item_qty") or 1)
                        bruto = price*qty
                        com = bruto*(float(srow["com_perc"])/100.0)
                        taxa = qty*float(srow["taxa_un"])
                        esperado = bruto - com - taxa
                        rows.append({"shop_id": int(srow["shop_id"]), "order_sn": od.get("order_sn"),
                                     "item_name": it.get("item_name"), "unit_price": price, "qty": qty,
                                     "bruto": bruto, "comissao": com, "taxa_fixa": taxa, "esperado": esperado,
                                     "created_time": created})
                if rows:
                    with engine.begin() as con:
                        con.execute(text("""
                            INSERT INTO orders(shop_id, order_sn, item_name, unit_price, qty, bruto, comissao, taxa_fixa, esperado, created_time)
                            VALUES(:shop_id,:order_sn,:item_name,:unit_price,:qty,:bruto,:comissao,:taxa_fixa,:esperado,:created_time)
                        """), rows)
                    st.success(f"Sincronizados {len(rows)} itens.")
                df = pd.read_sql("SELECT * FROM orders WHERE shop_id=:sid AND created_time BETWEEN :tf AND :tt",
                                  engine, params={"sid": int(srow["shop_id"]), "tf": tf, "tt": tt})
                st.dataframe(df, use_container_width=True)
                st.download_button("Baixar CSV (pedidos)", df.to_csv(index=False).encode("utf-8"), "orders_sync.csv","text/csv")
        except Exception as e:
            st.error(f"Erro: {e}")

st.markdown("---")
st.markdown("## 4) Importar Released (CSV) e conciliar")
uploaded = st.file_uploader("Arquivo Released/Income (CSV)", type=["csv"])
if uploaded is not None and not shops.empty:
    import io
    content = uploaded.read().decode("utf-8", errors="ignore")
    # tentar separadores comuns
    for sep in [",",";","\t","|"]:
        try:
            df_rel_raw = pd.read_csv(io.StringIO(content), sep=sep)
            if df_rel_raw.shape[1] >= 2:
                break
        except Exception:
            continue
    st.write("Prévia:")
    st.dataframe(df_rel_raw.head(10), use_container_width=True)
    cols = df_rel_raw.columns.tolist()
    col_order = st.selectbox("Coluna de Order ID (order_sn)", cols, index=0)
    col_valor = st.selectbox("Coluna de Valor creditado", cols, index=1)
    col_batch = st.selectbox("Coluna de Batch (opcional)", ["(vazio)"]+cols, index=0)
    col_data = st.selectbox("Coluna Data release (opcional)", ["(vazio)"]+cols, index=0)
    shop_rel = st.selectbox("Loja (shop_id) para esses lançamentos", shops["shop_id"].astype(str).tolist())
    if st.button("Gravar releases"):
        rows = []
        for _,r in df_rel_raw.iterrows():
            rows.append({
                "shop_id": int(shop_rel),
                "order_sn": str(r[col_order]),
                "valor_creditado": float(pd.to_numeric(r[col_valor], errors="coerce") or 0),
                "batch": None if col_batch=="(vazio)" else str(r[col_batch]),
                "data_release": None if col_data=="(vazio)" else str(r[col_data])
            })
        with engine.begin() as con:
            con.execute(text("""INSERT INTO releases(shop_id, order_sn, valor_creditado, batch, data_release)
                                VALUES(:shop_id,:order_sn,:valor_creditado,:batch,:data_release)"""), rows)
        st.success(f"Foram gravados {len(rows)} lançamentos.")

st.markdown("---")
st.markdown("## 5) Resumo e Status (por loja/período)")
if not shops.empty:
    sid2 = st.selectbox("Loja", shops["shop_id"].astype(str).tolist(), key="report_shop")
    d1r = st.date_input("De (relatório)", value=datetime.utcnow().date()-timedelta(days=7), key="d1r")
    d2r = st.date_input("Até (relatório)", value=datetime.utcnow().date(), key="d2r")
    tf2 = int(datetime(d1r.year,d1r.month,d1r.day).timestamp())
    tt2 = int(datetime(d2r.year,d2r.month,d2r.day,23,59,59).timestamp())
    dfp = pd.read_sql("SELECT * FROM orders WHERE shop_id=:sid AND created_time BETWEEN :tf AND :tt",
                      engine, params={"sid": int(sid2), "tf": tf2, "tt": tt2})
    dfr = pd.read_sql("SELECT order_sn, SUM(valor_creditado) AS liberado FROM releases WHERE shop_id=:sid GROUP BY order_sn",
                      engine, params={"sid": int(sid2)})
    if dfp.empty:
        st.info("Sem pedidos nesse período.")
    else:
        conc = dfp.merge(dfr, on="order_sn", how="left").fillna({"liberado":0.0})
        conc["delta"] = conc["liberado"] - conc["esperado"]
        def status_row(r):
            exp = round(float(r["esperado"]),2)
            lib = round(float(r["liberado"]),2)
            if lib == 0: return "PENDENTE"
            if abs(lib-exp) <= 0.01: return "LIBERADO"
            if 0 < lib < exp - 0.01: return "PARCIAL"
            if lib > exp + 0.01: return "ACIMA_DO_ESPERADO"
            return "VERIFICAR"
        conc["status"] = conc.apply(status_row, axis=1)
        # KPIs
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Pedidos", int(conc["order_sn"].nunique()))
        c2.metric("Bruto (R$)", f"{conc['bruto'].sum():,.2f}")
        c3.metric("Esperado (R$)", f"{conc['esperado'].sum():,.2f}")
        c4.metric("Liberado (R$)", f"{conc['liberado'].sum():,.2f}")
        c5.metric("Δ (R$)", f"{conc['delta'].sum():,.2f}")
        st.dataframe(conc[["order_sn","item_name","unit_price","qty","bruto","comissao","taxa_fixa","esperado","liberado","delta","status"]]
                     .sort_values(["status","order_sn"]), use_container_width=True)
        st.download_button("Baixar conciliação (CSV)", conc.to_csv(index=False).encode("utf-8"),
                           "conciliação_shopee.csv","text/csv")

st.markdown("---")
st.caption("v2: multi-conta, política editável, resumo por período e conciliação com Released. Produção: configure DATABASE_URL (Postgres) para escalar.")
