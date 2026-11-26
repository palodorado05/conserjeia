// Conserje IA — interfaz web (sin dependencias externas)
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (ruta, opciones = {}) => {
  const r = await fetch(ruta, { headers: { "Content-Type": "application/json" }, ...opciones });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const post = (ruta, cuerpo) => api(ruta, { method: "POST", body: JSON.stringify(cuerpo || {}) });
const fmtFecha = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("es-ES", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const NOMBRE_AGENTE = { router: "Router", legal: "Agente legal", incidencias: "Agente de incidencias", redactor: "Redactor", verificador: "Verificador", orquestador: "Orquestador" };

// ---------------------------------------------------------------- estado
let ESTADO = null;
async function cargarEstado() {
  try { ESTADO = await api("/api/estado"); } catch { return; }
  $("#comunidad").textContent = ESTADO.comunidad;
  const l = ESTADO.llm;
  const llmOk = l.ollama && l.modelo_ok;
  const pl = [["outlook", "Outlook"], ["google", "Calendar"], ["notion", "Notion"]];
  $("#estado").innerHTML =
    `<span class="pastilla" title="Modelo local servido por Ollama"><span class="punto ${llmOk ? "" : l.ollama ? "medio" : "mal"}"></span>${esc(l.modelo)}${llmOk ? "" : l.ollama ? " (falta el modelo)" : " · sin Ollama: modo degradado"}</span>` +
    `<span class="pastilla" title="RAG sobre la LPH"><span class="punto ${ESTADO.rag.modo === "sin corpus" ? "mal" : ESTADO.rag.modo === "lexico" ? "medio" : ""}"></span>RAG ${esc(ESTADO.rag.modo)}</span>` +
    (ESTADO.modo_plataformas === "mcp"
      ? `<span class="pastilla" title="Outlook, Google Calendar y Notion reales, vía servidores MCP"><span class="punto"></span>MCP: cuentas reales</span>`
      : `<span class="pastilla" title="Sin cuentas: Outlook, Calendar y Notion simulados dentro de la app (data/mock). Las cuentas reales se enseñan en la demo y en las trazas."><span class="punto medio"></span>MCP: modo prueba (simulado)</span>`) +
    pl.map(([k, n]) => {
      const caida = ESTADO.caidas.includes(k);
      return `<button class="pastilla" data-plat="${k}" title="Clic para ${caida ? "restaurar" : "simular una caída de"} ${n}"><span class="punto ${caida ? "mal" : ""}"></span>${n}${caida ? " caída" : ""}</button>`;
    }).join("");
  $("#pie-modelo").textContent = `Modelo ${l.modelo} en local (Ollama) · razonamiento: ` +
    Object.entries(ESTADO.esfuerzo).map(([k, v]) => `${k} ${v ? "sí" : "no"}`).join(", ");
  $("#reiniciar").hidden = ESTADO.modo_plataformas !== "mock";
}
$("#estado").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-plat]");
  if (!b) return;
  await post("/api/caida", { plataforma: b.dataset.plat, caida: !ESTADO.caidas.includes(b.dataset.plat) });
  cargarEstado();
});

// ---------------------------------------------------------------- trabajos (polling)
function describirPaso(p) {
  if (p.tipo === "llm") return `${NOMBRE_AGENTE[p.agente] || p.agente} ${p.think ? "razonando" : "pensando"} · ${p.tokens_in}→${p.tokens_out} tokens · ${(p.ms / 1000).toFixed(1)} s`;
  if (p.tipo === "herramienta") return `${p.herramienta} (${p.permiso}) · ${p.estado}${p.error ? " — " + p.error : ""}`;
  if (p.tipo === "barandilla") return `Barandilla: riesgo ${p.riesgo}${p.bloquear ? " · BLOQUEADO" : ""}`;
  if (p.tipo === "verificacion") return `Verificador: ${p.ok ? "aprobado" : "rechazado → plantilla segura"}`;
  if (p.tipo === "escalado") return `Escalado a humano: ${p.motivo}`;
  return p.tipo;
}
async function esperar(tid, alPaso) {
  for (;;) {
    const t = await api(`/api/trabajo/${tid}`);
    alPaso && alPaso(t.pasos);
    if (t.estado !== "en_curso") return t;
    await new Promise((r) => setTimeout(r, 900));
  }
}

