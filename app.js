const byId = (id) => document.getElementById(id);
let csrfToken = "";
let clientes = [];
let prestamos = [];
let usuarioActual = null;
let instalacionPendiente = null;
let avisoTimer = null;
const necesitaGuiaInstalacion = /iPhone|iPad|iPod/i.test(navigator.userAgent) && !navigator.standalone;

async function api(ruta, opciones = {}, recuperarCsrfVencido = true) {
  const metodo = (opciones.method || "GET").toUpperCase();
  const encabezados = new Headers(opciones.headers || {});
  if (opciones.body) encabezados.set("Content-Type", "application/json");
  if (metodo !== "GET") {
    if (!csrfToken) throw new Error("La sesión aún se está preparando. Inténtalo de nuevo.");
    encabezados.set("X-CSRF-Token", csrfToken);
  }

  const respuesta = await fetch(ruta, {
    ...opciones,
    method: metodo,
    headers: encabezados,
    credentials: "same-origin",
  });
  let contenido = {};
  try {
    contenido = await respuesta.json();
  } catch (error) {
    throw new Error("El servidor devolvió una respuesta que no se pudo leer.");
  }
  if (!respuesta.ok) {
    if (
      respuesta.status === 403
      && metodo !== "GET"
      && recuperarCsrfVencido
      && contenido.error === "La sesión de seguridad venció. Actualiza la página e inténtalo otra vez."
    ) {
      const estado = await api("/api/session", {}, false);
      if (!estado.csrf_token) throw new Error("No se pudo renovar la sesión segura. Recarga la página.");
      csrfToken = estado.csrf_token;
      return api(ruta, opciones, false);
    }
    if (respuesta.status === 402 && contenido.premium_requerido) mostrarPremiumRequerido(contenido);
    if (respuesta.status === 402 && contenido.pago_requerido) mostrarPagoRequerido(contenido);
    const error = new Error(contenido.error || "No se pudo completar la operación.");
    error.premiumRequerido = Boolean(contenido.premium_requerido);
    throw error;
  }
  return contenido;
}

async function cargarPortalCliente() {
  try {
    const portal = await api("/api/portal");
    const prestamos = portal.prestamos;
    byId("portal-client-name").textContent = portal.nombre;
    byId("portal-loan-count").textContent = prestamos.length;
    byId("portal-balance").textContent = formatearDinero(
      prestamos.reduce((total, prestamo) => total + Number(prestamo.saldo_pendiente), 0),
    );
    const lista = byId("portal-loans");
    lista.replaceChildren();
    byId("portal-empty").hidden = prestamos.length > 0;
    for (const prestamo of prestamos) {
      const tarjeta = document.createElement("article");
      tarjeta.className = "portal-loan";
      const encabezado = document.createElement("div");
      encabezado.className = "portal-loan-heading";
      encabezado.append(
        textoElemento("strong", `Préstamo ${prestamo.id_prestamo}`),
        textoElemento("span", prestamo.saldo_pendiente <= 0 ? "Pagado" : "En seguimiento"),
      );
      const detalles = document.createElement("div");
      detalles.className = "portal-loan-details";
      detalles.append(
        textoElemento("span", `Monto: ${formatearDinero(prestamo.monto)}`),
        textoElemento("span", `Saldo pendiente: ${formatearDinero(prestamo.saldo_pendiente)}`),
        textoElemento("span", `Vencimiento: ${prestamo.fecha_vencimiento}`),
      );
      tarjeta.append(encabezado, detalles);
      if (prestamo.pagos.length) {
        const pagos = document.createElement("ul");
        pagos.className = "portal-payments";
        for (const pago of prestamo.pagos) {
          pagos.appendChild(textoElemento(
            "li",
            `Pago del ${pago.fecha}: ${formatearDinero(pago.monto)}`,
          ));
        }
        tarjeta.appendChild(pagos);
      }
      lista.appendChild(tarjeta);
    }
  } catch (error) {
    mostrarAviso(error.message, true);
  }
}

