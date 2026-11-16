import ast
import csv
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
from contextlib import closing, contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from calendar import monthrange


_ITERACIONES_HASH = 600_000
_ESQUEMA_HASH = "pbkdf2_sha256"
_MENSUALIDAD_INICIAL = os.environ.get("RIJO_MONTHLY_PRICE", "600")
_MONEDA_MENSUALIDAD = "DOP"


def _ruta_base_datos():
    ruta_configurada = os.environ.get("RIJO_DB_PATH")
    if ruta_configurada:
        return os.path.abspath(ruta_configurada)
    if getattr(sys, "frozen", False):
        carpeta = os.path.join(
            os.environ.get(
                "LOCALAPPDATA",
                os.path.join(os.path.expanduser("~"), "AppData", "Local"),
            ),
            "RijoExpress",
        )
        ruta = os.path.join(carpeta, "rijoexpress.db")
        os.makedirs(carpeta, exist_ok=True)
        if not os.path.exists(ruta):
            directorio_ejecutable = os.path.dirname(os.path.abspath(sys.executable))
            candidatos = (
                os.path.join(directorio_ejecutable, "rijoexpress.db"),
                os.path.join(os.path.dirname(directorio_ejecutable), "rijoexpress.db"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "rijoexpress.db"),
            )
            origen = next(
                (candidato for candidato in candidatos if os.path.isfile(candidato)),
                None,
            )
            if origen:
                with closing(sqlite3.connect(origen)) as base_origen:
                    with closing(sqlite3.connect(ruta)) as base_destino:
                        base_origen.backup(base_destino)
                        base_destino.commit()
        return ruta
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rijoexpress.db")


@contextmanager
def _conectar_base_datos():
    conexion = sqlite3.connect(_ruta_base_datos())
    try:
        conexion.execute("PRAGMA foreign_keys = ON")
        _asegurar_esquema(conexion)
        conexion.execute(
            "CREATE TABLE IF NOT EXISTS usuarios ("
            "id_usuario INTEGER PRIMARY KEY AUTOINCREMENT, nombre_usuario TEXT NOT NULL UNIQUE, "
            "contrasena TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'usuario', tenant_id INTEGER "
            "REFERENCES tenants(id), forzar_cambio_contrasena INTEGER NOT NULL DEFAULT 0, "
            "id_cliente TEXT)"
        )
        columnas_usuarios = {
            fila[1] for fila in conexion.execute("PRAGMA table_info(usuarios)")
        }
        if "tenant_id" not in columnas_usuarios:
            conexion.execute(
                "ALTER TABLE usuarios ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)"
            )
        if "forzar_cambio_contrasena" not in columnas_usuarios:
            conexion.execute(
                "ALTER TABLE usuarios ADD COLUMN forzar_cambio_contrasena INTEGER NOT NULL DEFAULT 0"
            )
        if "id_cliente" not in columnas_usuarios:
            conexion.execute("ALTER TABLE usuarios ADD COLUMN id_cliente TEXT")
        conexion.execute("UPDATE usuarios SET tenant_id=1 WHERE tenant_id IS NULL")
        conexion.execute(
            "CREATE INDEX IF NOT EXISTS idx_usuarios_tenant ON usuarios(tenant_id)"
        )
        conexion.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuario_cliente "
            "ON usuarios(tenant_id, id_cliente) WHERE rol='cliente'"
        )
        conexion.commit()
        with conexion:
            yield conexion
    finally:
        conexion.close()


def _crear_tabla_clientes(conexion):
    conexion.execute(
        "CREATE TABLE clientes ("
        "tenant_id INTEGER NOT NULL REFERENCES tenants(id), id_cliente TEXT NOT NULL, "
        "nombre TEXT NOT NULL, fecha_registro TEXT NOT NULL, codigo_acceso_hash TEXT, "
        "PRIMARY KEY (tenant_id, id_cliente))"
    )


