# Rijo Express para Windows

Aplicación de escritorio para administrar empresas de préstamos, clientes, préstamos, pagos y mensualidades. El programa de uso normal es `dist\rijoexpress.exe`; no necesita navegador ni servidor web.

## Ejecutar y compilar

Para usar el ejecutable, abre `dist\rijoexpress.exe`. Puedes copiarlo a una carpeta de tu computadora o a una memoria USB. El ejecutable de Windows no funciona en Android ni iPhone.

Para ejecutar desde el código o volver a crear el EXE:

```powershell
python -m pip install -r requirements.txt
python -m PyInstaller --clean --noconfirm app.spec
```

El archivo resultante queda en `dist\rijoexpress.exe`. En una instalación nueva, el programa permite configurar el primer administrador. Si junto al ejecutable hay una base de datos `rijoexpress.db`, la copia a la carpeta local de datos al abrirse por primera vez.

## Datos y copias de seguridad

- La base activa está en `%LOCALAPPDATA%\RijoExpress\rijoexpress.db`, separada del EXE para evitar problemas de permisos.
- Esta versión no sincroniza por Internet. Suspender o renovar una cuenta solo cambia la base de datos de esa computadora.
- La primera ejecución conserva una base `rijoexpress.db` que ya esté junto al ejecutable o en la carpeta superior.
- Para guardar una copia en una memoria USB, inserta la memoria, inicia sesión y pulsa **Backup de Datos**. Elige la unidad USB; se guardará allí un archivo `RijoExpress-backup-fecha-hora.db` con clientes, préstamos, pagos y cuentas.
- Al cerrar, también se genera una copia local en `%LOCALAPPDATA%\RijoExpress\backup`.
- Para reemplazar la base de datos de una instalación existente, cierra el programa y guarda primero una copia de la base actual. Luego reemplaza `%LOCALAPPDATA%\RijoExpress\rijoexpress.db` por el respaldo deseado.
- La copia contiene datos de todas las cuentas. No la compartas; úsala solo para respaldar o trasladar la instalación entre equipos controlados por la administración.

## Cuentas y planes de la aplicación web

- El acceso de administración está separado del registro gratuito de empresas. Estas reglas aplican a la aplicación web; el programa de escritorio mantiene datos locales y no sincroniza ni aplica la cuota web.
- Cada cuenta nueva puede crear hasta 5 préstamos en total sin pagar. El sexto requiere Premium; después de activar Premium, la membresía es mensual aunque la cuenta tenga pocos préstamos.
- El precio inicial de Premium es RD$600 por mes. El administrador puede cambiarlo en **Suscripciones**; las activaciones y renovaciones se confirman manualmente al recibir el comprobante por WhatsApp.
- Después del vencimiento, Premium conserva acceso normal por 3 días; al terminar el plazo se suspende hasta registrar el pago.
- La administración puede consultar cuentas e historial, suspender/reactivar el acceso y restablecer contraseñas. Las contraseñas se guardan como hashes y las claves temporales se muestran una sola vez.
- Los clientes, préstamos y pagos de cada empresa se guardan por separado en la base de datos.
- La empresa genera un código de activación de un solo uso para cada cliente prestatario. El cliente usa el usuario de la empresa, su ID y ese código para consultar únicamente sus propios préstamos, balances e historial de pagos.

## Aplicación web y publicación en Google

La aplicación web es independiente del programa de escritorio. Para probarla localmente, instala los requisitos y ejecuta `python web_app.py`; el servidor local no es visible en Internet. Para usarla desde teléfonos y computadoras, publícala en un hosting HTTPS compatible con Flask y configura una base de datos persistente. En un navegador compatible, el botón **Instalar app** permite instalar la PWA.

En producción, configura como mínimo `RIJO_ENV=production`, `RIJO_SECRET_KEY` con un valor secreto aleatorio, `RIJO_HTTPS=1`, `RIJO_DB_PATH` para la base persistente y `RIJO_PUBLIC_URL` con la URL pública final (por ejemplo, `https://tudominio.com`). El precio Premium inicial es RD$600/mes y el pago se confirma manualmente por WhatsApp. Haz respaldos regulares y no publiques ni compartas la base de datos.

La página pública incluye información descriptiva, metadatos para buscadores, `robots.txt` y `sitemap.xml`. Cuando el sitio esté publicado, registra el dominio en Google Search Console y envía `https://tudominio.com/sitemap.xml`. La inclusión en Google requiere un dominio público accesible y la revisión de Google; no puede lograrse desde el EXE ni desde una instalación local, y no se puede garantizar una posición en los resultados.

La aplicación de escritorio guarda sus datos en esta computadora. Para trasladarlos a otra instalación controlada por la administración, crea un respaldo y copia el archivo de respaldo como `rijoexpress.db` junto al ejecutable antes de abrirlo por primera vez en la otra computadora.

El archivo de base de datos, los respaldos y los secretos locales están excluidos por `.gitignore`; no los subas a GitHub.

## Plantilla visual para Blogger

El archivo `rijoexpress-blogger.xml` es una plantilla XML para la página informativa de Rijo Express en Blogger. Para cargarla, guarda una copia de tu tema actual; luego, en Blogger, abre **Tema**, selecciona el menú junto a **Personalizar**, elige **Restaurar** y sube el XML. En **Diseño** puedes añadir publicaciones, editar el título del blog y revisar el enlace de WhatsApp (`https://wa.me/18099070345`).

Esta plantilla muestra información y entradas del blog. Blogger no ejecuta la aplicación Flask ni guarda las cuentas, clientes, préstamos, pagos o suscripciones de Rijo Express. Para usar esas funciones hace falta publicar la aplicación en un hosting compatible por separado.
