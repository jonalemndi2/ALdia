/**
 * api.js - Cliente HTTP para consumir la API REST del backend
 * Reemplaza db.js (sql.js) con fetch a FastAPI
 */

const API_BASE = "/api";

const API = {
    /** Token JWT almacenado en sessionStorage */
    getToken() {
        return sessionStorage.getItem('aldia_token');
    },

    /** Guardar token JWT */
    setToken(token) {
        sessionStorage.setItem('aldia_token', token);
    },

    /** Clear token */
    clearToken() {
        sessionStorage.removeItem('aldia_token');
        sessionStorage.removeItem('aldia_user');
    },

    /** Headers con autenticación */
    headers(isJson = true) {
        const h = {};
        if (isJson) h['Content-Type'] = 'application/json';
        const token = this.getToken();
        if (token) h['Authorization'] = `Bearer ${token}`;
        return h;
    },

    /** GET request */
    async get(endpoint, params = {}) {
        const url = new URL(API_BASE + endpoint, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') url.searchParams.append(k, v);
        });
        
        const response = await fetch(url.toString(), {
            method: 'GET',
            headers: this.headers(false)
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Error desconocido' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        return response.json();
    },

    /** POST request */
    async post(endpoint, data) {
        const response = await fetch(API_BASE + endpoint, {
            method: 'POST',
            headers: this.headers(true),
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Error desconocido' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        // Handle 204 No Content
        if (response.status === 204) return null;
        
        return response.json();
    },

    /** PUT request */
    async put(endpoint, data) {
        const response = await fetch(API_BASE + endpoint, {
            method: 'PUT',
            headers: this.headers(true),
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Error desconocido' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        return response.json();
    },

    /** DELETE request */
    async delete(endpoint) {
        const response = await fetch(API_BASE + endpoint, {
            method: 'DELETE',
            headers: this.headers(false)
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Error desconocido' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        return response.json();
    },

    // ==================== CLIENTES ====================
    clientes: {
        getAll(search) { return API.get('/clientes/', search ? { search } : {}); },
        getById(cuit) { return API.get(`/clientes/${cuit}`); },
        create(data) { return API.post('/clientes/', data); },
        update(cuit, data) { return API.put(`/clientes/${cuit}`, data); },
        delete(cuit) { return API.delete(`/clientes/${cuit}`); }
    },

    // ==================== PROVEEDORES ====================
    proveedores: {
        getAll(search) { return API.get('/proveedores/', search ? { search } : {}); },
        getById(cuit) { return API.get(`/proveedores/${cuit}`); },
        create(data) { return API.post('/proveedores/', data); },
        update(cuit, data) { return API.put(`/proveedores/${cuit}`, data); },
        delete(cuit) { return API.delete(`/proveedores/${cuit}`); }
    },

    // ==================== STOCK ====================
    stock: {
        getAll(search) { return API.get('/stock/', search ? { search } : {}); },
        getById(codigo) { return API.get(`/stock/${codigo}`); },
        create(data) { return API.post('/stock/', data); },
        update(codigo, data) { return API.put(`/stock/${codigo}`, data); },
        delete(codigo) { return API.delete(`/stock/${codigo}`); }
    },

    // ==================== REMITOS ====================
    remitos: {
        getAll(fecha) { return API.get('/remitos/', fecha ? { fecha } : {}); },
        getById(id) { return API.get(`/remitos/${id}`); },
        create(data) { return API.post('/remitos/', data); },
        getVentas(remitoId) { return API.get(`/remitos/${remitoId}/ventas`); },
        createVenta(data) { return API.post('/remitos/ventas', data); },
        getNoFacturados() { return API.get('/remitos/nofacturados'); }
    },

    // ==================== FACTURAS ====================
    facturas: {
        getAll(fecha, cliente) { 
            const params = {};
            if (fecha) params.fecha = fecha;
            if (cliente) params.cliente = cliente;
            return API.get('/facturas/', params);
        },
        getById(num) { return API.get(`/facturas/${num}`); },
        getVentas(num) { return API.get(`/facturas/${num}/ventas`); },
        create(data) { return API.post('/facturas/', data); },
        delete(num) { return API.delete(`/facturas/${num}`); }
    },

    // ==================== AFIP (factura electrónica) ====================
    // El backend habla con los web services reales de AFIP (WSAA + WSFEv1).
    // Si no hay certificado configurado, /estado devuelve habilitado:false y
    // solicitarCae responde 400 "AFIP no configurado": NUNCA un CAE inventado.
    afip: {
        estado() { return API.get('/afip/estado'); },
        tiposComprobante() { return API.get('/afip/tipos-comprobante'); },
        tiposIva() { return API.get('/afip/tipos-iva'); },
        ultimoAutorizado(puntoVenta, tipoComprobante) {
            const params = {};
            if (puntoVenta) params.punto_venta = puntoVenta;
            if (tipoComprobante) params.tipo_comprobante = tipoComprobante;
            return API.get('/afip/ultimo-autorizado', params);
        },
        solicitarCae(num, opciones = {}) {
            return API.post(`/afip/facturas/${num}/solicitar-cae`, opciones);
        },
        // QR fiscal obligatorio (RG 4892). Solo existe si la factura ya tiene CAE.
        qr(num) { return API.get(`/afip/facturas/${num}/qr`); },
        condicionesIva() { return API.get('/afip/condiciones-iva'); },
        tipoSugerido(num) { return API.get(`/afip/facturas/${num}/tipo-sugerido`); }
    },

    // ==================== COBROS ====================
    cobros: {
        getAll(fecha, cliente) { 
            const params = {};
            if (fecha) params.fecha = fecha;
            if (cliente) params.cliente = cliente;
            return API.get('/cobros/', params);
        },
        create(data) { return API.post('/cobros/', data); },
        delete(ordcobro) { return API.delete(`/cobros/${ordcobro}`); }
    },

    // ==================== PAGOS ====================
    pagos: {
        getAll(fecha, proveedor) { 
            const params = {};
            if (fecha) params.fecha = fecha;
            if (proveedor) params.proveedor = proveedor;
            return API.get('/pagos/', params);
        },
        create(data) { return API.post('/pagos/', data); },
        delete(ordpago) { return API.delete(`/pagos/${ordpago}`); }
    },

    // ==================== CAJA ====================
    caja: {
        getAll(fecha) { return API.get('/caja/', fecha ? { fecha } : {}); },
        create(data) { return API.post('/caja/', data); },
        getSaldo() { return API.get('/caja/saldo'); },
        getChequera() { return API.get('/caja/chequera'); },
        delete(id) { return API.delete(`/caja/${id}`); }
    },

    // ==================== GASTOS ====================
    gastos: {
        getAll(fecha) { return API.get('/gastos/', fecha ? { fecha } : {}); },
        create(data) { return API.post('/gastos/', data); },
        getConceptos(gastoId) { return API.get(`/gastos/${gastoId}/conceptos`); },
        delete(id) { return API.delete(`/gastos/${id}`); }
    },

    // ==================== IVA ====================
    iva: {
        consultar(fechaDesde, fechaHasta) { 
            const params = {};
            if (fechaDesde) params.fecha_desde = fechaDesde;
            if (fechaHasta) params.fecha_hasta = fechaHasta;
            return API.get('/iva/consulta', params);
        }
    },

    // ==================== AUTH ====================
    auth: {
        login(username, password) { 
            return API.post('/auth/login', { username, password });
        },
        getMe() { return API.get('/auth/me'); },
        getUsuarios() { return API.get('/auth/usuarios'); },
        crearUsuario(data) { return API.post('/auth/register', data); },
        eliminarUsuario(id) { return API.delete(`/auth/usuarios/${id}`); },
        cambiarPassword(passwordActual, passwordNueva) {
            return API.post('/auth/cambiar-password', {
                password_actual: passwordActual,
                password_nueva: passwordNueva
            });
        }
    },

    // ==================== ADMIN ====================
    admin: {
        getDashboard() { return API.get('/admin/dashboard'); },
        getDbInfo() { return API.get('/admin/db-info'); },
        resetDb() { return API.post('/admin/reset-db'); },
        seedData() { return API.post('/admin/seed-data'); },
        buscarMov(tipo, numero) { 
            const params = {};
            if (numero) params.numero = numero;
            return API.get(`/admin/movimientos/${tipo}`, params);
        },
        eliminarMov(tipo, id) { return API.delete(`/admin/movimientos/${tipo}/${id}`); },
        getMorosos() { return API.get('/admin/morosos'); },
        getResumen(desde, hasta) { 
            const params = {};
            if (desde) params.fecha_desde = desde;
            if (hasta) params.fecha_hasta = hasta;
            return API.get('/admin/resumen', params);
        }
    },

    // ==================== MÓDULOS ====================
    modulos: {
        getAll() { return API.get('/modulos/'); },
        getActivos() { return API.get('/modulos/activos'); },
        update(clave, data) { return API.put(`/modulos/${clave}`, data); },
        seed() { return API.post('/modulos/seed'); }
    },

    // ==================== AUDITORÍA ====================
    // Solo lectura: el registro no tiene endpoints de escritura ni de borrado,
    // ni siquiera para el administrador (ver backend/routers/auditoria.py).
    auditoria: {
        consultar(filtros = {}) { return API.get('/auditoria/', filtros); },
        filtros() { return API.get('/auditoria/filtros'); },
        /** Descarga el CSV con el token en la cabecera (un <a href> no lo lleva). */
        async exportarCsv(filtros = {}) {
            const url = new URL(API_BASE + '/auditoria/exportar.csv', window.location.origin);
            Object.entries(filtros).forEach(([k, v]) => {
                if (v !== undefined && v !== null && v !== '') url.searchParams.append(k, v);
            });
            const response = await fetch(url.toString(), { method: 'GET', headers: API.headers(false) });
            if (!response.ok) {
                const error = await response.json().catch(() => ({ detail: 'Error desconocido' }));
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            const blob = await response.blob();
            const enlace = document.createElement('a');
            enlace.href = URL.createObjectURL(blob);
            enlace.download = `auditoria_${new Date().toISOString().slice(0, 10)}.csv`;
            document.body.appendChild(enlace);
            enlace.click();
            enlace.remove();
            setTimeout(() => URL.revokeObjectURL(enlace.href), 5000);
            return true;
        }
    },

    // ==================== CONFIGURACIÓN ====================
    config: {
        get() { return API.get('/config/'); },
        update(cambios) { return API.put('/config/', cambios); }
    }
};

// Exponer globalmente
window.API = API;