// ---------------------------------------------------------------- chat
const CONV = "web-" + Math.random().toString(36).slice(2, 8);
function añadir(html, clase) {
  const d = document.createElement("div");
  d.className = "msg " + clase;
  d.innerHTML = html;
  $("#mensajes").appendChild(d);
  $("#mensajes").scrollTop = $("#mensajes").scrollHeight;
  return d;
}
function conCitas(texto) {
  return esc(texto).replace(/\[([^\]]+?LPH)\]/g, '<span class="cita">$1</span>');
}
function pintarRespuesta(r) {
  const acc = (r.acciones || []).map((a) => `<span class="chip ${esc(a.tipo)}">${esc(a.texto)}</span>`).join("");
  const frags = (r.fragmentos || []).length
    ? `<details><summary>Fragmentos de la LPH consultados (${r.fragmentos.length})</summary>${r.fragmentos.map((f) => `<div class="frag"><b>${esc(f.cita)}</b> · sim. ${f.score}<br>${esc(f.texto)}…</div>`).join("")}</details>`
    : "";
  const t = r.traza || {};
  const ver = r.verificacion ? ` · verificador: ${r.verificacion.ok ? "ok" : "rechazó el borrador"}` : "";
  return `<div class="cuerpo">${conCitas(r.respuesta)}</div>
    ${acc ? `<div class="acciones">${acc}</div>` : ""}
    ${frags}
    <div class="meta">Intención: ${esc(r.intencion)} · ${t.llamadas_llm ?? 0} llamadas al modelo · ${t.tokens_in ?? 0} tokens entrada / ${t.tokens_out ?? 0} salida · ${((t.duracion_ms ?? 0) / 1000).toFixed(1)} s${ver} · sesión ${esc(t.sesion)}</div>`;
}
async function enviar(texto) {
  if (!texto.trim()) return;
  añadir(`<p>${esc(texto)}</p>`, "vecino");
  $("#texto").value = "";
  $("#enviar").disabled = true;
  const burbuja = añadir(`<span class="girando"></span>Pensando…<ul class="pasos-vivo"></ul>`, "bot");
  try {
    const { trabajo } = await post("/api/chat", {
      mensaje: texto, conversacion: CONV,
      nombre: `${$("#nombre").value} (${$("#vivienda").value})`, vivienda: $("#vivienda").value, email: $("#email").value,
    });
    const t = await esperar(trabajo, (pasos) => {
      burbuja.querySelector(".pasos-vivo").innerHTML = pasos.map((p) => `<li>${esc(describirPaso(p))}</li>`).join("");
      $("#mensajes").scrollTop = $("#mensajes").scrollHeight;
    });
    burbuja.innerHTML = t.estado === "hecho" ? pintarRespuesta(t.resultado) : `<p>Error: ${esc(t.resultado?.error)}</p>`;
  } catch (e) {
    burbuja.innerHTML = `<p>No he podido conectar con el servidor: ${esc(e.message)}</p>`;
  }
  $("#enviar").disabled = false;
  $("#mensajes").scrollTop = $("#mensajes").scrollHeight;
  if (VISTA !== "bandeja") mostrar(VISTA);
}
$("#form").addEventListener("submit", (e) => { e.preventDefault(); enviar($("#texto").value); });
$("#texto").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#form").requestSubmit(); } });
$("#sugerencias").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON" && !$("#enviar").disabled) enviar(e.target.textContent); });

