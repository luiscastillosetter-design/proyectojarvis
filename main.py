import os
import sys
import json
import sqlite3
import logging
import requests
import time
import threading
import asyncio
import telebot
import platform
import datetime
from dotenv import load_dotenv
from duckduckgo_search import DDGS

# SDK Oficial de Google para Análisis de Videos y Google Workspace
from google import genai
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# Configuración de Logging Profesional
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("jarvis_system.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("JarvisExecutive")

# =====================================================================
# 1. CONFIGURACIÓN MAESTRA (MWAPI CLAUDE + SUPABASE + VOZ + WEB HUD)
# =====================================================================
load_dotenv()

MWAPI_KEY = os.getenv("MWAPI_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
MWAPI_BASE_URL = os.getenv("MWAPI_BASE_URL", "https://api.mwapi.dev").rstrip("/")
MWAPI_MODEL = os.getenv("MWAPI_MODEL", "claude-haiku-4-5-20251001")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
ID_TELEGRAM_LUIS = int(os.getenv("ID_TELEGRAM_LUIS", "0"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HORA_DESPERTADOR_DEFAULT = os.getenv("HORA_DESPERTADOR", "07:30")

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_PHONE_ID = os.getenv("META_PHONE_ID")

GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

VOZ_JARVIS = os.getenv("VOZ_JARVIS", "es-MX-JorgeNeural")
JARVIS_WEB_PORT = int(os.getenv("JARVIS_WEB_PORT", "8050"))
NOMBRE_AGENCIA = os.getenv("NOMBRE_AGENCIA", "GuiporDI Soluciones / Telotengo Solutions")
NOMBRE_JEFE = os.getenv("NOMBRE_JEFE", "Luis Castillo")

MODELO_AUDIO = "whisper-large-v3"
TEMPERATURA = 0.2
LIMITE_MEMORIA_CORTA = 12
ARCHIVO_DB_LOCAL = "jarvis_respaldo_local.db"

SCOPES_GOOGLE = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
bot = telebot.TeleBot(TOKEN_TELEGRAM) if TOKEN_TELEGRAM else None

db_lock = threading.Lock()
historial_lock = threading.Lock()

os.makedirs("temp_audios", exist_ok=True)
os.makedirs("temp_videos", exist_ok=True)
os.makedirs("contratos_pdf", exist_ok=True)

# =====================================================================
# 2. CONECTOR INTELIGENTE SUPABASE + RESPALDO LOCAL (SQLITE)
# =====================================================================
def supabase_activo() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY and "supabase.co" in SUPABASE_URL)

def sb_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def inicializar_respaldo_local():
    """Garantiza que Jarvis funcione al 100% incluso si falla la red hacia Supabase."""
    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT)""")
        c.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('hora_despertador', ?)", (HORA_DESPERTADOR_DEFAULT,))
        c.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('ultimo_briefing_fecha', '')")
        
        c.execute("""CREATE TABLE IF NOT EXISTS jarvis_proyectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_proyecto TEXT, cliente TEXT, estado TEXT, prioridad INTEGER,
            monto_acordado REAL DEFAULT 0, monto_cobrado REAL DEFAULT 0,
            fecha_entrega TEXT, siguiente_paso TEXT, notas TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS jarvis_tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT, cliente_o_proyecto TEXT, prioridad INTEGER,
            etiqueta_prioridad TEXT, fecha_limite TEXT, descripcion TEXT, estado TEXT DEFAULT 'pendiente'
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS jarvis_finanzas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT, monto REAL, moneda TEXT DEFAULT 'USD',
            concepto TEXT, cliente_o_proyecto TEXT, metodo_pago TEXT, fecha TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS jarvis_memoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT, cliente_o_tema TEXT, detalle_completo TEXT, fecha TEXT
        )""")
        conn.commit()
        conn.close()

inicializar_respaldo_local()

# =====================================================================
# 3. HERRAMIENTAS DE PROYECTOS, TAREAS, FINANZAS Y MEMORIA (SUPABASE)
# =====================================================================

def registrar_o_actualizar_proyecto(
    nombre_proyecto: str,
    cliente: str,
    estado: str = "1_Pagado_En_Curso",
    prioridad: int = 1,
    monto_acordado: float = 0.0,
    monto_cobrado: float = 0.0,
    fecha_entrega: str = "Cuando el jefe indique",
    siguiente_paso: str = "",
    notas: str = ""
) -> str:
    payload = {
        "nombre_proyecto": nombre_proyecto,
        "cliente": cliente,
        "estado": estado,
        "prioridad": int(prioridad),
        "monto_acordado": float(monto_acordado),
        "monto_cobrado": float(monto_cobrado),
        "fecha_entrega": fecha_entrega,
        "siguiente_paso": siguiente_paso,
        "notas": notas
    }
    saldo_pendiente = float(monto_acordado) - float(monto_cobrado)
    
    if supabase_activo():
        try:
            url = f"{SUPABASE_URL}/rest/v1/jarvis_proyectos"
            res = requests.post(url, headers=sb_headers(), json=payload, timeout=10)
            if res.status_code in [200, 201]:
                return (
                    f"🗂️ *[PROYECTO GUARDADO EN SUPABASE]*\n"
                    f"• *Proyecto:* {nombre_proyecto} ({cliente})\n"
                    f"• *Estado:* {estado} — *Meta:* {fecha_entrega}\n"
                    f"• *Finanzas:* Acordado USD {monto_acordado:,.2f} — Cobrado USD {monto_cobrado:,.2f} — *Por cobrar: USD {saldo_pendiente:,.2f}*\n"
                    f"• *Siguiente paso:* {siguiente_paso}"
                )
        except Exception as e:
            logger.warning(f"Fallo Supabase en proyecto: {e}")

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO jarvis_proyectos (nombre_proyecto, cliente, estado, prioridad, monto_acordado, monto_cobrado, fecha_entrega, siguiente_paso, notas) VALUES (?,?,?,?,?,?,?,?,?)",
            (nombre_proyecto, cliente, estado, int(prioridad), float(monto_acordado), float(monto_cobrado), fecha_entrega, siguiente_paso, notas)
        )
        conn.commit()
        conn.close()
    return f"🗂️ *[PROYECTO REGISTRADO]*: '{nombre_proyecto}' ({cliente}) — Por cobrar: USD {saldo_pendiente:,.2f}"

def consultar_tablero_proyectos() -> str:
    filas = []
    origen = "Supabase ☁️" if supabase_activo() else "Base Local 💾"
    
    if supabase_activo():
        try:
            url = f"{SUPABASE_URL}/rest/v1/jarvis_proyectos?select=*&order=prioridad.asc,id.asc"
            res = requests.get(url, headers=sb_headers(), timeout=10)
            if res.status_code == 200:
                filas = res.json()
        except Exception as e:
            logger.warning(f"Error consultando proyectos: {e}")

    if not filas:
        with db_lock:
            conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
            c = conn.cursor()
            c.execute("SELECT id, nombre_proyecto, cliente, estado, prioridad, monto_acordado, monto_cobrado, fecha_entrega, siguiente_paso, notas FROM jarvis_proyectos ORDER BY prioridad ASC, id ASC")
            for r in c.fetchall():
                filas.append({
                    "id": r[0], "nombre_proyecto": r[1], "cliente": r[2], "estado": r[3],
                    "prioridad": r[4], "monto_acordado": r[5], "monto_cobrado": r[6],
                    "fecha_entrega": r[7], "siguiente_paso": r[8], "notas": r[9]
                })
            conn.close()

    if not filas:
        return "📭 No hay proyectos registrados todavía."

    total_acordado = 0.0
    total_cobrado = 0.0
    lineas = [f"🚀 *TABLERO EJECUTIVO DE PROYECTOS ({origen})*\n"]

    for p in filas:
        acordado = float(p.get("monto_acordado") or 0)
        cobrado = float(p.get("monto_cobrado") or 0)
        pendiente = acordado - cobrado
        total_acordado += acordado
        total_cobrado += cobrado

        info_dinero = f"💰 Cotizado: USD {acordado:,.2f} — Cobrado: USD {cobrado:,.2f} — *Resta: USD {pendiente:,.2f}*" if acordado > 0 else "💵 _Monto aún por definir_"
        notas_txt = f"\n   • *Notas:* {p.get('notas')}" if p.get("notas") else ""
        lineas.append(
            f"🔹 *#{p.get('id')} - {p.get('nombre_proyecto')}* ({p.get('cliente')})\n"
            f"   • *Fase:* `{p.get('estado')}` — *Meta:* {p.get('fecha_entrega')}\n"
            f"   • {info_dinero}\n"
            f"   • *Acción:* {p.get('siguiente_paso')}{notas_txt}\n"
        )

    total_calle = total_acordado - total_cobrado
    lineas.append(
        f"----------------------------------------\n"
        f"📊 *RESUMEN DE CARTERA:*\n"
        f"• *Total Cerrado:* USD {total_acordado:,.2f}\n"
        f"• *Ya Cobrado:* USD {total_cobrado:,.2f}\n"
        f"• *🔥 PLATA EN LA CALLE (Por Cobrar):* *USD {total_calle:,.2f}*"
    )
    return "\n".join(lineas)

def agregar_tarea_agenda(titulo: str, cliente_o_proyecto: str = "General", fecha_limite: str = "Cuando el jefe indique", nivel_prioridad: int = 1, descripcion: str = "") -> str:
    mapa = {
        1: "🔴 1 - CRÍTICA (Ya pagó / Entrega o Reunión Inminente)",
        2: "🟠 2 - ALTA (Clonación rápida / Proyecto en curso)",
        3: "🟡 3 - MEDIA (Demo para prospecto)",
        4: "🟢 4 - BAJA (Idea / Sin urgencia)"
    }
    prio = max(1, min(4, int(nivel_prioridad)))
    etiqueta = mapa.get(prio, "🟠 2 - ALTA")

    if supabase_activo():
        try:
            url = f"{SUPABASE_URL}/rest/v1/jarvis_tareas"
            payload = {
                "titulo": titulo, "cliente_o_proyecto": cliente_o_proyecto, "prioridad": prio,
                "etiqueta_prioridad": etiqueta, "fecha_limite": fecha_limite, "descripcion": descripcion, "estado": "pendiente"
            }
            res = requests.post(url, headers=sb_headers(), json=payload, timeout=10)
            if res.status_code in [200, 201]:
                datos = res.json()
                t_id = datos[0].get("id") if isinstance(datos, list) and datos else "OK"
                return f"✅ *[TAREA #{t_id} EN SUPABASE]*: '{titulo}'\n• *Cliente/Nicho:* {cliente_o_proyecto}\n• *Prioridad:* {etiqueta}\n• *Tiempo asignado:* {fecha_limite}"
        except Exception as e:
            logger.warning(f"Fallback local en tarea: {e}")

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO jarvis_tareas (titulo, cliente_o_proyecto, prioridad, etiqueta_prioridad, fecha_limite, descripcion, estado) VALUES (?,?,?,?,?,?, 'pendiente')",
            (titulo, cliente_o_proyecto, prio, etiqueta, fecha_limite, descripcion)
        )
        t_id = c.lastrowid
        conn.commit()
        conn.close()
    return f"✅ *[TAREA #{t_id} ANOTADA]*: '{titulo}' ({etiqueta}) — Tiempo: {fecha_limite}."

def consultar_agenda_priorizada(estado: str = "pendiente") -> str:
    filas = []
    origen = "Supabase ☁️" if supabase_activo() else "Base Local 💾"

    if supabase_activo():
        try:
            filtro = "" if estado == "todas" else f"&estado=eq.{estado}"
            url = f"{SUPABASE_URL}/rest/v1/jarvis_tareas?select=*{filtro}&order=prioridad.asc,id.asc"
            res = requests.get(url, headers=sb_headers(), timeout=10)
            if res.status_code == 200:
                filas = res.json()
        except Exception as e:
            logger.warning(f"Error leyendo tareas en Supabase: {e}")

    if not filas:
        with db_lock:
            conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
            c = conn.cursor()
            if estado == "todas":
                c.execute("SELECT id, titulo, cliente_o_proyecto, etiqueta_prioridad, fecha_limite, descripcion, estado FROM jarvis_tareas ORDER BY prioridad ASC, id ASC")
            else:
                c.execute("SELECT id, titulo, cliente_o_proyecto, etiqueta_prioridad, fecha_limite, descripcion, estado FROM jarvis_tareas WHERE estado = ? ORDER BY prioridad ASC, id ASC", (estado,))
            for r in c.fetchall():
                filas.append({
                    "id": r[0], "titulo": r[1], "cliente_o_proyecto": r[2], "etiqueta_prioridad": r[3],
                    "fecha_limite": r[4], "descripcion": r[5], "estado": r[6]
                })
            conn.close()

    if not filas:
        return "🎉 No tienes tareas pendientes en este momento, jefe."

    lineas = [f"📋 *AGENDA PRIORIZADA DE {NOMBRE_JEFE.upper()} ({origen}):*\n"]
    for t in filas:
        icono = "⏳" if t.get("estado") == "pendiente" else "✅"
        desc_txt = f" — _{t.get('descripcion')}_" if t.get("descripcion") else ""
        lineas.append(
            f"{icono} *ID #{t.get('id')}: {t.get('titulo')}*\n"
            f"   • *Proyecto/Cliente:* {t.get('cliente_o_proyecto')}\n"
            f"   • *Prioridad:* {t.get('etiqueta_prioridad')}\n"
            f"   • *Horario/Plazo:* {t.get('fecha_limite')}{desc_txt}\n"
        )
    return "\n".join(lineas)

def cambiar_estado_tarea(id_tarea: int, nuevo_estado: str = "completada", nueva_fecha: str = "") -> str:
    datos_update = {"estado": nuevo_estado.lower()}
    if nueva_fecha:
        datos_update["fecha_limite"] = nueva_fecha

    if supabase_activo():
        try:
            url = f"{SUPABASE_URL}/rest/v1/jarvis_tareas?id=eq.{int(id_tarea)}"
            res = requests.patch(url, headers=sb_headers(), json=datos_update, timeout=10)
            if res.status_code in [200, 204]:
                return f"✅ Tarea #{id_tarea} actualizada a: *{nuevo_estado.upper()}*."
        except Exception as e:
            logger.warning(f"Error actualizando tarea en Supabase: {e}")

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        if nueva_fecha:
            c.execute("UPDATE jarvis_tareas SET estado = ?, fecha_limite = ? WHERE id = ?", (nuevo_estado.lower(), nueva_fecha, int(id_tarea)))
        else:
            c.execute("UPDATE jarvis_tareas SET estado = ? WHERE id = ?", (nuevo_estado.lower(), int(id_tarea)))
        conn.commit()
        conn.close()
    return f"✅ Tarea #{id_tarea} marcada como *{nuevo_estado.upper()}*."

def registrar_movimiento_financiero(tipo: str, monto: float, concepto: str, cliente_o_proyecto: str = "Agencia", metodo_pago: str = "General", moneda: str = "USD") -> str:
    tipo_limpio = tipo.lower().strip()
    if tipo_limpio not in ["cobro", "gasto", "inversion"]:
        tipo_limpio = "gasto" if "gast" in tipo_limpio else ("inversion" if "inver" in tipo_limpio else "cobro")
    
    fecha_hoy = str(datetime.date.today())
    payload = {
        "tipo": tipo_limpio, "monto": float(monto), "moneda": moneda.upper(),
        "concepto": concepto, "cliente_o_proyecto": cliente_o_proyecto,
        "metodo_pago": metodo_pago.strip(), "fecha": fecha_hoy
    }

    icono = "💵" if tipo_limpio == "cobro" else ("💸" if tipo_limpio == "gasto" else "🚀")
    if supabase_activo():
        try:
            url = f"{SUPABASE_URL}/rest/v1/jarvis_finanzas"
            res = requests.post(url, headers=sb_headers(), json=payload, timeout=10)
            if res.status_code in [200, 201]:
                return (
                    f"{icono} *[FINANZAS SUPABASE - {tipo_limpio.upper()} REGISTRADO]*\n"
                    f"• *Monto:* USD {float(monto):,.2f} ({moneda.upper()})\n"
                    f"• *Cuenta/Método:* {metodo_pago}\n"
                    f"• *Concepto:* {concepto} ({cliente_o_proyecto})"
                )
        except Exception as e:
            logger.warning(f"Error guardando finanza en Supabase: {e}")

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO jarvis_finanzas (tipo, monto, moneda, concepto, cliente_o_proyecto, metodo_pago, fecha) VALUES (?,?,?,?,?,?,?)",
            (tipo_limpio, float(monto), moneda.upper(), concepto, cliente_o_proyecto, metodo_pago.strip(), fecha_hoy)
        )
        conn.commit()
        conn.close()
    return f"{icono} *[{tipo_limpio.upper()} REGISTRADO]*: USD {float(monto):,.2f} {moneda.upper()} en {metodo_pago} - {concepto}."

def consultar_reporte_financiero(filtro_cliente: str = "") -> str:
    filas = []
    origen = "Supabase ☁️" if supabase_activo() else "Base Local 💾"

    if supabase_activo():
        try:
            url = f"{SUPABASE_URL}/rest/v1/jarvis_finanzas?select=*&order=id.desc&limit=100"
            res = requests.get(url, headers=sb_headers(), timeout=10)
            if res.status_code == 200:
                filas = res.json()
        except Exception as e:
            logger.warning(f"Error leyendo finanzas de Supabase: {e}")

    if not filas:
        with db_lock:
            conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
            c = conn.cursor()
            c.execute("SELECT id, tipo, monto, moneda, concepto, cliente_o_proyecto, metodo_pago, fecha FROM jarvis_finanzas ORDER BY id DESC LIMIT 100")
            for r in c.fetchall():
                filas.append({
                    "id": r[0], "tipo": r[1], "monto": r[2], "moneda": r[3],
                    "concepto": r[4], "cliente_o_proyecto": r[5], "metodo_pago": r[6], "fecha": r[7]
                })
            conn.close()

    plata_en_la_calle = 0.0
    if supabase_activo():
        try:
            res_p = requests.get(f"{SUPABASE_URL}/rest/v1/jarvis_proyectos?select=monto_acordado,monto_cobrado", headers=sb_headers(), timeout=8)
            if res_p.status_code == 200:
                for pr in res_p.json():
                    plata_en_la_calle += (float(pr.get("monto_acordado") or 0) - float(pr.get("monto_cobrado") or 0))
        except Exception:
            pass

    if not filas and plata_en_la_calle == 0:
        return "📊 Aún no hay movimientos financieros registrados."

    if filtro_cliente:
        f_low = filtro_cliente.lower()
        filas = [x for x in filas if f_low in str(x.get("cliente_o_proyecto", "")).lower() or f_low in str(x.get("concepto", "")).lower() or f_low in str(x.get("metodo_pago", "")).lower()]

    total_cobros = sum(float(x.get("monto", 0)) for x in filas if x.get("tipo") == "cobro")
    total_gastos = sum(float(x.get("monto", 0)) for x in filas if x.get("tipo") == "gasto")
    total_inversiones = sum(float(x.get("monto", 0)) for x in filas if x.get("tipo") == "inversion")
    flujo_neto = total_cobros - (total_gastos + total_inversiones)

    saldos_por_cuenta = {}
    for x in filas:
        cuenta = (x.get("metodo_pago") or "General").strip().title()
        monto_m = float(x.get("monto", 0))
        if x.get("tipo") == "cobro":
            saldos_por_cuenta[cuenta] = saldos_por_cuenta.get(cuenta, 0.0) + monto_m
        else:
            saldos_por_cuenta[cuenta] = saldos_por_cuenta.get(cuenta, 0.0) - monto_m

    lineas = [
        f"💰 *REPORTE CFO DE {NOMBRE_AGENCIA.upper()} ({origen})*\n",
        f"🟢 *Total Cobros (Entradas):* +USD {total_cobros:,.2f}",
        f"🔴 *Total Gastos Operativos:* -USD {total_gastos:,.2f}",
        f"🚀 *Total Inversiones (Tokens/Tech):* -USD {total_inversiones:,.2f}",
        f"⚖️ *CAJA NETA DISPONIBLE:* *USD {flujo_neto:,.2f}*",
        f"🔥 *PLATA EN LA CALLE (Por Cobrar):* *USD {plata_en_la_calle:,.2f}*\n"
    ]

    if saldos_por_cuenta:
        lineas.append("🏦 *SALDO TEÓRICO POR CUENTA / BILLETERA:*")
        for cta, saldo_cta in saldos_por_cuenta.items():
            lineas.append(f"   • *{cta}:* USD {saldo_cta:,.2f}")
        lineas.append("")

    lineas.append("📜 *Últimos Movimientos:*")
    for m in filas[:10]:
        t = m.get("tipo", "cobro")
        ico = "🟢 Cobro" if t == "cobro" else ("🔴 Gasto" if t == "gasto" else "🚀 Inversión")
        cta_txt = m.get("metodo_pago") or "General"
        lineas.append(f"• [{m.get('fecha')}] {ico} ({cta_txt}): *USD {float(m.get('monto', 0)):,.2f}* — {m.get('concepto')} (_{m.get('cliente_o_proyecto')}_)")

    return "\n".join(lineas)

def guardar_en_boveda_memoria(cliente_o_tema: str, detalle_completo: str, categoria: str = "acuerdo_cliente") -> str:
    fecha_hoy = str(datetime.date.today())
    payload = {
        "categoria": categoria, "cliente_o_tema": cliente_o_tema, "detalle_completo": detalle_completo, "fecha": fecha_hoy
    }
    if supabase_activo():
        try:
            url = f"{SUPABASE_URL}/rest/v1/jarvis_memoria"
            res = requests.post(url, headers=sb_headers(), json=payload, timeout=10)
            if res.status_code in [200, 201]:
                return f"🧠 *[GUARDADO EN BÓVEDA SUPABASE]*: '{cliente_o_tema}' -> {detalle_completo}"
        except Exception as e:
            logger.warning(f"Error guardando en bóveda Supabase: {e}")

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute("INSERT INTO jarvis_memoria (categoria, cliente_o_tema, detalle_completo, fecha) VALUES (?,?,?,?)", (categoria, cliente_o_tema, detalle_completo, fecha_hoy))
        conn.commit()
        conn.close()
    return f"🧠 *[GUARDADO EN BÓVEDA]*: '{cliente_o_tema}' -> {detalle_completo}"

def buscar_en_boveda_memoria(palabra_clave: str = "") -> str:
    resultados = []
    if supabase_activo():
        try:
            if palabra_clave:
                q = palabra_clave.strip()
                url = f"{SUPABASE_URL}/rest/v1/jarvis_memoria?or=(cliente_o_tema.ilike.*{q}*,detalle_completo.ilike.*{q}*)&order=id.desc&limit=25"
            else:
                url = f"{SUPABASE_URL}/rest/v1/jarvis_memoria?select=*&order=id.desc&limit=25"
            res = requests.get(url, headers=sb_headers(), timeout=10)
            if res.status_code == 200:
                resultados = res.json()
        except Exception as e:
            logger.warning(f"Error buscando en bóveda Supabase: {e}")

    if not resultados:
        with db_lock:
            conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
            c = conn.cursor()
            if palabra_clave:
                like_q = f"%{palabra_clave}%"
                c.execute("SELECT fecha, categoria, cliente_o_tema, detalle_completo FROM jarvis_memoria WHERE cliente_o_tema LIKE ? OR detalle_completo LIKE ? ORDER BY id DESC LIMIT 25", (like_q, like_q))
            else:
                c.execute("SELECT fecha, categoria, cliente_o_tema, detalle_completo FROM jarvis_memoria ORDER BY id DESC LIMIT 25")
            for r in c.fetchall():
                resultados.append({"fecha": r[0], "categoria": r[1], "cliente_o_tema": r[2], "detalle_completo": r[3]})
            conn.close()

    if not resultados:
        return f"📭 No encontré apuntes previos sobre '{palabra_clave}' en la Bóveda."

    lineas = [f"🔍 *[RECUERDOS EN LA BÓVEDA PARA '{palabra_clave or 'TODO'}']*:\n"]
    for item in resultados:
        lineas.append(f"• *[{item.get('fecha')}] {item.get('cliente_o_tema')}* ({item.get('categoria')}):\n  _{item.get('detalle_completo')}_")
    return "\n".join(lineas)

def configurar_hora_despertador(hora_24h: str) -> str:
    try:
        partes = hora_24h.strip().split(":")
        hora_formateada = f"{int(partes[0]):02d}:{int(partes[1]):02d}"
        with db_lock:
            conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('hora_despertador', ?)", (hora_formateada,))
            conn.commit()
            conn.close()
        return f"⏰ *[DESPERTADOR CONFIGURADO]*: Te despertaré todos los días a las {hora_formateada} con tu agenda, proyectos y finanzas."
    except Exception:
        return "❌ Formato inválido. Usa formato 24h como '07:30' o '08:00'."

def generar_plan_y_prompt_gemini(idea_o_proyecto: str, cliente_o_nicho: str, requerimientos_clave: str) -> str:
    plantilla = f"""🚀 *PLAN DE EJECUCIÓN Y PROMPT MAESTRO PARA GEMINI*
==================================================
📌 *Proyecto:* {idea_o_proyecto}
🏢 *Cliente / Nicho:* {cliente_o_nicho}

### 🗺️ ETAPAS DE DESARROLLO:
1. **Etapa 1 (Configuración Marca Blanca):** Definir datos del negocio, colores y estructura en `src/config/site.ts`.
2. **Etapa 2 (Interfaz Dual Móvil/PC):** Construir la landing/aplicación principal garantizando 0 elementos encimados en celular.
3. **Etapa 3 (Flujo Funcional y Cierre):** Conectar lógica clave ({requerimientos_clave}) y embudo directo a WhatsApp/Pagos.

---
📋 *COPIA Y PEGA ESTE PROMPT EN GEMINI:*
```text
Gemini, vamos a construir este proyecto aplicando obligatoriamente nuestras 3 skills:
1. "arquitecto-guiado-paso-a-paso" (Regla de Oro: PROHIBIDO recortar o resumir código; entrega siempre archivos completos de la línea 1 a la final y aplica freno de mano de 1 sola tarea a la vez).
2. "auditor-ui-responsive-dual" (Cero elementos encimados en celular y PC).
3. "memoria-activa-proyectos" (Arquitectura marca blanca desde src/config/site.ts y autogestión en /admin).
Además, aplica nuestra directiva Top-Tier Open Source (solo herramientas premium líderes).

PROYECTO: {idea_o_proyecto}
CLIENTE / NICHO: {cliente_o_nicho}
REQUERIMIENTOS CLAVE: {requerimientos_clave}

Por favor:
1. Propón la arquitectura limpia en Next.js + Tailwind CSS.
2. Divídelo en Tareas claras sin imponer fechas.
3. Entrégame de inmediato el código completo de la TAREA 1 y espera mi luz verde.
```"""
    guardar_en_boveda_memoria(cliente_o_nicho, f"Plan creado para proyecto '{idea_o_proyecto}': {requerimientos_clave}", "arquitectura_prompts")
    return plantilla

# =====================================================================
# 4. HERRAMIENTAS DE INVESTIGACIÓN WEB, GOOGLE WORKSPACE, SCRAPING, VOZ Y CONTRATOS
# =====================================================================
def buscar_y_leer_internet(query: str, max_resultados: int = 4) -> str:
    try:
        try:
            res_jina = requests.get(f"https://s.jina.ai/{query}", headers={"Accept": "text/plain"}, timeout=12)
            if res_jina.status_code == 200 and len(res_jina.text.strip()) > 100:
                return f"🌐 [INVESTIGACIÓN WEB EN VIVO]:\n\n{res_jina.text[:3500]}"
        except Exception:
            pass
        res = DDGS().text(query, max_results=max_resultados)
        if not res:
            return "⚠️ Sin resultados en la web."
        bloques = []
        for r in res:
            bloques.append(f"• *{r.get('title')}*\n  URL: {r.get('href')}\n  Resumen: {r.get('body')}\n")
        return "\n".join(bloques)
    except Exception as e:
        return f"❌ Error buscando en internet: {str(e)}"

def autenticar_google():
    """Autenticación perpetua 24/7 vía Cuenta de Servicio (o respaldo OAuth sin colgar SSH)."""
    if os.path.exists('credentials.json'):
        try:
            with open('credentials.json', 'r', encoding='utf-8') as f:
                data_cred = json.load(f)
            if data_cred.get("type") == "service_account":
                return ServiceAccountCredentials.from_service_account_file('credentials.json', scopes=SCOPES_GOOGLE)
        except Exception as e:
            logger.error(f"Error leyendo credentials.json de Cuenta de Servicio: {e}")

    creds = None
    if os.path.exists('token_google.json'):
        try:
            creds = Credentials.from_authorized_user_file('token_google.json', SCOPES_GOOGLE)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open('token_google.json', 'w', encoding='utf-8') as token_file:
                    token_file.write(creds.to_json())
        except Exception as e:
            logger.error(f"Error refrescando token_google.json: {e}")
            return None
    return creds

def _obtener_id_calendario_compartido(service) -> str:
    """Detecta automáticamente el calendario personal de Luis compartido con la Cuenta de Servicio."""
    if GOOGLE_CALENDAR_ID and GOOGLE_CALENDAR_ID != "primary":
        return GOOGLE_CALENDAR_ID
    try:
        cal_list = service.calendarList().list().execute().get('items', [])
        for cal in cal_list:
            cal_id = cal.get('id', '')
            if '@' in cal_id and not cal_id.endswith('iam.gserviceaccount.com') and not cal_id.endswith('group.calendar.google.com'):
                return cal_id
    except Exception:
        pass
    return 'primary'

def crear_reunion_google_meet(titulo: str, fecha_hora_iso: str, duracion_minutos: int = 60, descripcion: str = "") -> str:
    try:
        creds = autenticar_google()
        if not creds:
            return "⚠️ No hay credenciales de Google activas (verifica credentials.json)."
        service = build('calendar', 'v3', credentials=creds)
        cal_id = _obtener_id_calendario_compartido(service)

        fecha_limpia = fecha_hora_iso.replace("Z", "").strip()
        inicio = datetime.datetime.fromisoformat(fecha_limpia)
        fin = inicio + datetime.timedelta(minutes=int(duracion_minutos))

        evento_base = {
            'summary': titulo,
            'description': descripcion or f"Agendado por Jarvis Executive para {NOMBRE_JEFE}",
            'start': {'dateTime': inicio.isoformat(), 'timeZone': 'America/New_York'},
            'end': {'dateTime': fin.isoformat(), 'timeZone': 'America/New_York'}
        }

        try:
            evento_meet = dict(evento_base)
            evento_meet['conferenceData'] = {'createRequest': {'requestId': f"req_{int(time.time())}", 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}}
            res = service.events().insert(calendarId=cal_id, body=evento_meet, conferenceDataVersion=1).execute()
        except Exception:
            res = service.events().insert(calendarId=cal_id, body=evento_base).execute()

        link_html = res.get('htmlLink', 'N/D')
        link_meet = res.get('hangoutLink', '')
        extra_meet = f"\n• *Link Meet:* {link_meet}" if link_meet else ""
        return (
            f"📅 *[EVENTO AGENDADO EN GOOGLE CALENDAR]*\n"
            f"• *Título:* {titulo}\n"
            f"• *Calendario:* `{cal_id}`\n"
            f"• *Inicio:* {inicio.strftime('%Y-%m-%d %H:%M')}\n"
            f"• *Enlace Calendar:* {link_html}{extra_meet}"
        )
    except Exception as e:
        return f"❌ Error agendando en Google Calendar: {str(e)}"

def consultar_eventos_google_calendar(dias_adelante: int = 7) -> str:
    """Lee los próximos eventos del Google Calendar de Luis."""
    try:
        creds = autenticar_google()
        if not creds:
            return "⚠️ No hay credenciales de Google activas."
        service = build('calendar', 'v3', credentials=creds)
        cal_id = _obtener_id_calendario_compartido(service)
        ahora = datetime.datetime.utcnow().isoformat() + 'Z'
        limite = (datetime.datetime.utcnow() + datetime.timedelta(days=int(dias_adelante))).isoformat() + 'Z'

        eventos_res = service.events().list(
            calendarId=cal_id, timeMin=ahora, timeMax=limite,
            maxResults=15, singleEvents=True, orderBy='startTime'
        ).execute()
        items = eventos_res.get('items', [])
        if not items:
            return f"📭 No tienes eventos agendados en Google Calendar (`{cal_id}`) para los próximos {dias_adelante} días."

        lineas = [f"📅 *PRÓXIMOS EVENTOS EN GOOGLE CALENDAR ({cal_id}):*\n"]
        for ev in items:
            inicio = ev['start'].get('dateTime', ev['start'].get('date'))
            lineas.append(f"• *{inicio}* — {ev.get('summary', 'Sin título')}")
        return "\n".join(lineas)
    except Exception as e:
        return f"❌ Error leyendo Google Calendar: {str(e)}"

def enviar_correo_resend(destinatario: str, asunto: str, cuerpo_mensaje: str) -> str:
    try:
        api_key = os.getenv("RESEND_API_KEY")
        if not api_key:
            return "⚠️ Falta RESEND_API_KEY en el archivo .env."
        remitente = os.getenv("RESEND_CORREO_ORIGEN", "info@telotengosolutions.com")
        res = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": remitente, "to": [destinatario.strip()], "subject": asunto, "text": cuerpo_mensaje},
            timeout=15
        )
        return f"✅ *[CORREO ENVIADO CON ÉXITO]*\n• *Para:* {destinatario}\n• *Asunto:* {asunto}" if res.status_code in [200, 201] else f"❌ Error Resend ({res.status_code}): {res.text}"
    except Exception as e:
        return f"❌ Error enviando correo: {str(e)}"

def enviar_mensaje_whatsapp_oficial(telefono_destino: str, mensaje: str) -> str:
    if not META_ACCESS_TOKEN or not META_PHONE_ID:
        return "⚠️ Faltan credenciales Meta (META_ACCESS_TOKEN / META_PHONE_ID) en .env."
    url = f"https://graph.facebook.com/v17.0/{META_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": telefono_destino, "type": "text", "text": {"body": mensaje}}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        return f"✅ WhatsApp enviado a {telefono_destino}." if res.status_code == 200 else f"❌ Error Meta: {res.text}"
    except Exception as e:
        return f"❌ Error WhatsApp: {str(e)}"

def buscar_archivo_google_drive(nombre_archivo: str = "") -> str:
    """Busca archivos o tablas en Google Drive compartidos con Jarvis y devuelve su ID."""
    try:
        creds = autenticar_google()
        if not creds:
            return "⚠️ No hay credenciales de Google activas."
        service = build('drive', 'v3', credentials=creds)
        if nombre_archivo.strip():
            query = f"name contains '{nombre_archivo.strip()}' and trashed = false"
        else:
            query = "trashed = false"
        results = service.files().list(q=query, pageSize=15, fields="files(id, name, mimeType, webViewLink)").execute()
        items = results.get('files', [])
        if not items:
            return f"📭 No encontré archivos en Drive que coincidan con '{nombre_archivo}'. Recuerda compartir el archivo o carpeta con el correo de la Cuenta de Servicio."
        res_str = "📁 *ARCHIVOS ENCONTRADOS EN GOOGLE DRIVE*:\n"
        for i in items:
            tipo = "Hoja de Cálculo (Sheets)" if "spreadsheet" in i.get('mimeType', '') else ("Carpeta" if "folder" in i.get('mimeType', '') else "Documento/Archivo")
            res_str += f"• *{i['name']}* ({tipo})\n  • ID: `{i['id']}`\n"
        return res_str
    except Exception as e:
        return f"❌ Error en Google Drive: {str(e)}"

def gestionar_google_sheets(accion: str, spreadsheet_id: str, rango: str = "A1:Z50", valores_json: str = "[]") -> str:
    """Lee, escribe o actualiza celdas en un Google Sheet usando su ID."""
    try:
        creds = autenticar_google()
        if not creds:
            return "⚠️ No hay credenciales de Google activas."
        service = build('sheets', 'v4', credentials=creds)
        
        if accion.lower() == "leer":
            res = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rango).execute()
            datos = res.get('values', [])
            if not datos:
                return f"📭 El rango {rango} está vacío."
            lineas_formateadas = [f"📊 *DATOS DE GOOGLE SHEETS ({rango}):*\n"]
            for idx, fila in enumerate(datos[:30], start=1):
                lineas_formateadas.append(f"• *Fila {idx}:* " + " — ".join(str(celda) for celda in fila))
            return "\n".join(lineas_formateadas)
        
        elif accion.lower() in ["escribir", "editar", "agregar"]:
            try:
                data_array = json.loads(valores_json)
                if not isinstance(data_array, list):
                    data_array = [[str(data_array)]]
                elif data_array and not isinstance(data_array[0], list):
                    data_array = [data_array]
            except Exception:
                data_array = [[valores_json]]
            body = {'values': data_array}
            res = service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id, range=rango,
                valueInputOption="USER_ENTERED", body=body).execute()
            celdas = res.get('updates', {}).get('updatedCells', 0)
            return f"✅ *[GOOGLE SHEETS ACTUALIZADO]*: Se han agregado/editado {celdas} celdas en `{rango}`."
        return "❌ Acción inválida. Usa 'leer' o 'escribir'."
    except Exception as e:
        return f"❌ Error en Google Sheets: {str(e)}"

def extraer_datos_instagram(usuario_o_shortcode: str, palabra_clave_filtro: str = "") -> str:
    """Extrae publicaciones de un perfil o todos los comentarios de un post de Instagram y filtra prospectos."""
    try:
        import instaloader
        L = instaloader.Instaloader(quiet=True)
        objetivo = usuario_o_shortcode.strip().replace("@", "").rstrip("/")
        if "instagram.com/p/" in objetivo or "instagram.com/reel/" in objetivo:
            objetivo = objetivo.split("/")[-1]

        # Caso 1: Es un Shortcode de un Post/Reel (extraer comentarios)
        if len(objetivo) == 11 and "_" not in objetivo and "." not in objetivo:
            post = instaloader.Post.from_shortcode(L.context, objetivo)
            comentarios = []
            for c in post.get_comments():
                txt = c.text or ""
                if not palabra_clave_filtro or palabra_clave_filtro.lower() in txt.lower():
                    comentarios.append(f"• @{c.owner.username}: {txt}")
                if len(comentarios) >= 100:
                    break
            if not comentarios:
                return f"📸 Analicé el post `{objetivo}`, pero no encontré comentarios públicos o que coincidan con '{palabra_clave_filtro}'."
            resumen = "\n".join(comentarios[:25])
            guardar_en_boveda_memoria(f"Leads Instagram ({objetivo})", resumen[:1500], "leads_scraping")
            return f"📸 *[SCRAPING INSTAGRAM - {len(comentarios)} COMENTARIOS EXTRAÍDOS]*:\n\n{resumen}"

        # Caso 2: Es un Perfil de Usuario (extraer biografía y últimas publicaciones)
        profile = instaloader.Profile.from_username(L.context, objetivo)
        lineas = [
            f"📸 *[PERFIL DE INSTAGRAM: @{profile.username}]*",
            f"• *Nombre:* {profile.full_name}",
            f"• *Seguidores:* {profile.followers:,} — *Siguiendo:* {profile.followees:,}",
            f"• *Biografía:* {profile.biography}",
            f"\n🔥 *Últimas Publicaciones:*"
        ]
        cont = 0
        for post in profile.get_posts():
            caption = (post.caption or "Sin texto")[:160].replace("\n", " ")
            if not palabra_clave_filtro or palabra_clave_filtro.lower() in caption.lower():
                lineas.append(f"• *Post `{post.shortcode}`* ({post.likes} likes, {post.comments} coment.): _{caption}_")
                cont += 1
            if cont >= 8:
                break
        salida = "\n".join(lineas)
        guardar_en_boveda_memoria(f"Perfil IG @{profile.username}", salida[:1500], "leads_scraping")
        return salida
    except Exception as e:
        res_fallback = buscar_y_leer_internet(f"site:instagram.com {usuario_o_shortcode} {palabra_clave_filtro}")
        return f"⚠️ Instagram bloqueó la conexión directa sin login ({str(e)[:120]}). Aquí tienes el rastreo profundo alternativo:\n\n{res_fallback}"

def scraping_web_profundo(url: str, aguja_a_buscar: str = "") -> str:
    """Extrae datos profundos de cualquier sitio web usando Scrapling + Jina Reader."""
    try:
        url_limpia = url.strip()
        if not url_limpia.startswith("http"):
            url_limpia = "https://" + url_limpia

        texto_extraido = ""
        try:
            from scrapling import Fetcher
            fetcher = Fetcher(auto_match=False)
            page = fetcher.get(url_limpia)
            texto_extraido = page.get_all_text(ignore_tags=('script', 'style', 'noscript'))
        except Exception:
            res_jina = requests.get(f"https://r.jina.ai/{url_limpia}", timeout=15)
            texto_extraido = res_jina.text

        texto_extraido = (texto_extraido or "").strip()
        if not texto_extraido:
            return f"⚠️ No pude extraer texto legible de {url_limpia}."

        if aguja_a_buscar:
            lineas_coincidentes = [ln.strip() for ln in texto_extraido.splitlines() if aguja_a_buscar.lower() in ln.lower() and len(ln.strip()) > 3]
            extracto = "\n".join(f"• {l[:250]}" for l in lineas_coincidentes[:20]) or "No se halló la palabra exacta, mostrando contenido general:\n" + texto_extraido[:2500]
            return f"🕸️ *[SCRAPING PROFUNDO EN {url_limpia} — Filtro: '{aguja_a_buscar}']*\n\n{extracto}"

        return f"🕸️ *[SCRAPING PROFUNDO EN {url_limpia}]*\n\n{texto_extraido[:3200]}"
    except Exception as e:
        return f"❌ Error en Scraping profundo: {str(e)}"

def generar_contrato_o_documento_formal(
    titulo_documento: str,
    nombre_cliente: str,
    cuerpo_clausulas: str,
    monto_acordado_usd: float = 0.0
) -> str:
    """Genera un Contrato o Propuesta formal en PDF, lo envía por Telegram a Luis, lo respalda en Google Drive y lo habilita para firma digital con el dedo."""
    try:
        from fpdf import FPDF
        fecha_str = str(datetime.date.today())
        slug_cliente = "".join(c if c.isalnum() else "_" for c in nombre_cliente)[:25]
        nombre_pdf = f"Contrato_{slug_cliente}_{int(time.time())}.pdf"
        ruta_pdf = os.path.join("contratos_pdf", nombre_pdf)

        def limpiar_latin1(txt: str) -> str:
            reemplazos = {"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "•": "-", "€": "EUR"}
            for k, v in reemplazos.items():
                txt = txt.replace(k, v)
            return txt.encode('latin-1', 'ignore').decode('latin-1')

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # Cabecera Corporativa Ejecutiva
        pdf.set_fill_color(10, 14, 23)
        pdf.rect(0, 0, 210, 36, 'F')
        pdf.set_text_color(0, 229, 255)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(15, 10)
        pdf.cell(0, 8, limpiar_latin1(NOMBRE_AGENCIA.upper()), ln=True)
        pdf.set_text_color(220, 225, 235)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_x(15)
        pdf.cell(0, 6, limpiar_latin1(f"Documento Oficial — Fecha de Emision: {fecha_str}"), ln=True)

        pdf.ln(18)
        pdf.set_text_color(15, 20, 35)
        pdf.set_font("Helvetica", "B", 15)
        pdf.multi_cell(0, 9, limpiar_latin1(titulo_documento.upper()), align='C')
        pdf.ln(4)

        # Resumen de Partes y Monto
        pdf.set_fill_color(240, 245, 250)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 9, limpiar_latin1(f"  CLIENTE / CONTRATANTE: {nombre_cliente}"), ln=True, fill=True)
        pdf.cell(0, 9, limpiar_latin1(f"  REPRESENTANTE AGENCIA: {NOMBRE_JEFE} ({NOMBRE_AGENCIA})"), ln=True, fill=True)
        if float(monto_acordado_usd) > 0:
            pdf.cell(0, 9, limpiar_latin1(f"  VALOR TOTAL ACORDADO: USD {float(monto_acordado_usd):,.2f}"), ln=True, fill=True)
        pdf.ln(6)

        # Cuerpo de Cláusulas
        pdf.set_font("Helvetica", "", 11)
        for parrafo in cuerpo_clausulas.split("\n"):
            p_limpio = limpiar_latin1(parrafo.strip())
            if not p_limpio:
                pdf.ln(3)
                continue
            if p_limpio.isupper() or p_limpio.startswith("CLAUSULA") or p_limpio.startswith("CLÁUSULA") or p_limpio.startswith("1.") or p_limpio.startswith("2.") or p_limpio.startswith("3."):
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(0, 6.5, p_limpio)
                pdf.set_font("Helvetica", "", 11)
            else:
                pdf.multi_cell(0, 6.5, p_limpio)
            pdf.ln(2)

        # Bloque de Firmas Digitales
        pdf.ln(15)
        if pdf.get_y() > 235:
            pdf.add_page()
        y_firma = pdf.get_y() + 15
        pdf.set_draw_color(50, 60, 80)
        pdf.line(20, y_firma, 95, y_firma)
        pdf.line(115, y_firma, 190, y_firma)

        pdf.set_xy(20, y_firma + 3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(75, 5, limpiar_latin1(NOMBRE_JEFE), align='C')
        pdf.set_xy(115, y_firma + 3)
        pdf.cell(75, 5, limpiar_latin1(nombre_cliente), align='C')

        pdf.set_xy(20, y_firma + 8)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(75, 5, limpiar_latin1("Firma Autorizada Agencia"), align='C')
        pdf.set_xy(115, y_firma + 8)
        pdf.cell(75, 5, limpiar_latin1("Firma de Conformidad Cliente"), align='C')

        pdf.output(ruta_pdf)

        # 1. Enviar PDF directamente al Telegram de Luis
        if bot and ID_TELEGRAM_LUIS:
            try:
                with open(ruta_pdf, "rb") as doc_file:
                    bot.send_document(
                        ID_TELEGRAM_LUIS,
                        doc_file,
                        caption=f"📄 *{titulo_documento}*\n👤 *Cliente:* {nombre_cliente}\n✍️ _Listo para imprimir o firmar digitalmente en el HUD Web._",
                        parse_mode="Markdown"
                    )
            except Exception as e_tg:
                logger.warning(f"No se pudo adjuntar PDF en Telegram: {e_tg}")

        # 2. Subir respaldo a Google Drive si hay carpeta/credenciales
        info_drive = "Guardado localmente en el servidor"
        try:
            creds = autenticar_google()
            if creds:
                service_drive = build('drive', 'v3', credentials=creds)
                meta = {'name': nombre_pdf}
                if GOOGLE_DRIVE_FOLDER_ID:
                    meta['parents'] = [GOOGLE_DRIVE_FOLDER_ID]
                media = MediaFileUpload(ruta_pdf, mimetype='application/pdf')
                archivo_drive = service_drive.files().create(body=meta, media_body=media, fields='id, webViewLink').execute()
                info_drive = f"Subido a Google Drive (ID: `{archivo_drive.get('id')}`)"
        except Exception as e_drv:
            logger.warning(f"Nota Drive en contrato: {e_drv}")

        guardar_en_boveda_memoria(nombre_cliente, f"Contrato PDF generado ({nombre_pdf}): {titulo_documento} por USD {monto_acordado_usd}", "contratos")
        return (
            f"📄 *[CONTRATO / DOCUMENTO PDF GENERADO CON ÉXITO]*\n"
            f"• *Archivo:* `{nombre_pdf}`\n"
            f"• *Cliente:* {nombre_cliente}\n"
            f"• *Entrega:* Te lo acabo de enviar como PDF adjunto aquí en Telegram.\n"
            f"• *Respaldo:* {info_drive}\n"
            f"• *Firma Táctil:* Disponible en la pestaña 'Firma Digital' de tu App Web Tony Stark (Puerto {JARVIS_WEB_PORT})."
        )
    except Exception as e:
        return f"❌ Error generando contrato PDF: {str(e)}"

# =====================================================================
# MOTOR DE VOZ NEURONAL ROBÓTICA (XTTS LOCAL - PUERTO 8020)
# =====================================================================
def usuario_pidio_voz(texto: str) -> bool:
    t = texto.lower()
    triggers = [
        "con nota de voz", "en nota de voz", "por nota de voz",
        "con voz", "en audio", "por audio", "respóndeme hablando",
        "respondeme hablando", "háblame", "hablame", "/voz"
    ]
    return any(tr in t for tr in triggers)

def generar_audio_voz_jarvis(texto_respuesta: str) -> str:
    """Genera la voz de Jarvis usando el motor XTTS local en el puerto 8020."""
    import re
    
    try:
        # Limpiar símbolos Markdown y URLs para que el motor lea fluidamente
        texto_limpio = re.sub(r'[*_`#~>\[\]]', '', texto_respuesta)
        texto_limpio = re.sub(r'https?://\S+', 'enlace adjunto', texto_limpio)
        texto_limpio = texto_limpio[:1500].strip()
        if not texto_limpio:
            texto_limpio = "Orden ejecutada, jefe."

        ruta_salida = os.path.join("temp_audios", f"jarvis_tts_{int(time.time()*1000)}.wav")
        
        # Conexión directa a la API local de XTTS
        url = "http://localhost:8020/v1/audio/speech"
        payload = {
            "input": texto_limpio,
            "voice": "jarvis_listo.wav",
            "language": "es",
            "model": "tts-1"
        }
        
        response = requests.post(url, json=payload, timeout=120)
        if response.status_code == 200:
            with open(ruta_salida, 'wb') as f:
                f.write(response.content)
            return ruta_salida
        else:
            logger.error(f"Error del servidor de voz XTTS: {response.status_code}")
            return ""
    except Exception as e:
        logger.error(f"Falla de conexión con el motor XTTS local: {e}")
        return ""

# =====================================================================
# 5. CATÁLOGO MODULAR DE MICRO-HERRAMIENTAS (21 TOOLS)
# =====================================================================
CATALOGO_TOOLS = {
    "registrar_o_actualizar_proyecto": {
        "type": "function", "function": {
            "name": "registrar_o_actualizar_proyecto",
            "description": "Guarda un proyecto o cliente nuevo en Supabase con estado, monto acordado, monto cobrado y siguiente paso.",
            "parameters": {"type": "object", "properties": {"nombre_proyecto": {"type": "string"}, "cliente": {"type": "string"}, "estado": {"type": "string", "enum": ["1_Pagado_En_Curso", "2_Reunion_Critica", "3_Clonar_Ganancia_Rapida", "4_Prospecto_Demo", "Completado"]}, "prioridad": {"type": "integer"}, "monto_acordado": {"type": "number"}, "monto_cobrado": {"type": "number"}, "fecha_entrega": {"type": "string"}, "siguiente_paso": {"type": "string"}, "notas": {"type": "string"}}, "required": ["nombre_proyecto", "cliente", "estado", "prioridad", "siguiente_paso"]}
        }
    },
    "consultar_tablero_proyectos": {
        "type": "function", "function": {"name": "consultar_tablero_proyectos", "description": "Consulta todos los proyectos activos en Supabase y plata en la calle.", "parameters": {"type": "object", "properties": {}}}
    },
    "agregar_tarea_agenda": {
        "type": "function", "function": {
            "name": "agregar_tarea_agenda",
            "description": "Anota una tarea o demo pendiente en Supabase respetando los tiempos que indique el jefe.",
            "parameters": {"type": "object", "properties": {"titulo": {"type": "string"}, "cliente_o_proyecto": {"type": "string"}, "fecha_limite": {"type": "string"}, "nivel_prioridad": {"type": "integer"}, "descripcion": {"type": "string"}}, "required": ["titulo", "cliente_o_proyecto", "nivel_prioridad"]}
        }
    },
    "consultar_agenda_priorizada": {
        "type": "function", "function": {"name": "consultar_agenda_priorizada", "description": "Muestra la lista de tareas ordenadas por prioridad.", "parameters": {"type": "object", "properties": {"estado": {"type": "string", "enum": ["pendiente", "completada", "todas"]}}}}
    },
    "cambiar_estado_tarea": {
        "type": "function", "function": {
            "name": "cambiar_estado_tarea",
            "description": "Marca una tarea como completada o cambia su horario.",
            "parameters": {"type": "object", "properties": {"id_tarea": {"type": "integer"}, "nuevo_estado": {"type": "string", "enum": ["completada", "pendiente"]}, "nueva_fecha": {"type": "string"}}, "required": ["id_tarea", "nuevo_estado"]}
        }
    },
    "registrar_movimiento_financiero": {
        "type": "function", "function": {
            "name": "registrar_movimiento_financiero",
            "description": "Registra en Supabase un 'cobro', 'gasto' o 'inversion' indicando la cuenta (ej: Binance, Zelle).",
            "parameters": {"type": "object", "properties": {"tipo": {"type": "string", "enum": ["cobro", "gasto", "inversion"]}, "monto": {"type": "number"}, "concepto": {"type": "string"}, "cliente_o_proyecto": {"type": "string"}, "metodo_pago": {"type": "string"}, "moneda": {"type": "string"}}, "required": ["tipo", "monto", "concepto"]}
        }
    },
    "consultar_reporte_financiero": {
        "type": "function", "function": {"name": "consultar_reporte_financiero", "description": "Consulta el balance financiero: cobros, gastos, saldo en cuentas y plata en la calle.", "parameters": {"type": "object", "properties": {"filtro_cliente": {"type": "string"}}}}
    },
    "guardar_en_boveda_memoria": {
        "type": "function", "function": {
            "name": "guardar_en_boveda_memoria",
            "description": "Guarda cualquier apunte, acuerdo o dato clave en Supabase.",
            "parameters": {"type": "object", "properties": {"cliente_o_tema": {"type": "string"}, "detalle_completo": {"type": "string"}, "categoria": {"type": "string"}}, "required": ["cliente_o_tema", "detalle_completo"]}
        }
    },
    "buscar_en_boveda_memoria": {
        "type": "function", "function": {"name": "buscar_en_boveda_memoria", "description": "Busca en Supabase acuerdos o datos guardados.", "parameters": {"type": "object", "properties": {"palabra_clave": {"type": "string"}}}}
    },
    "generar_plan_y_prompt_gemini": {
        "type": "function", "function": {
            "name": "generar_plan_y_prompt_gemini",
            "description": "Genera el Prompt Maestro para construir un proyecto con Gemini inyectando las skills obligatorias.",
            "parameters": {"type": "object", "properties": {"idea_o_proyecto": {"type": "string"}, "cliente_o_nicho": {"type": "string"}, "requerimientos_clave": {"type": "string"}}, "required": ["idea_o_proyecto", "cliente_o_nicho", "requerimientos_clave"]}
        }
    },
    "configurar_hora_despertador": {
        "type": "function", "function": {"name": "configurar_hora_despertador", "description": "Cambia la hora del despertador diario (formato HH:MM).", "parameters": {"type": "object", "properties": {"hora_24h": {"type": "string"}}, "required": ["hora_24h"]}}
    },
    "buscar_y_leer_internet": {
        "type": "function", "function": {"name": "buscar_y_leer_internet", "description": "Busca información, ejemplos o referencias en vivo en internet.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_resultados": {"type": "integer"}}, "required": ["query"]}}
    },
    "crear_reunion_google_meet": {
        "type": "function", "function": {"name": "crear_reunion_google_meet", "description": "Agenda un evento o reunión en Google Calendar en la fecha/hora ISO indicada (ej: 2026-10-23T08:30:00).", "parameters": {"type": "object", "properties": {"titulo": {"type": "string"}, "fecha_hora_iso": {"type": "string"}, "duracion_minutos": {"type": "integer"}, "descripcion": {"type": "string"}}, "required": ["titulo", "fecha_hora_iso"]}}
    },
    "consultar_eventos_google_calendar": {
        "type": "function", "function": {"name": "consultar_eventos_google_calendar", "description": "Consulta los eventos agendados en Google Calendar.", "parameters": {"type": "object", "properties": {"dias_adelante": {"type": "integer"}}}}
    },
    "enviar_correo_resend": {
        "type": "function", "function": {"name": "enviar_correo_resend", "description": "Envía un correo electrónico oficial mediante Resend.", "parameters": {"type": "object", "properties": {"destinatario": {"type": "string"}, "asunto": {"type": "string"}, "cuerpo_mensaje": {"type": "string"}}, "required": ["destinatario", "asunto", "cuerpo_mensaje"]}}
    },
    "enviar_mensaje_whatsapp_oficial": {
        "type": "function", "function": {"name": "enviar_mensaje_whatsapp_oficial", "description": "Envía un WhatsApp oficial.", "parameters": {"type": "object", "properties": {"telefono_destino": {"type": "string"}, "mensaje": {"type": "string"}}, "required": ["telefono_destino", "mensaje"]}}
    },
    "buscar_archivo_google_drive": {
        "type": "function", "function": {
            "name": "buscar_archivo_google_drive",
            "description": "Busca un archivo o Google Sheet en Google Drive por su nombre y devuelve su ID.",
            "parameters": {"type": "object", "properties": {"nombre_archivo": {"type": "string"}}, "required": ["nombre_archivo"]}
        }
    },
    "gestionar_google_sheets": {
        "type": "function", "function": {
            "name": "gestionar_google_sheets",
            "description": "Lee o agrega filas en un archivo de Google Sheets usando su spreadsheet_id.",
            "parameters": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["leer", "escribir"]}, "spreadsheet_id": {"type": "string"}, "rango": {"type": "string"}, "valores_json": {"type": "string"}}, "required": ["accion", "spreadsheet_id", "rango"]}
        }
    },
    "extraer_datos_instagram": {
        "type": "function", "function": {
            "name": "extraer_datos_instagram",
            "description": "Extrae publicaciones de una cuenta de Instagram o todos los comentarios de un post/shortcode filtrando por palabra clave.",
            "parameters": {"type": "object", "properties": {"usuario_o_shortcode": {"type": "string"}, "palabra_clave_filtro": {"type": "string"}}, "required": ["usuario_o_shortcode"]}
        }
    },
    "scraping_web_profundo": {
        "type": "function", "function": {
            "name": "scraping_web_profundo",
            "description": "Hace web scraping profundo de una URL para extraer su información o buscar un dato específico (aguja en un pajar).",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "aguja_a_buscar": {"type": "string"}}, "required": ["url"]}
        }
    },
    "generar_contrato_o_documento_formal": {
        "type": "function", "function": {
            "name": "generar_contrato_o_documento_formal",
            "description": "Redacta y genera un contrato o presupuesto formal en PDF listo para imprimir o firmar digitalmente, lo envía por Telegram y lo sube a Google Drive.",
            "parameters": {"type": "object", "properties": {"titulo_documento": {"type": "string"}, "nombre_cliente": {"type": "string"}, "cuerpo_clausulas": {"type": "string"}, "monto_acordado_usd": {"type": "number"}}, "required": ["titulo_documento", "nombre_cliente", "cuerpo_clausulas"]}
        }
    }
}

# =====================================================================
# 6. CEREBRO JARVIS CON MICRO-ENRUTADOR INTELIGENTE (AHORRO DE TOKENS)
# =====================================================================
class CerebroJarvis:
    def __init__(self):
        self.system_prompt = f"""[DIRECTIVA DE IDENTIDAD SUPREMA]
NO eres Kiro. Eres JARVIS: Jefe de Gabinete, CFO y Arquitecto de Sistemas de {NOMBRE_JEFE} en {NOMBRE_AGENCIA}.
Fecha y hora actual del servidor: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} ({platform.system()}).
Conexión a Supabase ({SUPABASE_URL}): ACTIVA.
Conexión a Google Calendar, Drive, Sheets y Resend: ACTIVA EN VIVO.

