# -*- coding: utf-8 -*-
# -----------------------------------------------------------------
# Bot de Vendas para Discord - Adaptado para Render.com (Webhook Model)
# -----------------------------------------------------------------

import os
import io
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import threading

from flask import Flask, request, jsonify
import requests
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from discord import Embed, Color
from supabase import create_client, Client

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- Configuração do App Flask ---
app = Flask(__name__)

# --- Carregamento de Variáveis de Ambiente ---
try:
    DISCORD_BOT_TOKEN = os.environ['DISCORD_BOT_TOKEN']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    ADMIN_ROLE_ID = int(os.environ['ADMIN_ROLE_ID'])
    DISCORD_PUBLIC_KEY = os.environ['DISCORD_PUBLIC_KEY']
    DISCORD_APP_ID = os.environ['DISCORD_APP_ID']
except KeyError as e:
    raise RuntimeError(f"ERRO: A variável de ambiente '{e.args[0]}' não foi definida no Render.")

# --- Conexões e Clientes ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
BASE_DISCORD_API_URL = "https://discord.com/api/v10"
AUTH_HEADERS = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}

# --- Definição dos Produtos ---
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

# --- Funções Auxiliares ---
def create_dashboard_image(completed_orders: list) -> io.BytesIO:
    sales_by_day = defaultdict(float)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=30)

    for order in completed_orders:
        created_at = datetime.fromisoformat(order['created_at'].replace('Z', '+00:00'))
        if start_date <= created_at <= end_date:
            day = created_at.date()
            product_id = order.get('product_id')
            if product_id and product_id in PRODUTOS:
                sales_by_day[day] += PRODUTOS[product_id]['price_value']

    dates = [start_date.date() + timedelta(days=i) for i in range(31)]
    sales = [sales_by_day[d] for d in dates]
    total_sales_count = len(completed_orders)
    total_revenue = sum(PRODUTOS[o['product_id']]['price_value'] for o in completed_orders if o['product_id'] in PRODUTOS)
    
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 7), dpi=120)
    fig.patch.set_facecolor('#23272A')
    ax.set_facecolor('#2C2F33')
    ax.bar(dates, sales, color='#5865F2', zorder=2)
    ax.grid(axis='y', color='white', linestyle=':', linewidth=0.5, alpha=0.3, zorder=1)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    plt.xticks(rotation=45, color='white')
    plt.yticks(color='white')
    for spine in ['top', 'right']: ax.spines[spine].set_visible(False)
    for spine in ['left', 'bottom']: ax.spines[spine].set_color('#FFFFFF')
    fig.suptitle('Dashboard de Vendas', fontsize=22, color='white', weight='bold')
    ax.set_title('Receita nos Últimos 30 Dias', fontsize=14, color='#B9BBBE', pad=20)
    formatted_revenue = f"R$ {total_revenue:,.2f}".replace(',', 'v').replace('.', ',').replace('v', '.')
    props = dict(boxstyle='round,pad=0.5', facecolor='#23272A', alpha=0.9)
    ax.text(0.02, 0.95, f"Receita Total: {formatted_revenue}\nTotal de Vendas: {total_sales_count}",
            transform=ax.transAxes, fontsize=12, verticalalignment='top', color='white', bbox=props)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    return buf

def is_admin(interaction: dict) -> bool:
    if 'member' not in interaction or 'roles' not in interaction['member']:
        return False
    return str(ADMIN_ROLE_ID) in interaction['member']['roles']

# --- Funções de Lógica de Negócio ---

