# -*- coding: utf-8 -*-
"""
Aplicativo Streamlit para o Agente Financeiro Pessoal com IA.
Fornece uma interface web para coletar dados, executar a análise
e exibir os resultados, incluindo o link para a planilha Google Sheets.

Para rodar localmente no Visual Studio Code:
1. Siga as instruções no README.md para configurar seu ambiente.
2. Certifique-se de que o arquivo JSON das credenciais do Google Sheets está no caminho correto.
   ATUALIZE A VARIÁVEL SERVICE_ACCOUNT_KEY_FILE ABAIXO.
3. Certifique-se de que seu arquivo .env com GOOGLE_API_KEY está na raiz do projeto.
4. No terminal do VS Code, com o ambiente virtual ativado, execute:
   streamlit run seu_app.py
5. Em outro terminal, inicie o ngrok (veja README.md para detalhes de autenticação):
   ngrok http 8501
"""

import sys
import os
import google.generativeai as genai
from dotenv import load_dotenv # Para ler do arquivo .env
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st # Importa a biblioteca Streamlit
import pandas as pd # Importado aqui para garantir que esteja disponível para DataFrames
import json # <--- ADICIONE ESTA LINHA: Importa o módulo json

# DEFINIÇÃO DA VARIÁVEL SCOPE
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']


# --- Estrutura de Dados do Usuário ---
class DadosFinanceirosUsuario:
    def __init__(self):
        self.email_pessoal_usuario = ""
        self.renda_liquida_mensal = 0.0
        self.fonte_renda = ""
        self.gastos_por_categoria = {}
        self.patrimonio = {}
        self.dividas = []
        self.dependentes = 0
        self.estabilidade_financeira = ""

        # Resultados da análise numérica (Etapa 2)
        self.total_gastos_mensais = 0.0
        self.total_gastos_essenciais = 0.0
        self.classificacao_gastos = {} # Mantido para a lógica de essenciais/supérfluos
        self.status_fluxo_caixa = ""
        self.saldo_mensal = 0.0

        # Resultados do planejamento da reserva (Etapa 4)
        self.valor_reserva_emergencia_ideal = 0.0
        self.meses_reserva_sugerido = 0
        self.saldo_mensal_para_reserva = 0.0
        self.tempo_para_montar_reserva_meses = 0.0
        self.meta_mensal_reserva = 0.0

        # Resultados do acompanhamento e reforço (Etapa 5)
        self.relatorio_mensal_simulado = ""
        self.feedback_ia_comportamento = ""

    # O método __str__ não é usado diretamente no Streamlit para exibição
    # mas mantido para depuração se necessário.
    def __str__(self):
        resumo = (f"--- Resumo dos Dados Coletados e Análise ---\n"
                  f"Email do Usuário: {self.email_pessoal_usuario}\n"
                  f"Renda Líquida Mensal: R$ {self.renda_liquida_mensal:.2f}\n"
                  f"Total de Gastos Mensais: R$ {self.total_gastos_mensais:.2f}\n"
                  f"Total de Gastos Essenciais: R$ {self.total_gastos_essenciais:.2f}\n"
                  f"Saldo Mensal: R$ {self.saldo_mensal:.2f}\n"
                  f"Status do Fluxo de Caixa: {self.status_fluxo_caixa}\n"
                  f"--- Planejamento da Reserva de Emergência ---\n"
                  f"Valor Ideal da Reserva: R$ {self.valor_reserva_emergencia_ideal:.2f} ({self.meses_reserva_sugerido} meses de gastos essenciais)\n"
                  f"Saldo Mensal Disponível para Reserva: R$ {self.saldo_mensal_para_reserva:.2f}\n"
                  f"Tempo Estimado para Montar a Reserva: {self.tempo_para_montar_reserva_meses:.1f} meses" if self.tempo_para_montar_reserva_meses != float('inf') else "Saldo insuficiente para iniciar",
                  f"Meta Mensal Sugerida para Reserva: R$ {self.meta_mensal_reserva:.2f}\n"
                  f"--- Relatório Mensal Simulado ---\n{self.relatorio_mensal_simulado}\n"
                  f"--- Análise e Recomendações da IA (Comportamento) ----\n{self.feedback_ia_comportamento}\n"
                  f"---------------------------------")
        return resumo

# --- Funções de Processamento (Adaptadas para receber dados dos widgets Streamlit) ---

