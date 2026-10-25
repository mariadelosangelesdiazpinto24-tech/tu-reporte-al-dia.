import os
import urllib.parse as urlparse
import urllib.request
import json
import psycopg2
import psycopg2.extras
import unicodedata
import re
import shutil
import traceback
import base64
from zoneinfo import ZoneInfo
from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form, UploadFile, File, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware

app = FastAPI()

app.add_middleware(GZipMiddleware, minimum_size=1000)

BANQUEROS_FIJOS = {
    "LIDER": {
        "clave": "lider123",
        "comercializadora": "COMERCIALIZADORA LIDER"
    },
    "NYS": {
        "clave": "nys123",
        "comercializadora": "COMERCIALIZADORA NYS"
    },
    "SUPER APUESTAS": {
        "clave": "super123",
        "comercializadora": "COMERCIALIZADORA SUPER APUESTAS"
    },
    "DUBAI": {
        "clave": "dubai123",
        "comercializadora": "COMERCIALIZADORA DUBAI"
    }
}

ONESIGNAL_APP_ID = "88b4cb90-08ed-4ef3-8852-c45316493190"
ONESIGNAL_REST_KEY = os.environ.get("ONESIGNAL_REST_KEY", "os_v2_app_xxxxxxxxxxxxxxxxxxxxxxxx")

def disparar_notificacion(agencia_destino: str, titulo: str, mensaje: str):
    url = "https://onesignal.com/api/v1/notifications"
    
    api_key = ONESIGNAL_REST_KEY.strip()
    if not api_key or "xxxxxxxx" in api_key:
        print("⚠️ AVISO: ONESIGNAL_REST_KEY no está configurada.")
        return

    headers = {
        "Authorization": f"Key {api_key}" if api_key.startswith("os_v2_") else f"Basic {api_key}",
        "Content-Type": "application/json; charset=utf-8"
    }

    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "headings": {"es": titulo, "en": titulo},
        "contents": {"es": mensaje, "en": mensaje},
        "chrome_web_icon": "https://tu-reporte-al-dia.onrender.com/templates/logo.png",
        "url": "/login"
    }

    if agencia_destino == "TODAS":
        payload["included_segments"] = ["Total Subscriptions"]
    elif agencia_destino.upper() == "ADMIN":
        payload["include_aliases"] = {"external_id": ["ADMIN"]}
        payload["target_channel"] = "push"
    else:
        payload["include_aliases"] = {"external_id": [normalizar(agencia_destino)]}
        payload["target_channel"] = "push"

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            print(f"✅ Notificación enviada a {agencia_destino}: Código {resp.status}")
    except Exception as e:
        print("❌ Error enviando notificación push:", e)

@app.get("/OneSignalSDKWorker.js")
def onesignal_worker():
    contenido_worker = 'importScripts("https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js");'
    return Response(content=contenido_worker, media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})

@app.get("/manifest.json")
def get_manifest():
    ruta_manifest = os.path.join("templates", "manifest.json")
    if os.path.exists(ruta_manifest):
        return FileResponse(ruta_manifest, media_type="application/manifest+json")
    return FileResponse("manifest.json", media_type="application/manifest+json")

TZ_VENEZUELA = ZoneInfo("America/Caracas")

def obtener_fecha_venezuela() -> str:
    return datetime.now(TZ_VENEZUELA).strftime('%Y-%m-%d')

def obtener_fechahora_venezuela() -> str:
    return datetime.now(TZ_VENEZUELA).strftime('%Y-%m-%d %H:%M:%S')

def obtener_ahora_vzla() -> datetime:
    return datetime.now(TZ_VENEZUELA)

def obtener_rango_semana_actual():
    hoy = datetime.now(TZ_VENEZUELA).date()
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    return lunes.strftime('%Y-%m-%d'), domingo.strftime('%Y-%m-%d')

