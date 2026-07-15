// ─────────────────────────────────────────────────────────
//  Don Pilsen — Agente Cervecero | app.js
//  Dashboard ERP Cervecería
// ─────────────────────────────────────────────────────────

const API_BASE = 'http://localhost:8000';

// Instancias de gráficos
let chartUno = null;
let chartDos = null;
let chartTres = null;
let chartCuatro = null;

// ─────────────────────────────────────────────────────────
//  INICIO
// ─────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
    inicializarChat();
    await cargarFiltros().then(() => cargarGraficos(null, null));

    // Frontend Warmup: Pre-cargar LLaMA silenciosamente en background mientras el usuario ve el dashboard
    fetch(`${API_BASE}/api/bia/estado`).catch(() => {});
    
    verificarEstadoOllama();

    document.getElementById("filtro-carrera").addEventListener("change", async (e) => {
        const receta = e.target.value || null;
        
        // Actualizar meses dinámicamente según la receta seleccionada
        try {
            const selectMes = document.getElementById("filtro-mes");
            const prevMes = selectMes.value;
            
            const res = await fetch(`${API_BASE}/api/kpi/grafico_uno${receta ? '?receta_id=' + receta : ''}`);
            const json = await res.json();
            
            // Extraer meses únicos ordenados
            const uniqueMonths = [...new Set(json.data.map(item => item.mes))].sort().reverse();
            
            selectMes.innerHTML = '<option value="">Todos los Meses</option>';
            uniqueMonths.forEach(mes => {
                const opcion = document.createElement("option");
                opcion.value = mes;
                opcion.textContent = mes;
                selectMes.appendChild(opcion);
            });
            
            // Mantener selección anterior si sigue siendo válida
            if (uniqueMonths.includes(prevMes)) {
                selectMes.value = prevMes;
            } else {
                selectMes.value = "";
            }
        } catch (err) {
            console.error("Error al actualizar meses:", err);
        }
        
        const mes = document.getElementById("filtro-mes").value || null;
        cargarGraficos(receta, mes);
    });

    document.getElementById("filtro-mes").addEventListener("change", (e) => {
        const mes    = e.target.value || null;
        const receta = document.getElementById("filtro-carrera").value || null;
        cargarGraficos(receta, mes);
    });

    configurarExportacionPDF();
    checkStockAlerts();

    // Auto-refresh Enterprise: Actualizar datos cada 60 segundos
    setInterval(() => {
        const receta = document.getElementById("filtro-carrera").value || null;
        const mes    = document.getElementById("filtro-mes").value || null;
        cargarGraficos(receta, mes);
        checkStockAlerts();
    }, 60000);
});

// ─────────────────────────────────────────────────────────
//  ALERTA DE STOCK EN HEADER
// ─────────────────────────────────────────────────────────
async function checkStockAlerts() {
    try {
        const resp = await fetch(`${API_BASE}/api/kpi/alertas_stock`);
        const json = await resp.json();
        const alertsContainer = document.getElementById('stock-alerts-container');
        const alertsText = document.getElementById('stock-alerts-text');
        
        if (json.data && json.data.length > 0) {
            alertsContainer.classList.remove('hidden');
            const insumosNombres = json.data.map(i => i.insumo).join(', ');
            alertsText.innerHTML = `Stock Crítico: <b>${insumosNombres}</b>`;
        } else {
            alertsContainer.classList.add('hidden');
        }
    } catch (e) {
        console.error("Error checkStockAlerts:", e);
    }
}

// ─────────────────────────────────────────────────────────
//  VERIFICAR ESTADO DE OLLAMA
// ─────────────────────────────────────────────────────────
async function verificarEstadoOllama() {
    try {
        const resp = await fetch(`${API_BASE}/api/bia/estado`);
        const data = await resp.json();
        const label = document.getElementById('bia-status-label');
        const banner = document.getElementById('ollama-banner');

        if (data.ollama_activo && data.modelo_disponible) {
            label.textContent = 'En línea • LLaMA 3.2 activo';
            label.style.color = 'var(--green)';
            banner.classList.remove('show');
        } else if (data.ollama_activo && !data.modelo_disponible) {
            label.textContent = 'Ollama activo • Descargando modelo...';
            label.style.color = 'var(--orange, #fb923c)';
            banner.classList.add('show');
        } else {
            label.textContent = 'Modo análisis directo (sin LLM)';
            label.style.color = 'var(--blue)';
            banner.classList.add('show');
        }
    } catch (e) {
        // API no disponible
    }
}

