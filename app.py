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
        "id": "bot_musica", "name": "Bot de Música Avançado",
        "description": "Um bot completo para tocar músicas do YouTube e Spotify com alta qualidade.",
        "price_display": "R$ 50,00", "price_value": 50.00,
        "image_url": "https://i.imgur.com/r7ovmwr.png",
        "payment_link": "https://link.mercadopago.com.br/SEU_LINK_AQUI_1",
        "download_link": "https://github.com/SEU_USUARIO/SEU_REPOSITORIO_MUSICA/archive/refs/heads/main.zip"
    },
    "bot_moderacao": {
        "id": "bot_moderacao", "name": "Bot de Moderação Inteligente",
        "description": "Modere seu servidor com comandos automáticos, filtros e sistema de avisos.",
        "price_display": "R$ 75,00", "price_value": 75.00,
        "image_url": "https://i.imgur.com/zZqY2c2.png",
        "payment_link": "https://link.mercadopago.com.br/SEU_LINK_AQUI_2",
        "download_link": "https://github.com/SEU_USUARIO/SEU_REPOSITORIO_MODERACAO/archive/refs/heads/main.zip"
    },
    "bot_economia": {
        "id": "bot_economia", "name": "Bot de Economia Global",
        "description": "Sistema de economia com lojas, trabalhos e ranking para engajar seus membros.",
        "price_display": "R$ 40,00", "price_value": 40.00,
        "image_url": "https://i.imgur.com/T2yS1xQ.png",
        "payment_link": "https://link.mercadopago.com.br/SEU_LINK_AQUI_3",
        "download_link": "https://github.com/SEU_USUARIO/SEU_REPOSITORIO_ECONOMIA/archive/refs/heads/main.zip"
    }
}

# --- Funções Auxiliares e de Geração de Views ---

def is_admin(interaction: dict) -> bool:
    if 'member' not in interaction or 'roles' not in interaction['member']:
        return False
    return str(ADMIN_ROLE_ID) in interaction['member']['roles']

def build_pending_orders_view(page=0):
    """Busca pedidos pendentes e constrói a view (embed e botões)."""
    try:
        response = supabase.table('pedidos').select('*').eq('status', 'pending_payment').order('id').execute()
        pending_orders = response.data
    except Exception as e:
        app.logger.error(f"Erro ao buscar pedidos pendentes: {e}")
        return {"content": "❌ Erro ao buscar os pedidos.", "embeds": [], "components": []}

    if not pending_orders:
        return {"content": "✅ Não há pedidos pendentes no momento.", "embeds": [], "components": []}

    page = max(0, min(page, len(pending_orders) - 1))
    order = pending_orders[page]
    
    created_at_dt = datetime.fromisoformat(order['created_at'].replace('Z', '+00:00'))
    timestamp_str = f"<t:{int(created_at_dt.timestamp())}:f>"

    embed = Embed(title=f"Pedido Pendente #{order['id']}", description=f"**Produto:** {order['product_name']}", color=Color.orange())
    embed.add_field(name="Cliente", value=f"{order.get('user_name', 'N/A')} (`{order.get('user_id', 'N/A')}`)", inline=False)
    embed.add_field(name="Data do Pedido", value=timestamp_str, inline=False)
    embed.set_footer(text=f"Pedido {page + 1} de {len(pending_orders)}")

    components = [
        {"type": 1, "components": [
            {"type": 2, "style": 3, "label": "✅ Confirmar", "custom_id": f"pedidos_confirm_{order['id']}_{page}"},
            {"type": 2, "style": 4, "label": "❌ Cancelar", "custom_id": f"pedidos_cancel_{order['id']}_{page}"}
        ]},
        {"type": 1, "components": [
            {"type": 2, "style": 2, "emoji": {"name": "⬅️"}, "custom_id": f"pedidos_prev_{page}", "disabled": page == 0},
            {"type": 2, "style": 2, "emoji": {"name": "➡️"}, "custom_id": f"pedidos_next_{page}", "disabled": page >= len(pending_orders) - 1}
        ]}
    ]
    return {"content": "", "embeds": [embed.to_dict()], "components": components}

# --- Funções de Ações (executadas em threads) ---