def processar_dados_streamlit(email, renda, fonte_renda, dependentes, estabilidade, gastos_dict, patrimonio_dict, dividas_list):
    """
    Processa os dados recebidos dos widgets Streamlit e popula o objeto DadosFinanceirosUsuario.
    """
    dados_usuario = DadosFinanceirosUsuario()

    dados_usuario.email_pessoal_usuario = email
    dados_usuario.renda_liquida_mensal = renda
    dados_usuario.fonte_renda = fonte_renda
    dados_usuario.dependentes = dependentes
    dados_usuario.estabilidade_financeira = estabilidade
    dados_usuario.gastos_por_categoria = {k: v for k, v in gastos_dict.items() if v > 0} # Inclui apenas gastos > 0
    dados_usuario.patrimonio = {k: v for k, v in patrimonio_dict.items() if v > 0} # Inclui apenas patrimônio > 0
    dados_usuario.dividas = dividas_list

    # Classificação padrão (mantida para a lógica interna de essenciais/supérfluos)
    classificacao_padrao = {
        'Moradia (Aluguel)': {'tipo': 'Essencial', 'natureza': 'Fixo'},
        'Alimentação': {'tipo': 'Essencial', 'natureza': 'Variável'},
        'Transporte (Carro, Transporte Público, Uber...)': {'tipo': 'Essencial', 'natureza': 'Variável'},
        'Saúde': {'tipo': 'Essencial', 'natureza': 'Variável'},
        'Educação': {'tipo': 'Essencial', 'natureza': 'Fixo'},
        'Lazer': {'tipo': 'Supérfluo', 'natureza': 'Variável'},
        'Assinaturas': {'tipo': 'Supérfluo', 'natureza': 'Fixo'},
        'Contas de Consumo (água, luz, gás)': {'tipo': 'Essencial', 'natureza': 'Variável'},
        'Outros (Cabelo, Estética...)': {'tipo': 'Variável', 'natureza': 'Variável'}
    }
    dados_usuario.classificacao_gastos = {
        cat: classificacao_padrao.get(cat, {'tipo': 'Variável', 'natureza': 'Variável'})
        for cat in dados_usuario.gastos_por_categoria.keys() # Usa as chaves dos gastos efetivamente incluídos
    }

    return dados_usuario


# --- Funções de Análise, Planejamento, Relatório e Planilha (Mantidas - operam no objeto) ---

