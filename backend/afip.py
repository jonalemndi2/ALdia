"""
afip.py - Cliente de los Web Services de Factura Electronica de AFIP (Argentina).

Implementa el circuito REAL, sin simulaciones:

  WSAA  (Web Service de Autenticacion y Autorizacion)
        Arma el <loginTicketRequest>, lo firma en CMS/PKCS#7 con el certificado
        X.509 del contribuyente y su clave privada, lo envia al WSAA y obtiene
        el Ticket de Acceso (token + sign). El TA dura 12 horas y AFIP RECHAZA
        pedir uno nuevo mientras haya otro vigente, asi que se cachea en disco.

  WSFEv1 (Facturacion Electronica, RG 4291)
        FECAESolicitar, FECompUltimoAutorizado, FEParamGetTiposCbte,
        FEParamGetTiposIva y FEDummy.

REGLAS QUE ESTE MODULO NO ROMPE NUNCA:

  * No inventa CAE. Si AFIP no responde, o responde con Errors/Observaciones,
    se propaga como AfipError con el mensaje de AFIP traducido. Un rechazo
    JAMAS se devuelve como exito.
  * No arranca solo. Si no hay certificado configurado, `cargar_config()`
    devuelve `configurado=False` y los endpoints contestan "AFIP no configurado".
  * El certificado y la clave privada viven FUERA del repositorio (por defecto
    en <raiz>/certificados/, carpeta ignorada por git).

Dependencias: zeep (SOAP) y cryptography (firma CMS). Se importan de forma
diferida a proposito: si faltan, el resto del sistema tiene que seguir
arrancando con doble clic igual que siempre.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ─────────────────────────────────────────────────────────────
# Rutas y constantes
# ─────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ_PROYECTO = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Carpeta por defecto de los certificados. Esta en .gitignore (certificados/)
# justamente para que la identidad fiscal del comercio no llegue a GitHub.
DIR_CERTIFICADOS = os.path.join(RAIZ_PROYECTO, "certificados")
CERT_POR_DEFECTO = os.path.join(DIR_CERTIFICADOS, "afip.crt")
CLAVE_POR_DEFECTO = os.path.join(DIR_CERTIFICADOS, "afip.key")

SERVICIO_WSFE = "wsfe"

ENTORNOS = {
    "homologacion": {
        "wsaa": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
        "wsfe": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx",
    },
    "produccion": {
        "wsaa": "https://wsaa.afip.gov.ar/ws/services/LoginCms",
        "wsfe": "https://servicios1.afip.gov.ar/wsfev1/service.asmx",
    },
}

# Huso de Argentina. AFIP valida generationTime/expirationTime del ticket.
TZ_AR = timezone(timedelta(hours=-3))

# Alicuota de IVA -> Id de la tabla FEParamGetTiposIva de AFIP.
IVA_ID_POR_ALICUOTA = {
    0.0: 3,
    10.5: 4,
    21.0: 5,
    27.0: 6,
    5.0: 8,
    2.5: 9,
}

# Comprobantes que emitimos desde este sistema (FEParamGetTiposCbte trae la
# tabla completa; esto es solo para poder describirlos sin llamar a AFIP).
TIPOS_COMPROBANTE = {
    1: "Factura A",
    2: "Nota de Débito A",
    3: "Nota de Crédito A",
    6: "Factura B",
    7: "Nota de Débito B",
    8: "Nota de Crédito B",
    11: "Factura C",
    12: "Nota de Débito C",
    13: "Nota de Crédito C",
}

# Comprobantes clase C (monotributo): no discriminan IVA.
TIPOS_CLASE_C = {11, 12, 13}
# Notas de credito: los importes van en positivo, el signo lo da el tipo.
TIPOS_NOTA_CREDITO = {3, 8, 13}

TIMEOUT_SEGUNDOS = 30


class AfipError(Exception):
    """Error de la integracion con AFIP, con mensaje ya legible en castellano.

    `codigos` lleva los codigos de AFIP cuando los hubo, para poder buscarlos
    en la documentacion oficial.
    """

    def __init__(self, mensaje: str, codigos: Optional[list] = None, detalle: str = ""):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigos = codigos or []
        self.detalle = detalle


class AfipNoConfigurado(AfipError):
    """La integracion no esta habilitada o le falta configuracion."""


class AfipRechazo(AfipError):
    """AFIP contesto y RECHAZO el comprobante.

    Se distingue de un error de red, de certificado o de autenticacion: acá AFIP
    miró el comprobante y no lo autorizó, asi que el rechazo se guarda en la
    factura. Los otros errores no cambian el estado fiscal de nada.
    """


# ─────────────────────────────────────────────────────────────
# 1. Configuracion (entorno -> tabla configuracion -> valores por defecto)
# ─────────────────────────────────────────────────────────────

@dataclass
class AfipConfig:
    habilitado: bool = False
    entorno: str = "homologacion"
    cert_path: str = CERT_POR_DEFECTO
    key_path: str = CLAVE_POR_DEFECTO
    cuit: str = ""
    punto_venta: int = 1
    tipo_comprobante: int = 1
    problemas: list = field(default_factory=list)

    @property
    def configurado(self) -> bool:
        return not self.problemas

    @property
    def url_wsaa(self) -> str:
        return ENTORNOS[self.entorno]["wsaa"]

    @property
    def url_wsfe(self) -> str:
        return ENTORNOS[self.entorno]["wsfe"]


def _valor(env_key: str, db_key: str, db_valores: dict, defecto: str = "") -> str:
    """Prioridad: variable de entorno > tabla `configuracion` > valor por defecto."""
    desde_env = os.getenv(env_key)
    if desde_env is not None and desde_env.strip():
        return desde_env.strip()
    desde_db = (db_valores or {}).get(db_key)
    if desde_db is not None and str(desde_db).strip():
        return str(desde_db).strip()
    return defecto


def _es_si(valor: str) -> bool:
    return str(valor).strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def cargar_config(db=None) -> AfipConfig:
    """Arma la configuracion efectiva de AFIP.

    `db` es una sesion SQLAlchemy opcional: si viene, se leen tambien las claves
    de la tabla `configuracion`. La integracion esta DESHABILITADA por defecto,
    de modo que el sistema sigue arrancando con doble clic sin configurar nada.
    """
    db_valores: dict = {}
    if db is not None:
        try:
            from models import Configuracion
            db_valores = {c.clave: c.valor for c in db.query(Configuracion).all()}
        except Exception:
            db_valores = {}

    entorno = _valor("AFIP_ENTORNO", "afip_entorno", db_valores, "homologacion").lower()
    if entorno not in ENTORNOS:
        entorno = "homologacion"

    cfg = AfipConfig(
        habilitado=_es_si(_valor("AFIP_HABILITADO", "afip_habilitado", db_valores, "no")),
        entorno=entorno,
        cert_path=_valor("AFIP_CERT", "afip_cert", db_valores, CERT_POR_DEFECTO),
        key_path=_valor("AFIP_CLAVE", "afip_clave", db_valores, CLAVE_POR_DEFECTO),
        cuit=re.sub(r"[^0-9]", "", _valor("AFIP_CUIT", "afip_cuit", db_valores, "")
                    or _valor("", "negocio_cuit", db_valores, "")),
        punto_venta=_a_entero(
            _valor("AFIP_PUNTO_VENTA", "afip_punto_venta", db_valores, "")
            or _valor("", "negocio_punto_venta", db_valores, "1"), 1),
        tipo_comprobante=_a_entero(
            _valor("AFIP_TIPO_COMPROBANTE", "afip_tipo_comprobante", db_valores, "1"), 1),
    )

    # Diagnostico: que falta para poder facturar. Se muestra tal cual en /estado.
    problemas = []
    if not cfg.cuit:
        problemas.append(
            "Falta el CUIT del emisor (variable AFIP_CUIT o clave 'afip_cuit' en Configuración).")
    else:
        try:
            from schemas import validar_cuit  # reutiliza el validador con digito verificador
            cfg.cuit = validar_cuit(cfg.cuit)
        except Exception as exc:
            problemas.append(f"CUIT del emisor inválido: {exc}")
    if not os.path.exists(cfg.cert_path):
        problemas.append(f"No se encuentra el certificado en: {cfg.cert_path}")
    if not os.path.exists(cfg.key_path):
        problemas.append(f"No se encuentra la clave privada en: {cfg.key_path}")
    if cfg.punto_venta <= 0:
        problemas.append("El punto de venta debe ser un número mayor a cero.")
    cfg.problemas = problemas
    return cfg


def _a_entero(valor: Any, defecto: int) -> int:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return defecto


def exigir_operativa(cfg: AfipConfig) -> None:
    """Corta la operacion si AFIP no esta habilitado o le falta configuracion."""
    if not cfg.habilitado:
        raise AfipNoConfigurado(
            "AFIP no configurado: la facturación electrónica está deshabilitada. "
            "Actívela con AFIP_HABILITADO=si (o la clave 'afip_habilitado' en Configuración) "
            "después de cargar el certificado."
        )
    if cfg.problemas:
        raise AfipNoConfigurado(
            "AFIP no configurado: " + " ".join(cfg.problemas)
        )


# ─────────────────────────────────────────────────────────────
# 2. Certificado y firma CMS / PKCS#7
# ─────────────────────────────────────────────────────────────

def _importar_cryptography():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.serialization import pkcs7
        return x509, hashes, serialization, pkcs7
    except ImportError as exc:  # pragma: no cover - depende de la instalacion
        raise AfipError(
            "Falta la librería 'cryptography' para firmar el pedido a AFIP. "
            "Ejecute instalar.bat o: pip install -r backend/requirements.txt"
        ) from exc


def cargar_certificado(cfg: AfipConfig):
    """Devuelve (certificado_x509, clave_privada) leidos del disco.

    Acepta el certificado en PEM (lo habitual, es lo que descarga AFIP) o DER,
    y la clave privada en PEM sin contrasena.
    """
    x509, _hashes, serialization, _pkcs7 = _importar_cryptography()

    try:
        with open(cfg.cert_path, "rb") as fh:
            datos_cert = fh.read()
    except OSError as exc:
        raise AfipError(f"No se pudo leer el certificado ({cfg.cert_path}): {exc}") from exc
    try:
        with open(cfg.key_path, "rb") as fh:
            datos_key = fh.read()
    except OSError as exc:
        raise AfipError(f"No se pudo leer la clave privada ({cfg.key_path}): {exc}") from exc

    try:
        cert = (x509.load_pem_x509_certificate(datos_cert)
                if b"-----BEGIN" in datos_cert
                else x509.load_der_x509_certificate(datos_cert))
    except Exception as exc:
        raise AfipError(
            f"El certificado {cfg.cert_path} no es un X.509 válido (PEM o DER): {exc}"
        ) from exc

    try:
        clave = serialization.load_pem_private_key(datos_key, password=None)
    except TypeError as exc:
        raise AfipError(
            "La clave privada está protegida con contraseña y AFIP requiere firmarla "
            "sin intervención. Genere la clave sin passphrase."
        ) from exc
    except Exception as exc:
        raise AfipError(
            f"No se pudo leer la clave privada {cfg.key_path}: {exc}"
        ) from exc

    vence = _vencimiento_cert(cert)
    if vence and vence < datetime.now(timezone.utc):
        raise AfipError(
            f"El certificado de AFIP venció el {vence.date().isoformat()}. "
            "Hay que generar uno nuevo desde el sitio de AFIP (Administración de Certificados Digitales)."
        )
    return cert, clave


def _vencimiento_cert(cert) -> Optional[datetime]:
    """Fecha de vencimiento del certificado, en UTC (compatible con varias versiones)."""
    valor = getattr(cert, "not_valid_after_utc", None)
    if valor is None:
        valor = getattr(cert, "not_valid_after", None)
        if valor is not None and valor.tzinfo is None:
            valor = valor.replace(tzinfo=timezone.utc)
    return valor


def info_certificado(cfg: AfipConfig) -> dict:
    """Datos legibles del certificado, para mostrar en pantalla."""
    cert, _clave = cargar_certificado(cfg)
    vence = _vencimiento_cert(cert)
    return {
        "sujeto": cert.subject.rfc4514_string(),
        "emisor": cert.issuer.rfc4514_string(),
        "numero_serie": str(cert.serial_number),
        "vence": vence.isoformat() if vence else None,
        "autofirmado": cert.subject == cert.issuer,
    }


def construir_login_ticket_request(servicio: str = SERVICIO_WSFE, ttl_minutos: int = 10) -> bytes:
    """XML <loginTicketRequest> que exige el WSAA.

    generationTime se pone unos minutos en el pasado y expirationTime unos
    minutos en el futuro para tolerar el desfasaje de reloj de la PC del
    comercio, que es la causa mas comun de rechazo del ticket.
    """
    ahora = datetime.now(TZ_AR)
    unique_id = int(time.time()) % 2_147_483_647
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<loginTicketRequest version="1.0">'
        "<header>"
        f"<uniqueId>{unique_id}</uniqueId>"
        f"<generationTime>{(ahora - timedelta(minutes=ttl_minutos)).isoformat()}</generationTime>"
        f"<expirationTime>{(ahora + timedelta(minutes=ttl_minutos)).isoformat()}</expirationTime>"
        "</header>"
        f"<service>{servicio}</service>"
        "</loginTicketRequest>"
    )
    return xml.encode("utf-8")


def firmar_cms(datos: bytes, cert, clave) -> str:
    """Firma `datos` en CMS/PKCS#7 adjunto (no detached) y lo devuelve en base64.

    Equivale a `openssl smime -sign -nodetach -outform DER | base64`, que es lo
    que espera el metodo loginCms del WSAA.
    """
    _x509, hashes, serialization, pkcs7 = _importar_cryptography()
    try:
        firmado = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(datos)
            .add_signer(cert, clave, hashes.SHA256())
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
        )
    except Exception as exc:
        raise AfipError(f"No se pudo firmar el pedido de ticket de acceso: {exc}") from exc
    return base64.b64encode(firmado).decode("ascii")


# ─────────────────────────────────────────────────────────────
# 3. WSAA: ticket de acceso, con cache en disco
# ─────────────────────────────────────────────────────────────

@dataclass
class TicketAcceso:
    token: str
    sign: str
    expiracion: datetime
    servicio: str = SERVICIO_WSFE
    desde_cache: bool = False

    def vigente(self, margen_minutos: int = 10) -> bool:
        return datetime.now(timezone.utc) < (self.expiracion - timedelta(minutes=margen_minutos))


_lock_ta = threading.Lock()


def _ruta_cache_ta(cfg: AfipConfig, servicio: str) -> str:
    # El prefijo .afip_ta esta en .gitignore: el TA es una credencial viva.
    return os.path.join(BASE_DIR, f".afip_ta_{cfg.entorno}_{cfg.cuit or 'sincuit'}_{servicio}.json")


def _leer_ta_cache(cfg: AfipConfig, servicio: str) -> Optional[TicketAcceso]:
    ruta = _ruta_cache_ta(cfg, servicio)
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
        ta = TicketAcceso(
            token=datos["token"],
            sign=datos["sign"],
            expiracion=datetime.fromisoformat(datos["expiracion"]),
            servicio=servicio,
            desde_cache=True,
        )
    except (OSError, KeyError, ValueError):
        return None
    return ta if ta.vigente() else None


def _guardar_ta_cache(cfg: AfipConfig, ta: TicketAcceso) -> None:
    ruta = _ruta_cache_ta(cfg, ta.servicio)
    try:
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump({
                "token": ta.token,
                "sign": ta.sign,
                "expiracion": ta.expiracion.isoformat(),
                "servicio": ta.servicio,
                "entorno": cfg.entorno,
                "cuit": cfg.cuit,
            }, fh)
        try:
            import stat
            os.chmod(ruta, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except OSError:
        # Sin cache el sistema sigue funcionando, pero AFIP puede rechazar el
        # proximo pedido por tener un TA vigente. Se avisa por consola.
        print("[AFIP] AVISO: no se pudo guardar el ticket de acceso en disco.")


def parsear_login_ticket_response(xml_texto: str, servicio: str = SERVICIO_WSFE) -> TicketAcceso:
    """Extrae token, sign y expiracion del <loginTicketResponse> del WSAA."""
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError as exc:
        raise AfipError(
            "La respuesta del WSAA de AFIP no es un XML válido; no se puede obtener el "
            "ticket de acceso.", detalle=str(xml_texto)[:500]
        ) from exc

    token = raiz.findtext(".//credentials/token")
    sign = raiz.findtext(".//credentials/sign")
    expira = raiz.findtext(".//header/expirationTime")
    if not token or not sign:
        raise AfipError(
            "El WSAA de AFIP no devolvió token/sign en el ticket de acceso.",
            detalle=str(xml_texto)[:500],
        )
    try:
        expiracion = datetime.fromisoformat(expira) if expira else datetime.now(timezone.utc) + timedelta(hours=11)
        if expiracion.tzinfo is None:
            expiracion = expiracion.replace(tzinfo=TZ_AR)
        expiracion = expiracion.astimezone(timezone.utc)
    except ValueError:
        expiracion = datetime.now(timezone.utc) + timedelta(hours=11)
    return TicketAcceso(token=token, sign=sign, expiracion=expiracion, servicio=servicio)


# Mensajes tipicos del WSAA traducidos a algo accionable.
_ERRORES_WSAA = [
    ("ya posee un TA valido",
     "AFIP informa que ya existe un ticket de acceso vigente para este certificado. "
     "Espere unos minutos o reutilice el ticket cacheado (backend/.afip_ta_*.json)."),
    ("cms.sign.invalid",
     "AFIP rechazó la firma del pedido (CMS inválido). Verifique que el certificado y la "
     "clave privada sean el par correcto."),
    ("cms.cert.untrusted",
     "AFIP rechazó el certificado: no fue emitido por una autoridad certificante de AFIP. "
     "Hay que generar el certificado desde el sitio de AFIP (no sirve uno autofirmado)."),
    ("no es de confianza",
     "AFIP rechazó el certificado: no fue emitido por una autoridad certificante de AFIP. "
     "Hay que generar el certificado desde el sitio de AFIP (no sirve uno autofirmado)."),
    ("cms.cert.notFound",
     "AFIP no reconoce el certificado enviado. Verifique que sea el que descargó del sitio de AFIP."),
    ("cms.cert.expired",
     "El certificado enviado está vencido. Genere uno nuevo en AFIP."),
    ("cms.cert.notauthorized",
     "El certificado no está autorizado a usar este servicio. En AFIP hay que asociar el "
     "certificado (Alias) al servicio 'Facturación Electrónica' en Administrador de Relaciones."),
    ("wsn.unauthorizedaccess",
     "El certificado no está habilitado para el servicio wsfe. Falta darle la relación en "
     "'Administrador de Relaciones de Clave Fiscal'."),
    ("certificado no emitido",
     "AFIP rechazó el certificado: no fue emitido por una autoridad certificante de AFIP."),
    ("computador no autorizado",
     "AFIP no reconoce este certificado como autorizado para el servicio solicitado."),
    ("El CEE no se encuentra",
     "AFIP no encuentra el certificado registrado (CEE). Verifique el CUIT y el alias del certificado."),
    ("xml.generationtime.invalid",
     "AFIP rechazó las fechas del ticket. Suele ser el reloj de la PC desincronizado: "
     "ajuste fecha y hora de Windows."),
    ("xml.expirationtime.invalid",
     "AFIP rechazó el vencimiento del pedido de ticket. Ajuste la fecha y hora de la PC."),
]


def _traducir_fault_wsaa(texto: str) -> str:
    bajo = (texto or "").lower()
    for patron, mensaje in _ERRORES_WSAA:
        if patron.lower() in bajo:
            return mensaje
    return f"AFIP (WSAA) rechazó el pedido de ticket de acceso: {texto}"


def _cliente_soap(url: str):
    """Cliente zeep contra el WSDL de `url`, con timeouts razonables."""
    try:
        import zeep
        from zeep.transports import Transport
    except ImportError as exc:  # pragma: no cover
        raise AfipError(
            "Falta la librería 'zeep' para hablar con los web services de AFIP. "
            "Ejecute instalar.bat o: pip install -r backend/requirements.txt"
        ) from exc
    transporte = Transport(timeout=TIMEOUT_SEGUNDOS, operation_timeout=TIMEOUT_SEGUNDOS)
    try:
        return zeep.Client(wsdl=url + "?WSDL", transport=transporte)
    except Exception as exc:
        raise AfipError(
            f"No se pudo contactar el servicio de AFIP en {url}. "
            f"Verifique la conexión a internet. Detalle: {exc}"
        ) from exc


_clientes_cache: dict = {}
_lock_clientes = threading.Lock()


def _cliente_wsfe(cfg: AfipConfig):
    """Cliente zeep del WSFEv1, cacheado por entorno (el WSDL pesa ~75 KB)."""
    with _lock_clientes:
        cli = _clientes_cache.get(cfg.entorno)
        if cli is None:
            cli = _cliente_soap(cfg.url_wsfe)
            _clientes_cache[cfg.entorno] = cli
        return cli


def obtener_ticket_acceso(cfg: AfipConfig, servicio: str = SERVICIO_WSFE,
                          forzar: bool = False) -> TicketAcceso:
    """Ticket de acceso vigente: del cache en disco, o pidiendolo al WSAA.

    AFIP rechaza pedir un TA nuevo mientras el anterior siga vigente, por eso el
    cache no es una optimizacion: es parte del protocolo.
    """
    exigir_operativa(cfg)
    with _lock_ta:
        if not forzar:
            cacheado = _leer_ta_cache(cfg, servicio)
            if cacheado:
                return cacheado

        cert, clave = cargar_certificado(cfg)
        pedido = construir_login_ticket_request(servicio)
        cms = firmar_cms(pedido, cert, clave)

        cliente = _cliente_soap(cfg.url_wsaa)
        try:
            respuesta = cliente.service.loginCms(cms)
        except Exception as exc:
            texto = _texto_de_excepcion(exc)
            raise AfipError(_traducir_fault_wsaa(texto), detalle=texto) from exc

        ta = parsear_login_ticket_response(respuesta, servicio)
        _guardar_ta_cache(cfg, ta)
        return ta


def _texto_de_excepcion(exc: Exception) -> str:
    """Texto util de una excepcion de zeep (Fault trae message/detail aparte)."""
    partes = [str(exc)]
    mensaje = getattr(exc, "message", None)
    if mensaje and str(mensaje) not in partes:
        partes.append(str(mensaje))
    detalle = getattr(exc, "detail", None)
    if detalle is not None:
        try:
            partes.append(ET.tostring(detalle, encoding="unicode"))
        except Exception:
            partes.append(str(detalle))
    return " | ".join(p for p in partes if p)


# ─────────────────────────────────────────────────────────────
# 4. WSFEv1
# ─────────────────────────────────────────────────────────────

def _auth(cfg: AfipConfig) -> dict:
    ta = obtener_ticket_acceso(cfg)
    return {"Token": ta.token, "Sign": ta.sign, "Cuit": int(cfg.cuit)}


def _a_dict(objeto) -> Any:
    """Convierte la respuesta de zeep en estructuras Python simples."""
    try:
        from zeep.helpers import serialize_object
        return serialize_object(objeto, dict)
    except Exception:
        return objeto


def _errores_de(respuesta) -> list:
    """[(codigo, mensaje)] de la seccion Errors de una respuesta del WSFEv1."""
    salida = []
    errores = getattr(respuesta, "Errors", None)
    if errores is None:
        return salida
    lista = getattr(errores, "Err", None) or []
    for err in lista:
        salida.append((getattr(err, "Code", None), (getattr(err, "Msg", "") or "").strip()))
    return salida


def _eventos_de(respuesta) -> list:
    salida = []
    eventos = getattr(respuesta, "Events", None)
    if eventos is None:
        return salida
    for ev in (getattr(eventos, "Evt", None) or []):
        salida.append((getattr(ev, "Code", None), (getattr(ev, "Msg", "") or "").strip()))
    return salida


def _explicar(codigo, mensaje: str) -> str:
    """Agrega contexto a los errores mas comunes del WSFEv1."""
    ayudas = {
        600: "El token de acceso no es válido o venció: se va a renovar en el próximo intento.",
        601: "El CUIT del token no coincide con el CUIT del emisor configurado.",
        602: "Faltan datos obligatorios en el comprobante.",
        10015: "El punto de venta no está habilitado para factura electrónica en AFIP.",
        10016: "El número de comprobante no es correlativo: hay un salto respecto del último autorizado.",
        10017: "La fecha del comprobante está fuera del rango permitido (±5 días para productos).",
        10018: "El importe total no coincide con la suma de neto + IVA + tributos.",
        10019: "El tipo de comprobante no admite esa condición de IVA del receptor.",
        10048: "El punto de venta informado no existe o no está dado de alta en AFIP.",
    }
    extra = ayudas.get(codigo)
    base = f"[{codigo}] {mensaje}" if codigo is not None else mensaje
    # Sin caracteres fuera de cp1252: estos mensajes tambien se imprimen en la
    # consola de Windows del comercio.
    return f"{base} -- {extra}" if extra else base


def _fallar_si_hay_errores(respuesta, contexto: str, clase=AfipError) -> None:
    errores = _errores_de(respuesta)
    if errores:
        detalle = "; ".join(_explicar(c, m) for c, m in errores)
        raise clase(
            f"AFIP rechazó {contexto}: {detalle}",
            codigos=[c for c, _ in errores],
            detalle=detalle,
        )


def _llamar(cfg: AfipConfig, nombre: str, **kwargs):
    """Invoca una operacion del WSFEv1 traduciendo los errores de transporte."""
    cliente = _cliente_wsfe(cfg)
    operacion = getattr(cliente.service, nombre)
    try:
        return operacion(**kwargs)
    except AfipError:
        raise
    except Exception as exc:
        texto = _texto_de_excepcion(exc)
        raise AfipError(
            f"Falló la llamada {nombre} al WSFEv1 de AFIP ({cfg.entorno}): {texto}",
            detalle=texto,
        ) from exc


def fe_dummy(cfg: AfipConfig) -> dict:
    """FEDummy: estado de los servidores de AFIP. No requiere ticket de acceso."""
    respuesta = _llamar(cfg, "FEDummy")
    return {
        "AppServer": getattr(respuesta, "AppServer", None),
        "DbServer": getattr(respuesta, "DbServer", None),
        "AuthServer": getattr(respuesta, "AuthServer", None),
    }


def fe_comp_ultimo_autorizado(cfg: AfipConfig, punto_venta: int, tipo_comprobante: int) -> int:
    """FECompUltimoAutorizado: ultimo numero autorizado para (punto de venta, tipo)."""
    exigir_operativa(cfg)
    respuesta = _llamar(
        cfg, "FECompUltimoAutorizado",
        Auth=_auth(cfg), PtoVta=int(punto_venta), CbteTipo=int(tipo_comprobante),
    )
    _fallar_si_hay_errores(respuesta, "la consulta del último comprobante autorizado")
    return int(getattr(respuesta, "CbteNro", 0) or 0)


def fe_param_tipos_cbte(cfg: AfipConfig) -> list:
    """FEParamGetTiposCbte: tabla oficial de tipos de comprobante."""
    exigir_operativa(cfg)
    respuesta = _llamar(cfg, "FEParamGetTiposCbte", Auth=_auth(cfg))
    _fallar_si_hay_errores(respuesta, "la consulta de tipos de comprobante")
    datos = _a_dict(getattr(respuesta, "ResultGet", None)) or {}
    items = datos.get("CbteTipo") if isinstance(datos, dict) else None
    return [
        {
            "id": int(i.get("Id")),
            "descripcion": (i.get("Desc") or "").strip(),
            "vigente_desde": i.get("FchDesde"),
            "vigente_hasta": i.get("FchHasta"),
        }
        for i in (items or [])
    ]


def fe_param_tipos_iva(cfg: AfipConfig) -> list:
    """FEParamGetTiposIva: tabla oficial de alicuotas de IVA."""
    exigir_operativa(cfg)
    respuesta = _llamar(cfg, "FEParamGetTiposIva", Auth=_auth(cfg))
    _fallar_si_hay_errores(respuesta, "la consulta de alícuotas de IVA")
    datos = _a_dict(getattr(respuesta, "ResultGet", None)) or {}
    items = datos.get("IvaTipo") if isinstance(datos, dict) else None
    return [
        {"id": int(i.get("Id")), "descripcion": (i.get("Desc") or "").strip()}
        for i in (items or [])
    ]


@dataclass
class ComprobanteAFIP:
    """Datos fiscales de un comprobante a autorizar."""
    punto_venta: int
    tipo_comprobante: int
    doc_tipo: int          # 80 = CUIT, 96 = DNI, 99 = Consumidor Final
    doc_nro: int
    fecha: str             # YYYYMMDD
    imp_neto: float
    imp_iva: float
    imp_total: float
    alicuotas: list        # [{"Id": 5, "BaseImp": 100.0, "Importe": 21.0}]
    concepto: int = 1      # 1 = Productos, 2 = Servicios, 3 = Productos y Servicios
    imp_tot_conc: float = 0.0
    imp_op_ex: float = 0.0
    imp_trib: float = 0.0
    moneda: str = "PES"
    cotizacion: float = 1.0


# Un pedido de CAE toma el numero siguiente al ultimo autorizado. Si dos pedidos
# corren a la vez se pisarian el numero, asi que se serializan en el proceso.
_lock_cae = threading.Lock()


def solicitar_cae(cfg: AfipConfig, comp: ComprobanteAFIP) -> dict:
    """FECAESolicitar: pide el CAE de un comprobante.

    Devuelve un dict con resultado ('A' aprobado, 'P' parcial, 'R' rechazado),
    cae, vencimiento, numero de comprobante y observaciones.

    Si AFIP responde con Errors, o con Resultado 'R', se lanza AfipError con el
    texto de AFIP: nunca se devuelve un CAE que AFIP no otorgó.
    """
    exigir_operativa(cfg)

    with _lock_cae:
        ultimo = fe_comp_ultimo_autorizado(cfg, comp.punto_venta, comp.tipo_comprobante)
        numero = ultimo + 1

        detalle = {
            "Concepto": int(comp.concepto),
            "DocTipo": int(comp.doc_tipo),
            "DocNro": int(comp.doc_nro),
            "CbteDesde": numero,
            "CbteHasta": numero,
            "CbteFch": comp.fecha,
            "ImpTotal": round(comp.imp_total, 2),
            "ImpTotConc": round(comp.imp_tot_conc, 2),
            "ImpNeto": round(comp.imp_neto, 2),
            "ImpOpEx": round(comp.imp_op_ex, 2),
            "ImpTrib": round(comp.imp_trib, 2),
            "ImpIVA": round(comp.imp_iva, 2),
            "MonId": comp.moneda,
            "MonCotiz": comp.cotizacion,
        }
        # Los comprobantes clase C (monotributo) no discriminan IVA: mandar el
        # array Iva en un comprobante C es motivo de rechazo de AFIP.
        if comp.tipo_comprobante not in TIPOS_CLASE_C and comp.alicuotas:
            detalle["Iva"] = {"AlicIva": comp.alicuotas}
        if comp.concepto in (2, 3):
            # Servicios: AFIP exige el periodo facturado y el vencimiento de pago.
            detalle["FchServDesde"] = comp.fecha
            detalle["FchServHasta"] = comp.fecha
            detalle["FchVtoPago"] = comp.fecha

        peticion = {
            "FeCabReq": {
                "CantReg": 1,
                "PtoVta": int(comp.punto_venta),
                "CbteTipo": int(comp.tipo_comprobante),
            },
            "FeDetReq": {"FECAEDetRequest": [detalle]},
        }

        respuesta = _llamar(cfg, "FECAESolicitar", Auth=_auth(cfg), FeCAEReq=peticion)

    # 1) Errores de nivel general (estructura, punto de venta, token...).
    #    AFIP contesto sobre este comprobante: es un rechazo, no un problema de red.
    _fallar_si_hay_errores(respuesta, "el pedido de CAE", clase=AfipRechazo)

    cabecera = getattr(respuesta, "FeCabResp", None)
    resultado = getattr(cabecera, "Resultado", None) if cabecera is not None else None

    detalles = getattr(getattr(respuesta, "FeDetResp", None), "FECAEDetResponse", None) or []
    det = detalles[0] if detalles else None

    observaciones = []
    if det is not None:
        obs = getattr(det, "Observaciones", None)
        for o in (getattr(obs, "Obs", None) or []):
            observaciones.append((getattr(o, "Code", None), (getattr(o, "Msg", "") or "").strip()))

    cae = (getattr(det, "CAE", None) or "").strip() if det is not None else ""
    vencimiento = (getattr(det, "CAEFchVto", None) or "").strip() if det is not None else ""
    resultado_detalle = getattr(det, "Resultado", None) if det is not None else None
    resultado_final = resultado_detalle or resultado

    texto_obs = "; ".join(_explicar(c, m) for c, m in observaciones)

    # 2) Rechazo del comprobante: AFIP no otorga CAE. Esto NO es un exito.
    if resultado_final == "R" or not cae:
        raise AfipRechazo(
            "AFIP RECHAZÓ el comprobante (no se emitió CAE)."
            + (f" Motivo: {texto_obs}" if texto_obs else " AFIP no informó motivo."),
            codigos=[c for c, _ in observaciones],
            detalle=texto_obs,
        )

    return {
        "resultado": resultado_final,            # 'A' aprobado, 'P' aprobado con observaciones
        "cae": cae,
        "cae_vencimiento": vencimiento,          # YYYYMMDD
        "numero_comprobante": int(getattr(det, "CbteDesde", numero) or numero),
        "punto_venta": int(comp.punto_venta),
        "tipo_comprobante": int(comp.tipo_comprobante),
        "observaciones": texto_obs,
        "eventos": "; ".join(f"[{c}] {m}" for c, m in _eventos_de(respuesta)),
        "entorno": cfg.entorno,
        "importe_total": round(comp.imp_total, 2),
    }


# ─────────────────────────────────────────────────────────────
# 5. Utilidades de importes
# ─────────────────────────────────────────────────────────────

def id_iva(alicuota: float) -> int:
    """Id de AFIP para una alicuota de IVA (21.0 -> 5)."""
    try:
        clave = round(float(alicuota), 2)
    except (TypeError, ValueError):
        raise AfipError(f"Alícuota de IVA inválida: {alicuota}")
    if clave not in IVA_ID_POR_ALICUOTA:
        validas = ", ".join(f"{a:g}%" for a in sorted(IVA_ID_POR_ALICUOTA))
        raise AfipError(
            f"AFIP no acepta la alícuota de IVA {clave:g}%. Válidas: {validas}"
        )
    return IVA_ID_POR_ALICUOTA[clave]


def fecha_afip(fecha_iso: str) -> str:
    """'2026-08-17' -> '20260817' (formato CbteFch del WSFEv1)."""
    if not fecha_iso:
        raise AfipError("El comprobante no tiene fecha: AFIP la exige.")
    limpio = str(fecha_iso).strip().replace("-", "").replace("/", "")
    if len(limpio) == 8 and limpio.isdigit():
        return limpio
    raise AfipError(f"Fecha de comprobante inválida para AFIP: {fecha_iso}")


def fecha_desde_afip(aaaammdd: str) -> str:
    """'20260827' -> '2026-08-27' para mostrar en pantalla."""
    texto = (aaaammdd or "").strip()
    if len(texto) == 8 and texto.isdigit():
        return f"{texto[0:4]}-{texto[4:6]}-{texto[6:8]}"
    return texto


# ═════════════════════════════════════════════════════════════
# Código QR del comprobante (RG 4892/2020)
#
# Desde 2021 TODO comprobante electrónico impreso debe llevar un QR con los
# datos fiscales. Sin el QR, el comprobante impreso NO cumple la normativa,
# aunque el CAE sea válido.
#
# El QR codifica una URL de AFIP con un JSON en base64:
#   https://www.afip.gob.ar/fe/qr/?p=<json en base64>
# ═════════════════════════════════════════════════════════════

URL_QR_AFIP = "https://www.afip.gob.ar/fe/qr/?p="

# Tipo de documento del receptor segun AFIP.
DOC_TIPO_CUIT = 80
DOC_TIPO_CONSUMIDOR_FINAL = 99


def datos_qr(
    *,
    fecha: str,
    cuit_emisor: str,
    punto_venta: int,
    tipo_comprobante: int,
    nro_comprobante: int,
    importe_total: float,
    cae: str,
    doc_tipo_receptor: int = DOC_TIPO_CUIT,
    nro_doc_receptor: str = "",
    moneda: str = "PES",
    cotizacion: float = 1,
) -> dict:
    """Arma el diccionario que exige la RG 4892 para el QR."""
    if not cae:
        raise AfipError("No se puede generar el QR: el comprobante no tiene CAE.")

    def _solo_digitos(v) -> int:
        limpio = "".join(ch for ch in str(v or "") if ch.isdigit())
        return int(limpio) if limpio else 0

    receptor = _solo_digitos(nro_doc_receptor)
    # Sin CUIT de receptor el comprobante es a consumidor final.
    tipo_doc = doc_tipo_receptor if receptor else DOC_TIPO_CONSUMIDOR_FINAL

    return {
        "ver": 1,
        "fecha": fecha,                              # YYYY-MM-DD
        "cuit": _solo_digitos(cuit_emisor),
        "ptoVta": int(punto_venta or 0),
        "tipoCmp": int(tipo_comprobante or 0),
        "nroCmp": int(nro_comprobante or 0),
        "importe": round(float(importe_total or 0), 2),
        "moneda": moneda,
        "ctz": float(cotizacion or 1),
        "tipoDocRec": tipo_doc,
        "nroDocRec": receptor,
        "tipoCodAut": "E",                           # E = CAE (A seria CAEA)
        "codAut": _solo_digitos(cae),
    }


def url_qr(datos: dict) -> str:
    """Devuelve la URL de AFIP que debe contener el QR."""
    import base64
    import json

    crudo = json.dumps(datos, separators=(",", ":"), ensure_ascii=False)
    codificado = base64.b64encode(crudo.encode("utf-8")).decode("ascii")
    return URL_QR_AFIP + codificado


def qr_svg(datos: dict, escala: int = 4) -> str:
    """Genera el QR como SVG embebible en el comprobante impreso.

    Se usa SVG (no PNG) para que se imprima nitido a cualquier tamano y para no
    depender de Pillow.
    """
    try:
        import segno
    except ImportError as exc:  # pragma: no cover
        raise AfipError(
            "Falta la libreria 'segno' para generar el QR fiscal. "
            "Instalela con: pip install segno"
        ) from exc

    import io

    qr = segno.make(url_qr(datos), error="m")
    buffer = io.BytesIO()   # el writer SVG de segno escribe bytes
    qr.save(buffer, kind="svg", scale=escala, border=2, xmldecl=False, svgns=True)
    return buffer.getvalue().decode("utf-8")


# ═════════════════════════════════════════════════════════════
# Que tipo de comprobante corresponde (A / B / C)
#
# Elegir mal el tipo hace que AFIP RECHACE el comprobante, asi que conviene
# derivarlo de la condicion frente al IVA en vez de dejarlo a mano.
#
# Regla general en Argentina:
#   - Emisor Monotributista o Exento -> siempre clase C.
#   - Emisor Responsable Inscripto:
#       receptor Responsable Inscripto            -> clase A (discrimina IVA)
#       cualquier otro (CF, monotributo, exento)  -> clase B (no discrimina)
# ═════════════════════════════════════════════════════════════

# Codigos AFIP por clase y naturaleza del comprobante.
COMPROBANTES_POR_CLASE = {
    "A": {"factura": 1, "nota_debito": 2, "nota_credito": 3},
    "B": {"factura": 6, "nota_debito": 7, "nota_credito": 8},
    "C": {"factura": 11, "nota_debito": 12, "nota_credito": 13},
}

# Condiciones del EMISOR que obligan a emitir clase C.
EMISOR_CLASE_C = {"monotributo", "exento", "no_responsable"}


def _normalizar_condicion(valor: str) -> str:
    """Acepta tanto la clave interna como el texto que se muestra en pantalla."""
    texto = (valor or "").strip().lower().replace(" ", "_")
    equivalencias = {
        "responsable_inscripto": "responsable_inscripto",
        "ri": "responsable_inscripto",
        "monotributo": "monotributo",
        "monotributista": "monotributo",
        "responsable_monotributo": "monotributo",
        "exento": "exento",
        "iva_sujeto_exento": "exento",
        "consumidor_final": "consumidor_final",
        "cf": "consumidor_final",
        "no_responsable": "no_responsable",
        "iva_no_alcanzado": "no_responsable",
    }
    return equivalencias.get(texto, texto)


def clase_comprobante(condicion_emisor: str, condicion_receptor: str) -> str:
    """Devuelve 'A', 'B' o 'C' segun las condiciones frente al IVA."""
    emisor = _normalizar_condicion(condicion_emisor)
    receptor = _normalizar_condicion(condicion_receptor)

    if emisor in EMISOR_CLASE_C:
        return "C"
    # Emisor responsable inscripto (o desconocido: se asume el caso mas comun).
    return "A" if receptor == "responsable_inscripto" else "B"


def tipo_comprobante_sugerido(
    condicion_emisor: str,
    condicion_receptor: str,
    naturaleza: str = "factura",
) -> int:
    """Codigo AFIP del comprobante que corresponde emitir.

    `naturaleza`: 'factura', 'nota_debito' o 'nota_credito'.
    """
    clase = clase_comprobante(condicion_emisor, condicion_receptor)
    codigos = COMPROBANTES_POR_CLASE[clase]
    if naturaleza not in codigos:
        raise AfipError(
            f"Naturaleza de comprobante desconocida: '{naturaleza}'. "
            f"Validas: {', '.join(codigos)}"
        )
    return codigos[naturaleza]
