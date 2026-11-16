import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from tkcalendar import DateEntry
from clases import (
    Cliente,
    Prestamo,
    _ruta_base_datos,
    actualizar_mensualidad_prestamista,
    agregar_usuario,
    cambiar_contrasena_usuario,
    cambiar_estado_prestamista,
    cargar_clientes_sql as cargar_clientes,
    cargar_prestamos_sql as cargar_prestamos,
    crear_backup_base_datos,
    crear_cuenta_prestamista_con_mensualidad,
    guardar_clientes_sql as guardar_clientes,
    guardar_prestamos_sql as guardar_prestamos,
    historial_pagos_prestamista,
    listar_usuarios,
    obtener_cuentas_prestamistas,
    obtener_usuario_autenticado,
    renovar_suscripcion_prestamista,
    restablecer_contrasena_usuario,
)
from datetime import date, datetime
import os
import re
import secrets
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fpdf import FPDF


def ruta_recurso(nombre):
    carpeta = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(carpeta, nombre)


def configurar_estilos(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "TButton",
        font=("Segoe UI", 10, "bold"),
        padding=(12, 9),
        relief="flat",
        borderwidth=0,
        background="#e8efeb",
        foreground="#18352a",
    )
    style.map(
        "TButton",
        background=[("active", "#dce8e1"), ("pressed", "#d0dfd6")],
    )
    style.configure(
        "Bank.TButton",
        font=("Segoe UI", 10, "bold"),
        padding=(12, 10),
        relief="flat",
        borderwidth=0,
        background="#147a55",
        foreground="#ffffff",
    )
    style.map("Bank.TButton", background=[("active", "#106544"), ("pressed", "#0c573a")])
    style.configure(
        "Secondary.TButton",
        font=("Segoe UI", 10, "bold"),
        padding=(12, 10),
        relief="flat",
        borderwidth=0,
        background="#334b40",
        foreground="#ffffff",
    )
    style.map("Secondary.TButton", background=[("active", "#263b32"), ("pressed", "#1d3028")])
    style.configure(
        "Action.TButton",
        font=("Segoe UI", 10, "bold"),
        padding=(10, 11),
        relief="flat",
        borderwidth=0,
        background="#ffffff",
        foreground="#18352a",
    )
    style.map("Action.TButton", background=[("active", "#e8f1ec"), ("pressed", "#dce8e1")])
    style.configure("TEntry", font=("Segoe UI", 11), padding=8)
    return style