def gerar_analise_ia(dados_usuario, model_ia): # Recebe o modelo da IA
    """Usa modelo de IA para análise qualitativa."""
    # st.info("Gerando Análise Inteligente da IA (aguarde)...") # Feedback visual no Streamlit

    prompt_parts = [
        """Você é um consultor financeiro altamente experiente, com mais de 7 anos de experiência de mercado, e empático. Sua tarefa é analisar a situação financeira de um indivíduo e fornecer um diagnóstico claro, personalizado
         e acionável em português do Brasil. Com base nos dados fornecidos, identifique os principais pontos fortes e fracos, os maiores desafios e as oportunidades. Ofereça sugestões gerais para os próximos passos,
         incentivando o usuário a tomar ações positivas. Seja direto, mas compreensivo. Use linguagem fácil de entender, evitando jargões excessivos, mas mantendo a profundidade da análise e procure não enrolar muito,
         procure ser sucinto . Não use markdown no output.

         Inclua feedback sobre o progresso em relação à reserva de emergência (se aplicável) e sugestões concretas para otimizar gastos ou acelerar a quitação de dívidas, se necessário. Baseie as sugestões nos dados de gastos fornecidos.
         Exemplos de sugestões: "Considere reduzir seus gastos com Lazer em X R$/mês", "Priorize a quitação da dívida de [Tipo da Dívida]".
         Se o usuário estiver em superávit e no caminho para a reserva, reforce o comportamento positivo e sugira manter o foco.
         
         Mas se o usuário estiver com a conta no vermelho indique também caminhos e estrategia que ele pode adotar para melhorar seu saldo, como também dicas de renda extra (algo simples e que grande parte das pessoas poderia fazer
         ou algo relacionado a sua área de atuação a qual o usuário pertence), para ter uma alternativa a mais e melhorar sua renda.

         
         """,
        "\n--- Dados Financeiros do Usuário ---",
        f"Renda Líquida Mensal: R$ {dados_usuario.renda_liquida_mensal:.2f}",
        f"Fonte de Renda: {dados_usuario.fonte_renda}",
        f"Dependentes: {dados_usuario.dependentes}",
        f"Estabilidade Financeira: {dados_usuario.estabilidade_financeira}",
        "\nGastos por Categoria:",
    ]
    if dados_usuario.gastos_por_categoria:
        for categoria, valor in dados_usuario.gastos_por_categoria.items():
            classif = dados_usuario.classificacao_gastos.get(categoria, {'tipo': 'N/A', 'natureza': 'N/A'})
            prompt_parts.append(f"- {categoria}: R$ {valor:.2f} (Tipo: {classif['tipo']}, Natureza: {classif['natureza']})")
    else:
        prompt_parts.append("- Nenhum gasto informado.")


    prompt_parts.append("\nSituação Patrimonial:")
    if not dados_usuario.patrimonio:
        prompt_parts.append("- Nenhum patrimônio informado.")
    else:
        for bem, valor in dados_usuario.patrimonio.items():
            prompt_parts.append(f"- {bem}: R$ {valor:.2f}")

    prompt_parts.append("\nDívidas Existentes:")
    if not dados_usuario.dividas:
        prompt_parts.append("- Nenhuma dívida informada.")
    else:
        for divida in dados_usuario.dividas:
            prompt_parts.append(f"- Tipo: {divida['tipo']}, Valor Restante: R$ {divida['valor_restante']:.2f}, Taxa Juros Anual: {divida['taxa_juros_anual']:.2%}, Parcelas Restantes: {divida['parcelas_restantes']}/{divida['parcelas_totais']}")

    prompt_parts.append(f"\n--- Resumo Numérico (Já Calculado) ---")
    prompt_parts.append(f"Total de Gastos Mensais: R$ {dados_usuario.total_gastos_mensais:.2f}")
    prompt_parts.append(f"Total de Gastos Essenciais: R$ {dados_usuario.total_gastos_essenciais:.2f}")
    prompt_parts.append(f"Saldo Mensal (Renda - Gastos): R$ {dados_usuario.saldo_mensal:.2f}")
    prompt_parts.append(f"Status do Fluxo de Caixa: {dados_usuario.status_fluxo_caixa}")

    prompt_parts.append(f"\n--- Planejamento da Reserva de Emergência (Já Calculado) ---")
    prompt_parts.append(f"Valor Ideal da Reserva de Emergência: R$ {dados_usuario.valor_reserva_emergencia_ideal:.2f} ({dados_usuario.meses_reserva_sugerido} meses de gastos essenciais)")
    prompt_parts.append(f"Saldo Mensal Disponível para Construir a Reserva: R$ {dados_usuario.saldo_mensal_para_reserva:.2f}")
    prompt_parts.append(f"Tempo Estimado para Montar a Reserva (se possível): {dados_usuario.tempo_para_montar_reserva_meses:.1f} meses")
    prompt_parts.append(f"Meta Mensal Sugerida para Reserva: R$ {dados_usuario.meta_mensal_reserva:.2f}")

    prompt_parts.append("\n--- Progresso Atual (Baseado no Saldo Mensal e Meta) ---")
    if dados_usuario.saldo_mensal > 0 and dados_usuario.meta_mensal_reserva > 0:
        prompt_parts.append(f"Com o saldo atual de R$ {dados_usuario.saldo_mensal:.2f} e meta mensal de R$ {dados_usuario.meta_mensal_reserva:.2f}, você está no caminho para construir a reserva.")
    elif dados_usuario.saldo_mensal <= 0:
         prompt_parts.append("Seu saldo mensal não permite acumular para a reserva no momento.")


    full_prompt = "\n".join(prompt_parts)
    try:
        response = model_ia.generate_content(full_prompt) # Usa o modelo passado como argumento
        return response.text
    except Exception as e:
        st.error(f"Erro ao chamar a IA Generativa: {e}")
        return "Não foi possível gerar uma análise detalhada da IA neste momento."


def analisar_fluxo_caixa(dados_usuario):
    """Calcula totais e status do fluxo de caixa."""
    dados_usuario.total_gastos_mensais = sum(dados_usuario.gastos_por_categoria.values())

    dados_usuario.total_gastos_essenciais = sum(
        valor for categoria, valor in dados_usuario.gastos_por_categoria.items()
        if dados_usuario.classificacao_gastos.get(categoria, {}).get('tipo') == 'Essencial'
    )

    dados_usuario.saldo_mensal = dados_usuario.renda_liquida_mensal - dados_usuario.total_gastos_mensais

    if dados_usuario.saldo_mensal > 0:
        dados_usuario.status_fluxo_caixa = "Superavitário"
    elif dados_usuario.saldo_mensal < 0:
        dados_usuario.status_fluxo_caixa = "Deficitário"
    else:
        dados_usuario.status_fluxo_caixa = "Equilibrado"


def planejar_reserva_emergencia(dados_usuario):
    """Planeja a reserva de emergência."""
    meses_sugerido = 6
    if dados_usuario.estabilidade_financeira.lower() in ['autônomo', 'informal']:
        meses_sugerido = 12

    dados_usuario.meses_reserva_sugerido = meses_sugerido
    dados_usuario.valor_reserva_emergencia_ideal = dados_usuario.total_gastos_essenciais * meses_sugerido

    dados_usuario.saldo_mensal_para_reserva = max(0, dados_usuario.saldo_mensal)

    if dados_usuario.saldo_mensal_para_reserva > 0:
        if dados_usuario.saldo_mensal_para_reserva > 0:
            dados_usuario.tempo_para_montar_reserva_meses = dados_usuario.valor_reserva_emergencia_ideal / dados_usuario.saldo_mensal_para_reserva
        else:
             dados_usuario.tempo_para_montar_reserva_meses = float('inf')

        dados_usuario.meta_mensal_reserva = dados_usuario.saldo_mensal_para_reserva

    else:
        dados_usuario.tempo_para_montar_reserva_meses = float('inf')
        dados_usuario.meta_mensal_reserva = 0.0


