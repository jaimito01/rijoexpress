from clases import Cliente, Prestamo, cargar_clientes, guardar_clientes, cargar_prestamos, guardar_prestamos
from datetime import datetime

def agregar_cliente(clientes):
    id_cliente = input("Ingrese ID del cliente: ")
    if id_cliente in clientes:
        print("Cliente ya existe.")
        return
    nombre = input("Ingrese nombre del cliente: ")
    fecha_registro = datetime.now().strftime("%Y-%m-%d")
    clientes[id_cliente] = Cliente(id_cliente, nombre, fecha_registro)
    guardar_clientes(clientes)
    print("Cliente agregado exitosamente.")

def crear_prestamo(prestamos, clientes):
    id_cliente = input("Ingrese ID del cliente: ")
    if id_cliente not in clientes:
        print("Cliente no encontrado.")
        return
    id_prestamo = input("Ingrese ID del préstamo: ")
    if id_prestamo in prestamos:
        print("Préstamo ya existe.")
        return
    monto = float(input("Ingrese monto prestado: "))
    tasa_interes = float(input("Ingrese tasa de interés (%): "))
    fecha_inicio = input("Ingrese fecha de inicio (YYYY-MM-DD): ")
    fecha_vencimiento = input("Ingrese fecha de vencimiento (YYYY-MM-DD): ")
    prestamos[id_prestamo] = Prestamo(id_prestamo, id_cliente, monto, tasa_interes, fecha_inicio, fecha_vencimiento)
    guardar_prestamos(prestamos)
    print("Préstamo creado exitosamente.")

def registrar_pago(prestamos):
    id_prestamo = input("Ingrese ID del préstamo: ")
    if id_prestamo not in prestamos:
        print("Préstamo no encontrado.")
        return
    fecha = input("Ingrese fecha del pago (YYYY-MM-DD): ")
    monto = float(input("Ingrese monto del pago: "))
    try:
        prestamos[id_prestamo].registrar_pago(fecha, monto)
        guardar_prestamos(prestamos)
        print("Pago registrado exitosamente.")
    except ValueError as e:
        print(e)

def consultar_prestamos_activos(prestamos, clientes):
    id_cliente = input("Ingrese ID del cliente: ")
    if id_cliente not in clientes:
        print("Cliente no encontrado.")
        return
    activos = [p for p in prestamos.values() if p.id_cliente == id_cliente and p.saldo_pendiente > 0]
    if not activos:
        print("No hay préstamos activos.")
        return
    for p in activos:
        print(f"ID Préstamo: {p.id_prestamo}, Monto: {p.monto}, Saldo Pendiente: {p.saldo_pendiente}")

def generar_reportes(prestamos, clientes):
    print("=== Reporte de Préstamos Activos ===")
    for p in prestamos.values():
        if p.saldo_pendiente > 0:
            cliente = clientes.get(p.id_cliente)
            if cliente:
                print(f"Cliente: {cliente.nombre} (ID: {cliente.id_cliente})")
                print(f"Préstamo ID: {p.id_prestamo}, Monto: {p.monto}, Saldo: {p.saldo_pendiente}")
                print("Pagos realizados:")
                for pago in p.pagos:
                    print(f"  Fecha: {pago['fecha']}, Monto: {pago['monto']}")
                print("---")

def menu():
    clientes = cargar_clientes()
    prestamos = cargar_prestamos()
    while True:
        print("\n=== Sistema de Gestión de Préstamos ===")
        print("1. Agregar Cliente")
        print("2. Crear Préstamo")
        print("3. Registrar Pago")
        print("4. Consultar Préstamos Activos")
        print("5. Generar Reportes")
        print("6. Salir")
        opcion = input("Seleccione una opción: ")
        if opcion == '1':
            agregar_cliente(clientes)
        elif opcion == '2':
            crear_prestamo(prestamos, clientes)
        elif opcion == '3':
            registrar_pago(prestamos)
        elif opcion == '4':
            consultar_prestamos_activos(prestamos, clientes)
        elif opcion == '5':
            generar_reportes(prestamos, clientes)
        elif opcion == '6':
            break
        else:
            print("Opción inválida.")

if __name__ == "__main__":
    menu()