def _crear_tabla_prestamos(conexion):
    conexion.execute(
        "CREATE TABLE prestamos ("
        "tenant_id INTEGER NOT NULL REFERENCES tenants(id), id_prestamo TEXT NOT NULL, "
        "id_cliente TEXT NOT NULL, monto REAL NOT NULL, tasa_interes REAL NOT NULL, "
        "fecha_inicio TEXT NOT NULL, fecha_vencimiento TEXT NOT NULL, "
        "tasa_mora REAL NOT NULL DEFAULT 0, saldo_pendiente REAL NOT NULL, "
        "pagos TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (tenant_id, id_prestamo), "
        "FOREIGN KEY (tenant_id, id_cliente) REFERENCES clientes(tenant_id, id_cliente))"
    )


def _migrar_tabla_clientes(conexion):
    columnas = conexion.execute("PRAGMA table_info(clientes)").fetchall()
    if not columnas:
        _crear_tabla_clientes(conexion)
        return
    clave_primaria = [
        fila[1] for fila in sorted(columnas, key=lambda fila: fila[5]) if fila[5]
    ]
    nombres = {fila[1] for fila in columnas}
    if "tenant_id" in nombres and clave_primaria == ["tenant_id", "id_cliente"]:
        if "codigo_acceso_hash" not in nombres:
            conexion.execute("ALTER TABLE clientes ADD COLUMN codigo_acceso_hash TEXT")
        return
    if conexion.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='clientes_saas_legacy'"
    ).fetchone():
        raise RuntimeError("Se encontró una tabla clientes_saas_legacy; revisa la migración antes de continuar.")

    conexion.execute("ALTER TABLE clientes RENAME TO clientes_saas_legacy")
    _crear_tabla_clientes(conexion)
    tenant = "COALESCE(tenant_id, 1)" if "tenant_id" in nombres else "1"
    conexion.execute(
        "INSERT INTO clientes (tenant_id, id_cliente, nombre, fecha_registro) "
        "SELECT {}, id_cliente, nombre, fecha_registro FROM clientes_saas_legacy".format(tenant)
    )
    conexion.execute("DROP TABLE clientes_saas_legacy")


def _migrar_tabla_prestamos(conexion):
    columnas = conexion.execute("PRAGMA table_info(prestamos)").fetchall()
    if not columnas:
        _crear_tabla_prestamos(conexion)
        return
    clave_primaria = [
        fila[1] for fila in sorted(columnas, key=lambda fila: fila[5]) if fila[5]
    ]
    nombres = {fila[1] for fila in columnas}
    if "tenant_id" in nombres and clave_primaria == ["tenant_id", "id_prestamo"]:
        return
    if conexion.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prestamos_saas_legacy'"
    ).fetchone():
        raise RuntimeError("Se encontró una tabla prestamos_saas_legacy; revisa la migración antes de continuar.")

    conexion.execute("ALTER TABLE prestamos RENAME TO prestamos_saas_legacy")
    _crear_tabla_prestamos(conexion)
    tenant = "COALESCE(tenant_id, 1)" if "tenant_id" in nombres else "1"
    tasa_mora = "tasa_mora" if "tasa_mora" in nombres else "0"
    pagos = "COALESCE(pagos, '[]')" if "pagos" in nombres else "'[]'"
    conexion.execute(
        "INSERT INTO prestamos (tenant_id, id_prestamo, id_cliente, monto, tasa_interes, "
        "fecha_inicio, fecha_vencimiento, tasa_mora, saldo_pendiente, pagos) "
        "SELECT {}, id_prestamo, id_cliente, monto, tasa_interes, fecha_inicio, "
        "fecha_vencimiento, {}, saldo_pendiente, {} FROM prestamos_saas_legacy".format(
            tenant, tasa_mora, pagos
        )
    )
    conexion.execute("DROP TABLE prestamos_saas_legacy")


