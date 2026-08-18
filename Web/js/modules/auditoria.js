/**
 * auditoria.js - Pantalla de consulta del Registro de Auditoría.
 *
 * SOLO LECTURA. No existe -- ni debe agregarse -- ninguna acción que borre o
 * edite el registro: un log que el administrador puede borrar no sirve como
 * auditoría. El backend tampoco expone endpoints de escritura (ver
 * backend/routers/auditoria.py -> solo GET).
 *
 * SEGURIDAD DE RENDERIZADO: el registro guarda texto que viene del usuario
 * (descripciones, valores anteriores/nuevos, rutas, nombres de producto). TODO
 * dato interpolado pasa por Utils.escapeHtml antes de entrar al innerHTML; de
 * lo contrario, un producto llamado `<img onerror=...>` se ejecutaría en la
 * pantalla de quien audita, que es justo el usuario con más privilegios.
 */
const Auditoria = {
    _filtros: {},
    _pagina: 1,
    _porPagina: 50,
    _datos: { filas: [], total: 0, paginas: 1 },

    /** Punto de entrada del menú. */
    async showConsulta() {
        this._pagina = 1;
        const hoy = Utils.today();
        this._filtros = { desde: '', hasta: hoy, usuario: '', modulo: '', accion: '', resultado: '', texto: '' };
        Utils.showView(this._plantilla());
        this._bind();
        await this._cargarOpciones();
        await this.buscar();
    },

    _plantilla() {
        return `
            <div class="section-header d-flex justify-content-between align-items-center">
                <h4><i class="bi bi-clipboard-check"></i> Registro de Auditoría</h4>
                <button class="btn btn-sm btn-outline-success" data-action="Auditoria.exportar">
                    <i class="bi bi-file-earmark-spreadsheet"></i> Exportar CSV
                </button>
            </div>
            <div class="alert alert-secondary py-2">
                <small>
                    <i class="bi bi-shield-lock"></i>
                    Registro <strong>inmutable</strong> y de <strong>solo consulta</strong>: guarda toda
                    escritura contra la API (altas, modificaciones, anulaciones y también los intentos
                    rechazados). Nadie puede editarlo ni borrarlo desde el sistema, ni siquiera el administrador.
                </small>
            </div>
            <div class="card mb-3">
                <div class="card-body py-2">
                    <div class="row g-2 align-items-end">
                        <div class="col-md-2">
                            <label class="form-label mb-0"><small>Desde</small></label>
                            <input type="date" class="form-control form-control-sm" id="audDesde">
                        </div>
                        <div class="col-md-2">
                            <label class="form-label mb-0"><small>Hasta</small></label>
                            <input type="date" class="form-control form-control-sm" id="audHasta">
                        </div>
                        <div class="col-md-2">
                            <label class="form-label mb-0"><small>Usuario</small></label>
                            <select class="form-select form-select-sm" id="audUsuario"><option value="">(todos)</option></select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label mb-0"><small>Módulo</small></label>
                            <select class="form-select form-select-sm" id="audModulo"><option value="">(todos)</option></select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label mb-0"><small>Acción</small></label>
                            <select class="form-select form-select-sm" id="audAccion"><option value="">(todas)</option></select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label mb-0"><small>Resultado</small></label>
                            <select class="form-select form-select-sm" id="audResultado">
                                <option value="">(todos)</option>
                                <option value="exito">Éxito</option>
                                <option value="rechazado">Rechazado</option>
                            </select>
                        </div>
                        <div class="col-md-8">
                            <label class="form-label mb-0"><small>Buscar en descripción, N° de registro o ruta</small></label>
                            <input type="text" class="form-control form-control-sm" id="audTexto" placeholder="ej: factura 32">
                        </div>
                        <div class="col-md-4 text-end">
                            <button class="btn btn-sm btn-primary" data-action="Auditoria.aplicarFiltros">
                                <i class="bi bi-search"></i> Buscar
                            </button>
                            <button class="btn btn-sm btn-outline-secondary" data-action="Auditoria.limpiar">
                                Limpiar
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            <div id="audResumen" class="mb-2 text-muted"><small>Cargando…</small></div>
            <div id="audTabla"></div>
            <div id="audPaginacion" class="d-flex justify-content-between align-items-center mt-2"></div>
        `;
    },

    _bind() {
        const texto = document.getElementById('audTexto');
        if (texto && !texto.__audBound) {
            texto.addEventListener('keydown', (e) => { if (e.key === 'Enter') Auditoria.aplicarFiltros(); });
            texto.__audBound = true;
        }
        const hasta = document.getElementById('audHasta');
        if (hasta) hasta.value = this._filtros.hasta || '';
    },

    /** Poblar los desplegables con los valores realmente presentes en el registro. */
    async _cargarOpciones() {
        let opciones;
        try {
            opciones = await API.auditoria.filtros();
        } catch (err) {
            console.warn('No se pudieron cargar los filtros de auditoría:', err.message);
            return;
        }
        const llenar = (id, valores) => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const actual = sel.value;
            const primera = sel.options[0] ? sel.options[0].outerHTML : '';
            sel.innerHTML = primera + (valores || []).map(v =>
                `<option value="${Utils.escapeHtml(v)}">${Utils.escapeHtml(v)}</option>`
            ).join('');
            sel.value = actual;
        };
        llenar('audUsuario', opciones.usuarios);
        llenar('audModulo', opciones.modulos);
        llenar('audAccion', opciones.acciones);
    },

    _leerFiltros() {
        const val = (id) => (document.getElementById(id)?.value || '').trim();
        this._filtros = {
            desde: val('audDesde'),
            hasta: val('audHasta'),
            usuario: val('audUsuario'),
            modulo: val('audModulo'),
            accion: val('audAccion'),
            resultado: val('audResultado'),
            texto: val('audTexto')
        };
        return this._filtros;
    },

    aplicarFiltros() {
        this._leerFiltros();
        this._pagina = 1;
        return this.buscar();
    },

    limpiar() {
        ['audDesde', 'audHasta', 'audTexto'].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = '';
        });
        ['audUsuario', 'audModulo', 'audAccion', 'audResultado'].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = '';
        });
        return this.aplicarFiltros();
    },

    async buscar() {
        try {
            this._datos = await API.auditoria.consultar({
                ...this._filtros, pagina: this._pagina, por_pagina: this._porPagina
            });
        } catch (err) {
            document.getElementById('audTabla').innerHTML =
                `<div class="alert alert-danger">${Utils.escapeHtml(err.message || String(err))}</div>`;
            document.getElementById('audResumen').innerHTML = '';
            document.getElementById('audPaginacion').innerHTML = '';
            return;
        }
        this._render();
    },

    paginaAnterior() { if (this._pagina > 1) { this._pagina--; this.buscar(); } },
    paginaSiguiente() { if (this._pagina < (this._datos.paginas || 1)) { this._pagina++; this.buscar(); } },

    _render() {
        const d = this._datos;
        const resumen = document.getElementById('audResumen');
        if (resumen) {
            resumen.innerHTML = `<small><i class="bi bi-list-ol"></i> ${d.total} movimiento(s) registrado(s)` +
                ` — página ${d.pagina} de ${d.paginas}</small>`;
        }

        if (!d.filas.length) {
            document.getElementById('audTabla').innerHTML =
                '<div class="alert alert-info">No hay movimientos que coincidan con el filtro.</div>';
            document.getElementById('audPaginacion').innerHTML = '';
            return;
        }

        // Todo valor que provenga del registro se escapa: son datos que en
        // última instancia escribió un usuario del sistema.
        const e = (v) => Utils.escapeHtml(v === null || v === undefined ? '' : String(v));
        const corto = (v, n = 90) => {
            const s = v === null || v === undefined ? '' : String(v);
            return s.length > n ? s.slice(0, n) + '…' : s;
        };

        const filas = d.filas.map((r) => {
            const ok = r.resultado === 'exito';
            const badge = ok
                ? '<span class="badge bg-success">Éxito</span>'
                : `<span class="badge bg-danger">Rechazado ${e(r.codigo_http)}</span>`;
            const registro = [r.tipo_registro, r.numero_registro].filter(Boolean).map(e).join(' N° ');
            const cambio = (r.valor_anterior || r.valor_nuevo)
                ? `<button class="btn btn-link btn-sm p-0" data-action="Auditoria.verDetalle" data-arg="${e(r.id)}">ver antes/después</button>`
                : '<span class="text-muted">—</span>';
            return `
                <tr class="${ok ? '' : 'table-danger'}">
                    <td class="text-nowrap"><small>${e(r.fecha_hora)}</small></td>
                    <td class="text-nowrap"><strong>${e(r.usuario)}</strong><br><small class="text-muted">${e(r.rol)}</small></td>
                    <td>${e(r.modulo)}</td>
                    <td>${e(r.accion)}</td>
                    <td>${registro || '<span class="text-muted">—</span>'}</td>
                    <td><small>${e(corto(r.descripcion, 140))}</small></td>
                    <td class="text-nowrap">${cambio}</td>
                    <td class="text-nowrap"><small>${e(r.ip)}</small></td>
                    <td class="text-nowrap">${badge}</td>
                </tr>`;
        }).join('');

        document.getElementById('audTabla').innerHTML = `
            <div class="grid-container">
                <table class="table table-sm table-bordered table-aldia" id="audGrid">
                    <thead>
                        <tr>
                            <th>Fecha y hora</th><th>Usuario</th><th>Módulo</th><th>Acción</th>
                            <th>Registro</th><th>Descripción</th><th>Cambio</th><th>IP</th><th>Resultado</th>
                        </tr>
                    </thead>
                    <tbody>${filas}</tbody>
                </table>
            </div>`;

        document.getElementById('audPaginacion').innerHTML = `
            <div>
                <button class="btn btn-sm btn-outline-secondary" data-action="Auditoria.paginaAnterior"
                    ${d.pagina <= 1 ? 'disabled' : ''}><i class="bi bi-chevron-left"></i> Anterior</button>
                <button class="btn btn-sm btn-outline-secondary" data-action="Auditoria.paginaSiguiente"
                    ${d.pagina >= d.paginas ? 'disabled' : ''}>Siguiente <i class="bi bi-chevron-right"></i></button>
            </div>
            <small class="text-muted">Mostrando ${d.filas.length} de ${d.total} — ordenado por fecha descendente</small>`;

        if (window.App && App.bindDataActions) App.bindDataActions();
    },

    /** Detalle completo del antes y el después de una fila. */
    verDetalle(id) {
        const r = (this._datos.filas || []).find(f => String(f.id) === String(id));
        if (!r) return;
        const e = Utils.escapeHtml;
        const bloque = (titulo, json, clase) => `
            <h6 class="mt-3">${titulo}</h6>
            <pre class="${clase} p-2 rounded" style="white-space:pre-wrap;word-break:break-all;font-size:.8rem">${e(this._formatear(json))}</pre>`;
        Utils.showModal(
            `Auditoría N° ${e(r.id)} — ${e(r.accion)}`,
            `<dl class="row mb-0">
                <dt class="col-4">Fecha y hora</dt><dd class="col-8">${e(r.fecha_hora)}</dd>
                <dt class="col-4">Usuario</dt><dd class="col-8">${e(r.usuario)} (${e(r.rol)}) — id ${e(r.usuario_id)}</dd>
                <dt class="col-4">Módulo / acción</dt><dd class="col-8">${e(r.modulo)} / ${e(r.accion)}</dd>
                <dt class="col-4">Registro afectado</dt><dd class="col-8">${e(r.tipo_registro)} ${e(r.numero_registro)}</dd>
                <dt class="col-4">Petición</dt><dd class="col-8"><code>${e(r.metodo)} ${e(r.ruta)}</code></dd>
                <dt class="col-4">IP de origen</dt><dd class="col-8">${e(r.ip)}</dd>
                <dt class="col-4">Resultado</dt><dd class="col-8">${e(r.resultado)} (HTTP ${e(r.codigo_http)})</dd>
                <dt class="col-4">Descripción</dt><dd class="col-8">${e(r.descripcion)}</dd>
            </dl>
            ${r.valor_anterior ? bloque('Valor anterior', r.valor_anterior, 'bg-danger-subtle') : ''}
            ${r.valor_nuevo ? bloque('Valor nuevo', r.valor_nuevo, 'bg-success-subtle') : ''}`
        );
    },

    _formatear(json) {
        try { return JSON.stringify(JSON.parse(json), null, 2); }
        catch (err) { return String(json); }
    },

    /** Exportar el filtro actual a CSV. Exportar es una lectura: no vacía el registro. */
    async exportar() {
        this._leerFiltros();
        try {
            await API.auditoria.exportarCsv(this._filtros);
            Utils.toast('Exportación generada', 'Auditoría', 'success');
        } catch (err) {
            Utils.toast('No se pudo exportar: ' + (err.message || err), 'Auditoría', 'error');
        }
    }
};

window.Auditoria = Auditoria;
