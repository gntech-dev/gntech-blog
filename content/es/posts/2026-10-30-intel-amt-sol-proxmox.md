---
title: "Intel AMT Serial over LAN en Proxmox: configurar, iniciar sesión y desconectar"
description: "Identifica el dispositivo serie de AMT, habilita el inicio de sesión de Linux y distingue cerrar sesión de desconectar el cliente SOL."
date: 2026-10-31T02:00:00-04:00
lastmod: 2026-10-31
draft: false
translationKey: intel-amt-sol-proxmox
tags: [proxmox, intel-amt, linux, remote-access, homelab]
summary: "Edición resumida en español: detección del puerto, serial-getty, autenticación, desconexión y reversión."
cover:
  image: "/images/posts/intel-amt-sol/cover.webp"
  alt: "Ilustración de un mini PC y un portátil con una consola remota de texto."
  caption: "Ilustración generada con IA; no es una captura real ni un diagrama de cableado."
  relative: false
---

Una consola de recuperación sirve cuando el acceso habitual al servidor deja de funcionar. Intel AMT puede ofrecer Serial over LAN (SOL) en equipos compatibles.

Durante mis pruebas llegué al inicio de sesión de Proxmox y escribí `~.` para desconectar. Linux lo recibió como un nombre de usuario. La explicación: **cerrar la sesión de Linux y desconectar el cliente SOL son acciones diferentes**.

Esta es una **edición resumida en español** de la [guía completa en inglés](/posts/2026-10-30-intel-amt-sol-proxmox/). Conserva sus bloques de comandos; los mensajes que imprimen permanecen en inglés.

## Estado de verificación

| Alcance | Evidencia y límites |
| --- | --- |
| Entorno | Hosts Proxmox VE 9.2.21 con AMT; el puerto debe identificarse en cada equipo. |
| Observado previamente | Controlador SOL detectado en PVH01 e inicio de sesión de Linux accesible mediante SOL en PVH02. |
| Comprobación de preparación | Los diez bloques Bash son idénticos a los de la guía inglesa; allí pasaron una revisión de sintaxis. |
| Pendiente | Validar el cliente, firmware, dispositivo serie, configuración opcional y reconexión en el hardware de destino. |

La fecha de esta edición no representa una nueva prueba de hardware.

## Qué necesitas

Necesitas un equipo compatible con AMT SOL, AMT aprovisionado con SOL permitido y un cliente autenticado que alcance la red de administración. Tener un procesador Intel no garantiza esa compatibilidad.

Conserva una sesión SSH o consola local independiente mientras pruebas. Los comandos de configuración se ejecutan en una **shell root del host Proxmox**.

Mantén AMT en una red de administración de confianza o detrás de un acceso privado adecuado. Usa el modo cifrado y la validación de certificados que admita tu plataforma. No publiques directamente el acceso de administración en Internet.

AMT, el inicio de sesión de Linux y la redirección del arranque son capas distintas. Activar un getty no configura automáticamente BIOS, GRUB, mensajes del kernel ni KVM gráfico.

## 1. Identifica el dispositivo serie

```bash
hostname
pveversion
lspci -nnk | sed -n '/Communication controller/,+4p; /Serial controller/,+4p'
journalctl -k -b --no-pager | sed -n '/ttyS/p; /serial/p'
```

Busca el controlador PCI de SOL y su asignación a un dispositivo `ttyS` en los mensajes del kernel. La existencia de `/dev/ttyS0` por sí sola no demuestra que corresponda a AMT.

```bash
for serial_path in /sys/class/tty/ttyS*/device; do
    [ -e "$serial_path" ] || continue
    printf '%s -> ' "$serial_path"
    readlink -f "$serial_path"
done
```

Compara la ruta PCI cuando esté disponible. En PVH01 observé el controlador AMT SOL en `00:16.3`, con identificador `8086:a363`. El controlador HECI cercano es otro dispositivo: no confundas su función con el puerto serie.

## 2. Revisa el estado anterior

El ejemplo siguiente supone que confirmaste `ttyS0`. Modifica la variable si tu equipo usa otro puerto y continúa en la misma shell root:

```bash
sol_tty=ttyS0
test -c "/dev/$sol_tty" || { echo 'Serial device is missing'; exit 1; }
systemctl cat "serial-getty@$sol_tty.service"
systemctl is-enabled "serial-getty@$sol_tty.service"
systemctl is-active "serial-getty@$sol_tty.service"
```

Anota el estado original de habilitación y ejecución y conserva cualquier configuración local existente. Comprueba que otro servicio no esté usando el puerto. Un resultado inactivo o deshabilitado puede ser normal antes de configurarlo.

## 3. Habilita el inicio de sesión

```bash
systemctl enable --now "serial-getty@$sol_tty.service"
systemctl status "serial-getty@$sol_tty.service" --no-pager
journalctl -b -u "serial-getty@$sol_tty.service" --no-pager -n 30
```

Abre SOL y pulsa Enter. Si aparece el aviso de inicio de sesión y acepta entrada, la configuración básica funciona sin un archivo personalizado.

Si el cliente ofrece ajustes de velocidad y formato, comprueba que coincidan con el puerto. Un punto de partida habitual es 115200 baudios, 8 bits, sin paridad y un bit de parada; verifica lo que admite tu firmware y cliente.

## 4. Fija la velocidad solo si hace falta

Este ajuste es opcional, para un problema confirmado con la configuración original. **Reiniciar el getty termina cualquier sesión que lo esté usando.** Hazlo desde la sesión administrativa independiente.

