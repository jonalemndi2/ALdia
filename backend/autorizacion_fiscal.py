"""
autorizacion_fiscal.py - Codigo de un solo uso para que un agente pida un CAE.

EL PROBLEMA
-----------
Pedir un CAE declara una venta ante ARCA y no tiene vuelta atras. Cuando lo pide
un administrador desde la WebUI, la confirmacion es un clic de una persona.
Cuando lo pide un asistente de IA, `confirmar=true` lo escribe el propio modelo:
si se equivoca de factura, o si alguien lo convence con un mensaje armado, la
"confirmacion" no frena nada.

LA SOLUCION
-----------
ALdia genera un codigo de 6 digitos, se lo manda a la PERSONA responsable por
un canal que el agente no lee (hoy Telegram, con el bot que se configure) y
guarda solo su hash. El agente tiene que pedirle el codigo al usuario y
reenviarlo. Asi la autorizacion sale de la persona y no del modelo.

El codigo:
  * vale para UNA factura y UN uso;
  * vence a los CODIGO_VIGENCIA_MINUTOS;
  * se invalida si la factura cambia (cliente o total) desde que se pidio;
  * admite CODIGO_MAX_INTENTOS intentos fallidos, despues hay que pedir otro.

LIMITE CONOCIDO: protege contra errores del modelo y contra instrucciones
inyectadas que llegan por el MCP. NO protege contra un agente que corre con el
mismo usuario del sistema operativo y tiene acceso a la terminal: ese puede leer
la base y las claves directamente. Para eso, el agente debe correr con otro
usuario del sistema o sin acceso a shell.

CONFIGURACION (variables de entorno)
------------------------------------
  ALDIA_EMISION_FISCAL_AGENTE=si     habilita que el rol agente pida CAE (apagado
                                     por defecto).
  ALDIA_TELEGRAM_BOT_TOKEN=...       bot con el que se envia el codigo.
  ALDIA_TELEGRAM_CHAT_ID=...         chat de la persona que autoriza.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session

from errores import ErrorDeNegocio
from dinero import a_pesos
from models import AutorizacionFiscal, Cliente, Factura
from tiempo import ahora_utc

CODIGO_VIGENCIA_MINUTOS = 10
CODIGO_MAX_INTENTOS = 5
TELEGRAM_TIMEOUT_SEGUNDOS = 10


def emision_del_agente_habilitada() -> bool:
    return os.getenv("ALDIA_EMISION_FISCAL_AGENTE", "no").strip().lower() == "si"


def _canal_telegram() -> tuple[str, str] | None:
    token = os.getenv("ALDIA_TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("ALDIA_TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        return token, chat
    return None


def canal_configurado() -> bool:
    return _canal_telegram() is not None


def _hash(codigo: str) -> str:
    # HMAC con la clave de la instalacion: el hash solo no alcanza para probar
    # el millon de codigos posibles fuera de linea.
    from security import SECRET_KEY
    return hmac.new(SECRET_KEY.encode(), codigo.encode(), hashlib.sha256).hexdigest()


def huella_de(factura: Factura) -> str:
    """Lo que el usuario aprobo: si cambia, el codigo deja de valer."""
    texto = f"{factura.facturanumero}|{factura.cliente}|{factura.total}|{factura.fecha}"
    return hashlib.sha256(texto.encode()).hexdigest()


def _importe(centavos) -> str:
    pesos = float(a_pesos(centavos or 0))
    return f"${pesos:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cliente(db: Session, factura: Factura) -> str:
    """Nombre y CUIT: con el CUIT solo, la persona no reconoce a quien factura."""
    ficha = db.query(Cliente).filter(Cliente.cuit == factura.cliente).first()
    nombre = getattr(ficha, "nombre", "") or ""
    return f"{nombre} ({factura.cliente})" if nombre else str(factura.cliente)


def _enviar_telegram(texto: str) -> None:
    canal = _canal_telegram()
    if canal is None:
        raise RuntimeError("canal no configurado")
    token, chat = canal
    r = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": texto},
        timeout=TELEGRAM_TIMEOUT_SEGUNDOS,
    )
    r.raise_for_status()


def emitir_codigo(db: Session, factura: Factura, solicitante: str) -> None:
    """Crea un codigo nuevo para la factura, lo envia y corta el pedido.

    Siempre termina en ErrorDeNegocio: el pedido sin codigo nunca emite.
    """
    if not canal_configurado():
        raise ErrorDeNegocio(
            "EMISION_FISCAL_DEL_AGENTE_DESHABILITADA",
            "No hay un canal configurado para enviar el codigo de autorizacion "
            "(ALDIA_TELEGRAM_BOT_TOKEN y ALDIA_TELEGRAM_CHAT_ID). Sin codigo, la "
            "emision fiscal la hace un administrador desde la WebUI.",
        )

    ahora = ahora_utc()
    # Un solo codigo vivo por factura: pedir otro invalida el anterior.
    (db.query(AutorizacionFiscal)
       .filter(AutorizacionFiscal.factura_numero == factura.facturanumero,
               AutorizacionFiscal.usado_en.is_(None))
       .update({AutorizacionFiscal.usado_en: ahora}, synchronize_session=False))

    codigo = f"{secrets.randbelow(1_000_000):06d}"
    db.add(AutorizacionFiscal(
        factura_numero=factura.facturanumero,
        codigo_hash=_hash(codigo),
        huella=huella_de(factura),
        solicitado_por=solicitante[:60],
        creado_en=ahora,
        vence_en=ahora + timedelta(minutes=CODIGO_VIGENCIA_MINUTOS),
        intentos=0,
    ))
    db.commit()

    texto = (
        f"ALdia - autorizacion fiscal\n"
        f"{solicitante} pide el CAE de la factura interna N° {factura.facturanumero}\n"
        f"Cliente: {_cliente(db, factura)}\n"
        f"Total: {_importe(factura.total)}\n"
        f"Fecha: {factura.fecha}\n\n"
        f"Codigo: {codigo}\n"
        f"Vence en {CODIGO_VIGENCIA_MINUTOS} minutos. Si no lo pediste vos, no lo compartas."
    )
    try:
        _enviar_telegram(texto)
    except Exception as exc:  # noqa: BLE001 - cualquier falla de red se informa igual
        raise ErrorDeNegocio(
            "AFIP_NO_DISPONIBLE",
            f"No se pudo enviar el codigo de autorizacion por Telegram ({type(exc).__name__}). "
            "No se emitio nada; reintentar mas tarde.",
        ) from None

    raise ErrorDeNegocio(
        "CODIGO_DE_AUTORIZACION_REQUERIDO",
        f"No se emitio nada todavia. Se envio un codigo de autorizacion por Telegram a la "
        f"persona responsable para la factura {factura.facturanumero} "
        f"({_cliente(db, factura)}, {_importe(factura.total)}). Pidale el codigo al usuario y "
        f"repita el pedido con codigo=<el codigo>. Vence en {CODIGO_VIGENCIA_MINUTOS} minutos.",
        numero=factura.facturanumero, cliente=_cliente(db, factura),
        total=_importe(factura.total), minutos=CODIGO_VIGENCIA_MINUTOS,
    )


def verificar_codigo(db: Session, factura: Factura, codigo: str) -> None:
    """Valida y CONSUME el codigo. Si algo no cierra, corta con ErrorDeNegocio."""
    ahora = ahora_utc()
    vigente = (db.query(AutorizacionFiscal)
                 .filter(AutorizacionFiscal.factura_numero == factura.facturanumero,
                         AutorizacionFiscal.usado_en.is_(None))
                 .order_by(AutorizacionFiscal.id.desc())
                 .first())

    def invalido(motivo: str):
        return ErrorDeNegocio(
            "CODIGO_DE_AUTORIZACION_INVALIDO",
            f"Codigo de autorizacion rechazado: {motivo}. No se emitio nada.",
            motivo=motivo,
        )

    if vigente is None:
        raise invalido("no hay un codigo pendiente para esta factura; repita el pedido sin codigo")
    if vigente.vence_en < ahora:
        vigente.usado_en = ahora
        db.commit()
        raise invalido("el codigo vencio; repita el pedido sin codigo para recibir otro")
    if vigente.huella != huella_de(factura):
        vigente.usado_en = ahora
        db.commit()
        raise invalido("la factura cambio desde que se pidio el codigo; pida uno nuevo")

    limpio = "".join(ch for ch in str(codigo) if ch.isdigit())
    if not hmac.compare_digest(vigente.codigo_hash, _hash(limpio)):
        vigente.intentos = (vigente.intentos or 0) + 1
        if vigente.intentos >= CODIGO_MAX_INTENTOS:
            vigente.usado_en = ahora
            db.commit()
            raise invalido("demasiados intentos fallidos; repita el pedido sin codigo para recibir otro")
        db.commit()
        restantes = CODIGO_MAX_INTENTOS - vigente.intentos
        raise invalido(f"el codigo no coincide (quedan {restantes} intentos)")

    vigente.usado_en = ahora
    db.commit()
