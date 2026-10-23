"use client";
import React, { useState, useEffect, useCallback } from "react";
import { siteConfig } from "../config/site";
import ThinkingOrb from "../components/ThinkingOrb";
import SignaturePadModal from "../components/SignaturePadModal";
import {
  Mic,
  FileText,
  DollarSign,
  Instagram,
  Globe,
  HardDrive,
  Sparkles,
  Calendar,
  Mail,
  MessageSquare,
  ChevronRight,
  Server,
  Database,
  ShieldCheck,
  Smartphone,
  Send,
  Home,
  Layers,
  UserCheck,
  TrendingUp,
  Clock,
  CheckCircle2,
  RefreshCw,
  PlusCircle,
  Volume2,
} from "lucide-react";

interface ProyectoSB {
  id: number;
  nombre_proyecto: string;
  cliente: string;
  estado: string;
  prioridad: number;
  monto_acordado: number;
  monto_cobrado: number;
  fecha_entrega: string;
  siguiente_paso: string;
  notas?: string;
}

interface TareaSB {
  id: number;
  titulo: string;
  cliente_o_proyecto: string;
  prioridad: number;
  etiqueta_prioridad: string;
  fecha_limite: string;
  descripcion?: string;
  estado: string;
}

interface MemoriaSB {
  id: number;
  categoria: string;
  cliente_o_tema: string;
  detalle_completo: string;
  fecha: string;
}

interface ResumenSB {
  cajaNeta: number;
  totalCobros: number;
  totalGastos: number;
  totalInversiones: number;
  plataEnLaCalle: number;
  totalCotizado: number;
  saldosPorCuenta: Record<string, number>;
}

interface ChatMsg {
  id: string;
  sender: "jarvis" | "luis";
  time: string;
  text: string;
}