function mostrarCodigoAccesoCliente(codigo) {
  byId("client-access-code-value").textContent = codigo;
  byId("client-access-code-dialog").showModal();
}

function mostrarPremiumRequerido(datos) {
  byId("premium-required-message").textContent = datos.mensaje || datos.error;
  byId("premium-required-whatsapp").href = datos.whatsapp_url;
  const dialogo = byId("premium-required-dialog");
  if (typeof dialogo.showModal === "function") dialogo.showModal();
  else mostrarAviso(datos.mensaje || datos.error, true);
}

function mostrarAviso(mensaje, esError = false) {
  const aviso = byId("toast");
  aviso.textContent = mensaje;
  aviso.classList.toggle("is-error", esError);
  aviso.classList.add("is-visible");
  window.clearTimeout(avisoTimer);
  avisoTimer = window.setTimeout(() => aviso.classList.remove("is-visible"), 3600);
}

function mostrarPagoRequerido(datos) {
  byId("login-view").hidden = true;
  byId("admin-login-view").hidden = true;
  byId("password-change-view").hidden = true;
  byId("app-view").hidden = true;
  byId("payment-required-view").hidden = false;
  byId("payment-message").textContent = datos.mensaje || datos.error;
  const vencimiento = datos.suscripcion_hasta
    ? `Fecha de vencimiento: ${datos.suscripcion_hasta}. `
    : "";
  byId("payment-details").textContent =
    `${vencimiento}Mensualidad: ${datos.mensualidad} ${datos.moneda}.`;
  byId("payment-whatsapp").href = datos.whatsapp_url;
  usuarioActual = null;
  csrfToken = "";
}

function mostrarAplicacion(estado) {
  csrfToken = estado.csrf_token || "";
  usuarioActual = estado.autenticado
    ? {
      nombre: estado.nombre_usuario,
      empresa: estado.nombre_empresa || estado.nombre_usuario,
      rol: estado.rol,
    }
    : null;
  const cambioRequerido = Boolean(usuarioActual && estado.requiere_cambio_contrasena);
  const esCliente = usuarioActual?.rol === "cliente";
  byId("login-view").hidden = Boolean(usuarioActual);
  byId("admin-login-view").hidden = true;
  byId("app-view").hidden = !usuarioActual || cambioRequerido;
  byId("client-portal-view").hidden = !esCliente || cambioRequerido;
  document.querySelector(".app-layout").hidden = esCliente;
  byId("payment-required-view").hidden = true;
  byId("password-change-view").hidden = !cambioRequerido;
  byId("ios-install-hint").hidden = !usuarioActual || cambioRequerido || !necesitaGuiaInstalacion;
  if (!usuarioActual || cambioRequerido) return;

  byId("current-user").textContent = usuarioActual.empresa;
  byId("current-user").title = `Usuario: ${usuarioActual.nombre}`;
  byId("users-nav").hidden = usuarioActual.rol !== "admin";
  if (esCliente) cargarPortalCliente();
  else cargarDatos();
}

async function cargarSesion() {
  try {
    mostrarAplicacion(await api("/api/session"));
  } catch (error) {
    mostrarAviso(error.message, true);
  }
}

async function cargarDatos() {
  try {
    const [resumen, listaClientes, listaPrestamos, plan] = await Promise.all([
      api("/api/dashboard"),
      api("/api/clients"),
      api("/api/loans"),
      usuarioActual.rol === "admin" ? Promise.resolve(null) : api("/api/subscription"),
    ]);
    clientes = listaClientes.resultados;
    prestamos = listaPrestamos.resultados;
    mostrarResumen(resumen);
    mostrarClientes(clientes);
    mostrarPrestamos(prestamos);
    actualizarSelectorClientes();
    mostrarPlan(plan);
    if (usuarioActual.rol === "admin") await mostrarCuentas();
  } catch (error) {
    mostrarAviso(error.message, true);
  }
}

