from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
import io
import base64
import datetime
import sqlite3
from functools import wraps
import threading
import re
import shutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, create_string_object, DictionaryObject, BooleanObject
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf.generic import NameObject, NumberObject, create_string_object, DictionaryObject, BooleanObject, ArrayObject
import json

app = Flask(__name__)
app.secret_key = 'segredo123'  # Troque isso depois para algo seguro!

def resolve_network_path(path):
    """
    Se estiver rodando no Linux (Docker/Coolify), converte o caminho de rede do Windows (\\sv-scalco\...)
    para um caminho montado no Linux (/sv-scalco/...).
    Se estiver no Windows, mantém original.
    """
    if not path:
        return path
    if os.name != 'nt':
        p = path.replace('\\', '/')
        if p.startswith('//'):
            p = '/' + p[2:]
        return p
    return path

# Helpers de Gerentes no Banco
def get_gerentes_config():
    """Retorna lista de gerentes do banco: [{'id':..., 'nome':..., 'letra':..., 'senha':..., 'caminho_pasta':...}]"""
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gerentes")
            return [dict(row) for row in cursor.fetchall()]
    except:
        return []

def get_paths_checklist():
    """Retorna um dicionário { 'letra': 'caminho_pasta' } das gerentes"""
    gerentes = get_gerentes_config()
    return {g['letra']: resolve_network_path(g['caminho_pasta']) for g in gerentes}

def get_gerentes_map():
    """Retorna um dicionário { 'letra': 'nome' }"""
    return {g['letra']: g['nome'] for g in get_gerentes_config()}

def get_gerentes_reverso():
    """Retorna um dicionário { 'nome': 'letra' }"""
    return {g['nome']: g['letra'] for g in get_gerentes_config()}

def get_gerentes_nomes():
    """Retorna lista de nomes das gerentes"""
    return [g['nome'] for g in get_gerentes_config()]

# Configuração do banco de dados
DATABASE = os.environ.get('DB_PATH', 'scalco.db')

DATA_DIR = os.path.dirname(DATABASE)
if not DATA_DIR:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))

PASTA_PENDENTES = os.path.join(DATA_DIR, 'pendentes')
PASTA_REJEICOES = os.path.join(DATA_DIR, 'rejeicoes')

def mover_arquivo(origem, destino):
    """Move um arquivo garantindo que não vai dar PermissionError ao copiar estatísticas (chown/chmod) para o CIFS."""
    if os.path.exists(origem):
        shutil.copy(origem, destino)
        try:
            os.remove(origem)
        except Exception:
            pass

def init_db():
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            
            # Criar tabela de usuários
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT 0,
                    data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Criar tabela de comentários
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comentarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conteudo TEXT NOT NULL,
                    autor_id INTEGER NOT NULL,
                    data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP,
                    data_edicao DATETIME,
                    FOREIGN KEY (autor_id) REFERENCES usuarios (id)
                )
            ''')

            # Criar tabela de empresas (checklist)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS empresas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    numero TEXT NOT NULL,
                    gerente TEXT NOT NULL,
                    ativo BOOLEAN DEFAULT 1,
                    data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Criar tabela de histórico de baixas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS baixas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    empresa_id INTEGER NOT NULL,
                    arquivo_pdf TEXT NOT NULL,
                    data_baixa DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (empresa_id) REFERENCES empresas(id)
                )
            ''')
            
            # Criar tabela de gerentes
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS gerentes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE NOT NULL,
                    letra TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    caminho_pasta TEXT NOT NULL
                )
            ''')
            
            # Popular gerentes iniciais se vazio
            cursor.execute('SELECT COUNT(*) FROM gerentes')
            if cursor.fetchone()[0] == 0:
                gerentes_iniciais = [
                    ('Sandra', 'S', 'sandra123', r'\\sv-scalco\Sistemas\CAIXINHA\SANDRA\OK'),
                    ('Adriana', 'A', 'adriana123', r'\\sv-scalco\Sistemas\CAIXINHA\ADRIANA\OK'),
                    ('Rose', 'R', 'rose123', r'\\sv-scalco\Sistemas\CAIXINHA\ROSE\OK')
                ]
                cursor.executemany('INSERT INTO gerentes (nome, letra, senha, caminho_pasta) VALUES (?, ?, ?, ?)', gerentes_iniciais)
            
            # Verificar e adicionar novas colunas em empresas
            cursor.execute("PRAGMA table_info(empresas)")
            colunas_empresa = [col[1] for col in cursor.fetchall()]
            if 'status_lancamento_caixinha' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN status_lancamento_caixinha TEXT DEFAULT 'pendente'")
            if 'arquivo_gerado' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN arquivo_gerado TEXT")
            if 'atualizado_em' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN atualizado_em DATETIME")
            if 'cnpj' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN cnpj TEXT DEFAULT ''")
            if 'inscricao_estadual' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN inscricao_estadual TEXT DEFAULT ''")
            if 'tributacao' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN tributacao TEXT DEFAULT ''")
            if 'arquivo_rejeitado' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN arquivo_rejeitado TEXT")
            if 'motivo_rejeicao' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN motivo_rejeicao TEXT")
            if 'dados_lancamento' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN dados_lancamento TEXT DEFAULT '{}'")
            if 'revisor' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN revisor TEXT DEFAULT NULL")
            if 'revisor_anterior' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN revisor_anterior TEXT DEFAULT NULL")
            if 'arquivo_anexo_yasmin' not in colunas_empresa:
                cursor.execute("ALTER TABLE empresas ADD COLUMN arquivo_anexo_yasmin TEXT DEFAULT NULL")
            
            # Criar tabela de revisores (segundo nível de conferência)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS revisores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    caminho_pasta TEXT DEFAULT '',
                    pasta_anexos TEXT DEFAULT ''
                )
            ''')
            # Popular revisores iniciais se vazio
            cursor.execute('SELECT COUNT(*) FROM revisores')
            if cursor.fetchone()[0] == 0:
                revisores_iniciais = [
                    ('Valnei', 'valnei123', '', ''),
                    ('Yasmin', 'yasmin123', '', r'\\sv-scalco\Trabalho\Contabilidade\Miguel\Nova pasta (2)'),
                    ('Marielli', 'marielli123', '', ''),
                ]
                cursor.executemany('INSERT INTO revisores (nome, senha, caminho_pasta, pasta_anexos) VALUES (?, ?, ?, ?)', revisores_iniciais)
            
            # Verificar e adicionar novas colunas em revisores
            cursor.execute("PRAGMA table_info(revisores)")
            colunas_revisor = [col[1] for col in cursor.fetchall()]
            if 'caminho_pasta' not in colunas_revisor:
                cursor.execute("ALTER TABLE revisores ADD COLUMN caminho_pasta TEXT DEFAULT ''")
            if 'pasta_anexos' not in colunas_revisor:
                cursor.execute("ALTER TABLE revisores ADD COLUMN pasta_anexos TEXT DEFAULT ''")
                cursor.execute("UPDATE revisores SET pasta_anexos = ? WHERE nome = 'Yasmin'", (r'\\sv-scalco\Trabalho\Contabilidade\Miguel\Nova pasta (2)',))

            
            # Verificar se a tabela foi criada corretamente
            cursor.execute("PRAGMA table_info(usuarios)")
            columns = cursor.fetchall()
            if not any(col[1] == 'usuario' for col in columns):
                # Se a tabela não tiver a coluna 'usuario', recriar a tabela
                cursor.execute('DROP TABLE IF EXISTS usuarios')
                cursor.execute('''
                    CREATE TABLE usuarios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        usuario TEXT UNIQUE NOT NULL,
                        senha TEXT NOT NULL,
                        is_admin BOOLEAN DEFAULT 0,
                        data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
            # Criar usuário admin padrão se não existir
            cursor.execute('SELECT * FROM usuarios WHERE usuario = ?', ('admin',))
            if not cursor.fetchone():
                cursor.execute(
                    'INSERT INTO usuarios (usuario, senha, is_admin) VALUES (?, ?, ?)',
                    ('admin', '123', 1)
                )
            
            conn.commit()
    except sqlite3.Error as e:
        print(f"Erro ao inicializar o banco de dados: {e}")
        raise

# Inicializar banco de dados
init_db()

# ---- Watchdog Logic ----
class BaixaHandler(FileSystemEventHandler):
    def process_file(self, filepath):
        filename = os.path.basename(filepath)
        
        if not filename.lower().endswith('.pdf'):
            return
            
        # Match pattern: Letra - Numero - ..._Unido.pdf
        # ex: S - 403 - NOMEEMPRESA_Unido.pdf
        match = re.match(r'^([SAR])\s*-\s*(\d+)\s*-.*_Unido\.pdf$', filename, re.IGNORECASE)
        if match:
            letra = match.group(1).upper()
            numero = match.group(2)
            
            # Map letter to manager
            gerentes_map = get_gerentes_map()
            gerente = gerentes_map.get(letra)
            
            if gerente:
                try:
                    with sqlite3.connect(DATABASE) as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT id FROM empresas 
                            WHERE numero = ? AND gerente = ? AND ativo = 1
                        ''', (numero, gerente))
                        empresa = cursor.fetchone()
                        
                        if empresa:
                            empresa_id = empresa[0]
                            # Check to avoid duplicate baixas since on_modified can fire multiple times
                            cursor.execute('SELECT id FROM baixas WHERE empresa_id = ?', (empresa_id,))
                            if not cursor.fetchone():
                                cursor.execute('''
                                    INSERT INTO baixas (empresa_id, arquivo_pdf)
                                    VALUES (?, ?)
                                ''', (empresa_id, filename))
                                conn.commit()
                                print(f"[Checklist] Baixa efetuada para empresa ID {empresa_id} ({gerente}-{numero}) via arquivo {filename}")
                except Exception as e:
                    print(f"Erro ao processar baixa pelo watchdog: {e}")

    def on_created(self, event):
        if not event.is_directory:
            self.process_file(event.src_path)
            
    def on_modified(self, event):
        if not event.is_directory:
            self.process_file(event.src_path)
            
    def on_moved(self, event):
        if not event.is_directory:
            self.process_file(event.dest_path)

