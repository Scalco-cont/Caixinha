/* ============================================================
   lancamento.js — Lógica da página de Lançamento Caixinha
   ============================================================ */

let globalEmpresaId = null;
let globalGerentes = [];
const IS_ADMIN = document.body.getAttribute('data-is-admin') === 'true';

// --- Filtros com persistência em localStorage ---
const LS_GERENTE = 'lancamento_filter_gerente';
const LS_QTD = 'lancamento_itemsPerPage';
const LS_PENDENTES = 'lancamento_showOnlyPendentes';

let globalEmpresas = [];
let filtroGerente = localStorage.getItem(LS_GERENTE) || 'Todos';
let itemsPerPage = parseInt(localStorage.getItem(LS_QTD) || '0');
let showOnlyPendentes = localStorage.getItem(LS_PENDENTES) === 'true';
let currentPage = 1;

// --- Rascunho automático ---
let _rascunhoTimer = null;          // timer do debounce
let _rascunhoEmAndamento = false;   // evita saves simultâneos

/**
 * Lê todos os inputs do overlay e retorna o objeto de campos.
 */
function coletarCamposPDF() {
    const campos = {};
    document.querySelectorAll('#pdf-annotations input[data-pdf-field]').forEach(inp => {
        campos[inp.getAttribute('data-pdf-field')] = inp.value;
    });
    return campos;
}

/**
 * Salva os campos atuais como rascunho no banco de dados.
 * Não altera o status da empresa se já estiver em aprovação.
 */
function salvarRascunho(callback) {
    if (!globalEmpresaId) { if (callback) callback(); return; }
    if (_rascunhoEmAndamento) { if (callback) callback(); return; }

    const campos = coletarCamposPDF();
    _rascunhoEmAndamento = true;

    fetch('/caixinha/lancamento/salvar-rascunho', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ empresa_id: globalEmpresaId, campos: campos })
    })
        .then(r => r.json())
        .then(data => {
            _rascunhoEmAndamento = false;
            if (data.status === 'ok') {
                mostrarIndicadorRascunho();
                // Atualiza o cache local para que ao reabrir os dados apareçam
                valoresSalvosGlobais = campos;
            }
            if (callback) callback();
        })
        .catch(() => {
            _rascunhoEmAndamento = false;
            if (callback) callback();
        });
}

function salvarRascunhoManual() {
    salvarRascunho(() => {
        showMessage('Rascunho salvo com sucesso!', true);
    });
}

/**
 * Agenda um save com debounce de 1.5s.
 * Cada nova digitação reinicia o timer.
 */
function agendarRascunho() {
    clearTimeout(_rascunhoTimer);
    _rascunhoTimer = setTimeout(() => salvarRascunho(), 1500);
}

/**
 * Exibe o indicador "Rascunho salvo" com fade-out.
 */
function mostrarIndicadorRascunho() {
    const el = document.getElementById('draft-saved-indicator');
    if (!el) return;
    el.style.opacity = '1';
    el.style.transition = 'none';
    clearTimeout(el._fadeTimer);
    el._fadeTimer = setTimeout(() => {
        el.style.transition = 'opacity 1.2s ease';
        el.style.opacity = '0';
    }, 2000);
}

// Salva o rascunho ao fechar a aba/janela via sendBeacon (fire-and-forget)
window.addEventListener('beforeunload', () => {
    if (!globalEmpresaId) return;
    const campos = coletarCamposPDF();
    const payload = JSON.stringify({ empresa_id: globalEmpresaId, campos: campos });
    navigator.sendBeacon('/caixinha/lancamento/salvar-rascunho', new Blob([payload], { type: 'application/json' }));
});

// PDF.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';

// --- Inicialização ---
document.addEventListener('DOMContentLoaded', () => {
    restaurarFiltros();
    carregarGerentesLista().then(() => {
        carregarEmpresas();
    });
    setupDragAndDrop();
});