function mostrarPlan(plan) {
  const aviso = byId("plan-notice");
  if (!plan || !plan.es_cliente || usuarioActual?.rol === "admin") {
    aviso.hidden = true;
    return;
  }
  aviso.hidden = false;
  byId("upgrade-premium-link").href = plan.whatsapp_url;
  if (!plan.premium) {
    const restantes = Math.max(0, plan.limite_gratis - plan.prestamos_usados);
    byId("upgrade-premium-link").textContent = "Actualizar a Premium";
    byId("plan-message").textContent = restantes
      ? `Plan gratis: ${plan.prestamos_usados} de ${plan.limite_gratis} préstamos usados. Te quedan ${restantes}.`
      : `Llegaste al límite de ${plan.limite_gratis} préstamos gratis. Actualiza a Premium para crear más.`;
  } else if (plan.en_gracia) {
    byId("upgrade-premium-link").textContent = "Renovar Premium";
    byId("plan-message").textContent =
      `Tu membresía venció. Estás en los 3 días de gracia hasta ${plan.gracia_hasta}; renueva para evitar la suspensión.`;
  } else {
    byId("upgrade-premium-link").textContent = "Renovar Premium";
    byId("plan-message").textContent =
      `Premium activo hasta ${plan.suscripcion_hasta}. Precio mensual: ${plan.mensualidad} ${plan.moneda}.`;
  }
}

function mostrarResumen(resumen) {
  byId("metric-clients").textContent = resumen.clientes;
  byId("metric-loans").textContent = resumen.prestamos;
  byId("metric-active").textContent = resumen.activos;
  byId("metric-overdue").textContent = resumen.en_mora;
  byId("metric-income").textContent = formatearDinero(resumen.ingresos);

  const lista = byId("due-list");
  lista.replaceChildren();
  if (!resumen.vencimientos.length) {
    lista.appendChild(textoElemento("p", "No hay préstamos por vencer durante los próximos 7 días.", "empty-state"));
    return;
  }
  for (const vencimiento of resumen.vencimientos) {
    const fila = document.createElement("div");
    fila.className = "due-item";
    fila.append(
      textoElemento("strong", `${vencimiento.cliente} · Préstamo ${vencimiento.id_prestamo}`),
      textoElemento("span", vencimiento.fecha_vencimiento),
    );
    lista.appendChild(fila);
  }
}

function mostrarClientes(lista) {
  const cuerpo = byId("clients-table");
  cuerpo.replaceChildren();
  byId("clients-empty").hidden = lista.length > 0;
  for (const cliente of lista) {
    const fila = document.createElement("tr");
    const accion = document.createElement("td");
    const codigo = document.createElement("button");
    codigo.type = "button";
    codigo.className = "table-action";
    codigo.dataset.clientAccessCode = cliente.id_cliente;
    codigo.dataset.clientName = cliente.nombre;
    codigo.textContent = "Código de acceso";
    accion.appendChild(codigo);
    fila.append(
      textoElemento("td", cliente.id_cliente, "table-primary"),
      textoElemento("td", cliente.nombre),
      textoElemento("td", cliente.fecha_registro),
      accion,
    );
    cuerpo.appendChild(fila);
  }
}

function mostrarPrestamos(lista) {
  const cuerpo = byId("loans-table");
  cuerpo.replaceChildren();
  byId("loans-empty").hidden = lista.length > 0;
  const hoy = fechaLocal();
  for (const prestamo of lista) {
    const fila = document.createElement("tr");
    const estado = prestamo.saldo_pendiente <= 0
      ? "Pagado"
      : prestamo.fecha_vencimiento < hoy ? "Vencido" : "Activo";
    const estadoCelda = textoElemento(
      "span",
      estado,
      `status-pill${estado === "Vencido" ? " is-overdue" : ""}`,
    );
    const botonPago = document.createElement("button");
    botonPago.type = "button";
    botonPago.className = "table-action";
    botonPago.dataset.paymentLoan = prestamo.id_prestamo;
    botonPago.textContent = "Registrar pago";
    botonPago.disabled = prestamo.saldo_pendiente <= 0;
    const accion = document.createElement("td");
    accion.appendChild(botonPago);
    const estadoCeldaTd = document.createElement("td");
    estadoCeldaTd.appendChild(estadoCelda);
    fila.append(
      textoElemento("td", prestamo.id_prestamo, "table-primary"),
      textoElemento("td", prestamo.nombre_cliente),
      textoElemento("td", prestamo.fecha_vencimiento),
      textoElemento("td", formatearDinero(prestamo.saldo_pendiente)),
      estadoCeldaTd,
      accion,
    );
    cuerpo.appendChild(fila);
  }
}