def start_watchdog():
    observer = Observer()
    handler = BaixaHandler()
    
    for path in get_paths_checklist().values():
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except Exception as e:
                print(f"Aviso: Não foi possível criar a pasta {path}: {str(e)}")
        
        if os.path.exists(path):
            observer.schedule(handler, path, recursive=False)
            
    observer.start()
    print("[Checklist] Watchdog iniciado monitorando pastas.")
    # Thread will run daemonically, no need to join here

# Start watchdog in background
watchdog_thread = threading.Thread(target=start_watchdog, daemon=True)
watchdog_thread.start()
# ------------------------

# Decorator para verificar se usuário está logado
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            return jsonify({'success': False, 'message': 'Usuário não está logado'})
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Buscar todos os comentários com informações do autor
        cursor.execute('''
            SELECT 
                c.*,
                u.usuario as autor_nome,
                strftime('%d/%m/%Y %H:%M', c.data_criacao, 'localtime') as data_formatada
            FROM comentarios c
            JOIN usuarios u ON c.autor_id = u.id
            ORDER BY c.data_criacao DESC
        ''')
        comentarios = cursor.fetchall()
        
    return render_template('index.html',
                         logado='usuario_id' in session,
                         usuario_atual=session.get('usuario_id'),
                         is_admin=session.get('is_admin', False),
                         comentarios=comentarios)

@app.route('/login', methods=['POST'])
def login():
    usuario = request.form.get('usuario')
    senha = request.form.get('senha')
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM usuarios WHERE usuario = ? AND senha = ?',
                      (usuario, senha))
        user = cursor.fetchone()
        
        if user:
            session['usuario_id'] = user[0]
            session['usuario'] = user[1]
            session['is_admin'] = user[3]
            return redirect(url_for('index'))
    
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/comentario', methods=['POST'])
@login_required
def adicionar_comentario():
    data = request.get_json()
    conteudo = data.get('comentario')
    autor_id = session['usuario_id']
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO comentarios (conteudo, autor_id)
            VALUES (?, ?)
        ''', (conteudo, autor_id))
        conn.commit()
        
    return jsonify({'success': True})

@app.route('/comentario/<int:id>', methods=['GET'])
@login_required
def get_comentario(id):
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.*, u.usuario as autor_nome
            FROM comentarios c
            JOIN usuarios u ON c.autor_id = u.id
            WHERE c.id = ?
        ''', (id,))
        comentario = cursor.fetchone()
        
    if comentario:
        return jsonify({
            'success': True,
            'conteudo': comentario['conteudo'],
            'autor': comentario['autor_nome']
        })
    return jsonify({'success': False, 'message': 'Comentário não encontrado'})

@app.route('/comentario/editar/<int:id>', methods=['POST'])
@login_required
def editar_comentario(id):
    data = request.get_json()
    novo_conteudo = data.get('comentario')
    autor_id = session['usuario_id']
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE comentarios 
            SET conteudo = ?, data_edicao = CURRENT_TIMESTAMP
            WHERE id = ? AND (autor_id = ? OR 
                ? IN (SELECT id FROM usuarios WHERE is_admin = 1))
        ''', (novo_conteudo, id, autor_id, autor_id))
        conn.commit()
        success = cursor.rowcount > 0
        
    return jsonify({'success': success})

@app.route('/comentario/deletar/<int:id>', methods=['POST'])
@login_required
def deletar_comentario(id):
    autor_id = session['usuario_id']
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM comentarios 
            WHERE id = ? AND (autor_id = ? OR 
                ? IN (SELECT id FROM usuarios WHERE is_admin = 1))
        ''', (id, autor_id, autor_id))
        conn.commit()
        success = cursor.rowcount > 0
        
    return jsonify({'success': success})




@app.route('/entregas')
def visualizar_entregas():
    linhas = []
    empresas = []
    nome_arquivo_recente = "N/A"
    pasta_entregas = resolve_network_path(r'\\sv-scalco\Trabalho\Contabilidade\SPED - ARQUIVOS\Fiscal\Recibos do mes')
    
    try:
        # Encontrar o arquivo .txt mais recente na pasta
        arquivos_txt = [f for f in os.listdir(pasta_entregas) if f.endswith('.txt') and os.path.isfile(os.path.join(pasta_entregas, f))]
        
        if not arquivos_txt:
            return "Nenhum arquivo .txt encontrado na pasta de entregas", 404
            
        # Ordena os arquivos por data de modificação (mais recente primeiro)
        arquivos_txt.sort(key=lambda f: os.path.getmtime(os.path.join(pasta_entregas, f)), reverse=True)
        
        # Pega o arquivo mais recente
        nome_arquivo_recente = arquivos_txt[0]
        arquivo_entregas = os.path.join(pasta_entregas, nome_arquivo_recente)

        # Tenta ler o conteúdo do arquivo com diferentes encodings
        try:
            with open(arquivo_entregas, 'r', encoding='utf-8') as file:
                linhas = file.readlines()
        except UnicodeDecodeError:
            try:
                with open(arquivo_entregas, 'r', encoding='latin-1') as file:
                    linhas = file.readlines()
            except Exception as enc_err:
                print(f"Erro de encoding ao ler {nome_arquivo_recente}: {enc_err}")
                raise # Re-levanta o erro se latin-1 também falhar
        
        # Processa cada linha para extrair as informações
        for i, linha in enumerate(linhas):
            linha_strip = linha.strip()
            if not linha_strip: # Pula linhas em branco
                continue
            try:
                partes = linha_strip.split('\t')
                if len(partes) >= 3:
                    numero = partes[0].strip()
                    nome = partes[1].strip()
                    gerente = '\t'.join(partes[2:]).strip() 
                    empresas.append({
                        'numero': numero,
                        'nome': nome,
                        'gerente': gerente
                    })
                # else:
                    # print(f"Aviso: Linha {i+1} ignorada - formato inesperado (menos de 3 colunas TAB): {linha_strip}") # Removido (opcional manter se quiser avisos)
            except IndexError as idx_err:
                print(f"Aviso: Erro de índice ao processar linha {i+1} em {nome_arquivo_recente}. Linha: {linha_strip} | Erro: {idx_err}") # Mantido para avisos importantes
            except Exception as proc_err:
                 print(f"Aviso: Erro inesperado ao processar linha {i+1} em {nome_arquivo_recente}. Linha: {linha_strip} | Erro: {proc_err}") # Mantido para avisos importantes
        
        # Se a requisição for AJAX (feita via JavaScript), retorna os dados estruturados
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(empresas)
            
        # Caso contrário, retorna a página completa
        return render_template('entregas.html', empresas=empresas)
        
    except FileNotFoundError:
        print(f"Erro Crítico: Pasta de entregas não encontrada: {pasta_entregas}") # Mantido para erros críticos
        return f"Erro: Pasta não encontrada: {pasta_entregas}", 500
    except PermissionError:
        print(f"Erro Crítico: Sem permissão para acessar a pasta de entregas: {pasta_entregas}") # Mantido para erros críticos
        return f"Erro: Sem permissão para acessar a pasta: {pasta_entregas}", 500
    except Exception as e:
        # Mantém log para erros inesperados gerais
        print(f"Erro Crítico Inesperado na rota /entregas: {type(e).__name__} - {e}")
        import traceback
        print(traceback.format_exc())
        return f"Erro interno ao processar entregas. Verifique os logs do servidor. Arquivo: {nome_arquivo_recente}", 500

