import ast
from html import escape as escape_html
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException

from clases import (
    _conectar_base_datos,
    _hash_contrasena,
    _verificar_contrasena,
    actualizar_mensualidad_plataforma,
    cargar_clientes_sql,
    cargar_prestamos_sql,
    cambiar_contrasena_usuario,
    crear_cuenta_prestamista_con_mensualidad,
    obtener_usuario_autenticado,
    obtener_mensualidad_plataforma,
    restablecer_contrasena_usuario,
)


BASE_DIR = Path(__file__).resolve().parent
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
MONTHLY_PRICE = os.environ.get("RIJO_MONTHLY_PRICE", "600")
MONTHLY_CURRENCY = os.environ.get("RIJO_MONTHLY_CURRENCY", "DOP")
FREE_LOAN_LIMIT = 5
SUBSCRIPTION_GRACE_DAYS = 3
PAYMENT_WHATSAPP = re.sub(
    r"\D",
    "",
    os.environ.get("RIJO_PAYMENT_WHATSAPP", "18099070345"),
)
if not re.fullmatch(r"\d{7,15}", PAYMENT_WHATSAPP):
    raise RuntimeError("RIJO_PAYMENT_WHATSAPP debe incluir el número internacional de WhatsApp.")
if not re.fullmatch(r"\d+(?:\.\d{1,2})?", MONTHLY_PRICE):
    raise RuntimeError("RIJO_MONTHLY_PRICE debe ser un importe positivo, sin separadores.")
PUBLIC_URL = os.environ.get("RIJO_PUBLIC_URL", "").strip().rstrip("/")
if PUBLIC_URL:
    url_publica = urlsplit(PUBLIC_URL)
    if (
        url_publica.scheme not in {"http", "https"}
        or not url_publica.netloc
        or url_publica.path
        or url_publica.query
        or url_publica.fragment
        or url_publica.username
        or url_publica.password
    ):
        raise RuntimeError("RIJO_PUBLIC_URL debe ser el origen público, sin ruta ni credenciales.")
if os.environ.get("RIJO_ENV") == "production" and (
    not PUBLIC_URL or urlsplit(PUBLIC_URL).scheme != "https"
):
    raise RuntimeError("RIJO_PUBLIC_URL debe configurarse con el dominio HTTPS público.")
BILLING_TIMEZONE = timezone(timedelta(hours=-4))

secret_key = os.environ.get("RIJO_SECRET_KEY")
if not secret_key and os.environ.get("RIJO_ENV") == "production":
    raise RuntimeError("RIJO_SECRET_KEY debe configurarse antes de iniciar en producción.")

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=secret_key or secrets.token_urlsafe(32),
    MAX_CONTENT_LENGTH=64 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RIJO_HTTPS") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
