# Lo que tenéis que hacer a mano (y en qué orden)

## 1. Hoy (30-45 min)
1. Instalar Ollama: https://ollama.com/download
2. `ollama pull qwen3:8b` y `ollama pull nomic-embed-text`
3. **Descargar la Ley de Propiedad Horizontal** en PDF desde el BOE (texto consolidado de la
   Ley 49/1960, BOE-A-1960-10906): https://www.boe.es/buscar/act.php?id=BOE-A-1960-10906
   → botón "PDF" → guardarlo como `data/corpus/lph.pdf`.
4. Seguir el "Arranque" del README y procesar la bandeja de ejemplo.
5. `python -m eval.evaluar_rag` y `python -m negocio.modelo_financiero` → ya tenéis cifras MEDIDAS.
   No borréis `logs/usage.jsonl`: es vuestro "usage" del §2.

## 2. Plataformas reales con cuentas NUEVAS de prueba (nada personal)
Las tres son proveedores distintos (Google y Microsoft cuentan como plataformas diferentes; Gmail y
Calendar serían la misma).

| Plataforma | Cuenta nueva | Uso en la app |
|---|---|---|
| Microsoft | `conserje.demo@outlook.com` (o similar) | Bandeja de los vecinos: leer y responder |
| Google | `conserje.demo@gmail.com` | Calendar: visitas de técnicos |
| Notion | Registro con uno de los correos anteriores | Base de datos "Incidencias" |

6. **Microsoft:** registrar una app en https://entra.microsoft.com (cuentas personales) y seguir el README
   del servidor MCP elegido (p. ej. `@softeria/ms-365-mcp-server`).
7. **Google:** proyecto gratis en https://console.cloud.google.com → activar Calendar API → credenciales
   OAuth "Desktop app" → añadir la cuenta como usuario de prueba → servidor MCP (p. ej. `workspace-mcp`).
8. **Notion:** https://www.notion.so/my-integrations → nueva integración → token en la variable de entorno
   `NOTION_TOKEN` (nunca en el repo). Crear la base de datos "Incidencias" y compartirla con la integración.
9. `python -m app.tools.mcp_backend --listar` → copiar los nombres reales de herramientas en `config.yaml`
   y completar los `TODO` de `app/tools/mcp_backend.py`. Cambiar `modo_plataformas: mcp`.
10. Demo: escribid como "vecinos" desde vuestros correos al Outlook de prueba.
11. Guardad la traza de una sesión real (`logs/trazas.jsonl`) para la memoria, incluyendo un fallo
    (p. ej. apagad la conexión a Notion y mirad cómo el sistema escala el mensaje).

## 3. Para la defensa
12. Cada miembro debe saber explicar cada fichero de `app/`. Orden recomendado:
    `orquestador.py` → `guardrails.py` → `agents/` → `rag/indice.py` → `llm.py`.
13. Confirmad con el profesor que la app puede arrancar en su portátil en modo mock y que las llamadas
    reales se enseñan en la demo y en la traza.