# --- Rotas de Lançamento Caixinha ---
@app.route('/lancamento')
def lancamento_page():
    return render_template('lancamento.html',
                           is_admin=session.get('is_admin', False))

@app.route('/caixinha/lancamento/gerentes')
def lancamento_gerentes():
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT gerente FROM empresas WHERE ativo = 1 ORDER BY gerente")
        gerentes = [{'id': row['gerente'], 'nome': row['gerente']} for row in cursor.fetchall()]
    return jsonify({'success': True, 'data': gerentes})

@app.route('/caixinha/lancamento/empresas')
def lancamento_empresas():
    gerente_id = request.args.get('gerente_id')
    quantidade = request.args.get('quantidade', 'todos')
    
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT id, numero, nome, gerente, status_lancamento_caixinha, cnpj, inscricao_estadual, tributacao FROM empresas WHERE ativo = 1"
        params = []
        if gerente_id:
            query += " AND gerente = ?"
            params.append(gerente_id)
        query += " ORDER BY nome"
        
        cursor.execute(query, params)
        empresas = [dict(row) for row in cursor.fetchall()]
        
        if quantidade != 'todos' and quantidade.isdigit():
            empresas = empresas[:int(quantidade)]
            
    return jsonify({'success': True, 'data': empresas})

# Campos fixos que serão desenhados como texto (não mais como form fields)
CAMPOS_FIXOS_PDF = {
    'Text1': 'nome_formatado',
    'Text2': 'cnpj',
    'Text5': 'inscricao_estadual',
    'Text3': 'tributacao',
    'Text4': 'vazio',
}

# Posições dos campos fixos no PDF (em pontos PDF, origem bottom-left)
# Formato: campo -> (x, y, largura, altura, font_size)
# Ajuste x/y conforme o seu MODELO.pdf
POSICOES_CAMPOS_FIXOS = {
    'Text1': (138.5, 814.9, 425.1, 14.2, 12),   # Razão Social  (+5)
    'Text2': (94.4,  798.5, 154.9, 14.9, 12),   # CNPJ          (+5)
    'Text4': (283.0, 801.0, 131.4, 14.4, 12),   # CPF           (+5)
    'Text5': (483.8, 799.4,  84.1, 14.0, 12),   # Inscrição Est (+5)
    'Text3': (122.0, 781.9, 146.8, 17.1, 12),   # Tributação    (+5)
}

def remover_campos_fixos_do_acroform(writer):
    """Remove os campos Text1–Text5 do AcroForm para que não sejam editáveis."""
    campos_para_remover = set(CAMPOS_FIXOS_PDF.keys())
    
    if '/AcroForm' not in writer._root_object:
        return
    
    acroform = writer._root_object['/AcroForm'].get_object()
    if '/Fields' not in acroform:
        return
    
    fields = acroform['/Fields']
    novos_fields = []
    
    for ref in fields:
        field = ref.get_object()
        nome = field.get('/T')
        if hasattr(nome, 'get_original_bytes'):
            nome = nome.get_original_bytes().decode('utf-8', errors='ignore')
        elif hasattr(nome, '__str__'):
            nome = str(nome)
        
        if nome not in campos_para_remover:
            novos_fields.append(ref)
    
    acroform[NameObject('/Fields')] = ArrayObject(novos_fields)
    
    # Remove também das anotações de cada página
    for page in writer.pages:
        if '/Annots' not in page:
            continue
        annots = page['/Annots']
        novas_annots = []
        for ref in annots:
            annot = ref.get_object()
            nome = annot.get('/T')
            if nome is not None:
                if hasattr(nome, 'get_original_bytes'):
                    nome = nome.get_original_bytes().decode('utf-8', errors='ignore')
                elif hasattr(nome, '__str__'):
                    nome = str(nome)
                if nome in campos_para_remover:
                    continue
            novas_annots.append(ref)
        page[NameObject('/Annots')] = ArrayObject(novas_annots)


def desenhar_campos_fixos_no_pdf(writer, empresa):
    """Desenha os dados fixos da empresa diretamente no canvas da página (não editável)."""
    buf = io.BytesIO()
    
    # Pega dimensões reais da primeira página
    page = writer.pages[0]
    media_box = page.mediabox
    page_width  = float(media_box.width)
    page_height = float(media_box.height)
    
    c = rl_canvas.Canvas(buf, pagesize=(page_width, page_height))
    c.setFont("Helvetica-Bold", 9)
    c.setFillColorRGB(0, 0, 0)
    
    dados = {
        'Text1': empresa.get('nome_formatado', ''),
        'Text2': empresa.get('cnpj', ''),
        'Text4': empresa.get('cpf', ''),          # se tiver CPF no cadastro
        'Text5': empresa.get('inscricao_estadual', '') or 'BAIXADA',
        'Text3': empresa.get('tributacao', ''),
    }
    
    for campo, texto in dados.items():
        if campo not in POSICOES_CAMPOS_FIXOS:
            continue
        x, y, largura, altura, font_size = POSICOES_CAMPOS_FIXOS[campo]
        if not texto:
            continue
        c.setFont("Helvetica-Bold", font_size)
        # Trunca se o texto for maior que o campo
        while c.stringWidth(texto, "Helvetica-Bold", font_size) > largura and len(texto) > 1:
            texto = texto[:-1]
        c.drawString(x, y, texto)
    
    c.save()
    buf.seek(0)
    
    # Merge do overlay na página 0
    overlay_reader = PdfReader(buf)
    overlay_page   = overlay_reader.pages[0]
    writer.pages[0].merge_page(overlay_page)


def preencher_e_formatar_pdf(writer, valores, travar_fixos=False, regenerar_ap=True):
    """Preenche apenas os campos editáveis (não-fixos) do formulário."""
    # Filtra fora os campos fixos — eles são desenhados diretamente no canvas
    valores_editaveis = {k: v for k, v in valores.items() if k not in CAMPOS_FIXOS_PDF}
    
    if '/AcroForm' in writer._root_object:
        acroform = writer._root_object['/AcroForm'].get_object()
        if NameObject('/DA') not in acroform:
            acroform[NameObject('/DA')] = create_string_object('/Helv 9 Tf 0 g')
        if NameObject('/DR') not in acroform:
            acroform[NameObject('/DR')] = DictionaryObject()
        dr = acroform[NameObject('/DR')].get_object()
        if NameObject('/Font') not in dr:
            dr[NameObject('/Font')] = DictionaryObject()

    for page in writer.pages:
        if '/Annots' not in page:
            continue
        for a_ref in page['/Annots']:
            annot = a_ref.get_object()
            t = annot.get('/T')
            if t not in valores_editaveis:
                continue
            annot[NameObject('/DA')] = create_string_object('/Helv 8 Tf 0 g')
            if NameObject('/AP') in annot:
                del annot[NameObject('/AP')]

    for page in writer.pages:
        writer.update_page_form_field_values(
            page, valores_editaveis, auto_regenerate=regenerar_ap
        )

    if '/AcroForm' in writer._root_object:
        acroform = writer._root_object['/AcroForm'].get_object()
        acroform[NameObject('/NeedAppearances')] = BooleanObject(True)

