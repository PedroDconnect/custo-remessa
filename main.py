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

periodo_inicio = "202606"
periodo_fim = hoje.strftime("%Y%m")

params = {
    "filial": "01",
    "perini": periodo_inicio,
    "perfim": periodo_fim,
    "page": 1,
    "pageSize": 13500
}

print(f"Buscando período: {periodo_inicio} até {periodo_fim}")

todos_registros = []

# ============================================================
# BUSCAR DADOS DA API
# ============================================================

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


# ============================================================
# LIMPAR TEXTOS DO PROTHEUS
# ============================================================

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
        df[coluna] = (
            df[coluna]
            .astype(str)
            .str.strip()
        )


# ============================================================
# CONVERTER DATA
# ============================================================

if "etq_data" in df.columns:
    df["etq_data"] = pd.to_datetime(
        df["etq_data"],
        format="%Y%m%d",
        errors="coerce"
    )


# ============================================================
# FILTRAR DE 01/06/2026 ATÉ HOJE
# ============================================================

if "etq_data" in df.columns:
    data_inicio = pd.Timestamp("2026-06-01")
    data_fim = pd.Timestamp(hoje.date())

    df = df[
        (df["etq_data"] >= data_inicio) &
        (df["etq_data"] <= data_fim)
    ]

print(f"Registros após filtro de data: {len(df)}")


# ============================================================
# GARANTIR QUANTIDADE NUMÉRICA
# ============================================================

if "etq_qtde" in df.columns:
    df["etq_qtde"] = pd.to_numeric(
        df["etq_qtde"],
        errors="coerce"
    )


# ============================================================
# EXTRAIR CÓDIGO DO PRODUTO DA DESCRIÇÃO
#
# Exemplo:
# I112101201 - CHOCOLATE QUENTE
# vira:
# I112101201
# ============================================================

if "etq_prod_desc" in df.columns:
    df["codigo_produto"] = (
        df["etq_prod_desc"]
        .astype(str)
        .str.extract(
            r"^\s*([A-Za-z0-9]+)\s*-",
            expand=False
        )
        .str.strip()
        .str.upper()
    )


# ============================================================
# REMOVER DUPLICAÇÕES EXATAS DA API
# ============================================================

df = df.drop_duplicates()

print(f"Registros após remoção de duplicados: {len(df)}")


# ============================================================
# CARREGAR TABELA DE CUSTOS
# ============================================================

arquivo_custos = "data/produtos_custos.csv"

if not os.path.exists(arquivo_custos):
    raise Exception(
        f"Arquivo de custos não encontrado: {arquivo_custos}"
    )

custos = pd.read_csv(
    arquivo_custos,
    dtype={"codigo": str}
)

# Limpar nomes das colunas
custos.columns = (
    custos.columns
    .str.strip()
    .str.lower()
)

colunas_obrigatorias = [
    "codigo",
    "produto",
    "valor"
]

for coluna in colunas_obrigatorias:
    if coluna not in custos.columns:
        raise Exception(
            f"Coluna obrigatória '{coluna}' não existe em produtos_custos.csv"
        )


# ============================================================
# LIMPAR CÓDIGOS DA TABELA DE CUSTOS
# ============================================================

custos["codigo"] = (
    custos["codigo"]
    .astype(str)
    .str.strip()
    .str.upper()
)

custos["produto"] = (
    custos["produto"]
    .astype(str)
    .str.strip()
)


# ============================================================
# CONVERTER VALOR PARA NÚMERO
# ============================================================

custos["valor"] = pd.to_numeric(
    custos["valor"],
    errors="coerce"
)


# ============================================================
# REMOVER LINHAS SEM CÓDIGO
#
# Produtos com código "-" não conseguem ser relacionados
# automaticamente com a API.
# ============================================================

custos = custos[
    (~custos["codigo"].isin(["-", "—", "", "NAN", "NONE"])) &
    (custos["codigo"].notna())
].copy()


# ============================================================
# VALIDAR CÓDIGOS DUPLICADOS
# ============================================================

duplicados = custos[
    custos.duplicated(
        subset=["codigo"],
        keep=False
    )
]

if not duplicados.empty:
    print("")
    print("====================================================")
    print("ERRO: CÓDIGOS DUPLICADOS NA TABELA DE CUSTOS")
    print("====================================================")

    print(
        duplicados[
            ["codigo", "produto", "valor"]
        ]
        .sort_values("codigo")
        .to_string(index=False)
    )

    raise Exception(
        "Existem códigos duplicados em data/produtos_custos.csv. "
        "Deve existir apenas um valor por código."
    )


# ============================================================
# CRUZAR API COM TABELA DE CUSTOS
# ============================================================

df = df.merge(
    custos[
        [
            "codigo",
            "produto",
            "valor"
        ]
    ],
    how="left",
    left_on="codigo_produto",
    right_on="codigo"
)


# ============================================================
# RENOMEAR COLUNAS
# ============================================================

df = df.rename(
    columns={
        "produto": "produto_custo",
        "valor": "valor_unitario"
    }
)


# Código da tabela auxiliar não é mais necessário
if "codigo" in df.columns:
    df = df.drop(columns=["codigo"])


# ============================================================
# CALCULAR CUSTO DA REMESSA
# ============================================================

df["custo_remessa"] = (
    df["etq_qtde"] *
    df["valor_unitario"]
)


# ============================================================
# VERIFICAR PRODUTOS SEM CUSTO CADASTRADO
# ============================================================

sem_custo = df[
    df["valor_unitario"].isna()
]

print("")
print("====================================================")
print("RESUMO DO CRUZAMENTO DE CUSTOS")
print("====================================================")

print(f"Total de registros: {len(df)}")
print(
    f"Registros com custo encontrado: "
    f"{df['valor_unitario'].notna().sum()}"
)
print(
    f"Registros sem custo encontrado: "
    f"{df['valor_unitario'].isna().sum()}"
)

if not sem_custo.empty:

    produtos_sem_custo = (
        sem_custo[
            [
                "codigo_produto",
                "etq_prod_desc"
            ]
        ]
        .drop_duplicates()
        .sort_values(
            by="codigo_produto",
            na_position="last"
        )
    )

    print("")
    print("Produtos sem custo cadastrado:")

    print(
        produtos_sem_custo
        .to_string(index=False)
    )


# ============================================================
# CRIAR PASTA DATA
# ============================================================

os.makedirs(
    "data",
    exist_ok=True
)


# ============================================================
# GERAR PARQUET
# ============================================================

arquivo = "data/etiquetas_historico.parquet"

con = duckdb.connect()

con.register(
    "etiquetas_df",
    df
)

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


# ============================================================
# FINALIZAÇÃO
# ============================================================

print("")
print("====================================================")
print("PROCESSAMENTO CONCLUÍDO")
print("====================================================")

print(f"Arquivo criado: {arquivo}")
print(f"Total final de registros: {len(df)}")

print(
    f"Custo total calculado: "
    f"R$ {df['custo_remessa'].sum():,.2f}"
)

print("Processamento concluído com sucesso.")
