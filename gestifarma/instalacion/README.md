# Instalación de Gestifarma en el cliente

Manual técnico para instalar Gestifarma en un servidor de la farmacia (opción recomendada) o en la nube
propia de la farmacia. Los datos quedan en la infraestructura de la farmacia; Gestifarma instala, mantiene y
da soporte. La propuesta para el cliente (opciones, seguridad, soporte) está en el documento «Gestifarma en
la farmacia: instalación, datos y soporte».

Todo se maneja con un solo comando, `./gestifarma.sh`, desde esta carpeta:

```text
./gestifarma.sh instalar                  primera instalación: claves, arranque y primer respaldo
./gestifarma.sh actualizar [versión]      respaldo previo, versión nueva y verificación; si falla, vuelve sola atrás
./gestifarma.sh respaldar                 respaldo inmediato (además del de todas las noches)
./gestifarma.sh respaldos [remoto]        lista los respaldos
./gestifarma.sh restaurar [id] [remoto]   restaura la base y las fotos de un respaldo
./gestifarma.sh estado                    servicios, versión, disco y último respaldo
./gestifarma.sh registros [servicio]      registros (app, proxy, db, respaldo)
./gestifarma.sh reiniciar [servicio]      reinicia la app, por ejemplo después de cambiar config/
```

## Qué queda instalado

```text
celulares y PC ──HTTPS──▶ proxy (Caddy) ──▶ app (Gestifarma) ──▶ db (PostgreSQL)
                                                 │                    │
                                              fotos ◀── respaldo ──▶ disco externo + copia fuera del local
```

| Servicio | Qué hace | Imagen |
| --- | --- | --- |
| `proxy` | HTTPS con certificado válido que se renueva solo | Caddy 2.10 con el módulo DNS de Cloudflare |
| `app` | Gestifarma: web, lectura de recetas sin IA y conciliación | Construida desde este repositorio o publicada |
| `db` | Base de datos; no es accesible desde fuera del servidor | PostgreSQL 17 |
| `respaldo` | Respaldo cifrado todas las noches y antes de cada actualización | PostgreSQL 17 + restic 0.17 |

Los datos viven en volúmenes de Docker (`base`, `archivos`) sobre el disco cifrado del servidor. La
configuración de la farmacia (reglas de los convenios y formatos de los reportes) queda en `config/`, y el
estado de respaldos y versiones en `estado/`.

## 1. Preparar el servidor

Equipo recomendado: mini PC de 4 núcleos, 16 GB de RAM, SSD de 1 TB, red por cable y TPM 2.0, con UPS y un
disco externo USB de 2 TB para los respaldos.

1. **Sistema operativo:** Ubuntu Server 24.04 LTS, con el disco cifrado (LUKS) desde el instalador. Para que
   arranque solo después de un corte de luz, atar el desbloqueo al chip TPM con Clevis y guardar la frase de
   recuperación en el sobre de la farmacia:

   ```bash
   sudo apt install clevis clevis-luks clevis-tpm2 clevis-initramfs
   sudo clevis luks bind -d /dev/<partición-cifrada> tpm2 '{"pcr_ids":"7"}'
   sudo update-initramfs -u
   ```

