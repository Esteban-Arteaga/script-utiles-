# Controles de la conciliación

Qué compara Gestifarma entre la receta y lo cargado, y qué hace cuando no coincide. Los umbrales y las
exigencias por obra social están en [`config/reglas.toml`](../config/reglas.toml).

## Cómo encuentra la carga de cada receta

1. Por **número de autorización** (ignora ceros adelante, guiones y espacios).
2. Si no, por **número de receta**.
3. Si la receta no tiene números: **mismo afiliado** y además misma fecha de prescripción, dispensa
   cercana (hasta 3 días) o el mismo medicamento.

## Resultados

| Resultado | Significa |
|---|---|
| **OK** | Coincide todo. |
| **Revisar** | Solo advertencias: algo para mirar (lectura dudosa, nombre parecido, plan distinto, no se ve el dorso). |
| **Con diferencias** | Al menos un error: corregir antes de presentar. |
| **Sin carga en el sistema** | La receta no está cargada: si se dispensó, no se va a cobrar. |
| **Carga sin receta** | Está cargada pero no hay receta escaneada: si la receta física falta, es un débito seguro. |

## Controles

| Control | Cómo compara | Si no coincide | Configurable |
|---|---|---|---|
| Obra social | Nombre normalizado, con alias (PAMI = INSSJP) | Error | `alias_obras_sociales`, `umbral_obra_social` |
| Plan | Texto normalizado | Revisar (puede cambiar la cobertura) | — |
| Número de afiliado | Ignora ceros adelante, guiones y espacios | Error. Si solo cambia el sufijo después de "/" (parentesco): Revisar | — |
| Nombre del afiliado | Tolera orden distinto, segundos nombres, iniciales y errores de tipeo | Parecido: Revisar. Distinto: Error | `umbral_nombre_ok`, `umbral_nombre_dudoso` |
| Matrícula del médico | Solo el número (ignora MN / MP) | Error | — |
| Fecha de prescripción | Receta contra carga | Error | — |
| Fecha de dispensa | Ticket de la receta contra carga | Revisar | — |
| Vigencia | Días entre prescripción y dispensa | Error si se pasa del máximo o si la dispensa es anterior | `dias_validez_receta` |
| Medicamentos | Cada producto cargado contra lo recetado: por troquel o código de barras, o por nombre de la droga (usa la monodroga del reporte si viene) | Cargado y no recetado: Error. Parecido pero no seguro (por ejemplo, una combinación de drogas): Revisar. Recetado y no cargado: Info | `umbral_producto`, `umbral_producto_minimo` |
| Concentración | "10 mg" contra "20 mg" en los productos emparejados | Error | — |
| Troquel y código de barras | Si figuran en la receta y en la carga | Error | — |
| Cantidad | Envases cargados contra recetados | Más que lo recetado: Error. La receta no dice cantidad y se cargó más de 1: Revisar | — |
| Importes | Ticket de la receta contra carga | Error si la diferencia supera la tolerancia | `tolerancia_importe` |
| Firma y sello del médico, firma del afiliado | Lo que se ve en las imágenes | Falta: Error. No se ve (por ejemplo, no hay foto del dorso): Revisar | `exigir_firma_medico`, `exigir_sello_medico`, `exigir_firma_afiliado` |
| Diagnóstico | Si la obra social lo exige | Error | `exigir_diagnostico` |
| Cantidad de medicamentos | Recetados contra el máximo | Error | `max_items_por_receta` |

**Lecturas dudosas:** si la IA marcó un dato como dudoso y ese dato da una diferencia, el mensaje lo
aclara para que se confirme mirando la imagen. Cuando el backoffice guarda la revisión, la receta se
vuelve a conciliar.

## Límites conocidos

- Sin una base de medicamentos (Alfabeta, Kairos u otra) no se puede asegurar que un nombre comercial
  corresponda a la droga recetada. Hoy se usa la columna de monodroga del reporte, el troquel o el código
  de barras; sumar una base de medicamentos está en la etapa 2 de la [hoja de ruta](propuesta.md#10-hoja-de-ruta).
- Los valores de `config/reglas.toml` son un punto de partida y hay que confirmarlos con cada convenio.
