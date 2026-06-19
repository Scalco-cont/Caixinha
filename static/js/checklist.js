        /* =====================================================
           SENHAS DAS GERENTES — altere aqui conforme necessário
           ===================================================== */
        let SENHAS_GERENTES = {};
        let LISTA_GERENTES = [];
        let LISTA_REVISORES = [];
        // Chave do localStorage para persistência de sessão
        const CONF_LS_KEY = 'checklist_conf_gerente';    // aba Conferência
        const BAIXAS_LS_KEY = 'checklist_baixas_gerente';  // aba Baixas
        const REV_LS_KEY = 'checklist_rev_revisor';     // aba Revisão
        let confGerenteSel = null; // gerente selecionada no login de Conferência
        let baixasGerenteSel = null; // gerente selecionada no login de Baixas
        let revRevisorSel = null; // revisor selecionado no login de Revisão
        let encRevisorSel = null; // revisor selecionado no modal de encaminhar

        // Configuração do PDF.js Worker
        if (typeof pdfjsLib !== 'undefined') {
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';
        }

        /* =====================================================
           CONTROLE DE ABAS
           ===================================================== */
        function trocarAba(aba) {
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('tab-' + aba).classList.add('active');
            document.getElementById('tab-' + aba + '-btn').classList.add('active');
            if (aba === 'conferencia') tentarAutoLogin();
            if (aba === 'baixas') tentarAutoLoginBaixas();
            if (aba === 'revisao') tentarAutoLoginRev();
        }

        /* =====================================================
           LÓGICA DE BAIXAS — LOGIN POR SENHA DE GERENTE
           ===================================================== */
        let lastDataString = '';
        let globalData = {};
        let currentPage = 1;
        let itemsPerPage = parseInt(localStorage.getItem('checklist_itemsPerPage')) || 10;
        if (![10, 20, 50, 0].includes(itemsPerPage)) itemsPerPage = 10;
        let showOnlyBaixadas = localStorage.getItem('checklist_showOnlyBaixadas') === 'true';
        let baixasGerenteAtual = null; // gerente logada na aba Baixas

        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('itemsPerPage').value = itemsPerPage;
            document.getElementById('showOnlyBaixadas').checked = showOnlyBaixadas;

            carregarGerentes();

            // Tratamento de rotas via hash (isolamento das áreas)
            const hash = window.location.hash;
            if (hash === '#revisao') {
                document.getElementById('main-tabs-bar').style.display = 'none';
                trocarAba('revisao');
            } else if (hash === '#baixas') {
                trocarAba('baixas');
            } else if (hash === '#conferencia') {
                trocarAba('conferencia');
            }
        });

        function carregarGerentes() {
            fetch('/api/gerentes')
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        LISTA_GERENTES = data.data;
                        const bContainer = document.getElementById('baixas-gerente-btns-container');
                        const cContainer = document.getElementById('conf-gerente-btns-container');
                        bContainer.innerHTML = ''; cContainer.innerHTML = '';

                        LISTA_GERENTES.forEach(g => {
                            const savedSenha = localStorage.getItem('senha_gerente_' + g.nome);
                            SENHAS_GERENTES[g.nome] = savedSenha || 'default_if_none';
                        });

                        // Vamos refazer a lista de botoes:
                        LISTA_GERENTES.forEach(g => {
                            // Botões de Baixas
                            let btnB = document.createElement('button');
                            btnB.className = 'baixas-gbtn';
                            btnB.dataset.gerente = g.nome;
                            btnB.textContent = g.nome;
                            btnB.onclick = () => {
                                document.querySelectorAll('.baixas-gbtn').forEach(b => b.classList.remove('selected'));
                                btnB.classList.add('selected');
                                baixasGerenteSel = g.nome;
                                document.getElementById('baixas-senha').focus();
                            };
                            bContainer.appendChild(btnB);

                            // Botões de Conf
                            let btnC = document.createElement('button');
                            btnC.className = 'conf-gbtn';
                            btnC.dataset.gerente = g.nome;
                            btnC.textContent = g.nome;
                            btnC.onclick = () => {
                                document.querySelectorAll('.conf-gbtn').forEach(b => b.classList.remove('selected'));
                                btnC.classList.add('selected');
                                confGerenteSel = g.nome;
                                document.getElementById('conf-senha').focus();
                            };
                            cContainer.appendChild(btnC);
                        });

                        // Tentar login automático se tiver salvo no LS
                        tentarAutoLoginBaixas();
                        tentarAutoLogin();

                        fetchChecklist();
                        setInterval(fetchChecklist, 5000);
                    }
                });

            // Carregar revisores para o modal e aba de revisão
            fetch('/api/revisores')
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        LISTA_REVISORES = data.data;
                        const rContainer = document.getElementById('rev-revisor-btns-container');
                        const encContainer = document.getElementById('enc-revisores-btns');
                        rContainer.innerHTML = '';
                        encContainer.innerHTML = '';

                        LISTA_REVISORES.forEach(r => {
                            // Botões da aba Revisão
                            let btnR = document.createElement('button');
                            btnR.className = 'rev-rbtn';
                            btnR.textContent = r.nome;
                            btnR.onclick = () => {
                                document.querySelectorAll('.rev-rbtn').forEach(b => b.classList.remove('selected'));
                                btnR.classList.add('selected');
                                revRevisorSel = r.nome;
                                document.getElementById('rev-senha').focus();
                            };
                            rContainer.appendChild(btnR);

                            // Botões do modal de encaminhar
                            let btnE = document.createElement('button');
                            btnE.className = 'revisor-btn';
                            btnE.textContent = r.nome;
                            btnE.onclick = () => {
                                document.querySelectorAll('.revisor-btn').forEach(b => b.classList.remove('selected'));
                                btnE.classList.add('selected');
                                encRevisorSel = r.nome;
                            };
                            encContainer.appendChild(btnE);
                        });

                        tentarAutoLoginRev();
                    }
                });
        }

        function validarSenhaBackend(gerente, senha, callback) {
            fetch('/api/gerentes/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome: gerente, senha: senha })
            })
                .then(r => r.json())
                .then(data => callback(data.success))
                .catch(() => callback(false));
        }

        function fetchChecklist() {
            fetch('/checklist/api')
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        const ns = JSON.stringify(data.data);
                        if (ns !== lastDataString) { lastDataString = ns; globalData = data.data; renderView(); }
                    }
                })
                .catch(err => console.error('Erro ao buscar checklist:', err));
        }

        /* --- Login de Baixas --- */
        function tentarAutoLoginBaixas() {
            const saved = localStorage.getItem(BAIXAS_LS_KEY);
            const pass = localStorage.getItem('senha_gerente_' + saved);
            if (saved && pass) {
                validarSenhaBackend(saved, pass, (ok) => { if (ok) entrarBaixas(saved); });
            }
        }

        function baixasLogin() {
            const gerente = baixasGerenteSel;
            const senha = document.getElementById('baixas-senha').value;
            const erroEl = document.getElementById('baixas-erro');
            erroEl.style.display = 'none';
            if (!gerente) { erroEl.textContent = 'Selecione uma gerência.'; erroEl.style.display = 'block'; return; }

            validarSenhaBackend(gerente, senha, (ok) => {
                if (ok) {
                    localStorage.setItem(BAIXAS_LS_KEY, gerente);
                    localStorage.setItem('senha_gerente_' + gerente, senha);
                    entrarBaixas(gerente);
                } else {
                    erroEl.textContent = 'Senha incorreta.'; erroEl.style.display = 'block';
                    document.getElementById('baixas-senha').value = '';
                }
            });
        }

        function entrarBaixas(gerente) {
            baixasGerenteAtual = gerente;
            document.getElementById('baixas-login-panel').style.display = 'none';
            document.getElementById('baixas-main').style.display = 'block';
            document.getElementById('baixas-subtitulo').textContent = `Gerência: ${gerente}`;
            document.getElementById('baixas-gerente-nome').textContent = gerente;
            renderView();
        }

        function baixasLogout() {
            localStorage.removeItem(BAIXAS_LS_KEY);
            baixasGerenteAtual = null;
            baixasGerenteSel = null;
            document.getElementById('baixas-main').style.display = 'none';
            document.getElementById('baixas-login-panel').style.display = 'block';
            document.getElementById('baixas-senha').value = '';
            document.querySelectorAll('.baixas-gbtn').forEach(b => b.classList.remove('selected'));
        }

        function changeItemsPerPage() {
            itemsPerPage = parseInt(document.getElementById('itemsPerPage').value);
            localStorage.setItem('checklist_itemsPerPage', itemsPerPage);
            currentPage = 1; renderView();
        }
        function toggleBaixadas() {
            showOnlyBaixadas = document.getElementById('showOnlyBaixadas').checked;
            localStorage.setItem('checklist_showOnlyBaixadas', showOnlyBaixadas);
            currentPage = 1; renderView();
        }
        function prevPage() { if (currentPage > 1) { currentPage--; renderView(); } }
        function nextPage() {
            if (!baixasGerenteAtual) return;
            const all = globalData[baixasGerenteAtual] || [];
            const emp = showOnlyBaixadas ? all.filter(e => e.tem_baixa > 0) : all;
            if (itemsPerPage > 0 && currentPage * itemsPerPage < emp.length) { currentPage++; renderView(); }
        }
        function renderView() {
            if (!baixasGerenteAtual) return;
            const gerente = baixasGerenteAtual;
            const all = globalData[gerente] || [];

            // Aplicar filtro de busca
            const searchStr = (document.getElementById('search-baixas')?.value || '').toLowerCase();
            const searched = all.filter(e => e.nome.toLowerCase().includes(searchStr) || e.numero.includes(searchStr));

            const emp = showOnlyBaixadas ? searched.filter(e => e.tem_baixa > 0) : searched;
            const tp = itemsPerPage > 0 ? Math.ceil(emp.length / itemsPerPage) : 1;
            if (currentPage > tp && tp > 0) currentPage = tp;
            if (currentPage < 1) currentPage = 1;
            document.getElementById('pageInfo').textContent = `Página ${currentPage} de ${tp || 1}`;

            const badge = document.getElementById('badge-baixas');
            const footer = document.getElementById('footer-baixas');
            const list = document.getElementById('list-baixas');
            const baixas = searched.filter(e => e.tem_baixa > 0).length;
            badge.textContent = baixas + '/' + searched.length;
            footer.innerHTML = `<span>Total: ${searched.length}</span><span>Baixadas: <strong>${baixas}</strong></span>`;

            let toRender = emp;
            if (itemsPerPage > 0) { const s = (currentPage - 1) * itemsPerPage; toRender = emp.slice(s, s + itemsPerPage); }
            list.innerHTML = '';
            if (toRender.length === 0) { list.innerHTML = '<li class="empty-state">Nenhuma empresa nesta página.</li>'; return; }
            toRender.forEach(e => {
                const tb = e.tem_baixa > 0;
                const li = document.createElement('li');
                li.className = 'company-item' + (tb ? ' baixa' : '');
                li.innerHTML = `<span class="company-number">${e.numero}</span><span class="company-name">${e.nome}</span><span class="status-icon">${tb ? '✓' : '○'}</span>`;
                list.appendChild(li);
            });
        }
        function resetBaixas() {
            if (confirm('Tem certeza que deseja resetar todas as baixas e iniciar um novo ciclo?')) {
                fetch('/checklist/reset', { method: 'POST' }).then(r => r.json()).then(data => {
                    if (data.success) { showMessage('Lista resetada com sucesso.', true); fetchChecklist(); }
                    else showMessage('Erro ao resetar: ' + data.message, false);
                }).catch(() => showMessage('Erro de comunicação com o servidor.', false));
            }
        }

        /* =====================================================
           LÓGICA DA CONFERÊNCIA
           ===================================================== */
        function tentarAutoLogin() {
            const saved = localStorage.getItem(CONF_LS_KEY);
            const pass = localStorage.getItem('senha_gerente_' + saved);
            if (saved && pass) {
                validarSenhaBackend(saved, pass, (ok) => { if (ok) entrarConferencia(saved); });
            }
        }

        function confLogin() {
            const gerente = confGerenteSel;
            const senha = document.getElementById('conf-senha').value;
            const erroEl = document.getElementById('conf-erro');
            erroEl.style.display = 'none';
            if (!gerente) { erroEl.textContent = 'Selecione uma gerência.'; erroEl.style.display = 'block'; return; }

            validarSenhaBackend(gerente, senha, (ok) => {
                if (ok) {
                    localStorage.setItem(CONF_LS_KEY, gerente);
                    localStorage.setItem('senha_gerente_' + gerente, senha);
                    entrarConferencia(gerente);
                } else {
                    erroEl.textContent = 'Senha incorreta.'; erroEl.style.display = 'block';
                    document.getElementById('conf-senha').value = '';
                }
            });
        }

        function entrarConferencia(gerente) {
            document.getElementById('conf-login-panel').style.display = 'none';
            document.getElementById('conf-main').style.display = 'block';
            document.getElementById('conf-subtitulo').textContent = `Gerência: ${gerente}`;
            carregarConferencia(gerente);
            carregarVisaoGeral();
        }

        function confLogout() {
            localStorage.removeItem(CONF_LS_KEY);
            document.getElementById('conf-main').style.display = 'none';
            document.getElementById('conf-login-panel').style.display = 'block';
            document.getElementById('conf-senha').value = '';
            confGerenteSel = null;
            document.querySelectorAll('.conf-gbtn').forEach(b => b.classList.remove('selected'));
        }

        let confDataAll = [];

        async function carregarConferencia(gerente) {
            const lista = document.getElementById('conf-lista');
            lista.innerHTML = '<div class="conf-empty"><div class="icon">⏳</div><p>Carregando...</p></div>';
            try {
                const res = await fetch(`/caixinha/conferencia/api?gerente=${encodeURIComponent(gerente)}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    confDataAll = data.data;
                    renderConferencia();
                } else {
                    lista.innerHTML = '<div class="conf-empty"><div class="icon">✅</div><p>Nenhum lançamento pendente de conferência no momento.</p></div>';
                }
            } catch (e) { showMessage('Erro ao carregar: ' + e.message, false); }
        }

        function renderConferencia() {
            const lista = document.getElementById('conf-lista');
            const searchStr = (document.getElementById('search-conf')?.value || '').toLowerCase();

            const filtered = confDataAll.filter(e => {
                const num = (e.numero || '').toLowerCase();
                const nome = (e.nome || '').toLowerCase();
                return nome.includes(searchStr) || num.includes(searchStr);
            });

            if (filtered.length === 0) {
                lista.innerHTML = '<div class="conf-empty"><div class="icon">✅</div><p>Nenhum lançamento pendente ou correspondente à busca.</p></div>';
                return;
            }
            lista.innerHTML = filtered.map(emp => confCardHTML(emp)).join('');
        }

        function confCardHTML(emp) {
            const numero = emp.numero || '';
            const nome = emp.nome || '';
            const dt = emp.atualizado_em ? new Date(emp.atualizado_em.replace(' ', 'T')).toLocaleString('pt-BR') : '';
            return `
        <div class="conf-card" data-id="${emp.id}" onclick="abrirEdicaoPdfConf(${emp.id}, '${nome.replace(/'/g, "\\'")}')" style="cursor: pointer; transition: 0.2s; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 10px;">
            <div class="conf-card-header" style="padding: 16px; display: flex; justify-content: space-between; align-items: center; background: #fff;">
                <div>
                    <h3 style="margin:0; font-size: 15px; color: #333;">${numero} — ${nome}</h3>
                    <div style="font-size: 12px; color: #888; margin-top: 4px;">Enviado em: ${dt}</div>
                </div>
                <div style="display:flex;align-items:center;gap:12px;">
                    <span class="badge-pend">⏳ Pendente</span>
                    <span style="font-size: 13px; color: #1a73e8; font-weight: bold; background: #e8f0fe; padding: 6px 12px; border-radius: 4px;">👁️ Conferir Lançamento</span>
                </div>
            </div>
        </div>`;
        }

        /* --- Lógica de Edição de PDF com PDF.js na Conferência --- */
        let confPdfDoc = null;
        let confPdfCurrentScale = 1.3;
        let confEmpresaIdAtual = null;
        let confValoresOriginais = {};

        function ajustarZoomConf(delta) {
            const novoScale = Math.min(3.0, Math.max(0.6, confPdfCurrentScale + delta));
            if (novoScale === confPdfCurrentScale) return;
            confPdfCurrentScale = novoScale;
            document.getElementById('zoom-label-conf').textContent = Math.round(confPdfCurrentScale * 100) + '%';
            if (confPdfDoc) rerenderizarPaginaConf();
        }

        function resetarZoomConf() {
            confPdfCurrentScale = 1.3;
            document.getElementById('zoom-label-conf').textContent = Math.round(confPdfCurrentScale * 100) + '%';
            if (confPdfDoc) rerenderizarPaginaConf();
        }

        function voltarConfLista() {
            document.getElementById('view-conf-form').style.display = 'none';
            document.getElementById('conf-main').style.display = 'block';
            confEmpresaIdAtual = null;
        }

        async function abrirEdicaoPdfConf(id, nome) {
            confEmpresaIdAtual = id;
            document.getElementById('conf-empresa-nome-title').textContent = nome;
            
            document.getElementById('conf-main').style.display = 'none';
            document.getElementById('view-conf-form').style.display = 'block';
            document.getElementById('pdf-container-conf').innerHTML = '';

            try {
                const r = await fetch('/caixinha/lancamento/dados/' + id);
                const data = await r.json();
                confValoresOriginais = (data.success && data.data) ? data.data : {};
            } catch (e) {
                confValoresOriginais = {};
            }

            renderizarPDFConf();
        }

        function renderizarPDFConf() {
            const loading = document.getElementById('loading-pdf-conf');
            const container = document.getElementById('pdf-container-conf');

            loading.style.display = 'block';
            container.style.display = 'none';
            loading.textContent = 'Carregando documento para conferência...';

            // Carrega o PDF real gerado (incluindo anexos complementares)
            const pdfUrl = '/caixinha/pdf/' + confEmpresaIdAtual;
            console.log('Iniciando carregamento do PDF:', pdfUrl);
            
            fetch(pdfUrl)
                .then(res => {
                    console.log('Resposta do fetch PDF:', res.status);
                    if (!res.ok) throw new Error('Falha ao baixar o PDF do servidor');
                    return res.arrayBuffer();
                })
                .then(buffer => {
                    const arr = new Uint8Array(buffer);
                    return pdfjsLib.getDocument({ data: arr }).promise;
                })
                .then(doc => {
                    confPdfDoc = doc;
                    rerenderizarPaginaConf();
                })
                .catch(err => {
                    loading.textContent = 'Erro ao carregar documento: ' + err.message;
                    console.error(err);
                });
        }

        function rerenderizarPaginaConf() {
            const loading = document.getElementById('loading-pdf-conf');
            const container = document.getElementById('pdf-container-conf');

            loading.style.display = 'block';
            loading.textContent = 'Renderizando páginas...';
            container.style.display = 'none';

            // Preservar valores caso a usuária já tenha começado a digitar e mudado o zoom
            const valoresSalvos = {};
            document.querySelectorAll('#pdf-container-conf input[data-pdf-field]').forEach(inp => {
                valoresSalvos[inp.getAttribute('data-pdf-field')] = inp.value;
            });
            
            container.innerHTML = ''; // Limpa as páginas anteriores

            const numPages = confPdfDoc.numPages;
            let pagesRendered = 0;

            for (let i = 1; i <= numPages; i++) {
                // Cria um wrapper para cada página
                const pageWrapper = document.createElement('div');
                pageWrapper.style.position = 'relative';
                pageWrapper.style.marginBottom = '20px';
                pageWrapper.style.boxShadow = '0 0 10px rgba(0,0,0,0.2)';
                pageWrapper.style.display = 'inline-block'; // Garante que a div abrace o tamanho do canvas
                
                const canvas = document.createElement('canvas');
                canvas.style.display = 'block';
                pageWrapper.appendChild(canvas);

                const annContainer = document.createElement('div');
                annContainer.style.position = 'absolute';
                annContainer.style.top = '0';
                annContainer.style.left = '0';
                annContainer.style.width = '100%';
                annContainer.style.height = '100%';
                pageWrapper.appendChild(annContainer);

                container.appendChild(pageWrapper);

                // Renderiza a página
                confPdfDoc.getPage(i).then(function (page) {
                    const viewport = page.getViewport({ scale: confPdfCurrentScale });
                    canvas.height = viewport.height;
                    canvas.width = viewport.width;

                    const ctx = canvas.getContext('2d');
                    page.render({ canvasContext: ctx, viewport: viewport }).promise.then(() => {
                        
                        // Busca anotações (apenas na primeira página, mas o loop fará em todas se tiver form fields)
                        page.getAnnotations().then(function (annotations) {
                            annotations.forEach(function (annot) {
                                if (annot.subtype !== 'Widget' || annot.fieldType !== 'Tx') return;

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
                                
                                input.value = valoresSalvos[annot.fieldName] !== undefined ? valoresSalvos[annot.fieldName] : (confValoresOriginais[annot.fieldName] || '');

                                input.style.position = 'absolute';
                                input.style.left = x + 'px';
                                input.style.top = y + 'px';
                                input.style.width = width + 'px';
                                input.style.height = height + 'px';

                                const alturaBase = Math.abs(annot.rect[3] - annot.rect[1]); 
                                const fSize = Math.max(8, Math.min(alturaBase * 0.75, 14));  
                                input.style.fontSize = (fSize * confPdfCurrentScale) + 'px';
                                input.style.border = '1px solid #1a73e8';
                                input.style.backgroundColor = '#e8f0fe';
                                input.style.padding = '0 2px';
                                input.style.boxSizing = 'border-box';
                                input.style.color = '#333';
                                input.style.fontWeight = 'bold';

                                input.addEventListener('focus', function() {
                                    this.style.backgroundColor = '#fff';
                                    this.style.border = '2px solid #1a73e8';
                                });
                                input.addEventListener('blur', function() {
                                    this.style.backgroundColor = '#e8f0fe';
                                    this.style.border = '1px solid #1a73e8';
                                });

                                annContainer.appendChild(input);
                            });
                        });
                        
                        pagesRendered++;
                        if (pagesRendered === numPages) {
                            loading.style.display = 'none';
                            container.style.display = 'flex';
                            container.style.flexDirection = 'column';
                            container.style.alignItems = 'center';
                            container.style.gap = '20px';
                        }
                    });
                });
            }
        }

        async function salvarEdicaoConfPdfOnly() {
            if (!confEmpresaIdAtual) return false;
            const btn = document.getElementById('btn-salvar-edicao-conf');
            const origText = btn.textContent;
            btn.disabled = true; btn.textContent = '⏳ Salvando...';

            const inputs = document.querySelectorAll('#pdf-container-conf input[data-pdf-field]');
            const campos = {};
            inputs.forEach(inp => { campos[inp.getAttribute('data-pdf-field')] = inp.value; });

            try {
                const form = new FormData();
                form.append('empresa_id', confEmpresaIdAtual);
                form.append('campos', JSON.stringify(campos));
                const res = await fetch('/caixinha/conferencia/salvar-edicao', { method: 'POST', body: form });
                const data = await res.json();
                if (data.status === 'ok') {
                    showMessage('✅ Alterações no PDF salvas com sucesso!', true);
                    return true;
                } else {
                    showMessage('Erro ao salvar: ' + data.mensagem, false);
                    return false;
                }
            } catch(err) {
                showMessage('Erro de conexão ao salvar.', false);
                return false;
            } finally {
                btn.disabled = false; btn.textContent = origText;
            }
        }

        async function conferirEdicaoAprovar() {
            if (!confEmpresaIdAtual) return;
            if (!confirm('Salvar as alterações e confirmar aprovação deste lançamento?')) return;
            
            const btnConf = document.getElementById('btn-conferido-conf');
            btnConf.disabled = true; btnConf.textContent = '⏳ Processando...';

            // Primeiro salva os inputs alterados no servidor
            const salvo = await salvarEdicaoConfPdfOnly();
            if (!salvo) {
                btnConf.disabled = false; btnConf.textContent = '✅ Salvar e Conferido';
                return;
            }

            // Se salvou com sucesso, chama a rota de aprovação
            try {
                const res = await fetch('/caixinha/conferencia/aprovar', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ empresa_id: confEmpresaIdAtual })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    showMessage('✅ Lançamento conferido com sucesso!', true);
                    const idParaEncaminhar = confEmpresaIdAtual;
                    voltarConfLista(); // Esconde formulário
                    abrirModalEncaminhar(idParaEncaminhar); // Abre encaminhamento
                    // Remove da lista em memória
                    confDataAll = confDataAll.filter(e => e.id != idParaEncaminhar);
                    renderConferencia();
                } else { 
                    showMessage('Erro ao aprovar: ' + data.mensagem, false); 
                }
            } catch (e) { 
                showMessage('Erro: ' + e.message, false); 
            } finally {
                btnConf.disabled = false; btnConf.textContent = '✅ Salvar e Conferido';
            }
        }

        function abrirModalRejeitarConf() {
            if (!confEmpresaIdAtual) return;
            document.getElementById('modal-empresa-id').value = confEmpresaIdAtual;
            document.getElementById('modal-motivo').value = '';
            document.getElementById('modal-arquivo').value = '';
            document.getElementById('modal-rejeicao').classList.add('open');
        }

        function fecharModal() { document.getElementById('modal-rejeicao').classList.remove('open'); }

        async function confirmarRejeicao() {
            const id = document.getElementById('modal-empresa-id').value;
            const motivo = document.getElementById('modal-motivo').value;
            const arquivo = document.getElementById('modal-arquivo').files[0];
            const form = new FormData();
            form.append('empresa_id', id);
            form.append('motivo', motivo);
            if (arquivo) form.append('arquivo_anotado', arquivo);
            try {
                const btn = document.querySelector('#modal-rejeicao .btn-confirmar-rej');
                if(btn) { btn.disabled = true; btn.textContent = 'Enviando...'; }

                // Opcional: Se a gerente quiser salvar o PDF com inputs antes de rejeitar, 
                // poderíamos salvarEdicaoConfPdfOnly aqui também, mas se ela tá rejeitando, 
                // geralmente ela deixa o PDF original + motivo ou anexa outro.
                
                const res = await fetch('/caixinha/conferencia/rejeitar', { method: 'POST', body: form });
                const data = await res.json();
                if (data.status === 'ok') {
                    fecharModal();
                    showMessage('❌ Lançamento rejeitado. Usuário será notificado.', true);
                    voltarConfLista();
                    confDataAll = confDataAll.filter(e => e.id != id);
                    renderConferencia();
                } else showMessage('Erro: ' + data.mensagem, false);
            } catch (e) { 
                showMessage('Erro: ' + e.message, false); 
            } finally {
                const btn = document.querySelector('#modal-rejeicao .btn-confirmar-rej');
                if(btn) { btn.disabled = false; btn.textContent = 'Confirmar Rejeição ✓'; }
            }
        }

        /* --- Modal de encaminhar para revisor --- */
        function abrirModalEncaminhar(id) {
            document.getElementById('enc-empresa-id').value = id;
            encRevisorSel = null;
            document.querySelectorAll('.revisor-btn').forEach(b => b.classList.remove('selected'));
            document.getElementById('modal-encaminhar').classList.add('open');
        }
        function fecharModalEnc() {
            document.getElementById('modal-encaminhar').classList.remove('open');
            // Remover o card da lista após fechar
            const id = document.getElementById('enc-empresa-id').value;
            const card = document.querySelector(`.conf-card[data-id="${id}"]`);
            if (card) { card.style.transition = 'opacity 0.4s'; card.style.opacity = '0'; setTimeout(() => card.remove(), 400); }
        }
        async function confirmarEncaminhar() {
            const id = document.getElementById('enc-empresa-id').value;
            if (!encRevisorSel) { alert('Selecione um revisor antes de encaminhar.'); return; }
            try {
                const res = await fetch('/caixinha/conferencia/encaminhar', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ empresa_id: parseInt(id), revisor: encRevisorSel })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    showMessage(`📤 Encaminhado para ${encRevisorSel} com sucesso!`, true);
                    fecharModalEnc();
                } else {
                    showMessage('Erro: ' + data.mensagem, false);
                }
            } catch (e) { showMessage('Erro: ' + e.message, false); }
        }
        document.getElementById('modal-encaminhar').addEventListener('click', function (e) {
            if (e.target === this) fecharModalEnc();
        });


        /* =====================================================
           LÓGICA DA ABA DE REVISÃO FINAL
           ===================================================== */
        let revDataAll = [];

        function tentarAutoLoginRev() {
            const saved = localStorage.getItem(REV_LS_KEY);
            const pass = localStorage.getItem('senha_revisor_' + saved);
            if (saved && pass) {
                fetch('/api/revisores/login', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nome: saved, senha: pass })
                }).then(r => r.json()).then(data => { if (data.success) entrarRevisao(saved); });
            }
        }

        function revLogin() {
            const revisor = revRevisorSel;
            const senha = document.getElementById('rev-senha').value;
            const erroEl = document.getElementById('rev-erro');
            erroEl.style.display = 'none';
            if (!revisor) { erroEl.textContent = 'Selecione um revisor.'; erroEl.style.display = 'block'; return; }

            fetch('/api/revisores/login', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome: revisor, senha: senha })
            }).then(r => r.json()).then(data => {
                if (data.success) {
                    localStorage.setItem(REV_LS_KEY, revisor);
                    localStorage.setItem('senha_revisor_' + revisor, senha);
                    entrarRevisao(revisor);
                } else {
                    erroEl.textContent = 'Senha incorreta.'; erroEl.style.display = 'block';
                    document.getElementById('rev-senha').value = '';
                }
            }).catch(() => { erroEl.textContent = 'Erro de conexão.'; erroEl.style.display = 'block'; });
        }

        function entrarRevisao(revisor) {
            document.getElementById('rev-login-panel').style.display = 'none';
            document.getElementById('rev-main').style.display = 'block';
            document.getElementById('rev-subtitulo').textContent = `Revisor: ${revisor}`;
            carregarRevisao(revisor);
        }

        function revLogout() {
            localStorage.removeItem(REV_LS_KEY);
            document.getElementById('rev-main').style.display = 'none';
            document.getElementById('rev-login-panel').style.display = 'block';
            document.getElementById('rev-senha').value = '';
            revRevisorSel = null;
            document.querySelectorAll('.rev-rbtn').forEach(b => b.classList.remove('selected'));
        }

        async function carregarRevisao(revisor) {
            const lista = document.getElementById('rev-lista');
            lista.innerHTML = '<div class="rev-empty"><div class="icon">⏳</div><p>Carregando...</p></div>';
            try {
                const res = await fetch(`/caixinha/revisao/api?revisor=${encodeURIComponent(revisor)}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    revDataAll = data.data;
                    renderRevisao();
                } else {
                    lista.innerHTML = '<div class="rev-empty"><div class="icon">✅</div><p>Nenhum lançamento pendente de revisão no momento.</p></div>';
                }
            } catch (e) { showMessage('Erro ao carregar: ' + e.message, false); }
        }

        function renderRevisao() {
            const lista = document.getElementById('rev-lista');
            const searchStr = (document.getElementById('search-rev')?.value || '').toLowerCase();
            const filtered = revDataAll.filter(e => {
                const num = (e.numero || '').toLowerCase();
                const nome = (e.nome || '').toLowerCase();
                return nome.includes(searchStr) || num.includes(searchStr);
            });
            if (filtered.length === 0) {
                lista.innerHTML = '<div class="rev-empty"><div class="icon">✅</div><p>Nenhum lançamento pendente de revisão ou correspondente à busca.</p></div>';
                return;
            }
            lista.innerHTML = filtered.map(emp => revCardHTML(emp)).join('');
            lista.querySelectorAll('.rev-card-header').forEach(hdr => {
                hdr.addEventListener('click', () => hdr.closest('.rev-card').classList.toggle('open'));
            });
        }

        function revCardHTML(emp) {
            const revisorLogado = localStorage.getItem(REV_LS_KEY) || '';
            const podEncaminhar = (revisorLogado === 'Valnei' || revisorLogado === 'Marielli');
            const isYasmin = (revisorLogado === 'Yasmin');
            const numero = emp.numero || '';
            const nome = emp.nome || '';
            const gerente = emp.gerente || '';
            const dt = emp.atualizado_em ? new Date(emp.atualizado_em.replace(' ', 'T')).toLocaleString('pt-BR') : '';
            const btnEnc = podEncaminhar
                ? `<button class="btn-enc-yasmin" onclick="revEncaminharYasmin(${emp.id}, this)">📤 Encaminhar para Yasmin</button>`
                : '';

            const uploadHtml = isYasmin ? `
        <div style="margin-top:14px; padding-top:14px; border-top:1px solid #f0d0d0;">
            <div style="font-size:12px;font-weight:bold;color:#c82333;margin-bottom:8px;">📎 Anexo Extra (Opcional)</div>
            <div class="yasmin-upload-zone" id="yasmin-zone-${emp.id}"
                 ondragover="yUploadDragOver(event,'${emp.id}')" ondragleave="yUploadDragLeave(event,'${emp.id}')" ondrop="yUploadDrop(event,'${emp.id}')">
                <input type="file" id="upload-yasmin-${emp.id}" accept=".pdf" onchange="yUploadChange(event,'${emp.id}')">
                <div class="yasmin-upload-icon">📄</div>
                <div class="yasmin-upload-label">Arraste o PDF aqui ou clique para selecionar</div>
                <div class="yasmin-upload-sub">Apenas arquivos .pdf</div>
            </div>
            <div class="yasmin-file-preview" id="yasmin-preview-${emp.id}">
                <span>✅</span>
                <span class="file-name" id="yasmin-filename-${emp.id}"></span>
                <button class="btn-remove-file" onclick="yRemoverArquivo('${emp.id}')">✕</button>
            </div>
        </div>` : '';

            return `
        <div class="rev-card" data-id="${emp.id}">
            <div class="rev-card-header">
                <h3>${numero} — ${nome}</h3>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:11px;background:rgba(255,255,255,0.25);padding:3px 9px;border-radius:12px;">Gerente: ${gerente}</span>
                    <span class="rev-expand">▼</span>
                </div>
            </div>
            <div class="rev-card-body">
                <div class="rev-card-meta">Conferido em: ${dt}</div>
                <div class="rev-pdf-wrap">
                    <iframe src="/caixinha/pdf/${emp.id}" title="PDF ${nome}"></iframe>
                </div>
                ${uploadHtml}
                <div class="conf-actions" style="margin-top:14px;">
                    <button class="btn-revisado" onclick="revAprovar(${emp.id}, this)">✅ Revisado / Aprovado</button>
                    <button class="btn-cancelar" style="background:#555;color:#fff;border:none;padding:10px 24px;border-radius:5px;font-size:14px;font-weight:bold;cursor:pointer;margin-left:8px;" onclick="revRecusar(${emp.id}, this)">❌ Recusar</button>
                    ${btnEnc}
                </div>
            </div>
        </div>`;
        }

        async function revAprovar(id, btn) {
            if (!confirm('Confirmar aprovação da revisão deste lançamento?')) return;
            btn.disabled = true; btn.textContent = '⏳ Aprovando...';
            try {
                const revisorLogado = localStorage.getItem(REV_LS_KEY) || '';
                const form = new FormData();
                form.append('empresa_id', id);
                form.append('revisor', revisorLogado);

                if (revisorLogado === 'Yasmin') {
                    const input = document.getElementById(`upload-yasmin-${id}`);
                    if (input && input.files.length > 0) {
                        form.append('arquivo_anexo', input.files[0]);
                    }
                }

                const res = await fetch('/caixinha/revisao/aprovar', {
                    method: 'POST', body: form
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    showMessage('✅ Revisão aprovada com sucesso!', true);
                    const card = document.querySelector(`.rev-card[data-id="${id}"]`);
                    if (card) { card.style.transition = 'opacity 0.4s'; card.style.opacity = '0'; setTimeout(() => card.remove(), 400); }
                } else { showMessage('Erro: ' + data.mensagem, false); btn.disabled = false; btn.innerHTML = '✅ Revisado / Aprovado'; }
            } catch (e) { showMessage('Erro: ' + e.message, false); btn.disabled = false; btn.innerHTML = '✅ Revisado / Aprovado'; }
        }

        async function revRecusar(id, btn) {
            if (!confirm('Recusar este lançamento e devolver para conferência da gerente?')) return;
            btn.disabled = true; btn.textContent = '⏳ Recusando...';
            try {
                const res = await fetch('/caixinha/revisao/recusar', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ empresa_id: id })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    showMessage('❌ Lançamento devolvido para a gerente.', true);
                    const card = document.querySelector(`.rev-card[data-id="${id}"]`);
                    if (card) { card.style.transition = 'opacity 0.4s'; card.style.opacity = '0'; setTimeout(() => card.remove(), 400); }
                } else { showMessage('Erro: ' + data.mensagem, false); btn.disabled = false; btn.innerHTML = '❌ Recusar'; }
            } catch (e) { showMessage('Erro: ' + e.message, false); btn.disabled = false; btn.innerHTML = '❌ Recusar'; }
        }

        async function revEncaminharYasmin(id, btn) {
            const revisorAtual = localStorage.getItem(REV_LS_KEY);
            if (!confirm('Encaminhar este lançamento para Yasmin?')) return;
            btn.disabled = true; btn.textContent = '⏳ Encaminhando...';
            try {
                const res = await fetch('/caixinha/revisao/encaminhar-yasmin', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ empresa_id: id, revisor_atual: revisorAtual })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    showMessage('📤 Encaminhado para Yasmin com sucesso!', true);
                    const card = document.querySelector(`.rev-card[data-id="${id}"]`);
                    if (card) { card.style.transition = 'opacity 0.4s'; card.style.opacity = '0'; setTimeout(() => card.remove(), 400); }
                } else { showMessage('Erro: ' + data.mensagem, false); btn.disabled = false; btn.innerHTML = '📤 Encaminhar para Yasmin'; }
            } catch (e) { showMessage('Erro: ' + e.message, false); btn.disabled = false; btn.innerHTML = '📤 Encaminhar para Yasmin'; }
        }

        function toggleVisaoGeral() {
            const lista = document.getElementById('conf-vg-lista');
            const icon = document.getElementById('vg-toggle-icon');
            if (lista.style.display === 'none') {
                lista.style.display = 'block';
                icon.textContent = '▼';
            } else {
                lista.style.display = 'none';
                icon.textContent = '▶';
            }
        }

        async function carregarVisaoGeral() {
            const lista = document.getElementById('conf-vg-lista');
            if (!lista) return;
            lista.innerHTML = '<p style="color:#aaa;font-size:13px;">Carregando...</p>';
            try {
                const res = await fetch('/caixinha/revisao/visao-geral');
                const data = await res.json();
                if (data.status !== 'ok') { lista.innerHTML = '<p style="color:#c0392b;font-size:13px;">Erro ao carregar.</p>'; return; }
                if (data.data.length === 0) {
                    lista.innerHTML = '<p style="color:#aaa;font-size:13px;text-align:center;padding:16px 0;">Nenhum lançamento em revisão ou concluído no momento.</p>';
                    return;
                }

                const ordem = ['Valnei', 'Marielli', 'Yasmin'];
                let html = '';
                ordem.forEach(rev => {
                    const itensDoRevisor = data.data.filter(e => e.revisor === rev);
                    if (itensDoRevisor.length === 0) return;

                    const pendentes = itensDoRevisor.filter(e => e.status_lancamento_caixinha === 'pendente_revisao');
                    const revisados = itensDoRevisor.filter(e => e.status_lancamento_caixinha === 'revisado');

                    html += `<div class="vg-group">`;
                    html += `<div class="vg-group-title">👤 ${rev} <span style="font-size:12px;font-weight:normal;color:#888;">(${pendentes.length} pendentes / ${revisados.length} concluídos)</span></div>`;

                    if (pendentes.length > 0) {
                        html += `<div style="font-size:12px; font-weight:bold; color:#d35400; margin: 8px 0 4px 0;">⏳ Precisam ser revisados:</div>`;
                        pendentes.forEach(e => {
                            const dt = e.atualizado_em ? new Date(e.atualizado_em.replace(' ', 'T')).toLocaleString('pt-BR') : '';
                            html += `<div class="vg-item">
                        <div><span class="vg-item-num">${e.numero}</span><strong>${e.nome}</strong><span class="vg-item-gerente">(${e.gerente})</span></div>
                        <span style="font-size:11px;color:#aaa;">Enviado: ${dt}</span>
                    </div>`;
                        });
                    }

                    if (revisados.length > 0) {
                        html += `<div style="font-size:12px; font-weight:bold; color:#27ae60; margin: 12px 0 4px 0;">✅ Já foram revisados:</div>`;
                        revisados.forEach(e => {
                            const dt = e.atualizado_em ? new Date(e.atualizado_em.replace(' ', 'T')).toLocaleString('pt-BR') : '';
                            html += `<div class="vg-item" style="opacity: 0.65;">
                        <div><span class="vg-item-num" style="background:#e8f8f5; color:#27ae60;">${e.numero}</span><strong style="text-decoration: line-through; color:#777;">${e.nome}</strong><span class="vg-item-gerente">(${e.gerente})</span></div>
                        <span style="font-size:11px;color:#aaa;">Concluído: ${dt}</span>
                    </div>`;
                        });
                    }
                    html += `</div>`;
                });
                lista.innerHTML = html;
            } catch (e) {
                lista.innerHTML = `<p style="color:#c0392b;font-size:13px;">Erro de conexão: ${e.message}</p>`;
            }
        }

        function confAbrirModal(id) {
            document.getElementById('modal-empresa-id').value = id;
            document.getElementById('modal-motivo').value = '';
            document.getElementById('modal-arquivo').value = '';
            document.getElementById('modal-rejeicao').classList.add('open');
        }
        function fecharModal() { document.getElementById('modal-rejeicao').classList.remove('open'); }

        async function confirmarRejeicao() {
            const id = document.getElementById('modal-empresa-id').value;
            const motivo = document.getElementById('modal-motivo').value;
            const arquivo = document.getElementById('modal-arquivo').files[0];
            const form = new FormData();
            form.append('empresa_id', id);
            form.append('motivo', motivo);
            if (arquivo) form.append('arquivo_anotado', arquivo);
            try {
                const res = await fetch('/caixinha/conferencia/rejeitar', { method: 'POST', body: form });
                const data = await res.json();
                if (data.status === 'ok') {
                    fecharModal();
                    showMessage('❌ Lançamento rejeitado. Usuário será notificado.', true);
                    const card = document.querySelector(`.conf-card[data-id="${id}"]`);
                    if (card) { card.style.transition = 'opacity 0.4s'; card.style.opacity = '0'; setTimeout(() => card.remove(), 400); }
                } else showMessage('Erro: ' + data.mensagem, false);
            } catch (e) { showMessage('Erro: ' + e.message, false); }
        }

        document.getElementById('modal-rejeicao').addEventListener('click', function (e) {
            if (e.target === this) fecharModal();
        });

        /* ---- Mensagem flutuante ---- */
        function showMessage(text, ok) {
            const el = document.getElementById('message');
            el.textContent = text;
            el.className = ok ? 'msg-success' : 'msg-error';
            el.style.display = 'block';
            setTimeout(() => el.style.display = 'none', 2000);
        }

        /* =====================================================
           UPLOAD DRAG & DROP — YASMIN
           ===================================================== */
        function yUploadDragOver(e, id) {
            e.preventDefault();
            document.getElementById('yasmin-zone-' + id)?.classList.add('drag-over');
        }
        function yUploadDragLeave(e, id) {
            document.getElementById('yasmin-zone-' + id)?.classList.remove('drag-over');
        }
        function yUploadDrop(e, id) {
            e.preventDefault();
            document.getElementById('yasmin-zone-' + id)?.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file && file.name.endsWith('.pdf')) {
                // Injetar no input real
                const input = document.getElementById('upload-yasmin-' + id);
                const dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                yMostrarPreview(id, file.name);
            } else {
                showMessage('Apenas arquivos .pdf são aceitos.', false);
            }
        }
        function yUploadChange(e, id) {
            const file = e.target.files[0];
            if (file) yMostrarPreview(id, file.name);
        }
        function yMostrarPreview(id, nome) {
            const zone = document.getElementById('yasmin-zone-' + id);
            const preview = document.getElementById('yasmin-preview-' + id);
            const nameEl = document.getElementById('yasmin-filename-' + id);
            if (zone) zone.style.display = 'none';
            if (preview) { preview.classList.add('visible'); }
            if (nameEl) nameEl.textContent = nome;
        }
        function yRemoverArquivo(id) {
            const input = document.getElementById('upload-yasmin-' + id);
            if (input) input.value = '';
            const zone = document.getElementById('yasmin-zone-' + id);
            const preview = document.getElementById('yasmin-preview-' + id);
            if (zone) zone.style.display = '';
            if (preview) preview.classList.remove('visible');
        }

        /* =====================================================
           UPLOAD DRAG & DROP — GERENTE (editar PDF)
           ===================================================== */
        function gerUploadDragOver(e) {
            e.preventDefault();
            /* =====================================================
               UPLOAD DRAG & DROP — GERENTE (inline por card)
               ===================================================== */
            function gerUploadDragOver(e, id) {
                e.preventDefault();
                document.getElementById('gzone-' + id)?.classList.add('drag-over');
            }
            function gerUploadDragLeave(e, id) {
                document.getElementById('gzone-' + id)?.classList.remove('drag-over');
            }
            function gerUploadDrop(e, id) {
                e.preventDefault();
                document.getElementById('gzone-' + id)?.classList.remove('drag-over');
                const file = e.dataTransfer.files[0];
                if (file && file.name.endsWith('.pdf')) {
                    const input = document.getElementById('ger-pdf-input-' + id);
                    const dt = new DataTransfer();
                    dt.items.add(file);
                    input.files = dt.files;
                    gerMostrarPreview(id, file.name);
                } else {
                    showMessage('Apenas arquivos .pdf são aceitos.', false);
                }
            }
            function gerUploadChange(e, id) {
                const file = e.target.files[0];
                if (file) gerMostrarPreview(id, file.name);
            }
            function gerMostrarPreview(id, nome) {
                document.getElementById('gzone-' + id).style.display = 'none';
                const preview = document.getElementById('gpreview-' + id);
                if (preview) preview.classList.add('visible');
                const nameEl = document.getElementById('gfilename-' + id);
                if (nameEl) nameEl.textContent = nome;
            }
            function gerRemoverArquivo(id) {
                const input = document.getElementById('ger-pdf-input-' + id);
                if (input) input.value = '';
                const zone = document.getElementById('gzone-' + id);
                if (zone) zone.style.display = '';
                const preview = document.getElementById('gpreview-' + id);
                if (preview) preview.classList.remove('visible');
            }

            async function salvarPdfEditado(id, btn) {
                const input = document.getElementById('ger-pdf-input-' + id);
                if (!input || !input.files.length) {
                    showMessage('Selecione um arquivo PDF antes de salvar.', false);
                    return;
                }
                const origText = btn.textContent;
                btn.disabled = true; btn.textContent = '⏳ Salvando...';

                const form = new FormData();
                form.append('empresa_id', id);
                form.append('pdf_editado', input.files[0]);

                try {
                    const res = await fetch('/caixinha/conferencia/atualizar-pdf', { method: 'POST', body: form });
                    const data = await res.json();
                    if (data.status === 'ok') {
                        showMessage('✅ PDF atualizado com sucesso!', true);
                        gerRemoverArquivo(id);
                        // Recarregar o iframe do card
                        const iframe = document.getElementById('pdf-iframe-' + id);
                        if (iframe) {
                            const src = iframe.src.split('?')[0];
                            iframe.src = '';
                            setTimeout(() => { iframe.src = src + '?t=' + Date.now(); }, 300);
                        }
                    } else {
                        showMessage('Erro: ' + data.mensagem, false);
                    }
                } catch (err) {
                    showMessage('Erro de conexão: ' + err.message, false);
                } finally {
                    btn.disabled = false; btn.textContent = origText;
                }
            }
        }