async function mostrarCuentas() {
  try {
    const resultado = await api("/api/admin/accounts");
    const cuerpo = byId("accounts-table");
    cuerpo.replaceChildren();
    byId("accounts-empty").hidden = resultado.resultados.length > 0;
    for (const cuenta of resultado.resultados) {
      const fila = document.createElement("tr");
      const estado = cuenta.vencida
        ? "Vencida"
        : cuenta.suspendida
          ? "Suspendida"
          : cuenta.en_gracia
            ? "En gracia"
            : cuenta.premium ? "Premium" : "Gratis";
      const estadoCelda = textoElemento(
        "span",
        estado,
        `status-pill${cuenta.vencida || cuenta.suspendida ? " is-overdue" : ""}`,
      );
      fila.append(
        textoElemento("td", cuenta.nombre, "table-primary"),
        textoElemento("td", cuenta.usuario),
        textoElemento("td", cuenta.premium ? "Premium" : "Gratis"),
        textoElemento("td", `${cuenta.prestamos_usados} / 5`),
        textoElemento("td", `${cuenta.mensualidad} DOP`),
        textoElemento("td", cuenta.creada_en || "—"),
        textoElemento("td", cuenta.suscripcion_hasta || "—"),
      );
      const estadoTd = document.createElement("td");
      estadoTd.appendChild(estadoCelda);
      fila.append(
        estadoTd,
        textoElemento("td", String(cuenta.cantidad_pagos || 0)),
        textoElemento("td", cuenta.ultimo_pago || "—"),
      );
      const acciones = document.createElement("td");
      const renovar = document.createElement("button");
      renovar.type = "button";
      renovar.className = "table-action";
      renovar.dataset.accountAction = "renovar";
      renovar.dataset.tenantId = cuenta.id;
      renovar.textContent = "Renovar +1 mes";
      acciones.appendChild(renovar);
      if (cuenta.suspendida && !cuenta.vencida) {
        const activar = document.createElement("button");
        activar.type = "button";
        activar.className = "table-action";
        activar.dataset.accountAction = "activar";
        activar.dataset.tenantId = cuenta.id;
        activar.textContent = "Reactivar";
        acciones.appendChild(activar);
      } else if (cuenta.activa) {
        const suspender = document.createElement("button");
        suspender.type = "button";
        suspender.className = "table-action";
        suspender.dataset.accountAction = "suspender";
        suspender.dataset.tenantId = cuenta.id;
        suspender.textContent = "Suspender";
        acciones.appendChild(suspender);
      }
      const historial = document.createElement("button");
      historial.type = "button";
      historial.className = "table-action";
      historial.dataset.accountAction = "historial";
      historial.dataset.tenantId = cuenta.id;
      historial.dataset.accountName = cuenta.nombre;
      historial.textContent = "Historial";
      acciones.appendChild(historial);
      const restablecer = document.createElement("button");
      restablecer.type = "button";
      restablecer.className = "table-action";
      restablecer.dataset.accountAction = "restablecer";
      restablecer.dataset.tenantId = cuenta.id;
      restablecer.dataset.accountName = cuenta.nombre;
      restablecer.dataset.accountUser = cuenta.usuario;
      restablecer.textContent = "Restablecer acceso";
      acciones.appendChild(restablecer);
      fila.appendChild(acciones);
      cuerpo.appendChild(fila);
    }
  } catch (error) {
    mostrarAviso(error.message, true);
  }
}