export default function JarvisCyberpunkHUD() {
  const [orbStatus, setOrbStatus] = useState<"idle" | "listening" | "thinking" | "speaking">("idle");
  const [isSigModalOpen, setSigModalOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<"cfo" | "agenda" | "tools" | "chat">("cfo");
  const [commandInput, setCommandInput] = useState("");
  const [lastSignature, setLastSignature] = useState<string | null>(null);
  const [clockStr, setClockStr] = useState("12:45");

  // Estado Real de Supabase
  const [sbConnected, setSbConnected] = useState<boolean>(false);
  const [loadingSync, setLoadingSync] = useState<boolean>(true);
  const [proyectos, setProyectos] = useState<ProyectoSB[]>([]);
  const [tareas, setTareas] = useState<TareaSB[]>([]);
  const [memoria, setMemoria] = useState<MemoriaSB[]>([]);
  const [resumen, setResumen] = useState<ResumenSB>({
    cajaNeta: 0,
    totalCobros: 0,
    totalGastos: 0,
    totalInversiones: 0,
    plataEnLaCalle: 0,
    totalCotizado: 0,
    saldosPorCuenta: {},
  });

  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: "init-1",
      sender: "jarvis",
      time: "EN LÍNEA",
      text: "Núcleo J.A.R.V.I.S. conectado a tu base de datos Supabase. Toca el Orbe Reactor para dictarme por voz o usa cualquier superpoder del panel.",
    },
  ]);

  // Reloj en tiempo real
  useEffect(() => {
    const updateClock = () => {
      setClockStr(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    };
    updateClock();
    const timer = setInterval(updateClock, 15000);
    return () => clearInterval(timer);
  }, []);

  // Sintetizador de voz nativo en navegador para cuando Jarvis responde en el HUD
  const speakJarvisBrowser = (text: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
      const clean = text.replace(/[*_#`~>•]/g, "");
      const utter = new SpeechSynthesisUtterance(clean);
      utter.lang = "es-MX";
      utter.rate = 1.06;
      utter.pitch = 0.88;
      utter.onstart = () => setOrbStatus("speaking");
      utter.onend = () => setOrbStatus("idle");
      window.speechSynthesis.speak(utter);
    } catch {
      setOrbStatus("idle");
    }
  };

  // Cargar datos reales desde /api/jarvis (Supabase)
  const fetchLiveSupabase = useCallback(async () => {
    setLoadingSync(true);
    try {
      const res = await fetch("/api/jarvis", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setSbConnected(Boolean(data.connected));
        setProyectos(data.proyectos || []);
        setTareas(data.tareas || []);
        setMemoria(data.memoria || []);
        if (data.resumen) setResumen(data.resumen);
      }
    } catch {
      setSbConnected(false);
    } finally {
      setLoadingSync(false);
    }
  }, []);

  useEffect(() => {
    fetchLiveSupabase();
    const interval = setInterval(fetchLiveSupabase, 20000);
    return () => clearInterval(interval);
  }, [fetchLiveSupabase]);

  // Enviar comando real a Jarvis (Claude Haiku 4.5 + Supabase)
  const executeCommand = async (ordenTexto: string, hablarRespuesta = false) => {
    const hora = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    setOrbStatus("thinking");
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-u`, sender: "luis", time: hora, text: ordenTexto },
    ]);

    try {
      const res = await fetch("/api/jarvis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "chat_jarvis",
          payload: {
            mensaje: ordenTexto,
            contextoResumen: {
              resumenFinanciero: resumen,
              proyectosActivos: proyectos.slice(0, 6),
              tareasPendientes: tareas.filter((t) => t.estado === "pendiente").slice(0, 8),
            },
          },
        }),
      });
      const data = await res.json();
      const respuesta = data.reply || "Orden procesada en Supabase.";

      setOrbStatus("speaking");
      setMessages((prev) => [
        ...prev,
        { id: `${Date.now()}-j`, sender: "jarvis", time: hora, text: respuesta },
      ]);

      if (hablarRespuesta) {
        speakJarvisBrowser(respuesta);
      } else {
        setTimeout(() => setOrbStatus("idle"), 2400);
      }
      fetchLiveSupabase();
    } catch {
      setOrbStatus("idle");
    }
  };

  // Reconocimiento de voz en vivo al tocar el Orbe Protagónico
  const handleOrbVoiceClick = () => {
    if (orbStatus !== "idle") {
      setOrbStatus("idle");
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
      return;
    }

    const SpeechRecognition =
      (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown })
        .SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setOrbStatus("listening");
      setTimeout(() => {
        executeCommand("Dame un resumen ejecutivo de nuestra caja neta, proyectos y tareas críticas de hoy", true);
      }, 1500);
      return;
    }

    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const recognition = new (SpeechRecognition as any)();
      recognition.lang = "es-ES";
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;

      setOrbStatus("listening");
      recognition.start();

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      recognition.onresult = (event: any) => {
        const transcript = event.results[0][0].transcript;
        if (transcript) {
          executeCommand(transcript, true);
        }
      };

      recognition.onerror = () => {
        setOrbStatus("idle");
      };
    } catch {
      setOrbStatus("idle");
    }
  };

  const handleSendCommand = (e: React.FormEvent) => {
    e.preventDefault();
    if (!commandInput.trim()) return;
    const cmd = commandInput.trim();
    setCommandInput("");
    executeCommand(cmd, false);
  };

  const handleToggleTarea = async (t: TareaSB) => {
    const nuevo = t.estado === "pendiente" ? "completada" : "pendiente";
    setOrbStatus("thinking");
    await fetch("/api/jarvis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "toggle_tarea",
        payload: { id: t.id, nuevo_estado: nuevo },
      }),
    });
    await fetchLiveSupabase();
    setOrbStatus("idle");
  };

  const handleSignatureSave = async (dataUrl: string) => {
    setLastSignature(dataUrl);
    await fetch("/api/jarvis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "guardar_memoria",
        payload: {
          categoria: "firma_digital",
          tema: "Firma Táctil en HUD",
          detalle: "Firma de conformidad capturada en el Dashboard Web y lista para PDF.",
        },
      }),
    });
    executeCommand("Confirmar captura de firma digital táctil para contrato PDF", false);
  };

  const cuentasEntries = Object.entries(resumen.saldosPorCuenta);
  const tareasPendientes = tareas.filter((t) => t.estado === "pendiente");

  return (
    <div className="min-h-screen w-full cyber-grid-bg text-slate-100 flex flex-col justify-between pb-20 lg:pb-4 relative overflow-x-hidden">
      {/* Luces ambientales Cyberpunk */}
      <div className="pointer-events-none fixed top-[-10%] left-[30%] w-[620px] h-[620px] rounded-full bg-cyber-cyan/10 blur-[160px]" />
      <div className="pointer-events-none fixed bottom-[-15%] right-[20%] w-[600px] h-[600px] rounded-full bg-cyber-purple/15 blur-[160px]" />

      {/* =====================================================================
          HEADER PANORÁMICO WIDESCREEN
      ===================================================================== */}
      <header className="w-full max-w-[1880px] mx-auto px-4 lg:px-8 pt-3 pb-2 flex items-center justify-between text-xs font-mono tracking-wider text-slate-300 z-20 border-b border-cyan-500/10">
        <div className="flex items-center gap-3">
          <span className="text-white font-bold text-sm">{clockStr}</span>
          <span className="text-cyber-cyan/80">•</span>
          <span className="text-[11px] sm:text-xs text-cyber-cyan uppercase tracking-[0.22em] font-semibold">
            {siteConfig.agency} // J.A.R.V.I.S. COCKPIT HUD
          </span>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchLiveSupabase}
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-400/30 text-cyber-cyan text-[11px] transition-colors"
          >
            <RefreshCw size={12} className={loadingSync ? "animate-spin" : ""} />
            {sbConnected ? "SUPABASE EN VIVO" : "MODO LOCAL"}
          </button>

          <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-400/30 text-emerald-300 text-[11px]">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
            CORE ONLINE
          </span>
        </div>
      </header>

      {/* =====================================================================
          COCKPIT PRINCIPAL WIDESCREEN (100% PANTALLA EN PC / PRIMERA VISTA EN MÓVIL)
      ===================================================================== */}
      <main className="w-full max-w-[1880px] mx-auto px-3 sm:px-5 lg:px-8 py-3 grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch z-10 flex-1">
        
        {/* ===================================================================
            COLUMNA CENTRAL PROTAGÓNICA: ROSTRO DE JARVIS + EL GRAN ORBE EN PRIMERA VISTA
            (En móvil aparece de PRIMERO arriba del todo `order-1`; en PC va en el centro `lg:order-2`)
        =================================================================== */}
        <section className="order-1 lg:order-2 lg:col-span-4 flex flex-col justify-between gap-4">
          <div className="hud-card p-4 sm:p-5 flex flex-col items-center justify-between flex-1 relative overflow-hidden border-cyan-400/35">
            {/* Etiqueta Superior */}
            <div className="w-full flex items-center justify-between mb-2 z-20">
              <span className="text-[10px] font-mono uppercase tracking-widest text-cyber-cyan/90">
                NÚCLEO HOLOGRÁFICO ACTIVO
              </span>
              <span className="px-3 py-0.5 rounded-full bg-[#091536] border border-cyan-400/40 text-[10px] font-bold uppercase tracking-[0.2em] text-cyber-cyan">
                J.A.R.V.I.S. AI
              </span>
            </div>

            {/* 1. BUSTO HOLOGRÁFICO CENTRAL DE JARVIS */}
            <div className="relative w-[175px] h-[185px] sm:w-[215px] sm:h-[225px] flex items-center justify-center">
              <div className="absolute inset-1 rounded-full border border-cyan-400/30 shadow-[0_0_45px_rgba(0,229,255,0.28)] animate-pulse-slow" />
              <div className="absolute inset-4 rounded-full border border-dashed border-blue-400/35 animate-spin-slow" />

              <div className="relative w-full h-full rounded-3xl overflow-hidden hologram-mask z-10">
                <img
                  src="/jarvis-face.jpg"
                  alt="Rostro Holográfico de Jarvis"
                  className="w-full h-full object-cover object-top scale-105 contrast-110 brightness-110"
                />
                <div className="absolute inset-0 hologram-scanlines pointer-events-none" />
              </div>

              {/* Base emisora de luz holográfica */}
              <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-32 h-2.5 rounded-full border border-cyber-cyan bg-white/90 shadow-[0_0_25px_#00E5FF] z-20" />
            </div>

            {/* 2. EL GRAN ORBE REACTOR PROTAGÓNICO (EN PRIMERA VISTA TANTO EN MÓVIL COMO EN PC) */}
            <div className="w-full flex flex-col items-center justify-center my-1 relative z-20">
              <ThinkingOrb status={orbStatus} onClick={handleOrbVoiceClick} size="hero" />

              <div className="mt-1 flex items-center gap-2">
                <button
                  onClick={handleOrbVoiceClick}
                  className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-cyber-cyan/15 hover:bg-cyber-cyan/30 border border-cyber-cyan/50 text-xs font-semibold text-cyber-cyan shadow-[0_0_20px_rgba(0,229,255,0.3)] transition-all"
                >
                  {orbStatus === "listening" ? <Volume2 size={15} className="animate-bounce" /> : <Mic size={15} />}
                  {orbStatus === "idle"
                    ? "Toca el Orbe para Hablar con Jarvis"
                    : orbStatus === "listening"
                    ? "Escuchando tu voz en vivo..."
                    : orbStatus === "thinking"
                    ? "Procesando en Supabase + Haiku 4.5..."
                    : "Jarvis respondiendo..."}
                </button>
              </div>
            </div>

            {/* 3. BARRA DIRECTA DE ÓRDENES EN EL CENTRO */}
            <form onSubmit={handleSendCommand} className="w-full mt-2 flex items-center gap-2 z-20">
              <input
                type="text"
                value={commandInput}
                onChange={(e) => setCommandInput(e.target.value)}
                placeholder="Ordena a Jarvis (ej: 'Anota cobro de $300 en Binance' o '¿Qué tenemos hoy?')..."
                className="flex-1 bg-[#050C22]/90 border border-cyan-400/35 rounded-xl px-3.5 py-2.5 text-xs text-white placeholder:text-slate-400 focus:outline-none focus:border-cyber-cyan shadow-inner"
              />
              <button
                type="submit"
                className="p-2.5 rounded-xl bg-cyber-cyan text-black hover:bg-cyan-300 transition-colors shadow-[0_0_15px_rgba(0,229,255,0.5)]"
              >
                <Send size={16} />
              </button>
            </form>
          </div>

          {/* CONSOLA COMPACTA DE RESPUESTA DE JARVIS DEBAJO DEL ORBE */}
          <div className="hud-card p-4 flex flex-col gap-2.5">
            <div className="flex items-center justify-between border-b border-white/10 pb-1.5">
              <span className="text-[10px] font-mono uppercase tracking-widest text-cyber-cyan">
                RESPUESTA EN VIVO DEL NÚCLEO
              </span>
              <span className="text-[10px] font-mono text-slate-400">CLAUDE HAIKU 4.5</span>
            </div>

            <div className="max-h-[135px] overflow-y-auto flex flex-col gap-2 pr-1">
              {messages.slice(-4).map((m) => (
                <div
                  key={m.id}
                  className={`p-2.5 rounded-xl text-xs leading-relaxed ${
                    m.sender === "luis"
                      ? "bg-blue-600/25 border border-blue-400/35 text-white self-end max-w-[92%]"
                      : "bg-[#081330]/90 border border-cyan-400/25 text-slate-100 self-start w-full"
                  }`}
                >
                  <span className="text-[10px] font-mono text-cyber-cyan block mb-0.5">
                    {m.sender === "luis" ? `TÚ • ${m.time}` : `JARVIS • ${m.time}`}
                  </span>
                  {m.text}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ===================================================================
            SELECTOR DE PESTAÑAS EMPAQUETADAS SOLO PARA MÓVIL (Debajo del Orbe)
        =================================================================== */}
        <div className="order-2 lg:hidden grid grid-cols-4 gap-2 bg-[#060D24]/90 p-1.5 rounded-2xl border border-cyan-400/25">
          <button
            onClick={() => setMobileTab("cfo")}
            className={`py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all ${
              mobileTab === "cfo" ? "bg-cyber-cyan text-black shadow-[0_0_12px_#00E5FF]" : "text-slate-300"
            }`}
          >
            💰 CFO
          </button>
          <button
            onClick={() => setMobileTab("agenda")}
            className={`py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all ${
              mobileTab === "agenda" ? "bg-cyber-cyan text-black shadow-[0_0_12px_#00E5FF]" : "text-slate-300"
            }`}
          >
            📋 Agenda
          </button>
          <button
            onClick={() => setMobileTab("tools")}
            className={`py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all ${
              mobileTab === "tools" ? "bg-cyber-cyan text-black shadow-[0_0_12px_#00E5FF]" : "text-slate-300"
            }`}
          >
            ⚡ Poderes
          </button>
          <button
            onClick={() => setMobileTab("chat")}
            className={`py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all ${
              mobileTab === "chat" ? "bg-cyber-cyan text-black shadow-[0_0_12px_#00E5FF]" : "text-slate-300"
            }`}
          >
            🧠 Bóveda
          </button>
        </div>

        {/* ===================================================================
            COLUMNA IZQUIERDA (SUPERPODERES DE JARVIS + ATAJOS RÁPIDOS + NODOS)
        =================================================================== */}
        <section
          className={`order-3 lg:order-1 lg:col-span-4 flex flex-col justify-between gap-4 ${
            mobileTab === "tools" ? "flex" : "hidden lg:flex"
          }`}
        >
          {/* 1. MATRIZ DE SUPERPODERES (AI TOOLS) */}
          <div className="hud-card p-5">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                  Hola, <span className="text-cyber-cyan">{siteConfig.boss.split(" ")[0]}</span>
                </h1>
                <p className="text-xs text-slate-300 mt-0.5">
                  Centro de Mando de {siteConfig.agency}
                </p>
              </div>
              <span className="px-2.5 py-1 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan/30 text-[10px] font-mono text-cyber-cyan">
                21 TOOLS
              </span>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2.5">
              <button
                onClick={() =>
                  executeCommand("Dame el balance financiero actual detallado por cuenta y plata en la calle")
                }
                className="hud-tool-btn group"
              >
                <DollarSign size={20} className="text-cyber-cyan group-hover:scale-110 transition-transform" />
                <span className="text-[11px] font-semibold text-slate-200">Balance CFO</span>
              </button>

              <button onClick={() => setSigModalOpen(true)} className="hud-tool-btn group">
                <FileText size={20} className="text-purple-400 group-hover:scale-110 transition-transform" />
                <span className="text-[11px] font-semibold text-slate-200">Firma / PDF</span>
              </button>

              <button
                onClick={() =>
                  executeCommand("¿Cómo uso el extractor de prospectos de Instagram con Instaloader?")
                }
                className="hud-tool-btn group"
              >
                <Instagram size={20} className="text-pink-400 group-hover:scale-110 transition-transform" />
                <span className="text-[11px] font-semibold text-slate-200">Scraping IG</span>
              </button>

              <button
                onClick={() =>
                  executeCommand("¿Cómo ejecuto un scraping web profundo de una página con Scrapling?")
                }
                className="hud-tool-btn group"
              >
                <Globe size={20} className="text-cyan-400 group-hover:scale-110 transition-transform" />
                <span className="text-[11px] font-semibold text-slate-200">Web Scraping</span>
              </button>

              <button
                onClick={() =>
                  executeCommand("Verifica el estado de mis archivos de Google Drive y Google Sheets")
                }
                className="hud-tool-btn group"
              >
                <HardDrive size={20} className="text-emerald-400 group-hover:scale-110 transition-transform" />
                <span className="text-[11px] font-semibold text-slate-200">Drive / Sheets</span>
              </button>

              <button
                onClick={() =>
                  executeCommand("Genera un Prompt Maestro con las 3 skills para un nuevo proyecto en Gemini")
                }
                className="hud-tool-btn group"
              >
                <Sparkles size={20} className="text-amber-400 group-hover:scale-110 transition-transform" />
                <span className="text-[11px] font-semibold text-slate-200">Prompt Gemini</span>
              </button>
            </div>
          </div>

          {/* 2. SMART SHORTCUTS (ATAJOS RÁPIDOS DE 1 CLIC) */}
          <div className="hud-card p-5 flex-1 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
                ATAJOS DE EJECUCIÓN RÁPIDA
              </h2>
              <span className="text-[10px] text-cyber-cyan font-mono">DIRECTOS</span>
            </div>

            <div className="flex flex-col gap-2.5">
              <div
                onClick={() =>
                  executeCommand("¿Qué prioridades críticas P1 debo atacar primero hoy según mi tablero?")
                }
                className="hud-row-item group"
              >
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-blue-500/15 border border-blue-400/30 flex items-center justify-center text-cyber-cyan">
                    <Calendar size={17} />
                  </div>
                  <div>
                    <p className="text-xs sm:text-sm font-semibold text-white group-hover:text-cyber-cyan">
                      Planificar mi Día (Anti-Procrastinación)
                    </p>
                    <p className="text-[11px] text-slate-400">Analiza proyectos pagados y reuniones P1</p>
                  </div>
                </div>
                <ChevronRight size={15} className="text-slate-500 group-hover:text-cyber-cyan" />
              </div>

              <div
                onClick={() =>
                  executeCommand("Redáctame un correo corporativo de seguimiento para un cliente de la agencia")
                }
                className="hud-row-item group"
              >
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-purple-500/15 border border-purple-400/30 flex items-center justify-center text-purple-300">
                    <Mail size={17} />
                  </div>
                  <div>
                    <p className="text-xs sm:text-sm font-semibold text-white group-hover:text-purple-300">
                      Asistente de Correo Resend
                    </p>
                    <p className="text-[11px] text-slate-400">Redacción ejecutiva @telotengosolutions.com</p>
                  </div>
                </div>
                <ChevronRight size={15} className="text-slate-500 group-hover:text-purple-300" />
              </div>

              <div
                onClick={() =>
                  executeCommand("Prepárame un mensaje persuasivo de cierre para enviar por WhatsApp (+584245885477)")
                }
                className="hud-row-item group"
              >
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-emerald-500/15 border border-emerald-400/30 flex items-center justify-center text-emerald-300">
                    <MessageSquare size={17} />
                  </div>
                  <div>
                    <p className="text-xs sm:text-sm font-semibold text-white group-hover:text-emerald-300">
                      Cierre por WhatsApp (+584245885477)
                    </p>
                    <p className="text-[11px] text-slate-400">Envío seguro bajo tu autorización</p>
                  </div>
                </div>
                <ChevronRight size={15} className="text-slate-500 group-hover:text-emerald-300" />
              </div>

              <div
                onClick={() =>
                  executeCommand("Háblame en voz alta con el resumen financiero y operativo de hoy", true)
                }
                className="hud-row-item group"
              >
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-cyan-500/15 border border-cyan-400/30 flex items-center justify-center text-cyber-cyan">
                    <Volume2 size={17} />
                  </div>
                  <div>
                    <p className="text-xs sm:text-sm font-semibold text-white group-hover:text-cyber-cyan">
                      Informe Hablado en Vivo
                    </p>
                    <p className="text-[11px] text-slate-400">Jarvis te lee el estado actual con voz</p>
                  </div>
                </div>
                <ChevronRight size={15} className="text-slate-500 group-hover:text-cyber-cyan" />
              </div>
            </div>
          </div>

          {/* 3. INFRAESTRUCTURA CONECTADA */}
          <div className="hud-card p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-bold uppercase tracking-widest text-slate-300">
                NODOS DEL SISTEMA
              </span>
              <span className="text-[10px] font-mono text-emerald-400">BLINDADO</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="p-2.5 rounded-xl bg-[#070E24]/80 border border-white/5 flex items-center gap-2">
                <Server size={15} className="text-cyber-cyan shrink-0" />
                <div className="truncate">
                  <p className="font-semibold text-white text-[11px]">Ubuntu Server</p>
                  <p className="text-[10px] text-emerald-400">tmux: jarvis</p>
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-[#070E24]/80 border border-white/5 flex items-center gap-2">
                <Database size={15} className="text-purple-400 shrink-0" />
                <div className="truncate">
                  <p className="font-semibold text-white text-[11px]">Supabase DB</p>
                  <p className="text-[10px] text-emerald-400">
                    {proyectos.length} proy / {tareas.length} tareas
                  </p>
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-[#070E24]/80 border border-white/5 flex items-center gap-2">
                <ShieldCheck size={15} className="text-blue-400 shrink-0" />
                <div className="truncate">
                  <p className="font-semibold text-white text-[11px]">Google Cloud</p>
                  <p className="text-[10px] text-cyber-cyan">Service Account</p>
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-[#070E24]/80 border border-white/5 flex items-center gap-2">
                <Smartphone size={15} className="text-emerald-400 shrink-0" />
                <div className="truncate">
                  <p className="font-semibold text-white text-[11px]">PWA Mobile</p>
                  <p className="text-[10px] text-emerald-400">Instalable</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ===================================================================
            COLUMNA DERECHA (FINANZAS REALES SUPABASE + PROYECTOS REALES + AGENDA REAL)
        =================================================================== */}
        <section
          className={`order-4 lg:order-3 lg:col-span-4 flex flex-col justify-between gap-4 ${
            mobileTab === "cfo" || mobileTab === "agenda" || mobileTab === "chat"
              ? "flex"
              : "hidden lg:flex"
          }`}
        >
          {/* 1. TESORERÍA CFO EN TIEMPO REAL (VALORES REALES DE SUPABASE) */}
          <div className={`hud-card p-5 ${mobileTab === "agenda" || mobileTab === "chat" ? "hidden lg:block" : "block"}`}>
            <div className="flex items-center justify-between text-xs text-slate-400 uppercase tracking-widest">
              <span>TESORERÍA CFO // CAJA NETA REAL</span>
              <span className="text-cyber-cyan font-mono">
                {sbConnected ? "🟢 SUPABASE LIVE" : "⚪ SINCRONIZANDO"}
              </span>
            </div>

            <div className="mt-3 flex items-center justify-between">
              <div>
                <div className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
                  ${resumen.cajaNeta.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <p className="text-xs text-amber-400 mt-1 font-semibold">
                  🔥 Plata en la calle (Por cobrar): $
                  {resumen.plataEnLaCalle.toLocaleString("en-US", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </p>
              </div>

              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-cyber-cyan/25 via-blue-600/20 to-purple-600/25 border border-cyan-400/40 flex flex-col items-center justify-center">
                <TrendingUp size={22} className="text-cyber-cyan" />
                <span className="text-[9px] font-mono text-white mt-0.5">CFO</span>
              </div>
            </div>

            {/* Desglose real de entradas, gastos y cuentas */}
            <div className="mt-4 pt-3 border-t border-white/10 grid grid-cols-3 gap-2 text-center">
              <div className="p-2 rounded-xl bg-[#070F26]/80 border border-white/5">
                <span className="text-[10px] text-slate-400 block">COBROS</span>
                <span className="text-xs font-bold text-emerald-400 mt-0.5 block">
                  +${resumen.totalCobros.toLocaleString("en-US")}
                </span>
              </div>
              <div className="p-2 rounded-xl bg-[#070F26]/80 border border-white/5">
                <span className="text-[10px] text-slate-400 block">COTIZADO</span>
                <span className="text-xs font-bold text-cyber-cyan mt-0.5 block">
                  ${resumen.totalCotizado.toLocaleString("en-US")}
                </span>
              </div>
              <div className="p-2 rounded-xl bg-[#070F26]/80 border border-white/5">
                <span className="text-[10px] text-slate-400 block">GASTOS/INV</span>
                <span className="text-xs font-bold text-rose-400 mt-0.5 block">
                  -${(resumen.totalGastos + resumen.totalInversiones).toLocaleString("en-US")}
                </span>
              </div>
            </div>

            {cuentasEntries.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {cuentasEntries.map(([cta, monto]) => (
                  <span
                    key={cta}
                    className="px-2.5 py-1 rounded-lg bg-[#081330] border border-cyan-400/20 text-[11px] font-mono text-slate-200"
                  >
                    {cta}: <strong className="text-cyber-cyan">${monto.toLocaleString("en-US")}</strong>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* 2. CARTERA DE PROYECTOS REALES EN SUPABASE */}
          <div className={`hud-card p-5 ${mobileTab === "chat" ? "hidden lg:block" : "block"}`}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
                CARTERA DE PROYECTOS ({proyectos.length})
              </h2>
              <span className="text-[10px] font-mono text-cyber-cyan">TIEMPO REAL</span>
            </div>

            <div className="max-h-[190px] overflow-y-auto flex flex-col gap-2 pr-1">
              {proyectos.length === 0 ? (
                <p className="text-xs text-slate-400 py-3 text-center">
                  No hay proyectos registrados aún en jarvis_proyectos.
                </p>
              ) : (
                proyectos.map((p) => {
                  const resta = Math.max(0, Number(p.monto_acordado || 0) - Number(p.monto_cobrado || 0));
                  return (
                    <div key={p.id} className="hud-row-item">
                      <div className="pr-2">
                        <p className="text-xs sm:text-sm font-semibold text-white">
                          {p.nombre_proyecto}{" "}
                          <span className="text-cyber-cyan font-normal">({p.cliente})</span>
                        </p>
                        <p className="text-[11px] text-slate-400 truncate max-w-[230px]">
                          {p.siguiente_paso || p.estado}
                        </p>
                      </div>
                      <div className="text-right shrink-0">
                        <span className="text-xs font-mono font-bold text-emerald-400 block">
                          ${Number(p.monto_acordado || 0).toLocaleString("en-US")}
                        </span>
                        {resta > 0 && (
                          <span className="text-[10px] font-mono text-amber-400 block">
                            Resta: ${resta.toLocaleString("en-US")}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* 3. AGENDA PRIORIZADA REAL (CON CHECK DE 1 CLIC EN SUPABASE) */}
          <div className={`hud-card p-5 flex-1 ${mobileTab === "cfo" ? "hidden lg:block" : "block"}`}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
                AGENDA PRIORIZADA ({tareasPendientes.length} PENDIENTES)
              </h2>
              <Clock size={15} className="text-cyber-cyan" />
            </div>

            <div className="max-h-[210px] overflow-y-auto flex flex-col gap-2 pr-1">
              {tareas.length === 0 ? (
                <p className="text-xs text-slate-400 py-3 text-center">
                  No hay tareas pendientes en Supabase.
                </p>
              ) : (
                tareas.slice(0, 8).map((t) => (
                  <div
                    key={t.id}
                    onClick={() => handleToggleTarea(t)}
                    className="hud-row-item group"
                    title="Haz clic para marcar como completada/pendiente en Supabase"
                  >
                    <div className="flex items-center gap-2.5">
                      <CheckCircle2
                        size={16}
                        className={
                          t.estado === "completada"
                            ? "text-emerald-400 shrink-0"
                            : "text-slate-500 group-hover:text-cyber-cyan shrink-0"
                        }
                      />
                      <div>
                        <p
                          className={`text-xs font-medium ${
                            t.estado === "completada" ? "line-through text-slate-500" : "text-white"
                          }`}
                        >
                          {t.titulo}
                        </p>
                        <p className="text-[10px] text-slate-400">
                          {t.cliente_o_proyecto} • {t.fecha_limite}
                        </p>
                      </div>
                    </div>
                    <span className="text-[10px] font-mono text-cyber-cyan shrink-0 ml-2">
                      P{t.prioridad}
                    </span>
                  </div>
                ))
              )}
            </div>

            {/* Recuerdos recientes de la Bóveda */}
            {memoria.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/10">
                <span className="text-[10px] font-mono uppercase tracking-widest text-purple-300 block mb-1.5">
                  ÚLTIMO APUNTE EN BÓVEDA ({memoria[0].cliente_o_tema})
                </span>
                <p className="text-[11px] text-slate-300 line-clamp-2 bg-[#070F26] p-2.5 rounded-xl border border-white/5">
                  {memoria[0].detalle_completo}
                </p>
              </div>
            )}

            {lastSignature && (
              <div className="mt-2.5 p-2.5 rounded-xl bg-white text-slate-900 flex items-center justify-between">
                <span className="text-[11px] font-bold">Firma Táctil Lista</span>
                <img src={lastSignature} alt="Firma" className="h-8 object-contain" />
              </div>
            )}
          </div>
        </section>
      </main>

      {/* =====================================================================
          BARRA INFERIOR EXCLUSIVA PARA MÓVIL (OCULTA EN PC `lg:hidden` PARA NO TAPAR NADA)
      ===================================================================== */}
      <nav className="lg:hidden fixed bottom-2.5 left-1/2 -translate-x-1/2 w-[94%] max-w-md hud-card px-5 py-2 flex items-center justify-between z-40 border border-cyan-400/40">
        <button
          onClick={() => setMobileTab("cfo")}
          className={`flex flex-col items-center gap-0.5 ${
            mobileTab === "cfo" ? "text-cyber-cyan" : "text-slate-400"
          }`}
        >
          <Home size={18} />
          <span className="text-[10px]">CFO</span>
        </button>

        <button
          onClick={() => setMobileTab("agenda")}
          className={`flex flex-col items-center gap-0.5 ${
            mobileTab === "agenda" ? "text-cyber-cyan" : "text-slate-400"
          }`}
        >
          <Clock size={18} />
          <span className="text-[10px]">Agenda</span>
        </button>

        <button
          onClick={handleOrbVoiceClick}
          className="relative -mt-5 w-12 h-12 rounded-full bg-gradient-to-b from-cyber-cyan via-blue-600 to-indigo-950 p-[2px] shadow-[0_0_20px_rgba(0,229,255,0.75)]"
        >
          <div className="w-full h-full rounded-full bg-[#050C24] flex items-center justify-center">
            <Mic size={18} className="text-cyber-cyan" />
          </div>
        </button>

        <button
          onClick={() => setMobileTab("tools")}
          className={`flex flex-col items-center gap-0.5 ${
            mobileTab === "tools" ? "text-cyber-cyan" : "text-slate-400"
          }`}
        >
          <Layers size={18} />
          <span className="text-[10px]">Poderes</span>
        </button>

        <button
          onClick={() => setSigModalOpen(true)}
          className="flex flex-col items-center gap-0.5 text-slate-400 hover:text-cyber-cyan"
        >
          <UserCheck size={18} />
          <span className="text-[10px]">Firma</span>
        </button>
      </nav>

      {/* Modal de Firma Digital Táctil */}
      <SignaturePadModal
        isOpen={isSigModalOpen}
        onClose={() => setSigModalOpen(false)}
        onSave={handleSignatureSave}
      />
    </div>
  );
}