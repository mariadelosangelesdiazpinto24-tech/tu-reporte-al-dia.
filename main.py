import os
import urllib.parse as urlparse
import psycopg2
import psycopg2.extras
import unicodedata
import re
import shutil
from zoneinfo import ZoneInfo
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, Request, Form, UploadFile, File, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

TZ_VENEZUELA = ZoneInfo("America/Caracas")

def obtener_fecha_venezuela() -> str:
    return datetime.now(TZ_VENEZUELA).strftime('%Y-%m-%d')

def obtener_fechahora_venezuela() -> str:
    return datetime.now(TZ_VENEZUELA).strftime('%Y-%m-%d %H:%M:%S')

os.makedirs("uploads", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

SISTEMAS_OFICIALES = [
    "LA IMAGINARIA", "BETSOL", "GATO", "LOTIPOS", "LOTTIPLAY", 
    "LOTTOLUCKY", "MAXPLAY", "SRQ", "POSNET", "POZO", 
    "PREMIER", "SRQ POLLA", "WINBIG VENTAS", "WINBIG BINGO", 
    "WINBIG POLLAS", "MATRIX", "PARLEY", "CALAMAR", "GUACA"
]

# HOMOLOGACIÓN DE ALIAS DE AGENCIAS Y SISTEMAS
ALIAS_AGENCIAS = {
    "RUTA MILLONARIA": "ANA MARIA",
    "DESTINO FORTUNA": "DESTINO SUERTE",
    "LA SUERTE DE JANN": "NABEL",
    "DATOS VIP 23": "VIP23",
    "CAMINO DE LA SUERTE": "FERNANDO",
    "LADD LA CONEJITA": "MILA",
    "AGENCIA VALLEMIL": "VALLEMIL",
    "AGENCIA ORQUIDEA 2": "ORQUIDEA",
    "AGENCIA ORQUÍDEA 2": "ORQUIDEA"
}

def normalizar(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    texto_limpio = texto.strip().upper()
    return ALIAS_AGENCIAS.get(texto_limpio, texto_limpio)

def normalizar_sistema(sistema: str) -> str:
    if not sistema:
        return ""
    s_clean = normalizar(sistema)
    if "VENTA ACTIVA" in s_clean:
        return "MATRIX"
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

    try:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS rol TEXT DEFAULT 'TAQUILLA'")
        cursor.execute("ALTER TABLE comunicados ADD COLUMN IF NOT EXISTS agencia_destino TEXT DEFAULT 'TODAS'")
    except Exception:
        pass

    try:
        cursor.execute("UPDATE pagos SET agencia = 'ANA MARIA' WHERE UPPER(TRIM(agencia)) = 'RUTA MILLONARIA'")
        cursor.execute("UPDATE lecturas_comunicados SET agencia = 'ANA MARIA' WHERE UPPER(TRIM(agencia)) = 'RUTA MILLONARIA'")
        cursor.execute("""
            DELETE FROM reportes r1
            WHERE UPPER(TRIM(r1.agencia)) = 'RUTA MILLONARIA'
              AND EXISTS (
                  SELECT 1 FROM reportes r2 
                  WHERE UPPER(TRIM(r2.agencia)) = 'ANA MARIA' 
                    AND r2.fecha = r1.fecha
              )
        """)
        cursor.execute("UPDATE reportes SET agencia = 'ANA MARIA' WHERE UPPER(TRIM(agencia)) = 'RUTA MILLONARIA'")
        cursor.execute("DELETE FROM usuarios WHERE UPPER(TRIM(agencia)) = 'RUTA MILLONARIA'")
    except Exception as e_mig:
        print("Aviso en unificación:", e_mig)

    cursor.execute("SELECT COUNT(*) AS total FROM configuracion_banqueros")
    cuenta = cursor.fetchone()
    if cuenta and cuenta['total'] == 0:
        reglas_iniciales = [
            ("COMERCIALIZADORA SUPER APUESTAS", "BETSOL", 0.15, 0.12, 0.10, False),
            ("COMERCIALIZADORA LOTTOLUCKY", "LOTTOLUCKY", 0.17, 0.13, 0.00, False),
            ("COMERCIALIZADORA NYS", "POZO", 0.13, 0.11, 0.00, True),
            ("COMERCIALIZADORA NYS", "LA IMAGINARIA", 0.17, 0.14, 0.35, True),
            ("COMERCIALIZADORA NYS", "WINBIG POLLAS", 0.18, 0.14, 0.00, True),
            ("COMERCIALIZADORA NYS", "CALAMAR", 0.18, 0.14, 0.25, True),
            ("COMERCIALIZADORA LIDER", "MAXPLAY", 0.16, 0.12, 0.20, False),
            ("COMERCIALIZADORA LIDER", "MATRIX", 0.16, 0.12, 0.20, False),
            ("COMERCIALIZADORA LIDER", "SRQ", 0.16, 0.12, 0.30, False),
            ("COMERCIALIZADORA LIDER", "LOTIPOS", 0.17, 0.13, 0.20, False),
            ("COMERCIALIZADORA LIDER", "GATO", 0.16, 0.12, 0.20, False),
            ("COMERCIALIZADORA LIDER", "PREMIER", 0.16, 0.12, 0.00, False),
            ("COMERCIALIZADORA LIDER", "POSNET", 0.15, 0.12, 0.20, False),
            ("COMERCIALIZADORA LIDER", "PARLEY", 0.12, 0.10, 0.00, False),
            ("COMERCIALIZADORA LIDER", "GUACA", 0.17, 0.13, 0.30, False),
            ("COMERCIALIZADORA LOTTIPLAY", "LOTTIPLAY", 0.15, 0.12, 0.00, False)
        ]
        for r in reglas_iniciales:
            cursor.execute(
                """INSERT INTO configuracion_banqueros (banquero, sistema, pct_banquero, pct_taquilla, pct_participacion, absorbe_cashea)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                r
            )
        
        banqueros_usuarios = [
            ("SUPER APUESTAS", "123456"),
            ("LOTTOLUCKY", "123456"),
            ("NYS", "123456"),
            ("LIDER", "123456"),
            ("LOTTIPLAY", "123456")
        ]
        for usr, pwd in banqueros_usuarios:
            cursor.execute(
                """INSERT INTO usuarios (agencia, clave, genero, rol)
                   VALUES (%s, %s, 'BANQUERO', 'BANQUERO') ON CONFLICT (agencia) DO NOTHING""",
                (normalizar(usr), pwd)
            )

    conn.commit()
    conn.close()

init_db()

def obtener_estructura_banqueros_bd():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM configuracion_banqueros ORDER BY banquero, id ASC")
    filas = cursor.fetchall()
    conn.close()

    estructura = {}
    for f in filas:
        b_name = f['banquero']
        if b_name not in estructura:
            estructura[b_name] = {
                "sistemas": [],
                "absorbe_cashea": bool(f['absorbe_cashea'])
            }
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

    if agencia_filtro:
        cursor.execute("SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) ILIKE %s AND fecha >= %s AND fecha <= %s", (f"%{normalizar(agencia_filtro)}%", f_desde, f_hasta))
    else:
        cursor.execute("SELECT * FROM reportes WHERE fecha >= %s AND fecha <= %s", (f_desde, f_hasta))
    reps_db = cursor.fetchall()

    sistemas_consolidados = {}
    sistemas_agencias_detalle = {}
    totales_generales = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}

    for rep_db in reps_db:
        ag_origen = normalizar(rep_db['agencia'])
        if rep_db and rep_db['detalle_html']:
            tabla_match = re.search(r'<table[^>]*>(.*?)<\/table>', rep_db['detalle_html'], re.DOTALL)
            if tabla_match:
                filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', tabla_match.group(1), re.DOTALL)
                for f in filas:
                    cols = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', f, re.DOTALL)
                    if len(cols) >= 5:
                        sys_raw = re.sub(r'<[^>]+>', '', cols[0]).strip()
                        if not sys_raw or "SISTEMA" in sys_raw.upper() or "TOTALES" in sys_raw.upper():
                            continue
                        
                        sys_nombre = normalizar_sistema(sys_raw)

                        try:
                            v = float(re.sub(r'[^\d.-]', '', cols[1]))
                            c = float(re.sub(r'[^\d.-]', '', cols[2]))
                            p = float(re.sub(r'[^\d.-]', '', cols[3]))
                            t = float(re.sub(r'[^\d.-]', '', cols[4]))
                        except:
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

    if agencia_filtro:
        cursor.execute("SELECT tipo, monto FROM pagos WHERE UPPER(TRIM(agencia)) ILIKE %s AND fecha >= %s AND fecha <= %s AND estado = 'APROBADO'", (f"%{normalizar(agencia_filtro)}%", f_desde, f_hasta))
    else:
        cursor.execute("SELECT tipo, monto FROM pagos WHERE fecha >= %s AND fecha <= %s AND estado = 'APROBADO'", (f_desde, f_hasta))
    pagos_aux = cursor.fetchall()

    totales_auxiliares = {"cashea": 0.0, "adelantos": 0.0, "abonos_banca": 0.0}
    for pa in pagos_aux:
        m_val = float(pa['monto'] or 0.0)
        t_type = str(pa['tipo']).strip().upper() if pa['tipo'] else ''
        if t_type == 'CASHEA':
            totales_auxiliares["cashea"] += m_val
        elif t_type in ['ADELANTO', 'LIQUIDACION']:
            totales_auxiliares["adelantos"] += m_val
        elif t_type in ['PAGO_TAQUILLA', 'PAGO_BANCA']:
            totales_auxiliares["abonos_banca"] += m_val

    ESTRUCTURA_BANQUEROS = obtener_estructura_banqueros_bd()
    desglose_banqueros = {}
    total_ganancia_excedente = 0.0
    total_ganancia_participacion = 0.0
    suma_cuadros_banqueros = 0.0

    for b_nombre, cfg in ESTRUCTURA_BANQUEROS.items():
        desglose_banqueros[b_nombre] = {
            "sistemas": [],
            "cashea_descontado": totales_auxiliares["cashea"] if cfg["absorbe_cashea"] else 0.0,
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
                """SELECT venta, comision, premios FROM ajustes_banqueros_manuales 
                   WHERE banquero = %s AND sistema = %s AND fecha >= %s AND fecha <= %s""",
                (b_nombre, s_name, f_desde, f_hasta)
            )
            ajuste_manual = cursor.fetchone()

            if ajuste_manual:
                v_sys = float(ajuste_manual['venta'])
                p_sys = float(ajuste_manual['premios'])
                c_banquero = float(ajuste_manual['comision'])
            else:
                c_banquero = v_sys * pct_b

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
                "pct_banquero": int(round(pct_b * 100)),
                "pct_taquilla": int(round(pct_t * 100)),
                "pct_excedente": int(round(pct_excedente)),
                "pct_participacion": int(round(pct_part * 100)),
                "ganancia_total": g_total,
                "ajustado_manual": bool(ajuste_manual)
            })

            subtotal_banquero += total_despues_participacion
            desglose_banqueros[b_nombre]["total_mi_ganancia_banca"] += g_total

        if cfg["absorbe_cashea"]:
            subtotal_banquero -= totales_auxiliares["cashea"]

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

    cursor.execute("SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s AND estado = 'APROBADO'", (agencia_norm, fecha_reporte))
    todos_pagos = cursor.fetchall()
    
    cursor.execute("SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s AND tipo = 'AJUSTE_PENDIENTE' AND estado = 'APROBADO'", (agencia_norm,))
    ajustes_anteriores = cursor.fetchall()

    conn.close()

    total_adelantos = 0.0
    total_pagos_taquilla = 0.0
    total_cashea = 0.0
    total_ajustes_pendientes = 0.0
    
    adelantos_rows_html = ""
    cashea_rows_html = ""
    pagos_banca_rows_html = ""
    ajustes_rows_html = ""

    for p in todos_pagos:
        monto_p = float(p['monto'] or 0.0)
        tipo_p = str(p['tipo']).strip().upper() if p['tipo'] else 'PAGO_TAQUILLA'
        comp = p['comprobante'] or ''
        
        comp_display = f'<a href="/uploads/{comp}" target="_blank">Ver Comprobante</a>' if (comp and (comp.endswith('.png') or comp.endswith('.jpg') or comp.endswith('.jpeg') or comp.endswith('.pdf'))) else comp

        if tipo_p in ['ADELANTO', 'LIQUIDACION']:
            total_adelantos += monto_p
            adelantos_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{comp_display}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #e91e63; font-weight: bold;">Bs. {monto_p:,.2f}</td>
            </tr>
            '''
        elif tipo_p == 'CASHEA':
            total_cashea += monto_p
            cashea_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['factura']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #e91e63; font-weight: bold;">Bs. {monto_p:,.2f}</td>
            </tr>
            '''
        elif tipo_p in ['PAGO_TAQUILLA', 'PAGO_BANCA']:
            total_pagos_taquilla += monto_p
            pagos_banca_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['factura']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #2e7d32; font-weight: bold;">Bs. {monto_p:,.2f}</td>
            </tr>
            '''

    for aj in ajustes_anteriores:
        monto_aj = float(aj['monto'] or 0.0)
        total_ajustes_pendientes += monto_aj
        color_aj = "#2e7d32" if monto_aj < 0 else "#e91e63"
        ajustes_rows_html += f'''
        <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
            <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{aj['fecha']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{aj['comprobante']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: {color_aj}; font-weight: bold;">Bs. {monto_aj:,.2f}</td>
        </tr>
        '''

    detalle_original = rep['detalle_html'] or ""
    match_sistemas = re.search(r'(<div class="table-responsive mb-3"[^>]*>.*?REPORTE DE SISTEMAS.*?<\/table>.*?<\/div>)', detalle_original, re.DOTALL)
    if not match_sistemas:
        match_sistemas = re.search(r'(<div class="mb-3"[^>]*>.*?REPORTE DE SISTEMAS.*?<\/table>.*?<\/div>)', detalle_original, re.DOTALL)
    tabla_sistemas_html = match_sistemas.group(1) if match_sistemas else ""

    total_neto_sistemas = 0.0
    filas_tabla = re.findall(r'<tr[^>]*>(.*?)<\/tr>', tabla_sistemas_html, re.DOTALL)
    for fila in filas_tabla:
        if 'TOTALES' in fila.upper():
            cols = re.findall(r'<td[^>]*>(.*?)<\/td>', fila)
            if cols:
                try:
                    total_neto_sistemas = float(cols[-1].replace(',', '').replace('Bs.', '').strip())
                except:
                    pass

    if total_neto_sistemas == 0.0:
        total_neto_sistemas = float(rep['ventas'] if rep['ventas'] != 0 else rep['monto'])

    monto_final = total_neto_sistemas - total_pagos_taquilla + total_adelantos - total_cashea + total_ajustes_pendientes

    bloque_pagos_banca = f'''
    <div class="mb-3" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #2e7d32;">
        <h5 style="color: #2e7d32; font-weight: bold; border-bottom: 2px solid #2e7d32; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-university"></i> PAGOS / ABONOS A LA BANCA</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background-color: #e8f5e9; color: #1b5e20; font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">REFERENCIA / DETALLE</th>
                <th style="padding: 10px; text-align: right;">MONTO ABONADO</th>
            </tr>
            {pagos_banca_rows_html if pagos_banca_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">No hay pagos abonados aún.</td></tr>'}
        </table>
    </div>
    '''

    bloque_cashea = f'''
    <div class="mb-3" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #00bcd4;">
        <h5 style="color: #00bcd4; font-weight: bold; border-bottom: 2px solid #00bcd4; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-shopping-cart"></i> CASHEA (Registros absorbidos)</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background-color: #e0f7fa; color: #006064; font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">DETALLE / FACTURA</th>
                <th style="padding: 10px; text-align: right;">MONTO ABSORBIDO</th>
            </tr>
            {cashea_rows_html if cashea_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">No hay registros de Cashea.</td></tr>'}
        </table>
    </div>
    '''

    bloque_ajustes = f'''
    <div class="mb-3" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #ff9800;">
        <h5 style="color: #ff9800; font-weight: bold; border-bottom: 2px solid #ff9800; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-exclamation-triangle"></i> PENDIENTES / AJUSTES DE DÍAS ANTERIORES</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background-color: #fff3e0; color: #e65100; font-size: 13px;">
                <th style="padding: 10px;">FECHA DÍA ANTERIOR</th>
                <th style="padding: 10px;">DETALLE AJUSTE</th>
                <th style="padding: 10px; text-align: right;">DIFERENCIAL ACUMULADO</th>
            </tr>
            {ajustes_rows_html if ajustes_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">Sin ajustes pendientes acumulados.</td></tr>'}
        </table>
    </div>
    '''

    bloque_adelantos = f'''
    <div class="mb-3" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #e91e63;">
        <h5 style="color: #e91e63; font-weight: bold; border-bottom: 2px solid #e91e63; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-hand-holding-usd"></i> ADELANTOS / LIQUIDACIÓN (Plata entregada por Admin)</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background-color: #fce4ec; color: #880e4f; font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">MOTIVO</th>
                <th style="padding: 10px; text-align: right;">MONTO APLICADO</th>
            </tr>
            {adelantos_rows_html if adelantos_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">Adelanto: 0.00 Bs.</td></tr>'}
        </table>
    </div>
    '''

    bloque_pendientes = f'''
    <div class="mb-2" style="background: #ffffff; border-radius: 12px; padding: 20px; color: #1a252c; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border-left: 6px solid #e91e63; border: 1px solid #e0e0e0;">
        <h5 style="color: #e91e63; font-weight: bold; border-bottom: 1px solid #e0e0e0; padding-bottom: 10px; margin-bottom: 12px;"><i class="fas fa-clock"></i> ESTADO DE CUENTA FINAL</h5>
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <span style="font-size: 14px; color: #333; font-weight: bold;">Fecha: {fecha_reporte}</span>
            <span style="font-size: 14px; font-weight: bold; color: #333;">{("Total a Pagar" if monto_final >= 0 else "Saldo a favor / Solicitar")}</span>
            <span style="font-size: 18px; font-weight: bold; color: {('#2e7d32' if monto_final < 0 else '#e91e63')};">Bs. {monto_final:,.2f}</span>
        </div>
    </div>
    '''

    detalle_actualizado = tabla_sistemas_html + bloque_pagos_banca + bloque_cashea + bloque_ajustes + bloque_adelantos + bloque_pendientes

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE reportes SET monto = %s, detalle_html = %s WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s", (monto_final, detalle_actualizado, agencia_norm, fecha_reporte))
    conn.commit()
    conn.close()

@app.post("/api/guardar-reporte-colab")
async def guardar_reporte_colab(request: Request):
    data = await request.form()
    agencia = normalizar(data.get("agencia", ""))
    fecha = data.get("fecha", "")
    monto = float(data.get("monto", 0.0))
    ventas = float(data.get("ventas", 0.0))
    premios = float(data.get("premios", 0.0))
    detalle_html = data.get("detalle_html", "")
    cashea_monto = float(data.get("cashea_monto", 0.0))
    cashea_detalle = data.get("cashea_detalle", "")

    hoy_str = obtener_fecha_venezuela()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s", (agencia, fecha))
    rep = cursor.fetchone()

    if rep and fecha < hoy_str:
        monto_anterior = rep['monto'] or 0.0
        diferencial = monto - monto_anterior
        if diferencial != 0.0:
            cursor.execute(
                "INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, %s, %s, 'AJUSTE_PENDIENTE', 'APROBADO')",
                (agencia, hoy_str, diferencial, f"Ajuste reporte del {fecha}", f"Excedente/Diferencial día anterior del {fecha}")
            )

    if rep:
        cursor.execute(
            "UPDATE reportes SET monto = %s, ventas = %s, premios = %s, detalle_html = %s WHERE id = %s",
            (monto, ventas, premios, detalle_html, rep['id'])
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
                "UPDATE pagos SET monto = %s, factura = %s, comprobante = %s WHERE id = %s",
                (cashea_monto, cashea_detalle, cashea_detalle, cashea_db['id'])
            )
        else:
            cursor.execute(
                "INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, %s, %s, 'CASHEA', 'APROBADO')",
                (agencia, fecha, cashea_monto, cashea_detalle, cashea_detalle)
            )

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia, fecha)
    recalcular_y_actualizar_reporte(agencia, hoy_str)
    return {"status": "ok", "mensaje": "Reporte y ajustes actualizados con éxito"}

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

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE UPPER(TRIM(agencia)) = %s", (usuario_norm,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data and user_data['clave'] == clave:
        actualizar_ultima_conexion(usuario_norm)
        
        if user_data.get('rol') == 'BANQUERO':
            response = RedirectResponse(url=f"/banquero?usuario={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
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
    hasta_fecha: Optional[str] = None
):
    if not usuario:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    usr_norm = normalizar(usuario)
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

    nombre_comercializadora = ""
    for b_key in desglose_banqueros.keys():
        if usr_norm in b_key.upper() or b_key.upper() in usr_norm:
            nombre_comercializadora = b_key
            break

    if not nombre_comercializadora:
        for b_key in desglose_banqueros.keys():
            partes = usr_norm.split()
            if any(p in b_key.upper() for p in partes if len(p) > 2):
                nombre_comercializadora = b_key
                break

    cuadro_banquero = desglose_banqueros.get(nombre_comercializadora, {
        "sistemas": [],
        "cashea_descontado": 0.0,
        "total_a_pagar_banquero": 0.0
    })

    return templates.TemplateResponse(request=request, name="banquero.html", context={
        "usuario": usr_norm,
        "nombre_comercializadora": nombre_comercializadora or "MI COMERCIALIZADORA",
        "cuadro": cuadro_banquero,
        "desde_fecha": f_desde,
        "hasta_fecha": f_hasta
    })

@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(
    request: Request, 
    nombre: Optional[str] = None,
    desde_fecha: Optional[str] = None,
    hasta_fecha: Optional[str] = None
):
    if not nombre:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    agencia_norm = normalizar(nombre)
    hoy_vzla = obtener_fecha_venezuela()
    f_desde = desde_fecha if desde_fecha else hoy_vzla
    f_hasta = hasta_fecha if hasta_fecha else hoy_vzla

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM usuarios WHERE UPPER(TRIM(agencia)) = %s", (agencia_norm,))
    agencia_info = cursor.fetchone()
    
    cursor.execute("SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s ORDER BY fecha DESC", (agencia_norm,))
    reportes_agencia_raw = cursor.fetchall()
    
    reportes_agencia = []
    for r in reportes_agencia_raw:
        r_dict = dict(r)
        comision_sum = 0.0
        if r_dict.get('detalle_html'):
            tabla_match = re.search(r'<table[^>]*>(.*?)<\/table>', r_dict['detalle_html'], re.DOTALL)
            if tabla_match:
                filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', tabla_match.group(1), re.DOTALL)
                for f in filas:
                    cols = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', f, re.DOTALL)
                    if len(cols) >= 5 and "TOTALES" not in cols[0].upper() and "SISTEMA" not in cols[0].upper():
                        try:
                            c_val = float(re.sub(r'[^\d.-]', '', cols[2]))
                            comision_sum += c_val
                        except:
                            pass
        
        if comision_sum == 0.0 and (float(r_dict.get('ventas') or 0) > 0):
            comision_sum = max(0.0, float(r_dict.get('ventas') or 0) - float(r_dict.get('premios') or 0) - float(r_dict.get('monto') or 0))
            
        r_dict['comision'] = comision_sum
        reportes_agencia.append(r_dict)

    cursor.execute(
        "SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s AND fecha >= %s AND fecha <= %s", 
        (agencia_norm, f_desde, f_hasta)
    )
    reps_rango = cursor.fetchall()
    
    auditoria_sistemas_agencia = {}
    totales_auditoria = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
    
    for rep_item in reps_rango:
        if rep_item and rep_item['detalle_html']:
            t_match = re.search(r'<table[^>]*>(.*?)<\/table>', rep_item['detalle_html'], re.DOTALL)
            if t_match:
                filas_s = re.findall(r'<tr[^>]*>(.*?)<\/tr>', t_match.group(1), re.DOTALL)
                for fs in filas_s:
                    cols_s = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', fs, re.DOTALL)
                    if len(cols_s) >= 5:
                        s_raw = re.sub(r'<[^>]+>', '', cols_s[0]).strip()
                        if not s_raw or "SISTEMA" in s_raw.upper() or "TOTALES" in s_raw.upper():
                            continue
                        
                        s_name = normalizar_sistema(s_raw)

                        try:
                            sv = float(re.sub(r'[^\d.-]', '', cols_s[1]))
                            sc = float(re.sub(r'[^\d.-]', '', cols_s[2]))
                            sp = float(re.sub(r'[^\d.-]', '', cols_s[3]))
                            st = float(re.sub(r'[^\d.-]', '', cols_s[4]))
                        except:
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

    cursor.execute("SELECT * FROM pagos WHERE UPPER(TRIM(agencia)) = %s ORDER BY id DESC", (agencia_norm,))
    pagos_agencia = [dict(row) for row in cursor.fetchall()]
    
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
    
    cursor.execute("SELECT SUM(monto) AS total_rep FROM reportes WHERE UPPER(TRIM(agencia)) = %s", (agencia_norm,))
    row_rep = cursor.fetchone()
    saldo_acumulado = float(row_rep['total_rep'] or 0.0) if row_rep else 0.0

    conn.close()
    
    return templates.TemplateResponse(request=request, name="agencia.html", context={
        "agencia": agencia_info,
        "nombre_agencia": agencia_norm,
        "reportes": reportes_agencia,
        "pagos": pagos_agencia,
        "comunicados": comunicados,
        "sistemas": SISTEMAS_OFICIALES,
        "saldo_actual": saldo_acumulado,
        "auditoria_sistemas": auditoria_sistemas_agencia,
        "totales_auditoria": totales_auditoria,
        "desde_fecha": f_desde,
        "hasta_fecha": f_hasta
    })

@app.post("/agencia/cambiar-clave")
def post_cambiar_clave(agencia: str = Form(...), nueva_clave: str = Form(...), confirm_clave: str = Form(...)):
    agencia_norm = normalizar(agencia)
    if not nueva_clave or nueva_clave != confirm_clave:
        return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=usuario&error=claves_no_coinciden", status_code=status.HTTP_303_SEE_OTHER)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET clave = %s WHERE UPPER(TRIM(agencia)) = %s", (nueva_clave.strip(), agencia_norm))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=usuario&success=clave_actualizada", status_code=status.HTTP_303_SEE_OTHER)

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
def post_solicitar_banca_directo(agencia: str = Form(...), fecha: str = Form(...), monto: float = Form(...)):
    agencia_norm = normalizar(agencia)
    monto_abs = abs(monto)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'SOLICITUD_BANCA', 'PENDIENTE')""",
        (agencia_norm, fecha, monto_abs, f"Solicitud Saldo del {fecha}", f"Solicitud de dinero: Bs. {monto_abs:,.2f}")
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/reportar")
async def post_reportar(
    agencia: str = Form(...),
    fecha: str = Form(...),
    factura: str = Form(...),
    monto: float = Form(...),
    comprobante: UploadFile = File(...)
):
    agencia_norm = normalizar(agencia)
    nombre_archivo = f"pago_{agencia_norm}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}_{comprobante.filename}"
    ruta_guardar = os.path.join("uploads", nombre_archivo)
    
    with open(ruta_guardar, "wb") as buffer:
        shutil.copyfileobj(comprobante.file, buffer)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'PAGO_TAQUILLA', 'PENDIENTE')""",
        (agencia_norm, fecha, monto, factura, nombre_archivo)
    )
    conn.commit()
    conn.close()

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
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/actualizar-reporte-sistema")
def post_actualizar_reporte_sistema(
    agencia: str = Form(...),
    fecha: str = Form(...),
    sistema: str = Form(...),
    venta: float = Form(...),
    premio: float = Form(...)
):
    agencia_norm = normalizar(agencia)
    sistema_norm = normalizar_sistema(sistema)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes WHERE UPPER(TRIM(agencia)) = %s AND fecha = %s", (agencia_norm, fecha))
    rep = cursor.fetchone()
    
    if rep and rep['detalle_html']:
        html = rep['detalle_html']
        
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

        comision_nueva = venta * pct_com
        total_nuevo = venta - comision_nueva - premio

        patron_fila = rf'<tr[^>]*>\s*<td[^>]*>\s*{re.escape(sistema)}\s*<\/td>.*?<\/tr>'
        nueva_fila = f'''<tr>
            <td>{sistema}</td>
            <td style="text-align: right;">{venta:,.2f}</td>
            <td style="text-align: right;">{comision_nueva:,.2f}</td>
            <td style="text-align: right;">{premio:,.2f}</td>
            <td style="text-align: right; font-weight: bold;">{total_nuevo:,.2f}</td>
        </tr>'''
        html_modificado = re.sub(patron_fila, nueva_fila, html, flags=re.DOTALL | re.IGNORECASE)

        filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', html_modificado, re.DOTALL)
        sum_v, sum_c, sum_p, sum_t = 0.0, 0.0, 0.0, 0.0
        for f in filas:
            cols = re.findall(r'<td[^>]*>(.*?)<\/td>', f, re.DOTALL)
            if len(cols) >= 5 and "TOTALES" not in cols[0].upper():
                try:
                    sum_v += float(re.sub(r'[^\d.-]', '', cols[1]))
                    sum_c += float(re.sub(r'[^\d.-]', '', cols[2]))
                    sum_p += float(re.sub(r'[^\d.-]', '', cols[3]))
                    sum_t += float(re.sub(r'[^\d.-]', '', cols[4]))
                except:
                    pass

        patron_totales = r'<tr[^>]*>\s*<td[^>]*>\s*TOTALES\s*<\/td>.*?<\/tr>'
        nueva_fila_totales = f'''<tr style="font-weight: bold; background-color: #f1f3f4;">
            <td>TOTALES</td>
            <td style="text-align: right;">{sum_v:,.2f}</td>
            <td style="text-align: right;">{sum_c:,.2f}</td>
            <td style="text-align: right;">{sum_p:,.2f}</td>
            <td style="text-align: right;">{sum_t:,.2f}</td>
        </tr>'''
        html_modificado = re.sub(patron_totales, nueva_fila_totales, html_modificado, flags=re.DOTALL | re.IGNORECASE)

        cursor.execute(
            "UPDATE reportes SET monto = %s, detalle_html = %s, ventas = %s, premios = %s WHERE id = %s",
            (sum_t, html_modificado, sum_v, sum_p, rep['id'])
        )
        conn.commit()

        cursor.execute(
            """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
               VALUES (%s, %s, %s, %s, %s, 'MODIFICACION', 'APROBADO')""",
            (agencia_norm, fecha, 0.0, f"Modificación {sistema}", f"Venta: Bs. {venta:,.2f} | Premio: Bs. {premio:,.2f}")
        )
        conn.commit()

    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    recalcular_y_actualizar_reporte(agencia_norm, obtener_fecha_venezuela())
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/eliminar-transaccion")
@app.post("/admin/eliminar-transaccion")
def post_eliminar_transaccion(pago_id: int = Form(...), redirect_to: Optional[str] = Form(None)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT agencia, fecha FROM pagos WHERE id = %s", (pago_id,))
    p_data = cursor.fetchone()
    if p_data:
        cursor.execute("DELETE FROM pagos WHERE id = %s", (pago_id,))
        conn.commit()
        recalcular_y_actualizar_reporte(p_data['agencia'], p_data['fecha'])
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
        
        nombre_guardado = f"Liquidación Saldo #{solicitud_id}"
        if comprobante_file and comprobante_file.filename:
            ext = comprobante_file.filename.split('.')[-1]
            nombre_archivo = f"liquidacion_{solicitud_id}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}.{ext}"
            ruta_destino = os.path.join("uploads", nombre_archivo)
            with open(ruta_destino, "wb") as buffer:
                shutil.copyfileobj(comprobante_file.file, buffer)
            nombre_guardado = nombre_archivo

        cursor.execute("UPDATE pagos SET estado = 'PROCESADO' WHERE id = %s", (solicitud_id,))
        
        cursor.execute(
            """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) 
               VALUES (%s, %s, %s, %s, %s, 'LIQUIDACION', 'APROBADO')""",
            (normalizar(agencia), fecha, monto_pagar, f"Liquidación {accion}", nombre_guardado)
        )

        cursor.execute(
            "INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)",
            (f"Se te ha transferido Bs. {monto_pagar:,.2f} ({accion}) para saldar tu cuenta.", normalizar(agencia))
        )
        conn.commit()

    conn.close()
    recalcular_y_actualizar_reporte(agencia, fecha)
    return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/validar-pago")
def post_validar_pago(solicitud_id: int = Form(...), accion: str = Form(...)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos WHERE id = %s", (solicitud_id,))
    pago = cursor.fetchone()

    if pago:
        agencia_p = pago['agencia']
        fecha_p = pago['fecha']
        monto_p = float(pago['monto'] or 0.0)
        
        if accion == "APROBAR":
            cursor.execute("UPDATE pagos SET estado = 'APROBADO' WHERE id = %s", (solicitud_id,))
            msg_notif = f"Tu pago de Bs. {monto_p:,.2f} ha sido APROBADO y aplicado a tu cuenta."
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
        
        recalcular_y_actualizar_reporte(agencia_p, fecha_p)
        return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

    conn.close()
    return RedirectResponse(url="/admin?tab=transacciones", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/liquidar-saldo-negativo")
async def post_liquidar_saldo_negativo(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: float = Form(...),
    comprobante_file: UploadFile = File(...)
):
    agencia_norm = normalizar(agencia)
    monto_pago = abs(monto)

    nombre_archivo = f"liquidacion_negativo_{agencia_norm}_{datetime.now(TZ_VENEZUELA).strftime('%Y%m%d_%H%M%S')}_{comprobante_file.filename}"
    ruta_guardar = os.path.join("uploads", nombre_archivo)
    with open(ruta_guardar, "wb") as buffer:
        shutil.copyfileobj(comprobante_file.file, buffer)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
           VALUES (%s, %s, %s, %s, %s, 'LIQUIDACION', 'APROBADO')""",
        (agencia_norm, fecha, monto_pago, "Liquidación Saldo a Favor", nombre_archivo)
    )

    mensaje = f"✅ Tu saldo a favor de Bs. {monto_pago:,.2f} del día {fecha} ha sido LIQUIDADO. Ya puedes revisar tu capture."
    try:
        cursor.execute(
            "INSERT INTO comunicados (mensaje, agencia_destino) VALUES (%s, %s)",
            (mensaje, agencia_norm)
        )
    except Exception:
        cursor.execute(
            "INSERT INTO comunicados (mensaje) VALUES (%s)",
            (mensaje,)
        )

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    hoy_vzla = obtener_fecha_venezuela()
    if fecha != hoy_vzla:
        recalcular_y_actualizar_reporte(agencia_norm, hoy_vzla)

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
def post_guardar_ajuste_banquero_sistema(
    banquero: str = Form(...),
    sistema: str = Form(...),
    fecha: str = Form(...),
    venta: float = Form(...),
    comision: float = Form(...),
    premios: float = Form(...),
    desde_fecha: Optional[str] = Form(None),
    hasta_fecha: Optional[str] = Form(None)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO ajustes_banqueros_manuales (banquero, sistema, fecha, venta, comision, premios)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (banquero, sistema, fecha) 
           DO UPDATE SET venta = EXCLUDED.venta, comision = EXCLUDED.comision, premios = EXCLUDED.premios""",
        (banquero, sistema, fecha, venta, comision, premios)
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
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM ajustes_banqueros_manuales WHERE banquero = %s AND sistema = %s",
        (banquero, sistema)
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
    return RedirectResponse(url="/admin?tab=comunicados", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/eliminar-comunicado")
def post_eliminar_comunicado(comunicado_id: int = Form(...)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM comunicados WHERE id = %s", (comunicado_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin?tab=comunicados", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/crear-agencia")
@app.post("/admin/crear-taquilla")
def post_crear_agencia(agencia: str = Form(...), clave: str = Form(...), genero: str = Form("FEMENINO"), rol: str = Form("TAQUILLA")):
    agencia_norm = normalizar(agencia)
    if agencia_norm and clave:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO usuarios (agencia, clave, genero, rol) VALUES (%s, %s, %s, %s)
               ON CONFLICT (agencia) DO UPDATE SET clave = EXCLUDED.clave, genero = EXCLUDED.genero, rol = EXCLUDED.rol""",
            (agencia_norm, clave, genero, rol)
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
    tab: str = "transacciones"
):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reportes ORDER BY id DESC")
        reportes = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM pagos WHERE tipo != 'CASHEA' ORDER BY id DESC")
        pagos = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM usuarios ORDER BY id DESC")
        agencias = [dict(row) for row in cursor.fetchall()]
        
        try:
            cursor.execute("SELECT * FROM comunicados WHERE agencia_destino = 'TODAS' ORDER BY id DESC")
            comunicados = [dict(row) for row in cursor.fetchall()]
        except Exception:
            cursor.execute("SELECT * FROM comunicados ORDER BY id DESC")
            comunicados = [dict(row) for row in cursor.fetchall()]

        hoy_vzla = obtener_fecha_venezuela()
        cursor.execute("SELECT fecha FROM reportes ORDER BY id DESC LIMIT 1")
        ultima_fila = cursor.fetchone()
        fecha_bd_reciente = ultima_fila['fecha'] if (ultima_fila and ultima_fila['fecha']) else hoy_vzla

        if agencia and not desde_fecha and not hasta_fecha:
            cursor.execute("SELECT fecha FROM reportes WHERE UPPER(TRIM(agencia)) ILIKE %s ORDER BY id DESC LIMIT 1", (f"%{normalizar(agencia)}%",))
            fila_ag = cursor.fetchone()
            if fila_ag and fila_ag['fecha']:
                fecha_bd_reciente = fila_ag['fecha']

        f_desde = desde_fecha if desde_fecha else fecha_bd_reciente
        f_hasta = hasta_fecha if hasta_fecha else fecha_bd_reciente
        agencia_filtro = agencia if agencia else ""

        cursor.execute("SELECT COUNT(*) AS total_pendientes FROM pagos WHERE estado ILIKE '%PENDIENTE%'")
        pend_row = cursor.fetchone()
        solicitudes_pendientes_count = pend_row['total_pendientes'] if pend_row else 0

        if agencia_filtro:
            cursor.execute("SELECT * FROM pagos WHERE tipo = 'CASHEA' AND UPPER(TRIM(agencia)) ILIKE %s AND fecha >= %s AND fecha <= %s ORDER BY id DESC", (f"%{normalizar(agencia_filtro)}%", f_desde, f_hasta))
        else:
            cursor.execute("SELECT * FROM pagos WHERE tipo = 'CASHEA' AND fecha >= %s AND fecha <= %s ORDER BY id DESC", (f_desde, f_hasta))
        casheas_generales = [dict(row) for row in cursor.fetchall()]
        total_cashea_filtrado = sum(float(c.get('monto') or 0.0) for c in casheas_generales)

        positivos = []
        negativos = []
        for ag in agencias:
            if ag.get('rol') == 'BANQUERO':
                continue
            ag_nombre = ag['agencia']
            
            cursor.execute(
                """SELECT SUM(ventas) as total_ventas, SUM(premios) as total_premios, SUM(monto) as saldo_neto, MAX(fecha) as ultima_fecha
                   FROM reportes WHERE UPPER(TRIM(agencia)) ILIKE %s AND fecha >= %s AND fecha <= %s""",
                (f"%{normalizar(ag_nombre)}%", f_desde, f_hasta)
            )
            fila_rep = cursor.fetchone()
            
            cursor.execute(
                """SELECT tipo, SUM(monto) as total_monto FROM pagos 
                   WHERE UPPER(TRIM(agencia)) ILIKE %s AND fecha >= %s AND fecha <= %s AND estado = 'APROBADO'
                   GROUP BY tipo""",
                (f"%{normalizar(ag_nombre)}%", f_desde, f_hasta)
            )
            filas_pagos = cursor.fetchall()
            
            sum_abonos = 0.0
            sum_cashea = 0.0
            sum_adelantos = 0.0
            for fp in filas_pagos:
                tipo_fp = str(fp['tipo']).upper()
                m_fp = float(fp['total_monto'] or 0.0)
                if tipo_fp in ['PAGO_TAQUILLA', 'PAGO_BANCA']:
                    sum_abonos += m_fp
                elif tipo_fp == 'CASHEA':
                    sum_cashea += m_fp
                elif tipo_fp in ['ADELANTO', 'LIQUIDACION']:
                    sum_adelantos += m_fp

            v_tot = float(fila_rep['total_ventas'] or 0.0) if fila_rep else 0.0
            p_tot = float(fila_rep['total_premios'] or 0.0) if fila_rep else 0.0
            saldo_val = float(fila_rep['saldo_neto'] or 0.0) if (fila_rep and fila_rep['saldo_neto'] is not None) else 0.0
            f_rep = fila_rep['ultima_fecha'] if (fila_rep and fila_rep['ultima_fecha']) else f_hasta

            ag['saldo_pendiente'] = saldo_val
            
            datos_desglose = {
                "agencia": ag_nombre,
                "fecha": f_rep,
                "monto": saldo_val,
                "ventas": v_tot,
                "premios": p_tot,
                "abonos": sum_abonos,
                "cashea": sum_cashea,
                "adelantos": sum_adelantos
            }

            if saldo_val > 0.009:
                positivos.append(datos_desglose)
            elif saldo_val < -0.009:
                datos_desglose_neg = dict(datos_desglose)
                datos_desglose_neg["monto"] = abs(saldo_val)
                negativos.append(datos_desglose_neg)

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
            "solicitudes_pendientes_count": solicitudes_pendientes_count,
            "desde_fecha": f_desde,
            "hasta_fecha": f_hasta,
            "agencia_filtro": agencia_filtro,
            "tab_activa": tab,
            "tab": tab
        })

    except Exception as e:
        print("Error en admin:", e)
        return HTMLResponse(content=f"Error interno en admin: {e}", status_code=500)