os.makedirs("uploads", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# 19 SISTEMAS OFICIALES EN EL ORDEN IDÉNTICO AL CUADRO AZUL
# ==============================================================================
SISTEMAS_OFICIALES = [
    "LA IMAGINARIA", "BETSOL", "GATO", "LOTIPOS", "LOTTIPLAY", 
    "LOTTOLUCKY", "MAXPLAY", "SRQ", "POSNET", "POZO", 
    "PREMIER", "SRQ POLLA", "WINBIG VENTAS", "WINBIG BINGO", 
    "WINBIG POLLAS", "VENTA ACTIVA", "PARLEY", "PATRONUS", "MASTER ACTIVO"
]

ALIAS_AGENCIAS = {
    "JCPEREZ": "JC PEREZ",
    "JC PEREZ": "JC PEREZ",
    "JC_PEREZ": "JC PEREZ",
    "RUTA MILLONARIA": "ANA MARIA",
    "LA SUERTE DE JANN": "NABEL",
    "LADD LA CONEJITA": "MILA",
    "LA CONEJITA": "MILA",
    "CONEJITA": "MILA",
    "EMILY LARA": "MILA",
    "EMILY": "MILA",
    "DESTINO FORTUNA": "DESTINO SUERTE",
    "DATOS VIP 23": "VIP23",
    "CAMINO DE LA SUERTE": "FERNANDO",
    "AGENCIA VALLEMIL": "VALLEMIL",
    "AGENCIA ORQUIDEA 2": "ORQUIDEA",
    "AGENCIA ORQUÍDEA 2": "ORQUIDEA",
    "LA LEONA": "ALEXA",
    "ALEXA🦁": "ALEXA",
    "GEGE🐼": "GEGE",
    "LAS VECINAS": "LAS VECINAS",
    "LA MOROCHA": "LA MOROCHA",
    "LOS LLANOS": "LOS LLANOS",
    "LA BRUJITA": "LA BRUJITA"
}

def normalizar(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    t_clean = texto.strip().upper()
    return ALIAS_AGENCIAS.get(t_clean, t_clean)

def normalizar_sistema(sistema: str) -> str:
    if not sistema:
        return ""
    s_clean = normalizar(sistema)
    if "MATRIX" in s_clean:
        return "VENTA ACTIVA"
    return s_clean

def formatear_monto(valor):
    try:
        if isinstance(valor, str):
            valor = valor.replace(',', '')
        return f"{float(valor):.2f}"
    except (ValueError, TypeError):
        return "0.00"

templates.env.filters["dinero"] = formatear_monto

def get_db():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            without_prefix = database_url.replace("postgresql://", "")
            auth_part, rest = without_prefix.split("@")
            user, password = auth_part.split(":", 1)
            host_port, dbname = rest.split("/")
            
            if ":" in host_port:
                host, port = host_port.split(":")
            else:
                host, port = host_port, "6543"

            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=urlparse.unquote(password),
                host=host,
                port=port,
                sslmode='require',
                cursor_factory=psycopg2.extras.RealDictCursor
            )
        except Exception:
            conn = psycopg2.connect(
                database_url,
                sslmode='require',
                cursor_factory=psycopg2.extras.RealDictCursor
            )
    else:
        import sqlite3
        conn = sqlite3.connect("database.db", timeout=30.0)
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            agencia TEXT UNIQUE,
            clave TEXT,
            genero TEXT DEFAULT 'FEMENINO',
            rol TEXT DEFAULT 'TAQUILLA',
            ultima_conexion TEXT
        )
    ''')

    cursor.execute('''
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS nombre_real TEXT;
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS cedula TEXT;
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefono TEXT;
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'ACTIVO';
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS recomendado_por TEXT;
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reportes (
            id SERIAL PRIMARY KEY,
            agencia TEXT,
            fecha TEXT,
            monto DOUBLE PRECISION,
            ventas DOUBLE PRECISION DEFAULT 0,
            premios DOUBLE PRECISION DEFAULT 0,
            detalle_html TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pagos (
            id SERIAL PRIMARY KEY,
            agencia TEXT,
            fecha TEXT,
            monto DOUBLE PRECISION,
            factura TEXT,
            comprobante TEXT,
            tipo TEXT DEFAULT 'PAGO_TAQUILLA',
            estado TEXT DEFAULT 'APROBADO'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comunicados (
            id SERIAL PRIMARY KEY,
            mensaje TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            agencia_destino TEXT DEFAULT 'TODAS'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lecturas_comunicados (
            id SERIAL PRIMARY KEY,
            comunicado_id INTEGER,
            agencia TEXT,
            leido INTEGER DEFAULT 1,
            UNIQUE(comunicado_id, agencia)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion_banqueros (
            id SERIAL PRIMARY KEY,
            banquero TEXT,
            sistema TEXT,
            pct_banquero DOUBLE PRECISION,
            pct_taquilla DOUBLE PRECISION,
            pct_participacion DOUBLE PRECISION,
            absorbe_cashea BOOLEAN DEFAULT FALSE,
            UNIQUE(banquero, sistema)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ajustes_banqueros_manuales (
            id SERIAL PRIMARY KEY,
            banquero TEXT,
            sistema TEXT,
            fecha TEXT,
            venta DOUBLE PRECISION,
            comision DOUBLE PRECISION,
            premios DOUBLE PRECISION,
            UNIQUE(banquero, sistema, fecha)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ajustes_globales_banqueros (
            id SERIAL PRIMARY KEY,
            banquero TEXT,
            fecha TEXT,
            adelantos DOUBLE PRECISION DEFAULT 0,
            pendientes DOUBLE PRECISION DEFAULT 0,
            UNIQUE(banquero, fecha)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conciliaciones_semanales (
            id SERIAL PRIMARY KEY,
            agencia TEXT,
            desde_fecha TEXT,
            hasta_fecha TEXT,
            total_reportado DOUBLE PRECISION DEFAULT 0,
            total_pagado DOUBLE PRECISION DEFAULT 0,
            total_sistema DOUBLE PRECISION DEFAULT 0,
            diferencia DOUBLE PRECISION DEFAULT 0,
            detalle_dias TEXT,
            UNIQUE(agencia, desde_fecha, hasta_fecha)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lista_negra (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            cedula TEXT,
            telefonos TEXT,
            rol_estafador TEXT,
            descripcion TEXT,
            evidencias TEXT,
            reportado_por TEXT,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    agencias_base = [
        "MILA", "ANA MARIA", "NABEL", "VIP23", "DESTINO SUERTE", 
        "VALLEMIL", "ALEXA", "PALOMITA", "GEGE", "LILI LA LOBA", 
        "LAS VECINAS", "LA MOROCHA", "LOS LLANOS", "LA BRUJITA"
    ]
    for ag in agencias_base:
        try:
            cursor.execute("INSERT INTO usuarios (agencia, clave, genero, rol) VALUES (%s, '123456', 'FEMENINO', 'TAQUILLA') ON CONFLICT (agencia) DO NOTHING", (ag,))
        except Exception:
            pass

    cursor.execute("""
        INSERT INTO configuracion_banqueros (banquero, sistema, pct_banquero, pct_taquilla, pct_participacion, absorbe_cashea)
        VALUES ('COMERCIALIZADORA LIDER', 'PATRONUS', 0.16, 0.12, 0.20, FALSE)
        ON CONFLICT (banquero, sistema) DO UPDATE
        SET pct_banquero = EXCLUDED.pct_banquero,
            pct_taquilla = EXCLUDED.pct_taquilla,
            pct_participacion = EXCLUDED.pct_participacion;
    """)

    cursor.execute("""
        INSERT INTO configuracion_banqueros (banquero, sistema, pct_banquero, pct_taquilla, pct_participacion, absorbe_cashea)
        VALUES ('COMERCIALIZADORA LIDER', 'MASTER ACTIVO', 0.17, 0.13, 0.30, FALSE)
        ON CONFLICT (banquero, sistema) DO UPDATE
        SET pct_banquero = EXCLUDED.pct_banquero,
            pct_taquilla = EXCLUDED.pct_taquilla,
            pct_participacion = EXCLUDED.pct_participacion;
    """)

    conn.commit()
    conn.close()

init_db()

def extraer_neto_de_html(detalle_html: str) -> float:
    if not detalle_html:
        return 0.0
    
    html_sistemas = detalle_html.split('<!-- BLOQUES_EXTRAS -->')[0]
    tablas = re.findall(r'<table[^>]*>(.*?)<\/table>', html_sistemas, re.DOTALL | re.IGNORECASE)
    
    for tabla in tablas:
        filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', tabla, re.DOTALL | re.IGNORECASE)
        for fila in filas:
            if 'TOTALES' in fila.upper():
                cols = re.findall(r'<td[^>]*>(.*?)<\/td>', fila, re.DOTALL | re.IGNORECASE)
                if cols:
                    try:
                        return float(re.sub(r'[^\d.-]', '', cols[-1]))
                    except Exception:
                        pass

    neto_acumulado = 0.0
    for tabla in tablas:
        filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', tabla, re.DOTALL | re.IGNORECASE)
        for fila in filas:
            cols = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', fila, re.DOTALL | re.IGNORECASE)
            if len(cols) >= 5:
                texto_0 = re.sub(r'<[^>]+>', '', cols[0]).strip().upper()
                if texto_0 and "TOTALES" not in texto_0 and "SISTEMA" not in texto_0 and "TRIPLETA" not in texto_0:
                    try:
                        neto_acumulado += float(re.sub(r'[^\d.-]', '', cols[4]))
                    except Exception:
                        pass
    return neto_acumulado

def obtener_cuenta_agencia_corte(agencia_raw: str, fecha_corte: Optional[str] = None):
    ag_norm = normalizar(agencia_raw)
    fecha_hoy_contable = fecha_corte if fecha_corte else obtener_fecha_venezuela()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT fecha, monto FROM pagos 
        WHERE UPPER(TRIM(agencia)) = %s AND tipo = 'AJUSTE_SALDO_ANTERIOR'
          AND fecha <= %s
        ORDER BY fecha DESC, id DESC LIMIT 1
    """, (ag_norm, fecha_hoy_contable))
    ajuste_previo = cursor.fetchone()

    if ajuste_previo and ajuste_previo['fecha'] == fecha_hoy_contable:
        saldo_anterior = float(ajuste_previo['monto'] or 0.0)
    else:
        fecha_obj = datetime.strptime(fecha_hoy_contable, '%Y-%m-%d').date()
        fecha_ayer_str = (fecha_obj - timedelta(days=1)).strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT monto, detalle_html FROM reportes 
            WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s
        """, (ag_norm, fecha_ayer_str))
        rep_ayer = cursor.fetchone()

        if rep_ayer and rep_ayer['monto'] is not None:
            saldo_anterior = float(rep_ayer['monto'])
        else:
            cursor.execute("""
                SELECT detalle_html FROM reportes 
                WHERE UPPER(TRIM(agencia)) = %s AND fecha < %s
            """, (ag_norm, fecha_hoy_contable))
            reps_prev = cursor.fetchall()
            neto_prev = sum(extraer_neto_de_html(r['detalle_html']) for r in reps_prev if r and r['detalle_html'])

            cursor.execute("""
                SELECT tipo, SUM(monto) as total FROM pagos 
                WHERE UPPER(TRIM(agencia)) = %s AND estado = 'APROBADO' 
                  AND tipo != 'AJUSTE_SALDO_ANTERIOR' AND fecha < %s
                GROUP BY tipo
            """, (ag_norm, fecha_hoy_contable))
            pagos_prev = cursor.fetchall()

            ab_p, ca_p, ad_p, li_p = 0.0, 0.0, 0.0, 0.0
            for p in pagos_prev:
                tp = str(p['tipo']).upper()
                m = float(p['total'] or 0.0)
                if tp in ['PAGO_TAQUILLA', 'PAGO_BANCA', 'AJUSTE_BANCA']: ab_p += m
                elif tp == 'CASHEA': ca_p += m
                elif tp == 'ADELANTO': ad_p += m
                elif tp == 'LIQUIDACION': li_p += m

            saldo_anterior = (neto_prev - ca_p) - ab_p + ad_p + li_p

    if abs(saldo_anterior) < 0.05:
        saldo_anterior = 0.0

    cursor.execute("""
        SELECT detalle_html FROM reportes 
        WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s
    """, (ag_norm, fecha_hoy_contable))
    rep_hoy = cursor.fetchone()
    neto_hoy = extraer_neto_de_html(rep_hoy['detalle_html']) if rep_hoy and rep_hoy['detalle_html'] else 0.0

    cursor.execute("""
        SELECT tipo, monto FROM pagos 
        WHERE UPPER(TRIM(agencia)) = %s 
          AND fecha = %s 
          AND estado = 'APROBADO' 
          AND tipo != 'AJUSTE_SALDO_ANTERIOR'
    """, (ag_norm, fecha_hoy_contable))
    pagos_hoy = cursor.fetchall()

    abonos_hoy = 0.0
    cashea_hoy = 0.0
    adelantos_hoy = 0.0
    liquidaciones_hoy = 0.0

    for p in pagos_hoy:
        tp = str(p['tipo']).upper()
        m_val = float(p['monto'] or 0.0)
        if tp in ['PAGO_TAQUILLA', 'PAGO_BANCA', 'AJUSTE_BANCA']:
            abonos_hoy += m_val
        elif tp == 'CASHEA':
            cashea_hoy += m_val
        elif tp == 'ADELANTO':
            adelantos_hoy += m_val
        elif tp == 'LIQUIDACION':
            liquidaciones_hoy += m_val

    saldo_final = saldo_anterior + (neto_hoy - cashea_hoy) - abonos_hoy + adelantos_hoy + liquidaciones_hoy

    if abs(saldo_final) < 0.05:
        saldo_final = 0.0

    conn.close()

    return {
        "agencia": ag_norm,
        "fecha": fecha_hoy_contable,
        "saldo_anterior": saldo_anterior,
        "neto_hoy": neto_hoy,
        "cashea_hoy": cashea_hoy,
        "abonos_hoy": abonos_hoy,
        "adelantos_hoy": adelantos_hoy,
        "liquidaciones_hoy": liquidaciones_hoy,
        "saldo_final": saldo_final
    }

def normalizar_nombre_banquero(nombre_raw: str) -> str:
    if not nombre_raw:
        return ""
    b = nombre_raw.strip().upper()
    if b in ["LIDER", "COMERCIALIZADORA LIDER"]:
        return "COMERCIALIZADORA LIDER"
    if b in ["NYS", "COMERCIALIZADORA NYS"]:
        return "COMERCIALIZADORA NYS"
    if b in ["DUBAI", "COMERCIALIZADORA DUBAI", "LOTTOLUCKY", "COMERCIALIZADORA LOTTOLUCKY", "LUCKY"]:
        return "COMERCIALIZADORA DUBAI"
    if b in ["SUPER APUESTAS", "COMERCIALIZADORA SUPER APUESTAS", "BETSOL"]:
        return "COMERCIALIZADORA SUPER APUESTAS"
    return b

def obtener_estructura_banqueros_bd():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM configuracion_banqueros ORDER BY id ASC")
    filas = cursor.fetchall()
    conn.close()

    estructura = {}
    for f in filas:
        b_name = normalizar_nombre_banquero(f['banquero'])

        if b_name not in estructura:
            estructura[b_name] = {
                "sistemas": [],
                "absorbe_cashea": bool(f['absorbe_cashea'])
            }
        
        sistemas_existentes = [s['sistema'] for s in estructura[b_name]["sistemas"]]
        if f['sistema'] not in sistemas_existentes:
            estructura[b_name]["sistemas"].append({
                "id": f['id'],
                "sistema": f['sistema'],
                "pct_banquero": float(f['pct_banquero']),
                "pct_taquilla": float(f['pct_taquilla']),
                "pct_participacion": float(f['pct_participacion'])
            })
    return estructura

def calcular_desglose_banqueros_datos(f_desde, f_hasta, agencia_filtro=""):
    conn = get_db()
    cursor = conn.cursor()
    ag_filtro_norm = normalizar(agencia_filtro) if agencia_filtro else ""

    cursor.execute("SELECT * FROM reportes WHERE fecha >= %s AND fecha <= %s", (f_desde, f_hasta))
    reps_db = cursor.fetchall()

    sistemas_consolidados = {
        s: {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
        for s in SISTEMAS_OFICIALES
    }
    sistemas_agencias_detalle = {s: [] for s in SISTEMAS_OFICIALES}
    totales_generales = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}

    for rep_db in reps_db:
        ag_origen = normalizar(rep_db['agencia'])
        if ag_filtro_norm and ag_origen != ag_filtro_norm:
            continue

        if rep_db and rep_db['detalle_html']:
            detalle_limpio = rep_db['detalle_html'].split('<!-- BLOQUES_EXTRAS -->')[0]
            tablas_encontradas = re.findall(r'<table[^>]*>(.*?)<\/table>', detalle_limpio, re.DOTALL | re.IGNORECASE)
            for t_html in tablas_encontradas:
                filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', t_html, re.DOTALL | re.IGNORECASE)
                for f in filas:
                    cols = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', f, re.DOTALL | re.IGNORECASE)
                    if len(cols) >= 5:
                        sys_raw = re.sub(r'<[^>]+>', '', cols[0]).strip()
                        
                        if not sys_raw or "SISTEMA" in sys_raw.upper() or "TOTALES" in sys_raw.upper() or "TRIPLETA" in sys_raw.upper():
                            continue
                        
                        sys_nombre = normalizar_sistema(sys_raw)
                        try:
                            v = float(re.sub(r'[^\d.-]', '', cols[1]))
                            c = float(re.sub(r'[^\d.-]', '', cols[2]))
                            p = float(re.sub(r'[^\d.-]', '', cols[3]))
                            t = float(re.sub(r'[^\d.-]', '', cols[4]))
                        except Exception:
                            v, c, p, t = 0.0, 0.0, 0.0, 0.0

                        if sys_nombre not in sistemas_consolidados:
                            sistemas_consolidados[sys_nombre] = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
                            sistemas_agencias_detalle[sys_nombre] = []
                        
                        sistemas_consolidados[sys_nombre]["venta"] += v
                        sistemas_consolidados[sys_nombre]["comision"] += c
                        sistemas_consolidados[sys_nombre]["premio"] += p
                        sistemas_consolidados[sys_nombre]["neto"] += t

                        if v > 0 or p > 0 or t != 0:
                            sistemas_agencias_detalle[sys_nombre].append({
                                "agencia": ag_origen,
                                "venta": v,
                                "comision": c,
                                "premio": p,
                                "total": t
                            })

                        totales_generales["venta"] += v
                        totales_generales["comision"] += c
                        totales_generales["premio"] += p
                        totales_generales["neto"] += t

    cursor.execute("SELECT * FROM pagos WHERE fecha >= %s AND fecha <= %s AND estado = 'APROBADO'", (f_desde, f_hasta))
    pagos_aux = cursor.fetchall()

    totales_auxiliares = {"cashea": 0.0, "adelantos": 0.0, "abonos_banca": 0.0}
    for pa in pagos_aux:
        ag_pago_norm = normalizar(pa['agencia'])
        if ag_filtro_norm and ag_pago_norm != ag_filtro_norm:
            continue

        m_val = float(pa['monto'] or 0.0)
        t_type = str(pa['tipo']).strip().upper() if pa['tipo'] else ''
        if t_type == 'CASHEA':
            totales_auxiliares["cashea"] += m_val
        elif t_type in ['ADELANTO', 'LIQUIDACION']:
            totales_auxiliares["adelantos"] += m_val
        elif t_type in ['PAGO_TAQUILLA', 'PAGO_BANCA', 'AJUSTE_BANCA']:
            totales_auxiliares["abonos_banca"] += m_val

    ESTRUCTURA_BANQUEROS = obtener_estructura_banqueros_bd()

    for k in ESTRUCTURA_BANQUEROS.keys():
        if "NYS" in k.upper():
            ESTRUCTURA_BANQUEROS[k]["absorbe_cashea"] = True

    desglose_banqueros = {}
    total_ganancia_excedente = 0.0
    total_ganancia_participacion = 0.0
    suma_cuadros_banqueros = 0.0

    for b_nombre, cfg in ESTRUCTURA_BANQUEROS.items():
        alias_banquero = b_nombre.replace("COMERCIALIZADORA ", "")
        cursor.execute(
            """SELECT SUM(adelantos) as sum_adelantos, SUM(pendientes) as sum_pendientes 
               FROM ajustes_globales_banqueros 
               WHERE (banquero = %s OR banquero = %s) AND fecha >= %s AND fecha <= %s""",
            (b_nombre, alias_banquero, f_desde, f_hasta)
        )
        row_ajustes_glob = cursor.fetchone()
        adelantos_b_val = float(row_ajustes_glob['sum_adelantos'] or 0.0) if row_ajustes_glob else 0.0
        pendientes_b_val = float(row_ajustes_glob['sum_pendientes'] or 0.0) if row_ajustes_glob else 0.0

        cashea_a_descontar = totales_auxiliares["cashea"] if (cfg.get("absorbe_cashea") or "NYS" in b_nombre.upper()) else 0.0

        desglose_banqueros[b_nombre] = {
            "sistemas": [],
            "cashea_descontado": cashea_a_descontar,
            "adelantos_banquero": adelantos_b_val,
            "pendientes_banquero": pendientes_b_val,
            "total_a_pagar_banquero": 0.0,
            "total_mi_ganancia_banca": 0.0,
            "total": 0.0
        }

        subtotal_banquero = 0.0

        for item in cfg["sistemas"]:
            s_name = item["sistema"]
            v_sys = sistemas_consolidados.get(s_name, {}).get("venta", 0.0)
            p_sys = sistemas_consolidados.get(s_name, {}).get("premio", 0.0)
            
            pct_b = item["pct_banquero"]
            pct_t = item["pct_taquilla"]
            pct_part = item["pct_participacion"]

            cursor.execute(
                """SELECT SUM(venta) as total_v, SUM(comision) as total_c, SUM(premios) as total_p, COUNT(*) as cant 
                   FROM ajustes_banqueros_manuales 
                   WHERE (banquero = %s OR banquero = %s) AND sistema = %s AND fecha >= %s AND fecha <= %s""",
                (b_nombre, alias_banquero, s_name, f_desde, f_hasta)
            )
            ajuste_manual = cursor.fetchone()

            if ajuste_manual and ajuste_manual['cant'] and ajuste_manual['cant'] > 0 and (ajuste_manual['total_v'] is not None or ajuste_manual['total_p'] is not None):
                v_sys = float(ajuste_manual['total_v'] or 0.0)
                p_sys = float(ajuste_manual['total_p'] or 0.0)
                c_banquero = float(ajuste_manual['total_c'] or 0.0)
                hay_ajuste = True
            else:
                c_banquero = v_sys * pct_b
                hay_ajuste = False

            t_banquero_sistema = v_sys - c_banquero - p_sys
            c_taquilla = v_sys * pct_t
            pct_excedente = (pct_b - pct_t) * 100.0
            g_excedente = v_sys * (pct_b - pct_t)
            
            monto_participacion = t_banquero_sistema * pct_part if pct_part > 0 else 0.0
            total_despues_participacion = t_banquero_sistema - monto_participacion
            g_total = g_excedente + monto_participacion

            total_ganancia_excedente += g_excedente
            total_ganancia_participacion += monto_participacion

            desglose_banqueros[b_nombre]["sistemas"].append({
                "id": item.get("id"),
                "sistema": s_name,
                "venta": v_sys,
                "comision_taquilla": c_taquilla,
                "comision_banquero": c_banquero,
                "premios": p_sys,
                "total_sistema": t_banquero_sistema,
                "monto_participacion": monto_participacion,
                "total_banquero": total_despues_participacion,
                "total_final": total_despues_participacion,
                "pct_banquero": int(round(pct_b * 100)),
                "pct_taquilla": int(round(pct_t * 100)),
                "pct_excedente": int(round(pct_excedente)),
                "pct_participacion": int(round(pct_part * 100)),
                "ganancia_total": g_total,
                "ajustado_manual": hay_ajuste
            })

            subtotal_banquero += total_despues_participacion
            desglose_banqueros[b_nombre]["total_mi_ganancia_banca"] += g_total

        subtotal_banquero -= cashea_a_descontar
        subtotal_banquero -= adelantos_b_val
        subtotal_banquero += pendientes_b_val

        desglose_banqueros[b_nombre]["total_a_pagar_banquero"] = subtotal_banquero
        desglose_banqueros[b_nombre]["total"] = subtotal_banquero
        suma_cuadros_banqueros += subtotal_banquero

    conn.close()
    total_mi_ganancia_global = total_ganancia_excedente + total_ganancia_participacion

    return (
        sistemas_consolidados,
        sistemas_agencias_detalle,
        totales_generales,
        totales_auxiliares,
        desglose_banqueros,
        total_ganancia_excedente,
        total_ganancia_participacion,
        total_mi_ganancia_global,
        suma_cuadros_banqueros
    )

def actualizar_ultima_conexion(agencia: str):
    agencia_norm = normalizar(agencia)
    if agencia_norm and agencia_norm != "ADMIN":
        try:
            now_str = obtener_fechahora_venezuela()
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE usuarios SET ultima_conexion = %s WHERE UPPER(TRIM(agencia)) = %s", (now_str, agencia_norm))
            conn.commit()
            conn.close()
        except Exception as e:
            print("Error actualizando conexion:", e)

def recalcular_y_actualizar_reporte(agencia: str, fecha_reporte: str):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s", (agencia_norm, fecha_reporte))
    rep = cursor.fetchone()
    
    if not rep:
        conn.close()
        return

    cursor.execute(
        """SELECT * FROM pagos 
           WHERE UPPER(TRIM(agencia)) = %s 
             AND estado = 'APROBADO' 
             AND tipo NOT IN ('AJUSTE_PENDIENTE', 'MODIFICACION', 'AJUSTE_SALDO_ANTERIOR')
             AND (fecha = %s OR factura LIKE %s)""", 
        (agencia_norm, fecha_reporte, f"%{fecha_reporte}%")
    )
    todos_pagos = cursor.fetchall()
    conn.close()

    total_adelantos = 0.0
    total_pagos_taquilla = 0.0
    total_liquidaciones_admin = 0.0
    total_cashea = 0.0
    
    adelantos_rows_html = ""
    cashea_rows_html = ""
    pagos_banca_rows_html = ""

    for p in todos_pagos:
        monto_p = float(p['monto'] or 0.0)
        tipo_p = str(p['tipo']).strip().upper() if p['tipo'] else 'PAGO_TAQUILLA'
        comp = p['comprobante'] or ''
        comp_display = f'<a href="/comprobante/{p["id"]}" class="btn btn-sm btn-outline-info py-0 fw-bold" style="border-color: var(--tech-primary); color: var(--tech-primary);"><i class="fas fa-download me-1"></i> Capture</a>' if comp else ""

        if tipo_p == 'ADELANTO':
            total_adelantos += monto_p
            adelantos_rows_html += f'''
            <tr style="font-size: 13px; background: rgba(255,255,255,0.02); color: var(--tech-text, #ffffff);">
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['factura']} {comp_display}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1)); text-align: right; color: var(--tech-primary, #ff007f); font-weight: bold;">Bs. {monto_p:,.2f}</td>
            </tr>'''
        elif tipo_p == 'LIQUIDACION':
            total_liquidaciones_admin += monto_p
            adelantos_rows_html += f'''
            <tr style="font-size: 13px; background: rgba(255,255,255,0.02); color: var(--tech-text, #ffffff);">
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['factura']} {comp_display}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1)); text-align: right; color: var(--tech-secondary, #ffd700); font-weight: bold;">+ Bs. {monto_p:,.2f}</td>
            </tr>'''
        elif tipo_p == 'CASHEA':
            total_cashea += monto_p
            cashea_rows_html += f'''
            <tr style="font-size: 13px; background: rgba(255,255,255,0.02); color: var(--tech-text, #ffffff);">
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['factura']}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1)); text-align: right; color: var(--tech-primary, #ff007f); font-weight: bold;">Bs. {monto_p:,.2f}</td>
            </tr>'''
        elif tipo_p in ['PAGO_TAQUILLA', 'PAGO_BANCA', 'AJUSTE_BANCA']:
            total_pagos_taquilla += monto_p
            pagos_banca_rows_html += f'''
            <tr style="font-size: 13px; background: rgba(255,255,255,0.02); color: var(--tech-text, #ffffff);">
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1));">{p['factura']}</td>
                <td style="padding: 10px; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1)); text-align: right; color: var(--tech-secondary, #ffd700); font-weight: bold;">Bs. {monto_p:,.2f}</td>
            </tr>'''

    detalle_original = rep['detalle_html'] or ""

    if '<!-- BLOQUES_EXTRAS -->' in detalle_original:
        tabla_sistemas_html = detalle_original.split('<!-- BLOQUES_EXTRAS -->')[0].strip()
    elif 'PAGOS / ABONOS A LA BANCA' in detalle_original:
        pos_corte = detalle_original.find('<div class="mb-3"')
        tabla_sistemas_html = detalle_original[:pos_corte].strip() if pos_corte != -1 else detalle_original
    else:
        tabla_sistemas_html = detalle_original.strip()

    cuenta_ag = obtener_cuenta_agencia_corte(agencia_norm, fecha_reporte)
    monto_final = cuenta_ag["saldo_final"]

    bloque_pagos_banca = f'''
    <div class="mb-3 tech-card" style="background: var(--tech-card-bg, rgba(20,20,30,0.85)); backdrop-filter: blur(10px); border-radius: 12px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border-left: 6px solid var(--tech-secondary, #ffd700); border-top: 1px solid var(--tech-border, rgba(255,255,255,0.1));">
        <h5 style="color: var(--tech-secondary, #ffd700); font-weight: bold; border-bottom: 2px solid var(--tech-secondary, #ffd700); padding-bottom: 10px; margin-bottom: 15px; letter-spacing: 0.5px;"><i class="fas fa-university"></i> PAGOS / ABONOS A LA BANCA</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background: rgba(0,0,0,0.3); color: var(--tech-secondary, #ffd700); font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">REFERENCIA / DETALLE</th>
                <th style="padding: 10px; text-align: right;">MONTO ABONADO</th>
            </tr>
            {pagos_banca_rows_html if pagos_banca_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">No hay pagos abonados aún.</td></tr>'}
        </table>
    </div>'''

    bloque_cashea = f'''
    <div class="mb-3 tech-card" style="background: var(--tech-card-bg, rgba(20,20,30,0.85)); backdrop-filter: blur(10px); border-radius: 12px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border-left: 6px solid var(--tech-primary, #ff007f); border-top: 1px solid var(--tech-border, rgba(255,255,255,0.1));">
        <h5 style="color: var(--tech-primary, #ff007f); font-weight: bold; border-bottom: 2px solid var(--tech-primary, #ff007f); padding-bottom: 10px; margin-bottom: 15px; letter-spacing: 0.5px;"><i class="fas fa-shopping-cart"></i> CASHEA (Registros absorbidos)</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background: rgba(0,0,0,0.3); color: var(--tech-primary, #ff007f); font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">DETALLE / FACTURA</th>
                <th style="padding: 10px; text-align: right;">MONTO ABSORBIDO</th>
            </tr>
            {cashea_rows_html if cashea_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">No hay registros de Cashea.</td></tr>'}
        </table>
    </div>'''

    bloque_adelantos = f'''
    <div class="mb-3 tech-card" style="background: var(--tech-card-bg, rgba(20,20,30,0.85)); backdrop-filter: blur(10px); border-radius: 12px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border-left: 6px solid var(--tech-primary, #ff007f); border-top: 1px solid var(--tech-border, rgba(255,255,255,0.1));">
        <h5 style="color: var(--tech-primary, #ff007f); font-weight: bold; border-bottom: 2px solid var(--tech-primary, #ff007f); padding-bottom: 10px; margin-bottom: 15px; letter-spacing: 0.5px;"><i class="fas fa-hand-holding-usd"></i> ADELANTOS / LIQUIDACIONES DE BANCA</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background: rgba(0,0,0,0.3); color: var(--tech-primary, #ff007f); font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">DETALLE</th>
                <th style="padding: 10px; text-align: right;">MONTO APLICADO</th>
            </tr>
            {adelantos_rows_html if adelantos_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">Sin adelantos o liquidaciones registradas hoy.</td></tr>'}
        </table>
    </div>'''

    color_monto_final = "var(--tech-secondary, #ffd700)" if monto_final <= 0 else "var(--tech-primary, #ff007f)"
    bloque_final = f'''
    <div class="mb-2 tech-card" style="background: var(--tech-card-bg, rgba(20,20,30,0.85)); backdrop-filter: blur(10px); border-radius: 12px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border-left: 6px solid {color_monto_final}; border: 1px solid var(--tech-border, rgba(255,255,255,0.1));">
        <h5 style="color: {color_monto_final}; font-weight: bold; border-bottom: 1px solid var(--tech-border, rgba(255,255,255,0.1)); padding-bottom: 10px; margin-bottom: 12px;"><i class="fas fa-clock"></i> ESTADO DE CUENTA FINAL</h5>
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <span style="font-size: 14px; color: var(--tech-text, #ffffff); font-weight: bold;">Fecha: {fecha_reporte}</span>
            <span style="font-size: 14px; font-weight: bold; color: var(--tech-text, #ffffff);">{("Cuenta Saldada (0.00 Bs.)" if abs(monto_final) < 0.05 else ("Total a Pagar" if monto_final > 0 else "Saldo a favor / Solicitar"))}</span>
            <span style="font-size: 20px; font-weight: bold; color: {color_monto_final}; text-shadow: 0 0 10px {color_monto_final};">Bs. {monto_final:,.2f}</span>
        </div>
    </div>'''

    detalle_actualizado = tabla_sistemas_html + "\n<!-- BLOQUES_EXTRAS -->\n" + bloque_pagos_banca + bloque_cashea + bloque_adelantos + bloque_final

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE reportes SET monto = %s, detalle_html = %s WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s", (monto_final, detalle_actualizado, agencia_norm, fecha_reporte))
    conn.commit()
    conn.close()

@app.get("/comprobante/{pago_id}")
def ver_o_descargar_comprobante(pago_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT agencia, fecha, comprobante FROM pagos WHERE id = %s", (pago_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row['comprobante']:
        return HTMLResponse("<h3>Comprobante no disponible o no adjuntado.</h3>", status_code=404)

    comp = str(row['comprobante']).strip()
    agencia_clean = str(row['agencia']).replace(" ", "_")
    nombre_archivo = f"Comprobante_{agencia_clean}_{row['fecha']}_{pago_id}.jpg"

    ruta_disco = os.path.join("uploads", os.path.basename(comp))
    if os.path.exists(ruta_disco):
        return FileResponse(
            ruta_disco, 
            filename=nombre_archivo, 
            headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'}
        )

    if comp.startswith("data:image"):
        try:
            header, encoded = comp.split(",", 1)
            mime = header.split(";")[0].split(":")[1]
            ext = mime.split("/")[-1]
            nombre_archivo = f"Comprobante_{agencia_clean}_{row['fecha']}_{pago_id}.{ext}"
            return Response(
                content=base64.b64decode(encoded), 
                media_type=mime, 
                headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'}
            )
        except Exception:
            pass

    return HTMLResponse(f"<h3>Comprobante: {comp}</h3>")

@app.post("/admin/ajustar-saldo-anterior")
def post_ajustar_saldo_anterior(
    agencia: str = Form(...),
    nuevo_saldo: float = Form(...)
):
    agencia_norm = normalizar(agencia)
    fecha_hoy = obtener_fecha_venezuela()
    valor_saldo = float(nuevo_saldo)

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND tipo = 'AJUSTE_SALDO_ANTERIOR'", (agencia_norm,))
    
    cursor.execute("""
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (%s, %s, %s, 'Ajuste Manual Saldo Anterior', 'Fijado desde panel admin', 'AJUSTE_SALDO_ANTERIOR', 'APROBADO')
    """, (agencia_norm, fecha_hoy, valor_saldo))

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha_hoy)
    return RedirectResponse(url="/admin?tab=balances", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/guardar-ajustes-banquero-global")
def post_guardar_ajustes_banquero_global(
    banquero: str = Form(...),
    fecha: str = Form(...),
    adelantos: float = Form(0.0),
    pendientes: float = Form(0.0),
    desde_fecha: Optional[str] = Form(None),
    hasta_fecha: Optional[str] = Form(None)
):
    b_norm = normalizar_nombre_banquero(banquero)
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO ajustes_globales_banqueros (banquero, fecha, adelantos, pendientes)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (banquero, fecha)
           DO UPDATE SET adelantos = EXCLUDED.adelantos, pendientes = EXCLUDED.pendientes""",
        (b_norm, fecha, adelantos, pendientes)
    )

    cursor.execute(
        "DELETE FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s AND tipo IN ('ADELANTO_BANQUERO', 'PENDIENTE_BANQUERO')",
        (b_norm, fecha)
    )

    if adelantos != 0:
        cursor.execute(
            """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
               VALUES (%s, %s, %s, %s, %s, 'ADELANTO_BANQUERO', 'APROBADO')""",
            (b_norm, fecha, abs(adelantos), f"Adelanto de dinero entregado por {b_norm}", f"Adelanto registrado para el cuadre ({fecha})")
        )

    if pendientes != 0:
        cursor.execute(
            """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
               VALUES (%s, %s, %s, %s, %s, 'PENDIENTE_BANQUERO', 'APROBADO')""",
            (b_norm, fecha, abs(pendientes), f"Saldo pendiente atrasado de {b_norm}", f"Pendiente de liquidación anterior ({fecha})")
        )

    conn.commit()
    conn.close()

    url_retorno = f"/admin?tab=desglose_banca&desde_fecha={desde_fecha or ''}&hasta_fecha={hasta_fecha or ''}"
    return RedirectResponse(url=url_retorno, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/guardar-reporte-colab")
async def guardar_reporte_colab(request: Request):
    data = await request.form()
    agencia_raw = data.get("agencia", "")
    agencia = normalizar(agencia_raw)
    fecha = data.get("fecha", "")
    monto = float(data.get("monto", 0.0))
    ventas = float(data.get("ventas", 0.0))
    premios = float(data.get("premios", 0.0))
    detalle_html = data.get("detalle_html", "")
    cashea_monto = float(data.get("cashea_monto", 0.0))
    cashea_detalle = data.get("cashea_detalle", "")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO usuarios (agencia, clave, genero, rol) VALUES (%s, '123456', 'FEMENINO', 'TAQUILLA') ON CONFLICT (agencia) DO NOTHING", (agencia,))

    cursor.execute("SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s", (agencia, fecha))
    rep = cursor.fetchone()

    if rep:
        cursor.execute(
            "UPDATE reportes SET agencia = %s, monto = %s, ventas = %s, premios = %s, detalle_html = %s WHERE id = %s",
            (agencia, monto, ventas, premios, detalle_html, rep['id'])
        )
    else:
        cursor.execute(
            "INSERT INTO reportes (agencia, fecha, monto, ventas, premios, detalle_html) VALUES (%s, %s, %s, %s, %s, %s)",
            (agencia, fecha, monto, ventas, premios, detalle_html)
        )

    if cashea_monto > 0:
        cursor.execute("SELECT id FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s AND tipo = 'CASHEA'", (agencia, fecha))
        cashea_db = cursor.fetchone()
        if cashea_db:
            cursor.execute(
                "UPDATE pagos SET agencia = %s, monto = %s, factura = %s, comprobante = %s WHERE id = %s",
                (agencia, cashea_monto, cashea_detalle, cashea_detalle, cashea_db['id'])
            )
        else:
            cursor.execute(
                "INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, %s, %s, 'CASHEA', 'APROBADO')",
                (agencia, fecha, cashea_monto, cashea_detalle, cashea_detalle)
            )

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia, fecha)

    cuenta_act = obtener_cuenta_agencia_corte(agencia, fecha)
    saldo_taquilla = cuenta_act["saldo_final"]
    if saldo_taquilla > 0:
        texto_saldo = f"Total a pagar a la banca: Bs. {saldo_taquilla:,.2f}"
    elif saldo_taquilla < 0:
        texto_saldo = f"Tienes saldo a favor: Bs. {abs(saldo_taquilla):,.2f}"
    else:
        texto_saldo = "Tu cuenta se encuentra saldada (0.00 Bs.)"

    disparar_notificacion(
        agencia,
        "📊 Reporte del Día Cargado",
        f"Tu reporte del {fecha} ya está listo en tu panel. {texto_saldo}"
    )

    return {"status": "ok", "mensaje": "Reporte actualizado con éxito"}

@app.post("/api/guardar-conciliacion-colab")
def guardar_conciliacion_colab(
    agencia: str = Form(...),
    desde_fecha: str = Form(...),
    hasta_fecha: str = Form(...),
    resumen: str = Form("{}"),
    detalle: str = Form("[]")
):
    agencia_norm = normalizar(agencia)

    try:
        data_resumen = json.loads(resumen)
    except Exception:
        data_resumen = {}

    total_reportado = float(data_resumen.get("total_reportado", 0.0) or 0.0)
    total_pagado = float(data_resumen.get("total_pagado", 0.0) or 0.0)
    total_sistema = float(data_resumen.get("total_sistema", 0.0) or 0.0)
    diferencia = float(data_resumen.get("diferencia", 0.0) or 0.0)

    conn = get_db()
    cursor = conn.cursor()

    is_postgres = bool(os.environ.get("DATABASE_URL"))

    if is_postgres:
        cursor.execute("""
            INSERT INTO conciliaciones_semanales (agencia, desde_fecha, hasta_fecha, total_reportado, total_pagado, total_sistema, diferencia, detalle_dias)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (agencia, desde_fecha, hasta_fecha)
            DO UPDATE SET total_reportado = EXCLUDED.total_reportado,
                          total_pagado = EXCLUDED.total_pagado,
                          total_sistema = EXCLUDED.total_sistema,
                          diferencia = EXCLUDED.diferencia,
                          detalle_dias = EXCLUDED.detalle_dias
        """, (agencia_norm, desde_fecha, hasta_fecha, total_reportado, total_pagado, total_sistema, diferencia, detalle))
    else:
        cursor.execute("""
            INSERT INTO conciliaciones_semanales (agencia, desde_fecha, hasta_fecha, total_reportado, total_pagado, total_sistema, diferencia, detalle_dias)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (agencia, desde_fecha, hasta_fecha)
            DO UPDATE SET total_reportado = excluded.total_reportado,
                          total_pagado = excluded.total_pagado,
                          total_sistema = excluded.total_sistema,
                          diferencia = excluded.diferencia,
                          detalle_dias = excluded.detalle_dias
        """, (agencia_norm, desde_fecha, hasta_fecha, total_reportado, total_pagado, total_sistema, diferencia, detalle))

    conn.commit()
    conn.close()

    return {"status": "ok", "mensaje": f"Conciliación guardada para {agencia_norm}"}

@app.get("/api/obtener-historico-semana")
def obtener_historico_semana(agencia: str, desde: str, hasta: str):
    ag_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT detalle_html FROM reportes 
        WHERE UPPER(TRIM(agencia)) = %s AND fecha >= %s AND fecha <= %s
    """, (ag_norm, desde, hasta))
    reps = cursor.fetchall()
    conn.close()

    sistemas_cobrados = {}
    
    for rep in reps:
        html = rep['detalle_html'] or ""
        html_limpio = html.split('<!-- BLOQUES_EXTRAS -->')[0]
        tablas = re.findall(r'<table[^>]*>(.*?)<\/table>', html_limpio, re.DOTALL | re.IGNORECASE)
        for t in tablas:
            filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', t, re.DOTALL | re.IGNORECASE)
            for f in filas:
                cols = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', f, re.DOTALL | re.IGNORECASE)
                if len(cols) >= 5:
                    sys_raw = re.sub(r'<[^>]+>', '', cols[0]).strip()
                    if not sys_raw or "SISTEMA" in sys_raw.upper() or "TOTALES" in sys_raw.upper() or "TRIPLETA" in sys_raw.upper():
                        continue
                    
                    sys_name = normalizar_sistema(sys_raw)
                    try:
                        v = float(re.sub(r'[^\d.-]', '', cols[1]))
                        c = float(re.sub(r'[^\d.-]', '', cols[2]))
                        p = float(re.sub(r'[^\d.-]', '', cols[3]))
                        neto = float(re.sub(r'[^\d.-]', '', cols[4]))
                    except Exception:
                        v, c, p, neto = 0.0, 0.0, 0.0, 0.0

                    if sys_name not in sistemas_cobrados:
                        sistemas_cobrados[sys_name] = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
                    
                    sistemas_cobrados[sys_name]["venta"] += v
                    sistemas_cobrados[sys_name]["comision"] += c
                    sistemas_cobrados[sys_name]["premio"] += p
                    sistemas_cobrados[sys_name]["neto"] += neto

    return {"sistemas": sistemas_cobrados}

@app.get("/api/lista-negra")
def api_obtener_lista_negra(q: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    if q and q.strip():
        termino = f"%{q.strip().upper()}%"
        cursor.execute("""
            SELECT * FROM lista_negra 
            WHERE UPPER(cedula) LIKE %s 
               OR UPPER(telefonos) LIKE %s 
               OR UPPER(nombre) LIKE %s 
            ORDER BY id DESC
        """, (termino, termino, termino))
    else:
        cursor.execute("SELECT * FROM lista_negra ORDER BY id DESC")
    
    filas = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    for f in filas:
        if f.get('fecha_registro'):
            f['fecha_str'] = str(f['fecha_registro'])[:16]
    return filas

@app.post("/api/lista-negra/guardar")
async def api_guardar_lista_negra(
    nombre: str = Form(...),
    cedula: Optional[str] = Form(""),
    telefonos: str = Form(...),
    rol_estafador: str = Form(...),
    descripcion: str = Form(...),
    agencia_reporta: str = Form(...),
    evidencias_files: List[UploadFile] = File(default=[])
):
    evidencias_data = []
    
    for file in evidencias_files:
        if file.filename:
            contenido = await file.read()
            mime = file.content_type or "image/jpeg"
            b64_str = base64.b64encode(contenido).decode('utf-8')
            data_url = f"data:{mime};base64,{b64_str}"
            evidencias_data.append(data_url)

    evidencias_json = json.dumps(evidencias_data)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO lista_negra (nombre, cedula, telefonos, rol_estafador, descripcion, evidencias, reportado_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        nombre.strip().upper(),
        cedula.strip().upper() if cedula else "N/A",
        telefonos.strip(),
        rol_estafador.strip().upper(),
        descripcion.strip(),
        evidencias_json,
        normalizar(agencia_reporta)
    ))
    conn.commit()
    conn.close()

    disparar_notificacion(
        "TODAS",
        "🚨 NUEVO REPORTE EN LISTA NEGRA",
        f"Se ha boletinado a: {nombre.upper()} ({rol_estafador}) - C.I: {cedula or 'N/A'}"
    )

    return {"status": "ok", "mensaje": "Estafador fichado con imágenes permanentes."}

@app.post("/api/banquero/crear-taquilla-listanegra")
def api_crear_taquilla_listanegra(
    nombre_real: str = Form(...),
    cedula: str = Form(...),
    agencia: str = Form(...),
    clave: str = Form("123456"),
    creado_por: str = Form(...)
):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO usuarios (agencia, clave, genero, rol, nombre_real, cedula, estado, recomendado_por)
        VALUES (%s, %s, 'FEMENINO', 'SOLO_LISTA_NEGRA', %s, %s, 'ACTIVO', %s)
        ON CONFLICT (agencia) DO UPDATE 
        SET clave = EXCLUDED.clave, rol = 'SOLO_LISTA_NEGRA', estado = 'ACTIVO', nombre_real = EXCLUDED.nombre_real, cedula = EXCLUDED.cedula
    """, (agencia_norm, clave.strip(), nombre_real.strip().upper(), cedula.strip().upper(), creado_por))
    
    mensaje = f"Taquilla {agencia_norm} (C.I: {cedula}) habilitada para Lista Negra por {creado_por}."
    try:
        cursor.execute("INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, 'ADMIN')", (mensaje,))
    except Exception:
        pass

    conn.commit()
    conn.close()
    
    return {"status": "ok", "mensaje": f"Taquilla '{agencia_norm}' creada exitosamente con acceso único a Lista Negra."}

@app.post("/banquero/guardar-ajustes-cuenta")
def post_banquero_guardar_ajustes_cuenta(
    banquero: str = Form(...),
    fecha: str = Form(...),
    adelantos: float = Form(0.0),
    pendientes: float = Form(0.0),
    desde_fecha: Optional[str] = Form(None),
    hasta_fecha: Optional[str] = Form(None),
    usuario: str = Form(...)
):
    b_norm = normalizar_nombre_banquero(banquero)
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO ajustes_globales_banqueros (banquero, fecha, adelantos, pendientes)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (banquero, fecha)
           DO UPDATE SET adelantos = EXCLUDED.adelantos, pendientes = EXCLUDED.pendientes""",
        (b_norm, fecha, adelantos, pendientes)
    )

    cursor.execute(
        "DELETE FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s AND tipo IN ('ADELANTO_BANQUERO', 'PENDIENTE_BANQUERO')",
        (b_norm, fecha)
    )

    if adelantos != 0:
        cursor.execute(
            """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
               VALUES (%s, %s, %s, %s, %s, 'ADELANTO_BANQUERO', 'APROBADO')""",
            (b_norm, fecha, abs(adelantos), f"Adelanto reportado por {b_norm}", f"Adelanto registrado el {fecha}")
        )

    if pendientes != 0:
        cursor.execute(
            """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
               VALUES (%s, %s, %s, %s, %s, 'PENDIENTE_BANQUERO', 'APROBADO')""",
            (b_norm, fecha, abs(pendientes), f"Atraso/Pendiente de {b_norm}", f"Pendiente registrado el {fecha}")
        )

    conn.commit()
    conn.close()

    url_retorno = f"/banquero?usuario={usuario}&desde_fecha={desde_fecha or ''}&hasta_fecha={hasta_fecha or ''}"
    return RedirectResponse(url=url_retorno, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/banquero/guardar-ajuste-sistema")
def post_banquero_guardar_ajuste_sistema(
    banquero: str = Form(...),
    sistema: str = Form(...),
    fecha: str = Form(...),
    venta: float = Form(...),
    comision: float = Form(...),
    premios: float = Form(...),
    desde_fecha: Optional[str] = Form(None),
    hasta_fecha: Optional[str] = Form(None),
    usuario: str = Form(...)
):
    b_norm = normalizar_nombre_banquero(banquero)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO ajustes_banqueros_manuales (banquero, sistema, fecha, venta, comision, premios)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (banquero, sistema, fecha) 
           DO UPDATE SET venta = EXCLUDED.venta, comision = EXCLUDED.comision, premios = EXCLUDED.premios""",
        (b_norm, sistema, fecha, venta, comision, premios)
    )
    conn.commit()
    conn.close()

    url_retorno = f"/banquero?usuario={usuario}&desde_fecha={desde_fecha or ''}&hasta_fecha={hasta_fecha or ''}"
    return RedirectResponse(url=url_retorno, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/registro-lista-negra", response_class=HTMLResponse)
def get_registro_lista_negra(request: Request, ref: Optional[str] = None):
    return templates.TemplateResponse(request=request, name="registro_lista_negra.html", context={"ref": ref or "AGENCIA EXTERNA"})

@app.post("/registro-lista-negra")
def post_registro_lista_negra(
    nombre_real: str = Form(...),
    cedula: str = Form(...),
    telefono: str = Form(...),
    agencia: str = Form(...),
    clave: str = Form(...),
    recomendado_por: Optional[str] = Form("DIRECTO")
):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM usuarios WHERE UPPER(TRIM(agencia)) = %s", (agencia_norm,))
    existe = cursor.fetchone()
    if existe:
        conn.close()
        return HTMLResponse("<script>alert('Ese nombre de agencia ya está en uso. Elige otro.'); window.history.back();</script>")

    cursor.execute("""
        INSERT INTO usuarios (agencia, clave, genero, rol, nombre_real, cedula, telefono, estado, recomendado_por)
        VALUES (%s, %s, 'FEMENINO', 'SOLO_LISTA_NEGRA', %s, %s, %s, 'PENDIENTE', %s)
    """, (agencia_norm, clave.strip(), nombre_real.strip().upper(), cedula.strip().upper(), telefono.strip(), recomendado_por))

    conn.commit()
    conn.close()

    disparar_notificacion("ADMIN", "🛡️ Nueva Solicitud Lista Negra", f"{nombre_real} ({agencia_norm}) solicitó acceso a la Lista Negra.")

    return HTMLResponse("""
        <script>
            alert('¡Solicitud enviada con éxito! La administración revisará tus datos y activará tu acceso pronto.');
            window.location.href = '/login';
        </script>
    """)

@app.post("/admin/crear-taquilla-listanegra")
def post_admin_crear_taquilla_ln(
    nombre_real: str = Form(...),
    cedula: str = Form(...),
    telefono: str = Form(...),
    agencia: str = Form(...),
    clave: str = Form(...)
):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO usuarios (agencia, clave, genero, rol, nombre_real, cedula, telefono, estado, recomendado_por)
        VALUES (%s, %s, 'FEMENINO', 'SOLO_LISTA_NEGRA', %s, %s, %s, 'ACTIVO', 'ADMIN')
        ON CONFLICT (agencia) DO UPDATE 
        SET clave = EXCLUDED.clave, rol = 'SOLO_LISTA_NEGRA', estado = 'ACTIVO', nombre_real = EXCLUDED.nombre_real, cedula = EXCLUDED.cedula, telefono = EXCLUDED.telefono
    """, (agencia_norm, clave.strip(), nombre_real.strip().upper(), cedula.strip().upper(), telefono.strip()))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin?tab=listanegra", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/aprobar-taquilla-ln")
def post_aprobar_taquilla_ln(usuario_id: int = Form(...), accion: str = Form(...)):
    conn = get_db()
    cursor = conn.cursor()
    if accion == "APROBAR":
        cursor.execute("UPDATE usuarios SET estado = 'ACTIVO', rol = 'SOLO_LISTA_NEGRA' WHERE id = %s", (usuario_id,))
    else:
        cursor.execute("DELETE FROM usuarios WHERE id = %s", (usuario_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin?tab=listanegra", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
def post_login(request: Request, usuario: Optional[str] = Form(None), clave: Optional[str] = Form(None)):
    if not usuario or not clave:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Ingresa usuario y clave"})

    usuario_norm = normalizar(usuario)

    if usuario_norm == "ADMIN" and clave == "admin123":
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value="ADMIN")
        return response

    if usuario_norm in BANQUEROS_FIJOS:
        if BANQUEROS_FIJOS[usuario_norm]["clave"] == clave.strip():
            response = RedirectResponse(url=f"/banquero?usuario={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
            response.set_cookie(key="user", value=usuario_norm)
            return response
        else:
            return templates.TemplateResponse(request=request, name="login.html", context={"error": "Usuario o clave incorrectos"})

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE UPPER(TRIM(agencia)) = %s", (usuario_norm,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data and user_data['clave'] == clave:
        if user_data.get('estado') == 'PENDIENTE':
            return templates.TemplateResponse(request=request, name="login.html", context={
                "error": "Tu cuenta está pendiente de aprobación por la administración."
            })

        actualizar_ultima_conexion(usuario_norm)
        
        if user_data.get('rol') == 'SOLO_LISTA_NEGRA':
            response = RedirectResponse(url=f"/agencia?nombre={usuario_norm}&tab=listanegra", status_code=status.HTTP_303_SEE_OTHER)
            response.set_cookie(key="user", value=usuario_norm)
            return response

        response = RedirectResponse(url=f"/agencia?nombre={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value=usuario_norm)
        return response

    return templates.TemplateResponse(request=request, name="login.html", context={"error": "Usuario o clave incorrectos"})

@app.get("/banquero", response_class=HTMLResponse)
def get_banquero(
    request: Request, 
    usuario: Optional[str] = None, 
    desde_fecha: Optional[str] = None, 
    hasta_fecha: Optional[str] = None,
    tab: Optional[str] = "liquidacion"
):
    if not usuario:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    usr_norm = normalizar(usuario)
    
    if usr_norm not in BANQUEROS_FIJOS:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    nombre_comercializadora = BANQUEROS_FIJOS[usr_norm]["comercializadora"]
    hoy_vzla = obtener_fecha_venezuela()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT fecha FROM reportes ORDER BY id DESC LIMIT 1")
    ultima_fila = cursor.fetchone()
    conn.close()
    
    fecha_bd_reciente = ultima_fila['fecha'] if (ultima_fila and ultima_fila['fecha']) else hoy_vzla
    f_desde = desde_fecha if desde_fecha else fecha_bd_reciente
    f_hasta = hasta_fecha if hasta_fecha else fecha_bd_reciente

    (
        sistemas_consolidados,
        _,
        totales_generales,
        totales_auxiliares,
        desglose_banqueros,
        _, _, _, _
    ) = calcular_desglose_banqueros_datos(f_desde, f_hasta)

    cuadro_banquero = desglose_banqueros.get(nombre_comercializadora, {
        "sistemas": [],
        "cashea_descontado": 0.0,
        "adelantos_banquero": 0.0,
        "pendientes_banquero": 0.0,
        "total_a_pagar_banquero": 0.0
    })

    sistemas_filtrados = []
    for sys in cuadro_banquero.get("sistemas", []):
        sistemas_filtrados.append({
            "sistema": sys.get("sistema"),
            "venta": sys.get("venta", 0.0),
            "premios": sys.get("premios", 0.0),
            "comision": sys.get("comision_banquero", 0.0),
            "total_sistema": sys.get("total_sistema", 0.0),
            "participacion": sys.get("monto_participacion", 0.0),
            "total_final": sys.get("total_final", 0.0)
        })

    cuadro_seguro = {
        "sistemas": sistemas_filtrados,
        "cashea_descontado": cuadro_banquero.get("cashea_descontado", 0.0),
        "adelantos_banquero": cuadro_banquero.get("adelantos_banquero", 0.0),
        "pendientes_banquero": cuadro_banquero.get("pendientes_banquero", 0.0),
        "total_a_pagar": cuadro_banquero.get("total_a_pagar_banquero", 0.0)
    }

    return templates.TemplateResponse(request=request, name="banquero.html", context={
        "usuario": usr_norm,
        "nombre_comercializadora": nombre_comercializadora,
        "cuadro": cuadro_seguro,
        "desde_fecha": f_desde,
        "hasta_fecha": f_hasta,
        "tab_activa": tab or "liquidacion"
    })

@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(
    request: Request, 
    nombre: Optional[str] = None, 
    desde_fecha: Optional[str] = None, 
    hasta_fecha: Optional[str] = None, 
    tab: Optional[str] = "pendiente"
):
    if not nombre:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    agencia_norm = normalizar(nombre)
    hoy_vzla = obtener_fecha_venezuela()

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM usuarios WHERE UPPER(TRIM(agencia)) = %s", (agencia_norm,))
    agencia_info = cursor.fetchone()
    
    genero_agencia = "FEMENINO"
    if agencia_info and agencia_info.get('genero'):
        genero_agencia = str(agencia_info['genero']).strip().upper()
    
    cursor.execute("SELECT fecha FROM reportes WHERE UPPER(TRIM(agencia)) = %s ORDER BY fecha DESC LIMIT 1", (agencia_norm,))
    row_ult = cursor.fetchone()
    fecha_reporte_activa = hasta_fecha or hoy_vzla

    f_desde = desde_fecha if desde_fecha else ""
    f_hasta = hasta_fecha if hasta_fecha else ""

    if f_desde and f_hasta:
        cursor.execute(
            "SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND fecha >= %s AND fecha <= %s ORDER BY id DESC", 
            (agencia_norm, f_desde, f_hasta)
        )
        pagos_agencia = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            "SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND tipo = 'CASHEA' AND fecha >= %s AND fecha <= %s ORDER BY fecha DESC, id DESC",
            (agencia_norm, f_desde, f_hasta)
        )
    else:
        cursor.execute("SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s ORDER BY id DESC", (agencia_norm,))
        pagos_agencia = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            "SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND tipo = 'CASHEA' ORDER BY fecha DESC, id DESC",
            (agencia_norm,)
        )
    casheas_agencia = [dict(r) for r in cursor.fetchall()]
    total_cashea_periodo = sum(float(c['monto'] or 0.0) for c in casheas_agencia)
    
    cursor.execute(
        "SELECT SUM(monto) as total_dia FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND tipo = 'CASHEA' AND fecha = %s",
        (agencia_norm, fecha_reporte_activa)
    )
    row_cdia = cursor.fetchone()
    total_cashea_dia = float(row_cdia['total_dia'] or 0.0) if row_cdia else 0.0

    cursor.execute(
        "SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s AND fecha >= %s AND fecha <= %s ORDER BY fecha ASC", 
        (agencia_norm, f_desde or fecha_reporte_activa, f_hasta or fecha_reporte_activa)
    )
    reps_rango = cursor.fetchall()
    
    # --------------------------------------------------------------------------
    # AUDITORÍA CONSOLIDADA: 19 SISTEMAS OFICIALES EN EL ORDEN DEL CUADRO AZUL
    # --------------------------------------------------------------------------
    auditoria_sistemas_agencia = {
        s: {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
        for s in SISTEMAS_OFICIALES
    }
    totales_auditoria = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
    
    for rep_item in reps_rango:
        if rep_item and rep_item['detalle_html']:
            detalle_limpio = rep_item['detalle_html'].split('<!-- BLOQUES_EXTRAS -->')[0]
            t_match = re.search(r'<table[^>]*>(.*?)<\/table>', detalle_limpio, re.DOTALL | re.IGNORECASE)
            if t_match:
                filas_s = re.findall(r'<tr[^>]*>(.*?)<\/tr>', t_match.group(1), re.DOTALL | re.IGNORECASE)
                for fs in filas_s:
                    cols_s = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', fs, re.DOTALL | re.IGNORECASE)
                    if len(cols_s) >= 5:
                        s_raw = re.sub(r'<[^>]+>', '', cols_s[0]).strip()
                        
                        if not s_raw or "SISTEMA" in s_raw.upper() or "TOTALES" in s_raw.upper() or "TRIPLETA" in s_raw.upper():
                            continue
                        
                        s_name = normalizar_sistema(s_raw)

                        try:
                            sv = float(re.sub(r'[^\d.-]', '', cols_s[1]))
                            sc = float(re.sub(r'[^\d.-]', '', cols_s[2]))
                            sp = float(re.sub(r'[^\d.-]', '', cols_s[3]))
                            st = float(re.sub(r'[^\d.-]', '', cols_s[4]))
                        except Exception:
                            sv, sc, sp, st = 0.0, 0.0, 0.0, 0.0
                        
                        if s_name not in auditoria_sistemas_agencia:
                            auditoria_sistemas_agencia[s_name] = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
                        
                        auditoria_sistemas_agencia[s_name]["venta"] += sv
                        auditoria_sistemas_agencia[s_name]["comision"] += sc
                        auditoria_sistemas_agencia[s_name]["premio"] += sp
                        auditoria_sistemas_agencia[s_name]["neto"] += st
                        
                        totales_auditoria["venta"] += sv
                        totales_auditoria["comision"] += sc
                        totales_auditoria["premio"] += sp
                        totales_auditoria["neto"] += st

    cursor.execute(
        "SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND tipo = 'CASHEA' AND fecha >= %s AND fecha <= %s AND estado = 'APROBADO'",
        (agencia_norm, f_desde or fecha_reporte_activa, f_hasta or fecha_reporte_activa)
    )
    facturas_cashea_auditoria = [dict(r) for r in cursor.fetchall()]
    auditoria_cashea_monto = sum(float(c['monto'] or 0.0) for c in facturas_cashea_auditoria)

    try:
        cursor.execute(
            """SELECT c.* FROM comunicados c
               LEFT JOIN lecturas_comunicados l ON c.id = l.comunicado_id AND UPPER(TRIM(l.agencia)) = %s
               WHERE (c.agencia_destino = 'TODAS' OR UPPER(TRIM(c.agencia_destino)) = %s)
                 AND l.id IS NULL
               ORDER BY c.id DESC""",
            (agencia_norm, agencia_norm)
        )
        comunicados = [dict(row) for row in cursor.fetchall()]
    except Exception:
        cursor.execute("SELECT * FROM comunicados ORDER BY id DESC")
        comunicados = [dict(row) for row in cursor.fetchall()]

    cuenta_ag = obtener_cuenta_agencia_corte(agencia_norm)

    desglose_cuenta = {
        "fecha": hoy_vzla,
        "saldo_anterior": cuenta_ag["saldo_anterior"],
        "neto_hoy": cuenta_ag["neto_hoy"],
        "cashea_hoy": cuenta_ag["cashea_hoy"],
        "abonos_hoy": cuenta_ag["abonos_hoy"],
        "adelantos_hoy": cuenta_ag["adelantos_hoy"],
        "liquidaciones_hoy": cuenta_ag["liquidaciones_hoy"],
        "saldo_final": cuenta_ag["saldo_final"]
    }
    saldo_actual = cuenta_ag["saldo_final"]

    cursor.execute("SELECT id, fecha, monto, detalle_html FROM reportes WHERE UPPER(TRIM(agencia)) = %s ORDER BY fecha DESC", (agencia_norm,))
    reportes_agencia = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT * FROM conciliaciones_semanales 
        WHERE UPPER(TRIM(agencia)) = %s 
        ORDER BY id DESC LIMIT 1
    """, (agencia_norm,))
    row_concil = cursor.fetchone()

    if row_concil:
        try:
            detalle_conciliacion = json.loads(row_concil["detalle_dias"] or "[]")
        except Exception:
            detalle_conciliacion = []

        tot_v_cob = sum(float(item.get("venta_cobrada", 0)) for item in detalle_conciliacion)
        tot_p_cob = sum(float(item.get("premio_cobrado", 0)) for item in detalle_conciliacion)
        tot_v_rea = sum(float(item.get("venta_real", 0)) for item in detalle_conciliacion)
        tot_p_rea = sum(float(item.get("premio_real", 0)) for item in detalle_conciliacion)

        conciliacion_resumen = {
            "total_venta_cobrada": tot_v_cob,
            "total_premio_cobrado": tot_p_cob,
            "total_reportado": float(row_concil["total_reportado"] or 0.0),
            "total_venta_real": tot_v_rea,
            "total_premio_real": tot_p_rea,
            "total_sistema": float(row_concil["total_sistema"] or 0.0),
            "diferencia": float(row_concil["diferencia"] or 0.0)
        }
    else:
        conciliacion_resumen = {
            "total_venta_cobrada": 0.0,
            "total_premio_cobrado": 0.0,
            "total_reportado": 0.0,
            "total_venta_real": 0.0,
            "total_premio_real": 0.0,
            "total_sistema": 0.0,
            "diferencia": 0.0
        }
        detalle_conciliacion = []

    conn.close()
    
    return templates.TemplateResponse(request=request, name="agencia.html", context={
        "agencia": agencia_info,
        "nombre_agencia": agencia_norm,
        "genero": genero_agencia.lower(),
        "genero_agencia": genero_agencia,
        "reportes": reportes_agencia,
        "pagos": pagos_agencia,
        "casheas_agencia": casheas_agencia,
        "total_cashea_periodo": total_cashea_periodo,
        "total_cashea_dia": total_cashea_dia,
        "comunicados": comunicados,
        "sistemas": SISTEMAS_OFICIALES,
        "saldo_actual": saldo_actual,
        "desglose_cuenta": desglose_cuenta,
        "items_pendientes": reportes_agencia,
        "auditoria_sistemas": auditoria_sistemas_agencia,
        "totales_auditoria": totales_auditoria,
        "auditoria_cashea_monto": auditoria_cashea_monto,
        "facturas_cashea_auditoria": facturas_cashea_auditoria,
        "conciliacion_resumen": conciliacion_resumen,
        "detalle_conciliacion": detalle_conciliacion,
        "desde_fecha": f_desde,
        "hasta_fecha": f_hasta,
        "tab_activa": tab or "pendiente"
    })

@app.post("/admin/registrar-pago-rapido")
def post_registrar_pago_rapido(
    agencia: str = Form(...),
    accion: str = Form(...),
    monto: float = Form(...)
):
    agencia_norm = normalizar(agencia)
    monto_val = abs(float(monto))
    fecha_hoy = obtener_fecha_venezuela()

    if monto_val > 0:
        conn = get_db()
        cursor = conn.cursor()

        if accion == "PAGO":
            cursor.execute(
                """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
                   VALUES (%s, %s, %s, %s, %s, 'PAGO_BANCA', 'APROBADO')""",
                (agencia_norm, fecha_hoy, monto_val, f"Abono Admin ({fecha_hoy})", "Registrado directamente por la administración")
            )
            mensaje = f"Se ha registrado tu pago/abono de Bs. {monto_val:,.2f} a la administración."
        else:
            cursor.execute(
                """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
                   VALUES (%s, %s, %s, %s, %s, 'LIQUIDACION', 'APROBADO')""",
                (agencia_norm, fecha_hoy, monto_val, f"Liquidación Admin ({fecha_hoy})", "Pago transferido directamente por la administración")
            )
            mensaje = f"Se te ha emitido un pago/liquidación de Bs. {monto_val:,.2f} por parte de la administración."

        try:
            cursor.execute(
                "INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)",
                (mensaje, agencia_norm)
            )
        except Exception:
            cursor.execute("INSERT INTO comunicados (mensaje) VALUES (%s)", (mensaje,))

        conn.commit()
        conn.close()
        recalcular_y_actualizar_reporte(agencia_norm, fecha_hoy)
        disparar_notificacion(agencia_norm, "💳 Movimiento Registrado", mensaje)

    return RedirectResponse(url="/admin?tab=balances", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/saldar-deuda-taquilla")
def post_saldar_deuda_taquilla(
    agencia: str = Form(...),
    monto_restante: float = Form(...),
    fecha: Optional[str] = Form(None)
):
    agencia_norm = normalizar(agencia)
    fecha_operacion = fecha or obtener_fecha_venezuela()
    monto_val = abs(float(monto_restante))
    
    if monto_val > 0.01:
        conn = get_db()
        cursor = conn.cursor()
        
        if float(monto_restante) > 0:
            cursor.execute(
                """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
                   VALUES (%s, %s, %s, %s, %s, 'PAGO_BANCA', 'APROBADO')""",
                (agencia_norm, fecha_operacion, monto_val, f"Saldar Deuda #{fecha_operacion}", "Ajuste completo de saldo")
            )
        else:
            cursor.execute(
                """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
                   VALUES (%s, %s, %s, %s, %s, 'LIQUIDACION', 'APROBADO')""",
                (agencia_norm, fecha_operacion, monto_val, f"Liquidación Saldo #{fecha_operacion}", "Liquidación completa de saldo a favor")
            )

        conn.commit()
        conn.close()

        recalcular_y_actualizar_reporte(agencia_norm, fecha_operacion)
        disparar_notificacion(agencia_norm, "✅ Cuenta Saldada", f"Tu cuenta del {fecha_operacion} ha quedado saldada con éxito.")

    return RedirectResponse(url="/admin?tab=balances", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/ajustes/salida-dinero")
async def post_ajustes_salida_dinero(
    agencia: str = Form(...),
    fecha: str = Form(...),
    tipo_salida: str = Form(...),
    monto: float = Form(...),
    detalle: Optional[str] = Form(""),
    comprobante_file: Optional[UploadFile] = File(None)
):
    agencia_norm = normalizar(agencia)
    fecha_operacion = fecha or obtener_fecha_venezuela()
    monto_val = abs(float(monto))
    detalle_texto = detalle.strip() if detalle else ("Liquidación de saldo a favor" if tipo_salida == 'LIQUIDACION' else "Avance / Adelanto entregado")
    
    comprobante_valor = detalle_texto
    if comprobante_file and comprobante_file.filename:
        contenido = await comprobante_file.read()
        nombre_archivo = f"salida_{agencia_norm}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}_{comprobante_file.filename}"
        ruta_guardar = os.path.join("uploads", nombre_archivo)
        with open(ruta_guardar, "wb") as buffer:
            buffer.write(contenido)
        comprobante_valor = nombre_archivo
        if len(contenido) < 1500000:
            mime = comprobante_file.content_type or "image/jpeg"
            comprobante_valor = f"data:{mime};base64,{base64.b64encode(contenido).decode('utf-8')}"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, %s, 'APROBADO')""",
        (agencia_norm, fecha_operacion, monto_val, detalle_texto, comprobante_valor, tipo_salida)
    )

    if tipo_salida == 'LIQUIDACION':
        mensaje = f"✅ Tu saldo a favor de Bs. {monto_val:,.2f} ha sido LIQUIDADO por la administración."
        titulo_notif = "💸 Saldo Liquidado"
    else:
        mensaje = f"💵 Se ha registrado un adelanto/avance de dinero por Bs. {monto_val:,.2f} a tu cuenta."
        titulo_notif = "💵 Adelanto Registrado"

    try:
        cursor.execute("INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)", (mensaje, agencia_norm))
    except Exception:
        cursor.execute("INSERT INTO comunicados (mensaje) VALUES (%s)", (mensaje,))

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha_operacion)
    disparar_notificacion(agencia_norm, titulo_notif, mensaje)
    return RedirectResponse(url="/admin?tab=ajustes&msg=salida_exitosa", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/ajustes/registrar-pago-recibido")
async def post_ajustes_registrar_pago_recibido(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: float = Form(...),
    metodo_pago: str = Form("Efectivo"),
    detalle: Optional[str] = Form(""),
    comprobante_file: Optional[UploadFile] = File(None)
):
    agencia_norm = normalizar(agencia)
    fecha_operacion = fecha or obtener_fecha_venezuela()
    monto_val = abs(float(monto))
    detalle_texto = f"Pago recibido ({metodo_pago}): {detalle.strip() if detalle else 'Abono manual registrado por administración'}"

    comprobante_valor = detalle_texto
    if comprobante_file and comprobante_file.filename:
        contenido = await comprobante_file.read()
        nombre_archivo = f"recibido_{agencia_norm}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}_{comprobante_file.filename}"
        ruta_guardar = os.path.join("uploads", nombre_archivo)
        with open(ruta_guardar, "wb") as buffer:
            buffer.write(contenido)
        comprobante_valor = nombre_archivo
        if len(contenido) < 1500000:
            mime = comprobante_file.content_type or "image/jpeg"
            comprobante_valor = f"data:{mime};base64,{base64.b64encode(contenido).decode('utf-8')}"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'PAGO_BANCA', 'APROBADO')""",
        (agencia_norm, fecha_operacion, monto_val, detalle_texto, comprobante_valor)
    )

    mensaje = f"💰 Se ha acreditado a tu cuenta un pago de Bs. {monto_val:,.2f} ({metodo_pago}) registrado por administración."
    try:
        cursor.execute("INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)", (mensaje, agencia_norm))
    except Exception:
        cursor.execute("INSERT INTO comunicados (mensaje) VALUES (%s)", (mensaje,))

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha_operacion)
    disparar_notificacion(agencia_norm, "💳 Pago Recibido Registrado", mensaje)
    return RedirectResponse(url="/admin?tab=ajustes&msg=recibido_exitoso", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/agencia/cambiar-clave")
def post_cambiar_clave(agencia: str = Form(...), nueva_clave: str = Form(...), confirm_clave: str = Form(...)):
    agencia_norm = normalizar(agencia)
    if not nueva_clave or nueva_clave != confirm_clave:
        return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=cuenta&error=claves_no_coinciden", status_code=status.HTTP_303_SEE_OTHER)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET clave = %s WHERE UPPER(TRIM(agencia)) = %s", (nueva_clave.strip(), agencia_norm))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=cuenta&success=clave_actualizada", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/marcar-comunicado-leido")
def post_marcar_leido(comunicado_id: int = Form(...), agencia: str = Form(...)):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO lecturas_comunicados (comunicado_id, agencia, leido)
           VALUES (%s, %s, 1) ON CONFLICT (comunicado_id, agencia) DO NOTHING""",
        (comunicado_id, agencia_norm)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/solicitar-banca-directo")
def post_solicitar_banca_directo(
    agencia: str = Form(...), 
    fecha: str = Form(...), 
    monto: float = Form(...), 
    tipo_solicitud: Optional[str] = Form("SOLICITUD_SALDO")
):
    agencia_norm = normalizar(agencia)
    monto_abs = abs(monto)
    conn = get_db()
    cursor = conn.cursor()

    if tipo_solicitud == "AVANCE_PREMIOS":
        factura_texto = f"Solicitud Avance de Dinero ({fecha})"
        comp_texto = f"Avance solicitado por taquilla para premios/operatividad: Bs. {monto_abs:,.2f}"
        msg_admin = f"La taquilla {agencia_norm} solicitó un avance de dinero de Bs. {monto_abs:,.2f}."
    else:
        factura_texto = f"Solicitud Saldo del {fecha}"
        comp_texto = f"Solicitud de dinero: Bs. {monto_abs:,.2f}"
        msg_admin = f"La taquilla {agencia_norm} solicitó Bs. {monto_abs:,.2f} para liquidar saldo."

    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'SOLICITUD_BANCA', 'PENDIENTE')""",
        (agencia_norm, fecha, monto_abs, factura_texto, comp_texto)
    )
    conn.commit()
    conn.close()
    
    disparar_notificacion("ADMIN", "📩 Solicitud de Dinero Recibida", msg_admin)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=pendiente", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/reportar")
async def post_reportar(
    agencia: str = Form(...),
    fecha: str = Form(...),
    factura: str = Form(...),
    monto: float = Form(...),
    comprobante: UploadFile = File(...)
):
    agencia_norm = normalizar(agencia)
    contenido = await comprobante.read()
    
    nombre_archivo = f"pago_{agencia_norm}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}_{comprobante.filename}"
    ruta_guardar = os.path.join("uploads", nombre_archivo)
    with open(ruta_guardar, "wb") as buffer:
        buffer.write(contenido)

    comprobante_valor = nombre_archivo
    if len(contenido) < 1500000:
        mime_tipo = comprobante.content_type or "image/jpeg"
        comprobante_valor = f"data:{mime_tipo};base64,{base64.b64encode(contenido).decode('utf-8')}"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'PAGO_TAQUILLA', 'PENDIENTE')""",
        (agencia_norm, fecha, monto, factura, comprobante_valor)
    )
    conn.commit()
    conn.close()

    disparar_notificacion("ADMIN", "💰 Pago Reportado", f"{agencia_norm} ha reportado un pago de Bs. {monto:,.2f} con comprobante.")
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/solicitar-adelanto")
def post_solicitar_adelanto(agencia: str = Form(...), fecha: str = Form(...), monto: float = Form(...), observacion: str = Form(...)):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'ADELANTO', 'APROBADO')""",
        (agencia_norm, fecha, monto, observacion, f"Adelanto: {observacion}")
    )
    conn.commit()
    conn.close()
    
    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    disparar_notificacion("ADMIN", "💵 Adelanto Registrado", f"La taquilla {agencia_norm} registró un adelanto de Bs. {monto:,.2f}.")
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/actualizar-reporte-sistema")
def post_actualizar_reporte_sistema(
    agencia: str = Form(...),
    fecha: str = Form(...),
    sistema: str = Form(...),
    venta: float = Form(...),
    premio: float = Form(...),
    origen: Optional[str] = Form("agencia")
):
    agencia_norm = normalizar(agencia)
    sistema_norm = normalizar_sistema(sistema)

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s", (agencia_norm, fecha))
    rep = cursor.fetchone()
    
    if rep:
        html = rep['detalle_html'] or ""

        pct_com = 0.12
        sys_u = sistema_norm.upper()
        if "IMAGINARIA" in sys_u or "WINBIG" in sys_u:
            pct_com = 0.14
        elif "LOTTOLUCKY" in sys_u or "LOTIPOS" in sys_u or "GUACA" in sys_u:
            pct_com = 0.13
        elif "POZO" in sys_u:
            pct_com = 0.11
        elif "CALAMAR" in sys_u:
            pct_com = 0.14
        elif "PARLEY" in sys_u:
            pct_com = 0.10
        elif "PATRONUS" in sys_u:
            pct_com = 0.12
        elif "MASTER ACTIVO" in sys_u:
            pct_com = 0.13

        comision_nueva = venta * pct_com
        total_nuevo_sistema = venta - comision_nueva - premio

        patron_fila = rf'<tr[^>]*>\s*<td[^>]*>\s*{re.escape(sistema)}.*?<\/tr>'
        nueva_fila = f'''<tr>
            <td style="padding: 3px 2px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{sistema}</td>
            <td style="padding: 3px 2px; text-align: right;">{venta:,.2f}</td>
            <td style="padding: 3px 2px; text-align: right;">{comision_nueva:,.2f}</td>
            <td style="padding: 3px 2px; text-align: right;">{premio:,.2f}</td>
            <td style="padding: 3px 2px; text-align: right; font-weight: bold;">{total_nuevo_sistema:,.2f}</td>
        </tr>'''
        
        if re.search(patron_fila, html, flags=re.DOTALL | re.IGNORECASE):
            html_modificado = re.sub(patron_fila, nueva_fila, html, flags=re.DOTALL | re.IGNORECASE)
        else:
            patron_totales_detect = r'(<tr[^>]*>\s*<t[dh][^>]*>\s*TOTALES.*?<\/tr>)'
            if re.search(patron_totales_detect, html, flags=re.DOTALL | re.IGNORECASE):
                html_modificado = re.sub(patron_totales_detect, nueva_fila + r'\n\1', html, flags=re.DOTALL | re.IGNORECASE)
            else:
                html_modificado = html

        filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', html_modificado, re.DOTALL | re.IGNORECASE)
        sum_v, sum_c, sum_p, sum_t = 0.0, 0.0, 0.0, 0.0
        for f in filas:
            cols = re.findall(r'<td[^>]*>(.*?)<\/td>', f, re.DOTALL | re.IGNORECASE)
            if len(cols) >= 5:
                texto_col0 = re.sub(r'<[^>]+>', '', cols[0]).strip().upper()
                if texto_col0 and "TOTALES" not in texto_col0 and "SISTEMA" not in texto_col0 and "TRIPLETA" not in texto_col0:
                    try:
                        sum_v += float(re.sub(r'[^\d.-]', '', cols[1]))
                        sum_c += float(re.sub(r'[^\d.-]', '', cols[2]))
                        sum_p += float(re.sub(r'[^\d.-]', '', cols[3]))
                        sum_t += float(re.sub(r'[^\d.-]', '', cols[4]))
                    except Exception:
                        pass

        patron_totales_remplazo = r'<tr[^>]*>\s*<t[dh][^>]*>\s*TOTALES.*?<\/tr>'
        nueva_fila_totales = f'''<tr style="background: rgba(0,0,0,0.3); font-weight: bold; border-top: 1px solid var(--tech-border, #444);">
            <td style="padding: 4px 2px; font-size: 10.5px;">TOTALES</td>
            <td style="padding: 4px 2px; text-align: right;">{sum_v:,.2f}</td>
            <td style="padding: 4px 2px; text-align: right;">-</td>
            <td style="padding: 4px 2px; text-align: right;">{sum_p:,.2f}</td>
            <td style="padding: 4px 2px; text-align: right; color: var(--tech-secondary, #ffd700);">{sum_t:,.2f}</td>
        </tr>'''
        html_modificado = re.sub(patron_totales_remplazo, nueva_fila_totales, html_modificado, flags=re.DOTALL | re.IGNORECASE)

        cursor.execute(
            "UPDATE reportes SET detalle_html = %s, ventas = %s, premios = %s, monto = %s WHERE id = %s",
            (html_modificado, sum_v, sum_p, sum_t, rep['id'])
        )
        conn.commit()

        cursor.execute(
            "DELETE FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND (factura LIKE %s OR tipo = 'AJUSTE_PENDIENTE')",
            (agencia_norm, f"%Modif. {sistema}%")
        )

        cursor.execute(
            """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
               VALUES (%s, %s, %s, %s, %s, 'MODIFICACION', 'APROBADO')""",
            (agencia_norm, fecha, 0.0, f"Modif. {sistema} ({fecha})", f"Venta: Bs. {venta:,.2f} | Premio: Bs. {premio:,.2f}")
        )
        conn.commit()

    conn.close()
    recalcular_y_actualizar_reporte(agencia_norm, fecha)

    if origen == "admin":
        return RedirectResponse(url="/admin?tab=balances&msg=actualizado", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=modificaciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/eliminar-transaccion")
@app.post("/admin/eliminar-transaccion")
def post_eliminar_transaccion(pago_id: int = Form(...), redirect_to: Optional[str] = Form(None)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT agencia, fecha FROM pagos WHERE id = %s", (pago_id,))
    p_data = cursor.fetchone()
    if p_data:
        ag_elim = p_data['agencia']
        fe_elim = p_data['fecha']
        cursor.execute("DELETE FROM pagos WHERE id = %s", (pago_id,))
        conn.commit()
        recalcular_y_actualizar_reporte(ag_elim, fe_elim)
    conn.close()

    if redirect_to:
        return RedirectResponse(url=redirect_to, status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/procesar-solicitud-dinero")
async def post_procesar_solicitud_dinero(
    solicitud_id: int = Form(...),
    accion: str = Form(...),
    monto_abono: Optional[float] = Form(0.0),
    agencia: str = Form(...),
    fecha: str = Form(...),
    comprobante_file: Optional[UploadFile] = File(None)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos WHERE id = %s", (solicitud_id,))
    solicitud = cursor.fetchone()

    if solicitud:
        monto_original = float(solicitud['monto'] or 0.0)
        monto_pagar = monto_original if accion == "COMPLETO" else float(monto_abono or 0.0)
        agencia_norm = normalizar(agencia)
        fecha_solicitud = solicitud['fecha'] or fecha or obtener_fecha_venezuela()
        fecha_actual = obtener_fecha_venezuela()

        nombre_guardado = f"Liquidación Saldo #{solicitud_id}"
        if comprobante_file and comprobante_file.filename:
            contenido = await comprobante_file.read()
            ext = comprobante_file.filename.split('.')[-1]
            nombre_archivo = f"liquidacion_{solicitud_id}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}.{ext}"
            ruta_destino = os.path.join("uploads", nombre_archivo)
            with open(ruta_destino, "wb") as buffer:
                buffer.write(contenido)

            nombre_guardado = nombre_archivo
            if len(contenido) < 1500000:
                mime = comprobante_file.content_type or "image/jpeg"
                nombre_guardado = f"data:{mime};base64,{base64.b64encode(contenido).decode('utf-8')}"

        if accion == "COMPLETO":
            cursor.execute(
                """UPDATE pagos 
                   SET tipo = 'LIQUIDACION', 
                       estado = 'APROBADO', 
                       monto = %s, 
                       factura = %s, 
                       comprobante = %s 
                   WHERE id = %s""",
                (monto_pagar, f"Liquidación Completa ({fecha_solicitud})", nombre_guardado, solicitud_id)
            )
        else:
            monto_restante = max(0.0, monto_original - monto_pagar)
            if monto_restante > 0.009:
                cursor.execute("UPDATE pagos SET monto = %s WHERE id = %s", (monto_restante, solicitud_id))
            else:
                cursor.execute("UPDATE pagos SET estado = 'PROCESADO' WHERE id = %s", (solicitud_id,))
            
            cursor.execute(
                """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) 
                   VALUES (%s, %s, %s, %s, %s, 'LIQUIDACION', 'APROBADO')""",
                (agencia_norm, fecha_solicitud, monto_pagar, f"Liquidación Parcial ({fecha_solicitud})", nombre_guardado)
            )

        mensaje_com = f"Se te ha transferido Bs. {monto_pagar:,.2f} ({accion}) para saldar tu cuenta."
        try:
            cursor.execute(
                "INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)",
                (mensaje_com, agencia_norm)
            )
        except Exception:
            cursor.execute("INSERT INTO comunicados (mensaje) VALUES (%s)", (mensaje_com,))

        conn.commit()
        conn.close()

        recalcular_y_actualizar_reporte(agencia_norm, fecha_solicitud)
        if fecha_solicitud != fecha_actual:
            recalcular_y_actualizar_reporte(agencia_norm, fecha_actual)

        disparar_notificacion(agencia_norm, "💸 Liquidación Procesada", mensaje_com)
        return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

    conn.close()
    return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/validar-pago")
def post_validar_pago(solicitud_id: int = Form(...), accion: str = Form(...)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos WHERE id = %s", (solicitud_id,))
    pago = cursor.fetchone()

    if pago:
        agencia_p = normalizar(pago['agencia'])
        fecha_pago = pago['fecha']
        monto_p = float(pago['monto'] or 0.0)
        
        if accion == "APROBAR":
            cursor.execute("UPDATE pagos SET estado = 'APROBADO' WHERE id = %s", (solicitud_id,))
            msg_notif = f"Tu pago de Bs. {monto_p:,.2f} ha sido APROBADO y acreditado a tu cuenta."
        else:
            cursor.execute("UPDATE pagos SET estado = 'RECHAZADO' WHERE id = %s", (solicitud_id,))
            msg_notif = f"Tu pago de Bs. {monto_p:,.2f} ha sido RECHAZADO. Por favor verifica con la administración."

        try:
            cursor.execute(
                "INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)",
                (msg_notif, agencia_p)
            )
        except Exception:
            cursor.execute(
                "INSERT INTO comunicados (mensaje) VALUES (%s)",
                (msg_notif,)
            )

        conn.commit()
        conn.close()
        
        recalcular_y_actualizar_reporte(agencia_p, fecha_pago)
        disparar_notificacion(agencia_p, "🔔 Estado de Pago", msg_notif)
        return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

    conn.close()
    return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/liquidar-saldo-negativo")
async def post_liquidar_saldo_negativo(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: float = Form(...),
    comprobante_file: Optional[UploadFile] = File(None)
):
    agencia_norm = normalizar(agencia)
    fecha_operacion = fecha or obtener_fecha_venezuela()
    monto_pago = abs(monto)
    comprobante_valor = "Liquidación Directa Admin"

    if comprobante_file and comprobante_file.filename:
        contenido = await comprobante_file.read()
        nombre_archivo = f"liquidacion_negativo_{agencia_norm}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}_{comprobante_file.filename}"
        ruta_guardar = os.path.join("uploads", nombre_archivo)
        with open(ruta_guardar, "wb") as buffer:
            buffer.write(contenido)

        comprobante_valor = nombre_archivo
        if len(contenido) < 1500000:
            mime = comprobante_file.content_type or "image/jpeg"
            comprobante_valor = f"data:{mime};base64,{base64.b64encode(contenido).decode('utf-8')}"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'LIQUIDACION', 'APROBADO')""",
        (agencia_norm, fecha_operacion, monto_pago, "Liquidación Saldo a Favor", comprobante_valor)
    )

    mensaje = f"✅ Tu saldo a favor de Bs. {monto_pago:,.2f} ha sido LIQUIDADO."
    try:
        cursor.execute(
            "INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)",
            (mensaje, agencia_norm)
        )
    except Exception:
        cursor.execute("INSERT INTO comunicados (mensaje) VALUES (%s)", (mensaje,))

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha_operacion)
    disparar_notificacion(agencia_norm, "💸 Saldo Liquidado", mensaje)
    return RedirectResponse(url="/admin?tab=balances", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/actualizar-regla-banquero")
def post_actualizar_regla_banquero(
    regla_id: int = Form(...),
    pct_banquero: float = Form(...),
    pct_taquilla: float = Form(...),
    pct_participacion: float = Form(...),
    desde_fecha: Optional[str] = Form(None),
    hasta_fecha: Optional[str] = Form(None)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE configuracion_banqueros 
           SET pct_banquero = %s, pct_taquilla = %s, pct_participacion = %s
           WHERE id = %s""",
        (pct_banquero / 100.0, pct_taquilla / 100.0, pct_participacion / 100.0, regla_id)
    )
    conn.commit()
    conn.close()

    url_retorno = f"/admin?tab=desglose_banca&desde_fecha={desde_fecha or ''}&hasta_fecha={hasta_fecha or ''}"
    return RedirectResponse(url=url_retorno, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/guardar-ajuste-banquero-sistema")
def post_guardar_ajuste_banquero-sistema(
    banquero: str = Form(...),
    sistema: str = Form(...),
    fecha: str = Form(...),
    venta: float = Form(...),
    comision: float = Form(...),
    premios: float = Form(...),
    desde_fecha: Optional[str] = Form(None),
    hasta_fecha: Optional[str] = Form(None)
):
    b_norm = normalizar_nombre_banquero(banquero)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO ajustes_banqueros_manuales (banquero, sistema, fecha, venta, comision, premios)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (banquero, sistema, fecha) 
           DO UPDATE SET venta = EXCLUDED.venta, comision = EXCLUDED.comision, premios = EXCLUDED.premios""",
        (b_norm, sistema, fecha, venta, comision, premios)
    )
    conn.commit()
    conn.close()

    url_retorno = f"/admin?tab=desglose_banca&desde_fecha={desde_fecha or ''}&hasta_fecha={hasta_fecha or ''}"
    return RedirectResponse(url=url_retorno, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/restablecer-ajuste-banquero-sistema")
def post_restablecer_ajuste_banquero_sistema(
    banquero: str = Form(...),
    sistema: str = Form(...),
    desde_fecha: Optional[str] = Form(None),
    hasta_fecha: Optional[str] = Form(None)
):
    b_norm = normalizar_nombre_banquero(banquero)
    if sistema.upper() in ["GUACA", "CALAMAR"]:
        url_retorno = f"/admin?tab=desglose_banca&desde_fecha={desde_fecha or ''}&hasta_fecha={hasta_fecha or ''}"
        return RedirectResponse(url=url_retorno, status_code=status.HTTP_303_SEE_OTHER)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM ajustes_banqueros_manuales WHERE (banquero = %s OR banquero = %s) AND sistema = %s",
        (b_norm, b_norm.replace("COMERCIALIZADORA ", ""), sistema)
    )
    conn.commit()
    conn.close()

    url_retorno = f"/admin?tab=desglose_banca&desde_fecha={desde_fecha or ''}&hasta_fecha={hasta_fecha or ''}"
    return RedirectResponse(url=url_retorno, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/crear-comunicado")
@app.post("/admin/comunicado")
def post_comunicado(mensaje: str = Form(...)):
    if mensaje and mensaje.strip():
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, 'TODAS')", (mensaje.strip(),))
        except Exception:
            cursor.execute("INSERT INTO comunicados (mensaje) VALUES (%s)", (mensaje.strip(),))
        conn.commit()
        conn.close()
        disparar_notificacion("TODAS", "📢 Comunicado Los Ángeles del Dinero", mensaje.strip())
    return RedirectResponse(url="/admin?tab=notificaciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/eliminar-comunicado")
def post_eliminar_comunicado(comunicado_id: int = Form(...)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM comunicados WHERE id = %s", (comunicado_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin?tab=notificaciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/crear-agencia")
@app.post("/admin/crear-taquilla")
def post_crear_agencia(agencia: str = Form(...), clave: str = Form(...), genero: str = Form("FEMENINO")):
    agencia_norm = normalizar(agencia)
    if agencia_norm and clave:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO usuarios (agencia, clave, genero, rol) VALUES (%s, %s, %s, 'TAQUILLA')
               ON CONFLICT (agencia) DO UPDATE SET clave = EXCLUDED.clave, genero = EXCLUDED.genero, rol = 'TAQUILLA'""",
            (agencia_norm, clave, genero)
        )
        conn.commit()
        conn.close()
    return RedirectResponse(url="/admin?tab=taquillas", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/eliminar-agencia")
def post_eliminar_agencia(agencia_id: int = Form(...)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE id = %s", (agencia_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin?tab=taquillas", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin", response_class=HTMLResponse)
def get_admin(
    request: Request, 
    agencia: Optional[str] = None, 
    desde_fecha: Optional[str] = None, 
    hasta_fecha: Optional[str] = None, 
    tipo_transaccion: Optional[str] = None, 
    tab: str = "balances"
):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reportes ORDER BY id DESC")
        reportes = [dict(row) for row in cursor.fetchall()]
        
        query_pagos = "SELECT * FROM pagos WHERE tipo != 'CASHEA' AND tipo != 'AJUSTE_SALDO_ANTERIOR'"
        params_pagos = []
        if tipo_transaccion:
            if tipo_transaccion == 'RECIBIDOS':
                query_pagos += " AND tipo IN ('PAGO_TAQUILLA', 'PAGO_BANCA', 'AJUSTE_BANCA')"
            elif tipo_transaccion == 'ENVIADOS':
                query_pagos += " AND tipo IN ('LIQUIDACION')"
            elif tipo_transaccion == 'ADELANTOS':
                query_pagos += " AND tipo IN ('ADELANTO', 'ADELANTO_BANQUERO')"
            elif tipo_transaccion == 'MODIFICACIONES':
                query_pagos += " AND tipo = 'MODIFICACION'"
            elif tipo_transaccion == 'SOLICITUDES':
                query_pagos += " AND tipo = 'SOLICITUD_BANCA'"
        query_pagos += " ORDER BY id DESC"
        cursor.execute(query_pagos, tuple(params_pagos))
        pagos = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM usuarios ORDER BY id DESC")
        agencias = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM usuarios WHERE estado = 'PENDIENTE' AND rol = 'SOLO_LISTA_NEGRA' ORDER BY id DESC")
        solicitudes_ln_pendientes = [dict(r) for r in cursor.fetchall()]
        
        try:
            cursor.execute("SELECT * FROM comunicados WHERE agencia_destino = 'TODAS' ORDER BY id DESC")
            comunicados = [dict(row) for row in cursor.fetchall()]
        except Exception:
            cursor.execute("SELECT * FROM comunicados ORDER BY id DESC")
            comunicados = [dict(row) for row in cursor.fetchall()]

        hoy_vzla = obtener_fecha_venezuela()
        lunes_sem, domingo_sem = obtener_rango_semana_actual()
        
        if tab in ['totalizador', 'desglose_banca', 'conciliacion_admin'] and not desde_fecha and not hasta_fecha:
            f_desde = lunes_sem
            f_hasta = domingo_sem
        else:
            f_desde = desde_fecha if desde_fecha else hoy_vzla
            f_hasta = hasta_fecha if hasta_fecha else hoy_vzla

        agencia_filtro = agencia if agencia else ""

        cursor.execute("SELECT * FROM pagos WHERE estado = 'PENDIENTE' ORDER BY id DESC")
        solicitudes_pendientes = [dict(r) for r in cursor.fetchall()]
        solicitudes_pendientes_count = len(solicitudes_pendientes)

        if agencia_filtro:
            cursor.execute("SELECT * FROM pagos WHERE tipo = 'CASHEA' AND UPPER(TRIM(agencia)) = %s AND fecha >= %s AND fecha <= %s ORDER BY id DESC", (normalizar(agencia_filtro), f_desde, f_hasta))
        else:
            cursor.execute("SELECT * FROM pagos WHERE tipo = 'CASHEA' AND fecha >= %s AND fecha <= %s ORDER BY id DESC", (f_desde, f_hasta))
        casheas_generales = [dict(row) for row in cursor.fetchall()]
        total_cashea_filtrado = sum(float(c.get('monto') or 0.0) for c in casheas_generales)

        positivos = []
        negativos = []
        for ag in agencias:
            if ag.get('rol') in ['BANQUERO', 'SOLO_LISTA_NEGRA']:
                continue
            ag_nombre = ag['agencia']
            
            cuenta_taquilla = obtener_cuenta_agencia_corte(ag_nombre)
            balance_contable = cuenta_taquilla["saldo_final"]

            ag['saldo_pendiente'] = balance_contable
            
            datos_desglose = {
                "agencia": ag_nombre,
                "fecha": cuenta_taquilla["fecha"],
                "monto": balance_contable,
                "balance_total": balance_contable,
                "saldo_anterior": cuenta_taquilla["saldo_anterior"],
                "reporte_neto": cuenta_taquilla["neto_hoy"],
                "abonos": cuenta_taquilla["abonos_hoy"],
                "cashea": cuenta_taquilla["cashea_hoy"],
                "adelantos": cuenta_taquilla["adelantos_hoy"],
                "liquidaciones": cuenta_taquilla["liquidaciones_hoy"]
            }

            if balance_contable > 0.009:
                positivos.append(datos_desglose)
            elif balance_contable < -0.009:
                datos_desglose_neg = dict(datos_desglose)
                datos_desglose_neg["monto"] = abs(balance_contable)
                negativos.append(datos_desglose_neg)

        if agencia_filtro:
            cursor.execute("""
                SELECT * FROM conciliaciones_semanales 
                WHERE UPPER(TRIM(agencia)) = %s 
                ORDER BY id DESC LIMIT 1
            """, (normalizar(agencia_filtro),))
            rows_concil_admin = cursor.fetchall()
        else:
            cursor.execute("""
                SELECT DISTINCT ON (UPPER(TRIM(agencia))) * 
                FROM conciliaciones_semanales 
                ORDER BY UPPER(TRIM(agencia)), id DESC
            """)
            rows_concil_admin = cursor.fetchall()

        conciliacion_admin_detalle = []
        tot_rep_admin = 0.0
        tot_sis_admin = 0.0
        tot_dif_admin = 0.0
        tot_vcob_admin = 0.0
        tot_pcob_admin = 0.0
        tot_vrea_admin = 0.0
        tot_prea_admin = 0.0

        for r_ca in rows_concil_admin:
            ag_name = r_ca.get("agencia", "")
            try:
                items_dias = json.loads(r_ca.get("detalle_dias") or "[]")
            except Exception:
                items_dias = []

            for item in items_dias:
                dif_n = float(item.get("dif_neto", 0) or 0)
                dif_v = float(item.get("dif_venta", 0) or 0)

                if abs(dif_n) > 0.01 or abs(dif_v) > 0.01:
                    item_completo = dict(item)
                    item_completo["agencia"] = ag_name
                    conciliacion_admin_detalle.append(item_completo)

                    tot_vcob_admin += float(item.get("venta_cobrada", 0) or 0)
                    tot_pcob_admin += float(item.get("premio_cobrado", 0) or 0)
                    tot_vrea_admin += float(item.get("venta_real", 0) or 0)
                    tot_prea_admin += float(item.get("premio_real", 0) or 0)
                    tot_rep_admin += float(item.get("neto_cobrado", 0) or 0)
                    tot_sis_admin += float(item.get("neto_real", 0) or 0)
                    tot_dif_admin += dif_n

        conciliacion_admin_resumen = {
            "total_venta_cobrada": tot_vcob_admin,
            "total_premio_cobrado": tot_pcob_admin,
            "total_reportado": tot_rep_admin,
            "total_venta_real": tot_vrea_admin,
            "total_premio_real": tot_prea_admin,
            "total_sistema": tot_sis_admin,
            "diferencia": tot_dif_admin
        }

        conn.close()

        (
            sistemas_consolidados,
            sistemas_agencias_detalle,
            totales_generales,
            totales_auxiliares,
            desglose_banqueros,
            total_ganancia_excedente,
            total_ganancia_participacion,
            total_mi_ganancia_global,
            suma_cuadros_banqueros
        ) = calcular_desglose_banqueros_datos(f_desde, f_hasta, agencia_filtro)

        return templates.TemplateResponse(request=request, name="admin.html", context={
            "reportes": reportes,
            "pagos": pagos,
            "agencias": agencias,
            "sistemas": SISTEMAS_OFICIALES,
            "comunicados": comunicados,
            "casheas_generales": casheas_generales,
            "total_cashea_filtrado": total_cashea_filtrado,
            "positivos": positivos,
            "negativos": negativos,
            "sistemas_consolidados": sistemas_consolidados,
            "sistemas_agencias_detalle": sistemas_agencias_detalle,
            "totales_generales": totales_generales,
            "totales_auxiliares": totales_auxiliares,
            "desglose_banqueros": desglose_banqueros,
            "total_ganancia_excedente": total_ganancia_excedente,
            "total_ganancia_participacion": total_ganancia_participacion,
            "total_mi_ganancia_global": total_mi_ganancia_global,
            "suma_cuadros_banqueros": suma_cuadros_banqueros,
            "solicitudes_pendientes": solicitudes_pendientes,
            "solicitudes_pendientes_count": solicitudes_pendientes_count,
            "solicitudes_ln_pendientes": solicitudes_ln_pendientes,
            "conciliacion_admin_resumen": conciliacion_admin_resumen,
            "conciliacion_admin_detalle": conciliacion_admin_detalle,
            "desde_fecha": f_desde,
            "hasta_fecha": f_hasta,
            "agencia_filtro": agencia_filtro,
            "tipo_transaccion": tipo_transaccion or "",
            "tab_activa": tab,
            "tab": tab
        })

    except Exception as e:
        print("Error en admin:", e)
        traceback.print_exc()
        return HTMLResponse(content=f"Error interno en admin: {e}", status_code=500)

@app.get("/templates/logo.png")
def get_logo():
    return FileResponse("templates/logo.png", media_type="image/png")
