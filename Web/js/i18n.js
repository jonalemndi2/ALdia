/**
 * i18n.js - La interfaz en el idioma de quien la usa.
 *
 * COMO SE TRADUCE UN ERROR SIN QUE EL SERVIDOR TRADUZCA
 * ----------------------------------------------------
 * El backend manda, junto al mensaje, un `codigo` estable y los `params` que lo
 * rellenan:
 *
 *     { detail: "Stock insuficiente de 'Coca 2.25': se piden 12 y hay 5",
 *       codigo: "STOCK_INSUFICIENTE",
 *       params: { producto: "Coca 2.25", pedido: 12, disponible: 5 } }
 *
 * Con eso alcanza para armar el mensaje en cualquier idioma acá, sin pedirle
 * nada más al servidor. Si no hay plantilla para ese código, se muestra
 * `detail` tal cual: un mensaje útil en otro idioma es mejor que una clave sin
 * traducir en la cara del cajero.
 *
 * ELEGIR EL IDIOMA
 * ----------------
 * Lo decide la instalación, no el navegador: sale de GET /api/config/pais. Un
 * comercio en Miami con un empleado que tiene el navegador en español igual
 * necesita que la factura y los rótulos digan lo mismo para todos.
 */

const I18N = {
    idioma: 'es-AR',

    /** Rótulos de la interfaz. La clave es descriptiva, no el texto en español. */
    textos: {
        'es-AR': {
            'app.cargando': 'Cargando…',
            'menu.stock': 'Stock', 'menu.clientes': 'Clientes',
            'menu.proveedores': 'Proveedores', 'menu.ventas': 'Ventas',
            'menu.caja': 'Caja', 'menu.gastos': 'Gastos',
            'menu.auditoria': 'Auditoría', 'menu.salir': 'Salir',
            'auth.usuario': 'Usuario', 'auth.password': 'Contraseña',
            'auth.entrar': 'Entrar',
            'accion.guardar': 'Guardar', 'accion.cancelar': 'Cancelar',
            'accion.eliminar': 'Eliminar', 'accion.buscar': 'Buscar',
            'accion.nuevo': 'Nuevo', 'accion.editar': 'Editar',
            'campo.nombre': 'Nombre', 'campo.telefono': 'Teléfono',
            'campo.domicilio': 'Domicilio', 'campo.saldo': 'Saldo',
            'campo.total': 'Total', 'campo.fecha': 'Fecha',
            'campo.cantidad': 'Cantidad', 'campo.precio': 'Precio',
            'error.generico': 'Ocurrió un error',
            'error.sin_conexion': 'No se pudo conectar con el servidor',
        },
        'en-US': {
            'app.cargando': 'Loading…',
            'menu.stock': 'Inventory', 'menu.clientes': 'Customers',
            'menu.proveedores': 'Vendors', 'menu.ventas': 'Sales',
            'menu.caja': 'Cash', 'menu.gastos': 'Expenses',
            'menu.auditoria': 'Audit log', 'menu.salir': 'Sign out',
            'auth.usuario': 'Username', 'auth.password': 'Password',
            'auth.entrar': 'Sign in',
            'accion.guardar': 'Save', 'accion.cancelar': 'Cancel',
            'accion.eliminar': 'Delete', 'accion.buscar': 'Search',
            'accion.nuevo': 'New', 'accion.editar': 'Edit',
            'campo.nombre': 'Name', 'campo.telefono': 'Phone',
            'campo.domicilio': 'Address', 'campo.saldo': 'Balance',
            'campo.total': 'Total', 'campo.fecha': 'Date',
            'campo.cantidad': 'Quantity', 'campo.precio': 'Price',
            'error.generico': 'Something went wrong',
            'error.sin_conexion': 'Could not reach the server',
        }
    },

    /** Plantillas de error por código. Las llaves son los `params` del backend. */
    errores: {
        'es-AR': {
            STOCK_INSUFICIENTE: "Stock insuficiente de '{producto}': se intentan facturar {pedido} y hay {disponible}",
            TIENE_MOVIMIENTOS: 'No se puede eliminar {que} porque tiene movimientos registrados ({detalle}).',
            CLIENTE_NO_EXISTE: 'No existe el cliente {identificador}',
            PROVEEDOR_NO_EXISTE: 'No existe el proveedor {identificador}',
            SIN_PERMISO: '{usuario} ({rol}) no tiene acceso al módulo «{modulo}»',
            SOLO_LECTURA: '{usuario} tiene rol auditor: no puede modificar datos',
            CREDENCIALES_INVALIDAS: 'Usuario o contraseña incorrectos',
            SESION_VENCIDA: 'La sesión ya no es válida. Volvé a iniciar sesión.',
            OPERACION_EN_CURSO: 'La misma operación se está ejecutando. Esperá unos segundos.',
        },
        'en-US': {
            STOCK_INSUFICIENTE: "Not enough stock for '{producto}': {pedido} requested, {disponible} on hand",
            TIENE_MOVIMIENTOS: '{que} cannot be deleted because it has recorded activity ({detalle}).',
            CLIENTE_NO_EXISTE: 'No such customer: {identificador}',
            PROVEEDOR_NO_EXISTE: 'No such vendor: {identificador}',
            SIN_PERMISO: '{usuario} ({rol}) does not have access to the "{modulo}" module',
            SOLO_LECTURA: '{usuario} has the auditor role: data cannot be changed',
            CREDENCIALES_INVALIDAS: 'Incorrect username or password',
            SESION_VENCIDA: 'This session is no longer valid. Please sign in again.',
            OPERACION_EN_CURSO: 'The same operation is already running. Wait a few seconds.',
        }
    },

    /** El idioma lo fija la instalación, no el navegador. */
    async iniciar() {
        try {
            const cfg = await API.get('/config/pais');
            if (cfg && cfg.idioma && this.textos[cfg.idioma]) this.idioma = cfg.idioma;
        } catch (e) {
            // Sin conexión o sin permisos: se queda con el idioma por defecto.
            // Traducir no es motivo para no dejar entrar a nadie.
            console.warn('i18n: no se pudo leer el idioma de la instalación', e);
        }
        this.aplicar();
        return this.idioma;
    },

    /** Un rótulo. Si falta, se devuelve la clave: se ve, y se puede arreglar. */
    t(clave) {
        const dic = this.textos[this.idioma] || {};
        const base = this.textos['es-AR'] || {};
        return dic[clave] || base[clave] || clave;
    },

    /**
     * El mensaje de un error, armado desde su código y sus params.
     * `respuesta` es el cuerpo JSON que devolvió el backend.
     */
    error(respuesta) {
        if (!respuesta) return this.t('error.generico');
        const { codigo, params, detail } = respuesta;
        const plantilla = (this.errores[this.idioma] || {})[codigo];
        if (!plantilla) return detail || this.t('error.generico');
        if (!params) return plantilla.replace(/\{[^}]+\}/g, '…');
        return plantilla.replace(/\{(\w+)\}/g, (_, k) =>
            (params[k] !== undefined ? params[k] : '…'));
    },

    /** Traduce el HTML ya renderizado: todo lo que tenga data-i18n. */
    aplicar(raiz = document) {
        raiz.querySelectorAll('[data-i18n]').forEach(el => {
            el.textContent = this.t(el.getAttribute('data-i18n'));
        });
        raiz.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.placeholder = this.t(el.getAttribute('data-i18n-placeholder'));
        });
        document.documentElement.lang = this.idioma.split('-')[0];
    }
};

window.I18N = I18N;
