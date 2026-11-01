import os
import sys
import re
import json
import base64
import sqlite3
import logging
import requests
import time
import threading
import telebot
import platform
import datetime
from zoneinfo import ZoneInfo
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from duckduckgo_search import DDGS

# SDK Oficial de Google para Análisis de Videos y Google Workspace
from google import genai
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
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

TZ_NAME = os.getenv("TZ_JARVIS", "America/Caracas")
try:
    ZONA_HORARIA = ZoneInfo(TZ_NAME)
except Exception:
    ZONA_HORARIA = datetime.timezone(datetime.timedelta(hours=-4))

def ahora_local() -> datetime.datetime:
    return datetime.datetime.now(ZONA_HORARIA)

def hoy_local_str() -> str:
    return ahora_local().strftime("%Y-%m-%d")

MWAPI_KEY = os.getenv("MWAPI_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
MWAPI_BASE_URL = os.getenv("MWAPI_BASE_URL", "https://api.mwapi.dev").rstrip("/")
MWAPI_MODEL = os.getenv("MWAPI_MODEL", "claude-haiku-4-5-20251001")

SUPABASE_URL = (
    os.getenv("SUPABASE_URL")
    or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    or "https://fmskxeqxbcklcjasefnv.supabase.co"
).rstrip("/")
SUPABASE_KEY = (
    os.getenv("SUPABASE_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or ""
)
DATABASE_URL = os.getenv("DATABASE_URL", "")

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
JARVIS_WEB_PORT = int(os.getenv("JARVIS_WEB_PORT", "3000"))
NOMBRE_AGENCIA = os.getenv("NOMBRE_AGENCIA", "GuiporDI Soluciones")
NOMBRE_JEFE = os.getenv("NOMBRE_JEFE", "Luis Castillo")

MODELO_AUDIO = "whisper-large-v3"
TEMPERATURA = 0.2
LIMITE_MEMORIA_CORTA = 14
ARCHIVO_DB_LOCAL = "jarvis_respaldo_local.db"
RUTA_ULTIMA_FIRMA = os.path.join("contratos_pdf", "ultima_firma_cliente.png")

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
# 2. CONECTOR UNIFICADO SUPABASE (REST / POSTGRES) + RESPALDO SQLITE
# =====================================================================
def supabase_rest_activo() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)

def base_datos_activa() -> bool:
    return supabase_rest_activo() or bool(DATABASE_URL)

def _sb_headers(prefer: str = "return=representation") -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer
    }

def sb_rest_query(method: str, tabla: str, query_params: str = "", payload: dict = None):
    """Ejecuta operaciones contra las tablas jarvis_* en Supabase vía REST API."""
    if not supabase_rest_activo():
        return None
    url = f"{SUPABASE_URL}/rest/v1/{tabla}"
    if query_params:
        url = f"{url}?{query_params}"
    try:
        res = requests.request(
            method=method.upper(),
            url=url,
            headers=_sb_headers(),
            json=payload,
            timeout=15
        )
        if res.status_code in [200, 201]:
            return res.json() if res.text.strip() else []
        elif res.status_code == 204:
            return []
        else:
            logger.warning(f"Supabase REST [{method} {tabla}] ({res.status_code}): {res.text[:200]}")
            return None
    except Exception as e:
        logger.warning(f"Fallo conexión Supabase REST ({tabla}): {e}")
        return None