```bash
test -x /sbin/agetty || { echo 'Check the agetty path first'; exit 1; }
override_dir="/etc/systemd/system/serial-getty@$sol_tty.service.d"
install -d -m 0755 "$override_dir"
if [ -e "$override_dir/60-amt-sol.conf" ]; then
    cp -a "$override_dir/60-amt-sol.conf" \
      "$override_dir/60-amt-sol.conf.bak-$(date +%Y%m%d-%H%M%S)"
fi
cat > "$override_dir/60-amt-sol.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --noclear --local-line 115200 %I vt100
EOF
systemctl daemon-reload
systemctl restart "serial-getty@$sol_tty.service"
systemctl status "serial-getty@$sol_tty.service" --no-pager
```

La línea vacía `ExecStart=` borra el comando heredado antes de sustituirlo. `%I` representa el dispositivo de esta instancia; `--local-line` evita depender de la señal de portadora y `vt100` establece el tipo de terminal.

No activa el inicio automático de sesión ni cambia permisos de cuentas. Revisa el resultado con `systemctl cat`, especialmente si ya existían otros ajustes.

## 5. Inicia sesión con una cuenta Linux

La autenticación AMT abre la conexión de administración. El aviso de Linux solicita **otra autenticación**, con una cuenta local autorizada para la consola. Un usuario web como `usuario@pve` no es automáticamente un nombre de cuenta Linux.

Es normal que la contraseña no muestre caracteres. Después de entrar, confirma el host y el terminal:

```bash
hostname
tty
whoami
```

En este ejemplo, el terminal debería ser `/dev/ttyS0`. Si falla la autenticación, revisa la cuenta y los registros mediante tu acceso administrativo existente.

## 6. Cierra sesión y después desconecta

En la shell Linux:

```bash
exit
```

Si abriste shells o sesiones SSH anidadas, sal de ellas hasta regresar al aviso de inicio de sesión del host. Después usa **Disconnect**, **Close session** o el control equivalente del cliente SOL.

Cerrar la ventana no garantiza que termine la sesión Linux: al reconectar podrías encontrar una shell todavía autenticada.

| Situación | Acción |
| --- | --- |
| Dentro de la shell Linux | Ejecuta `exit` hasta volver al inicio de sesión. |
| En el aviso de inicio de sesión | Desconecta desde el cliente SOL. |
| Buscando un atajo de escape | Consulta la ayuda del cliente concreto. |

`~.` es una secuencia reconocida por algunos clientes SSH bajo condiciones específicas; **no es una orden universal de AMT**. Si aparece `login: ~.`, llegó a Linux como texto. Cancela o deja terminar el intento y desconecta con el control del cliente.

## Consola Linux y mensajes de arranque

Puedes tener un inicio de sesión funcional sin ver mensajes anteriores del arranque. Inspecciona los parámetros actuales sin modificarlos:

```bash
cat /proc/cmdline
```

Un parámetro como `console=ttyS0,115200n8` puede habilitar salida serie del kernel, pero requiere el puerto correcto. La entrada y salida del cargador se configuran aparte; el orden de varios parámetros `console=` también puede influir.

Proxmox puede usar GRUB o una configuración con systemd-boot/proxmox-boot-tool. Identifica el mecanismo antes de editarlo y conserva una vía de recuperación. Este procedimiento no modifica el arranque.

## Problemas frecuentes

| Síntoma | Qué revisar |
| --- | --- |
| No conecta SOL | Aprovisionamiento AMT, permisos SOL, cliente, red y estado de energía admitido. |
| Conecta pero no aparece texto | Pulsa Enter; comprueba la asignación del puerto y el getty. |
| Caracteres ilegibles | Velocidad, formato y emulación de terminal. |
| Hay texto pero no entrada | Captura de teclado del cliente y otro proceso usando el puerto. |
| Funciona login pero no se ve el arranque | Configuración del kernel y cargador, separada del getty. |
| Reconecta a una shell abierta | Cierra explícitamente la sesión antes de desconectar. |

No reinicies un host de producción como primera prueba: revisa primero el estado del servicio y sus registros.

## Reversión

Si creaste desde cero el ajuste opcional de velocidad, elimina únicamente ese archivo y reinicia desde tu sesión independiente:

```bash
rm -i "/etc/systemd/system/serial-getty@$sol_tty.service.d/60-amt-sol.conf"
systemctl daemon-reload
systemctl restart "serial-getty@$sol_tty.service"
```

Si el archivo ya existía, restaura su copia anterior. Conserva los demás ajustes del servicio.

Solo si el getty estaba **deshabilitado e inactivo** antes de empezar, puedes revertir su activación así:

```bash
systemctl disable --now "serial-getty@$sol_tty.service"
```

Para otros estados originales, restaura por separado la habilitación y ejecución que anotaste. Un getty generado por los parámetros de consola o requerido por otro servicio puede reaparecer; deshabilitarlo no anula esas otras causas.

## Prueba final

Conecta, verifica el nombre del host, inicia sesión, ejecuta una consulta inocua, sal hasta el aviso de login y reconecta. Comprueba por separado la visibilidad durante el arranque en una ventana de mantenimiento.

Consulta la [guía completa y sus referencias](/posts/2026-10-30-intel-amt-sol-proxmox/) para ampliar el contexto. La traducción no añade validación de firmware, hardware o versiones. Para más rutas de lectura, visita [Empieza aquí](/es/start-here/).
