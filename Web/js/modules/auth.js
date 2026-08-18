/**
 * auth.js - Sistema de Autenticación y Autorización
 */
const Auth = {
    currentUser: null,

    async init() {
        const saved = sessionStorage.getItem('aldia_user');
        if (saved) {
            this.currentUser = JSON.parse(saved);
            // Validar token con el servidor
            try {
                const user = await API.auth.getMe();
                this.currentUser = user;
                sessionStorage.setItem('aldia_user', JSON.stringify(user));
                if (user.debe_cambiar_password) {
                    this.showCambioPassword();
                    return;
                }
                this.onLoginSuccess();
            } catch (err) {
                // Token inválido/expirado, limpiar y mostrar login
                API.clearToken();
                this.currentUser = null;
                this.showLogin();
            }
        } else {
            this.showLogin();
        }
    },

    showLogin() {
        document.getElementById('mainNavbar').classList.add('d-none');
        const dyn = document.getElementById('dynamicView');
        dyn.innerHTML = `
            <div class="row justify-content-center" style="margin-top: 10vh;">
                <div class="col-md-4">
                    <div class="card shadow border-primary">
                        <div class="card-header bg-primary text-white text-center py-3">
                            <h4 class="mb-0"><i class="bi bi-shield-lock"></i> Iniciar Sesión</h4>
                        </div>
                        <div class="card-body p-4">
                            <form id="loginForm">
                                <div class="mb-3">
                                    <label class="form-label text-muted">Usuario</label>
                                    <div class="input-group">
                                        <span class="input-group-text"><i class="bi bi-person"></i></span>
                                        <input type="text" id="loginUser" class="form-control form-control-lg" required>
                                    </div>
                                </div>
                                <div class="mb-4">
                                    <label class="form-label text-muted">Contraseña</label>
                                    <div class="input-group">
                                        <span class="input-group-text"><i class="bi bi-key"></i></span>
                                        <input type="password" id="loginPass" class="form-control form-control-lg" required>
                                    </div>
                                </div>
                                <button type="submit" class="btn btn-primary btn-lg w-100 mb-2">
                                    Ingresar <i class="bi bi-box-arrow-in-right"></i>
                                </button>
                                <div class="text-center mt-3">
                                    <small class="text-muted">Desarrollado para ALdia</small>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.getElementById('homeView').classList.add('d-none');
        dyn.classList.remove('d-none');

        document.getElementById('loginForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.login(document.getElementById('loginUser').value, document.getElementById('loginPass').value);
        });
    },

    async login(username, password) {
        try {
            const result = await API.auth.login(username, password);
            this.currentUser = result.user;
            API.setToken(result.access_token);
            sessionStorage.setItem('aldia_user', JSON.stringify(result.user));

            // Con la contraseña inicial el servidor rechaza todo lo demás:
            // llevar directo al cambio en vez de mostrar un sistema inoperable.
            if (result.user.debe_cambiar_password) {
                this.showCambioPassword();
                return;
            }

            Utils.toast(`Bienvenido ${result.user.username} (${result.user.rol})`, 'Login', 'success');
            this.onLoginSuccess();
        } catch (err) {
            Utils.toast(err.detail || 'Usuario o contraseña incorrectos', 'Error', 'error');
            const formInputs = document.querySelectorAll('#loginForm input');
            formInputs.forEach(i => i.classList.add('is-invalid'));
            setTimeout(() => {
                formInputs.forEach(i => i.classList.remove('is-invalid'));
            }, 2000);
        }
    },

    /**
     * Pantalla de cambio obligatorio. No hay forma de saltearla: el servidor
     * rechaza con 403 cualquier otra operación mientras la contraseña siga
     * siendo la inicial, así que esconder el botón no sería el control real.
     */
    showCambioPassword() {
        document.getElementById('mainNavbar').classList.add('d-none');
        const dyn = document.getElementById('dynamicView');
        dyn.innerHTML = `
            <div class="row justify-content-center" style="margin-top: 8vh;">
                <div class="col-md-5">
                    <div class="card shadow border-warning">
                        <div class="card-header bg-warning text-dark py-3">
                            <h5 class="mb-0"><i class="bi bi-shield-exclamation"></i>
                                Defina su contraseña</h5>
                        </div>
                        <div class="card-body p-4">
                            <p class="text-muted">
                                Está usando la contraseña inicial del sistema, que es
                                <strong>pública</strong>: figura en la documentación del
                                proyecto. Elija una propia para poder continuar.
                            </p>
                            <form id="cambioPassForm">
                                <div class="mb-3">
                                    <label class="form-label">Contraseña actual</label>
                                    <input type="password" id="passActual" class="form-control" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Contraseña nueva</label>
                                    <input type="password" id="passNueva" class="form-control" required>
                                    <div class="form-text">Mínimo 8 caracteres.</div>
                                </div>
                                <div class="mb-4">
                                    <label class="form-label">Repetir la nueva</label>
                                    <input type="password" id="passRepetir" class="form-control" required>
                                </div>
                                <button type="submit" class="btn btn-primary w-100">
                                    Guardar y continuar
                                </button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>`;
        document.getElementById('homeView').classList.add('d-none');
        dyn.classList.remove('d-none');

        document.getElementById('cambioPassForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const actual = document.getElementById('passActual').value;
            const nueva = document.getElementById('passNueva').value;
            const repetir = document.getElementById('passRepetir').value;

            if (nueva !== repetir) {
                Utils.toast('Las dos contraseñas nuevas no coinciden', 'Contraseña', 'error');
                return;
            }
            try {
                await API.auth.cambiarPassword(actual, nueva);
                this.currentUser.debe_cambiar_password = false;
                sessionStorage.setItem('aldia_user', JSON.stringify(this.currentUser));
                Utils.toast('Contraseña actualizada', 'Contraseña', 'success');
                this.onLoginSuccess();
            } catch (err) {
                Utils.toast(err.message || 'No se pudo cambiar la contraseña', 'Error', 'error');
            }
        });
    },

    async onLoginSuccess() {
        document.getElementById('mainNavbar').classList.remove('d-none');
        this.addLogoutButton();
        await this.applyConfig();
        await this.applyModulos();
        App.showHome();
    },

    logout() {
        this.currentUser = null;
        sessionStorage.removeItem('aldia_user');
        document.getElementById('logoutBtn')?.remove();
        this.showLogin();
    },

    addLogoutButton() {
        if (!document.getElementById('logoutBtn')) {
            const rightMenu = document.querySelector('#mainNavbar .navbar-text');
            const logoutLink = document.createElement('a');
            logoutLink.id = 'logoutBtn';
            logoutLink.href = '#';
            logoutLink.className = 'btn btn-sm btn-outline-light ms-3';
            logoutLink.innerHTML = '<i class="bi bi-power"></i> Salir';
            logoutLink.onclick = (e) => { e.preventDefault(); this.logout(); };
            rightMenu.appendChild(logoutLink);
        }
        
        // Mostrar nombre/rol en status
        const statusEl = document.getElementById('dbStatus');
        if (statusEl && this.currentUser) {
            const usuario = Utils.escapeHtml(String(this.currentUser.username || ''));
            const rolCrudo = String(this.currentUser.rol || '');
            const rol = Utils.escapeHtml(rolCrudo.charAt(0).toUpperCase() + rolCrudo.slice(1));
            statusEl.innerHTML += ` &nbsp; | &nbsp; <i class="bi bi-person"></i> ${usuario} (${rol})`;
        }
    },

    /** Cargar la configuración del negocio y aplicarla a la UI (nombre, etc.) */
    async applyConfig() {
        try {
            const cfg = await API.config.get();
            this.config = cfg || {};
            const nombre = this.config.negocio_nombre;
            if (nombre) {
                const brand = document.querySelector('#mainNavbar .navbar-brand');
                if (brand) brand.innerHTML = `<i class="bi bi-shop"></i> ${Utils.escapeHtml(nombre)}`;
                document.title = `${nombre} - Gestión Comercial`;
            }
        } catch (err) {
            console.warn('No se pudo cargar la configuración del negocio:', err.message);
        }
    },

    /**
     * Aplicar visibilidad de módulos y permisos según los módulos activos del
     * backend para el rol del usuario. Reemplaza el antiguo sistema hardcodeado.
     */
    async applyModulos() {
        const rol = (this.currentUser.rol || '').toLowerCase();
        const hideEl = (el) => el && el.classList.add('d-none');
        const showEl = (el) => el && el.classList.remove('d-none');

        // Mapeo de prefijo de acción a clave de módulo (para tarjetas del dashboard)
        const accionModulo = {
            'Stock': 'stock',
            'Clientes': 'clientes',
            'Remitos': 'ventas',
            'Facturas': 'ventas',
            'Proveedores': 'proveedores',
            'Pagos': 'proveedores',
            'Gastos': 'gastos',
            'Cobros': 'cuentas_corrientes',
            'Caja': 'caja',
            'IVA': 'iva',
            'Admin': 'administracion'
        };

        let activos = [];
        try {
            const modulos = await API.modulos.getActivos();
            activos = modulos.map(m => m.clave);
        } catch (err) {
            console.error('No se pudieron cargar los módulos activos:', err.message);
            // Ante un fallo, mostrar todo para no bloquear al usuario
            document.querySelectorAll('#mainNavbar [data-modulo]').forEach(showEl);
            return;
        }
        this.modulosActivos = activos;

        // 1) Mostrar/ocultar items del navbar por módulo
        // data-modulo admite varias claves separadas por coma: el item se ve si el
        // usuario tiene acceso a ALGUNA. Lo necesita el menú Administración, que
        // el rol auditor debe ver solo por el módulo "auditoria" (de solo consulta),
        // sin darle acceso al módulo "administracion".
        document.querySelectorAll('#mainNavbar [data-modulo]').forEach(el => {
            const claves = (el.getAttribute('data-modulo') || '').split(',').map(s => s.trim());
            if (claves.some(c => activos.includes(c))) showEl(el); else hideEl(el);
        });

        // 2) Ocultar items con rol requerido que el usuario no tenga
        document.querySelectorAll('[data-role-required]').forEach(el => {
            const roles = el.getAttribute('data-role-required').split(',').map(s => s.trim().toLowerCase());
            if (rol === 'administrador' || roles.includes(rol)) showEl(el); else hideEl(el);
        });

        // 3) Tarjetas del dashboard según módulo activo
        document.querySelectorAll('.dash-card[data-action]').forEach(el => {
            const prefijo = (el.getAttribute('data-action') || '').split('.')[0];
            const modulo = accionModulo[prefijo];
            if (!modulo || activos.includes(modulo)) showEl(el); else hideEl(el);
        });
    },

    /** Helper para que otros módulos comprueben acceso a un módulo */
    tieneModulo(clave) {
        return (this.modulosActivos || []).includes(clave);
    }
};

window.Auth = Auth;
