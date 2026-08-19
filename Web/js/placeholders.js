/**
 * Placeholders defensivos para los handlers declarativos (data-action="Stock.x").
 *
 * Si un modulo no llego a cargarse, `window.Stock` seria `undefined` y el click
 * moriria con un TypeError en la consola: el cajero ve que el boton "no hace
 * nada" y no hay forma de saber por que. Con el Proxy, cualquier metodo que se
 * invoque sobre un modulo ausente avisa por pantalla en vez de fallar callado.
 * No pisa modulos ya cargados: solo rellena los que faltan.
 *
 * Vive en su propio archivo y no como <script> inline dentro de index.html
 * porque la Content-Security-Policy del servidor (ver backend/main.py) declara
 * `script-src-elem 'self'`: ningun <script> escrito dentro del HTML se ejecuta.
 * Esa regla es la que impide que un dato del comercio con `<script>` adentro se
 * ejecute en la pantalla de quien lo mira, asi que el precio de mantenerla es
 * este archivo. Debe seguir cargandose DESPUES de todos los modulos.
 */
(function () {
    const modules = ['Stock', 'Clientes', 'Proveedores', 'Remitos', 'Facturas', 'Cobros', 'Pagos', 'Caja', 'Gastos', 'IVA', 'Admin', 'Auditoria', 'App', 'Utils'];
    modules.forEach(name => {
        if (!window[name]) {
            window[name] = new Proxy({}, {
                get(target, prop) {
                    if (typeof prop === 'string') {
                        return function () {
                            if (window.Utils && Utils.toast) Utils.toast(`${name} no cargado aún: ${prop}()`, 'Módulo', 'warning');
                            else console.warn(`${name}.${prop}() llamado pero módulo no está cargado`);
                        };
                    }
                    return undefined;
                }
            });
        }
    });
})();