if os.environ.get("RIJO_TRUST_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _respuesta_error(mensaje, estado):
    return jsonify(error=mensaje), estado


def _leer_json():
    if not request.is_json:
        return None
    contenido = request.get_json(silent=True)
    return contenido if isinstance(contenido, dict) else None


def _validar_csrf():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    esperado = session.get("csrf_token", "")
    recibido = request.headers.get("X-CSRF-Token", "")
    if not esperado or not hmac.compare_digest(esperado, recibido):
        return _respuesta_error("La sesión de seguridad venció. Actualiza la página e inténtalo otra vez.", 403)
    return None


@app.before_request
def proteger_operaciones():
    if request.path.startswith("/api/"):
        return _validar_csrf()
    return None


@app.after_request
def agregar_cabeceras_seguras(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if app.config["SESSION_COOKIE_SECURE"]:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.errorhandler(HTTPException)
def responder_error_http(error):
    if request.path.startswith("/api/"):
        return _respuesta_error(error.description, error.code or 500)
    return error


def requiere_sesion(funcion):
    @wraps(funcion)
    def envolver(*args, **kwargs):
        if not session.get("nombre_usuario"):
            return _respuesta_error("Inicia sesión para continuar.", 401)
        error = _validar_acceso_actual()
        if error:
            return error
        if session.get("requiere_cambio_contrasena"):
            return jsonify(
                error="Debes cambiar la contraseña temporal antes de continuar.",
                cambio_contrasena_requerido=True,
            ), 403
        return funcion(*args, **kwargs)

    return envolver


def _agregar_un_mes(fecha):
    mes = fecha.month % 12 + 1
    anio = fecha.year + (1 if fecha.month == 12 else 0)
    if mes == 12:
        ultimo_dia = (date(anio + 1, 1, 1) - date(anio, mes, 1)).days
    else:
        ultimo_dia = (date(anio, mes + 1, 1) - date(anio, mes, 1)).days
    return date(anio, mes, min(fecha.day, ultimo_dia))


def _hoy_suscripcion():
    return datetime.now(BILLING_TIMEZONE).date()


def _precio_mensualidad():
    return obtener_mensualidad_plataforma()


def _enlace_whatsapp(nombre_usuario, activar_premium=False, mensualidad=None):
    accion = "activar Rijo Express Premium" if activar_premium else "renovar Rijo Express Premium"
    mensaje = "Hola, quiero {}. Usuario: {}. Pago: {} {}. Adjunto mi comprobante.".format(
        accion,
        nombre_usuario,
        mensualidad if mensualidad is not None else _precio_mensualidad(),
        MONTHLY_CURRENCY,
    )
    return "https://wa.me/{}?text={}".format(PAYMENT_WHATSAPP, quote(mensaje))


def _enlace_whatsapp_recuperacion():
    mensaje = (
        "Hola, necesito recuperar el acceso a Rijo Express. "
        "Mi empresa de préstamos es: ______. Mi usuario (si lo recuerdo) es: ______."
    )
    return "https://wa.me/{}?text={}".format(PAYMENT_WHATSAPP, quote(mensaje))


def _respuesta_pago_requerido(nombre_usuario, suscripcion_hasta, suspendida=False):
    if suspendida:
        mensaje = "Tu cuenta está suspendida. Procede con el pago y envía el comprobante por WhatsApp."
    else:
        mensaje = "Terminó el plazo de gracia de tu membresía Premium. Envía el comprobante para reactivar tu cuenta."
    return jsonify(
        error=mensaje,
        pago_requerido=True,
        mensaje=mensaje,
        usuario=nombre_usuario,
        suscripcion_hasta=suscripcion_hasta,
        mensualidad=_precio_mensualidad(),
        moneda=MONTHLY_CURRENCY,
        whatsapp_url=_enlace_whatsapp(nombre_usuario),
        gracia_dias=SUBSCRIPTION_GRACE_DAYS,
    ), 402


def _validar_acceso_actual():
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        session.clear()
        return _respuesta_error("La sesión venció. Inicia sesión otra vez.", 401)
    with _conectar_base_datos() as conexion:
        fila = conexion.execute(
            "SELECT u.nombre_usuario, u.rol, u.tenant_id, u.id_cliente, t.tipo, t.activo, "
            "t.suscripcion_hasta, u.forzar_cambio_contrasena, t.nombre "
            "FROM usuarios u JOIN tenants t ON t.id=u.tenant_id WHERE u.id_usuario=?",
            (id_usuario,),
        ).fetchone()
    if not fila:
        session.clear()
        return _respuesta_error("La cuenta ya no está disponible. Inicia sesión otra vez.", 401)
    nombre_usuario, rol, tenant_id, id_cliente, tipo, activo, hasta, forzar_cambio, nombre_empresa = fila
    if tipo == "cliente":
        gracia_termina = (
            date.fromisoformat(hasta) + timedelta(days=SUBSCRIPTION_GRACE_DAYS)
            if hasta
            else None
        )
        vencida = gracia_termina is not None and _hoy_suscripcion() > gracia_termina
        if not activo or vencida:
            session.clear()
            return _respuesta_pago_requerido(nombre_usuario, hasta, suspendida=not activo)
    if rol == "cliente":
        with _conectar_base_datos() as conexion:
            existe = conexion.execute(
                "SELECT 1 FROM clientes WHERE tenant_id=? AND id_cliente=?",
                (tenant_id, id_cliente),
            ).fetchone()
        if not existe:
            session.clear()
            return _respuesta_error("La cuenta de cliente ya no está disponible.", 401)
    session["nombre_usuario"] = nombre_usuario
    session["rol"] = rol
    session["tenant_id"] = tenant_id
    session["id_cliente"] = id_cliente
    session["requiere_cambio_contrasena"] = bool(forzar_cambio)
    session["nombre_empresa"] = nombre_empresa
    return None


def requiere_admin(funcion):
    @wraps(funcion)
    @requiere_sesion
    def envolver(*args, **kwargs):
        if session.get("rol") != "admin":
            return _respuesta_error("Se requiere una cuenta administradora.", 403)
        return funcion(*args, **kwargs)

    return envolver


def requiere_prestamista(funcion):
    @wraps(funcion)
    @requiere_sesion
    def envolver(*args, **kwargs):
        if session.get("rol") not in {"admin", "prestamista", "usuario"}:
            return _respuesta_error("Esta función es solo para cuentas de empresa.", 403)
        return funcion(*args, **kwargs)

    return envolver


def _intentos_bloqueados(direccion_ip):
    ahora = int(time.time())
    with _conectar_base_datos() as conexion:
        conexion.execute(
            "CREATE TABLE IF NOT EXISTS intentos_inicio ("
            "direccion_ip TEXT PRIMARY KEY, inicio INTEGER NOT NULL, "
            "intentos INTEGER NOT NULL, bloqueado_hasta INTEGER NOT NULL DEFAULT 0)"
        )
        fila = conexion.execute(
            "SELECT inicio, bloqueado_hasta FROM intentos_inicio WHERE direccion_ip=?",
            (direccion_ip,),
        ).fetchone()
        if not fila:
            return False
        inicio, bloqueado_hasta = fila
        if ahora - inicio >= LOGIN_WINDOW_SECONDS and ahora >= bloqueado_hasta:
            conexion.execute("DELETE FROM intentos_inicio WHERE direccion_ip=?", (direccion_ip,))
            return False
        return bloqueado_hasta > ahora


def _registrar_intento_fallido(direccion_ip):
    ahora = int(time.time())
    with _conectar_base_datos() as conexion:
        conexion.execute(
            "CREATE TABLE IF NOT EXISTS intentos_inicio ("
            "direccion_ip TEXT PRIMARY KEY, inicio INTEGER NOT NULL, "
            "intentos INTEGER NOT NULL, bloqueado_hasta INTEGER NOT NULL DEFAULT 0)"
        )
        fila = conexion.execute(
            "SELECT inicio, intentos FROM intentos_inicio WHERE direccion_ip=?",
            (direccion_ip,),
        ).fetchone()
        if not fila or ahora - fila[0] >= LOGIN_WINDOW_SECONDS:
            inicio, intentos = ahora, 1
        else:
            inicio, intentos = fila[0], fila[1] + 1
        bloqueado_hasta = ahora + LOGIN_WINDOW_SECONDS if intentos >= LOGIN_MAX_FAILURES else 0
        conexion.execute(
            "INSERT INTO intentos_inicio (direccion_ip, inicio, intentos, bloqueado_hasta) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(direccion_ip) DO UPDATE SET "
            "inicio=excluded.inicio, intentos=excluded.intentos, "
            "bloqueado_hasta=excluded.bloqueado_hasta",
            (direccion_ip, inicio, intentos, bloqueado_hasta),
        )
        conexion.execute(
            "DELETE FROM intentos_inicio WHERE inicio < ?",
            (ahora - LOGIN_WINDOW_SECONDS * 4,),
        )
    return intentos >= LOGIN_MAX_FAILURES


def _limpiar_intentos(direccion_ip):
    with _conectar_base_datos() as conexion:
        conexion.execute("DELETE FROM intentos_inicio WHERE direccion_ip=?", (direccion_ip,))


def _registro_bloqueado(direccion_ip):
    ahora = int(time.time())
    with _conectar_base_datos() as conexion:
        conexion.execute(
            "CREATE TABLE IF NOT EXISTS intentos_registro ("
            "direccion_ip TEXT NOT NULL, creado INTEGER NOT NULL)"
        )
        conexion.execute(
            "DELETE FROM intentos_registro WHERE creado < ?",
            (ahora - 60 * 60,),
        )
        cantidad = conexion.execute(
            "SELECT COUNT(*) FROM intentos_registro WHERE direccion_ip=?",
            (direccion_ip,),
        ).fetchone()[0]
        if cantidad >= 5:
            return True
        conexion.execute(
            "INSERT INTO intentos_registro (direccion_ip, creado) VALUES (?, ?)",
            (direccion_ip, ahora),
        )
    return False


@app.get("/")
def inicio():
    respuesta = send_from_directory(BASE_DIR, "index.html")
    respuesta.direct_passthrough = False
    origen = escape_html(PUBLIC_URL or request.url_root.rstrip("/"), quote=True)
    respuesta.set_data(respuesta.get_data(as_text=True).replace("__RIJO_PUBLIC_ORIGIN__", origen))
    return respuesta


def _url_publica(ruta):
    base = PUBLIC_URL or request.url_root.rstrip("/")
    return escape(base + ruta, {'"': "&quot;"})


@app.get("/robots.txt")
def robots_txt():
    contenido = "User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {}\n".format(
        _url_publica("/sitemap.xml")
    )
    return app.response_class(contenido, mimetype="text/plain")


@app.get("/sitemap.xml")
def sitemap_xml():
    contenido = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>{}</loc></url></urlset>"
    ).format(_url_publica("/"))
    return app.response_class(contenido, mimetype="application/xml")


@app.get("/styles.css")
def estilos():
    return send_from_directory(BASE_DIR, "styles.css")


@app.get("/app.js")
def javascript():
    return send_from_directory(BASE_DIR, "app.js")


@app.get("/logo_rijo_express.png")
def logo():
    return send_from_directory(BASE_DIR, "logo_rijo_express.png")


@app.get("/manifest.webmanifest")
def manifiesto():
    return send_from_directory(BASE_DIR, "manifest.webmanifest")


@app.get("/service-worker.js")
def service_worker():
    respuesta = send_from_directory(BASE_DIR, "service-worker.js")
    respuesta.headers["Service-Worker-Allowed"] = "/"
    respuesta.headers["Cache-Control"] = "no-cache"
    return respuesta


@app.get("/icons/<path:nombre>")
def icono(nombre):
    if nombre not in {"icon-192.png", "icon-512.png"}:
        return _respuesta_error("No se encontró el icono.", 404)
    return send_from_directory(BASE_DIR / "icons", nombre)


@app.get("/api/session")
def estado_sesion():
    if session.get("nombre_usuario"):
        error = _validar_acceso_actual()
        if error:
            if error[1] != 401:
                return error
            session.clear()
    csrf_token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return jsonify(
        autenticado=bool(session.get("nombre_usuario")),
        nombre_usuario=session.get("nombre_usuario"),
        nombre_empresa=session.get("nombre_empresa"),
        rol=session.get("rol"),
        id_cliente=session.get("id_cliente"),
        tenant_id=session.get("tenant_id"),
        requiere_cambio_contrasena=bool(session.get("requiere_cambio_contrasena")),
        csrf_token=csrf_token,
    )


@app.get("/api/billing-info")
def informacion_mensualidad():
    return jsonify(
        mensualidad=_precio_mensualidad(),
        moneda=MONTHLY_CURRENCY,
        whatsapp_recuperacion_url=_enlace_whatsapp_recuperacion(),
    )


def _iniciar_sesion(es_administrador):
    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Envía los datos de inicio de sesión en formato JSON.", 400)
    nombre_usuario = str(contenido.get("usuario", "")).strip()
    contrasena = contenido.get("contrasena", "")
    if not nombre_usuario or not isinstance(contrasena, str) or not contrasena:
        return _respuesta_error("Escribe tu usuario y contraseña.", 400)

    direccion_ip = request.remote_addr or "desconocida"
    if _intentos_bloqueados(direccion_ip):
        return _respuesta_error("Demasiados intentos. Espera 15 minutos antes de volver a probar.", 429)
    usuario = obtener_usuario_autenticado(nombre_usuario, contrasena)
    if not usuario or (es_administrador and usuario["rol"] != "admin"):
        if _registrar_intento_fallido(direccion_ip):
            return _respuesta_error("Demasiados intentos. Espera 15 minutos antes de volver a probar.", 429)
        if es_administrador:
            return _respuesta_error("Usuario o contraseña de administrador incorrectos.", 401)
        return _respuesta_error("Usuario o contraseña incorrectos.", 401)
    if not es_administrador and usuario["rol"] == "admin":
        _limpiar_intentos(direccion_ip)
        return _respuesta_error("Usa el acceso separado para iniciar sesión como administrador.", 403)

    _limpiar_intentos(direccion_ip)
    session.clear()
    session.permanent = True
    session["nombre_usuario"] = nombre_usuario
    session["id_usuario"] = usuario["id_usuario"]
    session["tenant_id"] = usuario["tenant_id"]
    session["id_cliente"] = usuario["id_cliente"]
    session["rol"] = usuario["rol"]
    session["requiere_cambio_contrasena"] = usuario["requiere_cambio_contrasena"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    error = _validar_acceso_actual()
    if error:
        return error
    return jsonify(
        nombre_usuario=nombre_usuario,
        nombre_empresa=session["nombre_empresa"],
        rol=session["rol"],
        tenant_id=session["tenant_id"],
        id_cliente=session.get("id_cliente"),
        requiere_cambio_contrasena=session["requiere_cambio_contrasena"],
        csrf_token=session["csrf_token"],
    )


@app.post("/api/login")
def iniciar_sesion():
    return _iniciar_sesion(es_administrador=False)


@app.post("/api/admin/login")
def iniciar_sesion_administrador():
    return _iniciar_sesion(es_administrador=True)


@app.post("/api/password/change")
def cambiar_contrasena():
    if not session.get("id_usuario") or not session.get("nombre_usuario"):
        return _respuesta_error("Inicia sesión para cambiar la contraseña.", 401)
    error = _validar_acceso_actual()
    if error:
        return error

    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Envía la contraseña actual y la nueva contraseña.", 400)
    actual = contenido.get("contrasena_actual", "")
    nueva = contenido.get("contrasena_nueva", "")
    if not isinstance(actual, str) or not actual:
        return _respuesta_error("Escribe la contraseña temporal actual.", 400)
    if not isinstance(nueva, str) or not 12 <= len(nueva) <= 128:
        return _respuesta_error("La nueva contraseña debe tener entre 12 y 128 caracteres.", 400)
    if hmac.compare_digest(actual, nueva):
        return _respuesta_error("La nueva contraseña debe ser diferente.", 400)
    if not cambiar_contrasena_usuario(session["id_usuario"], actual, nueva):
        return _respuesta_error("La contraseña temporal no es correcta.", 401)

    session["requiere_cambio_contrasena"] = False
    return jsonify(ok=True, csrf_token=session["csrf_token"])


@app.post("/api/register")
def registrar_cuenta():
    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Envía los datos de la cuenta en formato JSON.", 400)
    nombre = str(contenido.get("nombre", "")).strip()
    nombre_usuario = str(contenido.get("usuario", "")).strip().lower()
    contrasena = contenido.get("contrasena", "")
    if not 2 <= len(nombre) <= 80:
        return _respuesta_error("Escribe el nombre de la empresa (2 a 80 caracteres).", 400)
    if not re.fullmatch(r"[a-z0-9._-]{3,32}", nombre_usuario):
        return _respuesta_error(
            "El usuario debe tener 3 a 32 caracteres: letras, números, punto, guion o guion bajo.",
            400,
        )
    if not isinstance(contrasena, str) or not 12 <= len(contrasena) <= 128:
        return _respuesta_error("La contraseña debe tener entre 12 y 128 caracteres.", 400)

    direccion_ip = request.remote_addr or "desconocida"
    if _registro_bloqueado(direccion_ip):
        return _respuesta_error("Se alcanzó el límite de registros. Inténtalo más tarde.", 429)

    mensualidad = _precio_mensualidad()
    tenant_id = crear_cuenta_prestamista_con_mensualidad(
        nombre,
        nombre_usuario,
        contrasena,
        None,
        mensualidad,
    )
    if tenant_id is None:
        return _respuesta_error("Ya existe una cuenta con ese nombre de usuario.", 409)

    usuario = obtener_usuario_autenticado(nombre_usuario, contrasena)
    if not usuario:
        return _respuesta_error("No se pudo iniciar la sesión de la cuenta creada.", 500)
    session.clear()
    session.permanent = True
    session["nombre_usuario"] = nombre_usuario
    session["id_usuario"] = usuario["id_usuario"]
    session["tenant_id"] = tenant_id
    session["id_cliente"] = None
    session["rol"] = usuario["rol"]
    session["requiere_cambio_contrasena"] = False
    session["nombre_empresa"] = nombre
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(
        nombre_usuario=nombre_usuario,
        nombre=nombre,
        rol=usuario["rol"],
        tenant_id=tenant_id,
        suscripcion_hasta=None,
        mensualidad=mensualidad,
        moneda=MONTHLY_CURRENCY,
        plan="gratis",
        csrf_token=session["csrf_token"],
    ), 201


@app.post("/api/client/register")
def registrar_cuenta_cliente():
    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Envía los datos de acceso en formato JSON.", 400)
    usuario_prestamista = str(contenido.get("prestamista", "")).strip().lower()
    id_cliente = str(contenido.get("id_cliente", "")).strip()
    codigo_acceso = contenido.get("codigo_acceso", "")
    nombre_usuario = str(contenido.get("usuario", "")).strip().lower()
    contrasena = contenido.get("contrasena", "")
    if (
        not usuario_prestamista
        or not id_cliente
        or not isinstance(codigo_acceso, str)
        or not codigo_acceso
        or not re.fullmatch(r"[a-z0-9._-]{3,32}", nombre_usuario)
        or not isinstance(contrasena, str)
        or not 12 <= len(contrasena) <= 128
    ):
        return _respuesta_error("Revisa los datos e intenta de nuevo.", 400)
    direccion_ip = request.remote_addr or "desconocida"
    if _registro_bloqueado(direccion_ip):
        return _respuesta_error("Se alcanzó el límite de registros. Inténtalo más tarde.", 429)

    with _conectar_base_datos() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        cuenta = conexion.execute(
            "SELECT t.id, t.nombre, t.activo, t.suscripcion_hasta "
            "FROM tenants t JOIN usuarios u ON u.tenant_id=t.id "
            "WHERE u.nombre_usuario=? AND u.rol='prestamista'",
            (usuario_prestamista,),
        ).fetchone()
        if (
            not cuenta
            or not cuenta[2]
            or (
                cuenta[3]
                and _hoy_suscripcion()
                > date.fromisoformat(cuenta[3]) + timedelta(days=SUBSCRIPTION_GRACE_DAYS)
            )
        ):
            return _respuesta_error("No se pudieron validar los datos de acceso.", 400)
        tenant_id, nombre_empresa, _, _ = cuenta
        cliente = conexion.execute(
            "SELECT codigo_acceso_hash FROM clientes WHERE tenant_id=? AND id_cliente=?",
            (tenant_id, id_cliente),
        ).fetchone()
        if (
            not cliente
            or not cliente[0]
            or not _verificar_contrasena(codigo_acceso, cliente[0])
        ):
            return _respuesta_error("No se pudieron validar los datos de acceso.", 400)
        try:
            cursor = conexion.execute(
                "INSERT INTO usuarios "
                "(nombre_usuario, contrasena, rol, tenant_id, id_cliente) "
                "VALUES (?, ?, 'cliente', ?, ?)",
                (nombre_usuario, _hash_contrasena(contrasena), tenant_id, id_cliente),
            )
        except sqlite3.IntegrityError:
            return _respuesta_error("Ese nombre de usuario ya está en uso.", 409)
        conexion.execute(
            "UPDATE clientes SET codigo_acceso_hash=NULL "
            "WHERE tenant_id=? AND id_cliente=?",
            (tenant_id, id_cliente),
        )
        id_usuario = cursor.lastrowid

    session.clear()
    session.permanent = True
    session["nombre_usuario"] = nombre_usuario
    session["id_usuario"] = id_usuario
    session["tenant_id"] = tenant_id
    session["id_cliente"] = id_cliente
    session["rol"] = "cliente"
    session["requiere_cambio_contrasena"] = False
    session["nombre_empresa"] = nombre_empresa
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(
        nombre_usuario=nombre_usuario,
        nombre_empresa=nombre_empresa,
        rol="cliente",
        id_cliente=id_cliente,
        csrf_token=session["csrf_token"],
    ), 201


@app.post("/api/logout")
@requiere_sesion
def cerrar_sesion():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/dashboard")
@requiere_prestamista
def resumen():
    tenant_id = session["tenant_id"]
    clientes = cargar_clientes_sql(tenant_id)
    prestamos = cargar_prestamos_sql(tenant_id)
    hoy = _hoy_suscripcion()
    activos = [prestamo for prestamo in prestamos.values() if prestamo.saldo_pendiente > 0]
    vencidos = [
        prestamo
        for prestamo in activos
        if date.fromisoformat(prestamo.fecha_vencimiento) < hoy
    ]
    proximos = []
    for prestamo in activos:
        fecha_vencimiento = date.fromisoformat(prestamo.fecha_vencimiento)
        dias = (fecha_vencimiento - hoy).days
        if 0 <= dias <= 7:
            cliente = clientes.get(prestamo.id_cliente)
            proximos.append(
                {
                    "id_prestamo": prestamo.id_prestamo,
                    "cliente": cliente.nombre if cliente else "Desconocido",
                    "fecha_vencimiento": prestamo.fecha_vencimiento,
                    "dias": dias,
                }
            )
    ingresos = sum(
        float(pago.get("monto", 0))
        for prestamo in prestamos.values()
        for pago in prestamo.pagos
    )
    return jsonify(
        clientes=len(clientes),
        prestamos=len(prestamos),
        activos=len(activos),
        en_mora=len(vencidos),
        ingresos=ingresos,
        vencimientos=sorted(proximos, key=lambda item: item["fecha_vencimiento"])[:5],
    )


@app.get("/api/clients")
@requiere_prestamista
def listar_clientes():
    busqueda = request.args.get("q", "").strip()
    clientes = cargar_clientes_sql(session["tenant_id"])
    resultados = [
        cliente.to_dict()
        for cliente in clientes.values()
        if not busqueda
        or busqueda.casefold() in cliente.id_cliente.casefold()
        or busqueda.casefold() in cliente.nombre.casefold()
    ]
    return jsonify(resultados=sorted(resultados, key=lambda cliente: cliente["nombre"].casefold()))


@app.post("/api/clients")
@requiere_prestamista
def crear_cliente():
    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Envía los datos del cliente en formato JSON.", 400)
    id_cliente = str(contenido.get("id_cliente", "")).strip()
    nombre = str(contenido.get("nombre", "")).strip()
    if not id_cliente or not nombre:
        return _respuesta_error("El ID y el nombre del cliente son obligatorios.", 400)
    tenant_id = session["tenant_id"]
    codigo_acceso = secrets.token_urlsafe(9)
    with _conectar_base_datos() as conexion:
        cursor = conexion.execute(
            "INSERT INTO clientes "
            "(tenant_id, id_cliente, nombre, fecha_registro, codigo_acceso_hash) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(tenant_id, id_cliente) DO NOTHING",
            (
                tenant_id,
                id_cliente,
                nombre,
                date.today().isoformat(),
                _hash_contrasena(codigo_acceso),
            ),
        )
        if cursor.rowcount == 0:
            return _respuesta_error("Ya existe un cliente con ese ID.", 409)
    return jsonify(id_cliente=id_cliente, nombre=nombre, codigo_acceso=codigo_acceso), 201


@app.post("/api/clients/<path:id_cliente>/access-code")
@requiere_prestamista
def regenerar_codigo_acceso_cliente(id_cliente):
    codigo_acceso = secrets.token_urlsafe(9)
    with _conectar_base_datos() as conexion:
        cursor = conexion.execute(
            "UPDATE clientes SET codigo_acceso_hash=? "
            "WHERE tenant_id=? AND id_cliente=?",
            (_hash_contrasena(codigo_acceso), session["tenant_id"], id_cliente),
        )
        if cursor.rowcount == 0:
            return _respuesta_error("No se encontró el cliente.", 404)
        conexion.execute(
            "DELETE FROM usuarios WHERE tenant_id=? AND id_cliente=? AND rol='cliente'",
            (session["tenant_id"], id_cliente),
        )
    return jsonify(id_cliente=id_cliente, codigo_acceso=codigo_acceso)


@app.get("/api/portal")
@requiere_sesion
def portal_cliente():
    if session.get("rol") != "cliente" or not session.get("id_cliente"):
        return _respuesta_error("Esta función es solo para clientes.", 403)
    with _conectar_base_datos() as conexion:
        cliente = conexion.execute(
            "SELECT nombre FROM clientes WHERE tenant_id=? AND id_cliente=?",
            (session["tenant_id"], session["id_cliente"]),
        ).fetchone()
    if not cliente:
        session.clear()
        return _respuesta_error("La cuenta de cliente ya no está disponible.", 401)
    prestamos = cargar_prestamos_sql(session["tenant_id"])
    resultados = []
    for prestamo in prestamos.values():
        if prestamo.id_cliente == session["id_cliente"]:
            resultados.append({
                **prestamo.to_dict(),
                "tasa_mora": prestamo.tasa_mora,
            })
    resultados.sort(key=lambda prestamo: prestamo["fecha_vencimiento"])
    return jsonify(nombre=cliente[0], prestamos=resultados)


@app.get("/api/loans")
@requiere_prestamista
def listar_prestamos():
    tenant_id = session["tenant_id"]
    clientes = cargar_clientes_sql(tenant_id)
    prestamos = cargar_prestamos_sql(tenant_id)
    resultados = []
    for prestamo in prestamos.values():
        resultados.append(
            {
                **prestamo.to_dict(),
                "tasa_mora": prestamo.tasa_mora,
                "nombre_cliente": (
                    clientes[prestamo.id_cliente].nombre
                    if prestamo.id_cliente in clientes
                    else "Desconocido"
                ),
            }
        )
    resultados.sort(key=lambda prestamo: prestamo["fecha_vencimiento"])
    return jsonify(resultados=resultados)


@app.post("/api/loans")
@requiere_prestamista
def crear_prestamo():
    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Envía los datos del préstamo en formato JSON.", 400)

    id_prestamo = str(contenido.get("id_prestamo", "")).strip()
    id_cliente = str(contenido.get("id_cliente", "")).strip()
    if not id_prestamo or not id_cliente:
        return _respuesta_error("El ID del préstamo y el cliente son obligatorios.", 400)
    try:
        monto = float(contenido.get("monto"))
        tasa_interes = float(contenido.get("tasa_interes"))
        tasa_mora = float(contenido.get("tasa_mora", 0) or 0)
        fecha_inicio = date.fromisoformat(str(contenido.get("fecha_inicio", "")))
        fecha_vencimiento = date.fromisoformat(str(contenido.get("fecha_vencimiento", "")))
    except (TypeError, ValueError):
        return _respuesta_error("Revisa los importes, tasas y fechas del préstamo.", 400)
    if (
        not all(math.isfinite(valor) for valor in (monto, tasa_interes, tasa_mora))
        or monto <= 0
        or tasa_interes < 0
        or tasa_mora < 0
        or fecha_vencimiento <= fecha_inicio
    ):
        return _respuesta_error("El monto debe ser positivo y el vencimiento posterior al inicio.", 400)

    tenant_id = session["tenant_id"]
    mensualidad = _precio_mensualidad()
    with _conectar_base_datos() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        if session.get("rol") != "admin":
            suscripcion = conexion.execute(
                "SELECT suscripcion_hasta FROM tenants WHERE id=?",
                (tenant_id,),
            ).fetchone()
            cantidad_prestamos = conexion.execute(
                "SELECT COUNT(*) FROM prestamos WHERE tenant_id=?",
                (tenant_id,),
            ).fetchone()[0]
            if suscripcion and not suscripcion[0] and cantidad_prestamos >= FREE_LOAN_LIMIT:
                mensaje = (
                    "Tu cuenta gratis ya usó sus 5 préstamos. "
                    "Actualiza a Premium por {} {} al mes para crear más préstamos.".format(
                        mensualidad,
                        MONTHLY_CURRENCY,
                    )
                )
                return jsonify(
                    error=mensaje,
                    mensaje=mensaje,
                    premium_requerido=True,
                    mensualidad=mensualidad,
                    moneda=MONTHLY_CURRENCY,
                    prestamos_usados=cantidad_prestamos,
                    limite_gratis=FREE_LOAN_LIMIT,
                    whatsapp_url=_enlace_whatsapp(
                        session["nombre_usuario"],
                        activar_premium=True,
                        mensualidad=mensualidad,
                    ),
                ), 402
        cliente = conexion.execute(
            "SELECT 1 FROM clientes WHERE tenant_id=? AND id_cliente=?",
            (tenant_id, id_cliente),
        ).fetchone()
        if not cliente:
            return _respuesta_error("No se encontró el cliente seleccionado.", 404)
        cursor = conexion.execute(
            "INSERT INTO prestamos (tenant_id, id_prestamo, id_cliente, monto, tasa_interes, fecha_inicio, "
            "fecha_vencimiento, tasa_mora, saldo_pendiente, pagos) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]') "
            "ON CONFLICT(tenant_id, id_prestamo) DO NOTHING",
            (
                tenant_id,
                id_prestamo,
                id_cliente,
                monto,
                tasa_interes,
                fecha_inicio.isoformat(),
                fecha_vencimiento.isoformat(),
                tasa_mora,
                monto,
            ),
        )
        if cursor.rowcount == 0:
            return _respuesta_error("Ya existe un préstamo con ese ID.", 409)
    return jsonify(id_prestamo=id_prestamo, saldo_pendiente=monto), 201


@app.post("/api/loans/<path:id_prestamo>/payments")
@requiere_prestamista
def registrar_pago(id_prestamo):
    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Envía los datos del pago en formato JSON.", 400)
    try:
        monto = float(contenido.get("monto"))
        fecha_pago = date.fromisoformat(str(contenido.get("fecha", "")))
    except (TypeError, ValueError):
        return _respuesta_error("Revisa el monto y la fecha del pago.", 400)
    if not math.isfinite(monto) or monto <= 0:
        return _respuesta_error("El monto del pago debe ser mayor que cero.", 400)

    tenant_id = session["tenant_id"]
    with _conectar_base_datos() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        fila = conexion.execute(
            "SELECT saldo_pendiente, pagos FROM prestamos WHERE tenant_id=? AND id_prestamo=?",
            (tenant_id, id_prestamo),
        ).fetchone()
        if not fila:
            return _respuesta_error("No se encontró el préstamo.", 404)
        saldo_pendiente = float(fila[0])
        if monto > saldo_pendiente:
            return _respuesta_error("El pago no puede exceder el saldo pendiente.", 400)
        pagos_texto = fila[1] or "[]"
        try:
            pagos = json.loads(pagos_texto)
        except json.JSONDecodeError:
            pagos = ast.literal_eval(pagos_texto)
        if not isinstance(pagos, list):
            return _respuesta_error("El historial de pagos del préstamo no es válido.", 500)
        pagos.append({"fecha": fecha_pago.isoformat(), "monto": monto})
        nuevo_saldo = saldo_pendiente - monto
        conexion.execute(
            "UPDATE prestamos SET saldo_pendiente=?, pagos=? "
            "WHERE tenant_id=? AND id_prestamo=?",
            (nuevo_saldo, json.dumps(pagos, ensure_ascii=False), tenant_id, id_prestamo),
        )
    return jsonify(saldo_pendiente=nuevo_saldo, pagos=pagos)


@app.get("/api/subscription")
@requiere_prestamista
def estado_suscripcion():
    with _conectar_base_datos() as conexion:
        fila = conexion.execute(
            "SELECT tipo, suscripcion_hasta, activo FROM tenants WHERE id=?",
            (session["tenant_id"],),
        ).fetchone()
    if not fila or fila[0] != "cliente":
        return jsonify(es_cliente=False)
    hoy = _hoy_suscripcion()
    hasta = date.fromisoformat(fila[1]) if fila[1] else None
    fin_gracia = (
        hasta + timedelta(days=SUBSCRIPTION_GRACE_DAYS)
        if hasta
        else None
    )
    en_gracia = bool(
        fila[2]
        and hasta
        and hoy > hasta
        and hoy <= fin_gracia
    )
    with _conectar_base_datos() as conexion:
        prestamos_usados = conexion.execute(
            "SELECT COUNT(*) FROM prestamos WHERE tenant_id=?",
            (session["tenant_id"],),
        ).fetchone()[0]
    return jsonify(
        es_cliente=True,
        suscripcion_hasta=fila[1],
        premium=bool(hasta),
        activa=bool(fila[2]) and (not fin_gracia or hoy <= fin_gracia),
        en_gracia=en_gracia,
        gracia_hasta=fin_gracia.isoformat() if fin_gracia else None,
        dias_gracia_restantes=max(0, (fin_gracia - hoy).days) if en_gracia else 0,
        prestamos_usados=prestamos_usados,
        limite_gratis=FREE_LOAN_LIMIT,
        mensualidad=_precio_mensualidad(),
        moneda=MONTHLY_CURRENCY,
        whatsapp_url=_enlace_whatsapp(
            session["nombre_usuario"],
            activar_premium=not bool(hasta),
        ),
    )


@app.post("/api/admin/settings/membership-price")
@requiere_admin
def actualizar_precio_membresia():
    contenido = _leer_json()
    if contenido is None:
        return _respuesta_error("Escribe el nuevo precio mensual.", 400)
    try:
        mensualidad = actualizar_mensualidad_plataforma(contenido.get("mensualidad"))
    except ValueError as error:
        return _respuesta_error(str(error), 400)
    return jsonify(mensualidad=mensualidad, moneda=MONTHLY_CURRENCY)


@app.get("/api/admin/accounts")
@requiere_admin
def listar_cuentas():
    with _conectar_base_datos() as conexion:
        cuentas = conexion.execute(
            "SELECT t.id, t.nombre, u.nombre_usuario, t.creada_en, t.suscripcion_hasta, "
            "t.activo, t.mensualidad, COUNT(p.id), MAX(p.fecha_pago), "
            "(SELECT COUNT(*) FROM prestamos pr WHERE pr.tenant_id=t.id) "
            "FROM tenants t JOIN usuarios u ON u.tenant_id=t.id AND u.rol='prestamista' "
            "LEFT JOIN pagos_suscripcion p ON p.tenant_id=t.id "
            "WHERE t.tipo='cliente' GROUP BY t.id, u.id_usuario "
            "ORDER BY t.creada_en DESC, t.id DESC"
        ).fetchall()
    hoy = _hoy_suscripcion()
    return jsonify(
        resultados=[
            {
                "id": id_tenant,
                "nombre": nombre,
                "usuario": nombre_usuario,
                "creada_en": creada_en,
                "suscripcion_hasta": hasta,
                "mensualidad": mensualidad,
                "premium": bool(hasta),
                "activa": bool(activa) and (
                    not hasta
                    or hoy <= date.fromisoformat(hasta) + timedelta(days=SUBSCRIPTION_GRACE_DAYS)
                ),
                "en_gracia": bool(hasta) and date.fromisoformat(hasta) < hoy
                and hoy <= date.fromisoformat(hasta) + timedelta(days=SUBSCRIPTION_GRACE_DAYS),
                "suspendida": not bool(activa),
                "vencida": bool(hasta) and hoy
                > date.fromisoformat(hasta) + timedelta(days=SUBSCRIPTION_GRACE_DAYS),
                "cantidad_pagos": cantidad_pagos,
                "ultimo_pago": ultimo_pago,
                "prestamos_usados": prestamos_usados,
            }
            for (
                id_tenant,
                nombre,
                nombre_usuario,
                creada_en,
                hasta,
                activa,
                mensualidad,
                cantidad_pagos,
                ultimo_pago,
                prestamos_usados,
            ) in cuentas
        ]
    )


@app.post("/api/admin/accounts/<int:tenant_id>/<accion>")
@requiere_admin
def actualizar_cuenta(tenant_id, accion):
    if accion not in {"suspender", "activar", "renovar"}:
        return _respuesta_error("La operación indicada no es válida.", 400)
    mensualidad = _precio_mensualidad() if accion == "renovar" else None
    with _conectar_base_datos() as conexion:
        fila = conexion.execute(
            "SELECT suscripcion_hasta, activo FROM tenants "
            "WHERE id=? AND tipo='cliente'",
            (tenant_id,),
        ).fetchone()
        if not fila:
            return _respuesta_error("No se encontró la cuenta.", 404)
        hasta_texto, activa = fila
        if accion == "suspender":
            conexion.execute("UPDATE tenants SET activo=0 WHERE id=?", (tenant_id,))
        elif accion == "activar":
            if (
                hasta_texto
                and _hoy_suscripcion()
                > date.fromisoformat(hasta_texto) + timedelta(days=SUBSCRIPTION_GRACE_DAYS)
            ):
                return _respuesta_error("Terminó el plazo de gracia; registra el pago con Renovar.", 409)
            conexion.execute("UPDATE tenants SET activo=1 WHERE id=?", (tenant_id,))
        else:
            hoy = _hoy_suscripcion()
            fecha_base = date.fromisoformat(hasta_texto) if hasta_texto else hoy
            periodo_desde = max(hoy, fecha_base)
            nuevo_vencimiento = _agregar_un_mes(periodo_desde).isoformat()
            conexion.execute(
                "UPDATE tenants SET activo=1, suscripcion_hasta=? WHERE id=?",
                (nuevo_vencimiento, tenant_id),
            )
            conexion.execute(
                "INSERT INTO pagos_suscripcion "
                "(tenant_id, fecha_pago, monto, moneda, periodo_desde, periodo_hasta, registrado_por) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant_id,
                    hoy.isoformat(),
                    mensualidad,
                    MONTHLY_CURRENCY,
                    periodo_desde.isoformat(),
                    nuevo_vencimiento,
                    session["nombre_usuario"],
                ),
            )
    return jsonify(
        ok=True,
        suscripcion_hasta=(nuevo_vencimiento if accion == "renovar" else hasta_texto),
        activa=accion != "suspender",
    )


@app.get("/api/admin/accounts/<int:tenant_id>/payments")
@requiere_admin
def historial_pagos_suscripcion(tenant_id):
    with _conectar_base_datos() as conexion:
        existe = conexion.execute(
            "SELECT 1 FROM tenants WHERE id=? AND tipo='cliente'",
            (tenant_id,),
        ).fetchone()
        if not existe:
            return _respuesta_error("No se encontró la cuenta.", 404)
        pagos = conexion.execute(
            "SELECT fecha_pago, monto, moneda, periodo_desde, periodo_hasta, registrado_por "
            "FROM pagos_suscripcion WHERE tenant_id=? ORDER BY fecha_pago DESC, id DESC",
            (tenant_id,),
        ).fetchall()
    return jsonify(
        resultados=[
            {
                "fecha_pago": fecha,
                "monto": monto,
                "moneda": moneda,
                "periodo_desde": desde,
                "periodo_hasta": hasta,
                "registrado_por": admin,
            }
            for fecha, monto, moneda, desde, hasta, admin in pagos
        ]
    )


@app.post("/api/admin/accounts/<int:tenant_id>/reset-password")
@requiere_admin
def restablecer_acceso(tenant_id):
    with _conectar_base_datos() as conexion:
        usuario = conexion.execute(
            "SELECT id_usuario, nombre_usuario FROM usuarios "
            "WHERE tenant_id=? AND rol='prestamista'",
            (tenant_id,),
        ).fetchone()
    if not usuario:
        return _respuesta_error("No se encontró la cuenta.", 404)
    contrasena_temporal = secrets.token_urlsafe(12)
    if not restablecer_contrasena_usuario(usuario[0], contrasena_temporal):
        return _respuesta_error("No se pudo restablecer el acceso.", 500)
    return jsonify(
        usuario=usuario[1],
        contrasena_temporal=contrasena_temporal,
        mostrar_una_vez=True,
    )


if __name__ == "__main__":
    host = os.environ.get("RIJO_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