def ejecutar_consulta_postgres(query: str, params: tuple = None, fetch: bool = False, fetchall: bool = True):
    """Respaldo por conexión directa PostgreSQL si no hay SUPABASE_KEY pero sí DATABASE_URL."""
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, params)
        resultado = None
        if fetch:
            resultado = cursor.fetchall() if fetchall else cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        return resultado
    except Exception as e:
        logger.warning(f"Fallo de red hacia Postgres DB: {str(e)}")
        return None

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
# 3. HERRAMIENTAS DE PROYECTOS, TAREAS, FINANZAS Y MEMORIA (SUPABASE + LOCAL)
# =====================================================================
def _obtener_proyectos_lista() -> tuple[list, str]:
    """Devuelve (lista_proyectos, origen_texto) desde Supabase o SQLite local."""
    if supabase_rest_activo():
        res = sb_rest_query("GET", "jarvis_proyectos", "select=*&order=prioridad.asc,id.asc")
        if res is not None:
            return res, "Supabase ☁️"

    if DATABASE_URL:
        res_pg = ejecutar_consulta_postgres("SELECT * FROM jarvis_proyectos ORDER BY prioridad ASC, id ASC;", fetch=True)
        if res_pg is not None:
            return [dict(r) for r in res_pg], "Postgres ☁️"

    filas = []
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
    return filas, "Base Local 💾"

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
    prio_int = max(1, min(4, int(prioridad or 1)))
    acordado_f = float(monto_acordado or 0.0)
    cobrado_f = float(monto_cobrado or 0.0)

    # Verificar si ya existe el proyecto para actualizarlo en lugar de duplicarlo
    proyectos_actuales, _ = _obtener_proyectos_lista()
    existente = None
    nom_low = nombre_proyecto.strip().lower()
    cli_low = cliente.strip().lower()
    for p in proyectos_actuales:
        p_nom = str(p.get("nombre_proyecto") or "").strip().lower()
        p_cli = str(p.get("cliente") or "").strip().lower()
        if p_nom == nom_low or (nom_low in p_nom and p_cli == cli_low):
            existente = p
            break

    if existente:
        nuevo_acordado = acordado_f if acordado_f > 0 else float(existente.get("monto_acordado") or 0.0)
        nuevo_cobrado = cobrado_f if cobrado_f > 0 else float(existente.get("monto_cobrado") or 0.0)
        nueva_meta = fecha_entrega if fecha_entrega != "Cuando el jefe indique" else (existente.get("fecha_entrega") or fecha_entrega)
        nuevo_paso = siguiente_paso or existente.get("siguiente_paso") or ""
        nuevas_notas = notas or existente.get("notas") or ""
        saldo_pendiente = max(0.0, nuevo_acordado - nuevo_cobrado)

        datos_update = {
            "nombre_proyecto": nombre_proyecto.strip(),
            "cliente": cliente.strip(),
            "estado": estado,
            "prioridad": prio_int,
            "monto_acordado": nuevo_acordado,
            "monto_cobrado": nuevo_cobrado,
            "fecha_entrega": nueva_meta,
            "siguiente_paso": nuevo_paso,
            "notas": nuevas_notas
        }

        actualizado_nube = False
        if supabase_rest_activo():
            res_up = sb_rest_query("PATCH", "jarvis_proyectos", f"id=eq.{existente['id']}", datos_update)
            actualizado_nube = res_up is not None

        with db_lock:
            conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
            c = conn.cursor()
            c.execute(
                """UPDATE jarvis_proyectos
                   SET estado=?, prioridad=?, monto_acordado=?, monto_cobrado=?, fecha_entrega=?, siguiente_paso=?, notas=?
                   WHERE id=? OR lower(nombre_proyecto)=?""",
                (estado, prio_int, nuevo_acordado, nuevo_cobrado, nueva_meta, nuevo_paso, nuevas_notas, existente["id"], nom_low)
            )
            conn.commit()
            conn.close()

        origen_lbl = "SUPABASE" if actualizado_nube else "LOCAL"
        return (
            f"🗂️ *[PROYECTO ACTUALIZADO EN {origen_lbl} — ID #{existente['id']}]*\n"
            f"• *Proyecto:* {nombre_proyecto} ({cliente})\n"
            f"• *Estado:* `{estado}` — *Meta:* {nueva_meta}\n"
            f"• *Finanzas:* Acordado USD {nuevo_acordado:,.2f} — Cobrado USD {nuevo_cobrado:,.2f} — *Por cobrar: USD {saldo_pendiente:,.2f}*\n"
            f"• *Siguiente paso:* {nuevo_paso}"
        )

    saldo_pendiente = max(0.0, acordado_f - cobrado_f)
    payload_nuevo = {
        "nombre_proyecto": nombre_proyecto.strip(),
        "cliente": cliente.strip(),
        "estado": estado,
        "prioridad": prio_int,
        "monto_acordado": acordado_f,
        "monto_cobrado": cobrado_f,
        "fecha_entrega": fecha_entrega,
        "siguiente_paso": siguiente_paso,
        "notas": notas
    }

    guardado_nube = False
    if supabase_rest_activo():
        res_ins = sb_rest_query("POST", "jarvis_proyectos", payload=payload_nuevo)
        guardado_nube = res_ins is not None

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO jarvis_proyectos (nombre_proyecto, cliente, estado, prioridad, monto_acordado, monto_cobrado, fecha_entrega, siguiente_paso, notas) VALUES (?,?,?,?,?,?,?,?,?)",
            (nombre_proyecto.strip(), cliente.strip(), estado, prio_int, acordado_f, cobrado_f, fecha_entrega, siguiente_paso, notas)
        )
        conn.commit()
        conn.close()

    origen_lbl = "SUPABASE" if guardado_nube else "LOCAL"
    return (
        f"🗂️ *[PROYECTO GUARDADO EN {origen_lbl}]*\n"
        f"• *Proyecto:* {nombre_proyecto} ({cliente})\n"
        f"• *Estado:* `{estado}` — *Meta:* {fecha_entrega}\n"
        f"• *Finanzas:* Acordado USD {acordado_f:,.2f} — Cobrado USD {cobrado_f:,.2f} — *Por cobrar: USD {saldo_pendiente:,.2f}*\n"
        f"• *Siguiente paso:* {siguiente_paso}"
    )