def gerar_relatorio_mensal_simulado(dados_usuario):
    """Simula a geração de relatório textual."""
    relatorio_parts = [
        "--- Relatório Mensal de Acompanhamento Financeiro ---",
        f"Período: Análise Inicial",
        f"Status do Fluxo de Caixa: {dados_usuario.status_fluxo_caixa}",
        f"Saldo Mensal: R$ {dados_usuario.saldo_mensal:.2f}",
        "",
        "Resumo de Gastos:",
        f"Total Geral: R$ {dados_usuario.total_gastos_mensais:.2f}",
        f"Total Essenciais: R$ {dados_usuario.total_gastos_essenciais:.2f}",
        f"Total Supérfluos: R$ {dados_usuario.total_gastos_mensais - dados_usuario.total_gastos_essenciais:.2f}",
        "",
        "Situação da Reserva de Emergência:",
        f"Valor Ideal: R$ {dados_usuario.valor_reserva_emergencia_ideal:.2f}",
        f"Meta Mensal para Construção: R$ {dados_usuario.meta_mensal_reserva:.2f}",
        f"Tempo Estimado para Atingir: {dados_usuario.tempo_para_montar_reserva_meses:.1f} meses" if dados_usuario.tempo_para_montar_reserva_meses != float('inf') else "Saldo insuficiente para iniciar",
        "",
        "Análise e Recomendações da IA:",
        dados_usuario.feedback_ia_comportamento
    ]
    dados_usuario.relatorio_mensal_simulado = "\n".join(relatorio_parts)


def gerar_feedback_comportamento_ia(dados_usuario, model_ia): # Recebe o modelo da IA
    """Invoca a IA para feedback de comportamento."""
    dados_usuario.feedback_ia_comportamento = gerar_analise_ia(dados_usuario, model_ia)