def _asegurar_esquema(conexion):
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS tenants ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, "
        "creada_en TEXT NOT NULL, suscripcion_hasta TEXT, activo INTEGER NOT NULL DEFAULT 1, "
        "tipo TEXT NOT NULL DEFAULT 'cliente', mensualidad TEXT NOT NULL DEFAULT '600')"
    )
    columnas_tenants = {
        fila[1] for fila in conexion.execute("PRAGMA table_info(tenants)")
    }
    if "mensualidad" not in columnas_tenants:
        conexion.execute(
            "ALTER TABLE tenants ADD COLUMN mensualidad TEXT NOT NULL DEFAULT '600'"
        )
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS configuracion_plataforma ("
        "clave TEXT PRIMARY KEY, valor TEXT NOT NULL)"
    )
    config_default = conexion.execute(
        "INSERT OR IGNORE INTO configuracion_plataforma (clave, valor) VALUES ('mensualidad', ?)",
        (_MENSUALIDAD_INICIAL,),
    )
    if config_default.rowcount:
        conexion.execute(
            "UPDATE tenants SET mensualidad=? WHERE tipo='cliente'",
            (_MENSUALIDAD_INICIAL,),
        )
    conexion.execute(
        "INSERT OR IGNORE INTO tenants "
        "(id, nombre, creada_en, suscripcion_hasta, activo, tipo) "
        "VALUES (1, 'Rijo Express', date('now'), NULL, 1, 'plataforma')"
    )
    _migrar_tabla_clientes(conexion)
    _migrar_tabla_prestamos(conexion)
    conexion.execute(
        "CREATE INDEX IF NOT EXISTS idx_clientes_tenant ON clientes(tenant_id)"
    )
    conexion.execute(
        "CREATE INDEX IF NOT EXISTS idx_prestamos_tenant ON prestamos(tenant_id)"
    )
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS pagos_suscripcion ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER NOT NULL REFERENCES tenants(id), "
        "fecha_pago TEXT NOT NULL, monto TEXT NOT NULL, moneda TEXT NOT NULL, "
        "periodo_desde TEXT NOT NULL, periodo_hasta TEXT NOT NULL, registrado_por TEXT NOT NULL)"
    )
    conexion.execute(
        "CREATE INDEX IF NOT EXISTS idx_pagos_suscripcion_tenant "
        "ON pagos_suscripcion(tenant_id, fecha_pago)"
    )


class Cliente:
    def __init__(self, id_cliente, nombre, fecha_registro):
        self.id_cliente = id_cliente
        self.nombre = nombre
        self.fecha_registro = fecha_registro

    def to_dict(self):
        return {
            'id_cliente': self.id_cliente,
            'nombre': self.nombre,
            'fecha_registro': self.fecha_registro
        }

class Prestamo:
    def __init__(self, id_prestamo, id_cliente, monto, tasa_interes, fecha_inicio, fecha_vencimiento, tasa_mora=0):
        self.id_prestamo = id_prestamo
        self.id_cliente = id_cliente
        self.monto = monto
        self.tasa_interes = tasa_interes
        self.fecha_inicio = fecha_inicio
        self.fecha_vencimiento = fecha_vencimiento
        self.tasa_mora = tasa_mora
        self.saldo_pendiente = monto
        self.pagos = []  # Lista de diccionarios {'fecha': , 'monto': }

    def registrar_pago(self, fecha, monto):
        if monto > self.saldo_pendiente:
            raise ValueError("El monto del pago no puede exceder el saldo pendiente.")
        self.pagos.append({'fecha': fecha, 'monto': monto})
        self.saldo_pendiente -= monto

    def to_dict(self):
        return {
            'id_prestamo': self.id_prestamo,
            'id_cliente': self.id_cliente,
            'monto': self.monto,
            'tasa_interes': self.tasa_interes,
            'fecha_inicio': self.fecha_inicio,
            'fecha_vencimiento': self.fecha_vencimiento,
            'saldo_pendiente': self.saldo_pendiente,
            'pagos': self.pagos
        }