async function mostrarHistorialPagos(tenantId, nombreEmpresa) {
  const resultado = await api(`/api/admin/accounts/${encodeURIComponent(tenantId)}/payments`);
  const cuerpo = byId("payment-history-table");
  cuerpo.replaceChildren();
  byId("payment-history-empty").hidden = resultado.resultados.length > 0;
  byId("payment-history-title").textContent = `Historial de pagos · ${nombreEmpresa}`;
  for (const pago of resultado.resultados) {
    const fila = document.createElement("tr");
    fila.append(
      textoElemento("td", pago.fecha_pago),
      textoElemento("td", `${pago.monto} ${pago.moneda}`),
      textoElemento("td", `${pago.periodo_desde} — ${pago.periodo_hasta}`),
      textoElemento("td", pago.registrado_por),
    );
    cuerpo.appendChild(fila);
  }
  abrirDialogo("payment-history-dialog");
}

function mostrarContrasenaTemporal(datos, nombreEmpresa) {
  byId("temporary-password-company").textContent =
    `${nombreEmpresa} · ${datos.usuario}`;
  byId("temporary-password-value").textContent = datos.contrasena_temporal;
  byId("temporary-password-dialog").showModal();
}

function textoElemento(etiqueta, texto, clase = "") {
  const elemento = document.createElement(etiqueta);
  elemento.textContent = texto;
  if (clase) elemento.className = clase;
  return elemento;
}

function formatearDinero(valor) {
  const monto = Number(valor) || 0;
  return `$${new Intl.NumberFormat("es-DO", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(monto)}`;
}

function fechaLocal() {
  const ahora = new Date();
  const ajuste = ahora.getTimezoneOffset() * 60_000;
  return new Date(ahora.getTime() - ajuste).toISOString().slice(0, 10);
}

function actualizarSelectorClientes() {
  const selector = byId("loan-client");
  selector.replaceChildren();
  selector.appendChild(textoElemento("option", "Selecciona un cliente"));
  selector.options[0].value = "";
  for (const cliente of clientes) {
    const opcion = textoElemento("option", `${cliente.nombre} (${cliente.id_cliente})`);
    opcion.value = cliente.id_cliente;
    selector.appendChild(opcion);
  }
}

function abrirDialogo(id, datos = {}) {
  const dialogo = byId(id);
  if (id === "loan-dialog") actualizarSelectorClientes();
  if (id === "payment-dialog") {
    const prestamo = prestamos.find((item) => item.id_prestamo === datos.id);
    if (!prestamo) return;
    byId("payment-form").dataset.loanId = prestamo.id_prestamo;
    byId("payment-loan-label").textContent =
      `Préstamo ${prestamo.id_prestamo} · Saldo ${formatearDinero(prestamo.saldo_pendiente)}`;
    byId("payment-date").value = fechaLocal();
    byId("payment-amount").max = prestamo.saldo_pendiente;
  }
  if (id === "loan-dialog") {
    byId("loan-start").value = fechaLocal();
    const fechaFin = new Date(`${fechaLocal()}T12:00:00`);
    fechaFin.setDate(fechaFin.getDate() + 30);
    byId("loan-due").value = fechaFin.toISOString().slice(0, 10);
  }
  if (typeof dialogo.showModal === "function") dialogo.showModal();
  else mostrarAviso("Este navegador no admite los formularios del programa.", true);
}

function cerrarDialogoDesde(elemento) {
  const dialogo = elemento.closest("dialog");
  if (dialogo) dialogo.close();
}

async function enviarFormulario(formulario, ruta, prepararDatos = (datos) => datos) {
  const datos = prepararDatos(Object.fromEntries(new FormData(formulario).entries()));
  const respuesta = await api(ruta, { method: "POST", body: JSON.stringify(datos) });
  formulario.reset();
  formulario.closest("dialog").close();
  await cargarDatos();
  mostrarAviso("Cambios guardados correctamente.");
  return respuesta;
}

