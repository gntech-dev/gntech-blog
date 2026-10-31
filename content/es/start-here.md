---
title: "Empieza aquí"
description: "Elige una ruta práctica de lectura sobre Proxmox, MikroTik, Docker y administración del laboratorio."
date: 2026-10-30T14:00:00-04:00
draft: false
translationKey: start-here
ShowToc: true
lastmod: 2026-10-31
---

Bienvenido a **GnTech**. Elige el problema que quieres resolver y sigue una ruta corta por las guías. No necesitas leer el blog en orden de publicación.

Las guías técnicas enlazadas en estas rutas están en **inglés**. Esta página te ayuda a elegirlas mientras se amplían las traducciones.

| Tu objetivo | Por dónde empezar |
| --- | --- |
| Crear un laboratorio virtualizado | [Fundamentos de Proxmox](#fundamentos-de-proxmox) |
| Separar usuarios, servidores y dispositivos | [Redes MikroTik](#redes-mikrotik) |
| Alojar y mantener servicios propios | [Docker Compose](#docker-compose) |
| Respaldar servicios y comprobar la recuperación | [Respaldos y recuperación](#respaldos-y-recuperación) |
| Administrar y recuperar tus equipos | [Administración y recuperación](#administración-y-recuperación) |

## Fundamentos de Proxmox

Empieza por la red para comprender cómo se conectan el host y las máquinas virtuales. Después prepara despliegues repetibles y planifica los respaldos.

1. [Puentes, VLAN y topología del host (inglés)](https://blog.gntech.me/posts/2026-05-08-proxmox-networking-bridges-vlans/) — entiende la red antes de modificarla.
2. [Plantillas de máquinas virtuales con cloud-init (inglés)](https://blog.gntech.me/posts/2026-05-16-proxmox-cloudinit-vm-templates/) — prepara configuraciones reutilizables.
3. [Proxmox Backup Server (inglés)](https://blog.gntech.me/posts/2026-05-08-proxmox-backup-server-setup/) — conoce el servicio de respaldos y sus almacenes de datos.

**Objetivo práctico:** dibuja el recorrido de red del host a una máquina virtual, crea una máquina de pruebas y comprueba la recuperación antes de confiar en un respaldo.

## Redes MikroTik

Estas guías requieren acceso al router y conocer las interfaces que vas a cambiar. Conserva una conexión de recuperación al modificar el acceso de administración o el filtrado VLAN.

1. [Construcción de R1 (inglés)](https://blog.gntech.me/posts/r1-router-deployment/) — conoce las piezas de un router segmentado.
2. [Segmentación por VLAN (inglés)](https://blog.gntech.me/posts/2026-05-12-mikrotik-vlan-segmentation/) — recorre el enrutamiento, DHCP y aislamiento.
3. [Redes en Proxmox (inglés)](https://blog.gntech.me/posts/2026-05-08-proxmox-networking-bridges-vlans/) — conecta el diseño del router con el host de virtualización.

**Objetivo práctico:** verifica tanto una conexión permitida como una que debería quedar bloqueada.

## Docker Compose

Comienza con pocos servicios. Comprende su almacenamiento, configuración y arranque antes de agregar aplicaciones.

1. [Patrones de Compose (inglés)](https://blog.gntech.me/posts/2026-05-08-docker-compose-patterns/) — organiza servicios y configuraciones.
2. [Comprobaciones de salud y dependencias de arranque (inglés)](https://blog.gntech.me/posts/2026-05-14-docker-compose-healthchecks/) — distingue un proceso en ejecución de un servicio listo.
3. [Despliegue de Frigate (inglés)](https://blog.gntech.me/posts/frigate-deployment/) — explora un proyecto de cámaras después de los fundamentos.

**Objetivo práctico:** recrea un conjunto de servicios de pruebas y comprueba que sus datos persisten. La guía de Frigate describe un despliegue anterior; revisa sus versiones y requisitos de hardware.

## Respaldos y recuperación

1. [Estrategia y copias independientes (inglés)](https://blog.gntech.me/posts/2026-05-23-proxmox-backup-strategies/) — define los objetivos y el fallo que debe soportar cada copia.
2. Para máquinas virtuales, sigue [PBS y recuperación aislada (inglés)](https://blog.gntech.me/posts/2026-05-08-proxmox-backup-server-setup/). Para PostgreSQL, usa el [laboratorio de exportación, programación y recuperación mediante Restic (inglés)](https://blog.gntech.me/posts/2026-06-01-docker-database-backup-automation-pgdump-cron/).
3. El [laboratorio de Restic (inglés)](https://blog.gntech.me/posts/2026-05-19-restic-docker-backup-strategy/) explica la recuperación de archivos y la copia entre repositorios con contraseñas separadas.

**Objetivo práctico:** recuperar en un destino aislado usando la copia y las credenciales disponibles después de un fallo. Los repositorios locales de CI comprueban los comandos; no validan tu almacenamiento remoto ni la recuperación del hardware.

## Administración y recuperación

Un equipo cliente cómodo y una consola de recuperación probada resuelven partes distintas del trabajo de administración.

1. [ThinkPad T420 con Arch Linux e i3 (inglés)](https://blog.gntech.me/posts/2026-10-30-thinkpad-t420-arch-i3/) — prepara un escritorio para administración.
2. [Intel AMT Serial over LAN en Proxmox (inglés)](https://blog.gntech.me/posts/2026-10-30-intel-amt-sol-proxmox/) — configura el acceso por consola y aprende a desconectarte correctamente.

**Objetivo práctico:** conecta con el host correcto, confirma su identidad, cierra la sesión y vuelve a conectar hasta ver un nuevo aviso de inicio de sesión.

## Cómo usar una guía

Revisa los requisitos, las versiones y las notas de validación antes de copiar comandos. Distingue los resultados observados de las configuraciones de ejemplo. Conserva los respaldos y el acceso de recuperación adecuados para el cambio y verifica el resultado completo.

Para un síntoma concreto, usa el [buscador](/es/search/). También puedes consultar los [proyectos](/es/projects/), leer [acerca del blog](/es/about/) o explorar [todos los artículos](/es/archives/). Sigue las publicaciones por [RSS](/es/index.xml).
