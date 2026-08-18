/**
 * app.js - Controlador principal de la aplicación ALdia
 * Inicialización, dashboard y enrutamiento
 */
const App = {
    async init() {
        try {
            document.getElementById('loadingOverlay').classList.remove('d-none');
            this.bindDataActions();
            // Verificar salud de la API
            await API.get('/health');
            const statusEl = document.getElementById('dbStatus');
            if (statusEl) {
                statusEl.innerHTML = '<i class="bi bi-hdd-network"></i> Conectado';
                statusEl.classList.remove('text-warning');
                statusEl.classList.add('text-success');
            }
            if (window.Auth) {
                Auth.init();
            } else {
                this.showHome();
            }
            document.getElementById('loadingOverlay').classList.add('d-none');
            console.log('ALdia inicializado correctamente');
        } catch (err) {
            document.getElementById('loadingOverlay').classList.add('d-none');
            const statusEl = document.getElementById('dbStatus');
            if (statusEl) {
                statusEl.innerHTML = '<i class="bi bi-hdd-network"></i> Sin conexión';
                statusEl.classList.remove('text-warning');
                statusEl.classList.add('text-danger');
            }
            console.error('Error al inicializar:', err);
            const msg = (window.Utils && Utils.escapeHtml) ? Utils.escapeHtml(err.message || String(err)) : (err.message || err);
            // Mostrar el error dentro de #dynamicView para preservar los paneles
            // que el resto de la aplicación necesita.
            Utils.showView(`
                <div class="alert alert-danger m-4">
                    <h5><i class="bi bi-exclamation-triangle"></i> Error de Inicialización</h5>
                    <p>${msg}</p>
                    <button class="btn btn-outline-danger" data-action="App.reload">Reintentar</button>
                </div>`);
        }
    },

    async showHome() {
        try {
            const dashboard = await API.get('/admin/dashboard');
            const stockCount = dashboard.stock_count;
            const clienteCount = dashboard.cliente_count;
            const provCount = dashboard.proveedor_count;
            const cajaHoy = dashboard.caja_saldo;

            const html = `
            <div class="text-center mb-4">
                <h2 class="text-primary"><i class="bi bi-grid-3x3-gap-fill"></i> ALdia - Panel de Control</h2>
                <p class="text-muted">Sistema de Gestión Comercial</p>
            </div>
            <div class="row g-3 mb-4">
                <div class="col-md-3">
                    <div class="card border-primary h-100 dash-card" data-action="Stock.showExistencia" style="cursor:pointer">
                        <div class="card-body text-center">
                            <i class="bi bi-box-seam fs-1 text-primary me-3"></i>
                            <h6 class="mb-0 text-muted">Productos</h6>
                            <h3 class="mb-0">${stockCount}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card border-success h-100 dash-card" data-action="Clientes.showClientes" style="cursor:pointer">
                        <div class="card-body text-center">
                            <i class="bi bi-people fs-1 text-success me-3"></i>
                            <h6 class="mb-0 text-muted">Clientes</h6>
                            <h3 class="mb-0">${clienteCount}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card border-warning h-100 dash-card" data-action="Proveedores.showProveedores" style="cursor:pointer">
                        <div class="card-body text-center">
                            <i class="bi bi-truck fs-1 text-warning me-3"></i>
                            <h6 class="mb-0 text-muted">Proveedores</h6>
                            <h3 class="mb-0">${provCount}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card border-info h-100 dash-card" data-action="Caja.showCajaChica" style="cursor:pointer">
                        <div class="card-body text-center">
                            <i class="bi bi-safe fs-1 text-info me-3"></i>
                            <h6 class="mb-0 text-muted">Caja</h6>
                            <h3 class="mb-0">${Utils.formatCurrency(cajaHoy)}</h3>
                        </div>
                    </div>
                </div>
            </div>`;
            // Renderizar dentro de #homeView: nunca reemplazar #mainContent, que
            // contiene los paneles #homeView y #dynamicView usados por Utils.showView().
            const home = document.getElementById('homeView');
            home.innerHTML = html;
            Utils.showHome();
            this.bindDataActions();
        } catch (err) {
            console.error('Error al cargar el dashboard:', err);
            Utils.toast('No se pudo cargar el panel de control: ' + (err.message || err), 'Dashboard', 'error');
        }
    },

    reload() {
        location.reload();
    },

    bindDataActions() {
        document.querySelectorAll('[data-action], [data-action-dbl]').forEach(el => {
            const action = el.getAttribute('data-action');
            const actionDbl = el.getAttribute('data-action-dbl');

            const callAction = (act, e) => {
                try {
                    const parts = act.split('.');
                    const mod = parts[0];
                    const method = parts[1];
                    const idx = el.dataset.idx !== undefined ? (isNaN(el.dataset.idx) ? el.dataset.idx : parseInt(el.dataset.idx)) : undefined;
                    const arg = el.dataset.arg !== undefined ? el.dataset.arg : undefined;
                    if (window[mod] && typeof window[mod][method] === 'function') {
                        if (idx !== undefined) {
                            window[mod][method](idx, el, e);
                        } else if (arg !== undefined) {
                            window[mod][method](arg, el, e);
                        } else {
                            window[mod][method](el, e);
                        }
                    } else {
                        console.warn(`Acción no encontrada: ${act}`);
                        if (window.Utils && Utils.toast) Utils.toast(`Acción no disponible: ${act}`, 'Acción', 'warning');
                    }
                } catch (err) {
                    console.error('Error ejecutando action', act, err);
                }
            };

            if (action && !el.__actionClickBound) {
                el.addEventListener('click', (e) => callAction(action, e));
                el.__actionClickBound = true;
            }
            if (actionDbl && !el.__actionDblBound) {
                el.addEventListener('dblclick', (e) => callAction(actionDbl, e));
                el.__actionDblBound = true;
            }
        });
    }

    // NOTA: aquí vivían App._ultimosRemitos() y App._ultimasFacturas(), que
    // leían con DB.query() de la base sql.js del navegador (ya inexistente).
    // Se eliminaron por código muerto: ninguna vista, plantilla ni data-action
    // del proyecto las invocaba (verificado por búsqueda en Web/).
};

// Exponer App globalmente para handlers inline
window.App = App;

/* ───────── Arranque ───────── */
document.addEventListener('DOMContentLoaded', () => App.init());