document.addEventListener("click", async (evento) => {
  const botonDialogo = evento.target.closest("[data-open-dialog]");
  if (botonDialogo) {
    if (botonDialogo.dataset.openDialog === "loan-dialog" && clientes.length === 0) {
      mostrarAviso("Primero agrega un cliente para crear un préstamo.", true);
      return;
    }
    abrirDialogo(botonDialogo.dataset.openDialog);
  }

  const botonCerrar = evento.target.closest("[data-close-dialog]");
  if (botonCerrar) cerrarDialogoDesde(botonCerrar);

  const botonNavegacion = evento.target.closest("[data-page]");
  if (botonNavegacion) cambiarPagina(botonNavegacion.dataset.page, botonNavegacion);

  const botonPago = evento.target.closest("[data-payment-loan]");
  if (botonPago) abrirDialogo("payment-dialog", { id: botonPago.dataset.paymentLoan });

  const botonCodigo = evento.target.closest("[data-client-access-code]");
  if (botonCodigo) {
    if (!window.confirm(
      `¿Generar un código nuevo para ${botonCodigo.dataset.clientName}? El código anterior y su acceso de cliente dejarán de funcionar.`,
    )) return;
    botonCodigo.disabled = true;
    try {
      const idCliente = encodeURIComponent(botonCodigo.dataset.clientAccessCode);
      const resultado = await api(`/api/clients/${idCliente}/access-code`, {
        method: "POST",
        body: "{}",
      });
      mostrarCodigoAccesoCliente(resultado.codigo_acceso);
      mostrarAviso("Código generado. Entrégalo al cliente por un medio privado.");
    } catch (error) {
      mostrarAviso(error.message, true);
    } finally {
      botonCodigo.disabled = false;
    }
  }

  const botonCuenta = evento.target.closest("[data-account-action]");
  if (botonCuenta) {
    const accionCuenta = botonCuenta.dataset.accountAction;
    if (accionCuenta === "restablecer" && !window.confirm(
      `¿Restablecer el acceso de ${botonCuenta.dataset.accountName}? La contraseña actual dejará de funcionar.`,
    )) return;
    botonCuenta.disabled = true;
    try {
      const tenantId = encodeURIComponent(botonCuenta.dataset.tenantId);
      if (accionCuenta === "historial") {
        await mostrarHistorialPagos(tenantId, botonCuenta.dataset.accountName);
      } else if (accionCuenta === "restablecer") {
        const datos = await api(`/api/admin/accounts/${tenantId}/reset-password`, {
          method: "POST",
          body: "{}",
        });
        mostrarContrasenaTemporal(datos, botonCuenta.dataset.accountName);
      } else {
        await api(`/api/admin/accounts/${tenantId}/${accionCuenta}`, {
          method: "POST",
          body: "{}",
        });
        await mostrarCuentas();
        mostrarAviso(accionCuenta === "renovar"
          ? "Pago registrado y mensualidad renovada."
          : "La suscripción fue actualizada.");
      }
    } catch (error) {
      mostrarAviso(error.message, true);
    } finally {
      botonCuenta.disabled = false;
    }
  }
});

function cambiarPagina(idPagina, boton) {
  if (idPagina === "users-page" && usuarioActual?.rol !== "admin") return;
  document.querySelectorAll(".page-section").forEach((pagina) => {
    pagina.hidden = pagina.id !== idPagina;
  });
  document.querySelectorAll(".nav-link").forEach((enlace) => {
    enlace.classList.toggle("is-active", enlace.dataset.page === idPagina);
  });
  if (boton) boton.blur();
}

byId("login-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  await iniciarSesion(evento.currentTarget, "/api/login", byId("login-submit"));
});

byId("admin-login-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  await iniciarSesion(evento.currentTarget, "/api/admin/login", byId("admin-login-submit"));
});

async function iniciarSesion(formulario, ruta, boton) {
  const datos = Object.fromEntries(new FormData(formulario).entries());
  boton.disabled = true;
  const textoOriginal = boton.textContent;
  boton.textContent = "Entrando…";
  try {
    const estado = await api(ruta, {
      method: "POST",
      body: JSON.stringify(datos),
    });
    mostrarAplicacion({
      autenticado: true,
      nombre_usuario: estado.nombre_usuario,
      nombre_empresa: estado.nombre_empresa,
      rol: estado.rol,
      requiere_cambio_contrasena: estado.requiere_cambio_contrasena,
      csrf_token: estado.csrf_token,
    });
    formulario.reset();
  } catch (error) {
    mostrarAviso(error.message, true);
  } finally {
    boton.textContent = textoOriginal;
    boton.disabled = false;
  }
}

