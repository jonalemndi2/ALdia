"""
secuencias.py - Numeracion de comprobantes: unica, correlativa y sin reuso.

EL PROBLEMA
===========
Seis routers (facturas, remitos, cobros, pagos, gastos, compras) calculaban el
numero del comprobante asi:

    ultimo = db.query(Factura).order_by(Factura.facturanumero.desc()).first()
    nuevo  = (ultimo.facturanumero + 1) if ultimo else 1

Eso falla de dos maneras distintas, y conviene separarlas porque tienen
gravedad muy distinta:

  (A) COLISION ENTRE TERMINALES -- falla ruidosa.
      Dos cajas facturando en el mismo segundo leen el mismo maximo y las dos
      calculan el mismo numero. Como `facturanumero` es PRIMARY KEY, la segunda
      no genera un duplicado: revienta con "UNIQUE constraint failed" y el
      cajero ve un error 500. La venta se PIERDE, pero al menos se nota.
      Medicion real contra este sistema, 12 facturas simultaneas:
      entraban 3, se perdian 9.

  (B) REUSO DE NUMERO -- falla SILENCIOSA, y la peor de las dos.
      `max+1` mira las filas que EXISTEN. Si se anula la ultima factura, el
      maximo baja y la siguiente factura sale con el numero de la anulada. Dos
      comprobantes distintos con el mismo numero fiscal, sin ningun error:
      la base no se queja porque el numero viejo ya no esta. Verificado: se
      emitio la N° 4, se anulo, y la siguiente factura tambien salio como N° 4.

QUE SE ELIGIO Y POR QUE
=======================
Las tres opciones sobre la mesa eran:

  1. AUTOINCREMENT de SQLite (dejar que el motor asigne el rowid).
     Resuelve (A) y, con la palabra clave AUTOINCREMENT, tambien (B). Pero:
     ata la numeracion fiscal al motor, obliga a recrear las tablas solo por
     esto, y sobre todo NO deja fijar el numero inicial. Al migrar desde el
     sistema viejo de VB6/Access la numeracion tiene que CONTINUAR donde estaba
     (si el comercio venia en la factura 8.451, la primera factura del sistema
     nuevo debe ser la 8.452, no la 1). Con AUTOINCREMENT eso se arregla
     insertando una fila falsa y borrandola, que es exactamente el tipo de
     truco que no se quiere en un sistema contable.

  2. TABLA DE SECUENCIAS (la elegida). Una fila por tipo de comprobante:

         UPDATE secuencias SET ultimo = ultimo + 1 WHERE tipo = 'factura'
         SELECT ultimo FROM secuencias WHERE tipo = 'factura'

     - Resuelve (B) por construccion: el contador NO mira las filas de la tabla
       de comprobantes, asi que anular una factura no lo hace retroceder.
     - Resuelve (A) porque el UPDATE corre dentro de la MISMA transaccion que el
       INSERT del comprobante, y esa transaccion se abre con `BEGIN IMMEDIATE`
       (ver database.py): el lock de escritura ya esta tomado cuando se lee el
       contador, asi que dos cajas se serializan en vez de leer lo mismo.
     - Conserva la correlatividad POR TIPO, que es el requisito fiscal: cada
       tipo tiene su propia fila y su propia serie.
     - El numero inicial es un dato editable, no un truco.
     - No depende de SQLite: el dia que esto se mude a PostgreSQL sigue andando.

  3. INSERT con reintento ante violacion de unicidad.
     Anda, pero convierte cada emision concurrente en varios intentos fallidos,
     no resuelve (B) en absoluto, y deja la logica de numeracion repartida en
     los seis routers otra vez. Se descarto.

POR QUE NO QUEDAN HUECOS
========================
El numero se reserva DENTRO de la transaccion del comprobante. Si la operacion
falla despues de pedir el numero (stock insuficiente, error de red, el usuario
cancela), el rollback deshace tambien el UPDATE del contador: el numero vuelve a
quedar disponible y la serie no se saltea nada. Esta es la diferencia con una
secuencia tipo PostgreSQL/Oracle, que es no-transaccional y si deja huecos.
El costo de esta eleccion es el que ya se paga igual: las emisiones concurrentes
se serializan. Para un comercio con unas pocas terminales es imperceptible.

ARRANQUE EN UNA BASE QUE YA TIENE COMPROBANTES
==============================================
La primera vez que se pide un numero de un tipo, el contador se siembra con el
maximo que YA existe en la tabla correspondiente. Asi una instalacion en marcha
sigue numerando donde estaba, sin que el usuario tenga que configurar nada
(requisito: el sistema arranca con doble clic).
"""
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models import (
    Cobro, Factura, FacturaProveedor, GastoFactura, NCP, Pago, Remito, Secuencia,
)

