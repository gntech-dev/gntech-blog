---
title: "Proxmox VM Disk Performance — VirtIO-blk vs VirtIO-SCSI, IO Threads & Cache Modes"
description: "Benchmark and tune Proxmox VM disk performance. Compare VirtIO-blk vs VirtIO-SCSI single controllers, IO threads, aio modes, and cache settings with fio benchmark results."
date: 2026-06-12T16:30:00-04:00
tags:
  - proxmox
  - virtualization
  - storage
  - performance
  - linux
keywords:
  - Proxmox VirtIO-blk VirtIO-SCSI single disk controller performance benchmark
  - Proxmox VM IO thread single vs multi-queue configuration guide
  - Proxmox aio native io_uring comparison VM disk performance
  - Proxmox disk cache mode none writeback writethrough benchmark
  - Proxmox fio benchmark VM disk IOPS latency throughput
  - KVM virtio disk controller tuning homelab best practices
  - Proxmox qemu command line drive iothread options Proxmox VE
summary: "Compare VirtIO-blk vs VirtIO-SCSI single disk controllers in Proxmox, benchmark IO threads and aio modes with fio, and choose the right cache settings for your homelab VMs."
canonical: "https://blog.gntech.me/posts/proxmox-vm-disk-performance-benchmark/"
---

Crear una VM en Proxmox es fácil. Conseguir que rinda al máximo en disco no lo es. Cuatro ajustes —el controlador de disco, el IO thread, el modo aio, y el modo de caché— determinan si tu VM obtiene 200 mil IOPS o 600 mil en el mismo hardware. La diferencia es real, medible, y muchas VM en homelab corren con valores por defecto que dejan hasta un 40 % de rendimiento sobre la mesa.

Esta guía cubre cada uno de esos parámetros: qué hacen, cómo configurarlos, cuándo elegir cada combinación, y cómo medir los resultados con fio. Todos los comandos y configs funcionan en Proxmox VE 8.x y 9.x.

## VirtIO-blk vs VirtIO-SCSI Single: Choosing the Right Disk Controller

Proxmox ofrece dos controladores paravirtualizados principales para discos de VM Linux. Cada uno tiene fortalezas distintas.

### VirtIO-blk

El controlador VirtIO-blk es el más antiguo de los dos. Fue el primer controlador de bloque completamente paravirtualizado para KVM, diseñado para ser simple y rápido. En benchmarks puros de throughput secuencial, VirtIO-blk sin IO thread suele igualar o superar ligeramente a VirtIO-SCSI en las mismas condiciones. Sin embargo, carece de soporte para discard/trim, no expone un bus SCSI real al guest, y no permite el uso de IO threads dedicados por disco — el IO thread se asigna al controlador completo.

Usa VirtIO-blk cuando:
- La VM corre kernels anteriores a 4.x
- No necesitas discard/trim
- Buscas la máxima velocidad en benchmarks sintéticos secuenciales
- Es una VM Windows con drivers virtio-win (tradicionalmente mejor soportados)

### VirtIO-SCSI Single

El controlador VirtIO-SCSI Single es el valor por defecto en Proxmox desde la versión 4.3. Usa un bus SCSI real sobre el transporte virtio, lo que le da varias ventajas: soporte completo de discard/trim, fences de cache (cache flushes), y la capacidad de asignar un IO thread dedicado por controladora SCSI. Es la opción recomendada para la gran mayoría de cargas de trabajo.

```bash
# Asignar VirtIO-SCSI Single con IO thread y discard
qm set 100 -scsi0 local-zfs:vm-100-disk-0,iothread=1,discard=on
```

VirtIO-SCSI (sin "Single") activa multi-queue con múltiples IO threads. Es útil cuando tienes muchos discos en una sola VM con alta concurrencia, pero para la mayoría de los homelabs con 1-3 discos por VM, VirtIO-SCSI Single ofrece mejor rendimiento porque evita la contención entre IO threads.

Verifica el controlador actual de tu VM:

```bash
qm config 100 | grep -E '(scsi|virtio)[0-9]+'
# scsi0: local-zfs:vm-100-disk-0,iothread=1,size=64G
```

## IO Threads: Dedicated Host Threads for Disk I/O

Cuando una VM ejecuta operaciones de disco sin IO thread, todo el I/O pasa por el hilo principal de QEMU — el mismo que maneja la emulación de la CPU, los dispositivos virtuales, y la red. Esto crea contención: una operación de disco bloquea otros trabajos del hilo principal, y viceversa.

Activar IO threads asigna un hilo de host independiente a cada controladora de disco. El beneficio es doble: menor latencia de I/O porque el hilo principal de QEMU ya no se intercala con operaciones de disco, y mejor uso de la caché de CPU porque el hilo de disco trabaja en un conjunto de datos más predecible.

```bash
# Habilitar IO thread en disco SCSI
qm set 100 -scsi0 local-zfs:vm-100-disk-0,iothread=1

# Habilitar IO thread en disco VirtIO-blk
qm set 100 -virtio0 local-zfs:vm-100-disk-0,iothread=1
```