// ─────────────────────────────────────────────────────────
//  INICIALIZAR CHAT
// ─────────────────────────────────────────────────────────
function inicializarChat() {
    // FAB
    document.getElementById('btn-abrir-chat').addEventListener('click', abrirChat);
    document.getElementById('btn-cerrar-chat').addEventListener('click', cerrarChat);
    document.getElementById('fab-donpilsen').addEventListener('click', abrirChat);
    
    // Quick Actions
    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const msg = btn.getAttribute('data-msg');
            if (msg) enviarMensaje(msg);
        });
    });

    // Input de texto
    const input = document.getElementById('chat-input');
    const btnEnviar = document.getElementById('btn-enviar');

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            const msg = input.value.trim();
            if (msg) enviarMensaje(msg);
        }
    });

    // Auto-resize textarea
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    btnEnviar.addEventListener('click', () => {
        const msg = input.value.trim();
        if (msg) enviarMensaje(msg);
    });

    // Mensaje de bienvenida
    agregarMensajeDonPilsen(
        `👋 **¡Hola! Soy Don Pilsen, tu Agente Cervecero.**\n\n` +
        `Estoy conectado a tu fábrica. Puedo darte el balance mensual, ` +
        `analizar tus márgenes, diagnosticar mermas o incluso ejecutar órdenes como cancelar lotes y vender barriles.\n\n` +
        `¿En qué te ayudo hoy, jefe?`,
        'llama3'
    );
}

// ─────────────────────────────────────────────────────────
//  ABRIR / CERRAR CHAT
// ─────────────────────────────────────────────────────────
function abrirChat() {
    document.body.classList.add('chat-open');
    setTimeout(() => {
        document.getElementById('chat-input').focus();
        scrollChatAbajo();
    }, 360);
}

function cerrarChat() {
    document.body.classList.remove('chat-open');
}

