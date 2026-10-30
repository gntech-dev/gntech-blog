---
title: "Acerca de"
description: "Gerlin Nolasco, el laboratorio GnTech y cómo se preparan estas guías de infraestructura."
date: 2026-05-08
lastmod: 2026-10-30
translationKey: about
---

Soy **Gerlin Nolasco**, la persona detrás de **GnTech**.

Documento la infraestructura que construyo, mantengo y diagnostico: hosts Proxmox, redes MikroTik, sistemas Linux y Windows, servicios Docker y herramientas de administración remota. El objetivo es convertir un problema real en una guía que otra persona pueda entender y seguir.

## Qué encontrarás aquí

- **Virtualización y almacenamiento:** Proxmox VE, máquinas virtuales, LXC, ZFS y respaldos.
- **Redes:** MikroTik, VLAN, enrutamiento, VPN y acceso de administración.
- **Servicios propios:** Docker Compose, proxies inversos, monitoreo y mantenimiento.
- **Diagnóstico:** síntomas, pruebas, cambios y verificación de una solución.
- **Equipos con una segunda vida:** experimentos prácticos como mi ThinkPad T420 para administración.

Puedes comenzar por los [proyectos](/es/projects/), usar el [buscador](/es/search/) o explorar los [archivos](/es/archives/).

## El laboratorio detrás de las guías

El trabajo abarca un laboratorio en casa e infraestructura alojada. Proxmox proporciona la virtualización; MikroTik, el enrutamiento y la segmentación; Docker y LXC alojan servicios. El monitoreo, los respaldos y el acceso de recuperación también forman parte del proyecto.

El laboratorio cambia con el tiempo. Cada artículo describe su propio entorno: una lista de equipos o un diagrama antiguo no representa necesariamente el inventario actual. Los ejemplos públicos incluyen los detalles necesarios para explicar el procedimiento.

## Cómo se preparan los artículos

La IA ayuda a redactar, organizar explicaciones, preparar ilustraciones y revisar ejemplos. Reviso los cambios mediante pull requests en GitHub antes de integrarlos. Integrar un artículo listo para publicar activa el despliegue habitual del sitio en Cloudflare Pages.

Las comprobaciones automáticas pueden detectar errores de compilación, recursos ausentes, enlaces internos rotos y algunos errores de sintaxis. No demuestran que un comando funcione en un equipo concreto ni que un procedimiento sea adecuado para cualquier entorno.

Los artículos deben distinguir los resultados observados en el laboratorio de los ejemplos propuestos y explicar sus límites de validación. Revisar la sintaxis no equivale a probar el hardware. Comprueba los requisitos y las versiones, conserva una vía de recuperación y verifica el resultado en tu entorno.

Las ilustraciones generadas se identifican como tales. Las capturas reales y las salidas de comandos, cuando se incluyen, muestran lo que se observó.

## Sobre el sitio

GnTech utiliza [Hugo](https://gohugo.io/) y el [tema PaperMod](https://github.com/adityatelange/hugo-PaperMod), con alojamiento en Cloudflare Pages. El blog está disponible en inglés y español; las traducciones se amplían a medida que se revisan las guías.

## Contacto

- [GitHub: gntech-dev](https://github.com/gntech-dev)
- [LinkedIn: Gerlin Nolasco](https://www.linkedin.com/in/gnolascohernandez/)
- [Suscripción por RSS](/es/index.xml)