Elige el número correcto de IO threads según tu hardware:

| Escenario                    | IO Threads recomendados |
|------------------------------|------------------------|
| 1-2 discos, VM típica       | 1 (VirtIO-SCSI Single) |
| 3+ discos, alta concurrencia | 2-3 (VirtIO-SCSI multi) |
| Host con 4+ núcleos/VMs ligeras | 1 por VM               |
| Host con muchas VMs (>10)   | IO thread solo en VMs críticas |

Verifica que el IO thread esté activo desde el host:

```bash
ps aux | grep qemu | grep -E 'iothread'
```

Si el proceso QEMU de tu VM tiene el flag `iothread` entre sus argumentos, el IO thread está funcionando.

## AIO Mode: How QEMU Submits I/O to the Kernel

El modo aio (asynchronous I/O) controla cómo QEMU envía operaciones de disco al kernel del host. Proxmox soporta tres modos.

### aio=native

Usa Linux AIO (libaio) con semántica O_DIRECT. Es el modo más maduro y probado. Funciona bien con discos rotativos, SSDs decentes, y configuraciones ZFS. Es el valor por defecto histórico de Proxmox.

### aio=io_uring

Introducido en Linux 5.1 y estable desde 5.4, io_uring es el reemplazo moderno de libaio. Reduce la sobrecarga de syscalls drásticamente: donde libaio requiere una syscall por lote de I/O, io_uring usa un ring buffer compartido entre kernel y userspace. En hardware NVMe moderno, io_uring suele superar a native entre un 10-20 % en IOPS aleatorias.

```bash
# Cambiar a io_uring en un disco existente
qm set 100 -scsi0 iothread=1,aio=io_uring
```

### aio=threads

Emula I/O asíncrono con un pool de pthreads. Tiene la mayor sobrecarga y solo debe usarse si native e io_uring no funcionan — por ejemplo, con ciertos backends de almacenamiento antiguos. En un homelab moderno no deberías necesitarlo.

```bash
# Ver modo aio actual
qm config 100 | grep aio
# scsi0: local-zfs:vm-100-disk-0,iothread=1,aio=io_uring,size=64G
```

Recomendación: usa `aio=io_uring` en cualquier host con Proxmox VE 8.x o superior y kernel 6.2+. Para kernels anteriores, usa `aio=native`.

## Cache Modes: none vs writeback vs writethrough vs unsafe

El modo de caché controla cómo QEMU interactúa con el page cache del host. Es el parámetro que más impacto tiene en el rendimiento de escritura — y también el que más riesgo conlleva.

### cache=none

Usa O_DIRECT para saltarse el page cache del host por completo. Las escrituras se reportan como completadas solo cuando llegan al dispositivo de almacenamiento. Es el modo por defecto y el más seguro para datos importantes. El guest maneja su propia caché (el page cache del guest Linux), y QEMU no añade una segunda capa.

### cache=writeback

QEMU usa el page cache del host. Las escrituras se reportan como completadas cuando llegan a la RAM del host, no al disco. Esto permite al kernel del host coalescer operaciones pequeñas en escrituras más grandes y reordenarlas para maximizar el throughput. En benchmarks, writeback puede duplicar las IOPS de escritura comparado con none.

El riesgo: si el host pierde energía, cualquier dato que esté en el page cache del host se pierde. Los guests que usan writeback no pueden garantizar la integridad de la transacción a menos que el host tenga una batería (BBU) o un UPS y discard flush commands no sea un problema.

### cache=writethrough

Cada escritura se confirma en el almacenamiento antes de reportarse como completa. Es el modo más lento y el más seguro. Combina la verificación de O_DSYNC con el uso del page cache del host para lecturas. En la práctica, su rendimiento es tan bajo que no lo recomendamos para nada que no sea una base de datos financiera o cumplimiento normativo.

### cache=unsafe

QEMU ignora todos los comandos de cache flush que envía el guest. Las escrituras van al page cache del host y se reportan como completas instantáneamente. Es extremadamente rápido y extremadamente peligroso. Úsalo solo en entornos efímeros: CI runners, VMs de desarrollo que se reconstruyen desde cero, o pruebas donde la pérdida de datos no importa.

### Tabla de recomendaciones prácticas

| Carga de trabajo             | Cache    | AIO       | Controlador          | IO thread |
|------------------------------|----------|-----------|----------------------|-----------|
| Base de datos (PostgreSQL, MariaDB) | none | io_uring | VirtIO-SCSI Single   | sí        |
| NAS / file server            | none     | native    | VirtIO-SCSI Single   | sí        |
| VM de desarrollo efímera     | writeback| io_uring  | VirtIO-blk           | sí        |
| CI runner (GitHub Actions)   | unsafe   | io_uring  | VirtIO-blk           | no        |
| Servidor web / aplicación    | none     | io_uring  | VirtIO-SCSI Single   | sí        |
| Cache / Redis (persistencia) | writeback| native    | VirtIO-SCSI Single   | sí        |

Cambia el modo de caché en una VM existente:

```bash
# De none a writeback (más velocidad, más riesgo)
qm set 100 -scsi0 local-zfs:vm-100-disk-0,cache=writeback,iothread=1,aio=io_uring
```

## Benchmarking with fio Inside Proxmox VMs

La única forma de saber qué combinación funciona mejor para tu hardware y tu carga de trabajo es medir. Usa fio dentro de la VM con parámetros controlados.

Instala fio en el guest Linux:

```bash
apt update && apt install fio -y
```

### Benchmark de lectura secuencial (throughput)

```bash
fio --name=seq-read --filename=/tmp/fio-test --size=4G \
    --ioengine=libaio --iodepth=32 --direct=1 \
    --rw=read --bs=1M --numjobs=1 --runtime=30 \
    --output-format=json --output=/tmp/fio-seq-read.json
```

### Benchmark de escritura aleatoria 4K (IOPS)

```bash
fio --name=randwrite-4k --filename=/tmp/fio-test --size=4G \
    --ioengine=libaio --iodepth=32 --direct=1 \
    --rw=randwrite --bs=4K --numjobs=4 --runtime=60 \
    --output-format=json --output=/tmp/fio-randwrite-4k.json
```

### Benchmark mixto 70/30 (carga típica de base de datos)

```bash
fio --name=mixed --filename=/tmp/fio-test --size=4G \
    --ioengine=libaio --iodepth=16 --direct=1 \
    --rw=randrw --rwmixread=70 --bs=8K --numjobs=2 --runtime=60 \
    --output-format=json --output=/tmp/fio-mixed.json
```

Extrae los resultados relevantes:

```bash
# IOPS de escritura
jq '.jobs[] | .write.iops' /tmp/fio-randwrite-4k.json
# Latencia P99 de escritura (usec)
jq '.jobs[] | .write.clat_ns.percentile["99.000000"]' /tmp/fio-randwrite-4k.json
# Throughput de lectura (bytes/seg)
jq '.jobs[] | .read.bw_bytes' /tmp/fio-seq-read.json
```

### Lo que encontré en mi homelab

En un host SRV1 con Proxmox VE 8.3, ZFS sobre dos NVMe Samsung PM9A3 en mirror, una VM Debian 13 con 4 vCPU y 8 GB RAM:

| Configuración                                    | IOPS randwrite 4K | Throughput seq read | P99 lat write |
|--------------------------------------------------|-------------------|---------------------|---------------|
| VirtIO-blk, cache=none, aio=native, no iothread  | 118K              | 1.1 GB/s            | 2.1 ms        |
| VirtIO-SCSI Single, cache=none, aio=native, iothread | 142K          | 1.3 GB/s            | 1.4 ms        |
| VirtIO-SCSI Single, cache=none, aio=io_uring, iothread | 189K         | 1.6 GB/s            | 0.9 ms        |
| VirtIO-blk, cache=writeback, aio=io_uring, iothread | 315K          | 1.8 GB/s            | 0.3 ms        |
| VirtIO-blk, cache=unsafe, aio=io_uring, iothread | 412K            | 2.0 GB/s            | 0.1 ms        |

Los números de writeback y unsafe son llamativos, pero implican riesgo de pérdida de datos en un corte de luz. Para mi homelab, VirtIO-SCSI Single + cache=none + aio=io_uring + iothread es el punto óptimo: ganas un 60 % de IOPS sobre los valores por defecto sin sacrificar seguridad.

## Applying the Optimal Configuration via CLI

Cambia todos los parámetros de una sola vez sin interfaz gráfica:

```bash
VMID=100

# Configuración óptima para base de datos / uso general
qm set $VMID \
  -scsi0 local-zfs:vm-${VMID}-disk-0,iothread=1,aio=io_uring,cache=none,discard=on \
  -scsihw virtio-scsi-single
```

Para aplicar la configuración a una VM existente, la VM debe estar apagada si estás cambiando el tipo de controladora (`-scsihw`). Los parámetros `iothread`, `aio`, y `cache` pueden cambiarse en caliente.

## Summary

Cinco decisiones determinan el rendimiento de disco de tus VMs en Proxmox:

1. **Controladora**: VirtIO-SCSI Single para uso general (default desde PVE 4.3 por una razón)
2. **IO thread**: actívalo siempre con `iothread=1` — el costo es mínimo y la ganancia de latencia es constante
3. **AIO mode**: `aio=io_uring` en Proxmox 8+ con kernel moderno; `aio=native` como respaldo
4. **Cache mode**: `cache=none` para datos importantes (seguro, rápido); `cache=writeback` para VMs efímeras si entiendes el riesgo
5. **Benchmark**: corre fio con `direct=1` y `--output-format=json` antes de decidir — los benchmarks sintéticos no mienten, pero solo importan si reflejan tu carga real

El cambio más impactante que puedes hacer hoy: agrega `iothread=1` y `aio=io_uring` a tu disco principal. Son dos parámetros, sin riesgo de pérdida de datos, y en la mayoría de los casos te dan entre un 20-60 % más de IOPS sin tocar el hardware.
