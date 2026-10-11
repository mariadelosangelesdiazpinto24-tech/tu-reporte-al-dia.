import os
import urllib.parse as urlparse
import psycopg2
import psycopg2.extras
import unicodedata
import re
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, Request, Form, UploadFile, File, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

os.makedirs("uploads", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

SISTEMAS_OFICIALES = [
    "LA IMAGINARIA", "BETSOL", "GATO", "LOTIPOS", "LOTTIPLAY", 
    "LOTTOLUCKY", "MAXPLAY", "SRQ", "POSNET", "POZO", 
    "PREMIER", "SRQ POLLA", "WINBIG VENTAS", "WINBIG BINGO", 
    "WINBIG POLLAS", "VENTA ACTIVA", "PARLEY"
]

def normalizar(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.strip().upper()

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
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    conn.commit()
    conn.close()

init_db()

def actualizar_ultima_conexion(agencia: str):
    agencia_norm = normalizar(agencia)
    if agencia_norm and agencia_norm != "ADMIN":
        try:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE usuarios SET ultima_conexion = %s WHERE agencia = %s", (now_str, agencia_norm))
            conn.commit()
            conn.close()
        except Exception as e:
            print("Error actualizando conexion:", e)

def recalcular_y_actualizar_reporte(agencia: str, fecha_reporte: str):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes WHERE agencia = %s AND fecha = %s", (agencia_norm, fecha_reporte))
    rep = cursor.fetchone()
    
    if not rep:
        conn.close()
        return

    cursor.execute("SELECT * FROM pagos WHERE agencia = %s AND fecha = %s AND estado = 'APROBADO'", (agencia_norm, fecha_reporte))
    todos_pagos = cursor.fetchall()
    
    cursor.execute("SELECT * FROM pagos WHERE agencia = %s AND tipo = 'AJUSTE_PENDIENTE' AND estado = 'APROBADO'", (agencia_norm,))
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
        monto_p = p['monto'] or 0.0
        tipo_p = str(p['tipo']).strip().upper() if p['tipo'] else 'PAGO_TAQUILLA'
        
        if tipo_p == 'ADELANTO':
            total_adelantos += monto_p
            adelantos_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['comprobante']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #e91e63; font-weight: bold;">- Bs. {monto_p:,.2f}</td>
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
        monto_aj = aj['monto'] or 0.0
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
        total_neto_sistemas = rep['ventas'] if rep['ventas'] > 0 else rep['monto']

    monto_final = total_neto_sistemas - total_pagos_taquilla - total_adelantos - total_cashea + total_ajustes_pendientes

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
        <h5 style="color: #e91e63; font-weight: bold; border-bottom: 2px solid #e91e63; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-hand-holding-usd"></i> ADELANTOS (Plata entregada por Admin)</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background-color: #fce4ec; color: #880e4f; font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">MOTIVO</th>
                <th style="padding: 10px; text-align: right;">MONTO DESCONTADO</th>
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
    cursor.execute("UPDATE reportes SET monto = %s, detalle_html = %s WHERE agencia = %s AND fecha = %s", (monto_final, detalle_actualizado, agencia_norm, fecha_reporte))
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

    hoy_str = datetime.now().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM reportes WHERE agencia = %s AND fecha = %s", (agencia, fecha))
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
        cursor.execute("SELECT id FROM pagos WHERE agencia = %s AND fecha = %s AND tipo = 'CASHEA'", (agencia, fecha))
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
    cursor.execute("SELECT clave FROM usuarios WHERE agencia = %s", (usuario_norm,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data and user_data['clave'] == clave:
        actualizar_ultima_conexion(usuario_norm)
        response = RedirectResponse(url=f"/agencia?nombre={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value=usuario_norm)
        return response

    return templates.TemplateResponse(request=request, name="login.html", context={"error": "Usuario o clave incorrectos"})

@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(request: Request, nombre: Optional[str] = None):
    if not nombre:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    agencia_norm = normalizar(nombre)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM usuarios WHERE agencia = %s", (agencia_norm,))
    agencia_info = cursor.fetchone()
    
    cursor.execute("SELECT * FROM reportes WHERE agencia = %s ORDER BY fecha DESC", (agencia_norm,))
    reportes_agencia = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM pagos WHERE agencia = %s ORDER BY id DESC", (agencia_norm,))
    pagos_agencia = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM comunicados ORDER BY id DESC")
    comunicados = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return templates.TemplateResponse(request=request, name="agencia.html", context={
        "agencia": agencia_info,
        "reportes": reportes_agencia,
        "pagos": pagos_agencia,
        "comunicados": comunicados,
        "nombre_agencia": agencia_norm
    })

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
        
        cursor.execute("SELECT * FROM comunicados ORDER BY id DESC")
        comunicados = [dict(row) for row in cursor.fetchall()]

        hoy_str = datetime.now().strftime('%Y-%m-%d')
        f_desde = desde_fecha if desde_fecha else hoy_str
        f_hasta = hasta_fecha if hasta_fecha else hoy_str
        agencia_filtro = agencia if agencia else ""

        if agencia_filtro:
            cursor.execute("SELECT * FROM pagos WHERE tipo = 'CASHEA' AND agencia = %s AND fecha >= %s AND fecha <= %s ORDER BY id DESC", (normalizar(agencia_filtro), f_desde, f_hasta))
        else:
            cursor.execute("SELECT * FROM pagos WHERE tipo = 'CASHEA' AND fecha >= %s AND fecha <= %s ORDER BY id DESC", (f_desde, f_hasta))
        casheas_generales = [dict(row) for row in cursor.fetchall()]

        total_taquillas_creadas = len(agencias)
        taquillas_activas_hoy = 0
        for ag in agencias:
            u_conn = ag.get('ultima_conexion') or ''
            if u_conn and u_conn.startswith(hoy_str):
                ag['estado_conexion'] = 'ACTIVA'
                taquillas_activas_hoy += 1
            elif u_conn:
                ag['estado_conexion'] = 'RECIENTE'
            else:
                ag['estado_conexion'] = 'SIN_CONEXION'

        sistemas_consolidados = {}
        totales_generales = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
        
        totales_auxiliares = {
            "cashea": 0.0,
            "adelantos": 0.0,
            "abonos_banca": 0.0
        }

        agencias_a_procesar = [normalizar(agencia_filtro)] if agencia_filtro else [a['agencia'] for a in agencias]

        for ag in agencias_a_procesar:
            cursor.execute(
                "SELECT * FROM reportes WHERE agencia = %s AND fecha >= %s AND fecha <= %s", 
                (ag, f_desde, f_hasta)
            )
            reps_db = cursor.fetchall()
            for rep_db in reps_db:
                if rep_db and rep_db['detalle_html']:
                    tabla_match = re.search(r'<table[^>]*>(.*?)<\/table>', rep_db['detalle_html'], re.DOTALL)
                    if tabla_match:
                        filas = re.findall(r'<tr[^>]*>(.*?)<\/tr>', tabla_match.group(1), re.DOTALL)
                        for f in filas:
                            cols = re.findall(r'<t[dh][^>]*>(.*?)<\/t[dh]>', f, re.DOTALL)
                            if len(cols) >= 5:
                                sys_nombre = re.sub(r'<[^>]+>', '', cols[0]).strip()
                                if not sys_nombre or "SISTEMA" in sys_nombre.upper() or "TOTALES" in sys_nombre.upper():
                                    continue
                                try:
                                    v = float(re.sub(r'[^\d.-]', '', cols[1]))
                                    c = float(re.sub(r'[^\d.-]', '', cols[2]))
                                    p = float(re.sub(r'[^\d.-]', '', cols[3]))
                                    t = float(re.sub(r'[^\d.-]', '', cols[4]))
                                except:
                                    v, c, p, t = 0.0, 0.0, 0.0, 0.0

                                if sys_nombre not in sistemas_consolidados:
                                    sistemas_consolidados[sys_nombre] = {"venta": 0.0, "comision": 0.0, "premio": 0.0, "neto": 0.0}
                                
                                sistemas_consolidados[sys_nombre]["venta"] += v
                                sistemas_consolidados[sys_nombre]["comision"] += c
                                sistemas_consolidados[sys_nombre]["premio"] += p
                                sistemas_consolidados[sys_nombre]["neto"] += t

                                totales_generales["venta"] += v
                                totales_generales["comision"] += c
                                totales_generales["premio"] += p
                                totales_generales["neto"] += t

            cursor.execute(
                "SELECT tipo, monto FROM pagos WHERE agencia = %s AND fecha >= %s AND fecha <= %s AND estado = 'APROBADO'",
                (ag, f_desde, f_hasta)
            )
            pagos_aux = cursor.fetchall()
            for pa in pagos_aux:
                m_val = pa['monto'] or 0.0
                t_type = str(pa['tipo']).strip().upper() if pa['tipo'] else ''
                if t_type == 'CASHEA':
                    totales_auxiliares["cashea"] += m_val
                elif t_type == 'ADELANTO':
                    totales_auxiliares["adelantos"] += m_val
                elif t_type in ['PAGO_TAQUILLA', 'PAGO_BANCA']:
                    totales_auxiliares["abonos_banca"] += m_val

        ESTRUCTURA_BANQUEROS = {
            "COMERCIALIZADORA SUPER APUESTAS": {
                "sistemas": [
                    {"sistema": "BETSOL", "pct_comision_completa": 0.15, "pct_participacion": 0.10, "tipo_participacion": "SALDO"}
                ],
                "cobranza": [],
                "absorbe_cashea": False
            },
            "COMERCIALIZADORA LOTTOLUCKY": {
                "sistemas": [
                    {"sistema": "LOTTOLUCKY", "pct_comision_completa": 0.17, "pct_participacion": 0.00, "tipo_participacion": "NINGUNA"}
                ],
                "cobranza": [],
                "absorbe_cashea": False
            },
            "COMERCIALIZADORA NYS": {
                "sistemas": [
                    {"sistema": "POZO", "pct_comision_completa": 0.11, "pct_participacion": 0.00, "tipo_participacion": "NINGUNA"},
                    {"sistema": "LA IMAGINARIA", "pct_comision_completa": 0.17, "pct_participacion": 0.35, "tipo_participacion": "TOTAL"},
                    {"sistema": "WINBIG POLLAS", "pct_comision_completa": 0.18, "pct_participacion": 0.00, "tipo_participacion": "NINGUNA"}
                ],
                "cobranza": [
                    {"nombre": "CALAMAR A", "pct_comision_completa": 0.17, "pct_participacion": 0.25},
                    {"nombre": "CALAMAR B", "pct_comision_completa": 0.17, "pct_participacion": 0.25}
                ],
                "absorbe_cashea": True
            },
            "COMERCIALIZADORA LIDER": {
                "sistemas": [
                    {"sistema": "MAXPLAY", "pct_comision_completa": 0.16, "pct_participacion": 0.20, "tipo_participacion": "TOTAL"},
                    {"sistema": "MATRIX", "pct_comision_completa": 0.16, "pct_participacion": 0.20, "tipo_participacion": "TOTAL"},
                    {"sistema": "SRQ", "pct_comision_completa": 0.16, "pct_participacion": 0.30, "tipo_participacion": "TOTAL"},
                    {"sistema": "LOTIPOS", "pct_comision_completa": 0.17, "pct_participacion": 0.20, "tipo_participacion": "TOTAL"},
                    {"sistema": "GATO", "pct_comision_completa": 0.16, "pct_participacion": 0.20, "tipo_participacion": "TOTAL"},
                    {"sistema": "PREMIER", "pct_comision_completa": 0.16, "pct_participacion": 0.00, "tipo_participacion": "NINGUNA"},
                    {"sistema": "POSNET", "pct_comision_completa": 0.15, "pct_participacion": 0.20, "tipo_participacion": "TOTAL"},
                    {"sistema": "PARLEY", "pct_comision_completa": 0.12, "pct_participacion": 0.20, "tipo_participacion": "TOTAL"}
                ],
                "cobranza": [
                    {"nombre": "GUACA", "pct_comision_completa": 0.17, "pct_participacion": 0.30},
                    {"nombre": "MEGA GUACA", "pct_comision_completa": 0.17, "pct_participacion": 0.30},
                    {"nombre": "TRIPLE GUACA", "pct_comision_completa": 0.17, "pct_participacion": 0.30}
                ],
                "absorbe_cashea": False
            },
            "COMERCIALIZADORA LOTTIPLAY": {
                "sistemas": [
                    {"sistema": "LOTTIPLAY", "pct_comision_completa": 0.15, "pct_participacion": 0.00, "tipo_participacion": "NINGUNA"}
                ],
                "cobranza": [],
                "absorbe_cashea": False
            }
        }

        desglose_banqueros = {}
        for b_nombre, cfg in ESTRUCTURA_BANQUEROS.items():
            desglose_banqueros[b_nombre] = {
                "sistemas": [],
                "cobranza": cfg["cobranza"],
                "cashea_descontado": totales_auxiliares["cashea"] if cfg["absorbe_cashea"] else 0.0,
                "total_a_pagar_banquero": 0.0,
                "total_mi_ganancia_banca": 0.0,
                "total": 0.0
            }

            for item in cfg["sistemas"]:
                s_name = item["sistema"]
                v_sys = sistemas_consolidados.get(s_name, {}).get("venta", 0.0)
                p_sys = sistemas_consolidados.get(s_name, {}).get("premio", 0.0)
                c_taquillas_pagada = sistemas_consolidados.get(s_name, {}).get("comision", 0.0)
                
                c_banquero_total = v_sys * item["pct_comision_completa"]
                t_banquero_sistema = v_sys - c_banquero_total - p_sys

                g_excedente_pct = c_banquero_total - c_taquillas_pagada
                pct_excedente_real = (g_excedente_pct / v_sys * 100) if v_sys > 0 else (item["pct_comision_completa"] * 100 - 13.0)

                s_upper = s_name.upper()
                pct_dif_val = pct_excedente_real  
                pct_part_val = item.get("pct_participacion", 0.0) * 100 if "pct_participacion" in item else 0.0

                if "BETSOL" in s_upper:
                    pct_dif_val = 3.0
                    pct_part_val = 10.0
                elif "POZO" in s_upper:
                    pct_dif_val = 1.0
                    pct_part_val = 0.0
                elif "MATRIX" in s_upper:
                    pct_dif_val = 4.0
                elif "GATO" in s_upper:
                    pct_dif_val = 4.0
                elif "POSNET" in s_upper:
                    pct_dif_val = 3.0
                elif "PARLEY" in s_upper:
                    pct_dif_val = 2.0

                g_total_privada = v_sys * (pct_dif_val / 100.0)

                desglose_banqueros[b_nombre]["sistemas"].append({
                    "sistema": s_name,
                    "venta": v_sys,
                    "comision_agencia": c_taquillas_pagada,
                    "premios": p_sys,
                    "total_banquero": t_banquero_sistema,
                    "pct_diferencial": int(pct_dif_val) if pct_dif_val.is_integer() else pct_dif_val,
                    "pct_participacion": int(pct_part_val) if pct_part_val.is_integer() else pct_part_val,
                    "mi_ganancia_total": g_total_privada
                })

                desglose_banqueros[b_nombre]["total"] += t_banquero_sistema

        conn.close()

        return templates.TemplateResponse(request=request, name="admin.html", context={
            "reportes": reportes,
            "pagos": pagos,
            "agencias": agencias,
            "comunicados": comunicados,
            "casheas_generales": casheas_generales,
            "total_taquillas_creadas": total_taquillas_creadas,
            "taquillas_activas_hoy": taquillas_activas_hoy,
            "sistemas_consolidados": sistemas_consolidados,
            "totales_generales": totales_generales,
            "totales_auxiliares": totales_auxiliares,
            "desglose_banqueros": desglose_banqueros,
            "desde_fecha": f_desde,
            "hasta_fecha": f_hasta,
            "agencia_filtro": agencia_filtro,
            "tab": tab
        })

    except Exception as e:
        print("Error en admin:", e)
        return HTMLResponse(content=f"Error interno en admin: {e}", status_code=500)
