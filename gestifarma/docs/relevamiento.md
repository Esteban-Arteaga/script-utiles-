# Relevamiento

Preguntas para la reunión con la farmacia. Las respuestas definen cómo nos conectamos a los sistemas, qué
reglas cargamos y cuánta plata está en juego.

## 1. Volumen y operación

- [ ] ¿Cuántas recetas de obra social se dispensan por mes? ¿Cuántas de cada una de las 5 obras sociales principales?
- [ ] ¿Qué porcentaje son manuscritas, impresas y electrónicas?
- [ ] ¿Cuántas personas hacen hoy el control y cuánto tiempo les lleva cada lote?
- [ ] ¿Cada cuánto se presenta cada obra social (quincenal, mensual)? ¿Cuándo es el cierre?
- [ ] ¿Las recetas se separan físicamente por obra social? ¿Dónde se guardan hasta presentarlas?

## 2. Sistemas

- [ ] ¿Qué sistema de gestión usa la farmacia (nombre y proveedor)? ¿Puede exportar las dispensas con el número de autorización? ¿En qué formato?
- [ ] ¿Contra qué validadores o gerenciadoras se valida online al dispensar?
- [ ] ¿Dónde se presenta cada obra social (colegio, gerenciadora, portal propio de la obra social)?
- [ ] Para cada sistema: ¿es una página web o un programa instalado? ¿Permite exportar lo cargado (Excel, CSV, PDF)? **Pedir un ejemplo real del reporte.**
- [ ] ¿Ofrece API o webservice? ¿Con quién hay que hablar para pedir acceso?
- [ ] ¿Cada persona tiene su usuario? ¿Hay captcha, doble factor o acceso restringido por IP o VPN?
- [ ] ¿Los términos de uso permiten el acceso automatizado?

## 3. Débitos (lo más importante para priorizar)

- [ ] Monto de débitos de los últimos 3 a 6 meses, total y por obra social.
- [ ] **El detalle de débitos con su motivo** (el informe que manda el colegio o la obra social). Con eso ordenamos qué controles importan más.
- [ ] ¿Se reclaman o refacturan? ¿Cuánto se recupera y cuánto tiempo lleva?

## 4. Reglas de cada obra social principal

- [ ] Vigencia de la receta (días desde la prescripción hasta la dispensa).
- [ ] Máximo de medicamentos por receta y de envases por medicamento; tratamientos prolongados.
- [ ] ¿Exige diagnóstico? ¿Firma y sello del médico? ¿Firma, aclaración y DNI de quien retira en el dorso?
- [ ] ¿Se siguen presentando troqueles? ¿Cómo se presentan las recetas electrónicas?
- [ ] Otros motivos de débito frecuentes: tachaduras, enmiendas sin salvar, medicamento no recetado por nombre genérico, etc.

## 5. Datos de muestra para el piloto

- [ ] 50 a 100 fotos de recetas reales (frente y dorso) de las obras sociales principales.
- [ ] El reporte de lo cargado en el sistema para esas mismas recetas.
- [ ] Una liquidación con débitos (para la etapa posterior a la liquidación).
- [ ] Cómo nos los pasan: son datos de salud, así que por una carpeta compartida con acceso restringido, no por WhatsApp ni por mail.

## 6. Infraestructura y equipamiento

- [ ] ¿La farmacia prefiere nube o servidor propio? ¿Tiene alguna política sobre dónde se guardan los datos?
- [ ] ¿Qué tan estable es la conexión a internet?
- [ ] ¿Quién se ocupa hoy de la parte técnica (un proveedor, alguien interno)?
- [ ] ¿Qué celulares se usarían para las fotos? ¿Hay escáner? (modelo, si tiene alimentador automático y doble faz)

## 7. Legal

- [ ] ¿La farmacia tiene registradas sus bases de datos ante la AAIP?
- [ ] ¿Quién firma la autorización para que procesemos los datos y, si se usa el robot, para el acceso automatizado a los portales?