byId("show-register").addEventListener("click", () => abrirDialogo("register-dialog"));
byId("show-client-register").addEventListener("click", () => abrirDialogo("client-register-dialog"));
byId("show-admin-login").addEventListener("click", () => {
  byId("login-view").hidden = true;
  byId("admin-login-view").hidden = false;
});
byId("back-to-login").addEventListener("click", () => {
  byId("admin-login-view").hidden = true;
  byId("login-view").hidden = false;
});

byId("register-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const formulario = evento.currentTarget;
  const datos = Object.fromEntries(new FormData(formulario).entries());
  try {
    const cuenta = await api("/api/register", {
      method: "POST",
      body: JSON.stringify(datos),
    });
    formulario.reset();
    formulario.closest("dialog").close();
    mostrarAplicacion({
      autenticado: true,
      nombre_usuario: cuenta.nombre_usuario,
      nombre_empresa: cuenta.nombre,
      rol: cuenta.rol,
      csrf_token: cuenta.csrf_token,
    });
    mostrarAviso("Cuenta gratis creada. Puedes registrar hasta 5 préstamos; el sexto requiere Premium.");
  } catch (error) {
    mostrarAviso(error.message, true);
  }
});

byId("password-change-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const formulario = evento.currentTarget;
  const boton = byId("password-change-submit");
  boton.disabled = true;
  try {
    await api("/api/password/change", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(formulario).entries())),
    });
    formulario.reset();
    mostrarAplicacion(await api("/api/session"));
    mostrarAviso("Contraseña actualizada. Ya puedes usar tu cuenta.");
  } catch (error) {
    mostrarAviso(error.message, true);
  } finally {
    boton.disabled = false;
  }
});

byId("payment-back").addEventListener("click", async () => {
  byId("payment-required-view").hidden = true;
  byId("login-view").hidden = false;
  await cargarSesion();
});

byId("logout-button").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
    csrfToken = "";
    mostrarAplicacion({ autenticado: false });
    cambiarPagina("dashboard-page");
    await cargarSesion();
  } catch (error) {
    mostrarAviso(error.message, true);
  }
});

byId("refresh-button").addEventListener("click", cargarDatos);
byId("refresh-accounts").addEventListener("click", mostrarCuentas);
byId("membership-price-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const boton = evento.currentTarget.querySelector('button[type="submit"]');
  boton.disabled = true;
  try {
    const resultado = await api("/api/admin/settings/membership-price", {
      method: "POST",
      body: JSON.stringify({ mensualidad: byId("membership-price").value }),
    });
    const precio = `${resultado.mensualidad} ${resultado.moneda}`;
    byId("membership-price").value = resultado.mensualidad;
    byId("monthly-price").textContent = precio;
    byId("registration-monthly-price").textContent = precio;
    await mostrarCuentas();
    mostrarAviso("Precio de Premium actualizado.");
  } catch (error) {
    mostrarAviso(error.message, true);
  } finally {
    boton.disabled = false;
  }
});
byId("client-search").addEventListener("input", (evento) => {
  const consulta = evento.currentTarget.value.trim().toLocaleLowerCase();
  mostrarClientes(clientes.filter((cliente) =>
    cliente.id_cliente.toLocaleLowerCase().includes(consulta)
    || cliente.nombre.toLocaleLowerCase().includes(consulta)));
});
byId("loan-search").addEventListener("input", (evento) => {
  const consulta = evento.currentTarget.value.trim().toLocaleLowerCase();
  mostrarPrestamos(prestamos.filter((prestamo) =>
    prestamo.id_prestamo.toLocaleLowerCase().includes(consulta)
    || prestamo.nombre_cliente.toLocaleLowerCase().includes(consulta)));
});

byId("client-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  try {
    const resultado = await enviarFormulario(evento.currentTarget, "/api/clients");
    mostrarCodigoAccesoCliente(resultado.codigo_acceso);
  } catch (error) {
    mostrarAviso(error.message, true);
  }
});