def handle_confirm_order(interaction: dict):
    """Processa a confirmação de um pedido e atualiza a mensagem original."""
    token = interaction['token']
    original_message_url = f"{BASE_DISCORD_API_URL}/webhooks/{DISCORD_APP_ID}/{token}/messages/@original"
    
    try:
        parts = interaction['data']['custom_id'].split('_')
        order_id = int(parts[2])
        current_page = int(parts[3])

        supabase.table('pedidos').update({'status': 'completed'}).eq('id', order_id).execute()
        
        order_res = supabase.table('pedidos').select('product_id, product_name, thread_id, user_id').eq('id', order_id).single().execute()
        order = order_res.data
        product = PRODUTOS.get(order['product_id'])
        
        if order.get('thread_id') and product:
            embed = Embed(title="✅ Pagamento Confirmado!", description=f"Olá <@{order['user_id']}>, seu pagamento para o **{order['product_name']}** foi confirmado!\n\nObrigado pela compra. Abaixo está o link para download.", color=Color.green())
            view = {"type": 1, "components": [{"type": 2, "style": 5, "label": "Clique aqui para Baixar", "url": product['download_link']}]}
            requests.post(f"{BASE_DISCORD_API_URL}/channels/{order['thread_id']}/messages", headers=AUTH_HEADERS, json={"embeds": [embed.to_dict()], "components": [view]})
        
        # Atualiza a mensagem de pedidos com a lista atualizada
        new_view_data = build_pending_orders_view(page=current_page)
        requests.patch(original_message_url, json=new_view_data)

    except Exception as e:
        app.logger.error(f"Erro ao confirmar pedido {order_id}: {e}")
        requests.patch(original_message_url, json={"content": f"❌ Erro ao confirmar o pedido #{order_id}."})

def handle_cancel_order(interaction: dict):
    """Processa o cancelamento de um pedido e atualiza a mensagem original."""
    token = interaction['token']
    original_message_url = f"{BASE_DISCORD_API_URL}/webhooks/{DISCORD_APP_ID}/{token}/messages/@original"

    try:
        parts = interaction['data']['custom_id'].split('_')
        order_id = int(parts[2])
        current_page = int(parts[3])

        supabase.table('pedidos').update({'status': 'cancelled'}).eq('id', order_id).execute()
        
        order_res = supabase.table('pedidos').select('product_name, thread_id, user_id').eq('id', order_id).single().execute()
        order = order_res.data
        
        if order.get('thread_id'):
            requests.post(f"{BASE_DISCORD_API_URL}/channels/{order['thread_id']}/messages", headers=AUTH_HEADERS, json={"content": f"Olá <@{order['user_id']}>, infelizmente seu pedido para o produto **{order['product_name']}** foi cancelado por um administrador."})
            
        new_view_data = build_pending_orders_view(page=current_page)
        requests.patch(original_message_url, json=new_view_data)

    except Exception as e:
        app.logger.error(f"Erro ao cancelar pedido {order_id}: {e}")
        requests.patch(original_message_url, json={"content": f"❌ Erro ao cancelar o pedido #{order_id}."})

