import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from config import DB_PATH
from streamlit_option_menu import option_menu


# Configurações da página
st.set_page_config(page_title="Painel Gerencial - Esportes.ia (Exemplo)", layout="wide")

FONT_CSS = """
<style>
/* registra a fonte externa (use as URLs que você já tem) */
@font-face {
    font-family: "Mangerica W00 Light";
    src: url("https://db.onlinewebfonts.com/t/7529ab540783c63be75c439c61d5f952.eot");
    src: url("https://db.onlinewebfonts.com/t/7529ab540783c63be75c439c61d5f952.eot?#iefix") format("embedded-opentype"),
         url("https://db.onlinewebfonts.com/t/7529ab540783c63be75c439c61d5f952.woff2") format("woff2"),
         url("https://db.onlinewebfonts.com/t/7529ab540783c63be75c439c61d5f952.woff") format("woff"),
         url("https://db.onlinewebfonts.com/t/7529ab540783c63be75c439c61d5f952.ttf") format("truetype"),
         url("https://db.onlinewebfonts.com/t/7529ab540783c63be75c439c61d5f952.svg#Mangerica W00 Light") format("svg");
    font-weight: 300 400;
    font-style: normal;
    font-display: swap;
}

/* aplica a fonte ao app inteiro */
html, body, .stApp, .block-container, .main, .css-1outpf7 {
    font-family: "Mangerica W00 Light", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    background-color: #0f1723 !important;
    color: #E5E7EB !important;
}

/* ajustes opcionais para headers/metricos */
h1, h2, h3, .stMetric, .stMetricValue {
    font-family: "Mangerica W00 Light", sans-serif !important;
}

/* força cores de fundo mais escuras em blocos (opcional) */
.stBlock, .st-Button, .stTextInput {
    background-color: transparent !important;
}
</style>
"""

# Utilitários
def db_connect():
    return sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)