# Funciones para manejo de archivos CSV
def cargar_clientes():
    clientes = {}
    if os.path.exists('clientes.csv'):
        with open('clientes.csv', 'r', newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                clientes[row['id_cliente']] = Cliente(row['id_cliente'], row['nombre'], row['fecha_registro'])
    return clientes

def guardar_clientes(clientes):
    with open('clientes.csv', 'w', newline='') as file:
        fieldnames = ['id_cliente', 'nombre', 'fecha_registro']
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for cliente in clientes.values():
            writer.writerow(cliente.to_dict())

def cargar_prestamos():
    prestamos = {}
    if os.path.exists('prestamos.csv'):
        with open('prestamos.csv', 'r', newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                prestamo = Prestamo(
                    row['id_prestamo'],
                    row['id_cliente'],
                    float(row['monto']),
                    float(row['tasa_interes']),
                    row['fecha_inicio'],
                    row['fecha_vencimiento']
                )
                prestamo.saldo_pendiente = float(row['saldo_pendiente'])
                # Cargar pagos si existe
                if 'pagos' in row and row['pagos']:
                    prestamo.pagos = ast.literal_eval(row['pagos'])
                prestamos[row['id_prestamo']] = prestamo
    return prestamos

def guardar_prestamos(prestamos):
    with open('prestamos.csv', 'w', newline='') as file:
        fieldnames = ['id_prestamo', 'id_cliente', 'monto', 'tasa_interes', 'fecha_inicio', 'fecha_vencimiento', 'saldo_pendiente', 'pagos']
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for prestamo in prestamos.values():
            row = prestamo.to_dict()
            row['pagos'] = str(row['pagos'])  # Convertir lista a string
            writer.writerow(row)


def cargar_clientes_sql(tenant_id=1):
    with _conectar_base_datos() as conexion:
        filas = conexion.execute(
            "SELECT id_cliente, nombre, fecha_registro FROM clientes WHERE tenant_id=?",
            (tenant_id,),
        ).fetchall()
    return {
        fila[0]: Cliente(fila[0], fila[1], fila[2])
        for fila in filas
    }


def guardar_clientes_sql(clientes, tenant_id=1):
    with _conectar_base_datos() as conexion:
        conexion.executemany(
            "INSERT INTO clientes (tenant_id, id_cliente, nombre, fecha_registro) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(tenant_id, id_cliente) DO UPDATE SET "
            "nombre=excluded.nombre, fecha_registro=excluded.fecha_registro",
            [
                (tenant_id, cliente.id_cliente, cliente.nombre, cliente.fecha_registro)
                for cliente in clientes.values()
            ],
        )


def cargar_prestamos_sql(tenant_id=1):
    with _conectar_base_datos() as conexion:
        filas = conexion.execute(
            "SELECT id_prestamo, id_cliente, monto, tasa_interes, fecha_inicio, "
            "fecha_vencimiento, tasa_mora, saldo_pendiente, pagos FROM prestamos WHERE tenant_id=?",
            (tenant_id,),
        ).fetchall()

    prestamos = {}
    for fila in filas:
        prestamo = Prestamo(*fila[:6], tasa_mora=fila[6] or 0)
        prestamo.saldo_pendiente = float(fila[7])
        pagos = fila[8] or "[]"
        try:
            prestamo.pagos = json.loads(pagos)
        except json.JSONDecodeError:
            prestamo.pagos = ast.literal_eval(pagos)
        prestamos[prestamo.id_prestamo] = prestamo
    return prestamos


def guardar_prestamos_sql(prestamos, tenant_id=1):
    with _conectar_base_datos() as conexion:
        conexion.executemany(
            "INSERT INTO prestamos (tenant_id, id_prestamo, id_cliente, monto, tasa_interes, "
            "fecha_inicio, fecha_vencimiento, tasa_mora, saldo_pendiente, pagos) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_id, id_prestamo) DO UPDATE SET "
            "id_cliente=excluded.id_cliente, monto=excluded.monto, "
            "tasa_interes=excluded.tasa_interes, fecha_inicio=excluded.fecha_inicio, "
            "fecha_vencimiento=excluded.fecha_vencimiento, tasa_mora=excluded.tasa_mora, "
            "saldo_pendiente=excluded.saldo_pendiente, pagos=excluded.pagos",
            [
                (
                    tenant_id,
                    prestamo.id_prestamo,
                    prestamo.id_cliente,
                    prestamo.monto,
                    prestamo.tasa_interes,
                    prestamo.fecha_inicio,
                    prestamo.fecha_vencimiento,
                    prestamo.tasa_mora,
                    prestamo.saldo_pendiente,
                    json.dumps(prestamo.pagos, ensure_ascii=False),
                )
                for prestamo in prestamos.values()
            ],
        )


def obtener_usuario_autenticado(nombre_usuario, contrasena):
    with _conectar_base_datos() as conexion:
        fila = conexion.execute(
            "SELECT u.id_usuario, u.contrasena, u.rol, u.tenant_id, u.id_cliente, "
            "u.forzar_cambio_contrasena, t.nombre, t.tipo, t.activo, "
            "t.suscripcion_hasta, t.mensualidad "
            "FROM usuarios u JOIN tenants t ON t.id=u.tenant_id "
            "WHERE u.nombre_usuario=?",
            (nombre_usuario,),
        ).fetchone()
    if not fila or not _verificar_contrasena(contrasena, fila[1]):
        return None

    (
        id_usuario,
        hash_guardado,
        rol,
        tenant_id,
        id_cliente,
        forzar_cambio,
        nombre_empresa,
        tipo_tenant,
        activo,
        suscripcion_hasta,
        mensualidad,
    ) = fila
    if not hash_guardado.startswith(_ESQUEMA_HASH + "$"):
        with _conectar_base_datos() as conexion:
            conexion.execute(
                "UPDATE usuarios SET contrasena=? WHERE nombre_usuario=? AND contrasena=?",
                (_hash_contrasena(contrasena), nombre_usuario, hash_guardado),
            )
    return {
        "id_usuario": id_usuario,
        "rol": rol,
        "tenant_id": tenant_id,
        "id_cliente": id_cliente,
        "requiere_cambio_contrasena": bool(forzar_cambio),
        "nombre_empresa": nombre_empresa,
        "tipo_tenant": tipo_tenant,
        "activo": bool(activo),
        "suscripcion_hasta": suscripcion_hasta,
        "mensualidad": mensualidad,
    }


def verificar_usuario(nombre_usuario, contrasena):
    usuario = obtener_usuario_autenticado(nombre_usuario, contrasena)
    return usuario["rol"] if usuario else None


def _hash_contrasena(contrasena):
    sal = secrets.token_bytes(16)
    derivada = hashlib.pbkdf2_hmac(
        "sha256",
        contrasena.encode("utf-8"),
        sal,
        _ITERACIONES_HASH,
    )
    return "{}${}${}${}".format(
        _ESQUEMA_HASH,
        _ITERACIONES_HASH,
        sal.hex(),
        derivada.hex(),
    )


def _verificar_contrasena(contrasena, guardada):
    if not guardada.startswith(_ESQUEMA_HASH + "$"):
        return hmac.compare_digest(contrasena.encode("utf-8"), guardada.encode("utf-8"))

    try:
        esquema, iteraciones_texto, sal_hex, derivada_hex = guardada.split("$")
        iteraciones = int(iteraciones_texto)
        sal = bytes.fromhex(sal_hex)
        derivada_esperada = bytes.fromhex(derivada_hex)
    except (ValueError, TypeError):
        return False

    if (
        esquema != _ESQUEMA_HASH
        or not 100_000 <= iteraciones <= 1_000_000
        or len(sal) != 16
        or len(derivada_esperada) != 32
    ):
        return False

    derivada = hashlib.pbkdf2_hmac(
        "sha256",
        contrasena.encode("utf-8"),
        sal,
        iteraciones,
    )
    return hmac.compare_digest(derivada, derivada_esperada)


def agregar_usuario(nombre_usuario, contrasena, rol="usuario"):
    with _conectar_base_datos() as conexion:
        cursor = conexion.execute(
            "INSERT INTO usuarios (nombre_usuario, contrasena, rol, tenant_id) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(nombre_usuario) DO NOTHING",
            (nombre_usuario, _hash_contrasena(contrasena), rol),
        )
        return cursor.rowcount == 1


def crear_cuenta_prestamista(nombre, nombre_usuario, contrasena, suscripcion_hasta):
    return crear_cuenta_prestamista_con_mensualidad(
        nombre,
        nombre_usuario,
        contrasena,
        suscripcion_hasta,
        _MENSUALIDAD_INICIAL,
    )


def crear_cuenta_prestamista_con_mensualidad(
    nombre,
    nombre_usuario,
    contrasena,
    suscripcion_hasta,
    mensualidad,
):
    mensualidad = _normalizar_mensualidad(mensualidad)
    with _conectar_base_datos() as conexion:
        cursor = conexion.execute(
            "INSERT INTO tenants (nombre, creada_en, suscripcion_hasta, activo, tipo, mensualidad) "
            "VALUES (?, date('now'), ?, 1, 'cliente', ?)",
            (nombre, suscripcion_hasta, mensualidad),
        )
        tenant_id = cursor.lastrowid
        usuario = conexion.execute(
            "INSERT INTO usuarios (nombre_usuario, contrasena, rol, tenant_id) "
            "VALUES (?, ?, 'prestamista', ?) ON CONFLICT(nombre_usuario) DO NOTHING",
            (nombre_usuario, _hash_contrasena(contrasena), tenant_id),
        )
        if usuario.rowcount == 0:
            conexion.execute("DELETE FROM tenants WHERE id=?", (tenant_id,))
            return None
    return tenant_id


def _normalizar_mensualidad(monto):
    try:
        valor = Decimal(str(monto))
    except (InvalidOperation, ValueError):
        raise ValueError("La mensualidad debe ser un monto numérico válido.")
    if not valor.is_finite() or valor <= 0 or valor > Decimal("1000000000"):
        raise ValueError("La mensualidad debe ser mayor que cero y no superar 1,000,000,000.")
    return format(valor.quantize(Decimal("0.01")), "f")


def obtener_mensualidad_plataforma():
    with _conectar_base_datos() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion_plataforma WHERE clave='mensualidad'"
        ).fetchone()
    return fila[0] if fila else _MENSUALIDAD_INICIAL


def actualizar_mensualidad_plataforma(monto):
    mensualidad = _normalizar_mensualidad(monto)
    with _conectar_base_datos() as conexion:
        conexion.execute(
            "INSERT INTO configuracion_plataforma (clave, valor) VALUES ('mensualidad', ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (mensualidad,),
        )
        conexion.execute(
            "UPDATE tenants SET mensualidad=? WHERE tipo='cliente'",
            (mensualidad,),
        )
    return mensualidad


def obtener_cuentas_prestamistas():
    with _conectar_base_datos() as conexion:
        filas = conexion.execute(
            "SELECT t.id, u.id_usuario, t.nombre, u.nombre_usuario, t.creada_en, "
            "t.suscripcion_hasta, t.activo, t.mensualidad, COUNT(p.id), MAX(p.fecha_pago) "
            "FROM tenants t JOIN usuarios u ON u.tenant_id=t.id AND u.rol='prestamista' "
            "LEFT JOIN pagos_suscripcion p ON p.tenant_id=t.id "
            "WHERE t.tipo='cliente' GROUP BY t.id, u.id_usuario "
            "ORDER BY t.creada_en DESC, t.id DESC"
        ).fetchall()
    return [
        {
            "tenant_id": fila[0],
            "id_usuario": fila[1],
            "empresa": fila[2],
            "usuario": fila[3],
            "creada_en": fila[4],
            "suscripcion_hasta": fila[5],
            "activo": bool(fila[6]),
            "mensualidad": fila[7],
            "cantidad_pagos": fila[8],
            "ultimo_pago": fila[9],
        }
        for fila in filas
    ]


def actualizar_mensualidad_prestamista(tenant_id, mensualidad):
    mensualidad = _normalizar_mensualidad(mensualidad)
    with _conectar_base_datos() as conexion:
        cursor = conexion.execute(
            "UPDATE tenants SET mensualidad=? WHERE id=? AND tipo='cliente'",
            (mensualidad, tenant_id),
        )
    return cursor.rowcount == 1


def cambiar_estado_prestamista(tenant_id, activo):
    with _conectar_base_datos() as conexion:
        cursor = conexion.execute(
            "UPDATE tenants SET activo=? WHERE id=? AND tipo='cliente'",
            (1 if activo else 0, tenant_id),
        )
    return cursor.rowcount == 1


def renovar_suscripcion_prestamista(tenant_id, registrado_por, fecha_pago=None):
    hoy = fecha_pago or date.today()
    if not isinstance(hoy, date):
        hoy = date.fromisoformat(hoy)
    with _conectar_base_datos() as conexion:
        cuenta = conexion.execute(
            "SELECT suscripcion_hasta, mensualidad FROM tenants "
            "WHERE id=? AND tipo='cliente'",
            (tenant_id,),
        ).fetchone()
        if not cuenta:
            return None
        hasta = date.fromisoformat(cuenta[0]) if cuenta[0] else hoy
        desde = max(hoy, hasta)
        mes = desde.month % 12 + 1
        anio = desde.year + (1 if desde.month == 12 else 0)
        nuevo_vencimiento = date(anio, mes, min(desde.day, monthrange(anio, mes)[1]))
        monto = _normalizar_mensualidad(cuenta[1])
        conexion.execute(
            "UPDATE tenants SET activo=1, suscripcion_hasta=? WHERE id=?",
            (nuevo_vencimiento.isoformat(), tenant_id),
        )
        conexion.execute(
            "INSERT INTO pagos_suscripcion "
            "(tenant_id, fecha_pago, monto, moneda, periodo_desde, periodo_hasta, registrado_por) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id,
                hoy.isoformat(),
                monto,
                _MONEDA_MENSUALIDAD,
                desde.isoformat(),
                nuevo_vencimiento.isoformat(),
                registrado_por,
            ),
        )
    return nuevo_vencimiento.isoformat()