def handle_buy_action(interaction: dict):
    """Cria a thread de compra e envia uma resposta de acompanhamento."""
    token = interaction['token']
    followup_url = f"{BASE_DISCORD_API_URL}/webhooks/{DISCORD_APP_ID}/{token}/messages/@original"
    try:
        product_id = interaction['data']['custom_id'].split('_', 1)[1]
        product = PRODUTOS.get(product_id)
        if not product:
            requests.patch(followup_url, json={"content": "❌ Produto não encontrado."})
            return

        user = interaction['member']['user']
        thread_url = f"{BASE_DISCORD_API_URL}/channels/{interaction['channel_id']}/threads"
        thread_res = requests.post(thread_url, headers=AUTH_HEADERS, json={"name": f"🛒-compra-{user['username']}", "type": 12, "auto_archive_duration": 1440})
        thread_res.raise_for_status()
        thread = thread_res.json()
        
        requests.put(f"{BASE_DISCORD_API_URL}/channels/{thread['id']}/thread-members/{user['id']}", headers=AUTH_HEADERS)
        
        data, _ = supabase.table('pedidos').insert({'user_id': int(user['id']), 'user_name': user['username'], 'product_id': product['id'], 'product_name': product['name'], 'thread_id': int(thread['id']), 'status': 'pending_payment'}).execute()
        
        embed = Embed(title=f"🛒 Pedido #{data[1][0]['id']}: {product['name']}", description=f"Olá <@{user['id']}>! Continue sua compra aqui.\n\n**Preço: {product['price_display']}**", color=Color.blue())
        embed.set_image(url=product['image_url'])
        message_payload = {"embeds": [embed.to_dict()], "components": [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Pagar Agora", "url": product['payment_link']}]}]}
        requests.post(f"{BASE_DISCORD_API_URL}/channels/{thread['id']}/messages", headers=AUTH_HEADERS, json=message_payload)
        
        requests.patch(followup_url, json={"content": f"✅ Criei um canal de compras privado para você! Clique aqui para finalizar: <#{thread['id']}>"})
    except Exception as e:
        app.logger.error(f"Erro inesperado em handle_buy_action: {e}")
        requests.patch(followup_url, json={"content": "❌ Ocorreu um erro inesperado ao processar sua compra."})

# (A função create_dashboard_image não foi alterada e pode ser omitida por brevidade se necessário)
def create_dashboard_image(completed_orders: list) -> io.BytesIO:
    sales_by_day=defaultdict(float);end_date=datetime.now(timezone.utc);start_date=end_date-timedelta(days=30)
    for o in completed_orders:
        c=datetime.fromisoformat(o['created_at'].replace('Z','+00:00'))
        if start_date<=c<=end_date:
            p=o.get('product_id')
            if p and p in PRODUTOS:sales_by_day[c.date()]+=PRODUTOS[p]['price_value']
    dates=[start_date.date()+timedelta(days=i) for i in range(31)];sales=[sales_by_day[d] for d in dates];total_sales_count=len(completed_orders);total_revenue=sum(PRODUTOS[o['product_id']]['price_value'] for o in completed_orders if o['product_id'] in PRODUTOS)
    plt.style.use('dark_background');fig,ax=plt.subplots(figsize=(12,7),dpi=120);fig.patch.set_facecolor('#23272A');ax.set_facecolor('#2C2F33');ax.bar(dates,sales,color='#5865F2',zorder=2);ax.grid(axis='y',color='white',linestyle=':',linewidth=0.5,alpha=0.3,zorder=1);ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'));ax.xaxis.set_major_locator(mdates.DayLocator(interval=5));plt.xticks(rotation=45,color='white');plt.yticks(color='white')
    for s in['top','right']:ax.spines[s].set_visible(False)
    for s in['left','bottom']:ax.spines[s].set_color('#FFFFFF')
    fig.suptitle('Dashboard de Vendas',fontsize=22,color='white',weight='bold');ax.set_title('Receita nos Últimos 30 Dias',fontsize=14,color='#B9BBBE',pad=20);formatted_revenue=f"R$ {total_revenue:,.2f}".replace(',','v').replace('.',',').replace('v','.');props=dict(boxstyle='round,pad=0.5',facecolor='#23272A',alpha=0.9);ax.text(0.02,0.95,f"Receita Total: {formatted_revenue}\nTotal de Vendas: {total_sales_count}",transform=ax.transAxes,fontsize=12,verticalalignment='top',color='white',bbox=props);plt.tight_layout(rect=[0,0.03,1,0.95]);buf=io.BytesIO();plt.savefig(buf,format='png',facecolor=fig.get_facecolor());buf.seek(0);plt.close();return buf
def handle_dashboard_command(interaction: dict):
    token=interaction['token'];followup_url=f"{BASE_DISCORD_API_URL}/webhooks/{DISCORD_APP_ID}/{token}/messages/@original"
    try:
        res=supabase.table('pedidos').select('*').eq('status','completed').execute()
        if not res.data:requests.patch(followup_url,json={"content":"ℹ️ Nenhuma venda foi concluída ainda."});return
        img_buf=create_dashboard_image(res.data);files={'file[0]':('dashboard.png',img_buf,'image/png')};payload_json={"content":""};requests.patch(followup_url,files=files,data={"payload_json":json.dumps(payload_json)})
    except Exception as e:app.logger.error(f"Erro ao gerar dashboard: {e}");requests.patch(followup_url,json={"content":"❌ Ocorreu um erro ao gerar o dashboard."})

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
    itype = interaction['type']
    
    if itype == 1: return jsonify({'type': 1})

    if itype == 2: # Command
        data = interaction['data']
        name = data['name']
        if name == "comprar":
            # (Lógica do /comprar permanece a mesma)
            return jsonify({"type": 4, "data": {"embeds": [Embed(title=list(PRODUTOS.values())[0]['name'], color=Color.from_str("#5865F2")).add_field(name="💰 Preço", value=f"**`{list(PRODUTOS.values())[0]['price_display']}`**", inline=True).add_field(name="📦 O que você recebe?", value="Código-fonte completo", inline=True).add_field(name="📄 Descrição", value=list(PRODUTOS.values())[0]['description'], inline=False).set_image(url=list(PRODUTOS.values())[0]['image_url']).set_footer(text=f"Página 1 de {len(PRODUTOS)}").to_dict()], "components": [{"type": 1, "components": [{"type": 2, "style": 3, "label": "Comprar este Item", "emoji": {"name": "🛒"}, "custom_id": f"buy_{list(PRODUTOS.values())[0]['id']}"}]}, {"type": 1, "components": [{"type": 2, "style": 2, "emoji": {"name": "⬅️"}, "custom_id": "catalog_prev_0", "disabled": True}, {"type": 2, "style": 2, "emoji": {"name": "➡️"}, "custom_id": "catalog_next_0", "disabled": len(PRODUTOS) <= 1}]}], "flags": 64}})
        
        if name == "pedidos":
            if not is_admin(interaction):
                return jsonify({"type": 4, "data": {"content": "❌ Você não tem permissão.", "flags": 64}})
            return jsonify({"type": 4, "data": {**build_pending_orders_view(), "flags": 64}})

        if name == "dashboard":
            if not is_admin(interaction):
                return jsonify({"type": 4, "data": {"content": "❌ Você não tem permissão.", "flags": 64}})
            threading.Thread(target=handle_dashboard_command, args=(interaction,)).start()
            return jsonify({"type": 5, "data": {"flags": 64}})

    if itype == 3: # Component
        custom_id = interaction['data']['custom_id']
        if custom_id.startswith("catalog_"):
            # (Lógica da navegação do catálogo permanece a mesma)
            parts=custom_id.split('_');action=parts[1];page=int(parts[2]);new_page=page+(1 if action=="next" else -1);products_list=list(PRODUTOS.values());new_page=max(0,min(new_page,len(products_list)-1));product=products_list[new_page];embed=Embed(title=product['name'],color=Color.from_str("#5865F2")).add_field(name="💰 Preço",value=f"**`{product['price_display']}`**",inline=True).add_field(name="📦 O que você recebe?",value="Código-fonte completo",inline=True).add_field(name="📄 Descrição",value=product['description'],inline=False).set_image(url=product['image_url']).set_footer(text=f"Página {new_page+1} de {len(products_list)}");return jsonify({"type":7,"data":{"embeds":[embed.to_dict()],"components":[{"type":1,"components":[{"type":2,"style":3,"label":"Comprar este Item","emoji":{"name":"🛒"},"custom_id":f"buy_{product['id']}"}]},{"type":1,"components":[{"type":2,"style":2,"emoji":{"name":"⬅️"},"custom_id":f"catalog_prev_{new_page}","disabled":new_page==0},{"type":2,"style":2,"emoji":{"name":"➡️"},"custom_id":f"catalog_next_{new_page}","disabled":new_page>=len(products_list)-1}]}]}})
        
        if custom_id.startswith("buy_"):
            threading.Thread(target=handle_buy_action, args=(interaction,)).start()
            return jsonify({"type": 5, "data": {"flags": 64}})

        if custom_id.startswith("pedidos_"):
            action = custom_id.split('_')[1]
            if action in ["prev", "next"]:
                page = int(custom_id.split('_')[2])
                new_page = page + (1 if action == "next" else -1)
                return jsonify({"type": 7, "data": build_pending_orders_view(page=new_page)})
            
            if action == "confirm":
                threading.Thread(target=handle_confirm_order, args=(interaction,)).start()
                return jsonify({"type": 6}) # DEFERRED_UPDATE_MESSAGE
            
            if action == "cancel":
                threading.Thread(target=handle_cancel_order, args=(interaction,)).start()
                return jsonify({"type": 6}) # DEFERRED_UPDATE_MESSAGE

    return jsonify({"type": 4, "data": {"content": "Interação não reconhecida.", "flags": 64}})

@app.route('/')
def home(): return "O bot de vendas está operando."
if __name__ == '__main__': app.run(host='0.0.0.0', port=8080, debug=True)