def period_to_dates(period, custom_start=None, custom_end=None):
    """
    Retorna start_str, end_str onde start nunca será anterior a 2025-01-01.
    """
    hoje = datetime.today()
    if period == "Dia":
        start = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
        end = hoje
    elif period == "Semana":
        start = (hoje - timedelta(days=hoje.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = hoje
    elif period == "Mês":
        start = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = hoje
    elif period == "Personalizado":
        # custom_start/custom_end expected as datetime.date
        start = datetime.combine(custom_start, datetime.min.time())
        end = datetime.combine(custom_end, datetime.max.time())
    else:
        # fallback últimos 7 dias
        start = (hoje - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = hoje

    # Garantir limite mínimo 2025-01-01
    min_date = datetime(2025, 1, 1)
    if start < min_date:
        start = min_date
    if end < min_date:
        # evita intervalos totalmente antes de 2025 -> iguala end ao min_date (vai retornar vazio)
        end = min_date

    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

# Queries principais

def fetch_kpis(start_date, end_date):
    conn = db_connect()
    cur = conn.cursor()

    # Margem Bruta (soma de Margem_USD da sales_orders no período)
    q_margem = """
        SELECT IFNULL(SUM(Margem_USD), 0) FROM sales_orders
        WHERE date(created_time) BETWEEN date(?) AND date(?)
        AND status IN ('Pedido Liberado', 'Enviado', 'Faturado')
    """

    # Toneladas carregadas no período
    q_t_carregadas = """
        SELECT IFNULL(SUM(quantidade_carregada), 0) FROM gestao_carregamentos
        WHERE status = 'Carregados'
        AND date(created_time) BETWEEN date(?) AND date(?)
    """

    # Toneladas pedidas no período (soma de quantity em sales_order_items)
    q_t_pedidas = """
        SELECT IFNULL(SUM(i.quantity), 0)
        FROM sales_order_items i
        JOIN sales_orders o ON i.sales_order_subject = o.subject
        WHERE date(o.created_time) BETWEEN date(?) AND date(?)
        AND o.status IN ('Pedido Liberado', 'Enviado')
    """

    # Número de pedidos distintos no período
    q_num_pedidos = """
        SELECT COUNT(DISTINCT subject) FROM sales_orders
        WHERE date(created_time) BETWEEN date(?) AND date(?)
        AND status IN ('Pedido Liberado', 'Enviado')
    """

    cur.execute(q_margem, (start_date, end_date))
    margem_bruta = cur.fetchone()[0] or 0

    cur.execute(q_t_carregadas, (start_date, end_date))
    toneladas_carregadas = cur.fetchone()[0] or 0

    cur.execute(q_t_pedidas, (start_date, end_date))
    toneladas_pedidas = cur.fetchone()[0] or 0

    cur.execute(q_num_pedidos, (start_date, end_date))
    num_pedidos = cur.fetchone()[0] or 0

    conn.close()
    return {
        "margem_bruta": margem_bruta,
        "toneladas_carregadas": toneladas_carregadas,
        "toneladas_pedidas": toneladas_pedidas,
        "num_pedidos": num_pedidos,
    }


def pedidos_por_produto(start_date, end_date, top_n=20):
    conn = db_connect()
    q = """
        SELECT i.product_name AS produto, SUM(i.quantity) AS quantidade
        FROM sales_order_items i
        JOIN sales_orders o ON i.sales_order_subject = o.subject
        WHERE date(o.created_time) BETWEEN date(?) AND date(?)
          AND o.status IN ('Pedido Liberado', 'Enviado')
        GROUP BY i.product_name
        ORDER BY quantidade DESC
        LIMIT ?
    """
    df = pd.read_sql_query(q, conn, params=(start_date, end_date, top_n))
    conn.close()
    return df


def carregamentos_por_dia(start_date, end_date):
    conn = db_connect()
    q = """
        SELECT date(created_time) AS dia, SUM(quantidade_carregada) AS quantidade
        FROM gestao_carregamentos
        WHERE status = 'Carregados'
          AND date(created_time) BETWEEN date(?) AND date(?)
        GROUP BY date(created_time)
        ORDER BY date(created_time)
    """
    df = pd.read_sql_query(q, conn, params=(start_date, end_date))
    conn.close()
    return df


def margem_por_produto(start_date, end_date):
    conn = db_connect()
    q = """
        SELECT i.product_name AS produto, SUM(o.Margem_USD) AS margem_total
        FROM sales_order_items i
        JOIN sales_orders o ON i.sales_order_subject = o.subject
        WHERE o.Margem_USD IS NOT NULL
          AND date(o.created_time) BETWEEN date(?) AND date(?)
        GROUP BY i.product_name
        ORDER BY margem_total DESC
        LIMIT 20
    """
    df = pd.read_sql_query(q, conn, params=(start_date, end_date))
    conn.close()
    return df


def compras_por_mes(limit_months=12):
    """
    Busca compras a partir de 2025-01-01 e retorna os últimos `limit_months` meses disponíveis.
    """
    conn = db_connect()
    q = """
        SELECT strftime('%Y-%m', data_compra) AS mes, SUM(quantity) AS quantidade
        FROM purchase_orders
        WHERE date(data_compra) >= '2025-01-01'
        GROUP BY mes
        ORDER BY mes
    """
    df = pd.read_sql_query(q, conn)
    conn.close()

    if not df.empty:
        # transforma em data para facilitar filtragem dos últimos N meses (respeitando 2025-01-01)
        df['mes_dt'] = pd.to_datetime(df['mes'] + '-01')
        # pega os últimos limit_months registros cronologicos (pode haver menos)
        df = df.sort_values('mes_dt').tail(limit_months)
        df['mes_label'] = df['mes_dt'].dt.strftime('%b/%Y')
        df = df[['mes', 'mes_label', 'quantidade']]
    return df


# Layout principal
st.title("Painel Gerencial")
st.markdown("Uma visão rápida (KPIs) e gráficos principais. Use os filtros abaixo para ajustar o período e os módulos.")

with st.sidebar:
    selected = option_menu(
        menu_title=None,  # sem título, só o menu estilizado
        options=["Gerencial"],   # somente a página gerencial como opção
        icons=["bar-chart"],     # ícone (use qualquer um suportado)
        menu_icon="cast",
        default_index=0,
        orientation="vertical",
        styles={
            "container": {"padding": "0!important", "background-color": "#0f1723"},
            "icon": {"color": "white", "font-size": "18px"},
            "nav-link": {
                "font-size": "14px",
                "text-align": "left",
                "margin":"0px",
                "padding":"8px 10px"
            },
            "nav-link-selected": {"background-color": "#2563eb", "color": "white"},
        }
    )

# Tabs internas (principal + sub-páginas)
tab_principal, tab_compras, tab_pedidos, tab_carregamentos, tab_margem = st.tabs([
    "Principal", "Compras", "Pedidos", "Carregamentos", "Margem"
])

# Filtro de período global (aplica-se aos KPIs e gráficos principais)
with tab_principal:
    col1, col2 = st.columns([3, 1])
    with col1:
        periodo = st.selectbox("Período principal", ["Dia", "Semana", "Mês", "Personalizado"], index=1)
    with col2:
        # se personalizado, seleciona intervalo
        if periodo == "Personalizado":
            start_date = st.date_input("Data inicial", value=datetime.today() - timedelta(days=7))
            end_date = st.date_input("Data final", value=datetime.today())
        else:
            start_date = None
            end_date = None

    start_str, end_str = period_to_dates(periodo, start_date, end_date)

    # KPIs
    kpis = fetch_kpis(start_str, end_str)

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Margem Bruta (USD)", f"{kpis['margem_bruta']:.2f}")
    kpi2.metric("Toneladas Carregadas", f"{kpis['toneladas_carregadas']:.2f}")
    kpi3.metric("Toneladas Pedidas", f"{kpis['toneladas_pedidas']:.2f}")
    kpi4.metric("Número de Pedidos", f"{kpis['num_pedidos']}")

    st.markdown("---")

    # Quatro gráficos principais
    g1_col, g2_col = st.columns(2)

    # Gráfico 1: Pedidos por produto (barra)
    with g1_col:
        st.subheader("Top produtos por quantidade (período)")
        df_prod = pedidos_por_produto(start_str, end_str, top_n=12)
        if df_prod.empty:
            st.info("Sem dados para o período selecionado")
        else:
            fig1 = px.bar(df_prod, x='produto', y='quantidade', labels={'produto': 'Produto', 'quantidade': 'Quantidade'})
            st.plotly_chart(fig1, use_container_width=True)

    # Gráfico 2: Carregamentos por dia (linha)
    with g2_col:
        st.subheader("Carregamentos por dia")
        df_car_dia = carregamentos_por_dia(start_str, end_str)
        if df_car_dia.empty:
            st.info("Sem carregamentos no período selecionado")
        else:
            fig2 = px.line(df_car_dia, x='dia', y='quantidade', labels={'dia': 'Dia', 'quantidade': 'Quantidade Carregada'})
            st.plotly_chart(fig2, use_container_width=True)

    g3_col, g4_col = st.columns(2)

    # Gráfico 3: Margem por produto (pizza)
    with g3_col:
        st.subheader("Margem por produto (top)")
        df_marg = margem_por_produto(start_str, end_str)
        if df_marg.empty:
            st.info("Sem margem registrada no período")
        else:
            fig3 = px.pie(df_marg, names='produto', values='margem_total', title='Margem por produto')
            st.plotly_chart(fig3, use_container_width=True)

    # Gráfico 4: Compras por mês (últimos 6-12 meses)
    with g4_col:
        st.subheader("Compras por mês (últimos 12 meses)")
        df_comp = compras_por_mes(limit_months=12)
        if df_comp.empty:
            st.info("Sem compras registradas a partir de 2025")
        else:
            fig4 = px.bar(df_comp, x='mes_label', y='quantidade', labels={'mes_label': 'Mês', 'quantidade': 'Quantidade'})
            st.plotly_chart(fig4, use_container_width=True)

    st.markdown("---")
    st.write("Use as abas acima (Compras / Pedidos / Carregamentos / Margem) para ver detalhes e filtros por módulo.")

# Sub-página: Compras
with tab_compras:
    st.header("Compras")
    st.markdown("Filtros específicos de Compras")
    colA, colB = st.columns(2)
    with colA:
        periodo_comp = st.selectbox("Período - Compras", ["Mês", "Personalizado"], index=0, key='pc')
        if periodo_comp == "Personalizado":
            start_c = st.date_input("Início (Compras)", value=datetime.today() - timedelta(days=30), key='sc')
            end_c = st.date_input("Fim (Compras)", value=datetime.today(), key='ec')
            start_c_str, end_c_str = period_to_dates('Personalizado', start_c, end_c)
        else:
            start_c_str, end_c_str = period_to_dates('Mês')

    df_comp_detalhe = pd.read_sql_query(
        "SELECT data_compra, produto_name AS produto, quantity FROM purchase_orders WHERE date(data_compra) BETWEEN date(?) AND date(?) AND date(data_compra) >= '2025-01-01' ORDER BY data_compra",
        db_connect(), params=(start_c_str, end_c_str)
    )
    st.dataframe(df_comp_detalhe, use_container_width=True)

# Sub-página: Pedidos
with tab_pedidos:
    st.header("Pedidos")
    st.markdown("Filtros específicos de Pedidos")
    colA, colB = st.columns(2)
    with colA:
        periodo_ped = st.selectbox("Período - Pedidos", ["Semana", "Personalizado"], index=0, key='pp')
        if periodo_ped == "Personalizado":
            s_p = st.date_input("Início (Pedidos)", value=datetime.today() - timedelta(days=7), key='spp')
            e_p = st.date_input("Fim (Pedidos)", value=datetime.today(), key='epp')
            s_p_str, e_p_str = period_to_dates('Personalizado', s_p, e_p)
        else:
            s_p_str, e_p_str = period_to_dates('Semana')

    df_pedidos_detalhe = pd.read_sql_query(
        "SELECT o.account_name AS razao_social, i.product_name AS produto, SUM(i.quantity) AS quantidade FROM sales_order_items i JOIN sales_orders o ON i.sales_order_subject = o.subject WHERE date(o.created_time) BETWEEN date(?) AND date(?) AND date(o.created_time) >= '2025-01-01' GROUP BY o.account_name, i.product_name ORDER BY o.account_name",
        db_connect(), params=(s_p_str, e_p_str)
    )
    st.dataframe(df_pedidos_detalhe, use_container_width=True)

# Sub-página: Carregamentos
with tab_carregamentos:
    st.header("Carregamentos")
    st.markdown("Filtros específicos de Carregamentos")
    periodo_car = st.selectbox("Período - Carregamentos", ["Semana", "Mês", "Personalizado"], index=0, key='pcar')
    if periodo_car == "Personalizado":
        s_c = st.date_input("Início (Carreg)", value=datetime.today() - timedelta(days=7), key='sc2')
        e_c = st.date_input("Fim (Carreg)", value=datetime.today(), key='ec2')
        s_c_str, e_c_str = period_to_dates('Personalizado', s_c, e_c)
    elif periodo_car == 'Mês':
        s_c_str, e_c_str = period_to_dates('Mês')
    else:
        s_c_str, e_c_str = period_to_dates('Semana')

    df_carreg_detalhe = pd.read_sql_query(
        "SELECT date(created_time) AS data, produto_name AS produto, quantidade_carregada FROM gestao_carregamentos WHERE status = 'Carregados' AND date(created_time) BETWEEN date(?) AND date(?) AND date(created_time) >= '2025-01-01' ORDER BY created_time",
        db_connect(), params=(s_c_str, e_c_str)
    )
    st.dataframe(df_carreg_detalhe, use_container_width=True)

# Sub-página: Margem
with tab_margem:
    st.header("Margem")
    st.markdown("Filtros específicos de Margem")
    periodo_m = st.selectbox("Período - Margem", ["Semana", "Mês", "Personalizado"], index=0, key='pm')
    if periodo_m == "Personalizado":
        s_m = st.date_input("Início (Margem)", value=datetime.today() - timedelta(days=7), key='sm')
        e_m = st.date_input("Fim (Margem)", value=datetime.today(), key='em')
        s_m_str, e_m_str = period_to_dates('Personalizado', s_m, e_m)
    elif periodo_m == 'Mês':
        s_m_str, e_m_str = period_to_dates('Mês')
    else:
        s_m_str, e_m_str = period_to_dates('Semana')

    df_marg_detalhe = pd.read_sql_query(
        "SELECT i.product_name AS produto, AVG(o.Margem_USD) AS margem_media, SUM(o.Margem_USD) AS margem_total FROM sales_order_items i JOIN sales_orders o ON i.sales_order_subject = o.subject WHERE o.Margem_USD IS NOT NULL AND date(o.created_time) BETWEEN date(?) AND date(?) AND date(o.created_time) >= '2025-01-01' GROUP BY i.product_name ORDER BY margem_total DESC",
        db_connect(), params=(s_m_str, e_m_str)
    )
    st.dataframe(df_marg_detalhe, use_container_width=True)


# Rodapé com nota
st.sidebar.markdown("---")
st.sidebar.caption("Dashboard gerencial - desenvolvido para exibir KPIs principais e detalhes por módulo. Ajuste filtros conforme necessário.")