// ─────────────────────────────────────────────────────────
//  ENVIAR MENSAJE Y OBTENER RESPUESTA DE Don Pilsen
// ─────────────────────────────────────────────────────────
async function enviarMensaje(texto) {
    const input = document.getElementById('chat-input');
    const btnEnviar = document.getElementById('btn-enviar');

    // Si el chat está cerrado, abrirlo
    if (!document.body.classList.contains('chat-open')) {
        abrirChat();
        await new Promise(r => setTimeout(r, 400));
    }

    // Mostrar mensaje del usuario
    agregarMensajeUsuario(texto);
    input.value = '';
    input.style.height = 'auto';
    btnEnviar.disabled = true;

    // Mostrar typing indicator
    const typingId = mostrarTyping();

    try {
        const resp = await fetch(`${API_BASE}/api/bia/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mensaje: texto, historial: window.chatHistorial || [] })
        });

        if (!resp.ok) {
            throw new Error(`Error HTTP ${resp.status}`);
        }

        const contentType = resp.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            quitarTyping(typingId);
            const data = await resp.json();
            agregarMensajeDonPilsen(data.respuesta, data.motor || 'fallback');
            
            window.chatHistorial = window.chatHistorial || [];
            window.chatHistorial.push({ role: 'user', content: texto });
            window.chatHistorial.push({ role: 'assistant', content: data.respuesta });
        } else {
            // Streaming Response
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            
            // We delay bubble creation until first chunk
            let bubble = null;
            let respuestaCompleta = "";
            let primerChunkRecibido = false;
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                if (!primerChunkRecibido) {
                    quitarTyping(typingId);
                    
                    // Create bubble now
                    const container = document.getElementById('chat-messages');
                    const div = document.createElement('div');
                    div.className = 'msg donpilsen';
                    div.innerHTML = `
                        <div class="msg-avatar">🍺</div>
                        <div>
                            <div class="msg-bubble" id="streaming-bubble"></div>
                            <span class="motor-badge llama">⚡ Groq LLaMA 3.1</span>
                        </div>
                    `;
                    container.appendChild(div);
                    bubble = div.querySelector('.msg-bubble');
                    
                    primerChunkRecibido = true;
                }

                const chunk = decoder.decode(value, { stream: true });
                respuestaCompleta += chunk;
                bubble.innerHTML = renderMarkdown(respuestaCompleta);
                scrollChatAbajo();
            }
            
            if (!primerChunkRecibido) quitarTyping(typingId); // In case stream was completely empty
            if (bubble) bubble.removeAttribute('id');
            window.chatHistorial = window.chatHistorial || [];
            window.chatHistorial.push({ role: 'user', content: texto });
            window.chatHistorial.push({ role: 'assistant', content: respuestaCompleta });
        }

        // Re-verificar estado de Ollama tras la respuesta
        verificarEstadoOllama();

    } catch (err) {
        quitarTyping(typingId);
        agregarMensajeDonPilsen(
            "Lo siento, ocurrió un error al conectar con mi base de datos de la fábrica. 🚨", 
            'error'
        );
    } finally {
        btnEnviar.disabled = false;
        input.focus();
    }
}

// ─────────────────────────────────────────────────────────
//  RENDERIZAR MENSAJES
// ─────────────────────────────────────────────────────────
function agregarMensajeUsuario(texto) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'msg user';
    div.innerHTML = `
        <div class="msg-avatar">👤</div>
        <div class="msg-bubble">${escapeHtml(texto)}</div>
    `;
    container.appendChild(div);
    scrollChatAbajo();
}

function agregarMensajeDonPilsen(texto, motor = 'fallback') {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'msg donpilsen';

    const motorLabel = motor === 'llama'
        ? `<span class="motor-badge llama">⚡ Groq LLaMA 3.1</span>`
        : `<span class="motor-badge fallback">🔵 Análisis ERP</span>`;

    div.innerHTML = `
        <div class="msg-avatar">🍺</div>
        <div>
            <div class="msg-bubble">${renderMarkdown(texto)}</div>
            ${motorLabel}
        </div>
    `;
    container.appendChild(div);
    scrollChatAbajo();
}

function mostrarTyping() {
    const container = document.getElementById('chat-messages');
    const id = 'typing-' + Date.now();
    const div = document.createElement('div');
    div.className = 'msg donpilsen';
    div.id = id;
    div.innerHTML = `
        <div class="msg-avatar">🍺</div>
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    container.appendChild(div);
    scrollChatAbajo();
    return id;
}

function quitarTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function scrollChatAbajo() {
    const container = document.getElementById('chat-messages');
    setTimeout(() => {
        container.scrollTop = container.scrollHeight;
    }, 50);
}

// ─────────────────────────────────────────────────────────
//  RENDERIZADOR DE MARKDOWN BÁSICO
// ─────────────────────────────────────────────────────────
function renderMarkdown(texto) {
    let html = escapeHtml(texto);

    // Bloques de código ```
    html = html.replace(/```([\s\S]*?)```/g, (_, code) =>
        `<pre>${code.trim()}</pre>`
    );

    // Código inline `text`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Negrita **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Cursiva *text*
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Títulos ### y ##
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');

    // Emojis de riesgo — highlight
    html = html.replace(/🔴 (.*?)(<br>|$)/g, '<span class="risk-red">🔴 $1</span><br>');
    html = html.replace(/🟠 (.*?)(<br>|$)/g, '<span class="risk-orange">🟠 $1</span><br>');
    html = html.replace(/🟡 (.*?)(<br>|$)/g, '<span class="risk-yellow">🟡 $1</span><br>');
    html = html.replace(/✅ (.*?)(<br>|$)/g, '<span class="risk-green">✅ $1</span><br>');

    // Saltos de línea
    html = html.replace(/\n/g, '<br>');

    // Listas: líneas que empiezan con "• " o "- " o "* "
    html = html.replace(/((<br>|^)[•\-\*] .+)+/g, (block) => {
        const items = block.split(/<br>/).filter(line => /^[•\-\*] /.test(line.trim()));
        if (!items.length) return block;
        const liItems = items.map(line => `<li>${line.replace(/^[•\-\*] /, '').trim()}</li>`).join('');
        return `<ul>${liItems}</ul>`;
    });

    return html;
}

function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ─────────────────────────────────────────────────────────
//  CARGA DE FILTROS
// ─────────────────────────────────────────────────────────
async function cargarFiltros() {
    const selectReceta = document.getElementById("filtro-carrera");
    const selectMes    = document.getElementById("filtro-mes");

    try {
        const respuesta = await fetch(`${API_BASE}/api/filtros`);
        const json = await respuesta.json();

        selectReceta.innerHTML = '<option value="">Todas las Recetas</option>';
        json.data.forEach(item => {
            const opcion = document.createElement("option");
            opcion.value = item.id;
            opcion.textContent = item.name;
            selectReceta.appendChild(opcion);
        });

        const resDos = await fetch(`${API_BASE}/api/kpi/grafico_dos`);
        const jsonDos = await resDos.json();
        selectMes.innerHTML = '<option value="">Todos los Meses</option>';
        jsonDos.data.forEach(item => {
            const opcion = document.createElement("option");
            opcion.value = item.mes;
            opcion.textContent = item.mes;
            selectMes.appendChild(opcion);
        });

    } catch (error) {
        console.error("Error al cargar los filtros:", error);
        selectReceta.innerHTML = '<option value="">Error de conexión con la API</option>';
    }
}

// ─────────────────────────────────────────────────────────
//  CARGA DE GRÁFICOS Y KPIs
// ─────────────────────────────────────────────────────────
async function cargarGraficos(recetaId, mes) {
    try {
        let urlUno = `${API_BASE}/api/kpi/grafico_uno`;
        const params = [];
        if (recetaId) params.push(`receta_id=${recetaId}`);
        if (mes)      params.push(`mes=${mes}`);
        if (params.length) urlUno += '?' + params.join('&');

        const respUno  = await fetch(urlUno);
        const jsonUno  = await respUno.json();
        const datosUno = jsonUno.data;

        const labelsUno   = datosUno.map(d => d.codigo_batch);
        const dataLitros  = datosUno.map(d => parseFloat(d.litros_producidos) || 0);
        const recetasUno  = datosUno.map(d => d.nombre_receta || 'Desconocida');

        const totalLitros = dataLitros.reduce((a, b) => a + b, 0);
        document.getElementById("kpi-litros").textContent = totalLitros.toFixed(0) + " L";
        document.getElementById("kpi-lotes").textContent  = datosUno.length;

        if (chartUno) chartUno.destroy();
        const ctxUno = document.getElementById('graficoUno').getContext('2d');
        chartUno = new Chart(ctxUno, {
            type: 'bar',
            data: {
                labels: labelsUno,
                datasets: [{
                    label: 'Litros Producidos',
                    data: dataLitros,
                    backgroundColor: 'rgba(247, 201, 72, 0.7)',
                    borderColor:     'rgba(232, 165, 0, 1)',
                    borderWidth: 2,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { labels: { color: '#7d8fa8', font: { family: 'Inter' } } },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const litros = context.raw;
                                return `${litros} Litros`;
                            },
                            afterLabel: function(context) {
                                const idx = context.dataIndex;
                                return `Receta: ${recetasUno[idx]}`;
                            }
                        }
                    }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#4a5870' }, grid: { color: 'rgba(255,255,255,0.04)' } },
                    x: { ticks: { color: '#4a5870', maxRotation: 30 }, grid: { color: 'rgba(255,255,255,0.04)' } }
                }
            }
        });

        const respDos  = await fetch(`${API_BASE}/api/kpi/grafico_dos`);
        const jsonDos  = await respDos.json();
        const datosDos = jsonDos.data;

        const labelsDos    = datosDos.map(d => d.mes);
        const producido    = datosDos.map(d => parseFloat(d.litros_producidos) || 0);
        const vendido      = datosDos.map(d => parseFloat(d.litros_vendidos)   || 0);
        const stockMensual = datosDos.map(d => parseFloat(d.stock_actual)      || 0);

        const stockTotal     = stockMensual.reduce((a, b) => a + b, 0);
        const totalProducido = producido.reduce((a, b) => a + b, 0);
        const totalVendido   = vendido.reduce((a, b) => a + b, 0);
        const ratioDespacho  = totalProducido > 0 ? (totalVendido / totalProducido) * 100 : 0;

        document.getElementById("kpi-abv").textContent         = stockTotal.toFixed(0) + " L";
        document.getElementById("kpi-rendimiento").textContent = ratioDespacho.toFixed(1) + "%";

        if (chartDos) chartDos.destroy();
        const ctxDos = document.getElementById('graficoDos').getContext('2d');
        chartDos = new Chart(ctxDos, {
            type: 'line',
            data: {
                labels: labelsDos,
                datasets: [
                    {
                        label: 'Litros Producidos',
                        data: producido,
                        backgroundColor: 'rgba(96,165,250,0.1)',
                        borderColor: 'rgba(96,165,250,1)',
                        borderWidth: 2,
                        fill: true, tension: 0.4,
                        pointRadius: 5, pointBackgroundColor: 'rgba(96,165,250,1)'
                    },
                    {
                        label: 'Litros Vendidos',
                        data: vendido,
                        backgroundColor: 'rgba(74,222,128,0.1)',
                        borderColor: 'rgba(74,222,128,1)',
                        borderWidth: 2,
                        fill: false, tension: 0.4,
                        pointRadius: 5, pointBackgroundColor: 'rgba(74,222,128,1)'
                    },
                    {
                        label: 'Stock en Bodega',
                        data: stockMensual,
                        backgroundColor: 'rgba(255,255,255,0.04)',
                        borderColor: 'rgba(200,200,200,0.7)',
                        borderWidth: 2,
                        fill: false, tension: 0.4,
                        pointRadius: 5, borderDash: [5, 4],
                        pointBackgroundColor: 'rgba(200,200,200,1)'
                    }
                ]
            },
            options: {
                responsive: true,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { labels: { color: '#7d8fa8', font: { family: 'Inter' } } },
                    tooltip: {
                        callbacks: {
                            label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} L`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { color: '#4a5870' },
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        title: { display: true, text: 'Litros', color: '#4a5870' }
                    },
                    x: {
                        ticks: { color: '#4a5870' },
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    }
                }
            }
        });

        // Gráfico 3: Pipeline de Estado (Doughnut)
        const respTres = await fetch(`${API_BASE}/api/kpi/grafico_tres`);
        const jsonTres = await respTres.json();
        
        // Colores para estados: done(verde), ready(azul), fermenting(naranja), mashing(rojo), draft(gris)
        const coloresEstado = {
            'done': 'rgba(74,222,128,0.85)',
            'ready': 'rgba(96,165,250,0.85)',
            'fermenting': 'rgba(247,201,72,0.85)',
            'mashing': 'rgba(248,113,113,0.85)',
            'draft': 'rgba(200,200,200,0.6)'
        };
        const traducirEstado = {
            'done': 'Terminado',
            'ready': 'Listo para Envasar',
            'fermenting': 'Fermentando',
            'mashing': 'Cocción / Macerado',
            'draft': 'Borrador'
        };

        const labelsTres = jsonTres.data.map(d => traducirEstado[d.estado] || d.estado);
        const dataTres = jsonTres.data.map(d => parseInt(d.cantidad) || 0);
        const bgColorsTres = jsonTres.data.map(d => coloresEstado[d.estado] || 'rgba(150,150,150,0.8)');

        if (chartTres) chartTres.destroy();
        const ctxTres = document.getElementById('graficoTres').getContext('2d');
        chartTres = new Chart(ctxTres, {
            type: 'doughnut',
            data: {
                labels: labelsTres,
                datasets: [{
                    data: dataTres,
                    backgroundColor: bgColorsTres,
                    borderWidth: 2,
                    borderColor: 'var(--bg-card)'
                }]
            },
            options: {
                responsive: true,
                cutout: '65%',
                plugins: {
                    legend: { position: 'right', labels: { color: '#7d8fa8', font: { family: 'Inter' } } }
                }
            }
        });

        // Gráfico 4: Costo vs Rentabilidad (Bar)
        const respCuatro = await fetch(`${API_BASE}/api/kpi/grafico_cuatro`);
        const jsonCuatro = await respCuatro.json();
        
        const labelsCuatro = jsonCuatro.data.map(d => d.receta);
        const dataCosto = jsonCuatro.data.map(d => parseFloat(d.avg_costo_litro) || 0);
        const dataVenta = jsonCuatro.data.map(d => parseFloat(d.avg_precio_venta_litro) || 0);
        const dataMargen = jsonCuatro.data.map(d => parseFloat(d.margen_porcentaje) || 0);
        
        if (chartCuatro) chartCuatro.destroy();
        const ctxCuatro = document.getElementById('graficoCuatro').getContext('2d');
        chartCuatro = new Chart(ctxCuatro, {
            type: 'bar',
            data: {
                labels: labelsCuatro,
                datasets: [
                    {
                        label: 'Costo x Litro',
                        data: dataCosto,
                        backgroundColor: 'rgba(248,113,113,0.7)',
                        borderColor: 'rgba(220,38,38,1)',
                        borderWidth: 2,
                        borderRadius: 6
                    },
                    {
                        label: 'Venta x Litro',
                        data: dataVenta,
                        backgroundColor: 'rgba(74,222,128,0.7)',
                        borderColor: 'rgba(22,163,74,1)',
                        borderWidth: 2,
                        borderRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { labels: { color: '#7d8fa8', font: { family: 'Inter' } } },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP' }).format(context.parsed.y);
                                }
                                if (context.datasetIndex === 1) { // Barra verde de Venta
                                    const margen = dataMargen[context.dataIndex];
                                    label += ` (Margen: ${margen}%)`;
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    y: { 
                        beginAtZero: true, 
                        ticks: { 
                            color: '#4a5870',
                            callback: function(value) {
                                return '$' + value;
                            }
                        }, 
                        grid: { color: 'rgba(255,255,255,0.04)' } 
                    },
                    x: { ticks: { color: '#4a5870', maxRotation: 30 }, grid: { color: 'rgba(255,255,255,0.04)' } }
                }
            }
        });

    } catch (error) {
        console.error("Error al cargar los gráficos:", error);
        document.getElementById("kpi-litros").textContent = "Error API";
    }
}

// ─────────────────────────────────────────────────────────
//  EXPORTACIÓN PDF
// ─────────────────────────────────────────────────────────
function configurarExportacionPDF() {
    const btnExportar = document.getElementById("btn-exportar");

    btnExportar.addEventListener("click", () => {
        btnExportar.style.display = "none";
        const elementoAExportar = document.getElementById("panel-principal");
        
        // Calcular dimensiones para un ajuste perfecto en 1 sola página PDF sin márgenes blancos
        const w = elementoAExportar.scrollWidth;
        const h = elementoAExportar.scrollHeight;
        
        const opciones = {
            margin: 0,
            filename: 'reporte_produccion_cervecera.pdf',
            image: { type: 'jpeg', quality: 1.0 },
            html2canvas: {
                scale: 2,
                backgroundColor: '#0a0f1a', // Fondo oscuro nativo del ERP
                useCORS: true, 
                logging: false,
                width: w,
                height: h,
                windowWidth: w
            },
            jsPDF: { unit: 'px', format: [w, h], orientation: w > h ? 'landscape' : 'portrait' }
        };
        html2pdf().set(opciones).from(elementoAExportar).save()
            .then(() => { btnExportar.style.display = ""; })
            .catch(err => {
                console.error("Error al exportar PDF:", err);
                btnExportar.style.display = "";
            });
    });
}