2. **Acceso:** un usuario administrador, SSH solo con clave pública y solo desde la red del local o la VPN.
3. **Parches de seguridad automáticos:** `sudo dpkg-reconfigure -plow unattended-upgrades` (viene instalado).
4. **Docker:** Docker Engine y el complemento Compose desde el repositorio oficial de Docker
   ([instrucciones](https://docs.docker.com/engine/install/ubuntu/)). Agregar el usuario al grupo `docker`.
5. **Disco de respaldo:** formatearlo en ext4 y montarlo por UUID con `nofail`, para que el servidor arranque
   aunque el disco no esté. No hace falta cifrarlo: restic ya cifra cada respaldo.

   ```text
   # /etc/fstab
   UUID=<uuid-del-disco>  /mnt/respaldo  ext4  defaults,nofail  0  2
   ```

6. **UPS:** conectarla por USB y configurar NUT (`sudo apt install nut`) para apagar el equipo en orden.
7. **IP fija:** reservar la IP del servidor en el DHCP del router.
8. **VPN** para entrar desde afuera y para el soporte: Tailscale en una cuenta de la farmacia, o WireGuard si
   el local tiene IP pública. El soporte de Gestifarma se agrega solo cuando la farmacia lo habilita.
9. **Firewall:** el router no reenvía ningún puerto al servidor. Docker publica los puertos 80 y 443 por
   fuera de `ufw`, así que se limitan con `GESTIFARMA_IP` (la IP del servidor en la red del local).

## 2. Dirección y certificado

La dirección (`GESTIFARMA_DOMINIO`) es un nombre del dominio de la farmacia, por ejemplo
`gestifarma.sufarmacia.com.ar`. El modo del certificado se elige con `GESTIFARMA_HTTPS`:

| Modo | Cuándo | Qué hace falta |
| --- | --- | --- |
| `red-local` | Servidor en la farmacia (recomendado) | DNS del dominio en Cloudflare y un token con permiso Zone > DNS > Edit, solo sobre ese dominio |
| `publico` | Servidor en la nube con IP pública | Registro DNS a la IP pública y puertos 80 y 443 abiertos |
| `interno` | Pruebas | Nada; los navegadores muestran una advertencia |

En el modo `red-local`:

- Crear en Cloudflare un registro `A` del nombre elegido a la IP del servidor en la red del local (por
  ejemplo `192.168.0.50`), **sin proxy** (nube gris). El certificado se valida por DNS: el servidor no
  recibe conexiones de internet.
- Cargar el mismo nombre en el DNS local del router, así la dirección funciona aunque se corte internet. Si
  el router bloquea respuestas DNS con IP privadas (protección contra DNS rebinding), agregar la excepción
  para ese nombre.

## 3. Instalar

```bash
git clone <repositorio> /opt/gestifarma          # o copiar la carpeta del proyecto
cd /opt/gestifarma/gestifarma/instalacion
./gestifarma.sh instalar                          # crea .env con claves nuevas
nano .env                                         # dominio, modo, token de Cloudflare, RESPALDO_DISCO=/mnt/respaldo
./gestifarma.sh instalar                          # construye, arranca y hace el primer respaldo
```

Al terminar muestra la dirección, el usuario, la clave y la **clave de recuperación de los respaldos**:
imprimirla y entregarla a la farmacia en un sobre cerrado. Sin ella los respaldos no se pueden restaurar.

Después, ajustar `config/reglas.toml` y los formatos de `config/fuentes/` con los datos del relevamiento y
correr `./gestifarma.sh reiniciar`.

Con una imagen publicada por Gestifarma (`GESTIFARMA_IMAGEN=ghcr.io/organizacion/gestifarma`), cargar
también `GESTIFARMA_VERSION` con la versión a instalar; el servidor necesita permiso de lectura sobre ese
registro (`docker login`).

## 4. Respaldos

- **Qué:** la base completa (`pg_dump`) y todas las fotos.
- **Cuándo:** todas las noches (`RESPALDO_HORARIO`, por defecto 23:30) y antes de cada actualización.
- **Dónde:** en el disco externo (`RESPALDO_DISCO`) y, si está configurado `RESPALDO_REMOTO`, en una copia
  fuera del local. Si el disco externo no está montado, el respaldo falla y avisa en vez de escribir en el
  disco interno.
- **Cuánto tiempo:** una copia por día de la última semana, una por semana del último mes y una por mes del
  último año. Los domingos se libera espacio y se verifica el repositorio.
- **Aviso:** `./gestifarma.sh estado` muestra el último resultado y advierte si tiene más de 26 horas. Con
  `MONITOR_URL` el servidor avisa a un monitor si salió bien (la URL) o mal (la URL + `/fail`), sin datos de
  recetas ni de pacientes.

Copia fuera del local, siempre a nombre de la farmacia:

- **Otra sucursal o la casa del dueño:** un [rest-server de restic](https://github.com/restic/rest-server)
  detrás de la VPN, `RESPALDO_REMOTO=rest:https://usuario:clave@respaldos.ejemplo:8000/gestifarma`.
- **Nube de la farmacia (S3):** un bucket privado con versionado, y un usuario de IAM con permiso solo sobre
  ese bucket. `RESPALDO_REMOTO=s3:s3.sa-east-1.amazonaws.com/<bucket>/gestifarma`, con
  `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`. Los datos van cifrados con la clave de la farmacia; igual,
  si el bucket está fuera del país, validarlo con el asesor legal.

Restaurar:

```bash
./gestifarma.sh respaldos                 # lista los respaldos del disco
./gestifarma.sh restaurar                 # el último del disco (pide escribir RESTAURAR)
./gestifarma.sh restaurar 1a2b3c4d remoto # uno en particular, desde la copia fuera del local
```

Si se rompe el servidor: preparar un equipo nuevo (sección 1), copiar la carpeta, crear `.env` con la
**misma** `RESTIC_PASSWORD` y el mismo `RESPALDO_DISCO` o `RESPALDO_REMOTO`, correr `./gestifarma.sh instalar` y
después `./gestifarma.sh restaurar`.

La restauración de prueba del plan de soporte se hace en un equipo de prueba, nunca sobre el servidor de la
farmacia.

## 5. Actualizar

```bash
./gestifarma.sh actualizar 1.2.0          # con imagen publicada
git pull && ./gestifarma.sh actualizar    # construyendo desde el repositorio (la versión es el commit)
```

El comando:

1. hace un respaldo (si falla, no actualiza);
2. prepara la versión nueva (si no la puede bajar o construir, no cambia nada);
3. la instala y espera a que responda;
4. si no responde, detiene la app, devuelve la base al respaldo previo, vuelve a la versión anterior y avisa.

Cada cambio queda en `estado/versiones.log`. La imagen anterior queda en el servidor, así que volver atrás
no necesita internet.

## 6. Soporte y monitoreo

- `./gestifarma.sh estado` y `./gestifarma.sh registros app` alcanzan para la mayoría de los diagnósticos.
- El acceso remoto es por la VPN, con un usuario de soporte que la farmacia habilita y deshabilita. Anotar en
  el registro del cliente quién entró, cuándo y qué se hizo, y mandárselo a la farmacia.
- Nunca sacar datos de recetas ni de pacientes del servidor para dar soporte.

## 7. Nube propia de la farmacia (AWS)

Mismo kit, en una cuenta de AWS a nombre de la farmacia (la región completa más cercana es San Pablo; los
datos quedan fuera del país, así que antes lo valida el asesor legal):

| Recurso | Configuración |
| --- | --- |
| EC2 | Ubuntu Server 24.04, `t3.medium` (2 vCPU, 4 GB), perfil de instancia con `AmazonSSMManagedInstanceCore` |
| EBS | Disco de sistema gp3 de 100 GB cifrado; un segundo volumen cifrado montado en `/mnt/respaldo` |
| Red | IP elástica; grupo de seguridad con 80 y 443 abiertos y sin SSH |
| Acceso de soporte | Systems Manager Session Manager, con un rol para Gestifarma que la farmacia puede borrar |
| S3 | Bucket privado con versionado para `RESPALDO_REMOTO` |
| AWS Backup | Plan diario de copias de los volúmenes |
| CloudWatch | Alarmas de estado de la instancia y de disco, por correo |

En `.env`: `GESTIFARMA_HTTPS=publico` y el dominio apuntando a la IP elástica.

## 8. Lista de control de entrega

- [ ] La dirección abre con candado desde un celular conectado al Wi-Fi del local.
- [ ] Sigue andando con internet cortado (DNS local del router).
- [ ] Se entra desde afuera por la VPN.
- [ ] Usuario y clave entregados al responsable de la farmacia.
- [ ] `./gestifarma.sh estado` muestra el último respaldo OK en el disco local y en la copia externa.
- [ ] Restauración de prueba hecha en otro equipo.
- [ ] Clave de recuperación impresa y entregada en un sobre cerrado, junto con la frase de recuperación del disco.
- [ ] La UPS apaga el equipo en orden y el servidor arranca solo al volver la luz.
- [ ] Parches de seguridad automáticos activos.
- [ ] Reglas y formatos de la farmacia cargados en `config/`.
- [ ] El monitor recibe los avisos (si se contrató).

## Qué está probado

- La app completa sobre PostgreSQL: `GESTIFARMA_TEST_DATABASE_URL=... pytest tests/test_postgres.py`.
- La lógica de `gestifarma.sh` (actualizar, vuelta atrás, respaldo previo fallido, claves nuevas):
  `pytest tests/test_instalacion.py`, con un Docker simulado.
- Respaldar y restaurar (disco local, copia externa y base previa) con restic 0.17 contra PostgreSQL 16.

Antes de la primera instalación real, correr el kit completo en un equipo de prueba: construir las imágenes,
sacar el certificado en el modo elegido, hacer un respaldo y restaurarlo.
