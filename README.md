# Shopee Sync Multi — v2

**Novidades:**
- Editar **política por loja** (comissão % e R$/unidade)
- **Resumo por loja/período** com KPIs (bruto, previsto, liberado, delta)
- **Importar Released CSV** e conciliar previsto × liberado (status: PENDENTE/PARCIAL/LIBERADO/ACIMA_DO_ESPERADO)
- **Postgres-ready**: se definir `DATABASE_URL`, usa Postgres; senão usa `sqlite:///data.db`

## Deploy
1. Suba `app.py`, `shopee_api.py`, `requirements.txt` no GitHub
2. Streamlit Cloud → Deploy → file `app.py`
3. (Opcional) Secrets: `redirect_url = "https://SEU-APP.streamlit.app"`
4. (Opcional) Produção: variáveis de ambiente `DATABASE_URL` (Postgres)