def gerar_planilha_google_sheets(dados_usuario, client_sheets, sheet_name="Meu_Painel_Financeiro_IA"): # Recebe o cliente do Sheets
    """Cria/atualiza planilha e compartilha."""
    if client_sheets is None:
        st.error("Não foi possível gerar a planilha Google Sheets. O cliente da API não foi autenticado.")
        return None

    #st.info(f"Tentando gerar/atualizar Painel Interativo no Google Sheets ({sheet_name})...")
    spreadsheet = None
    try:
        try:
            spreadsheet = client_sheets.open(sheet_name)
            #st.info(f"Planilha '{sheet_name}' encontrada. Atualizando...")
        except gspread.exceptions.SpreadsheetNotFound:
            st.warning(f"Planilha '{sheet_name}' não encontrada. Criando nova planilha...")
            try:
                spreadsheet = client_sheets.create(sheet_name)
                st.success(f"Planilha '{sheet_name}' criada com sucesso.")
            except Exception as create_error:
                st.error(f"ERRO GRAVE: Falha ao criar a planilha '{sheet_name}'.")
                st.error(f"Detalhes do erro de criação: {create_error}")
                st.warning("Causas comuns: Permissões insuficientes da conta de serviço no Google Drive para criar arquivos.")
                return None

        if dados_usuario.email_pessoal_usuario:
            try:
                spreadsheet.share(dados_usuario.email_pessoal_usuario, perm_type='user', role='writer')
                st.success(f"Planilha enviada com sucesso para o e-mail: {dados_usuario.email_pessoal_usuario}.")
            except Exception as share_error:
                st.warning(f"AVISO: Não foi possível compartilhar a planilha com {dados_usuario.email_pessoal_usuario}.")
                st.warning(f"Detalhes do erro de compartilhamento: {share_error}")
                st.info("Causas comuns: Email inválido, permissões insuficientes da conta de serviço para compartilhar.")
        else:
            st.info("AVISO: Email pessoal do usuário não fornecido. A planilha não será compartilhada automaticamente.")

        # ----- Aba de Resumo (Atualizada para incluir Reserva e Resumo Relatório) -----
        try:
            worksheet_resumo = spreadsheet.worksheet("Resumo Geral")
        except gspread.exceptions.WorksheetNotFound:
            worksheet_resumo = spreadsheet.add_worksheet(title="Resumo Geral", rows="200", cols="20")

        worksheet_resumo.clear()

        resumo_data = [
            ["Item", "Valor/Detalhe"],
            ["Renda Líquida Mensal", dados_usuario.renda_liquida_mensal],
            ["Total de Gastos Mensais", dados_usuario.total_gastos_mensais],
            ["Total de Gastos Essenciais", dados_usuario.total_gastos_essenciais],
            ["Saldo Mensal", dados_usuario.saldo_mensal],
            ["Status do Fluxo de Caixa", dados_usuario.status_fluxo_caixa],
            ["", ""],
            ["--- Reserva de Emergência ---", ""],
            ["Valor Ideal da Reserva", dados_usuario.valor_reserva_emergencia_ideal],
            [f"({dados_usuario.meses_reserva_sugerido} meses de gastos essenciais)", ""],
            ["Saldo Mensal para Reserva", dados_usuario.saldo_mensal_para_reserva],
            ["Tempo Estimado para Montar (meses)", dados_usuario.tempo_para_montar_reserva_meses if dados_usuario.tempo_para_montar_reserva_meses != float('inf') else "Saldo insuficiente"],
            ["Meta Mensal Sugerida", dados_usuario.meta_mensal_reserva],
            ["", ""],
            ["--- Relatório Mensal Simulado ---", ""],
            [dados_usuario.relatorio_mensal_simulado],
            ["", ""],
            #["--- Análise e Recomendações da IA (Comportamento) ---", ""],
            #[dados_usuario.feedback_ia_comportamento]
        ]
        worksheet_resumo.update('A1', resumo_data)

        #st.info("Aba 'Resumo Geral' atualizada com dados da análise, reserva e relatório simulado.")

        # ----- Aba de Gastos Detalhados (Mantida) -----
        try:
            worksheet_gastos = spreadsheet.worksheet("Gastos Detalhados")
        except gspread.exceptions.WorksheetNotFound:
            worksheet_gastos = spreadsheet.add_worksheet(title="Gastos Detalhados", rows="100", cols="10")

        worksheet_gastos.clear()

        gastos_header = ["Categoria", "Valor (R$)", "Tipo", "Natureza"]
        gastos_rows = [gastos_header]
        for categoria, valor in dados_usuario.gastos_por_categoria.items():
            classif = dados_usuario.classificacao_gastos.get(categoria, {'tipo': 'N/A', 'natureza': 'N/A'})
            gastos_rows.append([
                categoria,
                valor,
                classif.get('tipo', 'N/A'),
                classif.get('natureza', 'N/A')
            ])
        worksheet_gastos.update('A1', gastos_rows)
        #st.info("Aba 'Gastos Detalhados' atualizada.")

        # ----- Aba de Dívidas (Mantida) -----
        try:
            worksheet_dividas = spreadsheet.worksheet("Dívidas")
        except gspread.exceptions.WorksheetNotFound:
            worksheet_dividas = spreadsheet.add_worksheet(title="Dívidas", rows="100", cols="10")

        worksheet_dividas.clear()

        dividas_header = ["Tipo", "Valor Original (R$)", "Valor Restante (R$)", "Taxa Juros Anual (%)", "Parcelas Totais", "Parcelas Restantes"]
        dividas_rows = [dividas_header]
        for divida in dados_usuario.dividas:
            dividas_rows.append([
                divida['tipo'],
                divida['valor_original'],
                divida['valor_restante'],
                divida['taxa_juros_anual'] * 100, # Exibe como porcentagem
                divida['parcelas_totais'],
                divida['parcelas_restantes']
            ])
        if len(dividas_rows) == 1:
            dividas_rows.append(["Nenhuma dívida informada.", "", "", "", "", ""])

        worksheet_dividas.update('A1', dividas_rows)
        #st.info("Aba 'Dívidas' atualizada.")

        #st.success("Painel no Google Sheets gerado/atualizado com sucesso!")
        return spreadsheet.url

    except Exception as e:
        st.error(f"ERRO GERAL ao gerar/atualizar a planilha Google Sheets: {e}")
        st.warning("Verifique as permissões da sua conta de serviço no Google Cloud Console.")
        return None

# --- Interface Streamlit ---