// ---------------------------------------------------------------- vistas del panel
let VISTA = "bandeja";
const VISTAS = {
  async bandeja() {
    const [correos, enviados] = await Promise.all([api("/api/bandeja"), api("/api/enviados")]);
    const pend = correos.filter((c) => !c.procesado).length;
    return `<div class="barra"><h2>Bandeja de Outlook <span class="nota">· ${pend} sin procesar</span></h2>
      <span><button class="btn sec" id="marcar" ${pend ? "" : "disabled"} title="Marca los correos actuales como vistos sin contestarlos">Marcar todo como visto</button>
      <button class="btn" id="procesar" ${pend ? "" : "disabled"}>Procesar bandeja con los agentes</button></span></div>
      <div id="progreso"></div>
      ${correos.map((c) => `<div class="correo"><div class="cab"><span><span class="asunto">${esc(c.asunto)}</span> · ${esc(c.nombre)}</span>
        <span>${c.procesado ? '<span class="etiqueta ok">procesado</span>' : '<span class="etiqueta Abierta">nuevo</span>'}</span></div>
        <div class="txt">${esc(c.cuerpo)}</div></div>`).join("")}
      ${enviados.length ? `<h2 style="font-size:15px;margin:20px 0 8px">Enviados por el conserje (${enviados.length})</h2>` +
        enviados.map((e) => `<div class="correo"><div class="cab"><span class="asunto">${esc(e.asunto)}</span><span class="nota">para ${esc(e.para)}</span></div><div class="resp">${conCitas(e.cuerpo)}</div></div>`).join("") : ""}`;
  },
  async incidencias() {
    const l = await api("/api/incidencias");
    return `<div class="barra"><h2>Incidencias (Notion)</h2><span class="nota">${l.length} registradas</span></div>
      <div class="tabla"><table><thead><tr><th>ID</th><th>Título</th><th>Categoría</th><th>Prioridad</th><th>Vivienda</th><th>Estado</th><th>Fecha</th></tr></thead><tbody>
      ${l.map((i) => `<tr><td>${esc(i.id)}</td><td>${esc(i.titulo)}<div class="nota">${esc(i.descripcion)}</div></td><td>${esc(i.categoria)}</td>
        <td><span class="etiqueta ${esc(i.prioridad)}">${esc(i.prioridad)}</span></td><td>${esc(i.vivienda)}</td>
        <td><span class="etiqueta ${esc(String(i.estado).split(" ")[0])}">${esc(i.estado)}</span></td><td>${esc(i.fecha)}</td></tr>`).join("")}
      </tbody></table></div>`;
  },
  async agenda() {
    const l = await api("/api/agenda");
    return `<div class="barra"><h2>Visitas de técnicos (Google Calendar)</h2><span class="nota">próximos 30 días</span></div>
      ${l.length ? `<div class="tabla"><table><thead><tr><th>Cuándo</th><th>Visita</th><th>Detalle</th></tr></thead><tbody>
      ${l.map((e) => `<tr><td>${esc(fmtFecha(e.inicio))}</td><td>${esc(e.titulo)}</td><td class="nota">${esc(e.descripcion)}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="vacio">No hay visitas programadas.</div>`}`;
  },
  async traza() {
    const l = await api("/api/trazas?n=20");
    if (!l.length) return `<div class="vacio">Aún no hay sesiones. Escribe en el chat o procesa la bandeja.</div>`;
    return `<div class="barra"><h2>Trazas de sesión</h2><span class="nota">logs/trazas.jsonl · tokens medidos por Ollama</span></div>` +
      l.map((s, i) => `<details class="sesion" ${i === 0 ? "open" : ""}><summary><b>${esc(s.sesion)}</b><span>${esc(s.canal)}</span>
        <span>${s.llamadas_llm} LLM · ${s.herramientas} herramientas</span><span>${s.tokens_in} in / ${s.tokens_out} out</span>
        <span>${(s.duracion_ms / 1000).toFixed(1)} s</span>${s.fallos ? `<span class="etiqueta error">${s.fallos} fallos</span>` : ""}</summary>
        <div class="tabla"><table><thead><tr><th>#</th><th>Paso</th><th>Agente</th><th>Permiso</th><th>Estado</th><th class="num">Tokens in/out</th><th class="num">Ida + vuelta</th><th class="num">ms</th></tr></thead><tbody>
        ${s.pasos.map((p) => `<tr><td>${p.n}</td>
          <td>${p.tipo === "llm" ? `LLM · ${esc(p.tarea)}${p.think ? " (think)" : ""}` : p.tipo === "herramienta" ? `<b>${esc(p.herramienta)}</b> <span class="nota">${esc(p.plataforma)} · ${esc(p.modo)}</span>` : esc(p.tipo)}
            ${p.error ? `<div class="nota" style="color:var(--error)">${esc(p.error)}</div>` : ""}${p.motivos?.length ? `<div class="nota">${esc(p.motivos.join(", "))}</div>` : ""}${p.motivo ? `<div class="nota">${esc(p.motivo)}</div>` : ""}${p.problemas?.length ? `<div class="nota">${esc(p.problemas.join("; "))}</div>` : ""}</td>
          <td>${esc(NOMBRE_AGENTE[p.agente] || p.agente || "")}</td>
          <td>${p.permiso ? `<span class="etiqueta ${esc(p.permiso)}">${esc(p.permiso)}</span>` : ""}</td>
          <td>${p.estado ? `<span class="etiqueta ${esc(p.estado)}">${esc(p.estado)}</span>` : p.ok === false || p.bloquear ? '<span class="etiqueta error">no</span>' : p.ok || p.riesgo === 0 ? '<span class="etiqueta ok">ok</span>' : p.riesgo ? `riesgo ${p.riesgo}` : ""}</td>
          <td class="num">${p.tipo === "llm" ? `${p.tokens_in} / ${p.tokens_out}` : ""}</td>
          <td class="num">${p.tipo === "herramienta" ? `${p.tokens_ida ?? 0} + ${p.tokens_vuelta ?? 0}` : ""}</td>
          <td class="num">${p.ms ?? ""}</td></tr>`).join("")}
        </tbody></table></div></details>`).join("");
  },
  async analisis() {
    const a = await api("/api/analisis");
    const max = Math.max(1, ...Object.values(a.por_categoria));
    return `<div class="barra"><h2>Análisis de la comunidad</h2><span class="nota">datos de Notion + trazas</span></div>
      <div class="kpis">
        <div class="kpi"><div class="v">${a.incidencias_90d}</div><div class="l">incidencias en 90 días</div></div>
        <div class="kpi"><div class="v">${a.abiertas}</div><div class="l">abiertas ahora</div></div>
        <div class="kpi"><div class="v">${a.sesiones}</div><div class="l">sesiones atendidas</div></div>
        <div class="kpi"><div class="v">${a.tokens_medios_in} / ${a.tokens_medios_out}</div><div class="l">tokens medios in / out por sesión</div></div>
        <div class="kpi"><div class="v">${a.segundos_medios} s</div><div class="l">tiempo medio por sesión</div></div>
        <div class="kpi"><div class="v">${a.escalados}</div><div class="l">casos escalados a humano</div></div>
      </div>
      <h2 style="font-size:15px">Avisos por categoría (90 días)</h2>
      <div class="barras">${Object.entries(a.por_categoria).map(([k, v]) => `<span>${esc(k)}</span><div class="b" style="width:${(v / max) * 100}%"></div><span>${v}</span>`).join("")}</div>
      <h2 style="font-size:15px">Decisión que cambia</h2><p class="nota">Regla: ${esc(a.regla)}</p>
      ${a.recomendaciones.map((r) => `<div class="reco">${esc(r)}</div>`).join("")}`;
  },
  async escalados() {
    const l = await api("/api/escalados");
    if (!l.length) return `<div class="vacio">Nada escalado todavía.</div>`;
    return `<div class="barra"><h2>Casos escalados a humano</h2><span class="nota">logs/escalados.jsonl + correo al administrador</span></div>
      <div class="tabla"><table><thead><tr><th>Cuándo</th><th>Motivo</th><th>Remitente</th><th>Extracto</th></tr></thead><tbody>
      ${l.map((e) => `<tr><td>${esc(fmtFecha(e.ts))}</td><td>${esc(e.motivo)}</td><td>${esc(e.remitente)} ${esc(e.vivienda)}</td><td class="nota">${esc(e.extracto)}</td></tr>`).join("")}
      </tbody></table></div>`;
  },
};
async function mostrar(v) {
  VISTA = v;
  document.querySelectorAll("#pestanas button").forEach((b) => b.classList.toggle("activa", b.dataset.v === v));
  try { $("#vista").innerHTML = await VISTAS[v](); } catch (e) { $("#vista").innerHTML = `<div class="vacio">No se pudo cargar: ${esc(e.message)}</div>`; }
}
$("#pestanas").addEventListener("click", (e) => { if (e.target.dataset.v) mostrar(e.target.dataset.v); });

// procesar bandeja
$("#vista").addEventListener("click", async (e) => {
  if (e.target.id === "marcar") {
    if (!confirm("¿Marcar todos los correos actuales como vistos? No se contestarán.")) return;
    await post("/api/bandeja/marcar_vistos");
    return mostrar("bandeja");
  }
  if (e.target.id !== "procesar") return;
  e.target.disabled = true;
  const prog = $("#progreso");
  prog.innerHTML = `<div class="correo"><span class="girando"></span>Los agentes están procesando la bandeja…<ul class="pasos-vivo"></ul></div>`;
  const { trabajo } = await post("/api/bandeja/procesar");
  const t = await esperar(trabajo, (pasos) => {
    const ul = prog.querySelector(".pasos-vivo");
    if (ul) ul.innerHTML = pasos.slice(-6).map((p) => `<li>${esc(describirPaso(p))}</li>`).join("");
  });
  const res = Array.isArray(t.resultado) ? t.resultado : [t.resultado];
  await mostrar("bandeja");
  $("#progreso").innerHTML = `<div class="correo"><b>Resultado</b>${res.map((r) => r.error ? `<p>${esc(r.error)}</p>` :
    `<div style="margin-top:8px"><b>${esc(r.correo.asunto)}</b> → ${esc(r.intencion)} <div class="acciones">${(r.acciones || []).map((a) => `<span class="chip ${esc(a.tipo)}">${esc(a.texto)}</span>`).join("")}</div>
     <div class="nota">${r.traza.tokens_in} / ${r.traza.tokens_out} tokens · ${(r.traza.duracion_ms / 1000).toFixed(1)} s · ${esc(r.traza.sesion)}</div></div>`).join("")}</div>`;
});

$("#reiniciar").addEventListener("click", async () => {
  if (!confirm("¿Restaurar la bandeja, incidencias y agenda de ejemplo?")) return;
  await post("/api/reiniciar");
  mostrar(VISTA);
});

cargarEstado();
mostrar("bandeja");
setInterval(cargarEstado, 15000);