def consultar_tablero_proyectos() -> str:
    filas, origen = _obtener_proyectos_lista()
    if not filas:
        return "📭 No hay proyectos registrados todavía."

    total_acordado = 0.0
    total_cobrado = 0.0
    lineas = [f"🚀 *TABLERO EJECUTIVO DE PROYECTOS ({origen})*\n"]

    for p in filas:
        acordado = float(p.get("monto_acordado") or 0.0)
        cobrado = float(p.get("monto_cobrado") or 0.0)
        pendiente = max(0.0, acordado - cobrado)
        total_acordado += acordado
        total_cobrado += cobrado

        info_dinero = (
            f"💰 Cotizado: USD {acordado:,.2f} — Cobrado: USD {cobrado:,.2f} — *Resta: USD {pendiente:,.2f}*"
            if acordado > 0 else "💵 _Monto aún por definir_"
        )
        notas_txt = f"\n   • *Notas:* {p.get('notas')}" if p.get("notas") else ""
        lineas.append(
            f"🔹 *#{p.get('id')} - {p.get('nombre_proyecto')}* ({p.get('cliente')}) [P{p.get('prioridad', 1)}]\n"
            f"   • *Fase:* `{p.get('estado')}` — *Meta:* {p.get('fecha_entrega') or 'Cuando el jefe indique'}\n"
            f"   • {info_dinero}\n"
            f"   • *Acción:* {p.get('siguiente_paso') or 'Pendiente de definir'}{notas_txt}\n"
        )

    total_calle = max(0.0, total_acordado - total_cobrado)
    lineas.append(
        f"----------------------------------------\n"
        f"📊 *RESUMEN DE CARTERA:*\n"
        f"• *Total Cerrado:* USD {total_acordado:,.2f}\n"
        f"• *Ya Cobrado:* USD {total_cobrado:,.2f}\n"
        f"• *🔥 PLATA EN LA CALLE (Por Cobrar):* *USD {total_calle:,.2f}*"
    )
    return "\n".join(lineas)

def agregar_tarea_agenda(
    titulo: str,
    cliente_o_proyecto: str = "General",
    fecha_limite: str = "Cuando el jefe indique",
    nivel_prioridad: int = 1,
    descripcion: str = ""
) -> str:
    mapa = {
        1: "🔴 1 - CRÍTICA (Ya pagó / Entrega o Reunión Inminente)",
        2: "🟠 2 - ALTA (Clonación rápida / Proyecto en curso)",
        3: "🟡 3 - MEDIA (Demo para prospecto)",
        4: "🟢 4 - BAJA (Idea / Sin urgencia)"
    }
    prio = max(1, min(4, int(nivel_prioridad or 1)))
    etiqueta = mapa.get(prio, "🟠 2 - ALTA")

    payload_tarea = {
        "titulo": titulo.strip(),
        "cliente_o_proyecto": cliente_o_proyecto.strip(),
        "prioridad": prio,
        "etiqueta_prioridad": etiqueta,
        "fecha_limite": fecha_limite,
        "descripcion": descripcion,
        "estado": "pendiente"
    }

    t_id = None
    if supabase_rest_activo():
        res_sb = sb_rest_query("POST", "jarvis_tareas", payload=payload_tarea)
        if res_sb and isinstance(res_sb, list) and len(res_sb) > 0:
            t_id = res_sb[0].get("id")

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO jarvis_tareas (titulo, cliente_o_proyecto, prioridad, etiqueta_prioridad, fecha_limite, descripcion, estado) VALUES (?,?,?,?,?,?, 'pendiente')",
            (titulo.strip(), cliente_o_proyecto.strip(), prio, etiqueta, fecha_limite, descripcion)
        )
        if not t_id:
            t_id = c.lastrowid
        conn.commit()
        conn.close()

    return f"✅ *[TAREA #{t_id} ANOTADA EN SUPABASE]*: '{titulo}' ({etiqueta}) — Tiempo: {fecha_limite}."

def consultar_agenda_priorizada(estado: str = "pendiente") -> str:
    filas = []
    origen = "Supabase ☁️" if supabase_rest_activo() else "Base Local 💾"

    if supabase_rest_activo():
        filtro = "select=*&order=prioridad.asc,id.asc" if estado == "todas" else f"select=*&estado=eq.{estado}&order=prioridad.asc,id.asc"
        res_sb = sb_rest_query("GET", "jarvis_tareas", filtro)
        if res_sb is not None:
            filas = res_sb

    if not filas and not supabase_rest_activo():
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
    estado_clean = nuevo_estado.lower().strip()
    datos_patch = {"estado": estado_clean}
    if nueva_fecha:
        datos_patch["fecha_limite"] = nueva_fecha

    if supabase_rest_activo():
        sb_rest_query("PATCH", "jarvis_tareas", f"id=eq.{int(id_tarea)}", datos_patch)

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        if nueva_fecha:
            c.execute("UPDATE jarvis_tareas SET estado = ?, fecha_limite = ? WHERE id = ?", (estado_clean, nueva_fecha, int(id_tarea)))
        else:
            c.execute("UPDATE jarvis_tareas SET estado = ? WHERE id = ?", (estado_clean, int(id_tarea)))
        conn.commit()
        conn.close()
    return f"✅ Tarea #{id_tarea} marcada como *{estado_clean.upper()}* en Supabase."