def handle_buy_action(interaction: dict):
    """
    Lida com a lógica de criar uma thread de compra e envia uma resposta de acompanhamento.
    """
    token = interaction['token']
    followup_url = f"{BASE_DISCORD_API_URL}/webhooks/{DISCORD_APP_ID}/{token}/messages/@original"

    try:
        product_id = interaction['data']['custom_id'].split('_')[1]
        product = PRODUTOS.get(product_id)
        if not product:
            requests.patch(followup_url, json={"content": "❌ Produto não encontrado."})
            return

        user = interaction['member']['user']
        channel_id = interaction['channel_id']
        thread_name = f"🛒-compra-{user['username']}"

        # Cria a thread via API do Discord
        thread_url = f"{BASE_DISCORD_API_URL}/channels/{channel_id}/threads"
        thread_payload = {"name": thread_name, "type": 12, "auto_archive_duration": 1440}
        thread_res = requests.post(thread_url, headers=AUTH_HEADERS, json=thread_payload)
        thread_res.raise_for_status() # Lança um erro se a requisição falhar
        thread = thread_res.json()
        thread_id = thread['id']

        # Adiciona o usuário à thread
        requests.put(f"{BASE_DISCORD_API_URL}/channels/{thread_id}/thread-members/{user['id']}", headers=AUTH_HEADERS)

        # Insere o pedido no Supabase
        data, _ = supabase.table('pedidos').insert({
            'user_id': int(user['id']), 'user_name': user['username'],
            'product_id': product['id'], 'product_name': product['name'],
            'thread_id': int(thread_id), 'status': 'pending_payment'
        }).execute()
        order_id = data[1][0]['id']

        # Envia a mensagem na thread
        embed = Embed(
            title=f"🛒 Pedido #{order_id}: {product['name']}",
            description=f"Olá <@{user['id']}>! Continue sua compra aqui.\n\n**Preço: {product['price_display']}**",
            color=Color.blue()
        )
        embed.set_image(url=product['image_url'])
        embed.set_footer(text="Clique no botão abaixo para realizar o pagamento.")
        message_payload = {
            "embeds": [embed.to_dict()],
            "components": [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Pagar Agora", "url": product['payment_link']}]}]
        }
        requests.post(f"{BASE_DISCORD_API_URL}/channels/{thread_id}/messages", headers=AUTH_HEADERS, json=message_payload)
        
        # Envia a resposta de acompanhamento de sucesso
        success_payload = {"content": f"✅ Criei um canal de compras privado para você! Clique aqui para finalizar: <#{thread_id}>"}
        requests.patch(followup_url, json=success_payload)

    except requests.exceptions.HTTPError as http_err:
        app.logger.error(f"Erro de API do Discord em handle_buy_action: {http_err} - {http_err.response.text}")
        requests.patch(followup_url, json={"content": "❌ Desculpe, não foi possível iniciar sua compra devido a um erro de comunicação com o Discord."})
    except Exception as e:
        app.logger.error(f"Erro inesperado em handle_buy_action: {e}")
        requests.patch(followup_url, json={"content": "❌ Ocorreu um erro inesperado ao processar sua compra."})


def handle_dashboard_command(interaction: dict):
    token = interaction['token']
    followup_url = f"{BASE_DISCORD_API_URL}/webhooks/{DISCORD_APP_ID}/{token}/messages/@original"
    try:
        response = supabase.table('pedidos').select('*').eq('status', 'completed').execute()
        completed_orders = response.data
        if not completed_orders:
            requests.patch(followup_url, json={"content": "ℹ️ Nenhuma venda foi concluída ainda."})
            return

        image_buffer = create_dashboard_image(completed_orders)
        files = {'file[0]': ('dashboard.png', image_buffer, 'image/png')}
        payload_json = {"content": ""} # É preciso enviar um payload json mesmo com arquivos
        requests.patch(followup_url, files=files, data={"payload_json": json.dumps(payload_json)})

    except Exception as e:
        app.logger.error(f"Erro ao gerar dashboard: {e}")
        requests.patch(followup_url, json={"content": "❌ Ocorreu um erro ao gerar o dashboard."})


# --- Rota Principal de Interações ---

@app.route('/interactions', methods=['POST'])
def interactions_handler():
    signature = request.headers.get('X-Signature-Ed25519')
    timestamp = request.headers.get('X-Signature-Timestamp')
    body = request.data.decode('utf-8')
    if not signature or not timestamp: return 'Missing signature headers', 401
    try:
        verify_key.verify(f'{timestamp}{body}'.encode(), bytes.fromhex(signature))
    except BadSignatureError:
        return 'Invalid request signature', 401

    interaction = request.json
    interaction_type = interaction['type']
    
    if interaction_type == 1:
        return jsonify({'type': 1})

    if interaction_type == 2:
        command_name = interaction['data']['name']
        if command_name == "comprar":
            products_list = list(PRODUTOS.values())
            if not products_list:
                return jsonify({"type": 4, "data": {"content": "ℹ️ Nenhum produto no catálogo no momento.", "flags": 64}})
            
            product = products_list[0]
            embed = Embed(title=product['name'], color=Color.from_str("#5865F2"))
            embed.add_field(name="💰 Preço", value=f"**`{product['price_display']}`**", inline=True)
            embed.add_field(name="📦 O que você recebe?", value="Código-fonte completo", inline=True)
            embed.add_field(name="📄 Descrição", value=product['description'], inline=False)
            embed.set_image(url=product['image_url'])
            embed.set_footer(text=f"Página 1 de {len(products_list)}")
            return jsonify({"type": 4, "data": {"embeds": [embed.to_dict()], "components": [{"type": 1, "components": [{"type": 2, "style": 3, "label": "Comprar este Item", "emoji": {"name": "🛒"}, "custom_id": f"buy_{product['id']}"}]}, {"type": 1, "components": [{"type": 2, "style": 2, "emoji": {"name": "⬅️"}, "custom_id": "catalog_prev_0", "disabled": True}, {"type": 2, "style": 2, "emoji": {"name": "➡️"}, "custom_id": "catalog_next_0", "disabled": len(products_list) <= 1}]}], "flags": 64}})

        if command_name == "dashboard":
            if not is_admin(interaction):
                return jsonify({"type": 4, "data": {"content": "❌ Você não tem permissão para usar este comando.", "flags": 64}})
            threading.Thread(target=handle_dashboard_command, args=(interaction,)).start()
            return jsonify({"type": 5, "data": {"flags": 64}})

    if interaction_type == 3:
        custom_id = interaction['data']['custom_id']
        if custom_id.startswith("catalog_"):
            parts = custom_id.split('_')
            action = parts[1]
            current_page = int(parts[2])
            new_page = current_page
            if action == "next": new_page += 1
            elif action == "prev": new_page -= 1
            products_list = list(PRODUTOS.values())
            new_page = max(0, min(new_page, len(products_list) - 1))
            product = products_list[new_page]
            embed = Embed(title=product['name'], color=Color.from_str("#5865F2"))
            embed.add_field(name="💰 Preço", value=f"**`{product['price_display']}`**", inline=True)
            embed.add_field(name="📦 O que você recebe?", value="Código-fonte completo", inline=True)
            embed.add_field(name="📄 Descrição", value=product['description'], inline=False)
            embed.set_image(url=product['image_url'])
            embed.set_footer(text=f"Página {new_page + 1} de {len(products_list)}")
            return jsonify({"type": 7, "data": {"embeds": [embed.to_dict()], "components": [{"type": 1, "components": [{"type": 2, "style": 3, "label": "Comprar este Item", "emoji": {"name": "🛒"}, "custom_id": f"buy_{product['id']}"}]}, {"type": 1, "components": [{"type": 2, "style": 2, "emoji": {"name": "⬅️"}, "custom_id": f"catalog_prev_{new_page}", "disabled": new_page == 0}, {"type": 2, "style": 2, "emoji": {"name": "➡️"}, "custom_id": f"catalog_next_{new_page}", "disabled": new_page >= len(products_list) - 1}]}]}})

        if custom_id.startswith("buy_"):
            threading.Thread(target=handle_buy_action, args=(interaction,)).start()
            return jsonify({"type": 5, "data": {"flags": 64}})

    return jsonify({"type": 4, "data": {"content": "Interação não reconhecida.", "flags": 64}})

@app.route('/')
def home():
    return "O bot de vendas está operando."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
