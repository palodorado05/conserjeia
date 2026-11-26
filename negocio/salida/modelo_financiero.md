# Modelo financiero — Conserje IA

Generado por `python -m negocio.modelo_financiero`. Etiquetas: **MEDIDO** (sale de los logs de la app), **ESTIMACIÓN** (supuesto de `negocio/supuestos.yaml`), **CALCULADO** (combina los anteriores).

| Concepto | Valor | Tipo | Nota |
|---|---|---|---|
| Sesiones medidas | 12 | MEDIDO | logs/usage.jsonl, canales chat y correo |
| Tokens de entrada por sesión (media / mediana) | 1627 / 1435 | MEDIDO | prompt_eval_count de Ollama |
| Tokens de salida por sesión (media / mediana) | 653 / 564 | MEDIDO | eval_count de Ollama, incluye razonamiento (think) |
| Llamadas al modelo por sesión | 3.7 | MEDIDO |  |
| Fracción cacheada | 0 % | MEDIDO | Ollama no factura caché; se asume 0 (conservador). Reutiliza KV del prefijo, pero no lo reporta |
| Segundos de modelo por sesión (máquina de medida) | 169.4 s | MEDIDO |  |
| Sesiones por comunidad y mes | 45 | ESTIMACIÓN | 30 viviendas x 1.5 |
| Tokens por comunidad y mes | 102,622 | CALCULADO |  |
| GPU | NVIDIA L4 24 GB (nube, bajo demanda), 24 GB VRAM | ESTIMACIÓN | qwen3:8b cuantizado ocupa ~5-6 GB |
| Factura GPU al mes | 548 € | ESTIMACIÓN | 0.75 €/h x 730 h |
| Segundos de GPU por sesión | 21.2 s | ESTIMACIÓN | medido / 8 (aceleración supuesta) |
| Capacidad de una GPU | 248,273 sesiones/mes | CALCULADO | concurrencia 4, utilización 50% |
| Comunidades que caben en una GPU | 5,517 | CALCULADO |  |
| Coste de modelo por sesión (GPU llena) | 0.221 céntimos | CALCULADO |  |
| Coste de modelo por comunidad y mes (GPU llena) | 0.099 € | CALCULADO |  |
| Mismo consumo con Claude Haiku 5.5 por API | 0.020 €/comunidad/mes | CALCULADO | comparativa: precio público por token |
| Precio por comunidad y mes | 19 € | ESTIMACIÓN |  |
| Margen de contribución por comunidad | 18.90 € (99.5%) | CALCULADO | sin contar la GPU como fijo |
| Costes fijos al mes (sin GPU) | 600 € | ESTIMACIÓN |  |
| Punto de equilibrio | 61 comunidades | CALCULADO | (fijos + 1 GPU) / margen de contribución |
| Coste de construcción con Claude Code (Opus 5.5) | 20.76 € | MEDIDO | logs/coste_construccion.json |
| Inversión antes del primer euro de ingreso | 3,021 € | CALCULADO | construcción + legal/marca/piloto (estimación) |
| Mes con beneficio mensual positivo | 10 | CALCULADO |  |
| Mes en que se recupera la inversión (caja ≥ 0) | 20 | CALCULADO |  |
| Necesidad máxima de caja (lo que hay que poner) | 10,782 € | CALCULADO |  |
| Caja acumulada a 36 meses | 48,455 € | CALCULADO |  |
| ROI a 3 años sobre el capital necesario | 4.5x | CALCULADO | caja final / necesidad máxima de caja |
| Si la GPU sube un 50 %: punto de equilibrio | 76 comunidades | CALCULADO | factura GPU 821 €/mes |

Flujo mensual completo: `negocio/salida/flujo_36_meses.csv`.
