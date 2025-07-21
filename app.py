# -*- coding: utf-8 -*-
# -----------------------------------------------------------------
# Bot de Vendas para Discord - Adaptado para Render.com
# -----------------------------------------------------------------

# --- Bibliotecas Padrão e de Terceiros ---
import os
import io
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Flask para o servidor web e requests para chamadas HTTP
from flask import Flask, request, jsonify
import requests

# PyNaCl para verificação de assinatura do Discord
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# Discord.py para objetos como Embeds e Cores
from discord import Embed, Color

# Supabase para o banco de dados
from supabase import create_client, Client

# Matplotlib para gerar o gráfico do dashboard
import matplotlib
matplotlib.use('Agg') # Importante para rodar em ambiente sem tela
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- Configuração do App Flask ---
# Este objeto 'app' será o ponto de entrada para o Render
app = Flask(__name__)

# --- Carregamento de Variáveis de Ambiente ---
# No Render, configure estas variáveis no painel do seu projeto.
try:
    DISCORD_BOT_TOKEN = os.environ['DISCORD_BOT_TOKEN']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    ADMIN_ROLE_ID = int(os.environ['ADMIN_ROLE_ID'])
    # Chave pública do seu App no Portal de Desenvolvedor do Discord
    DISCORD_PUBLIC_KEY = os.environ['DISCORD_PUBLIC_KEY']
except KeyError as e:
    raise RuntimeError(f"ERRO: A variável de ambiente '{e.args[0]}' não foi definida no Render.")

# --- Conexões e Clientes ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
BASE_DISCORD_API_URL = "https://discord.com/api/v10"

# --- Definição dos Produtos (sem alterações) ---
PRODUTOS = {
    "bot_musica": {
        "id": "bot_musica",
        "name": "Bot de Música Avançado",
        "description": "Um bot completo para tocar músicas do YouTube e Spotify com alta qualidade.",
        "price_display": "R$ 50,00",
        "price_value": 50.00,
        "image_url": "https://i.imgur.com/r7ovmwr.png",
        "payment_link": "https://link.mercadopago.com.br/SEU_LINK_AQUI_1",
        "download_link": "https://github.com/SEU_USUARIO/SEU_REPOSITORIO_MUSICA/archive/refs/heads/main.zip"
    },
    "bot_moderacao": {
        "id": "bot_moderacao",
        "name": "Bot de Moderação Inteligente",
        "description": "Modere seu servidor com comandos automáticos, filtros e sistema de avisos.",
        "price_display": "R$ 75,00",
        "price_value": 75.00,
        "image_url": "https://i.imgur.com/zZqY2c2.png",
        "payment_link": "https://link.mercadopago.com.br/SEU_LINK_AQUI_2",
        "download_link": "https://github.com/SEU_USUARIO/SEU_REPOSITORIO_MODERACAO/archive/refs/heads/main.zip"
    },
    "bot_economia": {
        "id": "bot_economia",
        "name": "Bot de Economia Global",
        "description": "Sistema de economia com lojas, trabalhos e ranking para engajar seus membros.",
        "price_display": "R$ 40,00",
        "price_value": 40.00,
        "image_url": "https://i.imgur.com/T2yS1xQ.png",
        "payment_link": "https://link.mercadopago.com.br/SEU_LINK_AQUI_3",
        "download_link": "https://github.com/SEU_USUARIO/SEU_REPOSITORIO_ECONOMIA/archive/refs/heads/main.zip"
    }
}

# --- Funções Auxiliares (sem alterações) ---
def create_dashboard_image(completed_orders: list) -> io.BytesIO:
    sales_by_day = defaultdict(int)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=30)

    for order in completed_orders:
        created_at = datetime.fromisoformat(order['created_at'].replace('Z', '+00:00'))
        if start_date <= created_at <= end_date:
            day = created_at.date()
            sales_by_day[day] += 1

    dates = [start_date.date() + timedelta(days=i) for i in range(31)]
    sales = [sales_by_day[day] for day in dates]
    total_sales = len(completed_orders)
    total_revenue = sum(PRODUTOS[order['product_id']]['price_value'] for order in completed_orders if order['product_id'] in PRODUTOS)

    plt.style.use('dark_background')
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']

    fig, ax = plt.subplots(figsize=(12, 7), dpi=120)
    fig.patch.set_facecolor('#23272A')
    ax.set_facecolor('#2C2F33')

    ax.bar(dates, sales, color='#5865F2', label='Vendas por Dia', edgecolor='#FFFFFF', linewidth=0.5, zorder=2)
    ax.grid(axis='y', color='white', linestyle=':', linewidth=0.5, alpha=0.3, zorder=1)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    plt.xticks(color='white', fontsize=10)
    plt.yticks(color='white', fontsize=10)

    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)
    for spine in ['left', 'bottom']:
        ax.spines[spine].set_color('#FFFFFF')
        ax.spines[spine].set_linewidth(0.8)

    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')

    fig.suptitle('Dashboard de Vendas', fontsize=22, color='white', weight='bold', y=0.95)
    ax.set_title('Desempenho nos Últimos 30 Dias', fontsize=14, color='#B9BBBE', pad=15)
    
    formatted_revenue = f"R$ {total_revenue:,.2f}".replace(',', 'v').replace('.', ',').replace('v', '.')
    
    props = dict(boxstyle='round,pad=0.5', facecolor='#23272A', alpha=0.9, edgecolor='none')
    ax.text(0.02, 0.95, f"Receita Total: {formatted_revenue}\nTotal de Vendas: {total_sales}",
            transform=ax.transAxes, fontsize=12, verticalalignment='top', color='white', bbox=props)

    plt.tight_layout(rect=[0, 0, 1, 0.9])
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# --- Lógica de Resposta para o Discord (Funções que geram JSON) ---