@app.route('/caixinha/lancamento/prefill/<int:empresa_id>')
def lancamento_prefill(empresa_id):
    """Gera um PDF com os dados da empresa desenhados diretamente no canvas (não editável)."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM empresas WHERE id = ?', (empresa_id,))
            empresa = cursor.fetchone()

        if not empresa:
            return jsonify({'success': False, 'message': 'Empresa não encontrada'}), 404

        empresa = dict(empresa)
        numero = str(empresa.get('numero') or '').strip()
        nome   = str(empresa.get('nome')   or '').strip()
        empresa['nome_formatado'] = f"{numero} - {nome}" if numero else nome

        if not str(empresa.get('inscricao_estadual') or '').strip():
            empresa['inscricao_estadual'] = 'BAIXADA'

        caminho_pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'pdf', 'MODELO.pdf')
        reader = PdfReader(caminho_pdf)
        writer = PdfWriter()
        writer.append(reader)

        # 1. Remove os campos fixos do AcroForm (não serão mais editáveis)
        remover_campos_fixos_do_acroform(writer)

        # 2. Desenha os dados diretamente no canvas da página
        desenhar_campos_fixos_no_pdf(writer, empresa)

        # 3. Preenche campos editáveis normalmente (sem os fixos)
        preencher_e_formatar_pdf(writer, {}, travar_fixos=False, regenerar_ap=False)

        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        pdf_b64 = base64.b64encode(buf.read()).decode('utf-8')

        return jsonify({'success': True, 'pdf_base64': pdf_b64})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/caixinha/lancamento/dados/<int:empresa_id>')
def lancamento_dados(empresa_id):
    """Retorna os dados digitados na última submissão para recarregar o formulário."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT dados_lancamento FROM empresas WHERE id = ?', (empresa_id,))
            row = cursor.fetchone()
            
        dados = {}
        if row and row['dados_lancamento']:
            try:
                dados = json.loads(row['dados_lancamento'])
            except:
                pass
        return jsonify({'success': True, 'data': dados})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/caixinha/lancamento/formulario-campos')
def lancamento_formulario_campos():
    try:
        caminho_pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'pdf', 'MODELO.pdf')
        reader = PdfReader(caminho_pdf)
        campos = reader.get_fields()
        
        resultado = []
        for nome, campo in campos.items():
            tipo = campo.get("/FT", "")
            if hasattr(tipo, "replace"):
                tipo = tipo.replace("/", "")
            elif isinstance(tipo, str) and tipo.startswith("/"):
                tipo = tipo[1:]
            
            ff = campo.get("/Ff", 0)
            editavel = not bool(ff & 1)
            
            resultado.append({
                "nome": nome,
                "tipo": tipo,
                "editavel": editavel
            })
            
        return jsonify({'success': True, 'data': resultado})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/caixinha/lancamento/desbloquear', methods=['POST'])
def lancamento_desbloquear():
    """Apenas admin pode resetar o status de uma empresa finalizada."""
    if not session.get('is_admin'):
        return jsonify({'status': 'erro', 'mensagem': 'Acesso negado. Somente admins podem desbloquear.'}), 403
    data = request.get_json()
    empresa_id = data.get('empresa_id')
    if not empresa_id:
        return jsonify({'status': 'erro', 'mensagem': 'empresa_id não informado'}), 400
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE empresas
            SET status_lancamento_caixinha = NULL,
                arquivo_gerado = NULL,
                revisor = NULL,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (empresa_id,))
        
        # Remove da tabela de baixas para não ficar marcado/riscado na parte de gerente
        cursor.execute('DELETE FROM baixas WHERE empresa_id = ?', (empresa_id,))
        
        conn.commit()
    return jsonify({'status': 'ok'})

@app.route('/caixinha/lancamento/finalizar', methods=['POST'])
def lancamento_finalizar():
    try:
        empresa_id = request.form.get('empresa_id')
        campos_r015_str = request.form.get('campos_r015', '{}')
        campos_r015 = json.loads(campos_r015_str)
        arquivos = request.files.getlist('arquivos[]')

        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,))
            empresa = cursor.fetchone()
            if not empresa:
                return jsonify({'status': 'erro', 'mensagem': 'Empresa não encontrada'}), 404
            status_atual = empresa['status_lancamento_caixinha']
            if status_atual in ('pendente_aprovacao', 'conferido'):
                return jsonify({'status': 'erro', 'mensagem': 'Lançamento já enviado. Somente após rejeição ou desbloqueio pelo admin.'}), 403

        empresa = dict(empresa)
        numero = empresa.get('numero') or ''
        gerente = empresa.get('gerente') or ''
        nome_empresa = empresa.get('nome') or ''

        nome_formatado = f"{numero} - {nome_empresa}" if numero else nome_empresa
        empresa['nome_formatado'] = nome_formatado

        if not str(empresa.get('inscricao_estadual') or '').strip():
            empresa['inscricao_estadual'] = 'BAIXADA'

        # Remove campos fixos do dict — eles serão desenhados no canvas, não via form field
        for campo in list(CAMPOS_FIXOS_PDF.keys()):
            campos_r015.pop(campo, None)

        gerentes_reverso = get_gerentes_reverso()
        letra = gerentes_reverso.get(gerente)
        if not letra:
            return jsonify({'status': 'erro', 'mensagem': 'Gerente inválido'}), 400

        pasta_destino = get_paths_checklist().get(letra)
        if not pasta_destino:
            return jsonify({'status': 'erro', 'mensagem': 'Pasta de destino não configurada'}), 500

        writer = PdfWriter()
        caminho_r015 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'pdf', 'MODELO.pdf')
        reader_r015 = PdfReader(caminho_r015)
        writer.append(reader_r015)

        # 1. Remove campos fixos do AcroForm
        remover_campos_fixos_do_acroform(writer)

        # 2. Desenha dados da empresa diretamente no canvas
        desenhar_campos_fixos_no_pdf(writer, empresa)

        # 3. Preenche os campos editáveis (digitados pelo usuário)
        preencher_e_formatar_pdf(writer, campos_r015, travar_fixos=False, regenerar_ap=True)

        for arquivo in arquivos:
            if arquivo and arquivo.filename.endswith('.pdf'):
                reader_anexo = PdfReader(arquivo)
                writer.append(reader_anexo)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_seguro = re.sub(r'[^a-zA-Z0-9]', '', nome_empresa.replace(' ', ''))
        nome_arquivo = f"{letra} - {numero} - {nome_seguro}_{timestamp}_Unido.pdf"

        pasta_pendentes = PASTA_PENDENTES
        os.makedirs(pasta_pendentes, exist_ok=True)
        caminho_saida = os.path.join(pasta_pendentes, nome_arquivo)

        with open(caminho_saida, "wb") as f:
            writer.write(f)

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE empresas
                SET status_lancamento_caixinha = 'pendente_aprovacao',
                    arquivo_gerado = ?,
                    arquivo_rejeitado = NULL,
                    motivo_rejeicao = NULL,
                    dados_lancamento = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (nome_arquivo, campos_r015_str, empresa_id))
            conn.commit()

        return jsonify({'status': 'ok', 'arquivo': nome_arquivo})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

# --- Rotas de Conferência ---