class PrestamoApp(tk.Toplevel):
    def __init__(
        self,
        master,
        usuario_actual=None,
        rol_actual=None,
        tenant_id=1,
        nombre_empresa="Rijo Express",
    ):
        super().__init__(master)
        self.title(f"Rijo Express - {nombre_empresa}")
        self.geometry("1080x760")
        self.minsize(860, 660)
        self.resizable(True, True)
        self.configure(bg="#f4f7f5")

        self.usuario_actual = usuario_actual
        self.rol_actual = rol_actual
        self.tenant_id = tenant_id
        self.nombre_empresa = nombre_empresa

        self.style = configurar_estilos(self)

        self.clientes = {}
        self.prestamos = {}
        self.cargar_datos()
        self.crear_interfaz()

    def darken_color(self, hex_color):
        # Función simple para oscurecer color
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        darkened = tuple(max(0, c - 30) for c in rgb)
        return f"#{darkened[0]:02x}{darkened[1]:02x}{darkened[2]:02x}"

    def cargar_datos(self):
        self.clientes = cargar_clientes(self.tenant_id)
        self.prestamos = cargar_prestamos(self.tenant_id)

    def crear_interfaz(self):
        header_frame = tk.Frame(self, bg="#103c2d", height=116)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        logo_original = tk.PhotoImage(master=self, file=ruta_recurso("logo_rijo_express.png"))
        self.logo_header = logo_original.subsample(4, 4)
        tk.Label(header_frame, image=self.logo_header, bg="#103c2d").pack(
            side="left",
            padx=24,
            pady=6,
        )

        header_copy = tk.Frame(header_frame, bg="#103c2d")
        header_copy.pack(side="left", pady=23)
        tk.Label(
            header_copy,
            text="Panel de control",
            font=("Segoe UI", 21, "bold"),
            fg="#ffffff",
            bg="#103c2d",
        ).pack(anchor="w")
        tk.Label(
            header_copy,
            text=(
                f"{self.nombre_empresa} · Sesión de {self.usuario_actual}"
                if self.usuario_actual
                else "Gestión clara de clientes, préstamos y pagos"
            ),
            font=("Segoe UI", 10),
            fg="#c5ddd1",
            bg="#103c2d",
        ).pack(anchor="w")

        ttk.Button(
            header_frame,
            text="Pantalla completa",
            command=self.toggle_fullscreen,
            style="Secondary.TButton",
        ).pack(side="right", padx=(0, 12), pady=23)
        ttk.Button(
            header_frame,
            text="Cerrar sesión",
            command=self.cerrar_sesion,
            style="Secondary.TButton",
        ).pack(side="right", padx=(0, 20), pady=23)

        main_frame = tk.Frame(self, bg="#f4f7f5")
        main_frame.pack(expand=True, fill="both", padx=28, pady=(22, 12))

        tk.Label(
            main_frame,
            text="Resumen de cartera",
            font=("Segoe UI", 19, "bold"),
            bg="#f4f7f5",
            fg="#18352a",
        ).pack(anchor="w")
        tk.Label(
            main_frame,
            text="Indicadores principales de Rijo Express",
            font=("Segoe UI", 10),
            bg="#f4f7f5",
            fg="#687a71",
        ).pack(anchor="w", pady=(2, 14))

        stats_frame = tk.Frame(main_frame, bg="#f4f7f5")
        stats_frame.pack(fill="x", pady=(0, 16))
        metricas = [
            ("Clientes", len(self.clientes), "label_clientes", "#147a55"),
            ("Préstamos", len(self.prestamos), "label_prestamos", "#315e9e"),
            ("Activos", self.contar_prestamos_activos(), "label_activos", "#147a55"),
            ("En mora", self.contar_prestamos_mora(), "label_mora", "#bd4b3b"),
            ("Ingresos acumulados", f"${self.calcular_ingresos_totales():,.2f}", "label_ingresos", "#a16c17"),
        ]
        for columna, (titulo, valor, atributo, color) in enumerate(metricas):
            fila = columna // 3
            columna_tarjeta = columna % 3
            tarjeta = tk.Frame(
                stats_frame,
                bg="#ffffff",
                highlightbackground="#e1e9e4",
                highlightthickness=1,
            )
            tarjeta.grid(
                row=fila,
                column=columna_tarjeta,
                sticky="nsew",
                padx=(0 if columna_tarjeta == 0 else 6, 6),
                pady=(0, 6) if fila == 0 else (0, 0),
            )
            stats_frame.columnconfigure(columna_tarjeta, weight=1, uniform="metricas")
            tk.Label(
                tarjeta,
                text=titulo,
                font=("Segoe UI", 9, "bold"),
                bg="#ffffff",
                fg="#687a71",
            ).pack(anchor="w", padx=14, pady=(13, 3))
            etiqueta_valor = tk.Label(
                tarjeta,
                text=str(valor),
                font=("Segoe UI", 19, "bold"),
                bg="#ffffff",
                fg=color,
            )
            etiqueta_valor.pack(anchor="w", padx=14, pady=(0, 13))
            setattr(self, atributo, etiqueta_valor)

        alertas_frame = tk.Frame(
            main_frame,
            bg="#fffaf0",
            highlightbackground="#f2e4c9",
            highlightthickness=1,
        )
        alertas_frame.pack(fill="x", pady=(0, 16))
        franja_alerta = tk.Frame(alertas_frame, bg="#d59b35", width=4)
        franja_alerta.pack(side="left", fill="y")
        contenido_alertas = tk.Frame(alertas_frame, bg="#fffaf0")
        contenido_alertas.pack(side="left", fill="both", expand=True, padx=14, pady=11)
        tk.Label(
            contenido_alertas,
            text="Vencimientos próximos",
            font=("Segoe UI", 11, "bold"),
            bg="#fffaf0",
            fg="#72531b",
        ).pack(anchor="w", pady=(0, 3))
        proximos_vencimientos = self.obtener_proximos_vencimientos()
        if proximos_vencimientos:
            for alerta in proximos_vencimientos[:3]:
                tk.Label(
                    contenido_alertas,
                    text=alerta,
                    bg="#fffaf0",
                    fg="#72531b",
                    font=("Segoe UI", 9),
                ).pack(anchor="w", pady=1)
        else:
            tk.Label(
                contenido_alertas,
                text="No hay préstamos por vencer durante los próximos 7 días.",
                bg="#fffaf0",
                fg="#72531b",
                font=("Segoe UI", 9),
            ).pack(anchor="w")

        encabezado_acciones = tk.Frame(main_frame, bg="#f4f7f5")
        encabezado_acciones.pack(fill="x", pady=(0, 8))
        tk.Label(
            encabezado_acciones,
            text="Accesos rápidos",
            font=("Segoe UI", 13, "bold"),
            bg="#f4f7f5",
            fg="#18352a",
        ).pack(side="left")
        tk.Label(
            encabezado_acciones,
            text="Selecciona una tarea para continuar",
            font=("Segoe UI", 9),
            bg="#f4f7f5",
            fg="#687a71",
        ).pack(side="right")

        botones_frame = tk.Frame(main_frame, bg="#f4f7f5")
        botones_frame.pack(fill="x")

        botones = [
            ("Agregar Cliente", self.abrir_agregar_cliente, "Bank.TButton"),
            ("Buscar Cliente", self.abrir_buscar_cliente, "Bank.TButton"),
            ("Ver Clientes", self.abrir_lista_clientes, "Bank.TButton"),
            ("Crear Préstamo", self.abrir_crear_prestamo, "Bank.TButton"),
            ("Editar Préstamo", self.abrir_editar_prestamo, "Bank.TButton"),
            ("Registrar Pago", self.abrir_registrar_pago, "Secondary.TButton"),
            ("Ver Préstamos Activos", self.mostrar_prestamos_activos, "Bank.TButton"),
            ("Generar Reporte", self.mostrar_reportes, "Bank.TButton"),
            ("Generar Contrato PDF", self.generar_contrato_pdf, "Bank.TButton"),
            ("Configurar Notificaciones", self.configurar_notificaciones, "Secondary.TButton"),
            ("Backup de Datos", self.hacer_backup, "Secondary.TButton"),
        ]

        # La gestión de suscripciones solo está disponible para el administrador.
        if self.rol_actual == 'admin':
            botones.append(("Gestionar cuentas", self.abrir_gestion_usuarios, "Secondary.TButton"))

        for index, (texto, comando, estilo) in enumerate(botones):
            fila = index // 3
            columna = index % 3
            estilo_boton = "Action.TButton" if estilo == "Bank.TButton" else estilo
            boton = ttk.Button(botones_frame, text=texto, command=comando, style=estilo_boton)
            boton.grid(row=fila, column=columna, padx=5, pady=5, sticky="ew")

        botones_frame.columnconfigure(0, weight=1)
        botones_frame.columnconfigure(1, weight=1)
        botones_frame.columnconfigure(2, weight=1)

        footer = tk.Label(
            main_frame,
            text="Rijo Express  ·  Administración de cartera",
            font=("Segoe UI", 8),
            bg="#f4f7f5",
            fg="#85938c",
        )
        footer.pack(side="bottom", pady=(10, 0))

    def contar_prestamos_activos(self):
        return sum(1 for prestamo in self.prestamos.values() if prestamo.saldo_pendiente > 0)

    def contar_prestamos_mora(self):
        hoy = datetime.now().date()
        return sum(1 for prestamo in self.prestamos.values() if prestamo.saldo_pendiente > 0 and datetime.strptime(prestamo.fecha_vencimiento, "%Y-%m-%d").date() < hoy)

    def calcular_ingresos_totales(self):
        total = 0
        for prestamo in self.prestamos.values():
            for pago in prestamo.pagos:
                total += pago.get('monto', 0)
        return total

    def obtener_proximos_vencimientos(self):
        hoy = datetime.now().date()
        proximos = []
        for id_prestamo, prestamo in self.prestamos.items():
            if prestamo.saldo_pendiente > 0:
                fecha_venc = datetime.strptime(prestamo.fecha_vencimiento, "%Y-%m-%d").date()
                if fecha_venc >= hoy and (fecha_venc - hoy).days <= 7:  # Próximos 7 días
                    cliente = self.clientes.get(prestamo.id_cliente)
                    nombre_cliente = cliente.nombre if cliente else "Desconocido"
                    proximos.append(f"Préstamo {id_prestamo} de {nombre_cliente} vence el {fecha_venc}")
        return sorted(proximos, key=lambda x: x.split()[-1])  # Ordenar por fecha

    def actualizar_estadisticas(self):
        self.label_clientes.config(text=str(len(self.clientes)))
        self.label_prestamos.config(text=str(len(self.prestamos)))
        self.label_activos.config(text=str(self.contar_prestamos_activos()))
        self.label_mora.config(text=str(self.contar_prestamos_mora()))
        self.label_ingresos.config(text=f"${self.calcular_ingresos_totales():,.2f}")

    def abrir_agregar_cliente(self):
        ventana = tk.Toplevel(self)
        ventana.title("Rijo Express - Agregar Cliente")
        ventana.geometry("420x240")
        ventana.resizable(False, False)
        ventana.configure(bg="#f0f4f8")

        tk.Label(ventana, text="ID del cliente:", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(14, 4))
        entrada_id = ttk.Entry(ventana, font=("Arial", 10))
        entrada_id.pack(fill="x", padx=14)

        tk.Label(ventana, text="Nombre:", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(12, 4))
        entrada_nombre = ttk.Entry(ventana, font=("Arial", 10))
        entrada_nombre.pack(fill="x", padx=14)

        def guardar_cliente():
            id_cliente = entrada_id.get().strip()
            nombre = entrada_nombre.get().strip()
            if not id_cliente or not nombre:
                messagebox.showwarning("Validación", "Ingrese ID y nombre del cliente.")
                return
            if id_cliente in self.clientes:
                messagebox.showerror("Error", "El cliente ya existe.")
                return
            fecha_registro = datetime.now().strftime("%Y-%m-%d")
            self.clientes[id_cliente] = Cliente(id_cliente, nombre, fecha_registro)
            guardar_clientes(self.clientes, self.tenant_id)
            self.actualizar_estadisticas()
            messagebox.showinfo("Éxito", "Cliente agregado correctamente.")
            ventana.destroy()

        ttk.Button(ventana, text="Guardar Cliente", command=guardar_cliente).pack(pady=18, padx=14, fill="x")

    def abrir_crear_prestamo(self):
        ventana = tk.Toplevel(self)
        ventana.title("Rijo Express - Crear Préstamo")
        ventana.geometry("420x500")
        ventana.resizable(False, False)
        ventana.configure(bg="#f0f4f8")

        campos = [
            ("ID del préstamo:", "id_prestamo"),
            ("ID del cliente:", "id_cliente"),
            ("Monto:", "monto")
        ]

        entradas = {}
        for label_text, key in campos:
            tk.Label(ventana, text=label_text, anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
            entry = ttk.Entry(ventana, font=("Arial", 10))
            entry.pack(fill="x", padx=14)
            entradas[key] = entry

        # Fecha inicio con calendario
        tk.Label(ventana, text="Fecha inicio:", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
        fecha_inicio_entry = DateEntry(ventana, width=12, background='darkblue', foreground='white', borderwidth=2, date_pattern='yyyy-mm-dd')
        fecha_inicio_entry.pack(fill="x", padx=14)
        entradas["fecha_inicio"] = fecha_inicio_entry

        # Número de períodos con barra deslizante
        tk.Label(ventana, text="Número de períodos:", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
        num_periodos_var = tk.IntVar(value=1)
        num_periodos_scale = tk.Scale(ventana, from_=1, to=52, orient="horizontal", variable=num_periodos_var, bg="#f0f4f8", highlightbackground="#f0f4f8")
        num_periodos_scale.pack(fill="x", padx=14)
        entradas["num_periodos"] = num_periodos_var

        # Label para mostrar el valor
        label_num_periodos = tk.Label(ventana, text="1", anchor="w", bg="#f0f4f8", font=("Arial", 10))
        label_num_periodos.pack(fill="x", padx=14)
        num_periodos_var.trace("w", lambda *args: (label_num_periodos.config(text=str(num_periodos_var.get())), calcular_total()))

        # Periodo de pago
        tk.Label(ventana, text="Periodo de pago:", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
        periodo_combo = ttk.Combobox(ventana, values=["Semanal", "Quincenal", "Mensual"], state="readonly", font=("Arial", 10))
        periodo_combo.pack(fill="x", padx=14)
        periodo_combo.set("Semanal")
        entradas["periodo"] = periodo_combo

        # Tasa interés
        tk.Label(ventana, text="Tasa interés (%):", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
        entrada_tasa = ttk.Entry(ventana, font=("Arial", 10))
        entrada_tasa.pack(fill="x", padx=14)
        entradas["tasa_interes"] = entrada_tasa

        # Tasa mora
        tk.Label(ventana, text="Tasa mora (%):", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
        entrada_mora = ttk.Entry(ventana, font=("Arial", 10))
        entrada_mora.pack(fill="x", padx=14)
        entradas["tasa_mora"] = entrada_mora

        # Label para monto total
        tk.Label(ventana, text="Monto total con interés:", anchor="w", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
        label_total = tk.Label(ventana, text="0.00", anchor="w", bg="#f0f4f8", font=("Arial", 10))
        label_total.pack(fill="x", padx=14)
        entradas["label_total"] = label_total

        # Botón para ver tabla de amortización
        ttk.Button(ventana, text="Ver Tabla de Amortización", command=lambda: self.mostrar_tabla_amortizacion(entradas)).pack(pady=10, padx=14, fill="x")

    def mostrar_tabla_amortizacion(self, entradas):
        try:
            monto = float(entradas["monto"].get() or 0)
            tasa = float(entrada_tasa.get() or 0) / 100
            num_periodos = num_periodos_var.get()
            if monto <= 0 or tasa < 0 or num_periodos <= 0:
                messagebox.showwarning("Validación", "Ingrese valores válidos.")
                return
        except ValueError:
            messagebox.showwarning("Validación", "Valores inválidos.")
            return

        ventana_tabla = tk.Toplevel(self)
        ventana_tabla.title("Tabla de Amortización")
        ventana_tabla.geometry("600x400")

        texto = tk.Text(ventana_tabla, wrap="word", padx=12, pady=12, font=("Courier", 10))
        texto.pack(expand=True, fill="both")

        texto.insert("end", "TABLA DE AMORTIZACIÓN\n\n")
        texto.insert("end", f"Monto: ${monto:.2f}\n")
        texto.insert("end", f"Tasa anual: {tasa*100:.2f}%\n")
        texto.insert("end", f"Número de períodos: {num_periodos}\n\n")

        texto.insert("end", "Período | Cuota | Interés | Capital | Saldo\n")
        texto.insert("end", "-" * 50 + "\n")

        saldo = monto
        cuota_total = monto * (1 + tasa * num_periodos) / num_periodos  # Simplificada

        for i in range(1, num_periodos + 1):
            interes = saldo * tasa
            capital = cuota_total - interes
            saldo -= capital
            texto.insert("end", f"{i:7} | {cuota_total:5.2f} | {interes:6.2f} | {capital:6.2f} | {saldo:5.2f}\n")

        texto.configure(state="disabled")

        def actualizar_tasa(event=None):
            periodo = periodo_combo.get()
            if periodo == "Semanal":
                tasa = "10"
                max_periodos = 52
            elif periodo == "Quincenal":
                tasa = "20"
                max_periodos = 24
            else:
                tasa = "30"
                max_periodos = 12
            entrada_tasa.delete(0, "end")
            entrada_tasa.insert(0, tasa)
            num_periodos_scale.config(to=max_periodos)
            if num_periodos_var.get() > max_periodos:
                num_periodos_var.set(max_periodos)
            calcular_total()

        def calcular_total():
            try:
                monto = float(entradas["monto"].get() or 0)
                tasa = float(entrada_tasa.get() or 0)
                num_periodos = num_periodos_var.get()
                total = monto * (1 + (tasa / 100) * num_periodos)
                label_total.config(text=f"{total:.2f}")
            except ValueError:
                label_total.config(text="0.00")

        periodo_combo.bind("<<ComboboxSelected>>", actualizar_tasa)
        entradas["monto"].bind("<KeyRelease>", lambda e: calcular_total())
        entrada_tasa.bind("<KeyRelease>", lambda e: calcular_total())
        num_periodos_entry.bind("<KeyRelease>", lambda e: calcular_total())
        actualizar_tasa()

        # Botón guardar más prominente
        ttk.Button(ventana, text="Crear Préstamo", command=lambda: self.guardar_prestamo(ventana, entradas)).pack(pady=20, padx=14, fill="x")

        # Botón cancelar
        ttk.Button(ventana, text="Cancelar", command=ventana.destroy).pack(pady=(0, 10), padx=14, fill="x")

    def abrir_buscar_cliente(self):
        ventana = tk.Toplevel(self)
        ventana.title("Buscar Cliente")
        ventana.geometry("400x300")
        ventana.resizable(False, False)

        tk.Label(ventana, text="Buscar por ID o Nombre:", anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        entrada_busqueda = ttk.Entry(ventana)
        entrada_busqueda.pack(fill="x", padx=14)

        texto_resultados = tk.Text(ventana, wrap="word", padx=8, pady=8, height=10)
        texto_resultados.pack(expand=True, fill="both", padx=14, pady=8)

        def buscar():
            query = entrada_busqueda.get().strip().lower()
            resultados = []
            for cliente in self.clientes.values():
                if query in cliente.id_cliente.lower() or query in cliente.nombre.lower():
                    resultados.append(f"ID: {cliente.id_cliente}\nNombre: {cliente.nombre}\nRegistro: {cliente.fecha_registro}\n---\n")
            texto_resultados.delete("1.0", "end")
            if resultados:
                texto_resultados.insert("1.0", "".join(resultados))
            else:
                texto_resultados.insert("1.0", "No se encontraron clientes.")

        ttk.Button(ventana, text="Buscar", command=buscar).pack(pady=(0, 10), padx=14, fill="x")

    def abrir_lista_clientes(self):
        ventana = tk.Toplevel(self)
        ventana.title(f"Clientes - {self.nombre_empresa}")
        ventana.geometry("760x480")
        ventana.minsize(620, 360)
        ventana.configure(bg="#f4f7f5")

        tk.Label(
            ventana,
            text=f"Clientes de {self.nombre_empresa}",
            font=("Segoe UI", 16, "bold"),
            bg="#f4f7f5",
            fg="#18352a",
        ).pack(anchor="w", padx=18, pady=(16, 8))

        controles = ttk.Frame(ventana)
        controles.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Label(controles, text="Buscar por ID o nombre:").pack(side="left", padx=(0, 8))
        entrada_busqueda = ttk.Entry(controles)
        entrada_busqueda.pack(side="left", fill="x", expand=True)

        contenedor = ttk.Frame(ventana)
        contenedor.pack(expand=True, fill="both", padx=18, pady=(0, 8))
        columnas = ("id", "nombre", "fecha")
        tabla = ttk.Treeview(contenedor, columns=columnas, show="headings")
        for columna, titulo, ancho in [
            ("id", "ID del cliente", 150),
            ("nombre", "Nombre", 360),
            ("fecha", "Fecha de registro", 160),
        ]:
            tabla.heading(columna, text=titulo)
            tabla.column(columna, width=ancho, minwidth=80, anchor="w")
        barra = ttk.Scrollbar(contenedor, orient="vertical", command=tabla.yview)
        tabla.configure(yscrollcommand=barra.set)
        tabla.pack(side="left", expand=True, fill="both")
        barra.pack(side="right", fill="y")

        estado = tk.Label(
            ventana,
            text="",
            bg="#f4f7f5",
            fg="#687a71",
            anchor="w",
        )
        estado.pack(fill="x", padx=18, pady=(0, 12))

        def recargar(event=None):
            filtro = entrada_busqueda.get().strip().casefold()
            tabla.delete(*tabla.get_children())
            clientes = sorted(
                self.clientes.values(),
                key=lambda cliente: cliente.nombre.casefold(),
            )
            visibles = 0
            for cliente in clientes:
                id_cliente = str(cliente.id_cliente)
                nombre = str(cliente.nombre)
                if filtro and filtro not in id_cliente.casefold() and filtro not in nombre.casefold():
                    continue
                tabla.insert(
                    "",
                    "end",
                    values=(id_cliente, nombre, cliente.fecha_registro),
                )
                visibles += 1
            estado.config(text=f"{visibles} de {len(clientes)} clientes")

        entrada_busqueda.bind("<KeyRelease>", recargar)
        recargar()
        entrada_busqueda.focus_set()

    def abrir_editar_prestamo(self):
        ventana = tk.Toplevel(self)
        ventana.title("Editar Préstamo")
        ventana.geometry("400x400")
        ventana.resizable(False, False)

        tk.Label(ventana, text="ID del préstamo a editar:", anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        entrada_id = ttk.Entry(ventana)
        entrada_id.pack(fill="x", padx=14)

        campos_frame = tk.Frame(ventana)
        campos_frame.pack(pady=10)

        campos = [
            ("Monto:", "monto"),
            ("Tasa interés (%):", "tasa_interes")
        ]

        entradas = {}
        for label_text, key in campos:
            tk.Label(campos_frame, text=label_text, anchor="w").pack(fill="x", padx=4, pady=(4, 2))
            entry = ttk.Entry(campos_frame)
            entry.pack(fill="x", padx=4)
            entradas[key] = entry

        # Fecha inicio con calendario
        tk.Label(campos_frame, text="Fecha inicio:", anchor="w").pack(fill="x", padx=4, pady=(4, 2))
        fecha_inicio_entry = DateEntry(campos_frame, width=12, background='darkblue', foreground='white', borderwidth=2, date_pattern='yyyy-mm-dd')
        fecha_inicio_entry.pack(fill="x", padx=4)
        entradas["fecha_inicio"] = fecha_inicio_entry

        # Fecha vencimiento con calendario
        tk.Label(campos_frame, text="Fecha vencimiento:", anchor="w").pack(fill="x", padx=4, pady=(4, 2))
        fecha_vencimiento_entry = DateEntry(campos_frame, width=12, background='darkblue', foreground='white', borderwidth=2, date_pattern='yyyy-mm-dd')
        fecha_vencimiento_entry.pack(fill="x", padx=4)
        entradas["fecha_vencimiento"] = fecha_vencimiento_entry

        def cargar_prestamo():
            id_prestamo = entrada_id.get().strip()
            if id_prestamo not in self.prestamos:
                messagebox.showerror("Error", "Préstamo no encontrado.")
                return
            prestamo = self.prestamos[id_prestamo]
            entradas["monto"].delete(0, "end")
            entradas["monto"].insert(0, str(prestamo.monto))
            entradas["tasa_interes"].delete(0, "end")
            entradas["tasa_interes"].insert(0, str(prestamo.tasa_interes))
            # Setear fechas en DateEntry
            from datetime import datetime
            fecha_inicio_dt = datetime.strptime(prestamo.fecha_inicio, "%Y-%m-%d")
            fecha_vencimiento_dt = datetime.strptime(prestamo.fecha_vencimiento, "%Y-%m-%d")
            entradas["fecha_inicio"].set_date(fecha_inicio_dt)
            entradas["fecha_vencimiento"].set_date(fecha_vencimiento_dt)

        ttk.Button(ventana, text="Cargar Préstamo", command=cargar_prestamo).pack(pady=(0, 10), padx=14, fill="x")

        def guardar_cambios():
            id_prestamo = entrada_id.get().strip()
            if id_prestamo not in self.prestamos:
                messagebox.showerror("Error", "Préstamo no encontrado.")
                return
            try:
                monto = float(entradas["monto"].get())
                tasa_interes = float(entradas["tasa_interes"].get())
                if monto <= 0 or tasa_interes < 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Validación", "Ingrese valores positivos.")
                return
            fecha_inicio = entradas["fecha_inicio"].get_date().strftime("%Y-%m-%d")
            fecha_vencimiento = entradas["fecha_vencimiento"].get_date().strftime("%Y-%m-%d")
            if fecha_vencimiento <= fecha_inicio:
                messagebox.showwarning("Validación", "Fecha de vencimiento debe ser posterior.")
                return
            prestamo = self.prestamos[id_prestamo]
            prestamo.monto = monto
            prestamo.tasa_interes = tasa_interes
            prestamo.fecha_inicio = fecha_inicio
            prestamo.fecha_vencimiento = fecha_vencimiento
            guardar_prestamos(self.prestamos, self.tenant_id)
            messagebox.showinfo("Éxito", "Préstamo actualizado.")
            ventana.destroy()

        ttk.Button(ventana, text="Guardar Cambios", command=guardar_cambios).pack(pady=(0, 10), padx=14, fill="x")

    def exportar_datos(self):
        import os
        try:
            with open("clientes_export.csv", "w", newline="") as f:
                f.write("id_cliente,nombre,fecha_registro\n")
                for cliente in self.clientes.values():
                    f.write(f"{cliente.id_cliente},{cliente.nombre},{cliente.fecha_registro}\n")
            with open("prestamos_export.csv", "w", newline="") as f:
                f.write("id_prestamo,id_cliente,monto,tasa_interes,fecha_inicio,fecha_vencimiento,saldo_pendiente,pagos\n")
                for prestamo in self.prestamos.values():
                    f.write(f"{prestamo.id_prestamo},{prestamo.id_cliente},{prestamo.monto},{prestamo.tasa_interes},{prestamo.fecha_inicio},{prestamo.fecha_vencimiento},{prestamo.saldo_pendiente},{str(prestamo.pagos)}\n")
            messagebox.showinfo("Éxito", "Datos exportados a clientes_export.csv y prestamos_export.csv")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar: {str(e)}")

    def toggle_fullscreen(self):
        if self.state() == "zoomed":
            self.state("normal")
        else:
            self.state("zoomed")

    def guardar_prestamo(self, ventana, entradas):
        id_prestamo = entradas["id_prestamo"].get().strip()
        id_cliente = entradas["id_cliente"].get().strip()
        if not id_prestamo or not id_cliente:
            messagebox.showwarning("Validación", "Ingrese ID de préstamo y cliente.")
            return
        if id_prestamo in self.prestamos:
            messagebox.showerror("Error", "El préstamo ya existe.")
            return
        if id_cliente not in self.clientes:
            messagebox.showerror("Error", "Cliente no encontrado.")
            return
        try:
            monto = float(entradas["monto"].get())
            tasa_interes = float(entradas["tasa_interes"].get())
            num_periodos = int(entradas["num_periodos"].get())
            tasa_mora = float(entradas["tasa_mora"].get() or 0)
            if monto <= 0 or tasa_interes < 0 or num_periodos <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Validación", "Ingrese valores positivos.")
            return
        fecha_inicio = entradas["fecha_inicio"].get_date().strftime("%Y-%m-%d")
        periodo = entradas["periodo"].get()
        # Calcular fecha_vencimiento
        from datetime import timedelta
        fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
        if periodo == "Semanal":
            delta = timedelta(weeks=num_periodos)
        elif periodo == "Quincenal":
            delta = timedelta(days=15 * num_periodos)
        else:  # Mensual
            delta = timedelta(days=30 * num_periodos)  # Aproximado
        fecha_vencimiento = (fecha_inicio_dt + delta).strftime("%Y-%m-%d")
        from clases import Prestamo
        prestamo = Prestamo(id_prestamo, id_cliente, monto, tasa_interes, fecha_inicio, fecha_vencimiento, tasa_mora)
        self.prestamos[id_prestamo] = prestamo
        guardar_prestamos(self.prestamos, self.tenant_id)
        self.actualizar_estadisticas()
        messagebox.showinfo("Éxito", "Préstamo creado correctamente.")
        ventana.destroy()

    def abrir_registrar_pago(self):
        ventana = tk.Toplevel(self)
        ventana.title("Registrar Pago")
        ventana.geometry("380x260")
        ventana.resizable(False, False)

        # ID del préstamo
        tk.Label(ventana, text="ID del préstamo:", anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        entrada_id = ttk.Entry(ventana)
        entrada_id.pack(fill="x", padx=14)

        # Fecha pago con calendario
        tk.Label(ventana, text="Fecha pago:", anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        fecha_entry = DateEntry(ventana, width=12, background='darkblue', foreground='white', borderwidth=2, date_pattern='yyyy-mm-dd')
        fecha_entry.pack(fill="x", padx=14)

        # Monto pago
        tk.Label(ventana, text="Monto pago:", anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        entrada_monto = ttk.Entry(ventana)
        entrada_monto.pack(fill="x", padx=14)

        def guardar_pago():
            id_prestamo = entrada_id.get().strip()
            if id_prestamo not in self.prestamos:
                messagebox.showerror("Error", "Préstamo no encontrado.")
                return
            fecha = fecha_entry.get_date().strftime("%Y-%m-%d")
            try:
                monto = float(entrada_monto.get())
            except ValueError:
                messagebox.showwarning("Validación", "Ingrese un monto numérico.")
                return
            try:
                self.prestamos[id_prestamo].registrar_pago(fecha, monto)
                guardar_prestamos(self.prestamos, self.tenant_id)
                self.actualizar_estadisticas()
                messagebox.showinfo("Éxito", "Pago registrado correctamente.")
                ventana.destroy()
            except ValueError as error:
                messagebox.showerror("Error", str(error))

        ttk.Button(ventana, text="Guardar", command=guardar_pago).pack(pady=18)

    def mostrar_prestamos_activos(self):
        ventana = tk.Toplevel(self)
        ventana.title("Préstamos Activos")
        ventana.geometry("720x420")
        ventana.resizable(False, False)

        texto = tk.Text(ventana, wrap="word", padx=12, pady=12)
        texto.pack(expand=True, fill="both")

        activos = [p for p in self.prestamos.values() if p.saldo_pendiente > 0]
        if not activos:
            texto.insert("1.0", "No hay préstamos activos en este momento.")
        else:
            for p in activos:
                cliente = self.clientes.get(p.id_cliente)
                linea = f"Préstamo ID: {p.id_prestamo}\nCliente: {cliente.nombre if cliente else 'Desconocido'} ({p.id_cliente})\nMonto: {p.monto}\nSaldo pendiente: {p.saldo_pendiente}\nFecha inicio: {p.fecha_inicio}\nFecha vencimiento: {p.fecha_vencimiento}\n---\n"
                texto.insert("end", linea)
        texto.configure(state="disabled")

    def mostrar_reportes(self):
        ventana = tk.Toplevel(self)
        ventana.title("Reportes Avanzados")
        ventana.geometry("800x600")
        ventana.resizable(False, False)

        tk.Label(ventana, text="Seleccione tipo de reporte:", font=("Arial", 12, "bold")).pack(pady=10)

        tipo_reporte = ttk.Combobox(ventana, values=["General", "Mora", "Ingresos", "Cartera"], state="readonly")
        tipo_reporte.pack(pady=5)
        tipo_reporte.set("General")

        texto = tk.Text(ventana, wrap="word", padx=12, pady=12, font=("Arial", 10))
        texto.pack(expand=True, fill="both", padx=20, pady=10)

        def generar_reporte():
            tipo = tipo_reporte.get()
            texto.delete("1.0", "end")
            if tipo == "General":
                activos = [p for p in self.prestamos.values() if p.saldo_pendiente > 0]
                texto.insert("end", f"REPORTE GENERAL - {datetime.now().strftime('%Y-%m-%d')}\n\n")
                texto.insert("end", f"Total clientes: {len(self.clientes)}\n")
                texto.insert("end", f"Total préstamos: {len(self.prestamos)}\n")
                texto.insert("end", f"Préstamos activos: {len(activos)}\n")
                texto.insert("end", f"Préstamos en mora: {self.contar_prestamos_mora()}\n")
                texto.insert("end", f"Ingresos totales: ${self.calcular_ingresos_totales():.2f}\n\n")
                texto.insert("end", "DETALLE DE PRÉSTAMOS ACTIVOS:\n")
                for p in activos:
                    cliente = self.clientes.get(p.id_cliente)
                    texto.insert("end", f"- ID: {p.id_prestamo}, Cliente: {cliente.nombre if cliente else 'Desconocido'}, Monto: {p.monto}, Saldo: {p.saldo_pendiente}\n")
            elif tipo == "Mora":
                morosos = [p for p in self.prestamos.values() if p.saldo_pendiente > 0 and datetime.strptime(p.fecha_vencimiento, "%Y-%m-%d").date() < datetime.now().date()]
                texto.insert("end", f"REPORTE DE MORA - {datetime.now().strftime('%Y-%m-%d')}\n\n")
                texto.insert("end", f"Préstamos en mora: {len(morosos)}\n\n")
                for p in morosos:
                    cliente = self.clientes.get(p.id_cliente)
                    dias_mora = (datetime.now().date() - datetime.strptime(p.fecha_vencimiento, "%Y-%m-%d").date()).days
                    texto.insert("end", f"- ID: {p.id_prestamo}, Cliente: {cliente.nombre if cliente else 'Desconocido'}, Días en mora: {dias_mora}, Saldo: {p.saldo_pendiente}\n")
            elif tipo == "Ingresos":
                texto.insert("end", f"REPORTE DE INGRESOS - {datetime.now().strftime('%Y-%m-%d')}\n\n")
                total_ingresos = 0
                for p in self.prestamos.values():
                    ingresos_prestamo = sum(pago.get('monto', 0) for pago in p.pagos)
                    total_ingresos += ingresos_prestamo
                    if ingresos_prestamo > 0:
                        cliente = self.clientes.get(p.id_cliente)
                        texto.insert("end", f"- Préstamo {p.id_prestamo} ({cliente.nombre if cliente else 'Desconocido'}): ${ingresos_prestamo:.2f}\n")
                texto.insert("end", f"\nTOTAL INGRESOS: ${total_ingresos:.2f}\n")
            elif tipo == "Cartera":
                texto.insert("end", f"REPORTE DE CARTERA - {datetime.now().strftime('%Y-%m-%d')}\n\n")
                total_cartera = sum(p.saldo_pendiente for p in self.prestamos.values() if p.saldo_pendiente > 0)
                texto.insert("end", f"Valor total de la cartera: ${total_cartera:.2f}\n\n")
                for p in self.prestamos.values():
                    if p.saldo_pendiente > 0:
                        cliente = self.clientes.get(p.id_cliente)
                        texto.insert("end", f"- {p.id_prestamo}: {cliente.nombre if cliente else 'Desconocido'} - Saldo: ${p.saldo_pendiente:.2f}\n")

        ttk.Button(ventana, text="Generar Reporte", command=generar_reporte).pack(pady=10)

        # Botón exportar
        ttk.Button(ventana, text="Exportar a TXT", command=lambda: self.exportar_reporte(texto.get("1.0", "end"))).pack(pady=5)

    def configurar_notificaciones(self):
        ventana = tk.Toplevel(self)
        ventana.title("Configurar Notificaciones por Email")
        ventana.geometry("400x300")
        ventana.resizable(False, False)
        ventana.configure(bg="#f0f4f8")

        tk.Label(ventana, text="Email remitente:", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(pady=5)
        entry_email = ttk.Entry(ventana)
        entry_email.pack(fill="x", padx=20)

        tk.Label(ventana, text="Contraseña:", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(pady=5)
        entry_pass = ttk.Entry(ventana, show="*")
        entry_pass.pack(fill="x", padx=20)

        tk.Label(ventana, text="Email destinatario:", bg="#f0f4f8", font=("Arial", 10, "bold")).pack(pady=5)
        entry_dest = ttk.Entry(ventana)
        entry_dest.pack(fill="x", padx=20)

        def guardar_config():
            self.email_config = {
                'remitente': entry_email.get().strip(),
                'password': entry_pass.get().strip(),
                'destinatario': entry_dest.get().strip()
            }
            messagebox.showinfo("Éxito", "Configuración guardada.")
            ventana.destroy()

        ttk.Button(ventana, text="Guardar Configuración", command=guardar_config).pack(pady=10)

        ttk.Button(ventana, text="Enviar Alertas Ahora", command=self.enviar_alertas_email).pack(pady=5)

    def enviar_alertas_email(self):
        if not hasattr(self, 'email_config') or not self.email_config['remitente']:
            messagebox.showwarning("Configuración", "Configure el email primero.")
            return

        proximos = self.obtener_proximos_vencimientos()
        if not proximos:
            messagebox.showinfo("Alertas", "No hay alertas pendientes.")
            return

        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_config['remitente']
            msg['To'] = self.email_config['destinatario']
            msg['Subject'] = "Alertas de Vencimiento - Rijo Express"

            body = "Alertas de préstamos próximos a vencer:\n\n" + "\n".join(proximos)
            msg.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP('smtp.gmail.com', 587)  # Para Gmail, cambiar si es otro
            server.starttls()
            server.login(self.email_config['remitente'], self.email_config['password'])
            text = msg.as_string()
            server.sendmail(self.email_config['remitente'], self.email_config['destinatario'], text)
            server.quit()

            messagebox.showinfo("Éxito", "Alertas enviadas por email.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo enviar el email: {str(e)}")

    def hacer_backup(self):
        carpeta = filedialog.askdirectory(
            parent=self,
            title="Selecciona la memoria USB para guardar la copia",
        )
        if not carpeta:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = os.path.join(carpeta, f"RijoExpress-backup-{timestamp}.db")
        try:
            crear_backup_base_datos(destino)
            messagebox.showinfo("Copia completada", f"Respaldo de la base de datos guardado en:\n{destino}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo crear la copia de seguridad: {str(e)}")

    def hacer_backup_auto(self):
        backup_dir = os.path.join(os.path.dirname(_ruta_base_datos()), "backup")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(backup_dir, exist_ok=True)
        return crear_backup_base_datos(
            os.path.join(backup_dir, f"RijoExpress-auto-{timestamp}.db")
        )

    def cerrar_aplicacion(self):
        self._guardar_respaldo_al_cerrar()
        self.master.destroy()

    def cerrar_sesion(self):
        self._guardar_respaldo_al_cerrar()
        login = self.master
        self.destroy()
        login.entry_usuario.delete(0, "end")
        login.entry_contrasena.delete(0, "end")
        login.modo_admin = False
        login.actualizar_modo()
        login.deiconify()
        login.lift()
        login.entry_usuario.focus_set()

    def _guardar_respaldo_al_cerrar(self):
        try:
            self.hacer_backup_auto()
        except Exception as error:
            messagebox.showerror(
                "Error de copia",
                f"No se pudo crear el respaldo automático:\n{error}",
                parent=self,
            )

    def generar_contrato_pdf(self):
        ventana = tk.Toplevel(self)
        ventana.title("Generar Contrato PDF")
        ventana.geometry("400x200")
        ventana.resizable(False, False)

        tk.Label(ventana, text="ID del préstamo:", anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        entry_id = ttk.Entry(ventana)
        entry_id.pack(fill="x", padx=14)

        def crear_pdf():
            id_prestamo = entry_id.get().strip()
            if id_prestamo not in self.prestamos:
                messagebox.showerror("Error", "Préstamo no encontrado.")
                return

            prestamo = self.prestamos[id_prestamo]
            cliente = self.clientes.get(prestamo.id_cliente)

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)

            pdf.cell(200, 10, txt="CONTRATO DE PRÉSTAMO", ln=True, align='C')
            pdf.cell(200, 10, txt="Rijo Express - Plataforma Bancaria", ln=True, align='C')
            pdf.ln(10)

            pdf.cell(200, 10, txt=f"Fecha: {datetime.now().strftime('%Y-%m-%d')}", ln=True)
            pdf.cell(200, 10, txt=f"Cliente: {cliente.nombre if cliente else 'Desconocido'} (ID: {prestamo.id_cliente})", ln=True)
            pdf.cell(200, 10, txt=f"ID Préstamo: {prestamo.id_prestamo}", ln=True)
            pdf.cell(200, 10, txt=f"Monto: ${prestamo.monto:.2f}", ln=True)
            pdf.cell(200, 10, txt=f"Tasa Interés: {prestamo.tasa_interes}%", ln=True)
            pdf.cell(200, 10, txt=f"Tasa Mora: {prestamo.tasa_mora}%", ln=True)
            pdf.cell(200, 10, txt=f"Fecha Inicio: {prestamo.fecha_inicio}", ln=True)
            pdf.cell(200, 10, txt=f"Fecha Vencimiento: {prestamo.fecha_vencimiento}", ln=True)
            pdf.ln(10)

            pdf.cell(200, 10, txt="Términos y Condiciones:", ln=True)
            pdf.multi_cell(0, 10, txt="El cliente se compromete a pagar el monto prestado más intereses según el calendario acordado. En caso de mora, se aplicarán intereses adicionales. Este contrato es legalmente vinculante.")

            archivo = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("Archivo PDF", "*.pdf")])
            if archivo:
                pdf.output(archivo)
                messagebox.showinfo("Éxito", "Contrato PDF generado correctamente.")
                ventana.destroy()

        ttk.Button(ventana, text="Generar PDF", command=crear_pdf).pack(pady=20)

    def exportar_reporte(self, contenido):
        from tkinter import filedialog
        archivo = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Archivo de texto", "*.txt")])
        if archivo:
            with open(archivo, "w", encoding="utf-8") as f:
                f.write(contenido)
            messagebox.showinfo("Éxito", "Reporte exportado correctamente.")

    def abrir_gestion_usuarios(self):
        ventana = tk.Toplevel(self)
        ventana.title("Gestión de cuentas")
        ventana.geometry("900x490")
        ventana.minsize(760, 400)
        ventana.configure(bg="#f0f4f8")
        tk.Label(
            ventana,
            text="Empresas, mensualidades y vencimientos",
            font=("Segoe UI", 16, "bold"),
            bg="#f0f4f8",
            fg="#18352a",
        ).pack(anchor="w", padx=18, pady=(16, 8))
        tk.Label(
            ventana,
            text="Puedes editar el monto por cuenta, confirmar pagos o suspender el acceso.",
            font=("Segoe UI", 9),
            bg="#f0f4f8",
            fg="#687a71",
        ).pack(anchor="w", padx=18, pady=(0, 12))

        contenedor = ttk.Frame(ventana)
        contenedor.pack(expand=True, fill="both", padx=18, pady=(0, 12))
        columnas = ("empresa", "usuario", "mensualidad", "vence", "estado", "pagos", "ultimo")
        tabla = ttk.Treeview(contenedor, columns=columnas, show="headings", selectmode="browse")
        encabezados = [
            ("empresa", "Empresa", 190),
            ("usuario", "Usuario", 130),
            ("mensualidad", "Mensualidad (DOP)", 120),
            ("vence", "Vence", 100),
            ("estado", "Estado", 95),
            ("pagos", "Pagos", 60),
            ("ultimo", "Último pago", 100),
        ]
        for columna, titulo, ancho in encabezados:
            tabla.heading(columna, text=titulo)
            tabla.column(columna, width=ancho, minwidth=60, anchor="w")
        barra = ttk.Scrollbar(contenedor, orient="vertical", command=tabla.yview)
        tabla.configure(yscrollcommand=barra.set)
        tabla.pack(side="left", expand=True, fill="both")
        barra.pack(side="right", fill="y")

        def recargar():
            tabla.delete(*tabla.get_children())
            for cuenta in obtener_cuentas_prestamistas():
                vencimiento = cuenta["suscripcion_hasta"]
                vencida = not vencimiento or vencimiento < date.today().isoformat()
                estado = "Suspendida" if not cuenta["activo"] else "Vencida" if vencida else "Activa"
                tabla.insert(
                    "",
                    "end",
                    iid=str(cuenta["tenant_id"]),
                    values=(
                        cuenta["empresa"],
                        cuenta["usuario"],
                        cuenta["mensualidad"],
                        vencimiento or "—",
                        estado,
                        cuenta["cantidad_pagos"],
                        cuenta["ultimo_pago"] or "—",
                    ),
                )

        def cuenta_seleccionada():
            seleccion = tabla.selection()
            if not seleccion:
                messagebox.showwarning(
                    "Selecciona una cuenta",
                    "Selecciona una cuenta de la lista.",
                    parent=ventana,
                )
                return None
            tenant_id = int(seleccion[0])
            return next(
                (
                    cuenta for cuenta in obtener_cuentas_prestamistas()
                    if cuenta["tenant_id"] == tenant_id
                ),
                None,
            )

        def editar_mensualidad():
            cuenta = cuenta_seleccionada()
            if not cuenta:
                return
            monto = simpledialog.askstring(
                "Editar mensualidad",
                f"Nuevo monto mensual en DOP para {cuenta['empresa']}:",
                initialvalue=cuenta["mensualidad"],
                parent=ventana,
            )
            if monto is None:
                return
            try:
                if not actualizar_mensualidad_prestamista(cuenta["tenant_id"], monto):
                    raise ValueError("No se encontró la cuenta.")
            except ValueError as error:
                messagebox.showerror("Monto no válido", str(error), parent=ventana)
                return
            recargar()
            messagebox.showinfo("Mensualidad actualizada", "El nuevo monto quedó guardado.", parent=ventana)

        def renovar():
            cuenta = cuenta_seleccionada()
            if not cuenta:
                return
            confirmar = messagebox.askyesno(
                "Confirmar pago",
                f"¿Confirmaste el pago de {cuenta['mensualidad']} DOP de {cuenta['empresa']}?",
                parent=ventana,
            )
            if not confirmar:
                return
            try:
                vencimiento = renovar_suscripcion_prestamista(
                    cuenta["tenant_id"],
                    self.usuario_actual or "administrador",
                )
                if not vencimiento:
                    raise RuntimeError("No se encontró la cuenta.")
            except (ValueError, RuntimeError) as error:
                messagebox.showerror("No se pudo renovar", str(error), parent=ventana)
                return
            recargar()
            messagebox.showinfo("Suscripción renovada", f"Nuevo vencimiento: {vencimiento}", parent=ventana)

        def cambiar_estado():
            cuenta = cuenta_seleccionada()
            if not cuenta:
                return
            vencida = (
                not cuenta["suscripcion_hasta"]
                or cuenta["suscripcion_hasta"] < date.today().isoformat()
            )
            if cuenta["activo"]:
                nuevo_estado = False
            elif vencida:
                messagebox.showwarning(
                    "Mensualidad vencida",
                    "Confirma el pago con «Renovar +1 mes» para volver a habilitar esta cuenta.",
                    parent=ventana,
                )
                return
            else:
                nuevo_estado = True
            if not cambiar_estado_prestamista(cuenta["tenant_id"], nuevo_estado):
                messagebox.showerror("Error", "No se pudo cambiar el estado de la cuenta.", parent=ventana)
                return
            recargar()

        def ver_historial():
            cuenta = cuenta_seleccionada()
            if not cuenta:
                return
            historial = tk.Toplevel(ventana)
            historial.title(f"Pagos - {cuenta['empresa']}")
            historial.geometry("700x320")
            columnas_historial = ("fecha", "monto", "periodo", "registrado")
            tabla_historial = ttk.Treeview(
                historial,
                columns=columnas_historial,
                show="headings",
            )
            for columna, titulo, ancho in [
                ("fecha", "Fecha", 100),
                ("monto", "Monto", 100),
                ("periodo", "Periodo cubierto", 240),
                ("registrado", "Registrado por", 160),
            ]:
                tabla_historial.heading(columna, text=titulo)
                tabla_historial.column(columna, width=ancho, anchor="w")
            pagos = historial_pagos_prestamista(cuenta["tenant_id"])
            if not pagos:
                tk.Label(
                    historial,
                    text="No hay pagos registrados para esta cuenta.",
                    font=("Segoe UI", 10),
                ).pack(pady=18)
            tabla_historial.pack(expand=True, fill="both", padx=12, pady=12)
            for pago in pagos:
                fecha_pago, monto, moneda, desde, hasta, administrador = pago
                tabla_historial.insert(
                    "",
                    "end",
                    values=(
                        fecha_pago,
                        f"{monto} {moneda}",
                        f"{desde} — {hasta}",
                        administrador,
                    ),
                )

        def restablecer_acceso():
            cuenta = cuenta_seleccionada()
            if not cuenta:
                return
            temporal = secrets.token_urlsafe(12)
            if not restablecer_contrasena_usuario(cuenta["id_usuario"], temporal):
                messagebox.showerror("Error", "No se pudo restablecer la contraseña.", parent=ventana)
                return
            messagebox.showinfo(
                "Contraseña temporal",
                f"Entrega esta clave al usuario por un medio seguro. Solo se muestra ahora:\n\n{temporal}\n\nDeberá cambiarla al iniciar sesión.",
                parent=ventana,
            )

        botones = ttk.Frame(ventana)
        botones.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(botones, text="Editar mensualidad", command=editar_mensualidad).pack(side="left", padx=(0, 6))
        ttk.Button(botones, text="Renovar +1 mes", command=renovar).pack(side="left", padx=6)
        ttk.Button(botones, text="Suspender / reactivar", command=cambiar_estado).pack(side="left", padx=6)
        ttk.Button(botones, text="Historial de pagos", command=ver_historial).pack(side="left", padx=6)
        ttk.Button(botones, text="Restablecer acceso", command=restablecer_acceso).pack(side="left", padx=6)
        ttk.Button(botones, text="Cerrar", command=ventana.destroy).pack(side="right")
        recargar()


class LoginWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rijo Express - Inicio de sesión")
        self.geometry("440x660")
        self.resizable(False, False)
        fondo = "#f4f7f5"
        self.configure(bg=fondo)
        configurar_estilos(self)
        self.modo_admin = False
        self.hay_administrador = any(rol == "admin" for _, rol in listar_usuarios())

        tarjeta = tk.Frame(
            self,
            bg=fondo,
            highlightthickness=0,
        )
        tarjeta.pack(fill="both", expand=True, padx=34, pady=18)

        logo_original = tk.PhotoImage(master=self, file=ruta_recurso("logo_rijo_express.png"))
        self.logo_inicio = logo_original.subsample(3, 3)
        tk.Label(
            tarjeta,
            image=self.logo_inicio,
            bg=fondo,
        ).pack(pady=(6, 0))
        self.titulo_login = tk.Label(
            tarjeta,
            text="Accede a tu cuenta",
            font=("Segoe UI", 18, "bold"),
            bg=fondo,
            fg="#18352a",
        )
        self.titulo_login.pack()
        self.subtitulo_login = tk.Label(
            tarjeta,
            text="Inicia sesión para administrar tu cartera",
            font=("Segoe UI", 10),
            bg=fondo,
            fg="#687a71",
        )
        self.subtitulo_login.pack(pady=(4, 14))

        tk.Label(
            tarjeta,
            text="Usuario",
            font=("Segoe UI", 10, "bold"),
            bg=fondo,
            fg="#334b40",
        ).pack(anchor="w", padx=32, pady=(0, 5))
        self.entry_usuario = ttk.Entry(tarjeta, font=("Segoe UI", 11))
        self.entry_usuario.pack(fill="x", padx=32, pady=(0, 8))
        self.entry_usuario.bind("<Return>", lambda event: self.verificar_login())

        tk.Label(
            tarjeta,
            text="Contraseña",
            font=("Segoe UI", 10, "bold"),
            bg=fondo,
            fg="#334b40",
        ).pack(anchor="w", padx=32, pady=(0, 5))
        self.entry_contrasena = ttk.Entry(tarjeta, show="*", font=("Segoe UI", 11))
        self.entry_contrasena.pack(fill="x", padx=32, pady=(0, 12))
        self.entry_contrasena.bind("<Return>", lambda event: self.verificar_login())

        ttk.Button(
            tarjeta,
            text="Iniciar sesión",
            command=self.verificar_login,
            style="Bank.TButton",
        ).pack(fill="x", padx=32, pady=(0, 8))
        self.boton_registro = ttk.Button(tarjeta, command=self.abrir_registro)
        self.boton_registro.pack(fill="x", padx=32, pady=(0, 8))
        self.boton_admin = ttk.Button(tarjeta, command=self.alternar_acceso)
        self.boton_admin.pack(fill="x", padx=32, pady=(0, 24))
        self.actualizar_modo()
        self.entry_usuario.focus_set()

    def actualizar_modo(self):
        if self.modo_admin:
            self.title("Rijo Express - Acceso de administrador")
            self.titulo_login.config(text="Acceso privado")
            self.subtitulo_login.config(text="Solo para la administración de Rijo Express")
            self.boton_admin.config(text="Volver al acceso de cuenta")
            self.boton_registro.pack_forget()
            if self.hay_administrador:
                self.boton_admin.pack(fill="x", padx=32, pady=(0, 24))
            return
        self.title("Rijo Express - Acceso a tu cuenta")
        self.titulo_login.config(text="Accede a tu cuenta")
        self.subtitulo_login.config(text="Inicia sesión para administrar tu cartera")
        self.boton_admin.config(text="Acceso de administrador")
        self.boton_registro.config(
            text="Crear cuenta" if self.hay_administrador else "Configurar administrador",
        )
        self.boton_registro.pack(fill="x", padx=32, pady=(0, 8))
        if self.hay_administrador:
            self.boton_admin.pack(fill="x", padx=32, pady=(0, 24))
        else:
            self.boton_admin.pack_forget()

    def alternar_acceso(self):
        if not self.hay_administrador:
            self.abrir_registro_admin()
            return
        self.modo_admin = not self.modo_admin
        self.actualizar_modo()
        self.entry_usuario.focus_set()

    def verificar_login(self):
        usuario = self.entry_usuario.get().strip().lower()
        contrasena = self.entry_contrasena.get()
        datos = obtener_usuario_autenticado(usuario, contrasena)
        if not datos:
            messagebox.showerror("Error", "Usuario o contraseña incorrectos.")
            self.entry_contrasena.focus_set()
            return
        if self.modo_admin and datos["rol"] != "admin":
            messagebox.showerror(
                "Acceso de administrador",
                "Esta cuenta no tiene permisos de administrador.",
                parent=self,
            )
            return
        if not self.modo_admin and datos["rol"] == "admin":
            messagebox.showerror(
                "Acceso separado",
                "Para esta cuenta, selecciona «Acceso de administrador».",
                parent=self,
            )
            return
        if datos["tipo_tenant"] == "cliente":
            vencida = (
                not datos["suscripcion_hasta"]
                or datos["suscripcion_hasta"] < date.today().isoformat()
            )
            if not datos["activo"] or vencida:
                estado = "suspendida" if not datos["activo"] else "vencida"
                messagebox.showwarning(
                    "Mensualidad pendiente",
                    f"La cuenta está {estado}. Mensualidad actual: "
                    f"{datos['mensualidad']} DOP. Contacta al administrador para renovar.",
                    parent=self,
                )
                return
        if datos["requiere_cambio_contrasena"] and not self.cambiar_contrasena_temporal(
            datos,
            contrasena,
        ):
            return

        app = PrestamoApp(
            self,
            usuario_actual=usuario,
            rol_actual=datos["rol"],
            tenant_id=datos["tenant_id"],
            nombre_empresa=datos["nombre_empresa"],
        )
        self.withdraw()
        app.protocol("WM_DELETE_WINDOW", app.cerrar_aplicacion)

    def cambiar_contrasena_temporal(self, datos, temporal):
        nueva = simpledialog.askstring(
            "Cambia tu contraseña",
            "Escribe una nueva contraseña (mínimo 12 caracteres):",
            show="*",
            parent=self,
        )
        if nueva is None:
            return False
        confirmacion = simpledialog.askstring(
            "Confirma tu contraseña",
            "Escribe nuevamente la nueva contraseña:",
            show="*",
            parent=self,
        )
        if confirmacion is None:
            return False
        if len(nueva) < 12:
            messagebox.showerror("Contraseña no válida", "Debe tener al menos 12 caracteres.", parent=self)
            return False
        if nueva != confirmacion:
            messagebox.showerror("Contraseña no válida", "Las contraseñas no coinciden.", parent=self)
            return False
        if not cambiar_contrasena_usuario(datos["id_usuario"], temporal, nueva):
            messagebox.showerror("Error", "No se pudo actualizar la contraseña.", parent=self)
            return False
        return True

    def abrir_registro(self):
        if self.hay_administrador:
            RegistroWindow(self)
        else:
            self.abrir_registro_admin()

    def abrir_registro_admin(self):
        RegistroWindow(self, crear_administrador=True)


class RegistroWindow(tk.Toplevel):
    def __init__(self, parent, crear_administrador=False):
        super().__init__(parent)
        self.parent = parent
        self.crear_administrador = crear_administrador
        self.title(
            "Configurar administrador" if crear_administrador else "Crear cuenta"
        )
        self.geometry("440x570" if not crear_administrador else "440x460")
        self.resizable(False, False)
        self.configure(bg="#f4f7f5")
        self.transient(parent)
        self.grab_set()
        configurar_estilos(self)

        tarjeta = tk.Frame(
            self,
            bg="#ffffff",
            highlightbackground="#e1e9e4",
            highlightthickness=1,
        )
        tarjeta.pack(fill="both", expand=True, padx=24, pady=24)

        tk.Label(
            tarjeta,
            text="Crear administrador" if crear_administrador else "Crear cuenta",
            font=("Segoe UI", 19, "bold"),
            bg="#ffffff",
            fg="#18352a",
        ).pack(anchor="w", padx=26, pady=(24, 4))
        tk.Label(
            tarjeta,
            text=(
                "Este administrador podrá gestionar las mensualidades."
                if crear_administrador
                else "Escribe el nombre de tu empresa y crea tus credenciales."
            ),
            font=("Segoe UI", 10),
            bg="#ffffff",
            fg="#687a71",
        ).pack(anchor="w", padx=26, pady=(0, 18))

        if not crear_administrador:
            self.entry_empresa = self.agregar_campo(tarjeta, "Nombre de la empresa de préstamos")
        self.entry_usuario = self.agregar_campo(tarjeta, "Usuario")
        self.entry_contrasena = self.agregar_campo(tarjeta, "Contraseña", ocultar=True)
        self.entry_confirmar = self.agregar_campo(tarjeta, "Confirmar contraseña", ocultar=True)
        if not crear_administrador:
            tk.Label(
                tarjeta,
                text="Mensualidad inicial: 500 DOP. El administrador puede ajustarla.",
                font=("Segoe UI", 9),
                bg="#ffffff",
                fg="#687a71",
            ).pack(anchor="w", padx=26, pady=(0, 10))

        ttk.Button(
            tarjeta,
            text="Crear administrador" if crear_administrador else "Crear cuenta",
            command=self.registrar_usuario,
            style="Bank.TButton",
        ).pack(fill="x", padx=26, pady=(3, 24))

    def agregar_campo(self, tarjeta, texto, ocultar=False):
        tk.Label(
            tarjeta,
            text=texto,
            font=("Segoe UI", 10, "bold"),
            bg="#ffffff",
            fg="#334b40",
        ).pack(anchor="w", padx=26, pady=(0, 5))
        entrada = ttk.Entry(
            tarjeta,
            font=("Segoe UI", 11),
            show="*" if ocultar else "",
        )
        entrada.pack(fill="x", padx=26, pady=(0, 12))
        return entrada

    def registrar_usuario(self):
        usuario = self.entry_usuario.get().strip()
        contrasena = self.entry_contrasena.get()
        confirmar = self.entry_confirmar.get()

        if not usuario or not contrasena:
            messagebox.showerror("Error", "Escribe usuario y contraseña.", parent=self)
            return
        if not re.fullmatch(r"[a-z0-9._-]{3,32}", usuario.lower()):
            messagebox.showerror(
                "Usuario no válido",
                "Usa de 3 a 32 caracteres: letras, números, punto, guion o guion bajo.",
                parent=self,
            )
            return
        if not 12 <= len(contrasena) <= 128:
            messagebox.showerror(
                "Contraseña no válida",
                "La contraseña debe tener entre 12 y 128 caracteres.",
                parent=self,
            )
            return
        if contrasena != confirmar:
            messagebox.showerror("Error", "Las contraseñas no coinciden.", parent=self)
            return

        if self.crear_administrador:
            creado = agregar_usuario(usuario.lower(), contrasena, "admin")
            mensaje = "Administrador creado. Ya puedes iniciar sesión como administrador."
        else:
            empresa = self.entry_empresa.get().strip()
            if not 2 <= len(empresa) <= 80:
                messagebox.showerror(
                    "Nombre no válido",
                    "El nombre de la empresa debe tener entre 2 y 80 caracteres.",
                    parent=self,
                )
                return
            hoy = date.today()
            mes = hoy.month % 12 + 1
            anio = hoy.year + (1 if hoy.month == 12 else 0)
            from calendar import monthrange
            vencimiento = date(anio, mes, min(hoy.day, monthrange(anio, mes)[1]))
            creado = crear_cuenta_prestamista_con_mensualidad(
                empresa,
                usuario.lower(),
                contrasena,
                vencimiento.isoformat(),
                "500",
            )
            mensaje = (
                f"Cuenta creada. Mensualidad: 500 DOP. "
                f"Vence el {vencimiento.isoformat()}."
            )

        if creado:
            messagebox.showinfo("Cuenta creada", mensaje, parent=self)
            if self.crear_administrador:
                self.parent.hay_administrador = True
                self.parent.modo_admin = True
                self.parent.actualizar_modo()
                self.parent.entry_usuario.delete(0, "end")
                self.parent.entry_usuario.insert(0, usuario.lower())
            self.destroy()
        else:
            messagebox.showerror("Error", "Ese nombre de usuario ya existe.", parent=self)


if __name__ == "__main__":
    login = LoginWindow()
    login.mainloop()
