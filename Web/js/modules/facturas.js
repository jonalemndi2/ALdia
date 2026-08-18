/**
 * facturas.js - Módulo de Facturas
 * Equivale a: Facturar.frm, FacsinEntre.frm, Rem_fac.frm, facnorem.frm, not_CD.frm
 *
 * Persistencia: 100% contra la API REST (backend FastAPI). Este módulo ya NO usa
 * db.js / sql.js: aquella base vivía dentro del navegador, nunca se inicializaba
 * y los guardados se perdían en silencio.
 */
const Facturas = {
    /** `nmov` de los renglones que NO provienen de un remito (factura sin entrega).
     *  Los ids de remito arrancan en 1, así que 0 significa "sin remito". Usar el
     *  número de factura como nmov (lo hacía el sistema viejo) colisiona con los
     *  ids de remito y mezcla los renglones de comprobantes distintos. */
    NMOV_SIN_REMITO: 0,

    _items: [],
    _remitos: [],
    _ivaPorCodigo: {},
    _nombrePorCuit: {},
    _factList: [],
    /** Último estado conocido de la integración AFIP (GET /api/afip/estado). */
    _afip: null,

    // ==================== AFIP (factura electrónica) ====================

    /**
     * Estado real de la integración con AFIP. No simula nada: si el backend
     * dice que no está configurado, la interfaz lo dice tal cual.
     * Devuelve null si ni siquiera se pudo consultar (sin sesión, sin red...).
     */
    async _estadoAfip(forzar = false) {
        if (this._afip && !forzar) return this._afip;
        try {
            this._afip = await API.afip.estado();
        } catch (err) {
            console.warn('No se pudo consultar el estado de AFIP:', err.message);
            this._afip = null;
        }
        return this._afip;
    },

    /** ¿Se puede pedir CAE ahora mismo? */
    _afipOperativo(estado) {
        return !!(estado && estado.habilitado && estado.configurado && !estado.error);
    },

    /** Texto honesto para mostrar en pantalla según el estado devuelto. */
    _afipTextoEstado(estado) {
        if (!estado) return 'No se pudo consultar el estado de AFIP desde este equipo.';
        if (!estado.habilitado || !estado.configurado || estado.error) {
            return estado.mensaje || 'AFIP no configurado.';
        }
        return estado.mensaje || `AFIP operativo (${estado.entorno}).`;
    },

    /** Panel de estado de AFIP para las pantallas de facturación. */
    _afipPanelHtml(estado) {
        const ok = this._afipOperativo(estado);
        const homolog = ok && estado.entorno === 'homologacion';
        const clase = ok ? (homolog ? 'alert-warning' : 'alert-success') : 'alert-secondary';
        const icono = ok ? (homolog ? 'bi-exclamation-triangle' : 'bi-shield-check') : 'bi-info-circle';
        let extra = '';
        if (ok && homolog) {
            extra = '<br><strong>Entorno de HOMOLOGACIÓN (pruebas): los CAE que se obtengan NO tienen validez fiscal.</strong>';
        }
        if (estado && Array.isArray(estado.problemas) && estado.problemas.length) {
            extra += '<br>' + estado.problemas.map(p => '• ' + Utils.escapeHtml(String(p))).join('<br>');
        }
        return `<div class="alert ${clase} py-2 px-3 mb-2">
            <i class="bi ${icono}"></i> <strong>AFIP:</strong>
            ${Utils.escapeHtml(this._afipTextoEstado(estado))}${extra}
        </div>`;
    },

    /**
     * Pide el CAE de una factura ya emitida (POST /api/afip/facturas/{n}/solicitar-cae).
     * Devuelve el CAE otorgado por AFIP o null si AFIP lo rechazó / no está
     * configurado. Nunca inventa un número.
     */
    async solicitarCae(factNum, opciones = {}) {
        const num = parseInt(factNum, 10);
        if (!num) { Utils.toast('Indique el número de factura', 'AFIP', 'error'); return null; }

        const overlay = document.getElementById('loadingOverlay');
        if (overlay) overlay.classList.remove('d-none');
        try {
            const r = await API.afip.solicitarCae(num, opciones);
            Utils.toast(r.mensaje || `CAE ${r.cae} otorgado`, 'AFIP', 'success');
            await Utils.confirm('CAE otorgado por AFIP',
                `Factura N° <strong>${Utils.escapeHtml(String(r.facturanumero))}</strong><br>` +
                `CAE: <strong>${Utils.escapeHtml(String(r.cae))}</strong><br>` +
                `Vencimiento del CAE: <strong>${Utils.escapeHtml(Utils.formatDate(r.cae_vencimiento))}</strong><br>` +
                `Comprobante AFIP: <strong>${Utils.escapeHtml(String(r.punto_venta))}-${Utils.escapeHtml(String(r.nro_comprobante_afip))}</strong><br>` +
                `Entorno: <strong>${Utils.escapeHtml(String(r.entorno))}</strong>` +
                (r.observaciones ? `<br>Observaciones de AFIP: ${Utils.escapeHtml(String(r.observaciones))}` : ''));
            return r;
        } catch (err) {
            // Un rechazo de AFIP se muestra como rechazo, con su motivo textual.
            Utils.toast('AFIP: ' + err.message, 'AFIP', 'error');
            console.error('AFIP rechazó o no pudo autorizar la factura ' + num + ':', err.message);
            return null;
        } finally {
            if (overlay) overlay.classList.add('d-none');
        }
    },

    /** Solicitar CAE desde el panel de la pantalla "Remitir Factura". */
    async solicitarCaeDesdePanel() {
        const input = document.getElementById('afipFactNum');
        if (!input) return;
        const num = parseInt(input.value, 10);
        if (!num) { Utils.toast('Ingrese el número de factura a autorizar', 'AFIP', 'error'); return; }
        const tipoSel = document.getElementById('afipTipoCbte');
        const opciones = {};
        if (tipoSel && tipoSel.value) opciones.tipo_comprobante = parseInt(tipoSel.value, 10);
        const r = await this.solicitarCae(num, opciones);
        if (r) await this.remitirFactura();
    },

    // ==================== HELPERS ====================

    /** Mapa cuit -> nombre, para poder mostrar el nombre del cliente
     *  (la API devuelve sólo el CUIT en `cliente`). */
    async _cargarNombresClientes() {
        try {
            const clientes = await API.clientes.getAll();
            this._nombrePorCuit = {};
            clientes.forEach(c => { this._nombrePorCuit[c.cuit] = c.nombre; });
        } catch (err) {
            console.error('No se pudieron cargar los nombres de clientes:', err);
            this._nombrePorCuit = {};
        }
        return this._nombrePorCuit;
    },

    _nombreCliente(cuit) {
        return this._nombrePorCuit[cuit] || cuit || '';
    },

    /** Mapa codigo -> alícuota de IVA. Los renglones de `ventas` no guardan el
     *  IVA, hay que resolverlo contra el stock para no facturar todo al 21%. */
    async _cargarIvaProductos() {
        try {
            const stock = await API.stock.getAll();
            this._ivaPorCodigo = {};
            stock.forEach(p => { this._ivaPorCodigo[p.codigo] = p.iva; });
        } catch (err) {
            console.error('No se pudo cargar el IVA de los productos:', err);
            this._ivaPorCodigo = {};
        }
        return this._ivaPorCodigo;
    },

    _ivaDe(item) {
        const v = item.iva !== undefined && item.iva !== null
            ? item.iva
            : this._ivaPorCodigo[item.codigo];
        return (v === undefined || v === null) ? 21 : v;
    },

    /**
     * Renglones (tabla `ventas`) asociados a una factura.
     *
     * LIMITACIÓN DE LA API: no existe `GET /api/facturas/{num}/ventas`. Las líneas
     * sólo se pueden pedir por `nmov` (`GET /api/remitos/{nmov}/ventas`). Se prueba
     * primero con nmov = 0 (caso "factura sin entrega", que no tiene remito) y,
     * si no aparece nada, se recorren los remitos.
     */
    async _ventasDeFactura(factNum) {
        // El servidor devuelve los renglones de la factura en una sola consulta.
        // Antes había que recorrer todos los remitos y filtrar (N+1 peticiones,
        // con tope de resultados), lo que se degradaba al crecer la base.
        try {
            return await API.facturas.getVentas(factNum);
        } catch (err) {
            console.error('No se pudieron leer los renglones de la factura ' + factNum + ':', err.message);
            Utils.toast('No se pudo leer el detalle de la factura: ' + err.message, 'Facturas', 'error');
            return [];
        }
    },

    /** Todos los renglones ya facturados (idfactura > 0). Misma limitación que
     *  `_ventasDeFactura`: hace falta un endpoint de ventas para hacerlo bien. */
    async _ventasFacturadas(limite = 100) {
        console.warn(
            'Falta un endpoint de renglones facturados (p.ej. GET /api/ventas?idfactura=>0). ' +
            'Se reconstruye recorriendo remitos y facturas recientes.'
        );
        const [remitos, facturas] = await Promise.all([
            API.remitos.getAll().catch(() => []),
            API.facturas.getAll().catch(() => [])
        ]);

        const nmovs = new Set();
        remitos.slice(0, limite).forEach(r => nmovs.add(r.id));
        // Las "facturas sin entrega" no tienen remito: sus renglones van con nmov = 0.
        if (facturas.length) nmovs.add(Facturas.NMOV_SIN_REMITO);

        const lotes = await Promise.all(
            Array.from(nmovs).map(n => API.remitos.getVentas(n).catch(() => []))
        );

        const vistos = new Set();
        const out = [];
        lotes.forEach(lineas => (lineas || []).forEach(v => {
            if (Number(v.idfactura) > 0 && !vistos.has(v.id)) {
                vistos.add(v.id);
                out.push(v);
            }
        }));
        out.sort((a, b) => Number(b.idfactura) - Number(a.idfactura));
        return out;
    },

    // ==================== EMITIR FACTURA (Facturar.frm) ====================

    /** Emitir Factura - con selección de remitos pendientes */
    async emitirFactura() {
        this._items = [];
        try {
            // GET /remitos/nofacturados devuelve RENGLONES (tabla ventas) con
            // idfactura = 0, no cabeceras de remito. Se agrupan por nmov para
            // presentar un remito por fila.
            const [lineas] = await Promise.all([
                API.remitos.getNoFacturados(),
                this._cargarNombresClientes(),
                this._cargarIvaProductos()
            ]);

            const grupos = new Map();
            (lineas || []).forEach(l => {
                if (l.nmov === null || l.nmov === undefined) return;
                if (!grupos.has(l.nmov)) {
                    grupos.set(l.nmov, {
                        nmov: l.nmov, cliente: l.cliente, fecha: l.fecha, total: 0, lineas: []
                    });
                }
                const g = grupos.get(l.nmov);
                g.total += (l.cantidad || 0) * (l.precio || 0);
                g.lineas.push(l);
            });
            const remitosPendientes = Array.from(grupos.values())
                .sort((a, b) => Number(b.nmov) - Number(a.nmov));

            let remitosHtml = '';
            remitosPendientes.forEach((r, i) => {
                remitosHtml += `<tr data-action="Facturas.selectRemito" data-idx="${i}" style="cursor:pointer">
                    <td><input type="checkbox" class="form-check-input remito-check" data-idx="${i}"></td>
                    <td>${Utils.escapeHtml(String(r.nmov))}</td><td>${Utils.escapeHtml(this._nombreCliente(r.cliente))}</td>
                    <td>${Utils.escapeHtml(Utils.formatDate(r.fecha))}</td><td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(r.total))}</td>
                </tr>`;
            });
            if (!remitosHtml) {
                remitosHtml = '<tr><td colspan="5" class="text-muted text-center">No hay remitos pendientes de facturación</td></tr>';
            }

            const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#0d47a1,#1565c0)">
                <h4><i class="bi bi-file-earmark-ruled"></i> Emitir Factura</h4>
            </div>
            <div class="row">
                <div class="col-md-5">
                    <div class="form-card">
                        <h6>Remitos Pendientes de Facturación</h6>
                        <div class="grid-container" style="max-height:300px;">
                            <table class="table table-sm table-aldia" id="remitosTable">
                                <thead><tr><th></th><th>N° Remito</th><th>Cliente</th><th>Fecha</th><th>Total</th></tr></thead>
                                <tbody>${remitosHtml}</tbody>
                            </table>
                        </div>
                        <button class="btn btn-sm btn-primary mt-2" data-action="Facturas.cargarRemitosSeleccionados">
                            <i class="bi bi-arrow-right"></i> Cargar Selección
                        </button>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="form-card">
                        <div class="row mb-2">
                            <div class="col-4">
                                <label class="form-label-sm">Fecha</label>
                                <input type="date" class="form-control form-control-sm" id="factFecha" value="${Utils.today()}">
                            </div>
                            <div class="col-4">
                                <label class="form-label-sm">Cliente</label>
                                <input type="text" class="form-control form-control-sm" id="factCliente" readonly>
                            </div>
                            <div class="col-4">
                                <label class="form-label-sm">CUIT</label>
                                <input type="text" class="form-control form-control-sm" id="factCuit" readonly>
                            </div>
                        </div>
                        <div id="factGrid"></div>
                        <div class="row mt-2">
                            <div class="col-7">
                                <table class="table table-sm mb-0">
                                    <tr><td>Subtotal:</td><td class="text-end" id="factSubtotal">$0.00</td></tr>
                                    <tr><td>IVA:</td><td class="text-end" id="factIVA">$0.00</td></tr>
                                    <tr class="fw-bold"><td>TOTAL:</td><td class="text-end" id="factTotal">$0.00</td></tr>
                                </table>
                            </div>
                            <div class="col-5">
                                <label class="form-label-sm">Tipo Emisión</label>
                                <select class="form-select mb-2" id="factTipoEmision">
                                    <option value="local">Factura Local</option>
                                    <option value="afip">Electrónica (AFIP)</option>
                                </select>
                                <button class="btn btn-primary w-100" data-action="Facturas.guardarFactura">
                                    <i class="bi bi-check-circle"></i> Facturar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
            Utils.showView(html);
            this._remitos = remitosPendientes;
        } catch (err) {
            Utils.toast('Error al cargar remitos: ' + err.message, 'Error', 'error');
        }
    },

    selectRemito(idx, row, e) {
        const cb = row.querySelector('.remito-check');
        if (!cb) return;
        // Si el click fue sobre el propio checkbox, el navegador ya cambió su
        // estado: volver a togglearlo acá lo dejaba siempre como estaba, así que
        // marcar un remito clickeando la casilla no funcionaba.
        if (e && e.target === cb) return;
        cb.checked = !cb.checked;
    },

    cargarRemitosSeleccionados() {
        this._items = [];
        const checks = document.querySelectorAll('.remito-check:checked');
        let clienteCuit = null;

        for (const cb of checks) {
            const idx = parseInt(cb.dataset.idx);
            const rem = this._remitos[idx];
            if (!rem) continue;

            if (clienteCuit && clienteCuit !== rem.cliente) {
                Utils.toast('Los remitos seleccionados deben ser del mismo cliente', 'Error', 'error');
                return;
            }
            clienteCuit = rem.cliente;

            // Los renglones ya vinieron en GET /remitos/nofacturados: no hace
            // falta volver a pedirlos.
            rem.lineas.forEach(item => {
                this._items.push({
                    id: item.id, codigo: item.codigo, producto: item.producto,
                    cantidad: item.cantidad, precio: item.precio, unidad: item.unidad,
                    nmov: item.nmov, iva: this._ivaPorCodigo[item.codigo]
                });
            });
        }

        if (clienteCuit) {
            document.getElementById('factCliente').value = this._nombreCliente(clienteCuit);
            document.getElementById('factCuit').value = clienteCuit;
        }

        this._renderFactGrid();
    },

    _renderFactGrid() {
        let subtotal = 0, ivaTotal = 0;
        let html = '<table class="table table-sm flex-grid"><thead><tr>' +
            '<th>Cód.</th><th>Producto</th><th>Cant.</th><th>Unidad</th><th>Precio</th><th>Subtotal</th>' +
            '</tr></thead><tbody>';

        this._items.forEach(item => {
            const st = item.cantidad * item.precio;
            subtotal += st;
            ivaTotal += st * (this._ivaDe(item) / 100);
            html += `<tr><td>${Utils.escapeHtml(String(item.codigo))}</td><td>${Utils.escapeHtml(String(item.producto))}</td><td>${Utils.escapeHtml(String(item.cantidad))}</td>
                <td>${Utils.escapeHtml(String(item.unidad || ''))}</td><td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.precio))}</td>
                <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(st))}</td></tr>`;
        });
        html += '</tbody></table>';

        document.getElementById('factGrid').innerHTML = html;
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();

        document.getElementById('factSubtotal').textContent = Utils.formatCurrency(subtotal);
        document.getElementById('factIVA').textContent = Utils.formatCurrency(ivaTotal);
        document.getElementById('factTotal').textContent = Utils.formatCurrency(subtotal + ivaTotal);
    },

    async guardarFactura() {
        const cuit = document.getElementById('factCuit').value;
        if (!cuit) { Utils.toast('No hay cliente seleccionado', 'Error', 'error'); return; }
        if (this._items.length === 0) { Utils.toast('No hay ítems para facturar', 'Error', 'error'); return; }

        const fecha = document.getElementById('factFecha').value;
        let subtotal = 0, ivaTotal = 0;
        this._items.forEach(item => {
            const st = item.cantidad * item.precio;
            subtotal += st;
            ivaTotal += st * (this._ivaDe(item) / 100);
        });
        // Redondeo unico a 2 decimales: lo que se manda es lo que se mostro.
        subtotal = Utils.money(subtotal);
        ivaTotal = Utils.money(ivaTotal);
        const total = Utils.money(subtotal + ivaTotal);

        const tipoEmision = document.getElementById('factTipoEmision').value;

        // Emisión electrónica: se consulta el estado REAL de la integración
        // (certificado, entorno y servidores de AFIP) antes de prometer nada.
        let pedirCae = false;
        if (tipoEmision === 'afip') {
            const estado = await this._estadoAfip(true);
            if (this._afipOperativo(estado)) {
                pedirCae = true;
                if (estado.entorno === 'homologacion') {
                    const seguir = await Utils.confirm('AFIP - Homologación',
                        'La integración está apuntando al entorno de <strong>HOMOLOGACIÓN</strong> (pruebas).<br>' +
                        'El CAE que devuelva AFIP <strong>no tiene validez fiscal</strong>.<br><br>¿Continuar igual?');
                    if (!seguir) return;
                }
            } else {
                const seguir = await Utils.confirm('AFIP no configurado',
                    `${Utils.escapeHtml(this._afipTextoEstado(estado))}<br><br>` +
                    'La factura se puede registrar igual en el sistema, pero <strong>quedará sin CAE</strong> ' +
                    'y no es una factura electrónica válida ante AFIP.<br><br>¿Registrarla igual?');
                if (!seguir) return;
                console.warn('AFIP no configurado: la factura se registra localmente, sin CAE.');
            }
        }

        try {
            // El backend, en una sola transacción: crea la factura, marca los
            // renglones de `items[]` como facturados y suma el total al saldo
            // del cliente. NO hay que replicar nada de eso acá.
            const result = await API.facturas.create({
                cuit, fecha, subtotal, ivaTotal, total, tipoEmision,
                items: this._items.map(item => ({ id: item.id, codigo: item.codigo }))
            });

            Utils.toast(`Factura N° ${result.facturanumero} emitida`, 'Facturas', 'success');

            // La factura ya está registrada. Recién ahora se le pide el CAE a
            // AFIP: si AFIP rechaza, la venta no se pierde y el CAE se puede
            // volver a pedir desde "Remitir Factura".
            if (pedirCae) await this.solicitarCae(result.facturanumero);

            const ok = await Utils.confirm('Factura Generada',
                `Factura N° <strong>${Utils.escapeHtml(String(result.facturanumero))}</strong><br>Total: <strong>${Utils.formatCurrency(total)}</strong><br>¿Imprimir?`);
            if (ok) await this.imprimirFactura(result.facturanumero);

            await this.emitirFactura();
        } catch (err) {
            Utils.toast('Error al guardar factura: ' + err.message, 'Error', 'error');
        }
    },

    // ==================== FACTURA SIN ENTREGA (FacsinEntre.frm) ====================

    /** Factura sin Entrega - venta directa sin remito previo */
    facturaSinEntrega() {
        this._items = [];
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#4a148c,#7b1fa2)">
                <h4><i class="bi bi-file-earmark-plus"></i> Factura sin Entrega</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-5">
                    <div class="form-card">
                        <label class="form-label-sm">Cliente</label>
                        <div class="position-relative">
                            <input type="text" class="form-control" id="fseCliente" placeholder="Buscar cliente...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-6">
                                <label class="form-label-sm">Fecha</label>
                                <input type="date" class="form-control form-control-sm" id="fseFecha" value="${Utils.today()}">
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="form-card">
                        <label class="form-label-sm">Producto</label>
                        <div class="position-relative">
                            <input type="text" class="form-control form-control-sm" id="fseProd" placeholder="Buscar producto...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-3">
                                <label class="form-label-sm">Cantidad</label>
                                <input type="number" class="form-control form-control-sm" id="fseCant" value="1">
                            </div>
                            <div class="col-3">
                                <label class="form-label-sm">Precio</label>
                                <input type="number" class="form-control form-control-sm" id="fsePrecio" step="0.01">
                            </div>
                                <div class="col-3 d-flex align-items-end">
                                <button class="btn btn-sm btn-primary w-100" data-action="Facturas.addFseItem">
                                    <i class="bi bi-plus"></i> Agregar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="fseGrid"></div>
            <div class="row mt-3">
                <div class="col-md-4 offset-md-8">
                    <table class="table table-sm">
                        <tr><td>Subtotal:</td><td class="text-end" id="fseSubtotal">$0.00</td></tr>
                        <tr><td>IVA:</td><td class="text-end" id="fseIVA">$0.00</td></tr>
                        <tr class="fw-bold"><td>TOTAL:</td><td class="text-end" id="fseTotal">$0.00</td></tr>
                    </table>
                    <button class="btn btn-primary w-100" data-action="Facturas.guardarFse">
                        <i class="bi bi-check-circle"></i> Facturar
                    </button>
                </div>
            </div>
        `;
        Utils.showView(html);
        Utils.searchEntity('clientes', 'fseCliente');
        Utils.searchProduct('fseProd', (p) => {
            document.getElementById('fsePrecio').value = p.preven;
        });
    },

    async addFseItem() {
        const prodInput = document.getElementById('fseProd');
        const codigo = prodInput.dataset.codigo;
        if (!codigo) { Utils.toast('Seleccione un producto', 'Error', 'error'); return; }

        const cant = parseFloat(document.getElementById('fseCant').value) || 0;
        const precio = parseFloat(document.getElementById('fsePrecio').value) || 0;
        if (cant <= 0) { Utils.toast('La cantidad debe ser mayor a cero', 'Error', 'error'); return; }

        try {
            const prod = await API.stock.getById(codigo);

            // La factura sin entrega saca mercadería del depósito: si no hay
            // stock la venta no puede registrarse.
            if (cant > prod.cantidad) {
                Utils.toast(`Stock insuficiente. Disponible: ${prod.cantidad} ${prod.unidad}`, 'Stock', 'error');
                return;
            }

            this._items.push({
                codigo: prod.codigo, producto: prod.producto, cantidad: cant,
                precio: precio, unidad: prod.unidad, iva: prod.iva,
                subtotal: cant * precio, ivaAmt: cant * precio * (prod.iva / 100)
            });

            prodInput.value = '';
            prodInput.dataset.codigo = '';
            document.getElementById('fseCant').value = '1';
            document.getElementById('fsePrecio').value = '';
            this._renderFseGrid();
        } catch (err) {
            Utils.toast('Error al obtener producto: ' + err.message, 'Error', 'error');
        }
    },

    _renderFseGrid() {
        let subtotal = 0, ivaTotal = 0;
        let html = '<table class="table table-sm flex-grid"><thead><tr>' +
            '<th>Cód.</th><th>Producto</th><th>Cant.</th><th>Precio</th><th>IVA</th><th>Subtotal</th><th></th>' +
            '</tr></thead><tbody>';

        this._items.forEach((item, i) => {
            subtotal += item.subtotal;
            ivaTotal += item.ivaAmt;
            html += `<tr>
                <td>${Utils.escapeHtml(String(item.codigo))}</td><td>${Utils.escapeHtml(String(item.producto))}</td><td>${Utils.escapeHtml(String(item.cantidad))}</td>
                <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.precio))}</td>
                <td>${Utils.escapeHtml(String(item.iva))}%</td><td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.subtotal))}</td>
                <td><button class="btn btn-sm btn-outline-danger" data-action="Facturas.removeFseItem" data-idx="${i}"><i class="bi bi-trash"></i></button></td>
            </tr>`;
        });
        html += '</tbody></table>';

        document.getElementById('fseGrid').innerHTML = html;
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
        document.getElementById('fseSubtotal').textContent = Utils.formatCurrency(subtotal);
        document.getElementById('fseIVA').textContent = Utils.formatCurrency(ivaTotal);
        document.getElementById('fseTotal').textContent = Utils.formatCurrency(subtotal + ivaTotal);
    },

    removeFseItem(idx) {
        this._items.splice(idx, 1);
        this._renderFseGrid();
    },

    async guardarFse() {
        const cliInput = document.getElementById('fseCliente');
        const cuit = cliInput.dataset.cuit;
        if (!cuit) { Utils.toast('Seleccione un cliente', 'Error', 'error'); return; }
        if (this._items.length === 0) { Utils.toast('Agregue productos', 'Error', 'error'); return; }

        const fecha = document.getElementById('fseFecha').value;
        let subtotal = 0, ivaTotal = 0;
        this._items.forEach(i => { subtotal += i.subtotal; ivaTotal += i.ivaAmt; });
        subtotal = Utils.money(subtotal);
        ivaTotal = Utils.money(ivaTotal);
        const total = Utils.money(subtotal + ivaTotal);

        // Una sola petición: el servidor numera la factura, crea los renglones
        // (con nmov = 0 por no venir de un remito), descuenta el stock y suma el
        // total al saldo del cliente, todo en la misma transacción. Si el stock
        // no alcanza, rechaza la operación completa y no queda nada a medias.
        let factura;
        try {
            factura = await API.facturas.create({
                cuit, fecha, subtotal, ivaTotal, total, tipoEmision: 'local',
                items: this._items.map(item => ({
                    codigo: Number(item.codigo),
                    producto: item.producto,
                    cantidad: item.cantidad,
                    precio: item.precio,
                    unidad: item.unidad || 'UN'
                }))
            });
        } catch (err) {
            Utils.toast('Error al guardar factura: ' + err.message, 'Error', 'error');
            return;
        }
        const factNum = factura.facturanumero;

        Utils.toast(`Factura N° ${factNum} emitida por ${Utils.formatCurrency(total)}`, 'Facturas', 'success');
        this.facturaSinEntrega();
    },

    // ==================== REMITIR FACTURA (Rem_fac.frm) ====================

    async remitirFactura() {
        try {
            const [facturas, estadoAfip] = await Promise.all([
                API.facturas.getAll(),
                this._estadoAfip(true),
                this._cargarNombresClientes()
            ]);
            // La API devuelve `cliente` = CUIT; el nombre se resuelve contra /clientes/.
            // El estado fiscal sale de lo que respondió AFIP y quedó guardado en
            // la factura: sin CAE la factura NO está autorizada, y así se muestra.
            const data = facturas.slice(0, 50).map(f => Object.assign({}, f, {
                clienteNombre: this._nombreCliente(f.cliente),
                caeTexto: f.cae || '—',
                estadoAfip: f.cae
                    ? 'Autorizada'
                    : (f.resultado === 'R' ? 'Rechazada por AFIP' : 'Sin CAE')
            }));

            const columns = [
                { field: 'facturanumero', label: 'N° Factura' },
                { field: 'clienteNombre', label: 'Cliente' },
                { field: 'cliente', label: 'CUIT' },
                { field: 'fecha', label: 'Fecha', format: 'date' },
                { field: 'subtotal', label: 'Subtotal', format: 'currency' },
                { field: 'iva', label: 'IVA', format: 'currency' },
                { field: 'total', label: 'Total', format: 'currency' },
                { field: 'caeTexto', label: 'CAE' },
                { field: 'estadoAfip', label: 'Estado AFIP' }
            ];

            const operativo = this._afipOperativo(estadoAfip);
            const html = `
                <div class="section-header">
                    <h4><i class="bi bi-file-earmark-medical"></i> Remitir Factura</h4>
                </div>
                ${this._afipPanelHtml(estadoAfip)}
                <div class="form-card mb-2">
                    <div class="row g-2 align-items-end">
                        <div class="col-auto">
                            <label class="form-label-sm">N° de factura</label>
                            <input type="number" class="form-control form-control-sm" id="afipFactNum" style="width:140px">
                        </div>
                        <div class="col-auto">
                            <label class="form-label-sm">Tipo de comprobante</label>
                            <select class="form-select form-select-sm" id="afipTipoCbte" style="width:220px">
                                <option value="">(el configurado por defecto)</option>
                                <option value="1">1 - Factura A</option>
                                <option value="6">6 - Factura B</option>
                                <option value="11">11 - Factura C</option>
                                <option value="3">3 - Nota de Crédito A</option>
                                <option value="8">8 - Nota de Crédito B</option>
                                <option value="13">13 - Nota de Crédito C</option>
                            </select>
                        </div>
                        <div class="col-auto">
                            <button class="btn btn-sm btn-primary" data-action="Facturas.solicitarCaeDesdePanel" ${operativo ? '' : 'disabled'}>
                                <i class="bi bi-patch-check"></i> Solicitar CAE a AFIP
                            </button>
                        </div>
                    </div>
                    ${operativo ? '' : '<div class="form-text">Botón deshabilitado: AFIP no está configurado en este equipo.</div>'}
                </div>
                ${Utils.buildTable(columns, data, { id: 'factList', onDblClick: 'Facturas.verDetalle' })}
                <div class="mt-2 text-muted"><small>Doble click para ver detalle e imprimir</small></div>
            `;
            Utils.showView(html);
            this._factList = data;
        } catch (err) {
            Utils.toast('Error al cargar facturas: ' + err.message, 'Error', 'error');
        }
    },

    async verDetalle(idx) {
        const fact = this._factList[idx];
        if (fact) await this.imprimirFactura(fact.facturanumero);
    },

    // ==================== NOTAS DE DÉBITO / CRÉDITO (not_CD.frm) ====================

    notaDebitoCreditoCliente() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#bf360c,#e64a19)">
                <h4><i class="bi bi-file-earmark-diff"></i> Nota de Débito / Crédito a Cliente</h4>
            </div>
            <div class="form-card" style="max-width:600px;">
                <div class="mb-3">
                    <div class="btn-group w-100" role="group">
                        <input type="radio" class="btn-check" name="ndcTipo" id="ndcCredito" value="credito" checked>
                        <label class="btn btn-outline-success" for="ndcCredito">Nota de Crédito</label>
                        <input type="radio" class="btn-check" name="ndcTipo" id="ndcDebito" value="debito">
                        <label class="btn btn-outline-danger" for="ndcDebito">Nota de Débito</label>
                    </div>
                </div>
                <div class="mb-3 position-relative">
                    <label class="form-label-sm">Cliente</label>
                    <input type="text" class="form-control" id="ndcCliente" placeholder="Buscar cliente...">
                </div>
                <div class="row mb-3">
                    <div class="col-6">
                        <label class="form-label-sm">Monto</label>
                        <input type="number" class="form-control" id="ndcMonto" step="0.01">
                    </div>
                    <div class="col-6">
                        <label class="form-label-sm">IVA %</label>
                        <input type="number" class="form-control" id="ndcIVA" value="21">
                    </div>
                </div>
                <div class="mb-3">
                    <label class="form-label-sm">Descripción</label>
                    <textarea class="form-control" id="ndcDesc" rows="2"></textarea>
                </div>
                <button class="btn btn-primary w-100" data-action="Facturas.guardarNDC">
                    <i class="bi bi-check-circle"></i> Registrar
                </button>
            </div>
        `;
        Utils.showView(html);
        Utils.searchEntity('clientes', 'ndcCliente');
    },

    async guardarNDC() {
        const cuit = document.getElementById('ndcCliente').dataset.cuit;
        if (!cuit) { Utils.toast('Seleccione un cliente', 'Error', 'error'); return; }

        const tipo = document.querySelector('input[name="ndcTipo"]:checked').value;
        const monto = parseFloat(document.getElementById('ndcMonto').value) || 0;
        const ivaPct = parseFloat(document.getElementById('ndcIVA').value) || 0;
        const desc = document.getElementById('ndcDesc').value;
        const fecha = Utils.today();

        if (monto <= 0) { Utils.toast('Ingrese un monto mayor a cero', 'Error', 'error'); return; }

        const ivaAmt = Utils.money(monto * (ivaPct / 100));
        const total = Utils.money(monto + ivaAmt);
        const signo = tipo === 'credito' ? -1 : 1;

        // La API no expone las tablas nncv/nndv: la nota se registra como
        // comprobante en `facturas` (mismo criterio que el sistema original),
        // con importes negativos si es de crédito. El backend ajusta el saldo
        // del cliente con el signo del total, así que NO hay que tocarlo acá.
        console.warn('No existen endpoints para nncv/nndv: la descripción de la nota ' +
            'no se persiste y el comprobante se numera como una factura más.');

        try {
            const result = await API.facturas.create({
                cuit, fecha,
                subtotal: signo * monto,
                ivaTotal: signo * ivaAmt,
                total: signo * total,
                tipoEmision: tipo === 'credito' ? 'nota_credito' : 'nota_debito',
                items: []
            });

            const etiqueta = tipo === 'credito' ? 'Nota de Crédito' : 'Nota de Débito';
            Utils.toast(
                `${etiqueta} N° ${result.facturanumero} registrada por ${Utils.formatCurrency(total)}. ` +
                `Atención: la descripción no se guarda (falta el endpoint de notas).`,
                etiqueta, 'success');

            document.getElementById('ndcMonto').value = '';
            document.getElementById('ndcDesc').value = '';
            if (desc) console.warn('Descripción no persistida:', desc);
        } catch (err) {
            Utils.toast('Error al registrar la nota: ' + err.message, 'Error', 'error');
        }
    },

    // ==================== FACTURAS NO REMITIDAS (facnorem.frm) ====================

    async facturasNoRemitidas() {
        try {
            const [ventas] = await Promise.all([
                this._ventasFacturadas(),
                this._cargarNombresClientes()
            ]);
            const data = ventas.map(v => Object.assign({}, v, {
                clienteNombre: this._nombreCliente(v.cliente)
            }));

            const columns = [
                { field: 'idfactura', label: 'N° Factura' },
                { field: 'codigo', label: 'Código' },
                { field: 'producto', label: 'Producto' },
                { field: 'cantidad', label: 'Cantidad', format: 'number' },
                { field: 'precio', label: 'Precio', format: 'currency' },
                { field: 'clienteNombre', label: 'Cliente' },
                { field: 'fecha', label: 'Fecha', format: 'date' }
            ];

            const html = `
                <div class="section-header">
                    <h4><i class="bi bi-file-earmark-x"></i> Facturas no Remitidas</h4>
                </div>
                ${Utils.buildTable(columns, data)}
            `;
            Utils.showView(html);
        } catch (err) {
            Utils.toast('Error al cargar el listado: ' + err.message, 'Error', 'error');
        }
    },

    // ==================== IMPRESIÓN ====================

    async imprimirFactura(factNum) {
        try {
            const fact = await API.facturas.getById(factNum);
            if (!fact) return;

            const items = await this._ventasDeFactura(factNum);
            let cliente = null;
            try {
                cliente = await API.clientes.getById(fact.cliente);
            } catch (err) {
                console.warn('No se pudo resolver el cliente de la factura:', err.message);
            }

            let itemsHtml = '';
            items.forEach(i => {
                itemsHtml += `<tr><td>${Utils.escapeHtml(String(i.codigo))}</td><td>${Utils.escapeHtml(String(i.producto))}</td><td>${Utils.escapeHtml(String(i.cantidad))}</td>
                    <td>${Utils.escapeHtml(String(i.unidad || ''))}</td><td style="text-align:right">${Utils.escapeHtml(Utils.formatCurrency(i.precio))}</td>
                    <td style="text-align:right">${Utils.escapeHtml(Utils.formatCurrency(i.cantidad * i.precio))}</td></tr>`;
            });

            // ── Bloque fiscal ────────────────────────────────────────────
            // El CAE y su vencimiento se imprimen SOLO si AFIP los otorgó. Si no
            // hay CAE, el comprobante se marca como no válido como factura
            // electrónica: es lo que exige AFIP y es la verdad del documento.
            const TIPOS_CBTE = {
                1: 'FACTURA A', 2: 'NOTA DE DÉBITO A', 3: 'NOTA DE CRÉDITO A',
                6: 'FACTURA B', 7: 'NOTA DE DÉBITO B', 8: 'NOTA DE CRÉDITO B',
                11: 'FACTURA C', 12: 'NOTA DE DÉBITO C', 13: 'NOTA DE CRÉDITO C'
            };
            const encabezado = fact.cae
                ? `${TIPOS_CBTE[fact.tipo_comprobante] || 'COMPROBANTE'} N° ` +
                  `${Utils.escapeHtml(String(fact.punto_venta || 0).padStart(4, '0'))}-` +
                  `${Utils.escapeHtml(String(fact.nro_comprobante_afip || 0).padStart(8, '0'))}`
                : `FACTURA N° ${Utils.escapeHtml(String(fact.facturanumero))}`;

            let bloqueAfip = '';
            if (fact.cae) {
                // QR fiscal (RG 4892): obligatorio en el impreso desde 2021. Lo
                // genera el servidor a partir del CAE; si falla, se dice, porque
                // sin QR el comprobante impreso no cumple la normativa.
                let qrHtml = `
                    <div style="font-size:11px;color:#b00;max-width:180px;">
                        No se pudo generar el código QR obligatorio (RG 4892).
                        Este impreso no cumple la normativa.
                    </div>`;
                try {
                    const qr = await API.afip.qr(factNum);
                    if (qr && qr.svg) {
                        qrHtml = `<div style="width:160px;height:160px;">${qr.svg}</div>`;
                    }
                } catch (err) {
                    console.error('No se pudo obtener el QR fiscal de la factura ' + factNum + ':', err.message);
                }

                bloqueAfip = `
                    <div style="border:2px solid #333; padding:10px; margin-top:20px; display:flex; justify-content:space-between; align-items:center; gap:16px;">
                        ${qrHtml}
                        <div style="text-align:right;">
                            <div><strong>CAE N°:</strong> ${Utils.escapeHtml(String(fact.cae))}</div>
                            <div><strong>Fecha de Vto. de CAE:</strong> ${Utils.escapeHtml(Utils.formatDate(fact.cae_vencimiento))}</div>
                            <div style="font-size:11px;color:#555;">Comprobante autorizado por AFIP — Interno N° ${Utils.escapeHtml(String(fact.facturanumero))}</div>
                        </div>
                    </div>`;
            } else if (fact.resultado === 'R') {
                bloqueAfip = `
                    <div style="border:2px solid #b00; color:#b00; padding:10px; margin-top:20px;">
                        <strong>AFIP RECHAZÓ este comprobante: no tiene CAE y no es válido como factura electrónica.</strong>
                        <div style="font-size:11px;">${Utils.escapeHtml(String(fact.afip_observaciones || ''))}</div>
                    </div>`;
            } else {
                bloqueAfip = `
                    <div style="border:1px dashed #888; color:#555; padding:8px; margin-top:20px; font-size:12px;">
                        Documento no fiscal: sin CAE de AFIP. No válido como factura electrónica.
                    </div>`;
            }

            const printHtml = `
                <div style="font-family:Arial; padding:20px; max-width:800px; margin:auto;">
                    <h2 style="text-align:center;">${encabezado}</h2>
                    <hr>
                    <p><strong>Cliente:</strong> ${Utils.escapeHtml(String(cliente ? cliente.nombre : fact.cliente))}</p>
                    <p><strong>CUIT:</strong> ${Utils.escapeHtml(String(fact.cliente || ''))}</p>
                    <p><strong>Fecha:</strong> ${Utils.escapeHtml(Utils.formatDate(fact.fecha))}</p>
                    <table style="width:100%; border-collapse:collapse; margin-top:10px;">
                        <thead><tr style="background:#333;color:white;">
                            <th style="padding:6px;border:1px solid #333;">Cód.</th>
                            <th style="padding:6px;border:1px solid #333;">Producto</th>
                            <th style="padding:6px;border:1px solid #333;">Cant.</th>
                            <th style="padding:6px;border:1px solid #333;">Unidad</th>
                            <th style="padding:6px;border:1px solid #333;">Precio</th>
                            <th style="padding:6px;border:1px solid #333;">Subtotal</th>
                        </tr></thead>
                        <tbody>${itemsHtml}</tbody>
                    </table>
                    <div style="text-align:right; margin-top:20px;">
                        <p>Subtotal: ${Utils.escapeHtml(Utils.formatCurrency(fact.subtotal))}</p>
                        <p>IVA: ${Utils.escapeHtml(Utils.formatCurrency(fact.iva))}</p>
                        <h3>TOTAL: ${Utils.escapeHtml(Utils.formatCurrency(fact.total))}</h3>
                    </div>
                    ${bloqueAfip}
                </div>
            `;

            const win = window.open('', '_blank', 'width=850,height=600');
            if (!win) {
                Utils.toast('El navegador bloqueó la ventana de impresión. Habilite los pop-ups para imprimir.', 'Facturas', 'error');
                return;
            }
            win.document.write(printHtml);
            win.document.close();
            win.print();
        } catch (err) {
            Utils.toast('Error al imprimir factura: ' + err.message, 'Error', 'error');
        }
    }
};
// Exponer Facturas
window.Facturas = Facturas;
