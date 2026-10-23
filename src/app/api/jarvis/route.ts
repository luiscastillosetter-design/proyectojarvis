import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const SUPABASE_URL = (process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || "").replace(/\/$/, "");
const SUPABASE_KEY = process.env.SUPABASE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
const MWAPI_KEY = process.env.MWAPI_KEY || process.env.ANTHROPIC_API_KEY || process.env.CLAUDE_API_KEY || "";
const MWAPI_BASE_URL = (process.env.MWAPI_BASE_URL || "https://api.mwapi.dev").replace(/\/$/, "");
const MWAPI_MODEL = process.env.MWAPI_MODEL || "claude-haiku-4-5-20251001";

function sbHeaders() {
  return {
    apikey: SUPABASE_KEY,
    Authorization: `Bearer ${SUPABASE_KEY}`,
    "Content-Type": "application/json",
    Prefer: "return=representation",
  };
}

export async function GET() {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return NextResponse.json({
      connected: false,
      error: "Faltan SUPABASE_URL o SUPABASE_KEY en .env",
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
      fetch(`${SUPABASE_URL}/rest/v1/jarvis_memoria?select=*&order=id.desc&limit=15`, {
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

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { action, payload } = body;

    // 1. Marcar o cambiar estado de tarea en Supabase en tiempo real
    if (action === "toggle_tarea" && SUPABASE_URL && SUPABASE_KEY) {
      const { id, nuevo_estado } = payload;
      await fetch(`${SUPABASE_URL}/rest/v1/jarvis_tareas?id=eq.${Number(id)}`, {
        method: "PATCH",
        headers: sbHeaders(),
        body: JSON.stringify({ estado: nuevo_estado }),
      });
      return NextResponse.json({ ok: true });
    }

    // 2. Registrar movimiento financiero rápido en Supabase
    if (action === "registrar_finanza" && SUPABASE_URL && SUPABASE_KEY) {
      const hoy = new Date().toISOString().split("T")[0];
      await fetch(`${SUPABASE_URL}/rest/v1/jarvis_finanzas`, {
        method: "POST",
        headers: sbHeaders(),
        body: JSON.stringify({
          tipo: payload.tipo || "cobro",
          monto: Number(payload.monto || 0),
          moneda: "USD",
          concepto: payload.concepto || "Movimiento desde HUD",
          cliente_o_proyecto: payload.cliente || "Agencia",
          metodo_pago: payload.metodo_pago || "Binance",
          fecha: hoy,
        }),
      });
      return NextResponse.json({ ok: true });
    }

    // 3. Crear tarea rápida en Supabase
    if (action === "crear_tarea" && SUPABASE_URL && SUPABASE_KEY) {
      const prio = Number(payload.prioridad || 1);
      const mapa: Record<number, string> = {
        1: "🔴 1 - CRÍTICA (Ya pagó / Entrega o Reunión Inminente)",
        2: "🟠 2 - ALTA (Clonación rápida / Proyecto en curso)",
        3: "🟡 3 - MEDIA (Demo para prospecto)",
        4: "🟢 4 - BAJA (Idea / Sin urgencia)",
      };
      await fetch(`${SUPABASE_URL}/rest/v1/jarvis_tareas`, {
        method: "POST",
        headers: sbHeaders(),
        body: JSON.stringify({
          titulo: payload.titulo,
          cliente_o_proyecto: payload.cliente || "General",
          prioridad: prio,
          etiqueta_prioridad: mapa[prio] || mapa[1],
          fecha_limite: payload.fecha_limite || "Cuando el jefe indique",
          descripcion: payload.descripcion || "",
          estado: "pendiente",
        }),
      });
      return NextResponse.json({ ok: true });
    }

    // 4. Guardar firma o nota en la Bóveda de Memoria de Supabase
    if (action === "guardar_memoria" && SUPABASE_URL && SUPABASE_KEY) {
      const hoy = new Date().toISOString().split("T")[0];
      await fetch(`${SUPABASE_URL}/rest/v1/jarvis_memoria`, {
        method: "POST",
        headers: sbHeaders(),
        body: JSON.stringify({
          categoria: payload.categoria || "acuerdo_cliente",
          cliente_o_tema: payload.tema || "Nota HUD",
          detalle_completo: payload.detalle || "",
          fecha: hoy,
        }),
      });
      return NextResponse.json({ ok: true });
    }

    // 5. Hablar en vivo con Jarvis (Claude Haiku 4.5 con contexto real de Supabase)
    if (action === "chat_jarvis") {
      const mensajeUsuario = String(payload?.mensaje || "").trim();
      const contextoActual = JSON.stringify(payload?.contextoResumen || {});

      if (!MWAPI_KEY) {
        return NextResponse.json({
          ok: true,
          reply:
            "Recibí tu orden en el HUD. (Nota: Verifica MWAPI_KEY en tu .env para respuestas generativas en vivo). Tus datos de Supabase siguen sincronizados en tiempo real.",
        });
      }

      const systemPrompt = `Eres JARVIS, Jefe de Gabinete y CFO de Luis Castillo en Telotengo Solutions.
Responde de forma ejecutiva, directa, sin tablas markdown, usando viñetas limpias.
Datos reales en vivo de Supabase en este instante: ${contextoActual}`;

      const resChat = await fetch(`${MWAPI_BASE_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${MWAPI_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: MWAPI_MODEL,
          max_tokens: 600,
          temperature: 0.2,
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: mensajeUsuario },
          ],
        }),
      });

      if (resChat.ok) {
        const data = await resChat.json();
        const texto = data?.choices?.[0]?.message?.content || "Orden procesada, jefe.";
        return NextResponse.json({ ok: true, reply: texto });
      } else {
        return NextResponse.json({
          ok: true,
          reply: `Orden registrada en el HUD. (Estado API: ${resChat.status}).`,
        });
      }
    }

    return NextResponse.json({ ok: false, error: "Acción no reconocida" }, { status: 400 });
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : "Error interno";
    return NextResponse.json({ ok: false, error: msg }, { status: 500 });
  }
}