@app.route('/caixinha/conferencia/salvar-edicao', methods=['POST'])
def conferencia_salvar_edicao():
    """Gerente edita os campos do lançamento e o PDF é regenerado no sistema."""
    try:
        empresa_id = request.form.get('empresa_id')
        campos_str = request.form.get('campos', '{}')
        campos = json.loads(campos_str)

        if not empresa_id:
            return jsonify({'status': 'erro', 'mensagem': 'empresa_id não informado'}), 400

        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM empresas WHERE id = ?', (empresa_id,))
            empresa = cursor.fetchone()
            if not empresa:
                return jsonify({'status': 'erro', 'mensagem': 'Empresa não encontrada'}), 404
            empresa = dict(empresa)

        numero = empresa.get('numero') or ''
        nome_empresa = empresa.get('nome') or ''
        gerente = empresa.get('gerente') or ''
        arquivo_atual = empresa.get('arquivo_gerado') or ''

        nome_formatado = f"{numero} - {nome_empresa}" if numero else nome_empresa
        empresa['nome_formatado'] = nome_formatado
        if not str(empresa.get('inscricao_estadual') or '').strip():
            empresa['inscricao_estadual'] = 'BAIXADA'

        # Remover campos fixos dos dados editáveis (serão desenhados no canvas)
        for campo in list(CAMPOS_FIXOS_PDF.keys()):
            campos.pop(campo, None)

        # Regenerar o PDF
        writer = PdfWriter()
        caminho_modelo = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'pdf', 'MODELO.pdf')
        reader = PdfReader(caminho_modelo)
        writer.append(reader)
        remover_campos_fixos_do_acroform(writer)
        desenhar_campos_fixos_no_pdf(writer, empresa)
        preencher_e_formatar_pdf(writer, campos, travar_fixos=False, regenerar_ap=True)

        pasta_pendentes = PASTA_PENDENTES
        os.makedirs(pasta_pendentes, exist_ok=True)
        
        caminho_saida = None
        if arquivo_atual:
            caminho_saida = os.path.join(pasta_pendentes, arquivo_atual)
            # Adicionar anexos (páginas 2 em diante do arquivo atual)
            if os.path.exists(caminho_saida):
                try:
                    with open(caminho_saida, "rb") as f_atual:
                        pdf_bytes = io.BytesIO(f_atual.read())
                    reader_atual = PdfReader(pdf_bytes)
                    if len(reader_atual.pages) > 1:
                        for i in range(1, len(reader_atual.pages)):
                            writer.add_page(reader_atual.pages[i])
                except Exception as e:
                    print(f"Erro ao tentar reanexar paginas do arquivo atual: {e}")
        else:
            gerentes_reverso = get_gerentes_reverso()
            letra = gerentes_reverso.get(gerente, 'X')
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            nome_seguro = re.sub(r'[^a-zA-Z0-9]', '', nome_empresa.replace(' ', ''))
            arquivo_atual = f"{letra} - {numero} - {nome_seguro}_{ts}_Unido.pdf"
            caminho_saida = os.path.join(pasta_pendentes, arquivo_atual)

        with open(caminho_saida, 'wb') as f:
            writer.write(f)

        # Atualizar dados_lancamento no banco
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE empresas
                SET dados_lancamento = ?,
                    arquivo_gerado = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (json.dumps(campos), arquivo_atual, empresa_id))
            conn.commit()

        return jsonify({'status': 'ok', 'mensagem': 'PDF atualizado com sucesso!'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/conferencia/atualizar-pdf', methods=['POST'])
def conferencia_atualizar_pdf():
    """Gerente faz upload de um PDF editado para substituir o PDF gerado."""
    empresa_id = request.form.get('empresa_id')
    pdf_editado = request.files.get('pdf_editado')

    if not empresa_id or not pdf_editado:
        return jsonify({'status': 'erro', 'mensagem': 'empresa_id e arquivo PDF são obrigatórios'}), 400
    if not pdf_editado.filename.endswith('.pdf'):
        return jsonify({'status': 'erro', 'mensagem': 'Somente arquivos PDF são aceitos'}), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                'SELECT arquivo_gerado, status_lancamento_caixinha FROM empresas WHERE id = ?',
                (empresa_id,)
            )
            emp = cursor.fetchone()
            if not emp or not emp['arquivo_gerado']:
                return jsonify({'status': 'erro', 'mensagem': 'Empresa ou arquivo não encontrado'}), 404

            nome_arquivo = emp['arquivo_gerado']
            status = emp['status_lancamento_caixinha']

            # Localizar o arquivo atual para sobrescrever
            pasta_pendentes = PASTA_PENDENTES
            caminho = os.path.join(pasta_pendentes, nome_arquivo)

            # Se não estiver em pendentes, pode estar na pasta da gerente (já aprovado)
            if not os.path.exists(caminho):
                # Buscar gerente
                cursor.execute('SELECT gerente FROM empresas WHERE id = ?', (empresa_id,))
                g = cursor.fetchone()
                if g:
                    letra = get_gerentes_reverso().get(g['gerente'])
                    pasta_g = get_paths_checklist().get(letra, '')
                    caminho_g = os.path.join(pasta_g, nome_arquivo)
                    if os.path.exists(caminho_g):
                        caminho = caminho_g

            # Salvar PDF editado sobrescrevendo o arquivo original
            pdf_editado.save(caminho)

        return jsonify({'status': 'ok', 'mensagem': 'PDF atualizado com sucesso!'})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/conferencia/api')
def conferencia_api():
    """Retorna empresas com status pendente_aprovacao, filtradas por gerente."""
    gerente = request.args.get('gerente')
    if not gerente:
        return jsonify({'status': 'erro', 'mensagem': 'Gerente não informado'}), 400
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, numero, nome, gerente, status_lancamento_caixinha,
                       arquivo_gerado, arquivo_rejeitado, motivo_rejeicao, atualizado_em
                FROM empresas
                WHERE ativo = 1 AND gerente = ? AND status_lancamento_caixinha = 'pendente_aprovacao'
                ORDER BY atualizado_em DESC
            ''', (gerente,))
            empresas = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'ok', 'data': empresas})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

def get_caminho_pdf_caixinha(row, cursor):
    row_dict = dict(row)
    status = row_dict.get('status_lancamento_caixinha')
    revisor = row_dict.get('revisor')
    gerente = row_dict.get('gerente')
    arquivo = row_dict.get('arquivo_gerado')
    
    if not arquivo: return None
    
    caminho = None
    if status == 'pendente_aprovacao':
        pasta_pendentes = PASTA_PENDENTES
        caminho = os.path.join(pasta_pendentes, arquivo)
    elif status in ('conferido', 'rejeitado') and not revisor:
        gerentes_reverso = get_gerentes_reverso()
        letra = gerentes_reverso.get(gerente)
        pasta = get_paths_checklist().get(letra, '')
        caminho = os.path.join(pasta, arquivo)
    elif revisor:
        cursor.execute('SELECT caminho_pasta FROM revisores WHERE nome = ?', (revisor,))
        rev = cursor.fetchone()
        if rev and rev['caminho_pasta']:
            caminho = os.path.join(resolve_network_path(rev['caminho_pasta']), arquivo)
            
    if not caminho or not os.path.exists(caminho):
        gerentes_reverso = get_gerentes_reverso()
        letra = gerentes_reverso.get(gerente)
        pasta = get_paths_checklist().get(letra, '')
        caminho_fallback = os.path.join(pasta, arquivo)
        if os.path.exists(caminho_fallback):
            caminho = caminho_fallback
            
    return caminho

@app.route('/caixinha/pdf/<int:empresa_id>')
def serve_pdf(empresa_id):
    """Serve o PDF gerado do lançamento para visualização inline."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT gerente, arquivo_gerado, status_lancamento_caixinha, revisor FROM empresas WHERE id = ?', (empresa_id,))
            row = cursor.fetchone()
        if not row or not row['arquivo_gerado']:
            return 'PDF não encontrado', 404
            
        caminho = get_caminho_pdf_caixinha(row, cursor)
        if not caminho or not os.path.exists(caminho):
            return 'Arquivo não encontrado no servidor', 404
        from flask import send_file
        return send_file(caminho, mimetype='application/pdf')
    except Exception as e:
        return str(e), 500

@app.route('/caixinha/pdf_rejeitado/<int:empresa_id>')
def serve_pdf_rejeitado(empresa_id):
    """Serve o PDF anotado pela gerente (após rejeição)."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT gerente, arquivo_rejeitado, arquivo_gerado, status_lancamento_caixinha, revisor FROM empresas WHERE id = ?', (empresa_id,))
            row = cursor.fetchone()
        if not row:
            return 'PDF de rejeição não encontrado', 404
            
        caminho = None
        if row['arquivo_rejeitado']:
            pasta_rejeicao = PASTA_REJEICOES
            caminho = os.path.join(pasta_rejeicao, row['arquivo_rejeitado'])
        elif row['arquivo_gerado']:
            caminho = get_caminho_pdf_caixinha(row, cursor)
            
        if not caminho or not os.path.exists(caminho):
            return 'Arquivo não encontrado no servidor', 404
            
        from flask import send_file
        return send_file(caminho, mimetype='application/pdf')
    except Exception as e:
        return str(e), 500


@app.route('/caixinha/conferencia/aprovar', methods=['POST'])
def conferencia_aprovar():
    """Gerente aprova o lançamento."""
    data = request.get_json()
    empresa_id = data.get('empresa_id')
    if not empresa_id:
        return jsonify({'status': 'erro', 'mensagem': 'empresa_id não informado'}), 400
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT arquivo_gerado, gerente FROM empresas WHERE id = ? AND status_lancamento_caixinha = \'pendente_aprovacao\'', (empresa_id,))
            emp = cursor.fetchone()
            if emp and emp['arquivo_gerado']:
                arquivo_gerado = emp['arquivo_gerado']
                letra = get_gerentes_reverso().get(emp['gerente'])
                pasta_destino = get_paths_checklist().get(letra)
                pasta_pendentes = PASTA_PENDENTES
                
                if pasta_destino:
                    caminho_origem = os.path.join(pasta_pendentes, arquivo_gerado)
                    caminho_destino = os.path.join(pasta_destino, arquivo_gerado)
                    if os.path.exists(caminho_origem):
                        os.makedirs(pasta_destino, exist_ok=True)
                        mover_arquivo(caminho_origem, caminho_destino)

            cursor.execute('''
                UPDATE empresas
                SET status_lancamento_caixinha = 'conferido',
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND status_lancamento_caixinha = 'pendente_aprovacao'
            ''', (empresa_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'status': 'erro', 'mensagem': 'Lançamento não encontrado ou já processado'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/conferencia/encaminhar', methods=['POST'])
def conferencia_encaminhar():
    """Gerente encaminha lançamento conferido para um revisor (Valnei/Yasmin/Marielli)."""
    data = request.get_json()
    empresa_id = data.get('empresa_id')
    revisor = data.get('revisor')
    if not empresa_id or not revisor:
        return jsonify({'status': 'erro', 'mensagem': 'Dados incompletos'}), 400
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT id, caminho_pasta FROM revisores WHERE nome = ?', (revisor,))
        revisor_db = cursor.fetchone()
        if not revisor_db:
            return jsonify({'status': 'erro', 'mensagem': 'Revisor não encontrado'}), 404
            
        cursor.execute('SELECT arquivo_gerado, gerente FROM empresas WHERE id = ? AND status_lancamento_caixinha = \'conferido\'', (empresa_id,))
        emp = cursor.fetchone()
        if emp and emp['arquivo_gerado']:
            arquivo_gerado = emp['arquivo_gerado']
            letra = get_gerentes_reverso().get(emp['gerente'])
            pasta_origem = get_paths_checklist().get(letra)
            pasta_destino = resolve_network_path(revisor_db['caminho_pasta'])
            
            if pasta_origem and pasta_destino:
                caminho_origem = os.path.join(pasta_origem, arquivo_gerado)
                caminho_destino = os.path.join(pasta_destino, arquivo_gerado)
                if os.path.exists(caminho_origem):
                    os.makedirs(pasta_destino, exist_ok=True)
                    mover_arquivo(caminho_origem, caminho_destino)

        cursor.execute('''
            UPDATE empresas
            SET status_lancamento_caixinha = 'pendente_revisao',
                revisor = ?,
                revisor_anterior = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND status_lancamento_caixinha = 'conferido'
        ''', (revisor, emp['gerente'] if emp else None, empresa_id))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({'status': 'erro', 'mensagem': 'Lançamento não encontrado ou não está com status conferido'}), 400
    return jsonify({'status': 'ok'})

@app.route('/caixinha/revisao/api')
def revisao_api():
    """Retorna lançamentos com status pendente_revisao para um revisor específico."""
    revisor = request.args.get('revisor')
    if not revisor:
        return jsonify({'status': 'erro', 'mensagem': 'Revisor não informado'}), 400
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, numero, nome, gerente, revisor, status_lancamento_caixinha,
                       arquivo_gerado, atualizado_em
                FROM empresas
                WHERE ativo = 1 AND revisor = ? AND status_lancamento_caixinha = 'pendente_revisao'
                ORDER BY atualizado_em DESC
            ''', (revisor,))
            empresas = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'ok', 'data': empresas})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/revisao/aprovar', methods=['POST'])
