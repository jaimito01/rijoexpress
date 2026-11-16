import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from unittest import mock

import clases


class DesktopDataTest(unittest.TestCase):
    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.ruta_original = clases._ruta_base_datos
        clases._ruta_base_datos = lambda: os.path.join(self.directorio.name, "desktop.db")

    def tearDown(self):
        clases._ruta_base_datos = self.ruta_original
        self.directorio.cleanup()

    def crear_prestamista(self, monto="500"):
        return clases.crear_cuenta_prestamista_con_mensualidad(
            "Empresa de prueba",
            "prestamista-prueba",
            "clave-segura-123",
            date.today().isoformat(),
            monto,
        )

    def test_autenticacion_devuelve_tenant_y_separa_los_datos(self):
        tenant_id = self.crear_prestamista()
        usuario = clases.obtener_usuario_autenticado(
            "prestamista-prueba",
            "clave-segura-123",
        )
        self.assertEqual(usuario["rol"], "prestamista")
        self.assertEqual(usuario["tenant_id"], tenant_id)
        self.assertEqual(usuario["nombre_empresa"], "Empresa de prueba")

        clientes_admin = {
            "mismo-id": clases.Cliente("mismo-id", "Cliente administrador", "2026-01-01")
        }
        clientes_prestamista = {
            "mismo-id": clases.Cliente("mismo-id", "Cliente prestamista", "2026-01-01")
        }
        clases.guardar_clientes_sql(clientes_admin, tenant_id=1)
        clases.guardar_clientes_sql(clientes_prestamista, tenant_id=tenant_id)
        self.assertEqual(
            clases.cargar_clientes_sql(1)["mismo-id"].nombre,
            "Cliente administrador",
        )
        self.assertEqual(
            clases.cargar_clientes_sql(tenant_id)["mismo-id"].nombre,
            "Cliente prestamista",
        )

    def test_mensualidad_editable_y_renovacion_registrada(self):
        tenant_id = self.crear_prestamista()
        self.assertTrue(clases.actualizar_mensualidad_prestamista(tenant_id, "725.50"))
        vencimiento = clases.renovar_suscripcion_prestamista(
            tenant_id,
            "admin-prueba",
            fecha_pago=date(2026, 11, 12),
        )
        self.assertEqual(vencimiento, "2026-12-12")
        pago = clases.historial_pagos_prestamista(tenant_id)[0]
        self.assertEqual(pago[1:5], ("725.50", "DOP", "2026-11-12", "2026-12-12"))
        cuenta = clases.obtener_cuentas_prestamistas()[0]
        self.assertEqual(cuenta["mensualidad"], "725.50")
        self.assertEqual(cuenta["suscripcion_hasta"], "2026-12-12")
        with self.assertRaises(ValueError):
            clases.actualizar_mensualidad_prestamista(tenant_id, "cero")

    def test_backup_copia_la_base_sqlite_completa(self):
        tenant_id = self.crear_prestamista()
        destino = os.path.join(self.directorio.name, "usb", "respaldo.db")
        self.assertEqual(clases.crear_backup_base_datos(destino), destino)
        with closing(sqlite3.connect(destino)) as respaldo:
            self.assertEqual(
                respaldo.execute(
                    "SELECT nombre FROM tenants WHERE id=?",
                    (tenant_id,),
                ).fetchone()[0],
                "Empresa de prueba",
            )
            self.assertEqual(
                respaldo.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )

    def test_ejecutable_migra_la_base_existente_a_datos_locales(self):
        raiz = os.path.join(self.directorio.name, "proyecto")
        carpeta_exe = os.path.join(raiz, "dist")
        carpeta_appdata = os.path.join(self.directorio.name, "AppData")
        os.makedirs(carpeta_exe)
        base_anterior = os.path.join(raiz, "rijoexpress.db")
        with closing(sqlite3.connect(base_anterior)) as conexion:
            conexion.execute("CREATE TABLE datos (valor TEXT)")
            conexion.execute("INSERT INTO datos VALUES ('preservado')")
            conexion.commit()

        with (
            mock.patch.object(clases, "_ruta_base_datos", self.ruta_original),
            mock.patch.object(clases.sys, "frozen", True, create=True),
            mock.patch.object(
                clases.sys,
                "executable",
                os.path.join(carpeta_exe, "rijoexpress.exe"),
            ),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": carpeta_appdata}),
        ):
            ruta = clases._ruta_base_datos()

        self.assertEqual(
            ruta,
            os.path.join(carpeta_appdata, "RijoExpress", "rijoexpress.db"),
        )
        with closing(sqlite3.connect(ruta)) as conexion:
            self.assertEqual(
                conexion.execute("SELECT valor FROM datos").fetchone()[0],
                "preservado",
            )

    def test_primer_arranque_crea_la_carpeta_de_datos_sin_base_previa(self):
        raiz = os.path.join(self.directorio.name, "proyecto")
        carpeta_exe = os.path.join(raiz, "dist")
        carpeta_appdata = os.path.join(self.directorio.name, "AppData")
        os.makedirs(carpeta_exe)
        archivo_clases = os.path.join(raiz, "clases.py")

        with (
            mock.patch.object(clases, "_ruta_base_datos", self.ruta_original),
            mock.patch.object(clases, "__file__", archivo_clases),
            mock.patch.object(clases.sys, "frozen", True, create=True),
            mock.patch.object(
                clases.sys,
                "executable",
                os.path.join(carpeta_exe, "rijoexpress.exe"),
            ),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": carpeta_appdata}),
        ):
            ruta = clases._ruta_base_datos()
            with clases._conectar_base_datos() as conexion:
                self.assertEqual(conexion.execute("SELECT 1").fetchone()[0], 1)

        self.assertTrue(os.path.isdir(os.path.dirname(ruta)))
        self.assertTrue(os.path.isfile(ruta))


if __name__ == "__main__":
    unittest.main()
