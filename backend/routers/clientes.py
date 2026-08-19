"""
clientes.py - Router CRUD para Clientes
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from errores import ErrorDeNegocio
import direcciones
from paises import pais_configurado
from database import get_db
from migraciones import dependientes
from models import Cliente
from schemas import (ClienteCreate, ClienteUpdate, ClienteResponse,
                     CorreccionIdentificador)

router = APIRouter()


@router.get("/", response_model=List[ClienteResponse])
def get_clientes(search: str = None, db: Session = Depends(get_db)):
    """Obtener todos los clientes (con búsqueda opcional)"""
    query = db.query(Cliente)
    if search:
        query = query.filter(
            Cliente.nombre.ilike(f"%{search}%") |
            Cliente.cuit.ilike(f"%{search}%")
        )
    return query.all()


@router.get("/{cuit}", response_model=ClienteResponse)
def get_cliente(cuit: str, db: Session = Depends(get_db)):
    """Obtener un cliente por CUIT"""
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.post("/", response_model=ClienteResponse)
def create_cliente(cliente_data: ClienteCreate, db: Session = Depends(get_db)):
    """Crear nuevo cliente"""
    existing = db.query(Cliente).filter(Cliente.cuit == cliente_data.cuit).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un cliente con ese CUIT")
    
    new_cliente = Cliente(**cliente_data.model_dump())
    # Las columnas de direccion viejas y las internacionales tienen que decir lo
    # mismo mientras convivan. Ver backend/direcciones.py.
    direcciones.sincronizar(new_cliente, pais_configurado().codigo)
    db.add(new_cliente)
    db.commit()
    db.refresh(new_cliente)
    return new_cliente


@router.put("/{cuit}", response_model=ClienteResponse)
def update_cliente(cuit: str, cliente_data: ClienteUpdate, db: Session = Depends(get_db)):
    """Actualizar cliente"""
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    update_data = cliente_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(cliente, key, value)

    direcciones.sincronizar(cliente, pais_configurado().codigo)
    db.commit()
    db.refresh(cliente)
    return cliente


@router.delete("/{cuit}")
def delete_cliente(cuit: str, db: Session = Depends(get_db)):
    """Eliminar cliente"""
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Un maestro con movimientos NO se borra: su historico es lo que sostiene la
    # cuenta corriente, el libro de IVA y los comprobantes ya emitidos. Ahora eso
    # lo garantiza la base (clave foranea RESTRICT, ver models.py); este control
    # esta antes para poder decir QUE lo impide, en vez de dejar que el motor
    # devuelva un error ilegible.
    usos = dependientes(db, "clientes", cuit)
    if usos:
        detalle = ", ".join(f"{u['cantidad']} en {u['tabla']}" for u in usos)
        raise ErrorDeNegocio(
            "TIENE_MOVIMIENTOS",
            "No se puede eliminar el cliente porque tiene movimientos "
            f"registrados ({detalle}). Los comprobantes ya emitidos no se "
            "pueden dejar sin titular.",
            que="el cliente", detalle=detalle,
        )

    db.delete(cliente)
    db.commit()
    return {"message": "Cliente eliminado correctamente"}


@router.post("/{cuit}/identificacion", response_model=ClienteResponse)
def corregir_identificador(
    cuit: str,
    datos: CorreccionIdentificador,
    db: Session = Depends(get_db),
):
    """Corregir el identificador fiscal de un cliente que YA tiene movimientos.

    POR QUE ESTO EXISTE COMO ENDPOINT APARTE
    ----------------------------------------
    Antes era IMPOSIBLE. El CUIT era la clave primaria, asi que no se podia
    editar --el endpoint de actualizacion ni siquiera acepta el campo-- y borrar
    la ficha para volver a cargarla lo impide la integridad referencial en
    cuanto hay un comprobante emitido, con razon: una factura no puede quedar
    sin titular. Un cliente cargado con un digito de mas quedaba mal para
    siempre, y el unico arreglo era editar el archivo .db a mano.

    Ahora la ficha tiene identidad propia (`id`) y el identificador es un
    atributo. El cambio se propaga a facturas, remitos, cobros y pagos por
    ON UPDATE CASCADE, dentro de la misma transaccion.

    Se exige confirmacion textual a proposito: cambia un dato fiscal que ya
    figura en comprobantes emitidos. Para un agente eso tiene que ser una
    decision del usuario y no algo que deduzca solo (ver el codigo de error
    CONFIRMACION_REQUERIDA, cuya accion es "preguntar").
    """
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if not cliente:
        raise ErrorDeNegocio("CLIENTE_NO_EXISTE", f"No existe el cliente {cuit}",
                             identificador=cuit)

    nuevo = datos.tax_id
    if nuevo == cliente.cuit:
        raise ErrorDeNegocio(
            "DATOS_INVALIDOS",
            "El identificador nuevo es igual al actual: no hay nada que corregir.",
        )

    if db.query(Cliente).filter(Cliente.cuit == nuevo).first():
        raise ErrorDeNegocio(
            "YA_EXISTE", f"Ya hay otro cliente con el identificador {nuevo}."
        )

    if datos.confirmar.strip() != nuevo:
        arrastre = dependientes(db, "clientes", cliente.cuit)
        detalle = ", ".join(f"{u['cantidad']} en {u['tabla']}" for u in arrastre)
        raise ErrorDeNegocio(
            "CONFIRMACION_REQUERIDA",
            f"Esto cambia el identificador fiscal de '{cliente.nombre}' "
            f"({cliente.cuit} -> {nuevo}) en comprobantes YA emitidos"
            + (f": {detalle}. " if detalle else ". ")
            + f"Para confirmar, repita el valor nuevo en 'confirmar' "
            f"exactamente como {nuevo}.",
        )

    # Se mide ANTES: despues del cambio la consulta ya no encuentra nada con el
    # identificador viejo, justamente porque el cascade hizo su trabajo.
    arrastrados = dependientes(db, "clientes", cliente.cuit)

    cliente.cuit = nuevo
    db.commit()
    db.refresh(cliente)

    print(f"[clientes] identificador corregido: {cuit} -> {nuevo} "
          f"({cliente.nombre}); arrastro {arrastrados}; motivo: {datos.motivo or 's/d'}")
    return cliente