def revisao_aprovar():
    """Revisor aprova o lançamento (muda status para revisado) e opcionalmente Yasmin anexa PDF."""
    empresa_id = request.form.get('empresa_id')
    revisor = request.form.get('revisor')
    arquivo_anexo = request.files.get('arquivo_anexo')
    
    if not empresa_id:
        return jsonify({'status': 'erro', 'mensagem': 'empresa_id não informado'}), 400
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            nome_anexo_salvo = None
            if arquivo_anexo and arquivo_anexo.filename.endswith('.pdf'):
                cursor.execute('SELECT pasta_anexos FROM revisores WHERE nome = ?', (revisor,))
                rev = cursor.fetchone()
                if rev and rev['pasta_anexos']:
                    pasta_anexos = resolve_network_path(rev['pasta_anexos'])
                    os.makedirs(pasta_anexos, exist_ok=True)
                    # Manter o nome original do arquivo enviado pela Yasmin
                    nome_original = re.sub(r'[^\w\s\-.]', '', arquivo_anexo.filename).strip() or 'anexo.pdf'
                    nome_anexo_salvo = nome_original
                    # Se já existir, adicionar timestamp para não sobrescrever
                    if os.path.exists(os.path.join(pasta_anexos, nome_anexo_salvo)):
                        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                        nome_sem_ext = nome_original[:-4] if nome_original.endswith('.pdf') else nome_original
                        nome_anexo_salvo = f'{nome_sem_ext}_{ts}.pdf'
                    arquivo_anexo.save(os.path.join(pasta_anexos, nome_anexo_salvo))
                    
            if nome_anexo_salvo:
                cursor.execute('''
                    UPDATE empresas
                    SET status_lancamento_caixinha = 'revisado',
                        arquivo_anexo_yasmin = ?,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ? AND status_lancamento_caixinha = 'pendente_revisao'
                ''', (nome_anexo_salvo, empresa_id))
            else:
                cursor.execute('''
                    UPDATE empresas
                    SET status_lancamento_caixinha = 'revisado',
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ? AND status_lancamento_caixinha = 'pendente_revisao'
                ''', (empresa_id,))
                
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'status': 'erro', 'mensagem': 'Lançamento não encontrado ou já processado'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/revisao/recusar', methods=['POST'])
def revisao_recusar():
    """Revisor recusa o lançamento e devolve para quem repassou (Gerente ou Revisor Anterior)"""
    data = request.get_json()
    empresa_id = data.get('empresa_id')
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT arquivo_gerado, revisor, revisor_anterior, gerente FROM empresas WHERE id = ? AND status_lancamento_caixinha = \'pendente_revisao\'', (empresa_id,))
            emp = cursor.fetchone()
            
            if emp:
                revisor_anterior = emp['revisor_anterior'] or emp['gerente']
                
                # Mover arquivo de volta
                cursor.execute('SELECT caminho_pasta FROM revisores WHERE nome = ?', (emp['revisor'],))
                rev_atual_db = cursor.fetchone()
                
                pasta_destino = None
                novo_status = 'pendente_aprovacao'
                novo_revisor = None
                
                # Verificar se o revisor anterior é um gerente ou outro revisor
                gerentes_nomes = get_gerentes_nomes()
                if revisor_anterior in gerentes_nomes:
                    letra = get_gerentes_reverso().get(revisor_anterior)
                    pasta_destino = get_paths_checklist().get(letra)
                    novo_status = 'pendente_aprovacao'
                    novo_revisor = None
                else:
                    cursor.execute('SELECT caminho_pasta FROM revisores WHERE nome = ?', (revisor_anterior,))
                    rev_ant_db = cursor.fetchone()
                    if rev_ant_db:
                        pasta_destino = resolve_network_path(rev_ant_db['caminho_pasta'])
                    novo_status = 'pendente_revisao'
                    novo_revisor = revisor_anterior
                
                if rev_atual_db and rev_atual_db['caminho_pasta'] and pasta_destino and emp['arquivo_gerado']:
                    caminho_origem = os.path.join(resolve_network_path(rev_atual_db['caminho_pasta']), emp['arquivo_gerado'])
                    caminho_destino = os.path.join(pasta_destino, emp['arquivo_gerado'])
                    if os.path.exists(caminho_origem):
                        os.makedirs(pasta_destino, exist_ok=True)
                        mover_arquivo(caminho_origem, caminho_destino)
                
                cursor.execute('''
                    UPDATE empresas
                    SET status_lancamento_caixinha = ?,
                        revisor = ?,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ? AND status_lancamento_caixinha = 'pendente_revisao'
                ''', (novo_status, novo_revisor, empresa_id))
                conn.commit()
                if cursor.rowcount == 0:
                    return jsonify({'status': 'erro', 'mensagem': 'Lançamento não encontrado ou já processado'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/revisao/encaminhar-yasmin', methods=['POST'])
def revisao_encaminhar_yasmin():
    """Valnei ou Marielli encaminham o lançamento para Yasmin finalizar."""
    data = request.get_json()
    empresa_id = data.get('empresa_id')
    revisor_atual = data.get('revisor_atual')
    if revisor_atual not in ('Valnei', 'Marielli'):
        return jsonify({'status': 'erro', 'mensagem': 'Somente Valnei ou Marielli podem encaminhar para Yasmin'}), 403
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT arquivo_gerado FROM empresas WHERE id = ? AND status_lancamento_caixinha = \'pendente_revisao\' AND revisor = ?', (empresa_id, revisor_atual))
            emp = cursor.fetchone()
            
            cursor.execute('SELECT caminho_pasta FROM revisores WHERE nome = ?', (revisor_atual,))
            rev_atual_db = cursor.fetchone()
            
            cursor.execute('SELECT caminho_pasta FROM revisores WHERE nome = \'Yasmin\'')
            yasmin_db = cursor.fetchone()
            
            if emp and emp['arquivo_gerado'] and rev_atual_db and yasmin_db:
                arquivo_gerado = emp['arquivo_gerado']
                pasta_origem = resolve_network_path(rev_atual_db['caminho_pasta'])
                pasta_destino = resolve_network_path(yasmin_db['caminho_pasta'])
                if pasta_origem and pasta_destino:
                    caminho_origem = os.path.join(pasta_origem, arquivo_gerado)
                    caminho_destino = os.path.join(pasta_destino, arquivo_gerado)
                    if os.path.exists(caminho_origem):
                        os.makedirs(pasta_destino, exist_ok=True)
                        mover_arquivo(caminho_origem, caminho_destino)

            cursor.execute('''
                UPDATE empresas
                SET revisor = 'Yasmin',
                    revisor_anterior = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND revisor = ? AND status_lancamento_caixinha = 'pendente_revisao'
            ''', (revisor_atual, empresa_id, revisor_atual))
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'status': 'erro', 'mensagem': 'Lançamento não encontrado ou já processado'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/revisao/visao-geral')
def revisao_visao_geral():
    """Retorna todos os lançamentos em revisão (pendente_revisao), agrupados por revisor.
    Usado pelas gerentes para acompanhamento. Não requer autenticação de sessão pois
    a auth já é feita no cliente via senha de gerente no localStorage."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, numero, nome, gerente, revisor, status_lancamento_caixinha, atualizado_em
                FROM empresas
                WHERE ativo = 1 AND status_lancamento_caixinha = 'pendente_revisao'
                ORDER BY revisor, atualizado_em DESC
            ''')
            empresas = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'ok', 'data': empresas})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/caixinha/conferencia/rejeitar', methods=['POST'])
def conferencia_rejeitar():
    """Gerente rejeita o lançamento, opcionalmente enviando PDF anotado."""
    empresa_id = request.form.get('empresa_id')
    motivo = request.form.get('motivo', '')
    arquivo_anotado = request.files.get('arquivo_anotado')
    if not empresa_id:
        return jsonify({'status': 'erro', 'mensagem': 'empresa_id não informado'}), 400
    try:
        nome_arquivo_anotado = None
        if arquivo_anotado and arquivo_anotado.filename.endswith('.pdf'):
            pasta_rejeicao = PASTA_REJEICOES
            os.makedirs(pasta_rejeicao, exist_ok=True)
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            nome_arquivo_anotado = f'rejeicao_{empresa_id}_{ts}.pdf'
            arquivo_anotado.save(os.path.join(pasta_rejeicao, nome_arquivo_anotado))
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE empresas
                SET status_lancamento_caixinha = 'rejeitado',
                    arquivo_rejeitado = ?,
                    motivo_rejeicao = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND status_lancamento_caixinha = 'pendente_aprovacao'
            ''', (nome_arquivo_anotado, motivo, empresa_id))
            
            linhas_afetadas = cursor.rowcount
            
            # Remove da tabela de baixas para não ficar riscado no painel
            cursor.execute('DELETE FROM baixas WHERE empresa_id = ?', (empresa_id,))
            
            conn.commit()
            if linhas_afetadas == 0:
                return jsonify({'status': 'erro', 'mensagem': 'Lançamento não encontrado ou já processado'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500

@app.route('/api/gerentes', methods=['GET'])
def api_gerentes():
    try:
        gerentes = get_gerentes_config()
        # Não enviar senhas por segurança
        for g in gerentes:
            g.pop('senha', None)
        return jsonify({'success': True, 'data': gerentes})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/revisores', methods=['GET'])
def api_revisores():
    """Retorna lista de revisores (sem senha) para o frontend."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT id, nome FROM revisores ORDER BY nome')
            revisores = [dict(row) for row in cursor.fetchall()]
        return jsonify({'success': True, 'data': revisores})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/revisores/login', methods=['POST'])
def api_revisores_login():
    """Valida senha de revisor."""
    dados = request.json
    nome = dados.get('nome')
    senha = dados.get('senha')
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM revisores WHERE nome=? AND senha=?', (nome, senha))
        if cursor.fetchone():
            return jsonify({'success': True})
        return jsonify({'success': False})

@app.route('/api/gerentes/login', methods=['POST'])
def api_gerentes_login():
    dados = request.json
    nome = dados.get('nome')
    senha = dados.get('senha')
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM gerentes WHERE nome=? AND senha=?", (nome, senha))
        if cursor.fetchone():
            return jsonify({'success': True})
        return jsonify({'success': False})

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    return render_template('admin_dashboard.html')

@app.route('/admin/gerentes', methods=['GET', 'POST'])
@login_required
def admin_gerentes():
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        nome = request.form.get('nome')
        letra = request.form.get('letra')
        senha = request.form.get('senha')
        caminho_pasta = request.form.get('caminho_pasta')
        
        try:
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                if action == 'add':
                    cursor.execute('INSERT INTO gerentes (nome, letra, senha, caminho_pasta) VALUES (?, ?, ?, ?)',
                                   (nome, letra, senha, caminho_pasta))
                elif action == 'edit':
                    gid = request.form.get('id')
                    cursor.execute('UPDATE gerentes SET nome=?, letra=?, senha=?, caminho_pasta=? WHERE id=?',
                                   (nome, letra, senha, caminho_pasta, gid))
                elif action == 'delete':
                    gid = request.form.get('id')
                    cursor.execute('DELETE FROM gerentes WHERE id=?', (gid,))
                conn.commit()
            return redirect(url_for('admin_gerentes'))
        except Exception as e:
            return f"Erro: {str(e)}", 400

    gerentes = get_gerentes_config()
    return render_template('admin_gerentes.html', gerentes=gerentes)

@app.route('/admin/revisores', methods=['GET', 'POST'])
@login_required
def admin_revisores():
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        caminho_pasta = request.form.get('caminho_pasta')
        pasta_anexos = request.form.get('pasta_anexos')
        
        try:
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                if action == 'add':
                    cursor.execute('INSERT INTO revisores (nome, senha, caminho_pasta, pasta_anexos) VALUES (?, ?, ?, ?)',
                                   (nome, senha, caminho_pasta, pasta_anexos))
                elif action == 'edit':
                    rid = request.form.get('id')
                    cursor.execute('UPDATE revisores SET nome=?, senha=?, caminho_pasta=?, pasta_anexos=? WHERE id=?',
                                   (nome, senha, caminho_pasta, pasta_anexos, rid))
                elif action == 'delete':
                    rid = request.form.get('id')
                    cursor.execute('DELETE FROM revisores WHERE id=?', (rid,))
                conn.commit()
            return redirect(url_for('admin_revisores'))
        except Exception as e:
            return f"Erro: {str(e)}", 400

    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM revisores ORDER BY nome")
        revisores = [dict(row) for row in cursor.fetchall()]
        
    return render_template('admin_revisores.html', revisores=revisores)

@app.route('/checklist')
def checklist_index():
    return render_template('checklist.html', 
                         logado='usuario_id' in session,
                         usuario_atual=session.get('usuario_id'),
                         is_admin=session.get('is_admin', False))

@app.route('/checklist/api', methods=['GET'])
def checklist_api():
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Buscar empresas e verificar se possuem baixa recente (ex: hoje ou sempre).
            # O briefing não especificou período de reset automático, só manual.
            # Vamos verificar se existe registro na tabela baixas.
            cursor.execute('''
                SELECT e.*, 
                       (SELECT COUNT(1) FROM baixas b WHERE b.empresa_id = e.id) as tem_baixa
                FROM empresas e
                WHERE e.ativo = 1
            ''')
            empresas = [dict(row) for row in cursor.fetchall()]
            
            # Agrupar por gerente
            dados = {nome: [] for nome in get_gerentes_nomes()}
            for emp in empresas:
                gerente = emp['gerente']
                if gerente not in dados:
                    dados[gerente] = []
                dados[gerente].append(emp)
                    
            return jsonify({'success': True, 'data': dados})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/checklist/reset', methods=['POST'])
@login_required
def checklist_reset():
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Acesso negado'}), 403
        
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Antes de resetar, apagar os arquivos PDFs gerados na pasta pendentes
            cursor.execute('SELECT arquivo_gerado FROM empresas WHERE arquivo_gerado IS NOT NULL')
            arquivos = cursor.fetchall()
            pasta_pendentes = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'pdf', 'pendentes')
            for row in arquivos:
                nome_arq = row['arquivo_gerado']
                caminho = os.path.join(pasta_pendentes, nome_arq)
                if os.path.exists(caminho):
                    try:
                        os.remove(caminho)
                    except Exception:
                        pass

            cursor.execute('DELETE FROM baixas')
            cursor.execute('UPDATE empresas SET ativo = 1')
            # Limpar dados de lançamento da caixinha para o novo ciclo
            cursor.execute('''
                UPDATE empresas
                SET status_lancamento_caixinha = NULL,
                    arquivo_gerado = NULL,
                    arquivo_rejeitado = NULL,
                    motivo_rejeicao = NULL,
                    dados_lancamento = NULL,
                    revisor = NULL,
                    revisor_anterior = NULL,
                    arquivo_anexo_yasmin = NULL,
                    atualizado_em = NULL
            ''')
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/checklist/admin', methods=['GET', 'POST'])
@login_required
def checklist_admin():
    if not session.get('is_admin'):
        return "Acesso negado", 403
        
    if request.method == 'POST':
        nome = request.form.get('nome')
        numero = request.form.get('numero')
        gerente = request.form.get('gerente')
        cnpj = request.form.get('cnpj', '')
        inscricao = request.form.get('inscricao', '')
        tributacao = request.form.get('tributacao', '')
        
        if nome and numero and gerente in get_gerentes_nomes():
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM empresas WHERE numero = ? AND gerente = ?', (numero, gerente))
                row = cursor.fetchone()
                if not row:
                    cursor.execute('''
                        INSERT INTO empresas (nome, numero, gerente, cnpj, inscricao_estadual, tributacao) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (nome, numero, gerente, cnpj, inscricao, tributacao))
                else:
                    cursor.execute('''
                        UPDATE empresas 
                        SET nome = ?, cnpj = ?, inscricao_estadual = ?, tributacao = ?
                        WHERE id = ?
                    ''', (nome, cnpj, inscricao, tributacao, row[0]))
                conn.commit()
        return redirect(url_for('checklist_admin'))
        
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM empresas ORDER BY gerente, nome')
        empresas = cursor.fetchall()

    # Resultado de importação (passado via session)
    import_resultado = None
    if 'inseridos' in request.args:
        import_resultado = {
            'inseridos': int(request.args.get('inseridos', 0)),
            'atualizados': int(request.args.get('atualizados', 0)),
            'ignorados': int(request.args.get('ignorados', 0)),
        }
    import_log = session.pop('import_log', None)

    return render_template('checklist_admin.html',
                           empresas=empresas,
                           gerentes_nomes=get_gerentes_nomes(),
                           import_resultado=import_resultado,
                           import_log=import_log)

@app.route('/checklist/admin/delete/<int:id>', methods=['POST'])
@login_required
def checklist_admin_delete(id):
    if not session.get('is_admin'):
        return "Acesso negado", 403
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM baixas WHERE empresa_id = ?', (id,))
        cursor.execute('DELETE FROM empresas WHERE id = ?', (id,))
        conn.commit()
    return redirect(url_for('checklist_admin'))

@app.route('/checklist/admin/delete-multiple', methods=['POST'])
@login_required
def checklist_admin_delete_multiple():
    if not session.get('is_admin'):
        return "Acesso negado", 403
    ids = request.form.getlist('ids')
    if ids:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' for _ in ids)
            cursor.execute(f'DELETE FROM baixas WHERE empresa_id IN ({placeholders})', ids)
            cursor.execute(f'DELETE FROM empresas WHERE id IN ({placeholders})', ids)
            conn.commit()
    return redirect(url_for('checklist_admin'))

@app.route('/checklist/admin/import', methods=['POST'])
@login_required
def checklist_admin_import():
    if not session.get('is_admin'):
        return "Acesso negado", 403

    csv_data = request.form.get('csv_data', '')
    if not csv_data.strip():
        return redirect(url_for('checklist_admin'))

    linhas = csv_data.strip().split('\n')
    gerentes_map = get_gerentes_map()  # { 'S': 'Sandra', 'A': 'Adriana', ... }

    inseridos_lista  = []
    atualizados_lista = []
    ignorados_lista  = []

    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        for i, linha in enumerate(linhas, 1):
            linha_orig = linha.strip()
            if not linha_orig:
                continue

            # Tenta separar por vírgula, ponto e vírgula, ou traço
            # E escolhe o separador que resultar em mais colunas
            p_virgula = [p.strip() for p in linha_orig.split(',')]
            p_ponto_virgula = [p.strip() for p in linha_orig.split(';')]
            p_traco = [p.strip() for p in linha_orig.split(' - ')]
            
            partes = max([p_virgula, p_ponto_virgula, p_traco], key=len)

            if len(partes) < 3:
                ignorados_lista.append({'linha': i, 'raw': linha_orig, 'motivo': 'Menos de 3 campos'})
                continue

            letra      = partes[0].upper()
            numero_raw = partes[1]
            nome       = partes[2]
            cnpj       = partes[3] if len(partes) > 3 else ''
            inscricao  = partes[4] if len(partes) > 4 else ''
            tributacao = partes[5] if len(partes) > 5 else ''

            # Ignorar linhas sem nome
            if not nome:
                ignorados_lista.append({'linha': i, 'raw': linha_orig, 'motivo': 'Nome vazio'})
                continue

            # Ignorar linhas sem gerente válido
            if not letra:
                ignorados_lista.append({'linha': i, 'raw': linha_orig, 'motivo': 'Letra de gerente vazia', 'nome': nome})
                continue
            gerente = gerentes_map.get(letra)
            if not gerente:
                ignorados_lista.append({'linha': i, 'raw': linha_orig, 'motivo': f"Gerente '{letra}' não encontrado", 'nome': nome})
                continue

            # Remove sufixo do número: 99-1 → 99, 99-2 → 99, 4-5 → 4
            numero = re.sub(r'-\d+$', '', numero_raw)

            # Busca por valor numérico para tratar zero à esquerda:
            # CSV tem '9', banco tem '09' → CAST compara como inteiros (9 == 9)
            try:
                numero_int = int(numero)
                num_cond = "CAST(numero AS INTEGER) = ?"
                num_val = numero_int
            except ValueError:
                num_cond = "numero = ?"
                num_val = numero

            # Para diferenciar matriz/filial com o mesmo número, usamos CNPJ (ou nome se não tiver CNPJ)
            if cnpj:
                cursor.execute(
                    f'SELECT id FROM empresas WHERE {num_cond} AND gerente = ? AND cnpj = ?',
                    (num_val, gerente, cnpj)
                )
            else:
                cursor.execute(
                    f'SELECT id FROM empresas WHERE {num_cond} AND gerente = ? AND nome = ?',
                    (num_val, gerente, nome)
                )
            row = cursor.fetchone()
            item = {'nome': nome, 'numero': numero, 'gerente': gerente, 'cnpj': cnpj, 'tributacao': tributacao}
            if not row:
                cursor.execute('''
                    INSERT INTO empresas (nome, numero, gerente, cnpj, inscricao_estadual, tributacao)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (nome, numero, gerente, cnpj, inscricao, tributacao))
                inseridos_lista.append(item)
            else:
                cursor.execute('''
                    UPDATE empresas
                    SET nome = ?, cnpj = ?, inscricao_estadual = ?, tributacao = ?
                    WHERE id = ?
                ''', (nome, cnpj, inscricao, tributacao, row[0]))
                atualizados_lista.append(item)

        conn.commit()

    # O cookie de sessão tem limite de 4KB. Não podemos salvar 300 empresas aqui, 
    # então salvamos apenas as que deram erro (ignorados) para mostrar na tela.
    session['import_log'] = {
        'ignorados': ignorados_lista[:50], # Limita a 50 para não quebrar a sessão
    }

    return redirect(url_for('checklist_admin',
                            inseridos=len(inseridos_lista),
                            atualizados=len(atualizados_lista),
                            ignorados=len(ignorados_lista)))
# --------------------------

if __name__ == '__main__':
    HOST = '0.0.0.0'
    PORT = 5001
    print()
    print('=' * 48)
    print('  SCALCO CONTABILIDADE — Servidor iniciado')
    print(f'  Acesso local:  http://127.0.0.1:{PORT}')
    print(f'  Acesso na rede: http://{HOST}:{PORT}')
    print('=' * 48)
    print()
    app.run(debug=True, host=HOST, port=PORT)