# tipo -> (modelo, columna que lleva el numero)
#
# Cada entrada es una SERIE INDEPENDIENTE: la factura 15 y el remito 15 conviven
# sin problema, que es justamente la correlatividad "por tipo de comprobante".
COMPROBANTES = {
    "factura": (Factura, Factura.facturanumero),
    "remito": (Remito, Remito.id),
    "cobro": (Cobro, Cobro.ordcobro),
    "pago": (Pago, Pago.ordpago),
    "gasto": (GastoFactura, GastoFactura.id),
    "compra": (FacturaProveedor, FacturaProveedor.id),
    "nota_credito_proveedor": (NCP, NCP.id),
}


def _sembrar(db: Session, tipo: str) -> int:
    """Valor inicial del contador: el maximo que ya existe en la tabla.

    Solo corre la PRIMERA vez que se usa un tipo. En una base nueva da 0; en una
    instalacion que ya venia facturando, deja la serie donde estaba.
    """
    modelo, columna = COMPROBANTES[tipo]
    maximo = db.query(func.coalesce(func.max(columna), 0)).scalar() or 0
    return int(maximo)


def siguiente_numero(db: Session, tipo: str) -> int:
    """Reserva y devuelve el proximo numero del tipo indicado.

    Se llama DENTRO de la transaccion que graba el comprobante: si esa
    transaccion se deshace, el numero vuelve a quedar libre.
    """
    if tipo not in COMPROBANTES:
        raise ValueError(
            f"Tipo de comprobante desconocido: {tipo!r}. "
            f"Tipos validos: {', '.join(sorted(COMPROBANTES))}"
        )

    # UPDATE ... RETURNING seria una sola ida y vuelta, pero requiere SQLite
    # 3.35+ y aca no hace falta: ya estamos dentro de una transaccion IMMEDIATE,
    # asi que nadie mas puede tocar la fila entre el UPDATE y el SELECT.
    afectadas = db.execute(
        text("UPDATE secuencias SET ultimo = ultimo + 1 WHERE tipo = :tipo"),
        {"tipo": tipo},
    ).rowcount

    if not afectadas:
        # Primer uso de este tipo en esta base: se siembra desde lo ya existente.
        inicial = _sembrar(db, tipo) + 1
        db.execute(
            text("INSERT INTO secuencias (tipo, ultimo) VALUES (:tipo, :ultimo)"),
            {"tipo": tipo, "ultimo": inicial},
        )
        return inicial

    return int(
        db.execute(
            text("SELECT ultimo FROM secuencias WHERE tipo = :tipo"), {"tipo": tipo}
        ).scalar()
    )


def estado(db: Session) -> list[dict]:
    """Foto de todos los contadores, para diagnostico y para el panel de estado.

    Compara el contador con el maximo real de cada tabla. Que el contador este
    ADELANTE del maximo es normal y esperable (hubo anulaciones): significa
    justamente que no se van a reusar numeros. Que este ATRAS seria un problema.
    """
    guardados = {s.tipo: s.ultimo for s in db.query(Secuencia).all()}
    salida = []
    for tipo in sorted(COMPROBANTES):
        maximo = _sembrar(db, tipo)
        contador = guardados.get(tipo)
        salida.append({
            "tipo": tipo,
            "contador": contador,
            "maximo_en_tabla": maximo,
            "inicializado": contador is not None,
            # El unico caso que hay que mirar: el contador quedo por detras de
            # los comprobantes ya emitidos y volveria a repetir numeros.
            "atrasado": contador is not None and contador < maximo,
        })
    return salida
