/**
 * liquidaciones.js - Módulo de Liquidaciones Agropecuarias
 * Soporta Liquidación Primaria de Granos (LPG) y Liquidación Sector Pecuario / Hacienda (LSP).
 * Cumple CSP estricta mediante delegación declarativa data-action.
 */
const Liquidaciones = {
    rubroActual: 'granos',
    deduccionesTemp: [],
    retencionesTemp: [],
    ultimasFilas: [],

    _extraerValor(argOrEl, el, attr = 'id') {
        if (typeof argOrEl === 'number' || (typeof argOrEl === 'string' && argOrEl !== '')) {
            return argOrEl;
        }
        const nodo = (argOrEl && argOrEl.dataset) ? argOrEl : el;
        if (nodo && nodo.dataset) {
            return nodo.dataset[attr] || nodo.dataset.id || nodo.dataset.arg || nodo.dataset.rubro || '';
        }
        return '';
    },

    async showGranos() {
        this.rubroActual = 'granos';
        await this._mostrarBandeja('granos');
    },

    async showHacienda() {
        this.rubroActual = 'hacienda';
        await this._mostrarBandeja('hacienda');
    },

    async _mostrarBandeja(rubro, filtros = {}) {
        this.rubroActual = rubro;
        const esGranos = rubro === 'granos';
        const titulo = esGranos
            ? 'Liquidaciones de Granos (LPG)'
            : 'Liquidaciones de Hacienda (LSP)';
        const icono = esGranos ? 'bi-moisture' : 'bi-tags';
        const gradiente = esGranos
            ? 'linear-gradient(135deg,#2e7d32,#43a047)'
            : 'linear-gradient(135deg,#6d4c41,#8d6e63)';
        const textoBotonNueva = esGranos
            ? 'Nueva Liquidación de Granos'
            : 'Nueva Liquidación Pecuaria';

        let filas = [];
        try {
            const params = Object.assign({ rubro }, filtros);
            filas = await API.liquidaciones.getAll(params);
        } catch (err) {
            Utils.toast('Error al cargar liquidaciones: ' + err.message, 'Liquidaciones', 'error');
            filas = [];
        }
        this.ultimasFilas = filas;

        const borradores = filas.filter(f => f.estado === 'borrador');
        const htmlBorradores = borradores.length > 0
            ? `
            <div class="card border-warning mb-3">
                <div class="card-header bg-warning text-dark d-flex justify-content-between align-items-center py-2">
                    <strong><i class="bi bi-hourglass-split"></i> Bandeja de Borradores Pendientes de Confirmar (${borradores.length})</strong>
                    <span class="small">La confirmación impacta stock neto y cuenta corriente</span>
                </div>
                <div class="card-body p-2">
                    <div class="table-responsive">
                        <table class="table table-sm table-hover mb-0 align-middle">
                            <thead>
                                <tr>
                                    <th>N°</th>
                                    <th>Fecha</th>
                                    <th>Operación</th>
                                    <th>Tercero</th>
                                    <th>Comprobante</th>
                                    <th class="text-end">Neto Liquidado</th>
                                    <th class="text-end">Acciones</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${borradores.map(b => `
                                    <tr>
                                        <td>#${Utils.escapeHtml(String(b.id))}</td>
                                        <td>${Utils.escapeHtml(Utils.formatDate(b.fecha))}</td>
                                        <td><span class="badge bg-${b.operacion === 'venta' ? 'primary' : 'info'}">${Utils.escapeHtml(b.operacion)}</span></td>
                                        <td>${Utils.escapeHtml(b.tercero || b.cliente || b.proveedor || '')}</td>
                                        <td>${Utils.escapeHtml(b.num_comprobante || '—')}</td>
                                        <td class="text-end fw-bold">${Utils.escapeHtml(Utils.formatCurrency(b.neto_liquidado || 0))}</td>
                                        <td class="text-end">
                                            <button type="button" class="btn btn-sm btn-success me-1" data-action="Liquidaciones.confirmarBorrador" data-id="${Utils.escapeHtml(String(b.id))}">
                                                <i class="bi bi-check2-circle"></i> Confirmar
                                            </button>
                                            <button type="button" class="btn btn-sm btn-outline-primary me-1" data-action="Liquidaciones.verDetalle" data-id="${Utils.escapeHtml(String(b.id))}">
                                                <i class="bi bi-eye"></i> Detalle
                                            </button>
                                            <button type="button" class="btn btn-sm btn-outline-danger" data-action="Liquidaciones.anular" data-id="${Utils.escapeHtml(String(b.id))}">
                                                <i class="bi bi-x-circle"></i> Anular
                                            </button>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>`
            : `
            <div class="alert alert-light border d-flex justify-content-between align-items-center py-2 mb-3">
                <span><i class="bi bi-check-circle text-success"></i> No hay borradores pendientes de confirmar en ${Utils.escapeHtml(esGranos ? 'granos' : 'hacienda')}.</span>
                <span class="small text-muted">Total registradas: ${filas.length}</span>
            </div>`;

        const filasTabla = filas.map(f => {
            const dom = f.datos_dominio || {};
            const infoDominio = esGranos
                ? [dom.especie, dom.campana ? `Camp. ${dom.campana}` : '', dom.carta_porte ? `CP ${dom.carta_porte}` : '', dom.grado ? `Gr. ${dom.grado}` : ''].filter(Boolean).join(' · ')
                : [dom.categoria, dom.dte ? `DTE ${dom.dte}` : '', dom.renspa ? `RENSPA ${dom.renspa}` : '', dom.tropa ? `Tropa ${dom.tropa}` : ''].filter(Boolean).join(' · ');
            const badgeEstado = f.estado === 'confirmada'
                ? '<span class="badge bg-success">Confirmada</span>'
                : f.estado === 'borrador'
                    ? '<span class="badge bg-warning text-dark">Borrador</span>'
                    : '<span class="badge bg-secondary">Anulada</span>';
            return `
                <tr>
                    <td>#${Utils.escapeHtml(String(f.id))}</td>
                    <td>${Utils.escapeHtml(Utils.formatDate(f.fecha))}</td>
                    <td><span class="badge bg-${f.operacion === 'venta' ? 'primary' : 'info'}">${Utils.escapeHtml(f.operacion)}</span></td>
                    <td>${Utils.escapeHtml(f.tercero || f.cliente || f.proveedor || '')}</td>
                    <td>
                        <div>${Utils.escapeHtml(f.num_comprobante || '—')}</div>
                        ${f.codigo_autorizacion ? `<small class="text-success">COE: ${Utils.escapeHtml(f.codigo_autorizacion)}</small>` : ''}
                        ${infoDominio ? `<div class="small text-muted">${Utils.escapeHtml(infoDominio)}</div>` : ''}
                    </td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(f.total_bruto_operacion || 0))}</td>
                    <td class="text-end text-danger">${Utils.escapeHtml(Utils.formatCurrency(f.total_deducciones || 0))}</td>
                    <td class="text-end text-warning">${Utils.escapeHtml(Utils.formatCurrency(f.total_retenciones || 0))}</td>
                    <td class="text-end fw-bold">${Utils.escapeHtml(Utils.formatCurrency(f.neto_liquidado || 0))}</td>
                    <td>${badgeEstado}</td>
                    <td class="text-end text-nowrap">
                        <button type="button" class="btn btn-sm btn-outline-primary me-1" data-action="Liquidaciones.verDetalle" data-id="${Utils.escapeHtml(String(f.id))}" title="Ver detalle">
                            <i class="bi bi-eye"></i>
                        </button>
                        ${f.estado === 'borrador' ? `
                            <button type="button" class="btn btn-sm btn-success me-1" data-action="Liquidaciones.confirmarBorrador" data-id="${Utils.escapeHtml(String(f.id))}" title="Confirmar borrador">
                                <i class="bi bi-check2"></i>
                            </button>` : ''}
                        ${f.estado !== 'anulada' && !f.codigo_autorizacion ? `
                            <button type="button" class="btn btn-sm btn-outline-secondary me-1" data-action="Liquidaciones.registrarCoe" data-id="${Utils.escapeHtml(String(f.id))}" title="Registrar COE">
                                COE
                            </button>` : ''}
                        ${f.estado !== 'anulada' ? `
                            <button type="button" class="btn btn-sm btn-outline-danger" data-action="Liquidaciones.anular" data-id="${Utils.escapeHtml(String(f.id))}" title="Anular">
                                <i class="bi bi-trash"></i>
                            </button>` : ''}
                    </td>
                </tr>`;
        }).join('');

        const html = `
            <div class="section-header d-flex justify-content-between align-items-center" style="background:${gradiente}">
                <h4 class="mb-0"><i class="bi ${icono}"></i> ${Utils.escapeHtml(titulo)}</h4>
                <div>
                    <button type="button" class="btn btn-light btn-sm fw-bold me-1" data-action="Liquidaciones.crearNueva" data-rubro="${Utils.escapeHtml(rubro)}">
                        <i class="bi bi-plus-circle"></i> ${Utils.escapeHtml(textoBotonNueva)}
                    </button>
                    <button type="button" class="btn btn-outline-light btn-sm" data-action="${esGranos ? 'Liquidaciones.showHacienda' : 'Liquidaciones.showGranos'}">
                        <i class="bi bi-arrow-left-right"></i> Ir a ${esGranos ? 'Hacienda' : 'Granos'}
                    </button>
                </div>
            </div>

            ${htmlBorradores}

            <div class="form-card mb-3">
                <div class="row g-2 align-items-end">
                    <div class="col-md-3">
                        <label class="form-label-sm">Operación</label>
                        <select class="form-select form-select-sm" id="filtroLiqOperacion">
                            <option value="">Todas</option>
                            <option value="compra" ${filtros.operacion === 'compra' ? 'selected' : ''}>Compra (a productor/proveedor)</option>
                            <option value="venta" ${filtros.operacion === 'venta' ? 'selected' : ''}>Venta (a acopio/frigorífico/cliente)</option>
                        </select>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label-sm">Estado</label>
                        <select class="form-select form-select-sm" id="filtroLiqEstado">
                            <option value="">Todos</option>
                            <option value="borrador" ${filtros.estado === 'borrador' ? 'selected' : ''}>Borrador</option>
                            <option value="confirmada" ${filtros.estado === 'confirmada' ? 'selected' : ''}>Confirmada</option>
                            <option value="anulada" ${filtros.estado === 'anulada' ? 'selected' : ''}>Anulada</option>
                        </select>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label-sm">CUIT Tercero (Cliente / Proveedor)</label>
                        <input type="text" class="form-control form-control-sm" id="filtroLiqTercero" value="${Utils.escapeHtml(filtros.tercero || '')}" placeholder="Ej: 20123456789">
                    </div>
                    <div class="col-md-2">
                        <button type="button" class="btn btn-sm btn-primary w-100" data-action="Liquidaciones.filtrar">
                            <i class="bi bi-funnel"></i> Filtrar
                        </button>
                    </div>
                </div>
            </div>

            <div class="grid-container">
                <table class="table table-sm table-bordered table-aldia align-middle">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Fecha</th>
                            <th>Operación</th>
                            <th>Tercero</th>
                            <th>Comprobante / Datos</th>
                            <th class="text-end">Bruto c/IVA</th>
                            <th class="text-end">Deducciones</th>
                            <th class="text-end">Retenciones</th>
                            <th class="text-end">Neto Liquidado</th>
                            <th>Estado</th>
                            <th class="text-end">Acciones</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${filasTabla || '<tr><td colspan="11" class="text-center text-muted py-3">Sin liquidaciones registradas para este filtro.</td></tr>'}
                    </tbody>
                </table>
            </div>
        `;
        Utils.showView(html);
    },

    async filtrar() {
        const operacion = document.getElementById('filtroLiqOperacion')?.value || '';
        const estado = document.getElementById('filtroLiqEstado')?.value || '';
        const tercero = (document.getElementById('filtroLiqTercero')?.value || '').trim();
        await this._mostrarBandeja(this.rubroActual, { operacion, estado, tercero });
    },

    async crearNueva(el) {
        const rubro = this._extraerValor(el, null, 'rubro') || this.rubroActual || 'granos';
        this.rubroActual = rubro === 'hacienda' ? 'hacienda' : 'granos';
        const esGranos = this.rubroActual === 'granos';
        this.deduccionesTemp = [];
        this.retencionesTemp = [];

        const [stock, clientes, proveedores] = await Promise.all([
            API.stock.getAll().catch(() => []),
            API.clientes.getAll().catch(() => []),
            API.proveedores.getAll().catch(() => [])
        ]);

        const opcionesStock = [
            '<option value="">-- Sin vincular a código de stock --</option>',
            ...stock.map(s => `<option value="${Utils.escapeHtml(String(s.codigo))}">[${Utils.escapeHtml(String(s.codigo))}] ${Utils.escapeHtml(s.producto)} (${Utils.escapeHtml(String(s.cantidad))} ${Utils.escapeHtml(s.unidad || 'UN')})</option>`)
        ].join('');

        const tercerosList = [
            ...proveedores.map(p => `<option value="${Utils.escapeHtml(p.cuit)}">${Utils.escapeHtml(p.nombre)} (Proveedor)</option>`),
            ...clientes.map(c => `<option value="${Utils.escapeHtml(c.cuit)}">${Utils.escapeHtml(c.nombre)} (Cliente)</option>`)
        ].join('');

        const bloqueDominio = esGranos
            ? `
            <div class="card border-success mb-3">
                <div class="card-header bg-success text-white py-2">
                    <strong><i class="bi bi-moisture"></i> Datos de Campaña, Carta de Porte y Calidad (Granos)</strong>
                </div>
                <div class="card-body">
                    <div class="row g-2">
                        <div class="col-md-2">
                            <label class="form-label-sm">Campaña</label>
                            <input type="text" class="form-control form-control-sm" id="liqCampana" value="2025/2026" placeholder="2025/2026">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label-sm">Especie / Grano</label>
                            <select class="form-select form-select-sm" id="liqEspecie">
                                <option value="Soja">Soja</option>
                                <option value="Maíz">Maíz</option>
                                <option value="Trigo">Trigo</option>
                                <option value="Girasol">Girasol</option>
                                <option value="Sorgo">Sorgo</option>
                                <option value="Cebada">Cebada</option>
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label-sm">Carta de Porte (CPE)</label>
                            <input type="text" class="form-control form-control-sm" id="liqCartaPorte" placeholder="N° Carta de Porte">
                        </div>
                        <div class="col-md-2">
                            <label class="form-label-sm">Grado</label>
                            <select class="form-select form-select-sm" id="liqGrado">
                                <option value="G2">Grado 2 (Estándar)</option>
                                <option value="G1">Grado 1</option>
                                <option value="G3">Grado 3</option>
                                <option value="FG">Fuera de Grado</option>
                            </select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label-sm">Factor</label>
                            <input type="number" step="0.01" class="form-control form-control-sm" id="liqFactor" value="100">
                        </div>
                    </div>
                </div>
            </div>`
            : `
            <div class="card border-secondary mb-3">
                <div class="card-header bg-secondary text-white py-2">
                    <strong><i class="bi bi-tags"></i> Datos de Tropa, DT-e y RENSPA (Hacienda)</strong>
                </div>
                <div class="card-body">
                    <div class="row g-2">
                        <div class="col-md-3">
                            <label class="form-label-sm">N° DT-e (Documento de Tránsito)</label>
                            <input type="text" class="form-control form-control-sm" id="liqDte" placeholder="Ej: 012345678-9">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label-sm">RENSPA</label>
                            <input type="text" class="form-control form-control-sm" id="liqRenspa" placeholder="Ej: 01.001.0.00123/01">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label-sm">N° de Tropa</label>
                            <input type="text" class="form-control form-control-sm" id="liqTropa" placeholder="N° Tropa">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label-sm">Categoría</label>
                            <select class="form-select form-select-sm" id="liqCategoria">
                                <option value="Novillo">Novillo</option>
                                <option value="Novillito">Novillito</option>
                                <option value="Vaquillona">Vaquillona</option>
                                <option value="Vaca">Vaca</option>
                                <option value="Ternero">Ternero/a</option>
                                <option value="Toro">Toro</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>`;

        const opcionesDeduccion = esGranos
            ? `
                <option value="flete">Flete / Acarreo</option>
                <option value="secado">Secado</option>
                <option value="zarandeo">Zarandeo / Limpieza</option>
                <option value="comision">Comisión / Corretaje</option>
                <option value="almacenaje">Almacenaje</option>
                <option value="otro">Otro gasto</option>`
            : `
                <option value="feria">Comisión Feria / Consignatario</option>
                <option value="senasa">Arancel SENASA</option>
                <option value="guia">Guía Municipal / Provincial</option>
                <option value="flete">Flete de Hacienda</option>
                <option value="comision">Comisión</option>
                <option value="otro">Otro gasto</option>`;

        const html = `
            <div class="section-header d-flex justify-content-between align-items-center" style="background:${esGranos ? 'linear-gradient(135deg,#2e7d32,#43a047)' : 'linear-gradient(135deg,#6d4c41,#8d6e63)'}">
                <h4 class="mb-0">
                    <i class="bi ${esGranos ? 'bi-moisture' : 'bi-tags'}"></i>
                    ${esGranos ? 'Nueva Liquidación Primaria de Granos (LPG)' : 'Nueva Liquidación Pecuaria de Hacienda (LSP)'}
                </h4>
                <button type="button" class="btn btn-outline-light btn-sm" data-action="${esGranos ? 'Liquidaciones.showGranos' : 'Liquidaciones.showHacienda'}">
                    <i class="bi bi-arrow-left"></i> Volver al listado
                </button>
            </div>

            <input type="hidden" id="liqRubro" value="${Utils.escapeHtml(this.rubroActual)}">
            <datalist id="dlLiqTerceros">${tercerosList}</datalist>

            <div class="form-card mb-3">
                <h6 class="text-primary mb-2"><i class="bi bi-file-earmark-text"></i> Cabecera de la Operación</h6>
                <div class="row g-2">
                    <div class="col-md-3">
                        <label class="form-label-sm">Tipo de Operación</label>
                        <select class="form-select form-select-sm" id="liqOperacion">
                            <option value="compra">Compra (a Productor / Proveedor)</option>
                            <option value="venta">Venta (a Acopio / Frigorífico / Cliente)</option>
                        </select>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label-sm">CUIT Tercero (Proveedor o Cliente)</label>
                        <input type="text" class="form-control form-control-sm" id="liqTercero" list="dlLiqTerceros" placeholder="CUIT del tercero">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label-sm">Fecha</label>
                        <input type="date" class="form-control form-control-sm" id="liqFecha" value="${Utils.today()}">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label-sm">N° Comprobante</label>
                        <input type="text" class="form-control form-control-sm" id="liqNumComprobante" placeholder="0001-00000001">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label-sm">Estado Inicial</label>
                        <select class="form-select form-select-sm" id="liqEstado">
                            <option value="borrador">Guardar en Borrador</option>
                            <option value="confirmada">Confirmar directo</option>
                        </select>
                    </div>
                </div>
            </div>

            ${bloqueDominio}

            <div class="form-card mb-3">
                <h6 class="text-primary mb-2"><i class="bi bi-box-seam"></i> Detalle de Mercadería y Merma / Desbaste</h6>
                <div class="row g-2">
                    <div class="col-md-3">
                        <label class="form-label-sm">Artículo en Stock (opcional)</label>
                        <select class="form-select form-select-sm" id="liqCodigo">
                            ${opcionesStock}
                        </select>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label-sm">Descripción del Renglón</label>
                        <input type="text" class="form-control form-control-sm" id="liqDescripcion" value="${esGranos ? 'Soja Grado 2' : 'Novillo en pie'}" placeholder="Descripción">
                    </div>
                    ${!esGranos ? `
                    <div class="col-md-1">
                        <label class="form-label-sm">Cabezas</label>
                        <input type="number" min="0" step="1" class="form-control form-control-sm" id="liqCabezas" value="30">
                    </div>` : ''}
                    <div class="col-md-2">
                        <label class="form-label-sm">${esGranos ? 'Cantidad Bruta' : 'Kg Brutos'}</label>
                        <input type="number" min="0" step="0.01" class="form-control form-control-sm" id="liqCantidadBruta" value="${esGranos ? '30000' : '12500'}">
                    </div>
                    <div class="col-md-1">
                        <label class="form-label-sm">${esGranos ? '% Merma' : '% Desbaste'}</label>
                        <input type="number" min="0" max="99" step="0.01" class="form-control form-control-sm" id="liqMermaPct" value="${esGranos ? '1.5' : '4.0'}">
                    </div>
                    <div class="col-md-1">
                        <label class="form-label-sm">Unidad</label>
                        <select class="form-select form-select-sm" id="liqUnidad">
                            <option value="KG">KG</option>
                            <option value="TN">TN</option>
                            <option value="QQ">QQ</option>
                        </select>
                    </div>
                    <div class="col-md-1">
                        <label class="form-label-sm">${esGranos ? 'Precio' : 'Precio/Kg'}</label>
                        <input type="number" min="0" step="0.01" class="form-control form-control-sm" id="liqPrecioUnitario" value="250">
                    </div>
                    <div class="col-md-1">
                        <label class="form-label-sm">% IVA</label>
                        <select class="form-select form-select-sm" id="liqIvaAlicuota">
                            <option value="10.5" selected>10.5%</option>
                            <option value="21">21%</option>
                            <option value="0">0%</option>
                        </select>
                    </div>
                </div>
            </div>

            <div class="row g-3 mb-3">
                <!-- Deducciones -->
                <div class="col-md-6">
                    <div class="form-card h-100">
                        <h6 class="text-danger mb-2"><i class="bi bi-dash-circle"></i> Deducciones (${esGranos ? 'Flete, Secado, Comisión' : 'Feria, SENASA, Guías'})</h6>
                        <div class="row g-2 align-items-end mb-2">
                            <div class="col-md-3">
                                <label class="form-label-sm">Concepto</label>
                                <select class="form-select form-select-sm" id="dedConcepto">
                                    ${opcionesDeduccion}
                                </select>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label-sm">Descripción</label>
                                <input type="text" class="form-control form-control-sm" id="dedDescripcion" placeholder="Detalle del gasto">
                            </div>
                            <div class="col-md-2">
                                <label class="form-label-sm">Base ($)</label>
                                <input type="number" min="0" step="0.01" class="form-control form-control-sm" id="dedBaseImponible" value="0">
                            </div>
                            <div class="col-md-2">
                                <label class="form-label-sm">IVA %</label>
                                <select class="form-select form-select-sm" id="dedIvaAlicuota">
                                    <option value="21">21%</option>
                                    <option value="10.5">10.5%</option>
                                    <option value="0">0%</option>
                                </select>
                            </div>
                            <div class="col-md-1">
                                <button type="button" class="btn btn-sm btn-outline-danger w-100" data-action="Liquidaciones.agregarDeduccion" title="Agregar deducción">
                                    <i class="bi bi-plus"></i>
                                </button>
                            </div>
                        </div>
                        <div id="liqDeduccionesLista">
                            <p class="text-muted small mb-0">Sin deducciones cargadas.</p>
                        </div>
                    </div>
                </div>

                <!-- Retenciones -->
                <div class="col-md-6">
                    <div class="form-card h-100">
                        <h6 class="text-warning mb-2"><i class="bi bi-percent"></i> Retenciones Impositivas (SISA / IVA / Ganancias / IIBB)</h6>
                        <div class="row g-2 align-items-end mb-2">
                            <div class="col-md-3">
                                <label class="form-label-sm">Tipo</label>
                                <select class="form-select form-select-sm" id="retTipo">
                                    <option value="iva">Ret. IVA / SISA</option>
                                    <option value="ganancias">Ret. Ganancias</option>
                                    <option value="iibb">Ret. IIBB</option>
                                    <option value="sellos">Imp. Sellos</option>
                                    <option value="otro">Otra retención</option>
                                </select>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label-sm">Descripción</label>
                                <input type="text" class="form-control form-control-sm" id="retDescripcion" placeholder="RG 4310 / SISA">
                            </div>
                            <div class="col-md-2">
                                <label class="form-label-sm">Alícuota %</label>
                                <input type="number" min="0" max="100" step="0.01" class="form-control form-control-sm" id="retAlicuota" value="0">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label-sm">Importe ($)</label>
                                <input type="number" min="0" step="0.01" class="form-control form-control-sm" id="retImporte" value="0">
                            </div>
                            <div class="col-md-1">
                                <button type="button" class="btn btn-sm btn-outline-warning w-100" data-action="Liquidaciones.agregarRetencion" title="Agregar retención">
                                    <i class="bi bi-plus"></i>
                                </button>
                            </div>
                        </div>
                        <div id="liqRetencionesLista">
                            <p class="text-muted small mb-0">Sin retenciones cargadas.</p>
                        </div>
                    </div>
                </div>
            </div>

            <div class="form-card mb-3">
                <div class="row g-2 align-items-center">
                    <div class="col-md-9">
                        <label class="form-label-sm">Observaciones</label>
                        <input type="text" class="form-control form-control-sm" id="liqObservaciones" placeholder="Observaciones adicionales de la liquidación">
                    </div>
                    <div class="col-md-3 text-end pt-3">
                        <button type="button" class="btn btn-primary w-100" data-action="Liquidaciones.guardar">
                            <i class="bi bi-save"></i> Guardar Liquidación
                        </button>
                    </div>
                </div>
            </div>
        `;
        Utils.showView(html);
    },

    agregarDeduccion() {
        const concepto = document.getElementById('dedConcepto')?.value || 'otro';
        const descripcion = (document.getElementById('dedDescripcion')?.value || '').trim() || concepto;
        const base_imponible = Utils.money(document.getElementById('dedBaseImponible')?.value || 0);
        const iva_alicuota = parseFloat(document.getElementById('dedIvaAlicuota')?.value || '21') || 0;

        if (base_imponible <= 0) {
            Utils.toast('Ingrese una base imponible mayor a cero para la deducción', 'Deducciones', 'warning');
            return;
        }

        this.deduccionesTemp.push({ concepto, descripcion, base_imponible, iva_alicuota });
        const inpBase = document.getElementById('dedBaseImponible');
        const inpDesc = document.getElementById('dedDescripcion');
        if (inpBase) inpBase.value = '0';
        if (inpDesc) inpDesc.value = '';
        this._renderDeduccionesTemp();
    },

    quitarDeduccion(el) {
        const idx = parseInt(this._extraerValor(el, null, 'idx'), 10);
        if (!isNaN(idx) && idx >= 0 && idx < this.deduccionesTemp.length) {
            this.deduccionesTemp.splice(idx, 1);
            this._renderDeduccionesTemp();
        }
    },

    _renderDeduccionesTemp() {
        const cont = document.getElementById('liqDeduccionesLista');
        if (!cont) return;
        if (!this.deduccionesTemp.length) {
            cont.innerHTML = '<p class="text-muted small mb-0">Sin deducciones cargadas.</p>';
            return;
        }
        const filas = this.deduccionesTemp.map((d, i) => `
            <tr>
                <td><span class="badge bg-secondary">${Utils.escapeHtml(d.concepto)}</span></td>
                <td>${Utils.escapeHtml(d.descripcion)}</td>
                <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(d.base_imponible))}</td>
                <td class="text-end">${Utils.escapeHtml(String(d.iva_alicuota))}%</td>
                <td class="text-end">
                    <button type="button" class="btn btn-sm btn-link text-danger p-0" data-action="Liquidaciones.quitarDeduccion" data-id="${i}">
                        <i class="bi bi-x-lg"></i>
                    </button>
                </td>
            </tr>`).join('');
        cont.innerHTML = `
            <table class="table table-sm table-bordered mb-0">
                <thead><tr><th>Concepto</th><th>Descripción</th><th class="text-end">Base</th><th class="text-end">IVA</th><th></th></tr></thead>
                <tbody>${filas}</tbody>
            </table>`;
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
    },

    agregarRetencion() {
        const tipo = document.getElementById('retTipo')?.value || 'iva';
        const descripcion = (document.getElementById('retDescripcion')?.value || '').trim() || tipo;
        const alicuota = parseFloat(document.getElementById('retAlicuota')?.value || '0') || 0;
        const importe = Utils.money(document.getElementById('retImporte')?.value || 0);

        if (alicuota <= 0 && importe <= 0) {
            Utils.toast('Indique una alícuota (%) o un importe fijo para la retención', 'Retenciones', 'warning');
            return;
        }

        this.retencionesTemp.push({
            tipo,
            descripcion,
            base_calculo: 0,
            alicuota,
            importe,
            certificado: ''
        });
        const inpAlic = document.getElementById('retAlicuota');
        const inpImp = document.getElementById('retImporte');
        const inpDesc = document.getElementById('retDescripcion');
        if (inpAlic) inpAlic.value = '0';
        if (inpImp) inpImp.value = '0';
        if (inpDesc) inpDesc.value = '';
        this._renderRetencionesTemp();
    },

    quitarRetencion(el) {
        const idx = parseInt(this._extraerValor(el, null, 'idx'), 10);
        if (!isNaN(idx) && idx >= 0 && idx < this.retencionesTemp.length) {
            this.retencionesTemp.splice(idx, 1);
            this._renderRetencionesTemp();
        }
    },

    _renderRetencionesTemp() {
        const cont = document.getElementById('liqRetencionesLista');
        if (!cont) return;
        if (!this.retencionesTemp.length) {
            cont.innerHTML = '<p class="text-muted small mb-0">Sin retenciones cargadas.</p>';
            return;
        }
        const filas = this.retencionesTemp.map((r, i) => `
            <tr>
                <td><span class="badge bg-warning text-dark">${Utils.escapeHtml(r.tipo)}</span></td>
                <td>${Utils.escapeHtml(r.descripcion)}</td>
                <td class="text-end">${Utils.escapeHtml(String(r.alicuota))}%</td>
                <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(r.importe))}</td>
                <td class="text-end">
                    <button type="button" class="btn btn-sm btn-link text-danger p-0" data-action="Liquidaciones.quitarRetencion" data-id="${i}">
                        <i class="bi bi-x-lg"></i>
                    </button>
                </td>
            </tr>`).join('');
        cont.innerHTML = `
            <table class="table table-sm table-bordered mb-0">
                <thead><tr><th>Tipo</th><th>Descripción</th><th class="text-end">Alíc.</th><th class="text-end">Importe</th><th></th></tr></thead>
                <tbody>${filas}</tbody>
            </table>`;
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
    },

    async guardar() {
        const rubro = document.getElementById('liqRubro')?.value || this.rubroActual || 'granos';
        const operacion = document.getElementById('liqOperacion')?.value || 'compra';
        const tercero = (document.getElementById('liqTercero')?.value || '').trim();
        const fecha = document.getElementById('liqFecha')?.value || Utils.today();
        const num_comprobante = (document.getElementById('liqNumComprobante')?.value || '').trim();
        const estado = document.getElementById('liqEstado')?.value || 'borrador';
        const observaciones = (document.getElementById('liqObservaciones')?.value || '').trim();

        if (!tercero) {
            Utils.toast('Debe indicar el CUIT del tercero (proveedor o cliente)', 'Validación', 'warning');
            Utils.flagInvalid('liqTercero');
            return;
        }

        const codRaw = document.getElementById('liqCodigo')?.value || '';
        const codigo = codRaw !== '' ? parseInt(codRaw, 10) : null;
        const descripcion = (document.getElementById('liqDescripcion')?.value || '').trim();
        const cabezas = parseInt(document.getElementById('liqCabezas')?.value || '0', 10) || 0;
        const cantidad_bruta = parseFloat(document.getElementById('liqCantidadBruta')?.value || '0') || 0;
        const merma_pct = parseFloat(document.getElementById('liqMermaPct')?.value || '0') || 0;
        const unidad = document.getElementById('liqUnidad')?.value || 'KG';
        const precio_unitario = Utils.money(document.getElementById('liqPrecioUnitario')?.value || 0);
        const iva_alicuota = parseFloat(document.getElementById('liqIvaAlicuota')?.value || '10.5') || 0;

        if (!descripcion || cantidad_bruta <= 0 || precio_unitario <= 0) {
            Utils.toast('Complete descripción, cantidad bruta y precio unitario mayores a cero', 'Validación', 'warning');
            return;
        }

        const datos_dominio = rubro === 'granos'
            ? {
                campana: (document.getElementById('liqCampana')?.value || '').trim(),
                especie: document.getElementById('liqEspecie')?.value || 'Soja',
                carta_porte: (document.getElementById('liqCartaPorte')?.value || '').trim(),
                grado: document.getElementById('liqGrado')?.value || 'G2',
                factor: parseFloat(document.getElementById('liqFactor')?.value || '100') || 100
            }
            : {
                dte: (document.getElementById('liqDte')?.value || '').trim(),
                renspa: (document.getElementById('liqRenspa')?.value || '').trim(),
                tropa: (document.getElementById('liqTropa')?.value || '').trim(),
                categoria: document.getElementById('liqCategoria')?.value || 'Novillo'
            };

        const payload = {
            rubro,
            operacion,
            tercero,
            fecha,
            num_comprobante,
            datos_dominio,
            observaciones,
            estado,
            items: [{
                codigo,
                descripcion,
                cabezas,
                cantidad_bruta,
                merma_pct,
                unidad,
                precio_unitario,
                iva_alicuota
            }],
            deducciones: this.deduccionesTemp,
            retenciones: this.retencionesTemp
        };

        try {
            const creada = await API.liquidaciones.create(payload);
            Utils.toast(
                `Liquidación #${creada.id} registrada (${creada.estado}) — Neto: ${Utils.formatCurrency(creada.neto_liquidado)}`,
                'Liquidaciones',
                'success'
            );
            if (rubro === 'hacienda') {
                await this.showHacienda();
            } else {
                await this.showGranos();
            }
        } catch (err) {
            Utils.toast('No se pudo guardar la liquidación: ' + err.message, 'Error', 'error');
        }
    },

    async verDetalle(el) {
        const id = this._extraerValor(el, null, 'id');
        if (!id) return;
        try {
            const liq = await API.liquidaciones.getOne(id);
            const dom = liq.datos_dominio || {};
            const paresDom = Object.entries(dom)
                .filter(([, v]) => v !== null && v !== undefined && v !== '')
                .map(([k, v]) => `<span class="badge bg-light text-dark border me-1">${Utils.escapeHtml(k)}: <strong>${Utils.escapeHtml(String(v))}</strong></span>`)
                .join('');

            const filasItems = (liq.items || []).map(i => `
                <tr>
                    <td>${Utils.escapeHtml(i.descripcion)}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatNumber(i.cantidad_bruta))} ${Utils.escapeHtml(i.unidad)}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatNumber(i.merma_pct))}% (${Utils.escapeHtml(Utils.formatNumber(i.merma_cantidad))})</td>
                    <td class="text-end fw-bold">${Utils.escapeHtml(Utils.formatNumber(i.cantidad_neta))} ${Utils.escapeHtml(i.unidad)}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(i.precio_unitario))}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(i.subtotal))}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(i.iva_importe))} (${Utils.escapeHtml(String(i.iva_alicuota))}%)</td>
                </tr>`).join('');

            const filasDed = (liq.deducciones || []).map(d => `
                <tr>
                    <td>${Utils.escapeHtml(d.concepto)}</td>
                    <td>${Utils.escapeHtml(d.descripcion || '')}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(d.base_imponible))}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(d.iva_importe))}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(d.total))}</td>
                </tr>`).join('');

            const filasRet = (liq.retenciones || []).map(r => `
                <tr>
                    <td>${Utils.escapeHtml(r.tipo)}</td>
                    <td>${Utils.escapeHtml(r.descripcion || '')}</td>
                    <td class="text-end">${Utils.escapeHtml(String(r.alicuota))}%</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(r.importe))}</td>
                </tr>`).join('');

            const body = `
                <div class="mb-2 d-flex justify-content-between align-items-center">
                    <div>
                        <span class="badge bg-dark me-1">${Utils.escapeHtml(liq.rubro.toUpperCase())}</span>
                        <span class="badge bg-${liq.operacion === 'venta' ? 'primary' : 'info'} me-1">${Utils.escapeHtml(liq.operacion)}</span>
                        <span class="badge bg-${liq.estado === 'confirmada' ? 'success' : liq.estado === 'borrador' ? 'warning text-dark' : 'secondary'}">${Utils.escapeHtml(liq.estado)}</span>
                    </div>
                    <div class="small text-muted">
                        Fecha: <strong>${Utils.escapeHtml(Utils.formatDate(liq.fecha))}</strong> ·
                        Tercero: <strong>${Utils.escapeHtml(liq.tercero || '')}</strong>
                        ${liq.codigo_autorizacion ? ` · COE: <strong>${Utils.escapeHtml(liq.codigo_autorizacion)}</strong>` : ''}
                    </div>
                </div>
                ${paresDom ? `<div class="mb-3">${paresDom}</div>` : ''}
                <h6>Renglones Liquidados</h6>
                <table class="table table-sm table-bordered">
                    <thead>
                        <tr><th>Descripción</th><th class="text-end">Bruto</th><th class="text-end">Merma/Desb.</th><th class="text-end">Neto</th><th class="text-end">Precio</th><th class="text-end">Subtotal</th><th class="text-end">IVA</th></tr>
                    </thead>
                    <tbody>${filasItems}</tbody>
                </table>
                ${filasDed ? `
                    <h6>Deducciones</h6>
                    <table class="table table-sm table-bordered">
                        <thead><tr><th>Concepto</th><th>Detalle</th><th class="text-end">Base</th><th class="text-end">IVA</th><th class="text-end">Total</th></tr></thead>
                        <tbody>${filasDed}</tbody>
                    </table>` : ''}
                ${filasRet ? `
                    <h6>Retenciones</h6>
                    <table class="table table-sm table-bordered">
                        <thead><tr><th>Tipo</th><th>Detalle</th><th class="text-end">Alíc.</th><th class="text-end">Importe</th></tr></thead>
                        <tbody>${filasRet}</tbody>
                    </table>` : ''}
                <div class="alert alert-secondary mb-0 d-flex justify-content-between align-items-center">
                    <div>
                        Bruto c/IVA: <strong>${Utils.escapeHtml(Utils.formatCurrency(liq.total_bruto_operacion))}</strong> ·
                        Deducciones: <strong class="text-danger">-${Utils.escapeHtml(Utils.formatCurrency(liq.total_deducciones))}</strong> ·
                        Retenciones: <strong class="text-warning">-${Utils.escapeHtml(Utils.formatCurrency(liq.total_retenciones))}</strong>
                    </div>
                    <div class="fs-5">
                        Neto: <strong>${Utils.escapeHtml(Utils.formatCurrency(liq.neto_liquidado))}</strong>
                    </div>
                </div>
            `;
            Utils.showModal(`Liquidación #${liq.id} ${liq.num_comprobante ? '(' + liq.num_comprobante + ')' : ''}`, body);
        } catch (err) {
            Utils.toast('No se pudo obtener el detalle: ' + err.message, 'Liquidaciones', 'error');
        }
    },

    async confirmarBorrador(el) {
        const id = this._extraerValor(el, null, 'id');
        if (!id) return;
        const ok = await Utils.confirm(
            'Confirmar Liquidación',
            `¿Confirmar la liquidación #${Utils.escapeHtml(String(id))}? Esta acción actualizará el stock físico neto y el saldo en cuenta corriente.`
        );
        if (!ok) return;
        try {
            await API.liquidaciones.confirmar(id);
            Utils.toast(`Liquidación #${id} confirmada correctamente`, 'Liquidaciones', 'success');
            await this._mostrarBandeja(this.rubroActual);
        } catch (err) {
            Utils.toast('Error al confirmar: ' + err.message, 'Liquidaciones', 'error');
        }
    },

    async registrarCoe(el) {
        const id = this._extraerValor(el, null, 'id');
        if (!id) return;
        const coe = await Utils.inputBox('Registrar COE (ARCA)', 'Ingrese los 12 dígitos del Código de Operación Electrónica (COE):', '');
        if (!coe) return;
        try {
            await API.liquidaciones.registrarCoe(id, { coe: coe.trim() });
            Utils.toast(`COE registrado en liquidación #${id}`, 'Liquidaciones', 'success');
            await this._mostrarBandeja(this.rubroActual);
        } catch (err) {
            Utils.toast('Error al registrar COE: ' + err.message, 'Liquidaciones', 'error');
        }
    },

    async anular(el) {
        const id = this._extraerValor(el, null, 'id');
        if (!id) return;
        const ok = await Utils.confirm(
            'Anular Liquidación',
            `¿Está seguro de anular la liquidación #${Utils.escapeHtml(String(id))}? Si estaba confirmada, se revertirán los movimientos de stock y cuenta corriente.`
        );
        if (!ok) return;
        try {
            await API.liquidaciones.anular(id);
            Utils.toast(`Liquidación #${id} anulada`, 'Liquidaciones', 'success');
            await this._mostrarBandeja(this.rubroActual);
        } catch (err) {
            Utils.toast('Error al anular: ' + err.message, 'Liquidaciones', 'error');
        }
    }
};

window.Liquidaciones = Liquidaciones;