def registrar_movimiento_financiero(
    tipo: str,
    monto: float,
    concepto: str,
    cliente_o_proyecto: str = "Agencia",
    metodo_pago: str = "General",
    moneda: str = "USD"
) -> str:
    tipo_limpio = tipo.lower().strip()
    if tipo_limpio not in ["cobro", "gasto", "inversion"]:
        tipo_limpio = "gasto" if "gast" in tipo_limpio else ("inversion" if "inver" in tipo_limpio else "cobro")

    icono = "💵" if tipo_limpio == "cobro" else ("💸" if tipo_limpio == "gasto" else "🚀")
    fecha_hoy = hoy_local_str()
    monto_f = float(monto or 0.0)
    metodo_clean = (metodo_pago or "General").strip()
    moneda_clean = (moneda or "USD").upper().strip()

    payload_fin = {
        "tipo": tipo_limpio,
        "monto": monto_f,
        "moneda": moneda_clean,
        "concepto": concepto.strip(),
        "cliente_o_proyecto": cliente_o_proyecto.strip(),
        "metodo_pago": metodo_clean,
        "fecha": fecha_hoy
    }

    en_nube = False
    if supabase_rest_activo():
        res_sb = sb_rest_query("POST", "jarvis_finanzas", payload=payload_fin)
        en_nube = res_sb is not None

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO jarvis_finanzas (tipo, monto, moneda, concepto, cliente_o_proyecto, metodo_pago, fecha) VALUES (?,?,?,?,?,?,?)",
            (tipo_limpio, monto_f, moneda_clean, concepto.strip(), cliente_o_proyecto.strip(), metodo_clean, fecha_hoy)
        )
        conn.commit()
        conn.close()

    origen_lbl = "SUPABASE" if en_nube else "LOCAL"
    return (
        f"{icono} *[FINANZAS {origen_lbl} - {tipo_limpio.upper()} REGISTRADO]*\n"
        f"• *Monto:* USD {monto_f:,.2f} ({moneda_clean})\n"
        f"• *Cuenta/Método:* {metodo_clean}\n"
        f"• *Concepto:* {concepto} ({cliente_o_proyecto})\n"
        f"• *Fecha:* {fecha_hoy}"
    )

def consultar_reporte_financiero(filtro_cliente: str = "") -> str:
    filas = []
    origen = "Supabase ☁️" if supabase_rest_activo() else "Base Local 💾"

    if supabase_rest_activo():
        res_sb = sb_rest_query("GET", "jarvis_finanzas", "select=*&order=id.desc&limit=100")
        if res_sb is not None:
            filas = res_sb

    if not filas and not supabase_rest_activo():
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

    # Calcular Plata en la Calle real desde jarvis_proyectos
    proyectos_actuales, _ = _obtener_proyectos_lista()
    plata_en_la_calle = sum(
        max(0.0, float(p.get("monto_acordado") or 0.0) - float(p.get("monto_cobrado") or 0.0))
        for p in proyectos_actuales
    )

    if not filas and plata_en_la_calle == 0:
        return "📊 Aún no hay movimientos financieros registrados."

    if filtro_cliente:
        f_low = filtro_cliente.lower()
        filas = [
            x for x in filas
            if f_low in str(x.get("cliente_o_proyecto", "")).lower()
            or f_low in str(x.get("concepto", "")).lower()
            or f_low in str(x.get("metodo_pago", "")).lower()
        ]

    total_cobros = sum(float(x.get("monto") or 0.0) for x in filas if str(x.get("tipo", "")).lower() == "cobro")
    total_gastos = sum(float(x.get("monto") or 0.0) for x in filas if str(x.get("tipo", "")).lower() == "gasto")
    total_inversiones = sum(float(x.get("monto") or 0.0) for x in filas if str(x.get("tipo", "")).lower() == "inversion")
    flujo_neto = total_cobros - (total_gastos + total_inversiones)

    saldos_por_cuenta = {}
    for x in filas:
        cuenta = (x.get("metodo_pago") or "General").strip().title()
        monto_m = float(x.get("monto") or 0.0)
        if str(x.get("tipo", "")).lower() == "cobro":
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

    if filas:
        lineas.append("📜 *Últimos Movimientos:*")
        for m in filas[:10]:
            t = str(m.get("tipo") or "cobro").lower()
            ico = "🟢 Cobro" if t == "cobro" else ("🔴 Gasto" if t == "gasto" else "🚀 Inversión")
            cta_txt = m.get("metodo_pago") or "General"
            lineas.append(
                f"• [{m.get('fecha') or hoy_local_str()}] {ico} ({cta_txt}): *USD {float(m.get('monto') or 0):,.2f}* — {m.get('concepto')} (_{m.get('cliente_o_proyecto')}_)"
            )

    return "\n".join(lineas)

def guardar_en_boveda_memoria(cliente_o_tema: str = "General", detalle_completo: str = "", categoria: str = "acuerdo_cliente", **kwargs) -> str:
    detalle_completo = detalle_completo or kwargs.get("palabra_clave", "Dato registrado")
    fecha_hoy = hoy_local_str()

    payload_mem = {
        "categoria": categoria.strip(),
        "cliente_o_tema": cliente_o_tema.strip(),
        "detalle_completo": detalle_completo.strip(),
        "fecha": fecha_hoy
    }

    en_nube = False
    if supabase_rest_activo():
        res_sb = sb_rest_query("POST", "jarvis_memoria", payload=payload_mem)
        en_nube = res_sb is not None

    with db_lock:
        conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO jarvis_memoria (categoria, cliente_o_tema, detalle_completo, fecha) VALUES (?,?,?,?)",
            (categoria.strip(), cliente_o_tema.strip(), detalle_completo.strip(), fecha_hoy)
        )
        conn.commit()
        conn.close()

    origen_lbl = "SUPABASE" if en_nube else "LOCAL"
    return f"🧠 *[GUARDADO EN BÓVEDA {origen_lbl}]*: '{cliente_o_tema}' -> {detalle_completo[:300]}"