def historial_pagos_prestamista(tenant_id):
    with _conectar_base_datos() as conexion:
        return conexion.execute(
            "SELECT fecha_pago, monto, moneda, periodo_desde, periodo_hasta, registrado_por "
            "FROM pagos_suscripcion WHERE tenant_id=? "
            "ORDER BY fecha_pago DESC, id DESC",
            (tenant_id,),
        ).fetchall()


def crear_backup_base_datos(destino):
    origen = os.path.abspath(_ruta_base_datos())
    destino = os.path.abspath(destino)
    if os.path.normcase(origen) == os.path.normcase(destino):
        raise ValueError("El archivo de respaldo no puede ser la base de datos activa.")
    carpeta = os.path.dirname(destino)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with closing(sqlite3.connect(origen)) as base_origen:
        with closing(sqlite3.connect(destino)) as base_destino:
            base_origen.backup(base_destino)
            base_destino.commit()
            resultado = base_destino.execute("PRAGMA integrity_check").fetchone()
            if not resultado or resultado[0] != "ok":
                raise RuntimeError("La copia no superó la verificación de integridad de SQLite.")
    return destino


def cambiar_contrasena_usuario(id_usuario, contrasena_actual, contrasena_nueva):
    with _conectar_base_datos() as conexion:
        fila = conexion.execute(
            "SELECT contrasena FROM usuarios WHERE id_usuario=?",
            (id_usuario,),
        ).fetchone()
        if not fila or not _verificar_contrasena(contrasena_actual, fila[0]):
            return False
        conexion.execute(
            "UPDATE usuarios SET contrasena=?, forzar_cambio_contrasena=0 WHERE id_usuario=?",
            (_hash_contrasena(contrasena_nueva), id_usuario),
        )
    return True


def restablecer_contrasena_usuario(id_usuario, contrasena_temporal):
    with _conectar_base_datos() as conexion:
        cursor = conexion.execute(
            "UPDATE usuarios SET contrasena=?, forzar_cambio_contrasena=1 "
            "WHERE id_usuario=? AND rol='prestamista'",
            (_hash_contrasena(contrasena_temporal), id_usuario),
        )
    return cursor.rowcount == 1


def listar_usuarios():
    with _conectar_base_datos() as conexion:
        return conexion.execute(
            "SELECT nombre_usuario, rol FROM usuarios ORDER BY nombre_usuario"
        ).fetchall()