function carregarGerentesLista() {
    return fetch('/caixinha/lancamento/gerentes')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                globalGerentes = data.data.map(g => g.nome);
                const select = document.getElementById('filter-gerente');
                if (select) {
                    // Mantenho a primeira option
                    const currentVal = select.value;
                    select.innerHTML = '<option value="Todos">Todos os Gerentes</option>';
                    globalGerentes.forEach(nome => {
                        const opt = document.createElement('option');
                        opt.value = nome;
                        opt.textContent = nome;
                        select.appendChild(opt);
                    });
                    if (globalGerentes.includes(filtroGerente)) {
                        select.value = filtroGerente;
                    }
                }
            }
        });
}

function restaurarFiltros() {
    const gerenteEl = document.getElementById('filter-gerente');
    const qtdEl = document.getElementById('filter-quantidade');
    const pendEl = document.getElementById('showOnlyPendentes');

    if (gerenteEl) gerenteEl.value = filtroGerente;
    if (qtdEl) qtdEl.value = itemsPerPage;
    if (pendEl) pendEl.checked = showOnlyPendentes;
}

// ---- MENSAGEM ----
function showMessage(text, isSuccess) {
    const msg = document.getElementById('message');
    if (!msg) return;
    msg.textContent = text;
    msg.className = isSuccess ? 'msg-success' : 'msg-error';
    msg.style.display = 'block';
    setTimeout(() => { msg.style.display = 'none'; }, 4000);
}

// ---- FASE 1: LISTAGEM ----
function carregarEmpresas() {
    fetch('/caixinha/lancamento/empresas?quantidade=todos')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                globalEmpresas = data.data;
                renderizarCards();
            } else {
                document.getElementById('managers-grid').innerHTML =
                    '<p style="color:red;text-align:center">Erro ao carregar empresas.</p>';
            }
        })
        .catch(err => {
            console.error("Erro ao carregar empresas:", err);
            document.getElementById('managers-grid').innerHTML =
                '<p style="color:red;text-align:center">Falha de rede ao carregar empresas.</p>';
        });
}

function aplicarFiltros() {
    filtroGerente = document.getElementById('filter-gerente').value;
    localStorage.setItem(LS_GERENTE, filtroGerente);
    currentPage = 1;
    renderizarCards();
}

function togglePendentes() {
    showOnlyPendentes = document.getElementById('showOnlyPendentes').checked;
    localStorage.setItem(LS_PENDENTES, showOnlyPendentes);
    currentPage = 1;
    renderizarCards();
}

function changeItemsPerPage() {
    itemsPerPage = parseInt(document.getElementById('filter-quantidade').value);
    localStorage.setItem(LS_QTD, itemsPerPage);
    currentPage = 1;
    renderizarCards();
}

function getFilteredData() {
    let filtered = {};
    globalGerentes.forEach(g => filtered[g] = []);

    const searchStr = (document.getElementById('search-lancamento')?.value || '').toLowerCase();

    for (let i = 0; i < globalEmpresas.length; i++) {
        let emp = globalEmpresas[i];
        if (filtroGerente !== 'Todos' && emp.gerente !== filtroGerente) continue;

        if (showOnlyPendentes) {
            const st = emp.status_lancamento_caixinha;
            if (st === 'conferido' || st === 'finalizado' || st === 'pendente_revisao' || st === 'revisado') continue;
        }

        const num = (emp.numero || '').toLowerCase();
        const nom = (emp.nome || '').toLowerCase();
        if (searchStr && !nom.includes(searchStr) && !num.includes(searchStr)) continue;

        if (!filtered[emp.gerente]) filtered[emp.gerente] = [];
        filtered[emp.gerente].push(emp);
    }
    return filtered;
}

function prevPage() {
    if (currentPage > 1) { currentPage--; renderizarCards(); }
}

function nextPage() {
    const fd = getFilteredData();
    let maxItems = 0;
    globalGerentes.forEach(g => {
        if ((fd[g] || []).length > maxItems) maxItems = (fd[g] || []).length;
    });
    if (itemsPerPage > 0 && currentPage * itemsPerPage < maxItems) {
        currentPage++; renderizarCards();
    }
}