byId("client-register-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const formulario = evento.currentTarget;
  const boton = formulario.querySelector('button[type="submit"]');
  boton.disabled = true;
  try {
    const cuenta = await api("/api/client/register", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(formulario).entries())),
    });
    formulario.reset();
    formulario.closest("dialog").close();
    mostrarAplicacion({
      autenticado: true,
      nombre_usuario: cuenta.nombre_usuario,
      nombre_empresa: cuenta.nombre_empresa,
      rol: cuenta.rol,
      csrf_token: cuenta.csrf_token,
    });
    mostrarAviso("Acceso creado. Ya puedes consultar tus préstamos.");
  } catch (error) {
    mostrarAviso(error.message, true);
  } finally {
    boton.disabled = false;
  }
});

byId("loan-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  try {
    await enviarFormulario(evento.currentTarget, "/api/loans");
  } catch (error) {
    if (!error.premiumRequerido) mostrarAviso(error.message, true);
  }
});

byId("payment-form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const formulario = evento.currentTarget;
  const datos = Object.fromEntries(new FormData(formulario).entries());
  try {
    await api(`/api/loans/${encodeURIComponent(formulario.dataset.loanId)}/payments`, {
      method: "POST",
      body: JSON.stringify(datos),
    });
    formulario.reset();
    formulario.closest("dialog").close();
    await cargarDatos();
    mostrarAviso("Pago registrado correctamente.");
  } catch (error) {
    mostrarAviso(error.message, true);
  }
});

byId("install-button").addEventListener("click", async () => {
  if (!instalacionPendiente) return;
  instalacionPendiente.prompt();
  await instalacionPendiente.userChoice;
  instalacionPendiente = null;
  byId("install-button").hidden = true;
});

window.addEventListener("beforeinstallprompt", (evento) => {
  evento.preventDefault();
  instalacionPendiente = evento;
  byId("install-button").hidden = false;
});

window.addEventListener("appinstalled", () => {
  mostrarAviso("Rijo Express quedó instalado en este dispositivo.");
  byId("install-button").hidden = true;
});

window.addEventListener("online", () => {
  document.querySelector(".connection-indicator").lastChild.textContent = " Conectado";
  if (usuarioActual) cargarDatos();
});

window.addEventListener("offline", () => {
  document.querySelector(".connection-indicator").lastChild.textContent = " Sin conexión";
  mostrarAviso("Sin conexión: los datos necesitan internet para sincronizarse.", true);
});

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/service-worker.js")
    .catch(() => mostrarAviso("No se pudo activar el modo instalable. Revisa la conexión segura.", true));
}

async function cargarInformacionMensualidad() {
  try {
    const informacion = await api("/api/billing-info");
    const precio = `${informacion.mensualidad} ${informacion.moneda}`;
    byId("monthly-price").textContent = precio;
    byId("registration-monthly-price").textContent = precio;
    byId("membership-price").value = informacion.mensualidad;
    for (const id of ["forgot-access", "admin-forgot-access"]) {
      const enlace = byId(id);
      enlace.href = informacion.whatsapp_recuperacion_url;
      enlace.hidden = false;
    }
  } catch (error) {
    mostrarAviso(error.message, true);
  }
}

window.setInterval(() => {
  if (usuarioActual) {
    api("/api/session").catch((error) => mostrarAviso(error.message, true));
  }
}, 30_000);

async function inicializarAplicacion() {
  try {
    const estado = await api("/api/session");
    if (!estado.csrf_token) throw new Error("No se pudo preparar la sesión segura. Recarga la página.");
    mostrarAplicacion(estado);
    byId("login-submit").disabled = false;
    byId("show-register").disabled = false;
    byId("show-client-register").disabled = false;
    byId("show-admin-login").disabled = false;
    byId("admin-login-submit").disabled = false;
  } catch (error) {
    mostrarAviso(error.message, true);
  }
  await cargarInformacionMensualidad();
}

inicializarAplicacion();
