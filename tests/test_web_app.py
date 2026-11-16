import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from urllib.parse import unquote, urlparse

import clases
import web_app


class WebAppTest(unittest.TestCase):
    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.ruta_original = clases._ruta_base_datos
        clases._ruta_base_datos = lambda: os.path.join(self.directorio.name, "test.db")
        web_app.app.config.update(
            TESTING=True,
            SECRET_KEY="clave-de-prueba",
            SESSION_COOKIE_SECURE=False,
        )
        self.client = web_app.app.test_client()
        self.assertEqual(self.client.get("/api/clients").status_code, 401)

        estado = self.client.get("/api/session").get_json()
        self.csrf = estado["csrf_token"]
        self.assertTrue(clases.agregar_usuario("admin-prueba", "clave-prueba", "admin"))
        respuesta = self.client.post(
            "/api/admin/login",
            json={"usuario": "admin-prueba", "contrasena": "clave-prueba"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.csrf = respuesta.get_json()["csrf_token"]

    def tearDown(self):
        clases._ruta_base_datos = self.ruta_original
        self.directorio.cleanup()

    def encabezados_csrf(self):
        return {"X-CSRF-Token": self.csrf}

    def crear_cuenta_prestamista(self, usuario="prestamista1"):
        respuesta = self.client.post(
            "/api/register",
            json={
                "nombre": "Cartera de prueba",
                "usuario": usuario,
                "contrasena": "clave-segura-123",
            },
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(respuesta.status_code, 201)
        datos = respuesta.get_json()
        self.csrf = datos["csrf_token"]
        return datos

    def iniciar_sesion_admin(self):
        cliente_admin = web_app.app.test_client()
        csrf = cliente_admin.get("/api/session").get_json()["csrf_token"]
        respuesta = cliente_admin.post(
            "/api/admin/login",
            json={"usuario": "admin-prueba", "contrasena": "clave-prueba"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(respuesta.status_code, 200)
        return cliente_admin, respuesta.get_json()["csrf_token"]

    def test_pwa_shell_and_headers(self):
        inicio = self.client.get("/")
        self.assertEqual(inicio.status_code, 200)
        self.assertIn("Content-Security-Policy", inicio.headers)
        pagina = inicio.get_data(as_text=True).lower()
        self.assertIn("gestión de préstamos", pagina)
        self.assertIn('rel="canonical"', pagina)
        self.assertNotIn("__rijo_public_origin__", pagina)
        inicio.close()
        robots = self.client.get("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn("Disallow: /api/", robots.get_data(as_text=True))
        robots.close()
        sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn("<urlset", sitemap.get_data(as_text=True))
        sitemap.close()
        manifiesto = self.client.get("/manifest.webmanifest")
        self.assertEqual(manifiesto.status_code, 200)
        manifiesto.close()
        icono = self.client.get("/icons/icon-192.png")
        self.assertEqual(icono.status_code, 200)
        icono.close()
        worker = self.client.get("/service-worker.js")
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker.headers["Service-Worker-Allowed"], "/")
        worker.close()

    def test_portal_cliente_limita_datos_y_requiere_codigo_de_un_solo_uso(self):
        self.crear_cuenta_prestamista()
        fecha_inicio = date.today()
        fecha_vencimiento = fecha_inicio + timedelta(days=30)
        codigo_por_cliente = {}
        for id_cliente, nombre in (
            ("cliente-a", "Ana Prueba"),
            ("cliente-b", "Bruno Prueba"),
        ):
            cliente = self.client.post(
                "/api/clients",
                json={"id_cliente": id_cliente, "nombre": nombre},
                headers=self.encabezados_csrf(),
            )
            self.assertEqual(cliente.status_code, 201)
            codigo_por_cliente[id_cliente] = cliente.get_json()["codigo_acceso"]
            prestamo = self.client.post(
                "/api/loans",
                json={
                    "id_prestamo": f"prestamo-{id_cliente}",
                    "id_cliente": id_cliente,
                    "monto": 100,
                    "tasa_interes": 0,
                    "fecha_inicio": fecha_inicio.isoformat(),
                    "fecha_vencimiento": fecha_vencimiento.isoformat(),
                },
                headers=self.encabezados_csrf(),
            )
            self.assertEqual(prestamo.status_code, 201)
        pago = self.client.post(
            "/api/loans/prestamo-cliente-a/payments",
            json={"fecha": fecha_inicio.isoformat(), "monto": 25},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(pago.status_code, 200)

        portal = web_app.app.test_client()
        csrf = portal.get("/api/session").get_json()["csrf_token"]
        registro = portal.post(
            "/api/client/register",
            json={
                "prestamista": "prestamista1",
                "id_cliente": "cliente-a",
                "codigo_acceso": codigo_por_cliente["cliente-a"],
                "usuario": "ana-cliente",
                "contrasena": "clave-de-cliente-123",
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(registro.status_code, 201)
        self.assertEqual(registro.get_json()["rol"], "cliente")
        csrf = registro.get_json()["csrf_token"]

        datos_portal = portal.get("/api/portal").get_json()
        self.assertEqual(datos_portal["nombre"], "Ana Prueba")
        self.assertEqual(
            [prestamo["id_prestamo"] for prestamo in datos_portal["prestamos"]],
            ["prestamo-cliente-a"],
        )
        self.assertEqual(datos_portal["prestamos"][0]["saldo_pendiente"], 75)
        self.assertEqual(datos_portal["prestamos"][0]["pagos"][0]["monto"], 25)
        self.assertEqual(portal.get("/api/clients").status_code, 403)
        self.assertEqual(portal.get("/api/loans").status_code, 403)
        self.assertEqual(portal.get("/api/dashboard").status_code, 403)
        pago_prohibido = portal.post(
            "/api/loans/prestamo-cliente-a/payments",
            json={"fecha": fecha_inicio.isoformat(), "monto": 10},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(pago_prohibido.status_code, 403)

        segundo_registro = web_app.app.test_client()
        csrf_segundo = segundo_registro.get("/api/session").get_json()["csrf_token"]
        reutilizado = segundo_registro.post(
            "/api/client/register",
            json={
                "prestamista": "prestamista1",
                "id_cliente": "cliente-a",
                "codigo_acceso": codigo_por_cliente["cliente-a"],
                "usuario": "otra-cuenta",
                "contrasena": "clave-de-cliente-123",
            },
            headers={"X-CSRF-Token": csrf_segundo},
        )
        self.assertEqual(reutilizado.status_code, 400)

        codigo_nuevo = self.client.post(
            "/api/clients/cliente-a/access-code",
            json={},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(codigo_nuevo.status_code, 200)
        self.assertNotEqual(codigo_nuevo.get_json()["codigo_acceso"], codigo_por_cliente["cliente-a"])
        self.assertEqual(portal.get("/api/portal").status_code, 401)

    def test_cliente_prestamo_pago_y_panel(self):
        cliente = self.client.post(
            "/api/clients",
            json={"id_cliente": "c-1", "nombre": "Cliente de prueba"},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(cliente.status_code, 201)
        duplicado = self.client.post(
            "/api/clients",
            json={"id_cliente": "c-1", "nombre": "Otro nombre"},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(duplicado.status_code, 409)

        fecha_inicio = date.today()
        fecha_vencimiento = fecha_inicio + timedelta(days=30)
        prestamo = self.client.post(
            "/api/loans",
            json={
                "id_prestamo": "p-1",
                "id_cliente": "c-1",
                "monto": 100,
                "tasa_interes": 5,
                "tasa_mora": 1,
                "fecha_inicio": fecha_inicio.isoformat(),
                "fecha_vencimiento": fecha_vencimiento.isoformat(),
            },
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(prestamo.status_code, 201)

        pago = self.client.post(
            "/api/loans/p-1/payments",
            json={"fecha": fecha_inicio.isoformat(), "monto": 25},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(pago.status_code, 200)
        self.assertEqual(pago.get_json()["saldo_pendiente"], 75)

        lista = self.client.get("/api/loans").get_json()["resultados"]
        self.assertEqual(lista[0]["pagos"][0]["monto"], 25)
        resumen = self.client.get("/api/dashboard").get_json()
        self.assertEqual(resumen["clientes"], 1)
        self.assertEqual(resumen["activos"], 1)
        self.assertEqual(resumen["ingresos"], 25)

    def test_plan_gratis_limita_cinco_prestamos_y_premium_es_mensual(self):
        cuenta = self.crear_cuenta_prestamista()
        tenant_id = cuenta["tenant_id"]
        plan = self.client.get("/api/subscription").get_json()
        self.assertFalse(plan["premium"])
        self.assertIsNone(plan["suscripcion_hasta"])
        self.assertEqual(plan["limite_gratis"], 5)
        self.assertEqual(plan["mensualidad"], "600")

        cliente = self.client.post(
            "/api/clients",
            json={"id_cliente": "cuota", "nombre": "Cliente de cuota"},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(cliente.status_code, 201)
        hoy = date.today()
        for numero in range(5):
            respuesta = self.client.post(
                "/api/loans",
                json={
                    "id_prestamo": f"cuota-{numero}",
                    "id_cliente": "cuota",
                    "monto": 100,
                    "tasa_interes": 0,
                    "fecha_inicio": hoy.isoformat(),
                    "fecha_vencimiento": (hoy + timedelta(days=30)).isoformat(),
                },
                headers=self.encabezados_csrf(),
            )
            self.assertEqual(respuesta.status_code, 201)
        pago = self.client.post(
            "/api/loans/cuota-0/payments",
            json={"fecha": hoy.isoformat(), "monto": 100},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(pago.status_code, 200)
        sexto = self.client.post(
            "/api/loans",
            json={
                "id_prestamo": "cuota-5",
                "id_cliente": "cuota",
                "monto": 100,
                "tasa_interes": 0,
                "fecha_inicio": hoy.isoformat(),
                "fecha_vencimiento": (hoy + timedelta(days=30)).isoformat(),
            },
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(sexto.status_code, 402)
        self.assertTrue(sexto.get_json()["premium_requerido"])

        administrador, csrf_admin = self.iniciar_sesion_admin()
        precio = administrador.post(
            "/api/admin/settings/membership-price",
            json={"mensualidad": "750"},
            headers={"X-CSRF-Token": csrf_admin},
        )
        self.assertEqual(precio.status_code, 200)
        activacion = administrador.post(
            f"/api/admin/accounts/{tenant_id}/renovar",
            json={},
            headers={"X-CSRF-Token": csrf_admin},
        )
        self.assertEqual(activacion.status_code, 200)
        sexto = self.client.post(
            "/api/loans",
            json={
                "id_prestamo": "cuota-5",
                "id_cliente": "cuota",
                "monto": 100,
                "tasa_interes": 0,
                "fecha_inicio": hoy.isoformat(),
                "fecha_vencimiento": (hoy + timedelta(days=30)).isoformat(),
            },
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(sexto.status_code, 201)
        historial = administrador.get(
            f"/api/admin/accounts/{tenant_id}/payments"
        ).get_json()["resultados"]
        self.assertEqual(historial[0]["monto"], "750.00")

    def test_operaciones_de_escritura_requieren_csrf(self):
        respuesta = self.client.post(
            "/api/clients",
            json={"id_cliente": "c-2", "nombre": "Sin token"},
        )
        self.assertEqual(respuesta.status_code, 403)

    def test_registro_aísla_clientes_y_admite_ids_duplicados(self):
        cliente_admin, _ = self.iniciar_sesion_admin()
        respuesta = cliente_admin.post(
            "/api/clients",
            json={"id_cliente": "igual", "nombre": "Cliente del administrador"},
            headers={"X-CSRF-Token": cliente_admin.get("/api/session").get_json()["csrf_token"]},
        )
        self.assertEqual(respuesta.status_code, 201)
        inicio = date.today()
        respuesta = cliente_admin.post(
            "/api/loans",
            json={
                "id_prestamo": "mismo",
                "id_cliente": "igual",
                "monto": 100,
                "tasa_interes": 0,
                "fecha_inicio": inicio.isoformat(),
                "fecha_vencimiento": (inicio + timedelta(days=30)).isoformat(),
            },
            headers={"X-CSRF-Token": cliente_admin.get("/api/session").get_json()["csrf_token"]},
        )
        self.assertEqual(respuesta.status_code, 201)

        self.crear_cuenta_prestamista("prestamista2")
        self.assertEqual(self.client.get("/api/clients").get_json()["resultados"], [])
        respuesta = self.client.post(
            "/api/clients",
            json={"id_cliente": "igual", "nombre": "Cliente del prestamista"},
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(respuesta.status_code, 201)
        propios = self.client.get("/api/clients").get_json()["resultados"]
        self.assertEqual([cliente["nombre"] for cliente in propios], ["Cliente del prestamista"])
        respuesta = self.client.post(
            "/api/loans",
            json={
                "id_prestamo": "mismo",
                "id_cliente": "igual",
                "monto": 200,
                "tasa_interes": 0,
                "fecha_inicio": inicio.isoformat(),
                "fecha_vencimiento": (inicio + timedelta(days=30)).isoformat(),
            },
            headers=self.encabezados_csrf(),
        )
        self.assertEqual(respuesta.status_code, 201)
        prestamos_propios = self.client.get("/api/loans").get_json()["resultados"]
        self.assertEqual([prestamo["monto"] for prestamo in prestamos_propios], [200])

    def test_vencimiento_suspension_y_renovacion_muestran_whatsapp(self):
        cuenta = self.crear_cuenta_prestamista()
        tenant_id = cuenta["tenant_id"]
        with clases._conectar_base_datos() as conexion:
            conexion.execute(
                "UPDATE tenants SET suscripcion_hasta=?, activo=1 WHERE id=?",
                ((web_app._hoy_suscripcion() - timedelta(days=3)).isoformat(), tenant_id),
            )

        respuesta = self.client.get("/api/clients")
        self.assertEqual(respuesta.status_code, 200)
        with clases._conectar_base_datos() as conexion:
            conexion.execute(
                "UPDATE tenants SET suscripcion_hasta=? WHERE id=?",
                ((web_app._hoy_suscripcion() - timedelta(days=4)).isoformat(), tenant_id),
            )

        respuesta = self.client.get("/api/clients")
        self.assertEqual(respuesta.status_code, 402)
        detalles = respuesta.get_json()
        self.assertTrue(detalles["pago_requerido"])
        self.assertEqual(detalles["mensualidad"], "600")
        self.assertEqual(detalles["moneda"], "DOP")
        self.assertEqual(urlparse(detalles["whatsapp_url"]).netloc, "wa.me")
        self.assertEqual(unquote(urlparse(detalles["whatsapp_url"]).query.split("=", 1)[1]).count("prestamista1"), 1)

        cliente_admin, csrf_admin = self.iniciar_sesion_admin()
        renovacion = cliente_admin.post(
            f"/api/admin/accounts/{tenant_id}/renovar",
            json={},
            headers={"X-CSRF-Token": csrf_admin},
        )
        self.assertEqual(renovacion.status_code, 200)
        fecha_esperada = web_app._agregar_un_mes(web_app._hoy_suscripcion()).isoformat()
        self.assertEqual(renovacion.get_json()["suscripcion_hasta"], fecha_esperada)
        historial = cliente_admin.get(
            f"/api/admin/accounts/{tenant_id}/payments"
        ).get_json()["resultados"]
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["periodo_hasta"], fecha_esperada)
        cuentas = cliente_admin.get("/api/admin/accounts").get_json()["resultados"]
        cuenta_actual = next(item for item in cuentas if item["id"] == tenant_id)
        self.assertEqual(cuenta_actual["cantidad_pagos"], 1)
        self.assertEqual(cuenta_actual["ultimo_pago"], web_app._hoy_suscripcion().isoformat())

        csrf_prestamista = self.client.get("/api/session").get_json()["csrf_token"]
        acceso = self.client.post(
            "/api/login",
            json={"usuario": "prestamista1", "contrasena": "clave-segura-123"},
            headers={"X-CSRF-Token": csrf_prestamista},
        )
        self.assertEqual(acceso.status_code, 200)

        suspension = cliente_admin.post(
            f"/api/admin/accounts/{tenant_id}/suspender",
            json={},
            headers={"X-CSRF-Token": csrf_admin},
        )
        self.assertEqual(suspension.status_code, 200)
        respuesta = self.client.get("/api/session")
        self.assertEqual(respuesta.status_code, 402)
        self.assertIn("suspendida", respuesta.get_json()["mensaje"].lower())

    def test_acceso_admin_separado_y_restablecimiento_temporal(self):
        acceso_comun = web_app.app.test_client()
        csrf = acceso_comun.get("/api/session").get_json()["csrf_token"]
        respuesta = acceso_comun.post(
            "/api/login",
            json={"usuario": "admin-prueba", "contrasena": "clave-prueba"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(respuesta.status_code, 403)
        respuesta = acceso_comun.post(
            "/api/admin/login",
            json={"usuario": "admin-prueba", "contrasena": "clave-prueba"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(respuesta.status_code, 200)

        cuenta = self.crear_cuenta_prestamista()
        tenant_id = cuenta["tenant_id"]
        cliente_admin, csrf_admin = self.iniciar_sesion_admin()
        restablecimiento = cliente_admin.post(
            f"/api/admin/accounts/{tenant_id}/reset-password",
            json={},
            headers={"X-CSRF-Token": csrf_admin},
        )
        self.assertEqual(restablecimiento.status_code, 200)
        temporal = restablecimiento.get_json()["contrasena_temporal"]
        self.assertTrue(restablecimiento.get_json()["mostrar_una_vez"])

        cliente_prestamista = web_app.app.test_client()
        csrf_prestamista = cliente_prestamista.get("/api/session").get_json()["csrf_token"]
        inicio = cliente_prestamista.post(
            "/api/login",
            json={"usuario": "prestamista1", "contrasena": temporal},
            headers={"X-CSRF-Token": csrf_prestamista},
        )
        self.assertEqual(inicio.status_code, 200)
        self.assertTrue(inicio.get_json()["requiere_cambio_contrasena"])
        self.assertEqual(
            cliente_prestamista.get("/api/dashboard").status_code,
            403,
        )
        cambio = cliente_prestamista.post(
            "/api/password/change",
            json={
                "contrasena_actual": temporal,
                "contrasena_nueva": "nueva-clave-segura-123",
            },
            headers={"X-CSRF-Token": inicio.get_json()["csrf_token"]},
        )
        self.assertEqual(cambio.status_code, 200)
        self.assertFalse(
            cliente_prestamista.get("/api/session").get_json()["requiere_cambio_contrasena"]
        )
        self.assertEqual(cliente_prestamista.get("/api/dashboard").status_code, 200)

        with clases._conectar_base_datos() as conexion:
            hash_guardado = conexion.execute(
                "SELECT contrasena FROM usuarios WHERE nombre_usuario='prestamista1'"
            ).fetchone()[0]
        self.assertNotIn(temporal, hash_guardado)
        inicio_antiguo = web_app.app.test_client()
        csrf_antiguo = inicio_antiguo.get("/api/session").get_json()["csrf_token"]
        respuesta = inicio_antiguo.post(
            "/api/login",
            json={"usuario": "prestamista1", "contrasena": temporal},
            headers={"X-CSRF-Token": csrf_antiguo},
        )
        self.assertEqual(respuesta.status_code, 401)

    def test_migracion_preserva_datos_anteriores(self):
        directorio = tempfile.TemporaryDirectory()
        ruta_original = clases._ruta_base_datos
        ruta = os.path.join(directorio.name, "legacy.db")
        conexion = sqlite3.connect(ruta)
        conexion.executescript(
            "CREATE TABLE clientes (id_cliente TEXT PRIMARY KEY, nombre TEXT NOT NULL, fecha_registro TEXT NOT NULL);"
            "CREATE TABLE prestamos (id_prestamo TEXT PRIMARY KEY, id_cliente TEXT NOT NULL, monto REAL NOT NULL, "
            "tasa_interes REAL NOT NULL, fecha_inicio TEXT NOT NULL, fecha_vencimiento TEXT NOT NULL, "
            "tasa_mora REAL NOT NULL DEFAULT 0, saldo_pendiente REAL NOT NULL, pagos TEXT NOT NULL DEFAULT '[]');"
            "CREATE TABLE usuarios (id_usuario INTEGER PRIMARY KEY AUTOINCREMENT, nombre_usuario TEXT NOT NULL UNIQUE, "
            "contrasena TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'usuario');"
            "INSERT INTO clientes VALUES ('c-legacy', 'Cliente anterior', '2026-01-01');"
            "INSERT INTO prestamos VALUES ('p-legacy', 'c-legacy', 100, 5, '2026-01-01', '2026-02-01', 0, 75, "
            "'[{\"fecha\":\"2026-01-10\",\"monto\":25}]');"
            "INSERT INTO usuarios (nombre_usuario, contrasena, rol) VALUES ('admin-antiguo', 'hash', 'admin');"
        )
        conexion.close()
        try:
            clases._ruta_base_datos = lambda: ruta
            clientes = clases.cargar_clientes_sql()
            prestamos = clases.cargar_prestamos_sql()
            self.assertEqual(clientes["c-legacy"].nombre, "Cliente anterior")
            self.assertEqual(prestamos["p-legacy"].saldo_pendiente, 75)
            self.assertEqual(prestamos["p-legacy"].pagos[0]["monto"], 25)
            with clases._conectar_base_datos() as conexion_migrada:
                self.assertEqual(
                    conexion_migrada.execute(
                        "SELECT tenant_id FROM usuarios WHERE nombre_usuario='admin-antiguo'"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conexion_migrada.execute(
                        "SELECT tipo FROM tenants WHERE id=1"
                    ).fetchone()[0],
                    "plataforma",
                )
        finally:
            clases._ruta_base_datos = ruta_original
            directorio.cleanup()


if __name__ == "__main__":
    unittest.main()
