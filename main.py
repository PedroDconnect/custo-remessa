import os
import requests
import pandas as pd
import duckdb
from datetime import datetime

URL = "https://connectvending144155.protheus.cloudtotvs.com.br:1607/rest/WS_ETIQUETAS/ETIQUETAS"

USER = os.getenv("PROTHEUS_USER")
PASSWORD = os.getenv("PROTHEUS_PASSWORD")

if not USER or not PASSWORD:
    raise Exception("PROTHEUS_USER ou PROTHEUS_PASSWORD não configurados.")

hoje = datetime.now()
periodo_atual = hoje.strftime("%Y%m")

params = {
    "filial": "01",
    "perini": periodo_atual,
    "perfim": periodo_atual,
    "page": 1,
    "pageSize": 13500
}

print(f"Buscando período: {periodo_atual}")

todos_registros = []

while True:
    print(f"Buscando página {params['page']}...")

    response = requests.get(
        URL,
        params=params,
        auth=(USER, PASSWORD),
        timeout=180
    )

    response.raise_for_status()

    json_data = response.json()

    registros = json_data.get("etiquetas", [])

    if not registros:
        print("Nenhum registro retornado.")
        break

    print(f"Registros recebidos nesta página: {len(registros)}")

    todos_registros.extend(registros)

    if len(registros) < params["pageSize"]:
        break

    params["page"] += 1

print(f"Total recebido da API: {len(todos_registros)}")

if not todos_registros:
    print("Nada para processar.")
    exit()

df = pd.DataFrame(todos_registros)

# Limpar espaços do Protheus
colunas_texto = [
    "filial",
    "etq_cod",
    "etq_cli_nome",
    "etq_prod_desc",
    "etq_tracking",
    "etq_documento",
    "etq_serie",
    "etq_usuario_nome",
    "periodo"
]

for coluna in colunas_texto:
    if coluna in df.columns:
        df[coluna] = df[coluna].astype(str).str.strip()

# Converter data
if "etq_data" in df.columns:
    df["etq_data"] = pd.to_datetime(
        df["etq_data"],
        format="%Y%m%d",
        errors="coerce"
    )

# Garantir quantidade numérica
if "etq_qtde" in df.columns:
    df["etq_qtde"] = pd.to_numeric(
        df["etq_qtde"],
        errors="coerce"
    )

# Remover duplicações exatas
df = df.drop_duplicates()

os.makedirs("data", exist_ok=True)

arquivo = f"data/etiquetas_{periodo_atual}.parquet"

con = duckdb.connect()

con.register("etiquetas_df", df)

con.execute(f"""
    COPY (
        SELECT *
        FROM etiquetas_df
    )
    TO '{arquivo}'
    (
        FORMAT PARQUET,
        COMPRESSION ZSTD
    )
""")

con.close()

print(f"Arquivo criado: {arquivo}")
print(f"Total final de registros: {len(df)}")
print("Processamento concluído com sucesso.")