REGLAS INNEGOCIABLES DE AUTORIDAD Y FORMATO:
1. PROHIBIDO USAR TABLAS MARKDOWN: Jamás uses tablas con barras verticales en tus respuestas porque Telegram las rompe. Presenta todo en listas limpias con viñetas (•) y emojis.
2. PROHIBIDO RESUMIR O RECORTAR DATOS: Cuando {NOMBRE_JEFE} pida un reporte de proyectos, tareas o memoria, muéstrale toda la información completa y clara, sin abreviar palabras ni omitir detalles.
3. EL JEFE DICTA LOS TIEMPOS: Jamás inventes fechas de entrega ni le impongas a {NOMBRE_JEFE} qué día debe hacer una tarea. Si él no especifica fecha o día, regístralo como "Cuando el jefe indique". Solo agenda horas/días específicos cuando él te lo ordene explícitamente.
4. ACCIÓN CON HERRAMIENTAS:
   - Reuniones / Horarios: Usa 'crear_reunion_google_meet' o 'consultar_eventos_google_calendar'.
   - Drive / Sheets: Usa 'buscar_archivo_google_drive' y 'gestionar_google_sheets'.
   - Búsquedas web / Referencias / Scraping: Usa 'buscar_y_leer_internet', 'scraping_web_profundo' o 'extraer_datos_instagram'.
   - Contratos / PDFs: Usa 'generar_contrato_o_documento_formal'.
   - Correos: Usa 'enviar_correo_resend'."""
        self.historial = []

    def seleccionar_micro_herramientas(self, texto: str) -> list:
        t = texto.lower()
        if t.startswith("/chat"):
            return []

        seleccion = set()

        kw_finanzas = ["cobré", "cobre", "cobro", "pagó", "pago", "pagaron", "abono", "abonó", "gasté", "gaste", "gasto", "invertí", "inverti", "inversión", "inversion", "finanzas", "balance", "plata", "dinero", "debe", "calle", "binance", "zelle", "efectivo", "banco", "cuenta", "cuánto", "cuanto", "caja", "dólares"]
        if any(p in t for p in kw_finanzas):
            seleccion.update(["registrar_movimiento_financiero", "consultar_reporte_financiero", "consultar_tablero_proyectos"])

        kw_operaciones = ["anota", "agrega", "agenda", "tarea", "pendiente", "prioridad", "proyecto", "cliente", "concreté", "cerré", "demo", "aplicación", "web", "página", "ferretería", "carros", "agencia", "iglesia", "clonar", "procrastinador", "informe", "reporte", "resumen", "estado", "qué tenemos", "qué tengo", "qué hay", "hoy", "recuerda", "olvidé", "acuerdo", "quedamos", "bóveda", "memoria", "supabase", "terminé", "semana", "/hacer"]
        if any(p in t for p in kw_operaciones):
            seleccion.update(["agregar_tarea_agenda", "consultar_agenda_priorizada", "cambiar_estado_tarea", "registrar_o_actualizar_proyecto", "consultar_tablero_proyectos", "guardar_en_boveda_memoria", "buscar_en_boveda_memoria", "consultar_reporte_financiero"])

        kw_drive = ["drive", "hoja de cálculo", "hoja de calculo", "sheet", "sheets", "excel", "tabla", "crm", "archivo", "base de datos"]
        if any(p in t for p in kw_drive):
            seleccion.update(["buscar_archivo_google_drive", "gestionar_google_sheets"])

        kw_calendar = ["meet", "calendario", "calendar", "reunión", "reunion", "agéndame", "agendame", "cita", "evento", "horario", "jueves", "lunes", "martes", "miércoles", "viernes", "mañana"]
        if any(p in t for p in kw_calendar):
            seleccion.update(["crear_reunion_google_meet", "consultar_eventos_google_calendar", "agregar_tarea_agenda"])

        kw_web_scraping = ["internet", "busca", "búscame", "buscame", "web", "investiga", "averigua", "ejemplo", "referencia", "e-commerce", "scraping", "escrutar", "aguja", "pajar", "url", "http", "instagram", "ig", "comentarios", "publicaciones", "feed"]
        if any(p in t for p in kw_web_scraping):
            seleccion.update(["buscar_y_leer_internet", "scraping_web_profundo", "extraer_datos_instagram"])

        kw_contratos = ["contrato", "pdf", "documento formal", "acuerdo legal", "propuesta formal", "presupuesto pdf", "firmar", "firma"]
        if any(p in t for p in kw_contratos):
            seleccion.add("generar_contrato_o_documento_formal")

        if any(p in t for p in ["prompt", "etapa", "gemini", "arquitectura"]):
            seleccion.add("generar_plan_y_prompt_gemini")
        if any(p in t for p in ["despertador", "despiértame", "alarma"]):
            seleccion.add("configurar_hora_despertador")
        if any(p in t for p in ["correo", "email", "resend", "escríbele", "envía", "enviar"]):
            seleccion.add("enviar_correo_resend")
        if any(p in t for p in ["whatsapp", "mensaje a"]):
            seleccion.add("enviar_mensaje_whatsapp_oficial")

        return [CATALOGO_TOOLS[nombre] for nombre in seleccion if nombre in CATALOGO_TOOLS]

    def transcribir_audio(self, ruta: str) -> str:
        if not GROQ_API_KEY:
            return "Falta GROQ_API_KEY."
        try:
            with open(ruta, "rb") as f:
                res = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": (os.path.basename(ruta), f, "audio/ogg")},
                    data={"model": MODELO_AUDIO, "response_format": "json", "language": "es"},
                    timeout=30
                )
                res.raise_for_status()
                return res.json().get("text", "")
        except Exception as e:
            return f"Error audio: {e}"

    def procesar_video_multimodal(self, ruta_video: str, caption_usuario: str = "") -> str:
        if not client_gemini:
            return "Falta GEMINI_API_KEY."
        try:
            video_file = client_gemini.files.upload(file=ruta_video)
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = client_gemini.files.get(name=video_file.name)
            instruccion = caption_usuario.strip() if caption_usuario else f"Analiza este video para {NOMBRE_AGENCIA}."
            prompt = f"{NOMBRE_JEFE} pide: {instruccion}\nInforme ejecutivo en viñetas sin usar tablas."
            try:
                response = client_gemini.models.generate_content(model='gemini-2.5-flash', contents=[video_file, prompt])
            except Exception:
                response = client_gemini.models.generate_content(model='gemini-1.5-pro', contents=[video_file, prompt])
            texto = response.text or "Sin respuesta."
            try:
                client_gemini.files.delete(name=video_file.name)
            except Exception:
                pass
            guardar_en_boveda_memoria("Análisis de Video", f"{instruccion} - {texto[:800]}", "analisis_video")
            return f"🎬 *[VIDEO ANALIZADO]*\n\n{texto}"
        except Exception as e:
            return f"Error video: {str(e)}"

    def _llamar_mwapi_chat(self, mensajes: list, tools_activas: list = None) -> dict:
        if not MWAPI_KEY:
            return {"exito": False, "error": "Falta MWAPI_KEY."}
        url_chat = f"{MWAPI_BASE_URL}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {MWAPI_KEY}", "Content-Type": "application/json"}
        mensajes_completos = [{"role": "system", "content": self.system_prompt}] + mensajes
        payload = {
            "model": MWAPI_MODEL,
            "max_tokens": 1500,
            "messages": mensajes_completos,
            "temperature": TEMPERATURA
        }
        if tools_activas:
            payload["tools"] = tools_activas

        for intento in range(3):
            try:
                res = requests.post(url_chat, headers=headers, json=payload, timeout=90)
                if res.status_code == 200:
                    data = res.json()
                    choice = (data.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    return {
                        "exito": True,
                        "texto": msg.get("content") or "",
                        "tool_calls": msg.get("tool_calls") or [],
                        "raw_message": msg
                    }
                elif res.status_code in [502, 503, 504] and intento < 2:
                    time.sleep(2)
                    continue
                else:
                    return {"exito": False, "error": f"Error MWAPI ({res.status_code}): {res.text[:250]}"}
            except Exception as e:
                if intento < 2:
                    time.sleep(2)
                    continue
                return {"exito": False, "error": f"Error conexión: {str(e)}"}

    def procesar(self, instruccion: str) -> str:
        tools_seleccionadas = self.seleccionar_micro_herramientas(instruccion)
        num_tools = len(tools_seleccionadas)

        with historial_lock:
            if len(self.historial) > LIMITE_MEMORIA_CORTA:
                self.historial = self.historial[-LIMITE_MEMORIA_CORTA:]
            mensajes_sesion = list(self.historial)
            mensajes_sesion.append({"role": "user", "content": instruccion})

        etiqueta_modo = f"⚡ Jarvis + Supabase/Drive ({num_tools} tools)" if num_tools > 0 else "💬 Jarvis (Modo Ligero 0 tools)"
        salidas_ejecutadas = []

        for _ in range(5):
            respuesta = self._llamar_mwapi_chat(mensajes_sesion, tools_activas=tools_seleccionadas)
            if not respuesta["exito"]:
                if salidas_ejecutadas:
                    return f"[{etiqueta_modo}]\n\n" + "\n\n".join(salidas_ejecutadas)
                return respuesta["error"]

            tool_calls = respuesta.get("tool_calls", [])
            if tools_seleccionadas and tool_calls:
                mensajes_sesion.append(respuesta["raw_message"])
                for tc in tool_calls:
                    tc_id = tc.get("id")
                    fn_obj = tc.get("function") or {}
                    nombre_fn = fn_obj.get("name")
                    raw_args = fn_obj.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}
                    fn = globals().get(nombre_fn)
                    try:
                        res_ejecucion = fn(**args) if fn else f"❌ Función '{nombre_fn}' no encontrada."
                    except Exception as e:
                        res_ejecucion = f"❌ Error '{nombre_fn}': {str(e)}"
                    salidas_ejecutadas.append(str(res_ejecucion))
                    mensajes_sesion.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": str(res_ejecucion)[:3500]
                    })
            else:
                texto_salida = respuesta.get("texto", "").strip()
                if not texto_salida and salidas_ejecutadas:
                    texto_salida = "\n\n".join(salidas_ejecutadas)
                elif not texto_salida:
                    texto_salida = "✅ Listo, jefe."
                with historial_lock:
                    self.historial.append({"role": "user", "content": instruccion})
                    self.historial.append({"role": "assistant", "content": texto_salida})
                return f"[{etiqueta_modo}]\n\n{texto_salida}"

        texto_cierre = "\n\n".join(salidas_ejecutadas) if salidas_ejecutadas else "✅ Completado."
        with historial_lock:
            self.historial.append({"role": "user", "content": instruccion})
            self.historial.append({"role": "assistant", "content": texto_cierre})
        return f"[{etiqueta_modo}]\n\n{texto_cierre}"


# =====================================================================
# 7. DESPERTADOR MATUTINO CON RESUMEN DE AGENDA, PROYECTOS Y FINANZAS
# =====================================================================
def hilo_despertador_ejecutivo():
    logger.info("⏰ Vigilante iniciado.")
    while True:
        try:
            ahora = datetime.datetime.now()
            hora_actual = ahora.strftime("%H:%M")
            fecha_hoy = str(ahora.date())
            with db_lock:
                conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
                c = conn.cursor()
                c.execute("SELECT valor FROM configuracion WHERE clave = 'hora_despertador'")
                r_hora = c.fetchone()
                hora_obj = r_hora[0] if r_hora else HORA_DESPERTADOR_DEFAULT
                c.execute("SELECT valor FROM configuracion WHERE clave = 'ultimo_briefing_fecha'")
                r_fec = c.fetchone()
                ult_fecha = r_fec[0] if r_fec else ""
                conn.close()

            if hora_actual == hora_obj and ult_fecha != fecha_hoy:
                with db_lock:
                    conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
                    c = conn.cursor()
                    c.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ultimo_briefing_fecha', ?)", (fecha_hoy,))
                    conn.commit()
                    conn.close()
                mensaje = (
                    f"☀️ *REPORTE MATUTINO ({hora_actual})*\n"
                    f"📅 *Fecha:* {fecha_hoy}\n\n"
                    f"{consultar_agenda_priorizada('pendiente')}\n\n"
                    f"{consultar_tablero_proyectos()}\n\n"
                    f"{consultar_reporte_financiero()}\n\n"
                    f"💡 _Mándame un audio si cobraste algo o completaste una tarea._"
                )
                if bot and ID_TELEGRAM_LUIS:
                    for i in range(0, len(mensaje), 4000):
                        bot.send_message(ID_TELEGRAM_LUIS, mensaje[i:i+4000], parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error despertador: {e}")
        time.sleep(30)


# =====================================================================
# 8. SERVIDOR TELEGRAM, NOTAS DE VOZ ON-DEMAND Y COMANDOS (0 TOKENS)
# =====================================================================
def enviar_respuesta_segura(chat_id: int, texto: str):
    for i in range(0, len(texto), 4000):
        trozo = texto[i:i+4000]
        try:
            bot.send_message(chat_id, trozo, parse_mode="Markdown")
        except Exception:
            bot.send_message(chat_id, trozo)

def procesar_tarea_en_hilo(chat_id, texto_o_voz, es_audio=False, ruta_audio=None):
    try:
        if es_audio:
            texto = jarvis.transcribir_audio(ruta_audio)
            enviar_respuesta_segura(chat_id, f"🎙️ *Escuché:* \"_{texto}_\"")
            res = jarvis.procesar(texto)
            if ruta_audio and os.path.exists(ruta_audio):
                os.remove(ruta_audio)
        else:
            texto = texto_o_voz
            res = jarvis.procesar(texto)

        enviar_respuesta_segura(chat_id, res)

        if usuario_pidio_voz(texto):
            ruta_tts = generar_audio_voz_jarvis(res)
            if ruta_tts and os.path.exists(ruta_tts):
                with open(ruta_tts, "rb") as audio_f:
                    bot.send_voice(chat_id, audio_f)
                os.remove(ruta_tts)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")

def procesar_video_en_hilo(chat_id, ruta_vid, caption):
    try:
        enviar_respuesta_segura(chat_id, "📥 *Analizando video en segundo plano...*")
        res = jarvis.procesar_video_multimodal(ruta_vid, caption)
        enviar_respuesta_segura(chat_id, res)
        if ruta_vid and os.path.exists(ruta_vid):
            os.remove(ruta_vid)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error video: {str(e)}")


if __name__ == "__main__":
    print("=======================================================================")
    print(f"🚀 INICIANDO JARVIS CFO & JEFE DE GABINETE ({MWAPI_MODEL})")
    print(f"☁️ SUPABASE CONECTADO: {'SÍ ✅' if supabase_activo() else 'MODO LOCAL ⚠️'}")
    print("=======================================================================")
    autenticar_google()
    jarvis = CerebroJarvis()

    threading.Thread(target=hilo_despertador_ejecutivo, daemon=True).start()

    @bot.message_handler(commands=['agenda', 'tareas', 'hoy'])
    def cmd_agenda(m):
        if m.chat.id == ID_TELEGRAM_LUIS:
            enviar_respuesta_segura(m.chat.id, consultar_agenda_priorizada("pendiente"))

    @bot.message_handler(commands=['proyectos', 'cartera'])
    def cmd_proyectos(m):
        if m.chat.id == ID_TELEGRAM_LUIS:
            enviar_respuesta_segura(m.chat.id, consultar_tablero_proyectos())

    @bot.message_handler(commands=['finanzas', 'caja', 'balance'])
    def cmd_finanzas(m):
        if m.chat.id == ID_TELEGRAM_LUIS:
            enviar_respuesta_segura(m.chat.id, consultar_reporte_financiero())

    @bot.message_handler(commands=['boveda', 'memoria'])
    def cmd_boveda(m):
        if m.chat.id == ID_TELEGRAM_LUIS:
            termino = m.text.split(maxsplit=1)[1] if len(m.text.split()) > 1 else ""
            enviar_respuesta_segura(m.chat.id, buscar_en_boveda_memoria(termino))

    @bot.message_handler(content_types=['text'])
    def txt(m):
        if m.chat.id == ID_TELEGRAM_LUIS:
            threading.Thread(target=procesar_tarea_en_hilo, args=(m.chat.id, m.text), daemon=True).start()

    @bot.message_handler(content_types=['voice'])
    def voz(m):
        if m.chat.id == ID_TELEGRAM_LUIS:
            f_info = bot.get_file(m.voice.file_id)
            ruta = os.path.join("temp_audios", f"voz_{time.time()}.ogg")
            with open(ruta, "wb") as f:
                f.write(bot.download_file(f_info.file_path))
            threading.Thread(target=procesar_tarea_en_hilo, args=(m.chat.id, "", True, ruta), daemon=True).start()

    @bot.message_handler(content_types=['video'])
    def video_multimodal(m):
        if m.chat.id == ID_TELEGRAM_LUIS:
            f_info = bot.get_file(m.video.file_id)
            ruta_vid = os.path.join("temp_videos", f"video_{time.time()}.mp4")
            with open(ruta_vid, "wb") as f:
                f.write(bot.download_file(f_info.file_path))
            threading.Thread(target=procesar_video_en_hilo, args=(m.chat.id, ruta_vid, m.caption or ""), daemon=True).start()

    print("🤖 ¡JARVIS OPERATIVO CON MWAPI CLAUDE HAIKU 4.5, SUPABASE, DRIVE, VOZ Y PDF!\n")
    if bot:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)