function renderizarCards() {
    const grid = document.getElementById('managers-grid');
    if (!grid) return;
    grid.innerHTML = '';

    const fd = getFilteredData();
    let maxItems = 0;
    globalGerentes.forEach(g => {
        if ((fd[g] || []).length > maxItems) maxItems = (fd[g] || []).length;
    });

    const totalPages = itemsPerPage > 0 ? Math.ceil(maxItems / itemsPerPage) : 1;
    if (currentPage > totalPages && totalPages > 0) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    const pageInfoEl = document.getElementById('pageInfo');
    if (pageInfoEl) pageInfoEl.textContent = `Página ${currentPage} de ${totalPages || 1}`;

    const gerentesVisiveis = filtroGerente === 'Todos' ? globalGerentes : [filtroGerente];
    grid.style.gridTemplateColumns = filtroGerente === 'Todos' ? 'repeat(3, 1fr)' : '1fr';

    gerentesVisiveis.forEach(gerente => {
        const empsGerente = fd[gerente] || [];

        const totalPendentes = globalEmpresas.filter(e => {
            const s = e.status_lancamento_caixinha;
            return e.gerente === gerente && s !== 'conferido' && s !== 'finalizado' && s !== 'pendente_revisao' && s !== 'revisado';
        }).length;
        const totalManager = globalEmpresas.filter(e => e.gerente === gerente).length;

        const card = document.createElement('div');
        card.className = 'manager-card';

        let html = `
            <div class="manager-card-header">
                <h2>${gerente}</h2>
                <span class="badge">${totalPendentes}/${totalManager} PEND.</span>
            </div>
            <div class="manager-card-body">
                <ul class="company-list">
        `;

        if (empsGerente.length === 0) {
            html += `<li style="text-align:center;color:#aaa;padding:10px;">Nenhuma empresa encontrada</li>`;
        } else {
            let listaExibir = empsGerente;
            if (itemsPerPage > 0) {
                const startIndex = (currentPage - 1) * itemsPerPage;
                listaExibir = empsGerente.slice(startIndex, startIndex + itemsPerPage);
            }

            listaExibir.forEach(emp => {
                const st = emp.status_lancamento_caixinha;
                let statusText = 'Pendente';
                let statusClass = 'status-pendente';

                if (st === 'em_andamento') {
                    statusText = 'Em Andamento'; statusClass = 'status-andamento';
                } else if (st === 'finalizado' || st === 'conferido' || st === 'pendente_revisao' || st === 'revisado') {
                    statusText = 'Conferido ✅'; statusClass = 'status-finalizado';
                } else if (st === 'pendente_aprovacao') {
                    statusText = 'Aguardando Conferência ⏳'; statusClass = 'status-aguardando';
                } else if (st === 'rejeitado') {
                    statusText = 'Rejeitado ❌'; statusClass = 'status-rejeitado';
                }

                const isConferido = st === 'conferido' || st === 'finalizado' || st === 'pendente_revisao' || st === 'revisado';
                const isAguardando = st === 'pendente_aprovacao';
                const isRejeitado = st === 'rejeitado';
                const bloqueado = isConferido || isAguardando;

                const numSpan = `<span style="font-size:11px;font-weight:bold;color:#ff0000;background:#fff0f0;border:1px solid #fcc;padding:2px 7px;border-radius:4px;margin-right:10px;flex-shrink:0;">${emp.numero || ''}</span>`;

                // Botão de download do PDF corrigido (só aparece quando rejeitado)
                const btnDownload = isRejeitado
                    ? `<a href="/caixinha/pdf_rejeitado/${emp.id}" target="_blank"
                           onclick="event.stopPropagation()"
                           style="margin-left:8px;font-size:11px;padding:2px 8px;background:#f59e0b;color:#fff;
                                  border:none;border-radius:4px;cursor:pointer;text-decoration:none;display:inline-block;">
                           📄 Ver Correções</a>`
                    : '';

                // Botão de reabrir para admin (apenas quando conferido/finalizado)
                const btnReabrir = isConferido && IS_ADMIN
                    ? `<button onclick="desbloquearEmpresa(event,${emp.id})" style="margin-left:8px;font-size:11px;padding:2px 8px;background:#e74c3c;color:#fff;border:none;border-radius:4px;cursor:pointer;">Reabrir</button>`
                    : '';

                if (bloqueado && !IS_ADMIN) {
                    html += `
                        <li class="company-item" style="cursor:default;opacity:0.65;display:flex;align-items:center;" title="${statusText}">
                            ${numSpan}
                            <span class="company-name" style="flex:1;">${emp.nome || ''}</span>
                            <span class="status-icon ${statusClass}">${statusText}</span>
                        </li>`;
                } else if (bloqueado && IS_ADMIN) {
                    html += `
                        <li class="company-item" style="cursor:default;display:flex;align-items:center;">
                            ${numSpan}
                            <span class="company-name" style="flex:1;">${emp.nome || ''}</span>
                            <span class="status-icon ${statusClass}">${statusText}</span>
                            ${btnReabrir}
                        </li>`;
                } else if (isRejeitado) {
                    // Rejeitado: pode clicar para reenviar, mas mostra botão de download
                    const safeNome = (emp.nome || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    const safeCnpj = (emp.cnpj || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    const safeIe = (emp.inscricao_estadual || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    const safeTrib = (emp.tributacao || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    html += `
                        <li class="company-item" style="display:flex;align-items:center;background:#fff5f5;border-left:4px solid #dc2626;" onclick="iniciarPreenchimento(${emp.id},'${safeNome}','${safeCnpj}','${safeIe}','${safeTrib}')">
                            ${numSpan}
                            <span class="company-name" style="flex:1;">${emp.nome || ''}</span>
                            <span class="status-icon ${statusClass}">${statusText}</span>
                            ${btnDownload}
                        </li>`;
                } else {
                    const safeNome = (emp.nome || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    const safeCnpj = (emp.cnpj || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    const safeIe = (emp.inscricao_estadual || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    const safeTrib = (emp.tributacao || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");

                    html += `
                        <li class="company-item" style="display:flex;align-items:center;" onclick="iniciarPreenchimento(${emp.id},'${safeNome}','${safeCnpj}','${safeIe}','${safeTrib}')">
                            ${numSpan}
                            <span class="company-name" style="flex:1;">${emp.nome || ''}</span>
                            <span class="status-icon ${statusClass}">${statusText}</span>
                        </li>`;
                }
            });
        }

        html += `</ul></div>`;
        card.innerHTML = html;
        grid.appendChild(card);
    });
}

// ---- FASE 2: WIZARD PASSO 1 (PDF) ----
let pdfDoc = null;
let currentScale = 1.3;
const SCALE_MIN = 0.6;
const SCALE_MAX = 3.0;
const SCALE_DEFAULT = 1.3;

function ajustarZoom(delta) {
    const novoScale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, currentScale + delta));
    if (novoScale === currentScale) return;
    currentScale = novoScale;
    document.getElementById('zoom-label').textContent = Math.round(currentScale * 100) + '%';
    if (pdfDoc) rerenderizarPagina();
}

function resetarZoom() {
    currentScale = SCALE_DEFAULT;
    document.getElementById('zoom-label').textContent = Math.round(currentScale * 100) + '%';
    if (pdfDoc) rerenderizarPagina();
}

let globalEmpresaData = {};
let valoresSalvosGlobais = {};

async function iniciarPreenchimento(empresaId, empresaNome, cnpj, inscricao, tributacao) {
    globalEmpresaId = empresaId;
    globalEmpresaData = { nome: empresaNome, cnpj: cnpj, inscricao: inscricao, tributacao: tributacao };

    document.getElementById('empresa-nome-title').textContent = empresaNome;

    document.getElementById('view-lista').style.display = 'none';
    document.getElementById('view-form').style.display = 'block';
    document.getElementById('view-anexos').style.display = 'none';

    document.getElementById('pdf-annotations').innerHTML = '';
    document.getElementById('chk-so-caixinha').checked = false;
    toggleUploadArea();

    // Buscar dados preenchidos anteriormente (se houver, ex: rejeição)
    try {
        const r = await fetch('/caixinha/lancamento/dados/' + empresaId);
        const data = await r.json();
        valoresSalvosGlobais = (data.success && data.data) ? data.data : {};
    } catch (e) {
        valoresSalvosGlobais = {};
    }

    renderizarPDF();
}

function voltarParaLista() {
<<<<<<< HEAD
    // Salva rascunho antes de sair, depois volta para a lista
    clearTimeout(_rascunhoTimer);
    salvarRascunho(() => {
        document.getElementById('view-form').style.display = 'none';
        document.getElementById('view-anexos').style.display = 'none';
        document.getElementById('view-lista').style.display = 'block';
        globalEmpresaId = null;
    });
=======
    document.getElementById('view-form').style.display = 'none';
    document.getElementById('view-anexos').style.display = 'none';
    document.getElementById('view-lista').style.display = 'block';
    globalEmpresaId = null;
>>>>>>> 4bf72fcc7a5b4239890f734e3bb81d5854b9e203
}

function renderizarPDF() {
    const loading = document.getElementById('loading-pdf');
    const container = document.getElementById('pdf-container');

    loading.style.display = 'block';
    container.style.display = 'none';
    loading.textContent = 'Carregando formulário…';

    // Solicita ao servidor o PDF já com os campos da empresa preenchidos e travados
    fetch(`/caixinha/lancamento/prefill/${globalEmpresaId}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) throw new Error(data.message || 'Erro no servidor');

            // Converte base64 → Uint8Array para o pdf.js
            const raw = atob(data.pdf_base64);
            const arr = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);

            return pdfjsLib.getDocument({ data: arr }).promise;
        })
        .then(doc => {
            pdfDoc = doc;
            rerenderizarPagina();
        })
        .catch(err => {
            loading.textContent = 'Erro ao carregar formulário: ' + err.message;
            console.error(err);
        });
}

function rerenderizarPagina() {
    const loading = document.getElementById('loading-pdf');
    const container = document.getElementById('pdf-container');
    const canvas = document.getElementById('pdf-canvas');
    const ctx = canvas.getContext('2d');

    loading.style.display = 'block';
    loading.textContent = 'Renderizando…';
    container.style.display = 'none';

    // Preservar valores já digitados nos campos editáveis
    const valoresSalvos = {};
    document.querySelectorAll('#pdf-annotations input[data-pdf-field]').forEach(inp => {
        valoresSalvos[inp.getAttribute('data-pdf-field')] = inp.value;
    });

    pdfDoc.getPage(1).then(function (page) {
        const viewport = page.getViewport({ scale: currentScale });
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        page.render({ canvasContext: ctx, viewport: viewport }).promise.then(() => {
            page.getAnnotations().then(function (annotations) {
                const annContainer = document.getElementById('pdf-annotations');
                annContainer.innerHTML = '';

                annotations.forEach(function (annot) {
                    if (annot.subtype !== 'Widget' || annot.fieldType !== 'Tx') return;

                    // Pular campos read-only (preenchidos pelo servidor = dados da empresa)
                    const readOnly = !!(annot.fieldFlags & 1);
                    if (readOnly) return;

                    const rect = viewport.convertToViewportRectangle(annot.rect);
                    const x = Math.min(rect[0], rect[2]);
                    const y = Math.min(rect[1], rect[3]);
                    const width = Math.abs(rect[2] - rect[0]);
                    const height = Math.abs(rect[3] - rect[1]);

                    const input = document.createElement('input');
                    input.type = 'text';
                    input.className = 'pdf-input-overlay';
                    input.setAttribute('data-pdf-field', annot.fieldName);
                    // Usa o que já tava no input, ou o do banco de dados, ou vazio
                    input.value = valoresSalvos[annot.fieldName] !== undefined ? valoresSalvos[annot.fieldName] : (valoresSalvosGlobais[annot.fieldName] || '');

                    input.style.left = x + 'px';
                    input.style.top = y + 'px';
                    input.style.width = width + 'px';
                    input.style.height = height + 'px';

                    const alturaBase = Math.abs(annot.rect[3] - annot.rect[1]); // altura SEM escala (unidades PDF)
                    const fSize = Math.max(8, Math.min(alturaBase * 0.75, 14));  // entre 8pt e 14pt base
                    input.style.fontSize = (fSize * currentScale) + 'px';

<<<<<<< HEAD
                    // Agendamento de rascunho ao digitar
                    input.addEventListener('input', agendarRascunho);

=======
>>>>>>> 4bf72fcc7a5b4239890f734e3bb81d5854b9e203
                    annContainer.appendChild(input);
                });

                loading.style.display = 'none';
                container.style.display = 'inline-block';
            });
        });
    });
}

// ---- FASE 3: WIZARD PASSO 2 (ANEXOS E SUBMIT) ----
function irParaPasso2() {
    document.getElementById('view-form').style.display = 'none';
    document.getElementById('view-anexos').style.display = 'block';
}

function voltarParaPasso1() {
    document.getElementById('view-anexos').style.display = 'none';
    document.getElementById('view-form').style.display = 'block';
}

function toggleUploadArea() {
    const chk = document.getElementById('chk-so-caixinha');
    const area = document.getElementById('lancamentoUploadArea');
    if (chk && area) {
        if (chk.checked) {
            area.style.display = 'none';
            const fi = document.getElementById('lancamentoFileInput');
            if (fi) fi.value = '';
            const sf = document.getElementById('lancamentoSelectedFiles');
            if (sf) sf.innerHTML = '';
        } else {
            area.style.display = 'block';
        }
    }
}

function setupDragAndDrop() {
    const fileInput = document.getElementById('lancamentoFileInput');
    const fileLabel = document.querySelector('.file-label');
    const selectedFiles = document.getElementById('lancamentoSelectedFiles');

    if (fileInput && fileLabel && selectedFiles) {
        function updateFileList() {
            selectedFiles.innerHTML = '';
            const files = fileInput.files;
            for (let i = 0; i < files.length; i++) {
                const fileSize = (files[i].size / 1024).toFixed(2) + ' KB';
                selectedFiles.innerHTML += `<div style="padding:8px;background:#e8f4f8;margin-bottom:5px;border-radius:4px;border:1px solid #bce0fd;font-size:13px;">
                    <strong>📄 ${files[i].name}</strong> <span style="color:#666">(${fileSize})</span>
                </div>`;
            }
        }

        fileLabel.addEventListener('dragover', function (e) {
            e.preventDefault();
            this.style.background = '#ffebeb';
            this.style.borderColor = '#ff0000';
        });
        fileLabel.addEventListener('dragleave', function (e) {
            e.preventDefault();
            this.style.background = '#fafafa';
            this.style.borderColor = '#ccc';
        });
        fileLabel.addEventListener('drop', function (e) {
            e.preventDefault();
            this.style.background = '#fafafa';
            this.style.borderColor = '#ccc';
            fileInput.files = e.dataTransfer.files;
            updateFileList();
        });
        fileInput.addEventListener('change', updateFileList);
    }
}

function finalizarCaixinha() {
    const btn = document.getElementById('btn-finalizar');
    btn.disabled = true;
    btn.textContent = 'Enviando e Gerando PDF...';

    const inputs = document.querySelectorAll('#pdf-annotations input[data-pdf-field]');
    const camposData = {};
    inputs.forEach(inp => {
        camposData[inp.getAttribute('data-pdf-field')] = inp.value;
    });

    const formData = new FormData();
    formData.append('empresa_id', globalEmpresaId);
    formData.append('campos_r015', JSON.stringify(camposData));

    if (!document.getElementById('chk-so-caixinha').checked) {
        const files = document.getElementById('lancamentoFileInput').files;
        for (let i = 0; i < files.length; i++) {
            formData.append('arquivos[]', files[i]);
        }
    }

    fetch('/caixinha/lancamento/finalizar', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            btn.disabled = false;
            btn.textContent = 'FINALIZAR E GERAR PDF ✓';
            if (data.status === 'ok') {
                showMessage('Sucesso! Arquivo gerado: ' + data.arquivo, true);
                voltarParaLista();
                carregarEmpresas();
            } else {
                showMessage('Erro: ' + data.mensagem, false);
            }
        })
        .catch(() => {
            btn.disabled = false;
            btn.textContent = 'FINALIZAR E GERAR PDF ✓';
            showMessage('Erro de rede ao finalizar.', false);
        });
}

function desbloquearEmpresa(event, empresaId) {
    event.stopPropagation();
    if (!confirm('Tem certeza que deseja reabrir esta empresa para um novo lançamento?')) return;

    fetch('/caixinha/lancamento/desbloquear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ empresa_id: empresaId })
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ok') {
                showMessage('Empresa reaberta com sucesso.', true);
                carregarEmpresas();
            } else {
                showMessage('Erro: ' + data.mensagem, false);
            }
        })
        .catch(() => showMessage('Erro de rede ao desbloquear.', false));
}
