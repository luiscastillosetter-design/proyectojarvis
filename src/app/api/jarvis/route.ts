import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const SUPABASE_URL = (process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || "").replace(/\/$/, "");
const SUPABASE_KEY = process.env.SUPABASE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
const MWAPI_KEY = process.env.MWAPI_KEY || process.env.ANTHROPIC_API_KEY || process.env.CLAUDE_API_KEY || "";
const MWAPI_BASE_URL = (process.env.MWAPI_BASE_URL || "https://api.mwapi.dev").replace(/\/$/, "");
const MWAPI_MODEL = process.env.MWAPI_MODEL || "claude-haiku-4-5-20251001";

function sbHeaders(prefer = "return=representation") {
  return {
    apikey: SUPABASE_KEY,
    Authorization: `Bearer ${SUPABASE_KEY}`,
    "Content-Type": "application/json",
    Prefer: prefer,
  };
}

// =====================================================================
// DEFINICIÓN DE HERRAMIENTAS (TOOLS) PARA EL CHAT WEB Y ORBE
// =====================================================================
const WEB_TOOLS = [
  {
    type: "function",
    function: {
      name: "crear_tarea",
      description: "Crea una nueva tarea o pendiente en la agenda de Supabase.",
      parameters: {
        type: "object",
        properties: {
          titulo: { type: "string", description: "Título claro de la tarea" },
          cliente: { type: "string", description: "Cliente o proyecto vinculado (o 'General')" },
          prioridad: { type: "number", description: "1 (Crítica), 2 (Alta), 3 (Media), 4 (Baja)" },
          fecha_limite: { type: "string", description: "Fecha límite o 'Cuando el jefe indique'" },
          descripcion: { type: "string", description: "Detalles adicionales" }
        },
        required: ["titulo"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "registrar_finanza",
      description: "Registra un movimiento contable real (cobro, gasto, inversion) en Supabase.",
      parameters: {
        type: "object",
        properties: {
          tipo: { type: "string", enum: ["cobro", "gasto", "inversion"] },
          monto: { type: "number", description: "Monto numérico en USD" },
          concepto: { type: "string", description: "Concepto del pago o cobro" },
          cliente: { type: "string", description: "Cliente o proyecto vinculado" },
          metodo_pago: { type: "string", description: "Cuenta o método: Binance, Zelle, Efectivo, Banesco, etc." }
        },
        required: ["tipo", "monto", "concepto"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "registrar_o_actualizar_proyecto",
      description: "Crea o actualiza un proyecto en Supabase con sus cotizaciones y estados.",
      parameters: {
        type: "object",
        properties: {
          nombre_proyecto: { type: "string" },
          cliente: { type: "string" },
          estado: { type: "string", enum: ["1_Pagado_En_Curso", "2_Reunion_Critica", "3_Clonar_Ganancia_Rapida", "4_Prospecto_Demo", "Completado"] },
          prioridad: { type: "number" },
          monto_acordado: { type: "number" },
          monto_cobrado: { type: "number" },
          fecha_entrega: { type: "string" },
          siguiente_paso: { type: "string" }
        },
        required: ["nombre_proyecto", "cliente"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "cambiar_estado_tarea",
      description: "Cambia el estado de una tarea existente a completada o pendiente.",
      parameters: {
        type: "object",
        properties: {
          id_tarea: { type: "number" },
          nuevo_estado: { type: "string", enum: ["completada", "pendiente"] }
        },
        required: ["id_tarea", "nuevo_estado"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "guardar_memoria",
      description: "Guarda acuerdos, notas o apuntes clave en la Bóveda de Memoria.",
      parameters: {
        type: "object",
        properties: {
          tema: { type: "string", description: "Tema o cliente" },
          detalle: { type: "string", description: "Información a recordar" },
          categoria: { type: "string", description: "Categoría de la memoria" }
        },
        required: ["tema", "detalle"]
      }
    }
  }
];

// =====================================================================
// EJECUTOR DIRECTO DE HERRAMIENTAS CONTRA SUPABASE
// =====================================================================
async function ejecutarToolEnSupabase(nombre: string, args: Record<string, any>) {
  const hoy = new Date().toISOString().split("T")[0];

  if (nombre === "crear_tarea") {
    const prio = Number(args.prioridad || 1);
    const mapaPrio: Record<number, string> = {
      1: "🔴 1 - CRÍTICA (Ya pagó / Entrega o Reunión Inminente)",
      2: "🟠 2 - ALTA (Clonación rápida / Proyecto en curso)",
      3: "🟡 3 - MEDIA (Demo para prospecto)",
      4: "🟢 4 - BAJA (Idea / Sin urgencia)"
    };
    const res = await fetch(`${SUPABASE_URL}/rest/v1/jarvis_tareas`, {
      method: "POST",
      headers: sbHeaders(),
      body: JSON.stringify({
        titulo: args.titulo,
        cliente_o_proyecto: args.cliente || "General",
        prioridad: prio,
        etiqueta_prioridad: mapaPrio[prio] || mapaPrio[1],
        fecha_limite: args.fecha_limite || "Cuando el jefe indique",
        descripcion: args.descripcion || "",
        estado: "pendiente"
      })
    });
    return res.ok ? `Tarea '${args.titulo}' registrada con éxito en Supabase.` : "Error insertando tarea.";
  }

  if (nombre === "registrar_finanza") {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/jarvis_finanzas`, {
      method: "POST",
      headers: sbHeaders(),
      body: JSON.stringify({
        tipo: (args.tipo || "cobro").toLowerCase(),
        monto: Number(args.monto || 0),
        moneda: "USD",
        concepto: args.concepto,
        cliente_o_proyecto: args.cliente || "Agencia",
        metodo_pago: args.metodo_pago || "Binance",
        fecha: hoy
      })
    });
    return res.ok ? `${args.tipo.toUpperCase()} de USD ${args.monto} (${args.concepto}) registrado en Supabase.` : "Error registrando finanza.";
  }

  if (nombre === "cambiar_estado_tarea") {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/jarvis_tareas?id=eq.${Number(args.id_tarea)}`, {
      method: "PATCH",
      headers: sbHeaders(),
      body: JSON.stringify({ estado: args.nuevo_estado })
    });
    return res.ok ? `Tarea #${args.id_tarea} actualizada a ${args.nuevo_estado}.` : "Error actualizando tarea.";
  }

  if (nombre === "registrar_o_actualizar_proyecto") {
    // Buscar si ya existe el proyecto para actualizarlo
    const buscarRes = await fetch(`${SUPABASE_URL}/rest/v1/jarvis_proyectos?nombre_proyecto=ilike.${encodeURIComponent(args.nombre_proyecto)}&limit=1`, {
      headers: sbHeaders("return=representation")
    });
    const encontrados = buscarRes.ok ? await buscarRes.json() : [];

    if (encontrados.length > 0) {
      const p = encontrados[0];
      const resUpdate = await fetch(`${SUPABASE_URL}/rest/v1/jarvis_proyectos?id=eq.${p.id}`, {
        method: "PATCH",
        headers: sbHeaders(),
        body: JSON.stringify({
          cliente: args.cliente || p.cliente,
          estado: args.estado || p.estado,
          prioridad: args.prioridad ? Number(args.prioridad) : p.prioridad,
          monto_acordado: args.monto_acordado ? Number(args.monto_acordado) : p.monto_acordado,
          monto_cobrado: args.monto_cobrado ? Number(args.monto_cobrado) : p.monto_cobrado,
          fecha_entrega: args.fecha_entrega || p.fecha_entrega,
          siguiente_paso: args.siguiente_paso || p.siguiente_paso
        })
      });
      return resUpdate.ok ? `Proyecto '${args.nombre_proyecto}' actualizado correctamente.` : "Error al actualizar proyecto.";
    }

    const resInsert = await fetch(`${SUPABASE_URL}/rest/v1/jarvis_proyectos`, {
      method: "POST",
      headers: sbHeaders(),
      body: JSON.stringify({
        nombre_proyecto: args.nombre_proyecto,
        cliente: args.cliente,
        estado: args.estado || "1_Pagado_En_Curso",
        prioridad: Number(args.prioridad || 1),
        monto_acordado: Number(args.monto_acordado || 0),
        monto_cobrado: Number(args.monto_cobrado || 0),
        fecha_entrega: args.fecha_entrega || "Cuando el jefe indique",
        siguiente_paso: args.siguiente_paso || ""
      })
    });
    return resInsert.ok ? `Proyecto '${args.nombre_proyecto}' creado en Supabase.` : "Error al crear proyecto.";
  }

  if (nombre === "guardar_memoria") {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/jarvis_memoria`, {
      method: "POST",
      headers: sbHeaders(),
      body: JSON.stringify({
        categoria: args.categoria || "acuerdo_cliente",
        cliente_o_tema: args.tema,
        detalle_completo: args.detalle,
        fecha: hoy
      })
    });
    return res.ok ? `Dato guardado en la Bóveda de Memoria.` : "Error guardando memoria.";
  }

  return "Herramienta no implementada.";
}

// =====================================================================
// ENDPOINT GET: LECTURA EN TIEMPO REAL PARA EL DASHBOARD
// =====================================================================
export async function GET() {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return NextResponse.json({
      connected: false,
      error: "Faltan SUPABASE_URL o SUPABASE_KEY en las variables de entorno",
      proyectos: [],
      tareas: [],
      finanzas: [],
      memoria: [],
      resumen: {
        cajaNeta: 0,
        totalCobros: 0,
        totalGastos: 0,
        totalInversiones: 0,
        plataEnLaCalle: 0,
        totalCotizado: 0,
        saldosPorCuenta: {},
      },
    });
  }

  try {
    const [resProyectos, resTareas, resFinanzas, resMemoria] = await Promise.all([
      fetch(`${SUPABASE_URL}/rest/v1/jarvis_proyectos?select=*&order=prioridad.asc,id.asc`, {
        headers: sbHeaders(),
        cache: "no-store",
      }),
      fetch(`${SUPABASE_URL}/rest/v1/jarvis_tareas?select=*&order=prioridad.asc,id.asc&limit=30`, {
        headers: sbHeaders(),
        cache: "no-store",
      }),
      fetch(`${SUPABASE_URL}/rest/v1/jarvis_finanzas?select=*&order=id.desc&limit=100`, {
        headers: sbHeaders(),
        cache: "no-store",
      }),
      fetch(`${SUPABASE_URL}/rest/v1/jarvis_memoria?select=*&order=id.desc&limit=20`, {
        headers: sbHeaders(),
        cache: "no-store",
      }),
    ]);

    const proyectos = resProyectos.ok ? await resProyectos.json() : [];
    const tareas = resTareas.ok ? await resTareas.json() : [];
    const finanzas = resFinanzas.ok ? await resFinanzas.json() : [];
    const memoria = resMemoria.ok ? await resMemoria.json() : [];

    let totalCobros = 0;
    let totalGastos = 0;
    let totalInversiones = 0;
    const saldosPorCuenta: Record<string, number> = {};

    for (const mov of finanzas) {
      const monto = Number(mov.monto || 0);
      const tipo = String(mov.tipo || "cobro").toLowerCase();
      const cuenta = String(mov.metodo_pago || "General").trim();

      if (tipo === "cobro") {
        totalCobros += monto;
        saldosPorCuenta[cuenta] = (saldosPorCuenta[cuenta] || 0) + monto;
      } else if (tipo === "inversion") {
        totalInversiones += monto;
        saldosPorCuenta[cuenta] = (saldosPorCuenta[cuenta] || 0) - monto;
      } else {
        totalGastos += monto;
        saldosPorCuenta[cuenta] = (saldosPorCuenta[cuenta] || 0) - monto;
      }
    }

    let totalCotizado = 0;
    let totalCobradoProyectos = 0;
    for (const p of proyectos) {
      totalCotizado += Number(p.monto_acordado || 0);
      totalCobradoProyectos += Number(p.monto_cobrado || 0);
    }

    const plataEnLaCalle = Math.max(0, totalCotizado - totalCobradoProyectos);
    const cajaNeta = totalCobros - (totalGastos + totalInversiones);

    return NextResponse.json({
      connected: true,
      proyectos,
      tareas,
      finanzas,
      memoria,
      resumen: {
        cajaNeta,
        totalCobros,
        totalGastos,
        totalInversiones,
        plataEnLaCalle,
        totalCotizado,
        saldosPorCuenta,
      },
    });
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : "Error desconocido";
    return NextResponse.json({
      connected: false,
      error: msg,
      proyectos: [],
      tareas: [],
      finanzas: [],
      memoria: [],
      resumen: {
        cajaNeta: 0,
        totalCobros: 0,
        totalGastos: 0,
        totalInversiones: 0,
        plataEnLaCalle: 0,
        totalCotizado: 0,
        saldosPorCuenta: {},
      },
    });
  }
}

// =====================================================================
// ENDPOINT POST: ACCIONES DIRECTAS + AGENTE CONVERSACIONAL CON TOOLS
// =====================================================================
export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { action, payload } = body;

    // 1. Guardar Firma Digital Táctil en Base64 para incrustar en PDFs
    if (action === "guardar_firma" && SUPABASE_URL && SUPABASE_KEY) {
      const hoy = new Date().toISOString().split("T")[0];
      await fetch(`${SUPABASE_URL}/rest/v1/jarvis_memoria`, {
        method: "POST",
        headers: sbHeaders(),
        body: JSON.stringify({
          categoria: "firma_digital",
          cliente_o_tema: payload?.cliente || "Cliente General",
          detalle_completo: payload?.dataUrl || "",
          fecha: hoy,
        }),
      });
      return NextResponse.json({ ok: true, mensaje: "Firma digital registrada para contratos." });
    }

    // 2. Marcar tarea completada/pendiente desde los botones del HUD
    if (action === "toggle_tarea" && SUPABASE_URL && SUPABASE_KEY) {
      const { id, nuevo_estado } = payload;
      await fetch(`${SUPABASE_URL}/rest/v1/jarvis_tareas?id=eq.${Number(id)}`, {
        method: "PATCH",
        headers: sbHeaders(),
        body: JSON.stringify({ estado: nuevo_estado }),
      });
      return NextResponse.json({ ok: true });
    }

    // 3. Crear tarea manual desde formularios del HUD
    if (action === "crear_tarea" && SUPABASE_URL && SUPABASE_KEY) {
      const res = await ejecutarToolEnSupabase("crear_tarea", payload);
      return NextResponse.json({ ok: true, mensaje: res });
    }

    // 4. Registrar movimiento contable desde formularios del HUD
    if (action === "registrar_finanza" && SUPABASE_URL && SUPABASE_KEY) {
      const res = await ejecutarToolEnSupabase("registrar_finanza", payload);
      return NextResponse.json({ ok: true, mensaje: res });
    }

    // 5. Guardar nota o memoria general
    if (action === "guardar_memoria" && SUPABASE_URL && SUPABASE_KEY) {
      const res = await ejecutarToolEnSupabase("guardar_memoria", payload);
      return NextResponse.json({ ok: true, mensaje: res });
    }

    // 6. CHAT JARVIS CON TOOL CALLING EN VIVO (Barra central y Orbe)
    if (action === "chat_jarvis") {
      const mensajeUsuario = String(payload?.mensaje || "").trim();
      const contextoActual = JSON.stringify(payload?.contextoResumen || {});

      if (!MWAPI_KEY) {
        return NextResponse.json({
          ok: true,
          reply: "MWAPI_KEY no configurada en las variables de entorno.",
        });
      }

      const systemPrompt = `Eres JARVIS, Asistente Ejecutivo, Jefe de Gabinete y CFO de Luis Castillo en Telotengo Solutions.
Tu misión es ejecutar y registrar las órdenes del jefe en la base de datos de Supabase usando tus herramientas.
Si el usuario te dice que anotó un cobro, que gastó, que recuerdes algo, que crees una tarea o un proyecto, USA TUS HERRAMIENTAS DIRECTAMENTE.
Tono: Formal, ejecutivo, breve, en español y sin tablas markdown.
Estado financiero y operativo actual en pantalla: ${contextoActual}`;

      const messagesPayload: any[] = [
        { role: "system", content: systemPrompt },
        { role: "user", content: mensajeUsuario }
      ];

      // Primera llamada a Claude con catálogo de herramientas activas
      const resChat = await fetch(`${MWAPI_BASE_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${MWAPI_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: MWAPI_MODEL,
          max_tokens: 800,
          temperature: 0.2,
          messages: messagesPayload,
          tools: WEB_TOOLS,
        }),
      });

      if (!resChat.ok) {
        return NextResponse.json({
          ok: true,
          reply: `No se pudo conectar con el cerebro de IA (Status: ${resChat.status}).`,
        });
      }

      const dataChat = await resChat.json();
      const choice = dataChat?.choices?.[0] || {};
      const assistantMessage = choice?.message || {};
      const toolCalls = assistantMessage?.tool_calls || [];

      // Si Claude decide ejecutar una o varias herramientas
      if (toolCalls.length > 0) {
        messagesPayload.push(assistantMessage);

        for (const tc of toolCalls) {
          const fnName = tc.function?.name;
          let parsedArgs = {};
          try {
            parsedArgs = JSON.parse(tc.function?.arguments || "{}");
          } catch {
            parsedArgs = {};
          }

          const resultadoTool = await ejecutarToolEnSupabase(fnName, parsedArgs);

          messagesPayload.push({
            role: "tool",
            tool_call_id: tc.id,
            content: String(resultadoTool),
          });
        }

        // Segunda llamada para que Claude emita la confirmación ejecutiva con los datos ya guardados
        const resFinal = await fetch(`${MWAPI_BASE_URL}/v1/chat/completions`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${MWAPI_KEY}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: MWAPI_MODEL,
            max_tokens: 500,
            temperature: 0.2,
            messages: messagesPayload,
          }),
        });

        if (resFinal.ok) {
          const dataFinal = await resFinal.json();
          const respuestaTexto = dataFinal?.choices?.[0]?.message?.content || "Órdenes ejecutadas en Supabase, señor.";
          return NextResponse.json({ ok: true, reply: respuestaTexto, ejecutado: true });
        }

        return NextResponse.json({ ok: true, reply: "Acción registrada en la base de datos, señor.", ejecutado: true });
      }

      // Respuesta conversacional directa si no requirió tools
      const textoDirecto = assistantMessage?.content || "Sistemas listos para sus órdenes, señor.";
      return NextResponse.json({ ok: true, reply: textoDirecto });
    }

    return NextResponse.json({ ok: false, error: "Acción no reconocida" }, { status: 400 });
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : "Error interno";
    return NextResponse.json({ ok: false, error: msg }, { status: 500 });
  }
}