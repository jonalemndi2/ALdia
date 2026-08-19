"""
client.py - Cliente HTTP contra la API REST de ALdia.

Responsabilidades:

1. Login y renovacion del token JWT (dura 8 h). Las credenciales SIEMPRE salen
   de variables de entorno; nunca se escriben en el codigo ni se loguean.
2. Traducir los errores de la API a mensajes utiles para el asistente: si el
   backend responde 403 (rol sin permiso), 422 (validacion, p. ej. CUIT con
   digito verificador invalido) o 400 (regla de negocio, p. ej. stock
   insuficiente), el asistente tiene que recibir el texto real para poder
   corregir, no un "fallo la operacion".
3. Resolver identificadores tolerantes: en ALdia conviven CUIT guardados con
   guiones ("20-12345678-9") y sin guiones ("20123456789"), asi que las
   busquedas prueban ambas formas antes de darse por vencidas.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


# El token del backend dura 8 h (ACCESS_TOKEN_EXPIRE_MINUTES en routers/auth.py).
# Lo renovamos antes para no cortar una operacion a mitad de camino.
DURACION_TOKEN = timedelta(hours=8)
MARGEN_RENOVACION = timedelta(minutes=20)


class ALdiaError(Exception):
    """Error de negocio, permisos o validacion devuelto por la API de ALdia.

    El mensaje se construye para que el asistente pueda actuar sobre el:
    incluye el codigo HTTP y el `detail` textual que devolvio el backend.
    """


class ALdiaConfigError(ALdiaError):
    """Falta configuracion (variables de entorno) para hablar con ALdia."""


class ALdiaAmbiguo(ALdiaError):
    """Varios registros coinciden: hay que preguntarle al usuario cual es.

    Lleva los candidatos para que el asistente pueda ofrecer la eleccion en vez
    de pedirle al usuario que escriba un CUIT de memoria.
    """

    def __init__(self, mensaje: str, etiqueta: str = "", candidatos: list | None = None):
        super().__init__(mensaje)
        self.etiqueta = etiqueta
        self.candidatos = candidatos or []


def _texto_de_error(respuesta: httpx.Response) -> str:
    """Extrae el mensaje real que devolvio la API.

    FastAPI usa dos formas:
      - {"detail": "texto"}                        -> HTTPException del router
      - {"detail": [{"loc": [...], "msg": "..."}]} -> validacion Pydantic (422)
    """
    try:
        cuerpo = respuesta.json()
    except ValueError:
        texto = (respuesta.text or "").strip()
        return texto[:500] or f"HTTP {respuesta.status_code} sin cuerpo"

    detalle = cuerpo.get("detail") if isinstance(cuerpo, dict) else None

    if isinstance(detalle, str):
        return detalle

    if isinstance(detalle, list):
        partes: list[str] = []
        for item in detalle:
            if not isinstance(item, dict):
                partes.append(str(item))
                continue
            campo = ".".join(str(x) for x in item.get("loc", []) if x not in ("body",))
            msg = item.get("msg", "")
            # Pydantic prefija "Value error, " en los validadores propios.
            msg = msg.replace("Value error, ", "")
            partes.append(f"{campo}: {msg}" if campo else msg)
        return " | ".join(partes)

    return str(cuerpo)[:500]


class ALdiaClient:
    """Cliente REST autenticado contra ALdia."""

    def __init__(
        self,
        base_url: str | None = None,
        usuario: str | None = None,
        password: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("ALDIA_URL") or "http://127.0.0.1:8000").rstrip("/")
        self._usuario = usuario or os.getenv("ALDIA_USER") or ""
        self._password = password or os.getenv("ALDIA_PASSWORD") or ""
        if timeout is None:
            try:
                timeout = float(os.getenv("ALDIA_TIMEOUT", "30"))
            except ValueError:
                timeout = 30.0

        # Origen de las operaciones, para que la auditoria de ALdia no registre
        # todo como "la cuenta del agente". `ALDIA_CANAL` identifica la puerta
        # de entrada (openclaw, whatsapp, telegram) y `ALDIA_AGENTE` al agente.
        self._canal = (os.getenv("ALDIA_CANAL") or "openclaw").strip()[:30]
        self._agente = (os.getenv("ALDIA_AGENTE") or "aldia-mcp").strip()[:60]
        # Quien pidio la operacion, cuando el canal lo puede verificar (el numero
        # de WhatsApp, el user_id de Telegram). Se fija por llamada con
        # `fijar_solicitante()`: NUNCA lo deduce el modelo de la conversacion.
        self._solicitante: str = ""
        # Usuario de ALdia por el que actua el agente (ver fijar_actor).
        self._actor: str = ""
        self._operacion_id: str = ""

        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, follow_redirects=True)
        self._token: str | None = None
        self._token_vence: datetime | None = None
        self._usuario_info: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def fijar_solicitante(self, identificador: str) -> None:
        """Declara quien pidio las operaciones siguientes.

        El identificador debe venir del canal, que es lo unico verificable: el
        numero de telefono que informa WhatsApp, el user_id que informa
        Telegram. No debe salir de lo que el usuario escriba en el mensaje.

        Sirve para ATRIBUIR, no para autorizar: los permisos los sigue
        resolviendo ALdia contra la cuenta con la que este cliente se autentica.
        """
        self._solicitante = (identificador or "").strip()[:80]

    def fijar_actor(self, usuario: str) -> None:
        """Declara por que USUARIO DE ALdia actua el agente.

        Los permisos efectivos pasan a ser la interseccion de los de esta cuenta
        y los de ese usuario: el agente nunca puede hacer mas de lo que su propia
        credencial permite, ni mas de lo que permite la persona por la que actua.
        """
        self._actor = (usuario or "").strip()[:80]

    def _cabeceras_de_origen(self) -> dict[str, str]:
        cabeceras = {"X-ALdia-Canal": self._canal, "X-ALdia-Agente": self._agente}
        if self._solicitante:
            cabeceras["X-ALdia-Solicitante"] = self._solicitante
        if getattr(self, "_actor", ""):
            cabeceras["X-Actor-User-ID"] = self._actor
        if getattr(self, "_operacion_id", ""):
            cabeceras["X-Operation-Id"] = self._operacion_id
        return cabeceras

    # ─────────────────────────────────────────────────────────────
    # Autenticacion
    # ─────────────────────────────────────────────────────────────

    def _login(self) -> None:
        if not self._usuario or not self._password:
            raise ALdiaConfigError(
                "Faltan credenciales: defina las variables de entorno ALDIA_USER y "
                "ALDIA_PASSWORD (y ALDIA_URL si el servidor no esta en "
                "http://127.0.0.1:8000)."
            )
        try:
            respuesta = self._http.post(
                "/api/auth/login",
                json={"username": self._usuario, "password": self._password},
            )
        except httpx.RequestError as exc:
            raise ALdiaError(
                f"No se pudo conectar con ALdia en {self.base_url}: {exc}. "
                "Verifique que el servidor este levantado y que ALDIA_URL sea correcta."
            ) from exc

        if respuesta.status_code == 401:
            raise ALdiaError(
                "Usuario o contrasena incorrectos: revise ALDIA_USER / ALDIA_PASSWORD."
            )
        if respuesta.status_code == 429:
            raise ALdiaError(f"ALdia bloqueo el login: {_texto_de_error(respuesta)}")
        if respuesta.status_code >= 400:
            raise ALdiaError(
                f"Login rechazado (HTTP {respuesta.status_code}): {_texto_de_error(respuesta)}"
            )

        datos = respuesta.json()
        self._token = datos.get("access_token")
        self._usuario_info = datos.get("user")
        self._token_vence = datetime.now(timezone.utc) + DURACION_TOKEN

    def _asegurar_token(self) -> str:
        with self._lock:
            vencido = (
                self._token is None
                or self._token_vence is None
                or datetime.now(timezone.utc) >= self._token_vence - MARGEN_RENOVACION
            )
            if vencido:
                self._login()
            assert self._token is not None
            return self._token

    @property
    def usuario_actual(self) -> dict[str, Any]:
        """Datos del usuario con el que opera el asistente (id, username, rol)."""
        self._asegurar_token()
        return dict(self._usuario_info or {})

    # ─────────────────────────────────────────────────────────────
    # Peticiones
    # ─────────────────────────────────────────────────────────────

    def request(
        self,
        metodo: str,
        ruta: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        token = self._asegurar_token()
        limpios = {k: v for k, v in (params or {}).items() if v not in (None, "")}

        def _enviar(tok: str) -> httpx.Response:
            try:
                return self._http.request(
                    metodo,
                    ruta,
                    params=limpios or None,
                    json=json,
                    headers={"Authorization": f"Bearer {tok}", **self._cabeceras_de_origen()},
                )
            except httpx.RequestError as exc:
                raise ALdiaError(
                    f"Error de red hablando con ALdia ({metodo} {ruta}): {exc}"
                ) from exc

        respuesta = _enviar(token)

        # Token vencido o invalidado del lado del servidor: reintentar una vez.
        if respuesta.status_code == 401:
            with self._lock:
                self._token = None
                self._login()
                token = self._token or ""
            respuesta = _enviar(token)

        if respuesta.status_code >= 400:
            raise ALdiaError(self._mensaje_http(metodo, ruta, respuesta))

        if respuesta.status_code == 204 or not respuesta.content:
            return None
        try:
            return respuesta.json()
        except ValueError:
            return respuesta.text

    def _mensaje_http(self, metodo: str, ruta: str, respuesta: httpx.Response) -> str:
        detalle = _texto_de_error(respuesta)
        codigo = respuesta.status_code
        rol = (self._usuario_info or {}).get("rol", "desconocido")

        if codigo == 403:
            return (
                f"PERMISO DENEGADO ({codigo}) en {metodo} {ruta}: {detalle}. "
                f"El usuario '{(self._usuario_info or {}).get('username', '?')}' tiene rol "
                f"'{rol}'. Para hacer esta operacion hace falta un usuario con acceso a ese "
                "modulo (lo configura el administrador en 'Modulos del Sistema')."
            )
        if codigo == 404:
            return f"NO ENCONTRADO ({codigo}) en {metodo} {ruta}: {detalle}"
        if codigo == 422:
            return (
                f"DATOS INVALIDOS ({codigo}) en {metodo} {ruta}: {detalle}. "
                "Corrija el dato senalado y reintente."
            )
        if codigo == 400:
            return f"REGLA DE NEGOCIO ({codigo}) en {metodo} {ruta}: {detalle}"
        if codigo == 429:
            return f"DEMASIADOS INTENTOS ({codigo}) en {metodo} {ruta}: {detalle}"
        return f"ERROR {codigo} en {metodo} {ruta}: {detalle}"

    # Atajos
    def get(self, ruta: str, **params: Any) -> Any:
        return self.request("GET", ruta, params=params)

    def post(self, ruta: str, cuerpo: Any = None, **params: Any) -> Any:
        # Toda escritura lleva un identificador de operacion: si la respuesta se
        # pierde y esto se reintenta, ALdia devuelve el resultado original en vez
        # de ejecutar otra vez. Es lo que evita un cobro o una factura duplicada.
        import uuid
        self._operacion_id = f"mcp_{uuid.uuid4().hex}"
        try:
            return self.request("POST", ruta, params=params, json=cuerpo)
        finally:
            self._operacion_id = ""

    def put(self, ruta: str, cuerpo: Any = None) -> Any:
        return self.request("PUT", ruta, json=cuerpo)

    def delete(self, ruta: str) -> Any:
        return self.request("DELETE", ruta)

    # ─────────────────────────────────────────────────────────────
    # Resolucion de identificadores
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def solo_digitos(valor: str) -> str:
        return "".join(c for c in str(valor) if c.isdigit())

    def _resolver_entidad(self, recurso: str, etiqueta: str, texto: str) -> dict[str, Any]:
        """Devuelve la ficha de un cliente/proveedor a partir de CUIT o nombre.

        ALdia guarda algunos CUIT con guiones y otros sin, asi que buscar por
        coincidencia exacta no alcanza. Si hay mas de un candidato se lanza un
        error que los lista, para que el asistente pregunte cual es.
        """
        texto = (texto or "").strip()
        if not texto:
            raise ALdiaError(f"Falta indicar el {etiqueta} (CUIT o nombre).")

        # 1) Coincidencia exacta por CUIT tal cual esta guardado.
        try:
            return self.get(f"/api/{recurso}/{texto}")
        except ALdiaError:
            pass

        # 2) Busqueda por texto (el backend filtra por nombre y por CUIT).
        candidatos = self.get(f"/api/{recurso}/", search=texto) or []

        # 3) Si vino un CUIT con o sin guiones, comparar solo los digitos.
        digitos = self.solo_digitos(texto)
        if digitos:
            todos = self.get(f"/api/{recurso}/") or []
            por_digitos = [c for c in todos if self.solo_digitos(c.get("cuit", "")) == digitos]
            if por_digitos:
                candidatos = por_digitos

        if not candidatos:
            raise ALdiaError(
                f"No existe ningun {etiqueta} que coincida con '{texto}'. "
                f"Busque primero con la herramienta de busqueda de {recurso}, o de el alta "
                f"del {etiqueta} si es nuevo."
            )
        if len(candidatos) > 1:
            lista = ", ".join(f"{c.get('nombre')} ({c.get('cuit')})" for c in candidatos[:10])
            raise ALdiaAmbiguo(
                f"'{texto}' coincide con {len(candidatos)} {etiqueta}s: {lista}. "
                "Pregunte al usuario cuál es y vuelva a intentar con el CUIT exacto.",
                etiqueta=etiqueta,
                candidatos=[
                    {"cuit": c.get("cuit"), "nombre": c.get("nombre"),
                     "localidad": c.get("localidad", "")}
                    for c in candidatos[:10]
                ],
            )
        return candidatos[0]

    def dejar_pendiente(self, metodo: str, ruta: str, cuerpo: dict, *,
                        descripcion: str, candidatos: list, campo: str) -> dict:
        """Guarda una operación que no se puede ejecutar hasta que se aclare algo.

        La guarda EL SERVIDOR, no el agente: así sobrevive a un reinicio del
        asistente, queda auditada, y confirmarla reejecuta exactamente la misma
        operación en vez de una que el agente reconstruya de memoria.
        """
        return self.post("/api/pendientes/", {
            "metodo": metodo, "ruta": ruta, "cuerpo": cuerpo,
            "motivo": "AMBIGUEDAD", "descripcion": descripcion,
            "candidatos": candidatos, "campo": campo,
        })

    def resolver_cliente(self, texto: str) -> dict[str, Any]:
        return self._resolver_entidad("clientes", "cliente", texto)

    def resolver_proveedor(self, texto: str) -> dict[str, Any]:
        return self._resolver_entidad("proveedores", "proveedor", texto)

    def producto(self, codigo: int) -> dict[str, Any]:
        return self.get(f"/api/stock/{int(codigo)}")

    def cerrar(self) -> None:
        self._http.close()
