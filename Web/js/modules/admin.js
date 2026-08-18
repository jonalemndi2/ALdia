/**
 * admin.js - Módulo de Administración
 * Equivale a: Eliminarmov.frm, resumen.frm, morosos
 */
const Admin = {
    showEliminarMov() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#b71c1c,#d32f2f)">
                <h4><i class="bi bi-trash"></i> Eliminar Movimientos</h4>
            </div>
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle"></i> 
                <strong>Precaución:</strong> Esta operación revierte el movimiento seleccionado y restaura saldos y stock.
            </div>
            <div class="row mb-3">
                <div class="col-md-3">
                    <div class="form-card">
                        <label class="form-label-sm">Tipo de Movimiento</label>
                        <select class="form-select form-select-sm" id="elimTipo" onchange="Admin.buscarMov()">
                            <option value="">-- Seleccione --</option>
                            <option value="remito">Remito</option>
                            <option value="factura">Factura</option>
                            <option value="compra">Compra a Proveedor</option>
                            <option value="cobro">Cobro</option>
                            <option value="pago">Pago</option>
                        </select>
                        <label class="form-label-sm mt-2">N° Documento</label>
                        <input type="text" class="form-control form-control-sm" id="elimNumero">
                        <button class="btn btn-sm btn-primary mt-2 w-100" data-action="Admin.buscarMov">
                            <i class="bi bi-search"></i> Buscar
                        </button>
                    </div>
                </div>
                <div class="col-md-9">
                    <div id="elimResultados"></div>
                </div>
            </div>
        `;
        Utils.showView(html);
    },

    async buscarMov() {
        const tipo = document.getElementById('elimTipo').value;
        const numero = document.getElementById('elimNumero').value.trim();
        if (!tipo) return;

        try {
            let rows, columns;

            if (tipo === 'remito') {
                rows = await API.admin.buscarMov('remito', numero);
                columns = [
                    { field: 'id', label: 'N° Remito' },
                    { field: 'cliente', label: 'Cliente' },
                    { field: 'fecha', label: 'Fecha', format: 'date' }
                ];
            } else if (tipo === 'factura') {
                rows = await API.admin.buscarMov('factura', numero);
                columns = [
                    { field: 'facturanumero', label: 'N° Factura' },
                    { field: 'cliente', label: 'Cliente' },
                    { field: 'fecha', label: 'Fecha', format: 'date' },
                    { field: 'total', label: 'Total', format: 'currency' }
                ];
            } else if (tipo === 'compra') {
                rows = await API.admin.buscarMov('compra', numero);
                columns = [
                    { field: 'id', label: 'N° Compra' },
                    { field: 'proveedor', label: 'Proveedor' },
                    { field: 'fecha', label: 'Fecha', format: 'date' },
                    { field: 'total', label: 'Total', format: 'currency' }
                ];
            } else if (tipo === 'cobro') {
                rows = await API.admin.buscarMov('cobro', numero);
                columns = [
                    { field: 'ordcobro', label: 'N° Cobro' },
                    { field: 'cliente', label: 'Cliente' },
                    { field: 'monto', label: 'Monto', format: 'currency' },
                    { field: 'fecha', label: 'Fecha', format: 'date' }
                ];
            } else if (tipo === 'pago') {
                rows = await API.admin.buscarMov('pago', numero);
                columns = [
                    { field: 'ordpago', label: 'N° Pago' },
                    { field: 'proveedor', label: 'Proveedor' },
                    { field: 'monto', label: 'Monto', format: 'currency' },
                    { field: 'fecha', label: 'Fecha', format: 'date' }
                ];
            }

            // Agregar botón eliminar a cada fila
            const idField = tipo === 'remito' ? 'id' : tipo === 'factura' ? 'facturanumero' :
                             tipo === 'compra' ? 'id' : tipo === 'cobro' ? 'ordcobro' : 'ordpago';
            columns.push({
                field: '_accion', label: 'Acción',
                render: (row) => `<button class="btn btn-sm btn-danger" data-action="Admin.eliminar" data-tipo="${tipo}" data-id="${row[idField]}"><i class="bi bi-trash"></i> Eliminar</button>`
            });

            document.getElementById('elimResultados').innerHTML = Utils.buildTable(columns, rows);
        } catch (err) {
            Utils.toast('Error al buscar movimientos: ' + err.message, 'Error', 'error');
        }
    },

    async eliminar(tipo, id) {
        const ok = await Utils.confirm('Confirmar Eliminación',
            `¿Está seguro de eliminar este ${tipo} N° ${id}? Se revertirán saldos y stock.`);
        if (!ok) return;

        try {
            await API.admin.eliminarMov(tipo, id);
            Utils.toast(`${tipo} N° ${id} eliminado correctamente`, 'Administración', 'success');
            this.buscarMov();
        } catch (err) {
            Utils.toast('Error al eliminar: ' + err.message, 'Error', 'error');
        }
    },

    /* ───────── Morosos ───────── */
    async showMorosos() {
        try {
            const clientes = await API.admin.getMorosos();
            let totalDeuda = 0;
            clientes.forEach(c => totalDeuda += c.saldo);

            const columns = [
                { field: 'nombre', label: 'Cliente' },
                { field: 'cuit', label: 'CUIT' },
                { field: 'telefono', label: 'Teléfono' },
                { field: 'saldo', label: 'Deuda', format: 'currency' }
            ];

            const html = `
                <div class="section-header" style="background:linear-gradient(135deg,#e65100,#ef6c00)">
                    <h4><i class="bi bi-exclamation-circle"></i> Clientes Morosos</h4>
                </div>
                <div class="alert alert-info">
                    <strong>Total deuda:</strong> ${Utils.formatCurrency(totalDeuda)} | 
                    <strong>Clientes con saldo:</strong> ${clientes.length}
                </div>
                ${Utils.buildTable(columns, clientes)}
            `;
            Utils.showView(html);
        } catch (err) {
            Utils.toast('Error al cargar morosos: ' + err.message, 'Error', 'error');
        }
    },

    /* ───────── Resumen ───────── */
    showResumen() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#1a237e,#283593)">
                <h4><i class="bi bi-graph-up"></i> Resumen General</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-3">
                    <div class="form-card">
                        <label class="form-label-sm">Desde</label>
                        <input type="date" class="form-control form-control-sm" id="resDesde">
                        <label class="form-label-sm mt-2">Hasta</label>
                        <input type="date" class="form-control form-control-sm" id="resHasta" value="${Utils.today()}">
                        <button class="btn btn-primary mt-2 w-100" data-action="Admin.calcularResumen">
                            <i class="bi bi-calculator"></i> Calcular
                        </button>
                    </div>
                </div>
                <div class="col-md-9" id="resContenido">
                    <p class="text-muted">Seleccione un rango de fechas y presione Calcular.</p>
                </div>
            </div>
        `;
        Utils.showView(html);
    },

    async calcularResumen() {
        const desde = document.getElementById('resDesde').value;
        const hasta = document.getElementById('resHasta').value;

        try {
            const data = await API.admin.getResumen(desde, hasta);

            document.getElementById('resContenido').innerHTML = `
                <div class="row g-3">
                    <div class="col-md-4">
                        <div class="card text-center border-success">
                            <div class="card-body">
                                <h6 class="text-success">Ventas Facturadas</h6>
                                <h4>${Utils.formatCurrency(data.ventas)}</h4>
                                <small>${data.factCount} facturas</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-center border-danger">
                            <div class="card-body">
                                <h6 class="text-danger">Compras</h6>
                                <h4>${Utils.formatCurrency(data.compras)}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-center border-warning">
                            <div class="card-body">
                                <h6 class="text-warning">Gastos</h6>
                                <h4>${Utils.formatCurrency(data.gastos)}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-center border-info">
                            <div class="card-body">
                                <h6 class="text-info">Cobros</h6>
                                <h4>${Utils.formatCurrency(data.cobros)}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-center border-secondary">
                            <div class="card-body">
                                <h6>Pagos</h6>
                                <h4>${Utils.formatCurrency(data.pagos)}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-center border-primary">
                            <div class="card-body">
                                <h6 class="text-primary">Remitos</h6>
                                <h4>${data.remitos}</h4>
                            </div>
                        </div>
                    </div>
                </div>
                <hr>
                <div class="row g-3 mt-1">
                    <div class="col-md-4">
                        <div class="card text-center bg-success text-white">
                            <div class="card-body">
                                <h6>Resultado Bruto</h6>
                                <h4>${Utils.formatCurrency(data.ventas - data.compras - data.gastos)}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-center bg-warning text-dark">
                            <div class="card-body">
                                <h6>Saldo Clientes Deudores</h6>
                                <h4>${Utils.formatCurrency(data.totalClientes)}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-center bg-info text-white">
                            <div class="card-body">
                                <h6>Saldo Proveedores</h6>
                                <h4>${Utils.formatCurrency(data.totalProveedores)}</h4>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        } catch (err) {
            Utils.toast('Error al calcular resumen: ' + err.message, 'Error', 'error');
        }
    },

    /* ───────── Estado de la Base de Datos ─────────
     *
     * Antes esta pantalla era una CONSOLA SQL LIBRE (`Admin.ejecutarQuery`) que
     * corría contra la base sql.js del navegador. Se eliminó por dos motivos:
     *
     *  1. Esa base ya no existe: la consola sólo devolvía resultados vacíos y
     *     "DB no inicializada", y el panel informaba "OK / 0 tablas" sobre una
     *     base fantasma, no sobre la real.
     *  2. Migrarla tal cual habría exigido un endpoint que ejecute SQL arbitrario
     *     contra la base real. Eso es un agujero de seguridad grave (lectura de
     *     hashes de usuarios, DROP TABLE, escalada de privilegios) y este sistema
     *     se publica a internet, así que ese endpoint no existe ni debe existir.
     *
     * En su lugar: un panel de estado de sólo lectura armado con endpoints
     * acotados y ya existentes (db-info, dashboard, resumen, morosos).
     */
    async showChequearDB() {
        Utils.showView(`
            <div class="section-header" style="background:linear-gradient(135deg,#5e35b1,#7e57c2)">
                <h4><i class="bi bi-database-check"></i> Estado de la Base de Datos</h4>
            </div>
            <div id="chkContenido"><p class="text-muted"><i class="bi bi-hourglass-split"></i> Consultando el servidor...</p></div>
        `);

        const fallo = (err) => { console.warn('[admin] chequeo de BD:', err.message); return null; };
        const [info, dash, resumen, morosos] = await Promise.all([
            API.admin.getDbInfo().catch(fallo),
            API.admin.getDashboard().catch(fallo),
            API.admin.getResumen().catch(fallo),
            API.admin.getMorosos().catch(fallo)
        ]);

        const cont = document.getElementById('chkContenido');
        if (!cont) return;   // el usuario navegó a otra vista mientras cargaba

        if (!info && !dash && !resumen && !morosos) {
            cont.innerHTML = `<div class="alert alert-danger">
                <i class="bi bi-x-octagon"></i> <strong>Sin conexión con la base de datos.</strong>
                Ninguna consulta al servidor respondió correctamente. Revise que el backend esté corriendo.
            </div>`;
            return;
        }

        const num = (v) => Utils.escapeHtml(String(v === undefined || v === null ? '—' : v));
        const money = (v) => Utils.escapeHtml(Utils.formatCurrency(v || 0));
        const deuda = (morosos || []).reduce((a, c) => a + (c.saldo || 0), 0);

        const tarjeta = (color, titulo, valor, pie = '') => `
            <div class="col-md-3">
                <div class="card border-${color} h-100">
                    <div class="card-body text-center py-3">
                        <h6 class="text-${color} mb-1">${titulo}</h6>
                        <h4 class="mb-0">${valor}</h4>
                        ${pie ? `<small class="text-muted">${pie}</small>` : ''}
                    </div>
                </div>
            </div>`;

        const tablas = (info && info.tables) ? info.tables : [];
        const listaTablas = tablas.map(t => `<span class="badge bg-secondary me-1 mb-1">${Utils.escapeHtml(t)}</span>`).join('');

        cont.innerHTML = `
            <div class="alert ${info ? 'alert-success' : 'alert-warning'} d-flex justify-content-between align-items-center">
                <div>
                    <i class="bi bi-${info ? 'check-circle-fill' : 'exclamation-triangle'}"></i>
                    <strong>${info ? 'Base de datos accesible' : 'No se pudo leer la información del motor'}</strong>
                    ${info ? `<div class="small text-muted">Motor: <code>${Utils.escapeHtml(info.engine_url)}</code> — ${tablas.length} tablas en el esquema</div>` : ''}
                </div>
                <button class="btn btn-sm btn-outline-secondary" data-action="Admin.showChequearDB">
                    <i class="bi bi-arrow-clockwise"></i> Actualizar
                </button>
            </div>

            <h6 class="text-muted">Maestros</h6>
            <div class="row g-3 mb-3">
                ${tarjeta('primary', 'Productos', num(dash && dash.stock_count))}
                ${tarjeta('success', 'Clientes', num(dash && dash.cliente_count))}
                ${tarjeta('warning', 'Proveedores', num(dash && dash.proveedor_count))}
                ${tarjeta('info', 'Saldo de Caja', money(dash && dash.caja_saldo))}
            </div>

            <h6 class="text-muted">Comprobantes registrados (histórico completo)</h6>
            <div class="row g-3 mb-3">
                ${tarjeta('success', 'Ventas facturadas', money(resumen && resumen.ventas), resumen ? `${num(resumen.factCount)} facturas` : '')}
                ${tarjeta('danger', 'Compras', money(resumen && resumen.compras))}
                ${tarjeta('warning', 'Gastos', money(resumen && resumen.gastos))}
                ${tarjeta('primary', 'Remitos', num(resumen && resumen.remitos))}
                ${tarjeta('info', 'Cobros', money(resumen && resumen.cobros))}
                ${tarjeta('secondary', 'Pagos', money(resumen && resumen.pagos))}
                ${tarjeta('dark', 'Clientes con deuda', num(morosos ? morosos.length : null), morosos ? money(deuda) : '')}
            </div>

            <div class="row">
                <div class="col-md-8">
                    <div class="form-card">
                        <h6><i class="bi bi-table"></i> Tablas del esquema</h6>
                        ${tablas.length ? listaTablas : '<span class="text-muted small">No disponible (requiere rol administrador).</span>'}
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="form-card">
                        <h6><i class="bi bi-shield-lock"></i> Consola SQL</h6>
                        <p class="small mb-2">
                            La consola SQL libre fue <strong>retirada</strong>: ejecutar SQL arbitrario
                            desde el navegador contra la base real permitiría leer credenciales o borrar
                            tablas. Para operaciones puntuales use
                            <a href="#" data-action="Admin.showEliminarMov">Eliminar Movimiento</a>.
                        </p>
                        <h6 class="mt-3"><i class="bi bi-hdd"></i> Respaldo</h6>
                        <p class="small mb-0">
                            La base vive en el servidor, no en el navegador: el respaldo se hace copiando
                            el archivo del motor. La API todavía <strong>no expone</strong> un endpoint de
                            backup/restore.
                        </p>
                    </div>
                </div>
            </div>
        `;
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
    },

    // Roles disponibles en el sistema
    ROLES: ['administrador', 'caja', 'encargado_ventas', 'encargado_compras', 'encargado_deposito', 'auditor', 'finanzas'],

    // ==================== MÓDULOS DEL SISTEMA ====================
    async showModulos() {
        let modulos = [];
        try {
            modulos = await API.modulos.getAll();
        } catch (err) {
            Utils.toast('No se pudieron cargar los módulos: ' + err.message, 'Error', 'error');
            return;
        }

        const filas = modulos.map(m => {
            const rolesActuales = (m.roles || '').split(',').map(s => s.trim().toLowerCase());
            const checksRoles = this.ROLES.map(rol => `
                <div class="form-check form-check-inline">
                    <input class="form-check-input" type="checkbox" id="mod_rol_${m.clave}_${rol}" ${rolesActuales.includes(rol) ? 'checked' : ''} ${rol === 'administrador' ? 'checked disabled' : ''}>
                    <label class="form-check-label small" for="mod_rol_${m.clave}_${rol}">${rol}</label>
                </div>`).join('');
            return `
                <div class="card mb-2">
                    <div class="card-body py-2">
                        <div class="row align-items-center">
                            <div class="col-md-3">
                                <strong><i class="bi ${Utils.escapeHtml(m.icono || 'bi-grid')}"></i> ${Utils.escapeHtml(m.nombre)}</strong>
                                <div class="text-muted small">${Utils.escapeHtml(m.descripcion || '')}</div>
                                <span class="badge bg-secondary">${Utils.escapeHtml(m.categoria || '')}</span>
                            </div>
                            <div class="col-md-2">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="mod_hab_${m.clave}" ${m.habilitado ? 'checked' : ''}>
                                    <label class="form-check-label" for="mod_hab_${m.clave}">Habilitado</label>
                                </div>
                            </div>
                            <div class="col-md-5">
                                <label class="form-label-sm text-muted">Roles con acceso:</label><br>
                                ${checksRoles}
                            </div>
                            <div class="col-md-2 text-end">
                                <button class="btn btn-sm btn-primary" data-action="Admin.guardarModulo" data-arg="${m.clave}">
                                    <i class="bi bi-save"></i> Guardar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
        }).join('');

        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#37474f,#546e7a)">
                <h4><i class="bi bi-gear"></i> Módulos del Sistema</h4>
            </div>
            <p class="text-muted">Habilite o deshabilite los módulos disponibles en esta instalación y defina qué roles pueden acceder a cada uno.</p>
            ${filas}
        `;
        Utils.showView(html);
    },

    async guardarModulo(clave) {
        const habilitado = document.getElementById(`mod_hab_${clave}`).checked;
        const roles = this.ROLES.filter(rol => {
            const cb = document.getElementById(`mod_rol_${clave}_${rol}`);
            return cb && cb.checked;
        });
        try {
            await API.modulos.update(clave, { habilitado, roles: roles.join(',') });
            Utils.toast(`Módulo "${clave}" actualizado`, 'Módulos', 'success');
        } catch (err) {
            Utils.toast('Error al guardar: ' + err.message, 'Error', 'error');
        }
    },

    // ==================== CONFIGURACIÓN DEL NEGOCIO ====================
    async showConfiguracion() {
        let cfg = {};
        try {
            cfg = await API.config.get();
        } catch (err) {
            Utils.toast('No se pudo cargar la configuración: ' + err.message, 'Error', 'error');
            return;
        }
        const v = (k) => Utils.escapeHtml(cfg[k] || '');
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#1565c0,#1976d2)">
                <h4><i class="bi bi-shop"></i> Configuración del Negocio</h4>
            </div>
            <div class="form-card" style="max-width:720px">
                <div class="row g-3">
                    <div class="col-md-8">
                        <label class="form-label-sm">Nombre del comercio</label>
                        <input type="text" class="form-control" id="cfg_negocio_nombre" value="${v('negocio_nombre')}">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label-sm">CUIT</label>
                        <input type="text" class="form-control" id="cfg_negocio_cuit" value="${v('negocio_cuit')}">
                    </div>
                    <div class="col-md-8">
                        <label class="form-label-sm">Dirección</label>
                        <input type="text" class="form-control" id="cfg_negocio_direccion" value="${v('negocio_direccion')}">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label-sm">Localidad</label>
                        <input type="text" class="form-control" id="cfg_negocio_localidad" value="${v('negocio_localidad')}">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label-sm">Teléfono</label>
                        <input type="text" class="form-control" id="cfg_negocio_telefono" value="${v('negocio_telefono')}">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label-sm">Condición IVA</label>
                        <select class="form-select" id="cfg_negocio_iva">
                            ${['Responsable Inscripto', 'Monotributo', 'Exento', 'Consumidor Final'].map(o => `<option ${cfg.negocio_iva === o ? 'selected' : ''}>${o}</option>`).join('')}
                        </select>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label-sm">Punto de Venta</label>
                        <input type="text" class="form-control" id="cfg_negocio_punto_venta" value="${v('negocio_punto_venta')}">
                    </div>
                </div>
                <hr>
                <button class="btn btn-primary" data-action="Admin.guardarConfiguracion">
                    <i class="bi bi-save"></i> Guardar Configuración
                </button>
            </div>
        `;
        Utils.showView(html);
    },

    async guardarConfiguracion() {
        const claves = ['negocio_nombre', 'negocio_cuit', 'negocio_direccion', 'negocio_localidad', 'negocio_telefono', 'negocio_iva', 'negocio_punto_venta'];
        const cambios = {};
        claves.forEach(k => {
            const el = document.getElementById(`cfg_${k}`);
            if (el) cambios[k] = el.value;
        });
        try {
            await API.config.update(cambios);
            Utils.toast('Configuración guardada', 'Negocio', 'success');
            if (window.Auth && Auth.applyConfig) Auth.applyConfig();
        } catch (err) {
            Utils.toast('Error al guardar: ' + err.message, 'Error', 'error');
        }
    },

    // ==================== USUARIOS ====================
    async showUsuarios() {
        let usuarios = [];
        try {
            usuarios = await API.auth.getUsuarios();
        } catch (err) {
            Utils.toast('No se pudieron cargar los usuarios: ' + err.message, 'Error', 'error');
            return;
        }
        const filas = usuarios.map(u => `
            <tr>
                <td>${u.id}</td>
                <td>${Utils.escapeHtml(u.username)}</td>
                <td><span class="badge bg-info">${Utils.escapeHtml(u.rol)}</span></td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-danger" data-action="Admin.eliminarUsuario" data-arg="${u.id}">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>`).join('');
        const opcionesRol = this.ROLES.map(r => `<option value="${r}">${r}</option>`).join('');
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#4527a0,#5e35b1)">
                <h4><i class="bi bi-people-fill"></i> Gestión de Usuarios</h4>
            </div>
            <div class="row">
                <div class="col-md-7">
                    <table class="table table-sm table-bordered">
                        <thead><tr><th>ID</th><th>Usuario</th><th>Rol</th><th></th></tr></thead>
                        <tbody>${filas}</tbody>
                    </table>
                </div>
                <div class="col-md-5">
                    <div class="form-card">
                        <h6>Nuevo Usuario</h6>
                        <input type="text" class="form-control mb-2" id="nu_username" placeholder="Nombre de usuario">
                        <input type="password" class="form-control mb-2" id="nu_password" placeholder="Contraseña">
                        <select class="form-select mb-2" id="nu_rol">${opcionesRol}</select>
                        <button class="btn btn-success w-100" data-action="Admin.crearUsuario">
                            <i class="bi bi-person-plus"></i> Crear Usuario
                        </button>
                    </div>
                </div>
            </div>
        `;
        Utils.showView(html);
    },

    async crearUsuario() {
        const username = document.getElementById('nu_username').value.trim();
        const password = document.getElementById('nu_password').value;
        const rol = document.getElementById('nu_rol').value;
        if (!username || !password) {
            Utils.toast('Complete usuario y contraseña', 'Validación', 'warning');
            return;
        }
        try {
            await API.auth.crearUsuario({ username, password, rol });
            Utils.toast('Usuario creado', 'Usuarios', 'success');
            this.showUsuarios();
        } catch (err) {
            Utils.toast('Error: ' + err.message, 'Error', 'error');
        }
    },

    async eliminarUsuario(id) {
        if (!confirm('¿Eliminar este usuario?')) return;
        try {
            await API.auth.eliminarUsuario(id);
            Utils.toast('Usuario eliminado', 'Usuarios', 'success');
            this.showUsuarios();
        } catch (err) {
            Utils.toast('Error: ' + err.message, 'Error', 'error');
        }
    }
};
// Exponer Admin
window.Admin = Admin;