def buscar_en_boveda_memoria(palabra_clave: str = "") -> str:
    resultados = []
    kw = (palabra_clave or "").strip()

    if supabase_rest_activo():
        res_sb = sb_rest_query("GET", "jarvis_memoria", "select=*&order=id.desc&limit=40")
        if res_sb is not None:
            for r in res_sb:
                if not kw or kw.lower() in str(r.get("cliente_o_tema", "")).lower() or kw.lower() in str(r.get("detalle_completo", "")).lower() or kw.lower() in str(r.get("categoria", "")).lower():
                    resultados.append(r)

    if not resultados and not supabase_rest_activo():
        with db_lock:
            conn = sqlite3.connect(ARCHIVO_DB_LOCAL)
            c = conn.cursor()
            if kw:
                like_q = f"%{kw}%"
                c.execute(
                    "SELECT fecha, categoria, cliente_o_tema, detalle_completo FROM jarvis_memoria WHERE cliente_o_tema LIKE ? OR detalle_completo LIKE ? ORDER BY id DESC LIMIT 25",
                    (like_q, like_q)
                )
            else:
                c.execute("SELECT fecha, categoria, cliente_o_tema, detalle_completo FROM jarvis_memoria ORDER BY id DESC LIMIT 25")
            for r in c.fetchall():
                resultados.append({"fecha": r[0], "categoria": r[1], "cliente_o_tema": r[2], "detalle_completo": r[3]})
            conn.close()

    if not resultados:
        return f"📭 No encontré apuntes previos sobre '{kw}' en la Bóveda."

    lineas = [f"🔍 *[RECUERDOS EN LA BÓVEDA PARA '{kw or 'TODO'}']*:\n"]
    for item in resultados[:25]:
        detalle = str(item.get("detalle_completo") or "")
        if detalle.startswith("data:image/png;base64,"):
            detalle = "[Firma Digital Táctil en Base64 lista para estampar en PDF]"
        lineas.append(f"• *[{item.get('fecha')}] {item.get('cliente_o_tema')}* ({item.get('categoria')}):\n  _{detalle}_")
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
        return f"⏰ *[DESPERTADOR CONFIGURADO]*: Te despertaré todos los días a las {hora_formateada} ({TZ_NAME}) con tu agenda, proyectos y finanzas."
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
            'start': {'dateTime': inicio.isoformat(), 'timeZone': TZ_NAME},
            'end': {'dateTime': fin.isoformat(), 'timeZone': TZ_NAME}
        }

        try:
            evento_meet = dict(evento_base)
            evento_meet['conferenceData'] = {
                'createRequest': {
                    'requestId': f"req_{int(time.time())}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            }
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
            f"• *Inicio ({TZ_NAME}):* {inicio.strftime('%Y-%m-%d %H:%M')}\n"
            f"• *Enlace Calendar:* {link_html}{extra_meet}"
        )
    except Exception as e:
        return f"❌ Error agendando en Google Calendar: {str(e)}"

def consultar_eventos_google_calendar(dias_adelante: int = 7) -> str:
    """Lee los próximos eventos del Google Calendar de Luis en zona horaria local."""
    try:
        creds = autenticar_google()
        if not creds:
            return "⚠️ No hay credenciales de Google activas."
        service = build('calendar', 'v3', credentials=creds)
        cal_id = _obtener_id_calendario_compartido(service)
        ahora_utc = datetime.datetime.now(datetime.timezone.utc)
        limite_utc = ahora_utc + datetime.timedelta(days=int(dias_adelante))

        eventos_res = service.events().list(
            calendarId=cal_id,
            timeMin=ahora_utc.isoformat(),
            timeMax=limite_utc.isoformat(),
            maxResults=15,
            singleEvents=True,
            orderBy='startTime'
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
        return (
            f"✅ *[CORREO ENVIADO CON ÉXITO]*\n• *Para:* {destinatario}\n• *Asunto:* {asunto}"
            if res.status_code in [200, 201] else f"❌ Error Resend ({res.status_code}): {res.text}"
        )
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
        nombre_limpio = nombre_archivo.strip().replace("'", "")
        if nombre_limpio:
            query = f"name contains '{nombre_limpio}' and trashed = false"
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
                spreadsheetId=spreadsheet_id,
                range=rango,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
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
            lineas_coincidentes = [
                ln.strip() for ln in texto_extraido.splitlines()
                if aguja_a_buscar.lower() in ln.lower() and len(ln.strip()) > 3
            ]
            extracto = "\n".join(f"• {l[:250]}" for l in lineas_coincidentes[:20]) or (
                "No se halló la palabra exacta, mostrando contenido general:\n" + texto_extraido[:2500]
            )
            return f"🕸️ *[SCRAPING PROFUNDO EN {url_limpia} — Filtro: '{aguja_a_buscar}']*\n\n{extracto}"

        return f"🕸️ *[SCRAPING PROFUNDO EN {url_limpia}]*\n\n{texto_extraido[:3200]}"
    except Exception as e:
        return f"❌ Error en Scraping profundo: {str(e)}"

def _obtener_ruta_firma_reciente() -> str:
    """Busca la última firma digital guardada en Supabase o en el archivo local para estamparla en el PDF."""
    if supabase_rest_activo():
        res = sb_rest_query(
            "GET",
            "jarvis_memoria",
            "select=*&categoria=eq.firma_digital&order=id.desc&limit=1"
        )
        if res and len(res) > 0:
            detalle = str(res[0].get("detalle_completo") or "")
            if detalle.startswith("data:image/png;base64,"):
                try:
                    b64_data = detalle.split(",", 1)[1]
                    with open(RUTA_ULTIMA_FIRMA, "wb") as f:
                        f.write(base64.b64decode(b64_data))
                    return RUTA_ULTIMA_FIRMA
                except Exception as e:
                    logger.warning(f"No se pudo decodificar firma Base64 desde Supabase: {e}")
    if os.path.exists(RUTA_ULTIMA_FIRMA):
        return RUTA_ULTIMA_FIRMA
    return ""

def generar_contrato_o_documento_formal(
    titulo_documento: str,
    nombre_cliente: str,
    cuerpo_clausulas: str,
    monto_acordado_usd: float = 0.0
) -> str:
    """Genera un Contrato o Propuesta formal en PDF con Firma Táctil si existe, lo envía por Telegram y lo respalda en Drive."""
    try:
        from fpdf import FPDF
        fecha_str = hoy_local_str()
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
        if float(monto_acordado_usd or 0) > 0:
            pdf.cell(0, 9, limpiar_latin1(f"  VALOR TOTAL ACORDADO: USD {float(monto_acordado_usd):,.2f}"), ln=True, fill=True)
        pdf.ln(6)

        # Cuerpo de Cláusulas
        pdf.set_font("Helvetica", "", 11)
        for parrafo in cuerpo_clausulas.split("\n"):
            p_limpio = limpiar_latin1(parrafo.strip())
            if not p_limpio:
                pdf.ln(3)
                continue
            if p_limpio.isupper() or p_limpio.startswith(("CLAUSULA", "CLÁUSULA", "1.", "2.", "3.", "4.", "5.")):
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(0, 6.5, p_limpio)
                pdf.set_font("Helvetica", "", 11)
            else:
                pdf.multi_cell(0, 6.5, p_limpio)
            pdf.ln(2)

        # Bloque de Firmas Digitales
        pdf.ln(15)
        if pdf.get_y() > 225:
            pdf.add_page()
        y_firma = pdf.get_y() + 20

        # Estampar Firma Digital del Cliente si fue capturada en el HUD
        ruta_firma = _obtener_ruta_firma_reciente()
        firma_estampada = False
        if ruta_firma and os.path.exists(ruta_firma):
            try:
                pdf.image(ruta_firma, x=125, y=y_firma - 18, w=55, h=16)
                firma_estampada = True
            except Exception as e_img:
                logger.warning(f"No se pudo incrustar imagen de firma en PDF: {e_img}")

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
                        caption=f"📄 *{titulo_documento}*\n👤 *Cliente:* {nombre_cliente}\n✍️ _{'Firma digital estampada' if firma_estampada else 'Listo para firmar en el HUD Web'}._",
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

        guardar_en_boveda_memoria(
            nombre_cliente,
            f"Contrato PDF generado ({nombre_pdf}): {titulo_documento} por USD {monto_acordado_usd}",
            "contratos"
        )
        return (
            f"📄 *[CONTRATO / DOCUMENTO PDF GENERADO CON ÉXITO]*\n"
            f"• *Archivo:* `{nombre_pdf}`\n"
            f"• *Cliente:* {nombre_cliente}\n"
            f"• *Firma Táctil:* {'✅ Estampada automáticamente en el PDF' if firma_estampada else f'Disponible en tu HUD Web (Puerto {JARVIS_WEB_PORT})'}\n"
            f"• *Entrega:* Enviado como PDF adjunto aquí en Telegram.\n"
            f"• *Respaldo:* {info_drive}"
        )
    except Exception as e:
        return f"❌ Error generando contrato PDF: {str(e)}"

# =====================================================================
# MOTOR DE VOZ NEURONAL ROBÓTICA (XTTS LOCAL - PUERTO 8020)
# =====================================================================
def usuario_pidio_voz(texto: str) -> bool:
    t = texto.lower()
    return any(kw in t for kw in ["voz", "audio", "habla", "háblame", "hablame", "escuchar", "/voz"])

def generar_audio_voz_jarvis(texto_respuesta: str) -> str:
    """Genera la voz de Jarvis en <1s usando Edge-TTS neuronal en español neutro."""
    import re
    import asyncio
    import edge_tts

    try:
        # Limpiar etiquetas técnicas, Markdown y enlaces
        texto_limpio = re.sub(r'^\[.*?\]\s*', '', texto_respuesta.strip(), flags=re.DOTALL)
        texto_limpio = re.sub(r'[*_`#~>\[\]•]', '', texto_limpio)
        texto_limpio = re.sub(r'https?://\S+', 'enlace adjunto', texto_limpio)
        texto_limpio = texto_limpio[:1200].strip()
        if not texto_limpio:
            texto_limpio = "Sistemas operativos, señor."

        ruta_salida = os.path.join("temp_audios", f"jarvis_voice_{int(time.time()*1000)}.mp3")

        async def _sintetizar():
            com = edge_tts.Communicate(
                text=texto_limpio,
                voice="es-MX-JorgeNeural",
                pitch="-3Hz",
                rate="-2%"
            )
            await com.save(ruta_salida)

        asyncio.run(_sintetizar())

        if os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 0:
            return ruta_salida
        return ""
    except Exception as e:
        logger.error(f"Falla generando voz con Edge-TTS: {e}")
        return ""

# =====================================================================
# 5. CATÁLOGO MODULAR DE MICRO-HERRAMIENTAS (21 TOOLS)
# =====================================================================
CATALOGO_TOOLS = {
    "registrar_o_actualizar_proyecto": {
        "type": "function", "function": {
            "name": "registrar_o_actualizar_proyecto",
            "description": "Guarda o actualiza un proyecto en la BD. Si ya existe actualiza sus montos y estado.",
            "parameters": {"type": "object", "properties": {"nombre_proyecto": {"type": "string"}, "cliente": {"type": "string"}, "estado": {"type": "string", "enum": ["1_Pagado_En_Curso", "2_Reunion_Critica", "3_Clonar_Ganancia_Rapida", "4_Prospecto_Demo", "Completado"]}, "prioridad": {"type": "integer"}, "monto_acordado": {"type": "number"}, "monto_cobrado": {"type": "number"}, "fecha_entrega": {"type": "string"}, "siguiente_paso": {"type": "string"}, "notas": {"type": "string"}}, "required": ["nombre_proyecto", "cliente", "estado", "prioridad", "siguiente_paso"]}
        }
    },
    "consultar_tablero_proyectos": {
        "type": "function", "function": {"name": "consultar_tablero_proyectos", "description": "Consulta todos los proyectos activos en la Base de Datos y plata en la calle.", "parameters": {"type": "object", "properties": {}}}
    },
    "agregar_tarea_agenda": {
        "type": "function", "function": {
            "name": "agregar_tarea_agenda",
            "description": "Anota una tarea o demo pendiente respetando los tiempos que indique el jefe.",
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
            "description": "Registra en la Base de Datos un 'cobro', 'gasto' o 'inversion' indicando la cuenta (ej: Binance, Zelle).",
            "parameters": {"type": "object", "properties": {"tipo": {"type": "string", "enum": ["cobro", "gasto", "inversion"]}, "monto": {"type": "number"}, "concepto": {"type": "string"}, "cliente_o_proyecto": {"type": "string"}, "metodo_pago": {"type": "string"}, "moneda": {"type": "string"}}, "required": ["tipo", "monto", "concepto"]}
        }
    },
    "consultar_reporte_financiero": {
        "type": "function", "function": {"name": "consultar_reporte_financiero", "description": "Consulta el balance financiero: cobros, gastos, saldo en cuentas y plata en la calle.", "parameters": {"type": "object", "properties": {"filtro_cliente": {"type": "string"}}}}
    },
    "guardar_en_boveda_memoria": {
        "type": "function", "function": {
            "name": "guardar_en_boveda_memoria",
            "description": "Guarda cualquier apunte, acuerdo o dato clave en la Base de Datos.",
            "parameters": {"type": "object", "properties": {"cliente_o_tema": {"type": "string"}, "detalle_completo": {"type": "string"}, "categoria": {"type": "string"}}, "required": ["cliente_o_tema", "detalle_completo"]}
        }
    },
    "buscar_en_boveda_memoria": {
        "type": "function", "function": {"name": "buscar_en_boveda_memoria", "description": "Busca en la Base de Datos acuerdos o datos guardados.", "parameters": {"type": "object", "properties": {"palabra_clave": {"type": "string"}}}}
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
            "description": "Redacta y genera un contrato formal en PDF (estampando firma si existe), lo envía por Telegram y lo sube a Drive.",
            "parameters": {"type": "object", "properties": {"titulo_documento": {"type": "string"}, "nombre_cliente": {"type": "string"}, "cuerpo_clausulas": {"type": "string"}, "monto_acordado_usd": {"type": "number"}}, "required": ["titulo_documento", "nombre_cliente", "cuerpo_clausulas"]}
        }
    }
}

# =====================================================================
# 6. CEREBRO JARVIS CON MICRO-ENRUTADOR INTELIGENTE (AHORRO DE TOKENS)
# =====================================================================
class CerebroJarvis:
    def __init__(self):
        self.historial = []

    def get_system_prompt_dinamico(self) -> str:
        ahora = ahora_local()
        return f"""Eres JARVIS: Asistente Ejecutivo, Jefe de Gabinete y CFO de {NOMBRE_JEFE} en {NOMBRE_AGENCIA}.
Fecha y hora actual: {ahora.strftime('%Y-%m-%d %H:%M')} ({TZ_NAME}).
Tono: Formal, ejecutivo, resolutivo y directo.
Formato: Usa viñetas limpias (•) y emojis sobrios. NUNCA uses tablas markdown.
Capacidades: Cuentas con integración total de voz, agenda, finanzas, proyectos y generación de contratos en PDF con firma digital.
CONTRATOS Y DOCUMENTOS: Cuando el jefe te pida redactar, hacer o generar un contrato, presupuesto, documento legal o PDF, NUNCA respondas con texto plano para copiar ni digas que no puedes generar PDFs; estás OBLIGADO a ejecutar inmediatamente la herramienta 'generar_contrato_o_documento_formal' redactando tú mismo las cláusulas en el argumento 'cuerpo_clausulas' y fijando el monto acordado."""

    def seleccionar_micro_herramientas(self, texto: str) -> list:
        t = texto.lower()
        if t.startswith("/chat"):
            return []

        seleccion = set()

        kw_finanzas = ["cobré", "cobre", "cobro", "pagó", "pago", "pagaron", "abono", "abonó", "gasté", "gaste", "gasto", "invertí", "inverti", "inversión", "inversion", "finanzas", "balance", "plata", "dinero", "debe", "calle", "binance", "zelle", "efectivo", "banco", "cuenta", "cuánto", "cuanto", "caja", "dólares"]
        if any(p in t for p in kw_finanzas):
            seleccion.update(["registrar_movimiento_financiero", "consultar_reporte_financiero", "consultar_tablero_proyectos"])

        kw_operaciones = ["anota", "agrega", "agenda", "tarea", "pendiente", "prioridad", "proyecto", "cliente", "concreté", "cerré", "demo", "aplicación", "web", "página", "ferretería", "carros", "agencia", "iglesia", "clonar", "procrastinador", "informe", "reporte", "resumen", "estado", "qué tenemos", "qué tengo", "qué hay", "hoy", "recuerda", "olvidé", "acuerdo", "quedamos", "bóveda", "memoria", "supabase", "local", "terminé", "semana", "hazlo", "pásalo", "cóbramelos", "/hacer", "actualiza"]
        # 🟢 Reparación: Incluidos pronombres como "hazlo", "pásalo" para que no pierda las tools de seguimiento
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

        kw_contratos = ["contrato", "pdf", "documento formal", "acuerdo legal", "propuesta formal", "presupuesto pdf", "firmar", "firma", "estampar"]
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

        # Si el historial corto (últimos 3 mensajes) usó herramientas operativas, las mantenemos encendidas por si es una órden de seguimiento
        if len(self.historial) >= 2 and not seleccion:
            ult_msg = str(self.historial[-1].get("content", "")).lower()
            if "proyecto" in ult_msg or "tarea" in ult_msg:
                seleccion.update(["cambiar_estado_tarea", "registrar_o_actualizar_proyecto", "registrar_movimiento_financiero"])

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
        mensajes_completos = [{"role": "system", "content": self.get_system_prompt_dinamico()}] + mensajes
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

        etiqueta_modo = f"⚡ Jarvis + Supabase ({num_tools} tools)" if num_tools > 0 else "💬 Jarvis (Modo Ligero 0 tools)"
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
            ahora = ahora_local()
            hora_actual = ahora.strftime("%H:%M")
            fecha_hoy = hoy_local_str()
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
                    f"☀️ *REPORTE MATUTINO ({hora_actual} {TZ_NAME})*\n"
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
    # 🟢 Reparación: Uso estricto de finally para evitar fugas de memoria y limpieza segura de audios
    try:
        if es_audio:
            texto = jarvis.transcribir_audio(ruta_audio)
            enviar_respuesta_segura(chat_id, f"🎙️ *Escuché:* \"_{texto}_\"")
            res = jarvis.procesar(texto)
        else:
            texto = texto_o_voz
            res = jarvis.procesar(texto)

        enviar_respuesta_segura(chat_id, res)

        if usuario_pidio_voz(texto):
            ruta_tts = generar_audio_voz_jarvis(res)
            if ruta_tts and os.path.exists(ruta_tts):
                try:
                    with open(ruta_tts, "rb") as audio_f:
                        bot.send_voice(chat_id, audio_f)
                finally:
                    if os.path.exists(ruta_tts):
                        os.remove(ruta_tts)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")
    finally:
        if es_audio and ruta_audio and os.path.exists(ruta_audio):
            try:
                os.remove(ruta_audio)
            except Exception:
                pass

def procesar_video_en_hilo(chat_id, ruta_vid, caption):
    # 🟢 Reparación: Limpieza segura de videos en bloque finally
    try:
        enviar_respuesta_segura(chat_id, "📥 *Analizando video en segundo plano...*")
        res = jarvis.procesar_video_multimodal(ruta_vid, caption)
        enviar_respuesta_segura(chat_id, res)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error video: {str(e)}")
    finally:
        if ruta_vid and os.path.exists(ruta_vid):
            try:
                os.remove(ruta_vid)
            except Exception:
                pass


if __name__ == "__main__":
    print("=======================================================================")
    print(f"🚀 INICIANDO JARVIS CFO & JEFE DE GABINETE ({MWAPI_MODEL})")
    print(f"☁️ SUPABASE REST API: {'CONECTADA 🟢' if supabase_rest_activo() else 'MODO LOCAL 🔴'}")
    print(f"🕒 ZONA HORARIA ACTIVA: {TZ_NAME}")
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

    print("🤖 ¡JARVIS OPERATIVO Y A LA ESPERA DE ÓRDENES!\n")
    if bot:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)