def main():
    """Função principal para construir a interface Streamlit."""

    st.set_page_config(page_title="Agente Financeiro Pessoal com IA", layout="wide")

    # --- Configuração de Ambiente e APIs (MOVIDO PARA DENTRO DE MAIN) ---
    # Remova a linha load_dotenv() se ela estiver no escopo global fora de main()
    # Mantenha-a dentro do `else` do GOOGLE_API_KEY para uso local, se desejar.

    # Configuração da Google AI Key
    if 'GOOGLE_API_KEY' in st.secrets:
        GOOGLE_API_KEY = st.secrets['GOOGLE_API_KEY']
        #st.success("GOOGLE_API_KEY carregada dos Streamlit Secrets.")
    else:
        # Fallback para desenvolvimento local (lê do .env)
        load_dotenv() # Garante que o .env seja lido para ambiente local
        GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
        if not GOOGLE_API_KEY:
            st.error("ERRO: A variável de ambiente GOOGLE_API_KEY não está configurada.")
            st.warning("Defina-a no seu arquivo .env local OU nos secrets do Streamlit Cloud.")
            st.stop() # Interrompe a execução do Streamlit

    # Configura o modelo de IA
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        MODEL_IA = genai.GenerativeModel('gemini-2.0-flash')
    except Exception as e:
        st.error(f"ERRO ao configurar a API do Google Gemini: {e}")
        st.warning("Verifique se sua GOOGLE_API_KEY está correta e ativa.")
        st.stop()

    # --- Configuração do Google Sheets API ---
    CLIENT_SHEETS = None

    # Preferência por carregar as credenciais do Google Sheets via secrets no Streamlit Cloud
    if 'gcp_service_account_json' in st.secrets:
        try:
            # <--- MUDANÇA IMPORTANTE AQUI: Use json.loads() para converter a string JSON para um dicionário Python
            service_account_info = json.loads(st.secrets["gcp_service_account_json"])
            
            # Use gspread.service_account_from_dict com o dicionário parseado
            CLIENT_SHEETS = gspread.service_account_from_dict(service_account_info)
            #st.success("Autenticação com Google Sheets API via Streamlit Secrets bem-sucedida.")
        except json.JSONDecodeError as e:
            st.error(f"ERRO: O conteúdo do secret 'gcp_service_account_json' não é um JSON válido: {e}")
            st.warning("Verifique cuidadosamente a formatação do JSON no seu arquivo de secrets.")
            st.stop()
        except Exception as e:
            st.error(f"ERRO de autenticação com Google Sheets API (via secrets): {e}")
            st.warning("Verifique se o JSON em 'gcp_service_account_json' nos secrets está correto e completo.")
            st.stop()
    else:
        # Fallback para desenvolvimento local usando o arquivo JSON
        # !!! ATUALIZE ESTE CAMINHO COM O CAMINHO COMPLETO PARA O ARQUIVO JSON NO SEU SISTEMA DE ARQUIVOS !!!
        SERVICE_ACCOUNT_KEY_FILE = 'C:\\Users\\arthu\\google_sheets_key.json' # <--- MANTENHA ESTE CAMINHO LOCAL

        if not os.path.exists(SERVICE_ACCOUNT_KEY_FILE):
            st.error(f"Arquivo de credenciais não encontrado: {SERVICE_ACCOUNT_KEY_FILE}")
            st.warning("Por favor, verifique se o caminho para o arquivo JSON está correto LOCALMENTE ou configure os secrets no Streamlit Cloud.")
            st.stop() # Interrompe se o arquivo não for encontrado
        try:
            CREDS = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_KEY_FILE, SCOPE)
            CLIENT_SHEETS = gspread.authorize(CREDS)
            st.success("Autenticação com Google Sheets API localmente bem-sucedida.")
        except Exception as e:
            st.error(f"ERRO de autenticação com Google Sheets API (via arquivo): {e}")
            st.warning("Verifique se o arquivo JSON não está corrompido e se a conta de serviço está ativa.")
            st.stop()


    st.title("🤖 Agente Financeiro Pessoal com IA")
    st.markdown("✨ Transforme sua Relação com Dinheiro com a Ajuda da Inteligência Artificial! ✨")

    st.header("📊 Seus Dados Financeiros")

    # Formulário de entrada de dados
    with st.form("dados_financeiros_form"):
        st.subheader("Informações Pessoais")
        email_pessoal_usuario = st.text_input("Seu email pessoal do Google (para compartilhar a planilha):")
        renda_liquida_mensal = st.number_input("Sua renda líquida mensal (R$):", min_value=0.0, format="%.2f")
        # Label do campo de renda atualizado
        fonte_renda = st.text_input("Sua profissão / fonte(s) de renda (seja bem específico aqui):")
        dependentes = st.number_input("Número de dependentes:", min_value=0, step=1)
        estabilidade_financeira = st.selectbox(
            "Seu grau de estabilidade financeira:",
            ['CLT', 'Autônomo', 'Informal', 'Empresário', 'Aposentado', 'Outro']
        )

        st.subheader("Gastos Mensais por Categoria")
        st.info("Digite 0 para categorias sem gasto.")
        # Exemplo de categorias (adicione/remova conforme necessário)
        categorias_sugeridas = [
            'Moradia (Aluguel)', 'Alimentação', 'Transporte (Carro, Transporte Público, Uber...)', 'Saúde', 'Educação',
            'Lazer', 'Assinaturas', 'Contas de Consumo (água, luz, gás)', 'Outros (Cabelo, Estética...)'
        ]
        gastos_dict = {}
        for categoria in categorias_sugeridas:
            # Mantido 0.0 como valor inicial para number_input, é o padrão e mais robusto
            gastos_dict[categoria] = st.number_input(f"Gasto com {categoria} (R$):", value=0.0, min_value=0.0, format="%.2f", key=f"gasto_{categoria}")

        st.subheader("Situação Patrimonial")
        st.info("Digite 0 para itens sem valor.")
        bens_sugeridos = ['Imóveis', 'Veículos', 'Investimentos', 'Contas Bancárias (saldo total)', 'Outros Ativos']
        patrimonio_dict = {}
        for bem in bens_sugeridos:
             # Mantido 0.0 como valor inicial para number_input
             patrimonio_dict[bem] = st.number_input(f"Valor de {bem} (R$):", value=0.0, min_value=0.0, format="%.2f", key=f"patrimonio_{bem}")

        st.subheader("Dívida Principal (Opcional)")
        st.info("Preencha apenas se tiver uma dívida principal que deseja considerar na análise.")
        
        # Dropdown para tipo de dívida
        opcoes_divida = [
            "Selecione o tipo da dívida", # Opção padrão para "não selecionado"
            "Cartão de Crédito",
            "Empréstimo Pessoal",
            "Financiamento Imobiliário",
            "Financiamento de Veículo",
            "Cheque Especial",
            "Crédito Consignado",
            "Outro"
        ]
        divida_tipo_selecionado = st.selectbox(
            "Tipo da dívida principal:",
            opcoes_divida,
            key="divida_tipo_dropdown"
        )

        divida_tipo_especificado = ""
        # Campo de texto condicional se "Outro" for selecionado
        if divida_tipo_selecionado == "Outro":
            divida_tipo_especificado = st.text_input("Especifique o tipo da dívida:", key="divida_tipo_especificado")
            # Usa o valor especificado se "Outro" for escolhido e o campo não estiver vazio
            divida_tipo = divida_tipo_especificado if divida_tipo_especificado else "Outro (não especificado)"
        elif divida_tipo_selecionado == "Selecione o tipo da dívida":
            divida_tipo = "" # Nenhuma dívida selecionada
        else:
            divida_tipo = divida_tipo_selecionado # Usa o valor selecionado do dropdown

        dividas_list = []
        # Exibe os campos de valor da dívida apenas se um tipo de dívida válido foi selecionado
        if divida_tipo and divida_tipo != "Outro (não especificado)":
            try:
                # Mantido 0.0 como valor inicial para number_input
                divida_valor_original = st.number_input("Valor original da dívida (R$):", value=0.0, min_value=0.0, format="%.2f", key="divida_valor_original")
                divida_valor_restante = st.number_input("Valor restante da dívida (R$):", value=0.0, min_value=0.0, format="%.2f", key="divida_valor_restante")
                divida_taxa_juros_anual = st.number_input("Taxa de juros ANUAL da dívida (%):", value=0.0, min_value=0.0, format="%.2f", key="divida_taxa_juros_anual")
                divida_parcelas_totais = st.number_input("Total de parcelas da dívida:", value=0, min_value=0, step=1, key="divida_parcelas_totais")
                divida_parcelas_restantes = st.number_input("Parcelas restantes da dívida:", value=0, min_value=0, step=1, key="divida_parcelas_restantes")

                if divida_valor_restante > 0:
                     dividas_list.append({
                        'tipo': divida_tipo,
                        'valor_original': divida_valor_original,
                        'valor_restante': divida_valor_restante,
                        'taxa_juros_anual': divida_taxa_juros_anual / 100, # Converte % para decimal
                        'parcelas_totais': divida_parcelas_totais,
                        'parcelas_restantes': divida_parcelas_restantes
                     })
            except ValueError:
                 st.warning("Dados de dívida inválidos. A dívida não será incluída na análise.")


        # Botão para submeter o formulário e iniciar a análise
        submit_button = st.form_submit_button("Analisar Minhas Finanças com IA")

    # --- Execução da Análise e Exibição de Resultados ---
    if submit_button:
        # As verificações de API Key e CLIENT_SHEETS já foram feitas no início da main()
        # Se chegou aqui, as APIs estão configuradas.
        
        st.header("✨ Resultados da Análise ✨")

        # Processa os dados do formulário e popula o objeto dados_usuario
        dados_usuario = processar_dados_streamlit(
            email_pessoal_usuario,
            renda_liquida_mensal,
            fonte_renda,
            dependentes,
            estabilidade_financeira,
            gastos_dict,
            patrimonio_dict,
            dividas_list
        )

        # Executa as etapas de análise, planejamento e acompanhamento
        analisar_fluxo_caixa(dados_usuario)
        planejar_reserva_emergencia(dados_usuario)

        # Exibe o resumo numérico
        st.subheader("Resumo Numérico")
        col1, col2, col3 = st.columns(3)
        col1.metric("Renda Líquida Mensal", f"R$ {dados_usuario.renda_liquida_mensal:.2f}")
        col2.metric("Total de Gastos Mensais", f"R$ {dados_usuario.total_gastos_mensais:.2f}")
        col3.metric("Saldo Mensal", f"R$ {dados_usuario.saldo_mensal:.2f}", delta=f"{dados_usuario.status_fluxo_caixa}")

        st.subheader("Detalhes de Gastos")
        # Converte o dicionário de gastos para um DataFrame para exibição bonita no Streamlit
        if dados_usuario.gastos_por_categoria:
            gastos_df = pd.DataFrame(list(dados_usuario.gastos_por_categoria.items()), columns=['Categoria', 'Valor (R$)'])
            # Adiciona as colunas de classificação para exibição
            gastos_df['Tipo'] = gastos_df['Categoria'].apply(lambda x: dados_usuario.classificacao_gastos.get(x, {}).get('tipo', 'N/A'))
            gastos_df['Natureza'] = gastos_df['Categoria'].apply(lambda x: dados_usuario.classificacao_gastos.get(x, {}).get('natureza', 'N/A'))
            st.dataframe(gastos_df)
            st.info(f"Total de Gastos Essenciais: R$ {dados_usuario.total_gastos_essenciais:.2f}")
            st.info(f"Total de Gastos Supérfluos: R$ {dados_usuario.total_gastos_mensais - dados_usuario.total_gastos_essenciais:.2f}")
        else:
            st.info("Nenhum gasto informado.")

        st.subheader("Situação da Reserva de Emergência")
        st.info(f"Valor ideal da sua reserva de emergência ({dados_usuario.meses_reserva_sugerido} meses de gastos essenciais): R$ {dados_usuario.valor_reserva_emergencia_ideal:.2f}")
        if dados_usuario.saldo_mensal_para_reserva > 0:
             st.info(f"Com um saldo mensal disponível de R$ {dados_usuario.saldo_mensal_para_reserva:.2f}, você levaria aproximadamente {dados_usuario.tempo_para_montar_reserva_meses:.1f} meses para montar a reserva.")
             st.info(f"Meta mensal sugerida para a reserva: R$ {dados_usuario.meta_mensal_reserva:.2f}")
        else:
             st.warning("Seu saldo mensal não permite iniciar a reserva de emergência neste momento. Foque primeiro em equilibrar suas finanças.")

        st.subheader("Dívidas")
        if dados_usuario.dividas:
             dividas_df = pd.DataFrame(dados_usuario.dividas)
             # Formata a taxa de juros para exibição
             dividas_df['taxa_juros_anual'] = dividas_df['taxa_juros_anual'].apply(lambda x: f"{x:.2%}")
             st.dataframe(dividas_df)
        else:
             st.info("Nenhuma dívida informada.")


        # Gera feedback da IA
        st.subheader("Análise e Recomendações da IA")
        with st.spinner("A IA está analisando seus dados..."):
             gerar_feedback_comportamento_ia(dados_usuario, MODEL_IA) # Passa o modelo da IA
             st.write(dados_usuario.feedback_ia_comportamento)

        # Gera relatório simulado (pode ser exibido ou usado para a planilha)
        gerar_relatorio_mensal_simulado(dados_usuario)
        # st.subheader("Relatório Mensal Simulado")
        # st.text(dados_usuario.relatorio_mensal_simulado) # Exibe o relatório textual

        # Gera/atualiza a planilha Google Sheets
        planilha_url = gerar_planilha_google_sheets(dados_usuario, CLIENT_SHEETS, sheet_name="Meu_Painel_Financeiro_Pessoal_IA_Streamlit") # Passa o cliente do Sheets

        if planilha_url:
            st.subheader("Painel Interativo no Google Sheets")
            st.success(f"Seu painel foi gerado/atualizado. Acesse aqui: [Link para a Planilha]({planilha_url})")
            if dados_usuario.email_pessoal_usuario:
                 st.info(f"Um convite de compartilhamento foi enviado para {dados_usuario.email_pessoal_usuario} (se for a primeira vez).")
        else:
            st.error("Não foi possível gerar o painel no Google Sheets. Verifique as mensagens de erro acima.")

# --- Execução do Streamlit App ---
if __name__ == '__main__':
    main()