def build_catalog_response(page: int = 0):
    """Cria a resposta JSON para o comando /comprar."""
    products_list = list(PRODUTOS.values())
    if not products_list:
        return {"type": 4, "data": {"content": "ℹ️ Nenhum produto no catálogo no momento.", "flags": 64}}

    page = max(0, min(page, len(products_list) - 1))
    product = products_list[page]

    embed = Embed(title=product['name'], color=Color.from_str("#5865F2"))
    embed.add_field(name="💰 Preço", value=f"**`{product['price_display']}`**", inline=True)
    embed.add_field(name="📦 O que você recebe?", value="Código-fonte completo", inline=True)
    embed.add_field(name="📄 Descrição", value=product['description'], inline=False)
    embed.set_image(url=product['image_url'])
    embed.set_footer(text=f"Página {page + 1} de {len(products_list)}")

    components = [{
        "type": 1,
        "components": [
            {"type": 2, "style": 3, "label": "Comprar este Item", "emoji": {"name": "🛒"}, "custom_id": f"buy_{product['id']}"},
        ]
    }, {
        "type": 1,
        "components": [
            {"type": 2, "style": 2, "emoji": {"name": "⬅️"}, "custom_id": f"catalog_prev_{page}", "disabled": page == 0},
            {"type": 2, "style": 2, "emoji": {"name": "➡️"}, "custom_id": f"catalog_next_{page}", "disabled": page == len(products_list) - 1},
        ]
    }]

    return {"embeds": [embed.to_dict()], "components": components, "flags": 64}

# --- Ponto de Entrada Principal da API ---

# Rota de health check para o Render saber que o app está vivo
@app.route('/')
def home():
    return "O bot de vendas está operando e pronto para receber interações."

@app.route('/interactions', methods=['POST'])
def interactions():
    """Rota principal que recebe os webhooks do Discord."""
    # 1. Verificação de Assinatura
    signature = request.headers.get('X-Signature-Ed25519')
    timestamp = request.headers.get('X-Signature-Timestamp')
    body = request.data.decode('utf-8')

    if signature is None or timestamp is None:
        return 'Missing signature headers', 401

    try:
        verify_key.verify(f'{timestamp}{body}'.encode(), bytes.fromhex(signature))
    except BadSignatureError:
        app.logger.warning("Verificação de assinatura inválida.")
        return 'Invalid request signature', 401

    # 2. Processamento da Interação
    interaction = request.json
    interaction_type = interaction['type']
    
    # 2.1. Ping-Pong para verificação da URL
    if interaction_type == 1: # PING
        return jsonify({'type': 1}) # PONG

    # 2.2. Comando de Barra
    if interaction_type == 2: # APPLICATION_COMMAND
        command_data = interaction['data']
        command_name = command_data['name']

        if command_name == "comprar":
            response_data = build_catalog_response()
            return jsonify({"type": 4, "data": response_data}) # CH_MESSAGE_WITH_SOURCE

    # 2.3. Clique em Componente (Botão)
    if interaction_type == 3: # MESSAGE_COMPONENT
        component_data = interaction['data']
        custom_id = component_data['custom_id']

        # Lógica do catálogo
        if custom_id.startswith("catalog_"):
            parts = custom_id.split('_')
            action = parts[1]
            current_page = int(parts[2])
            
            new_page = current_page
            if action == "next":
                new_page += 1
            elif action == "prev":
                new_page -= 1
            
            response_data = build_catalog_response(new_page)
            # Para cliques em botões, o tipo de resposta é 7 (atualizar mensagem)
            return jsonify({"type": 7, "data": response_data}) # UPDATE_MESSAGE

    # Resposta padrão para interações não tratadas
    return jsonify({'type': 4, 'data': {'content': 'Interação não implementada.', 'flags': 64}})
