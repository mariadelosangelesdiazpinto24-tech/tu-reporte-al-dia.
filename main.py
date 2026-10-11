import os
import urllib.parse as urlparse
import psycopg2
import psycopg2.extras
import unicodedata
import re
from typing import Optional
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
        url = urlparse.urlparse(database_url)
        conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port if url.port else 5432,
            sslmode='require',
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    else:
        # Fallback local si no hay variable de entorno
        import sqlite3
        conn = sqlite3.connect("database.db", timeout=30.0)
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Supabase / PostgreSQL tables setup
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            agencia TEXT UNIQUE,
            clave TEXT,
            genero TEXT DEFAULT 'FEMENINO'
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
    conn.close()

    total_tripletas = 0.0
    total_adelantos = 0.0
    total_pagos_taquilla = 0.0
    total_cashea = 0.0
    total_pagos_banca = 0.0
    
    tripletas_rows_html = ""
    adelantos_rows_html = ""
    cashea_rows_html = ""

    for p in todos_pagos:
        monto_p = p['monto'] or 0.0
        tipo_p = str(p['tipo']).strip().upper() if p['tipo'] else 'PAGO_TAQUILLA'
        
        if tipo_p == 'TRIPLETA':
            total_tripletas += monto_p
            tripletas_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['comprobante']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #2e7d32; font-weight: bold;">+ Bs. {monto_p:,.2f}</td>
            </tr>
            '''
        elif tipo_p == 'ADELANTO':
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
        elif tipo_p == 'PAGO_TAQUILLA':
            total_pagos_taquilla += monto_p
        elif tipo_p == 'PAGO_BANCA':
            total_pagos_banca += monto_p

    detalle_original = rep['detalle_html'] or ""
    
    match_sistemas = re.search(r'(<div class="mb-3"[^>]*>.*?REPORTE DE SISTEMAS.*?<\/table>.*?<\/div>)', detalle_original, re.DOTALL)
    tabla_sistemas_html = match_sistemas.group(1) if match_sistemas else ""
    if not tabla_sistemas_html:
        tabla_sistemas_html = detalle_original.split('<div')[0]

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

    monto_final = total_neto_sistemas - total_pagos_taquilla + total_tripletas - total_adelantos - total_cashea + total_pagos_banca

    bloque_cashea = f'''
    <div class="mb-3" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #00bcd4;">
        <h5 style="color: #0d47a1; font-weight: bold; border-bottom: 2px solid #00bcd4; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-shopping-cart" style="color: #00bcd4;"></i> CASHEA (Registros absorbidos)</h5>
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

    bloque_tripletas = f'''
    <div class="mb-3" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #ffb300;">
        <h5 style="color: #0d47a1; font-weight: bold; border-bottom: 2px solid #ffb300; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-star" style="color: #ffb300;"></i> TRIPLETAS (Premios pagados por taquilla)</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background-color: #e3f2fd; color: #0d47a1; font-size: 13px;">
                <th style="padding: 10px;">FECHA TICKET</th>
                <th style="padding: 10px;">DETALLE</th>
                <th style="padding: 10px; text-align: right;">MONTO A FAVOR</th>
            </tr>
            {tripletas_rows_html if tripletas_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">Ninguna (0)</td></tr>'}
        </table>
    </div>
    '''

    bloque_adelantos = f'''
    <div class="mb-3" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #e91e63;">
        <h5 style="color: #0d47a1; font-weight: bold; border-bottom: 2px solid #e91e63; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-hand-holding-usd" style="color: #e91e63;"></i> ADELANTOS (Plata entregada por Admin - Se resta)</h5>
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
    <div class="mb-2" style="background: #ffffff; border-radius: 12px; padding: 20px; color: #1a252c; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border-left: 6px solid #0d47a1; border: 1px solid #e0e0e0;">
        <h5 style="color: #0d47a1; font-weight: bold; border-bottom: 1px solid #e0e0e0; padding-bottom: 10px; margin-bottom: 12px;"><i class="fas fa-clock"></i> ESTADO DE CUENTA FINAL</h5>
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <span style="font-size: 14px; color: #333; font-weight: bold;">Fecha: {fecha_reporte}</span>
            <span style="font-size: 14px; font-weight: bold; color: #333;">{("Total a Pagar" if monto_final >= 0 else "Saldo a favor / Solicitar")}</span>
            <span style="font-size: 18px; font-weight: bold; color: {('#2e7d32' if monto_final < 0 else '#e91e63')};">Bs. {monto_final:,.2f}</span>
        </div>
    </div>
    '''

    detalle_actualizado = tabla_sistemas_html + bloque_cashea + bloque_tripletas + bloque_adelantos + bloque_pendientes

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE reportes SET monto = %s, detalle_html = %s WHERE agencia = %s AND fecha = %s", (monto_final, detalle_actualizado, agencia_norm, fecha_reporte))
    conn.commit()
    conn.close()

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
        response = RedirectResponse(url=f"/agencia?nombre={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value=usuario_norm)
        return response

    return templates.TemplateResponse(request=request, name="login.html", context={"error": "Usuario o clave incorrectos"})

@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reportes ORDER BY id DESC")
        reportes = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM pagos ORDER BY id DESC")
        pagos = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM usuarios ORDER BY id DESC")
        agencias = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM comunicados ORDER BY id DESC")
        comunicados = [dict(row) for row in cursor.fetchall()]

        historial_comunicados = []
        for com in comunicados:
            c_dict = dict(com)
            cursor.execute("SELECT agencia FROM lecturas_comunicados WHERE comunicado_id = %s", (com['id'],))
            leidos = [row['agencia'] for row in cursor.fetchall()]
            
            no_leidos = [ag['agencia'] for ag in agencias if ag['agencia'] not in leidos]
            c_dict['leidos'] = leidos
            c_dict['no_leidos'] = no_leidos
            historial_comunicados.append(c_dict)

        positivos = [r for r in reportes if r['monto'] > 0]
        negativos = [r for r in reportes if r['monto'] < 0]

        conn.close()
    except:
        reportes, pagos, agencias, historial_comunicados, positivos, negativos = [], [], [], [], [], []

    return templates.TemplateResponse(request=request, name="admin.html", context={
        "reportes": reportes, 
        "pagos": pagos, 
        "agencias": agencias, 
        "comunicados": historial_comunicados,
        "positivos": positivos,
        "negativos": negativos
    })

@app.post("/admin/crear-agencia")
def crear_agencia(agencia: str = Form(...), clave: str = Form(...), genero: str = Form("FEMENINO")):
    agencia_norm = normalizar(agencia)
    genero_val = genero.upper()
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM usuarios WHERE agencia = %s", (agencia_norm,))
    existe = cursor.fetchone()
    
    if existe:
        cursor.execute("UPDATE usuarios SET clave = %s, genero = %s WHERE agencia = %s", (clave, genero_val, agencia_norm))
    else:
        cursor.execute("INSERT INTO usuarios (agencia, clave, genero) VALUES (%s, %s, %s)", (agencia_norm, clave, genero_val))
            
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/publicar-comunicado")
def publicar_comunicado(mensaje: str = Form(...)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO comunicados (mensaje) VALUES (%s)", (mensaje,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/pagar-solicitud-banca")
async def pagar_solicitud_banca(pago_id: int = Form(...), comprobante: UploadFile = File(...)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos WHERE id = %s", (pago_id,))
    pago = cursor.fetchone()

    if pago:
        agencia_norm = normalizar(pago['agencia'])
        fecha_pago = pago['fecha']
        monto_pago = pago['monto']
        
        ruta_archivo = f"uploads/BANCA_{agencia_norm}_{pago_id}_{comprobante.filename}"
        with open(ruta_archivo, "wb") as buffer:
            buffer.write(await comprobante.read())

        cursor.execute("UPDATE pagos SET estado = 'APROBADO', comprobante = %s WHERE id = %s", (ruta_archivo, pago_id))
        cursor.execute(
            "INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, 'PAGO DE REPORTES', %s, 'PAGO_BANCA', 'APROBADO')",
            (agencia_norm, fecha_pago, monto_pago, ruta_archivo)
        )
        conn.commit()
        conn.close()
        recalcular_y_actualizar_reporte(agencia_norm, fecha_pago)
    else:
        conn.close()

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(request: Request, nombre: str = ""):
    nombre_norm = normalizar(nombre)
    conn = get_db()
    cursor = conn.cursor()
    
    genero_taquilla = "FEMENINO"
    cursor.execute("SELECT genero FROM usuarios WHERE agencia = %s", (nombre_norm,))
    usr = cursor.fetchone()
    if usr and 'genero' in usr.keys() and usr['genero']:
        genero_taquilla = usr['genero']

    cursor.execute("SELECT * FROM reportes WHERE agencia = %s ORDER BY id DESC", (nombre_norm,))
    mis_reportes = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM pagos WHERE agencia = %s ORDER BY id DESC", (nombre_norm,))
    mis_pagos = [dict(row) for row in cursor.fetchall()]
    mis_casheas = [p for p in mis_pagos if str(p['tipo']).strip().upper() == 'CASHEA']
    notificaciones_banca = []
    
    cursor.execute("SELECT * FROM comunicados ORDER BY id DESC")
    todos_comunicados = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT comunicado_id FROM lecturas_comunicados WHERE agencia = %s", (nombre_norm,))
    leidos_ids = [row['comunicado_id'] for row in cursor.fetchall()]
    
    comunicados_pendientes = [c for c in todos_comunicados if c['id'] not in leidos_ids]

    conn.close()

    return templates.TemplateResponse(request=request, name="agencia.html", context={
        "agencia": nombre_norm, 
        "genero": genero_taquilla,
        "reportes": mis_reportes, 
        "pagos": mis_pagos, 
        "casheas": mis_casheas,
        "notificaciones": notificaciones_banca,
        "comunicados_pendientes": comunicados_pendientes,
        "todos_comunicados": todos_comunicados,
        "sistemas": SISTEMAS_OFICIALES
    })

@app.post("/marcar-comunicado-leido")
def marcar_comunicado_leido(agencia: str = Form(...), comunicado_id: int = Form(...)):
    agencia_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO lecturas_comunicados (comunicado_id, agencia, leido) VALUES (%s, %s, 1) ON CONFLICT (comunicado_id, agencia) DO NOTHING", (comunicado_id, agencia_norm))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/reportar")
async def reportar_pago(agencia: str = Form(...), fecha: str = Form(...), monto: str = Form(...), factura: str = Form(...), comprobante: UploadFile = File(...)):
    agencia_norm = normalizar(agencia)
    try:
        monto_val = float(monto.replace(',', '')) if monto else 0.0
    except:
        monto_val = 0.0
        
    ruta_archivo = f"uploads/{agencia_norm}_{factura}_{comprobante.filename}"
    with open(ruta_archivo, "wb") as buffer:
        buffer.write(await comprobante.read())

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, %s, %s, 'PAGO_TAQUILLA', 'EN ESPERA')", (agencia_norm, fecha, monto_val, factura, ruta_archivo))
    conn.commit()
    conn.close()
    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/solicitar-banca")
def solicitar_banca(agencia: str = Form(...), fecha: str = Form(...), monto: str = Form(...)):
    agencia_norm = normalizar(agencia)
    try:
        monto_val = abs(float(str(monto).replace(',', '')))
    except:
        monto_val = 0.0

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, 'SOLICITUD BANCA', 'Solicitud de cobro por saldo a favor', 'SOLICITUD_BANCA', 'PENDIENTE BANCA')",
        (agencia_norm, fecha, monto_val)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/solicitar-adelanto")
def solicitar_adelanto(agencia: str = Form(...), fecha: str = Form(...), monto: str = Form(...), observacion: str = Form(...)):
    agencia_norm = normalizar(agencia)
    try:
        monto_val = float(monto.replace(',', '')) if monto else 0.0
    except:
        monto_val = 0.0

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, %s, %s, 'ADELANTO', 'APROBADO')", (agencia_norm, fecha, monto_val, observacion, observacion))
    conn.commit()
    conn.close()
    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/reportar-tripleta")
def reportar_tripleta(agencia: str = Form(...), fecha: str = Form(...), sistema: str = Form(...), ticket: str = Form(...), monto: str = Form(...)):
    agencia_norm = normalizar(agencia)
    try:
        monto_val = float(monto.replace(',', '')) if monto else 0.0
    except:
        monto_val = 0.0
        
    detalle_str = f"Sistema: {sistema} | Ticket: {ticket}"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, %s, %s, 'TRIPLETA', 'APROBADO')", (agencia_norm, fecha, monto_val, ticket, detalle_str))
    conn.commit()
    conn.close()
    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/actualizar-reporte-sistema")
def actualizar_reporte_sistema(agencia: str = Form(...), fecha: str = Form(...), sistema: str = Form(...), venta: str = Form(...), premio: str = Form(...)):
    agencia_norm = normalizar(agencia)
    sistema_buscado = normalizar(sistema)
    
    try:
        venta_val = float(str(venta).replace(',', '')) if venta else 0.0
    except:
        venta_val = 0.0
        
    try:
        premio_val = float(str(premio).replace(',', '')) if premio else 0.0
    except:
        premio_val = 0.0

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reportes WHERE agencia = %s AND fecha = %s", (agencia_norm, fecha))
    rep = cursor.fetchone()

    if rep:
        detalle_html = rep['detalle_html'] or ""
        
        match_sistemas_div = re.search(r'(<div class="mb-3"[^>]*>.*?REPORTE DE SISTEMAS.*?<\/table>.*?<\/div>)', detalle_html, re.DOTALL)
        if match_sistemas_div:
            tabla_html_actual = match_sistemas_div.group(1)
            filas_datos = re.findall(r'<tr>\s*<td[^>]*>(.*?)<\/td>\s*<td[^>]*>(.*?)<\/td>\s*<td[^>]*>(.*?)<\/td>\s*<td[^>]*>(.*?)<\/td>\s*<td[^>]*>(.*?)<\/td>\s*<\/tr>', tabla_html_actual, re.DOTALL)
            
            sum_ventas = 0.0
            sum_comis = 0.0
            sum_premios = 0.0
            sum_totales = 0.0
            
            filas_nuevas_html = '''
            <div class="mb-3">
                <h6 style="color: #0d47a1; font-weight: bold; border-bottom: 2px solid #0d47a1; padding-bottom: 5px; margin-bottom: 10px;"><i class="fas fa-chart-bar"></i> REPORTE DE SISTEMAS</h6>
                <table class="table table-sm table-bordered align-middle mb-0" style="font-size: 12px; width: 100%; background: #ffffff; color: #1a252c;">
                    <tr style="background-color: #e3f2fd; color: #0d47a1; font-weight: bold;">
                        <th style="padding: 8px;">SISTEMA</th>
                        <th style="padding: 8px; text-align: right;">VENTA</th>
                        <th style="padding: 8px; text-align: right;">COMIS.</th>
                        <th style="padding: 8px; text-align: right;">PREMIO</th>
                        <th style="padding: 8px; text-align: right;">TOTAL</th>
                    </tr>
            '''
            
            for f in filas_datos:
                sys_nombre_raw = f[0].replace('<b>', '').replace('</b>', '').strip()
                sys_nombre_norm = normalizar(sys_nombre_raw)
                
                if "SISTEMA" in sys_nombre_norm or "TOTALES" in sys_nombre_norm or "TRIPLETA" in sys_nombre_norm:
                    continue
                
                if sys_nombre_norm == sistema_buscado:
                    v = venta_val
                    p = premio_val
                    c = v * 0.14
                    t = v - c - p
                else:
                    try:
                        v = float(str(f[1]).replace(',', ''))
                        c = float(str(f[2]).replace(',', ''))
                        p = float(str(f[3]).replace(',', ''))
                        t = float(str(f[4]).replace(',', ''))
                    except:
                        v, c, p, t = 0.0, 0.0, 0.0, 0.0
                
                sum_ventas += v
                sum_comis += c
                sum_premios += p
                sum_totales += t
                
                filas_nuevas_html += f'''
                <tr>
                  <td style="padding: 8px; font-weight: bold;">{sys_nombre_raw}</td>
                  <td style="padding: 8px; text-align: right;">{v:,.2f}</td>
                  <td style="padding: 8px; text-align: right;">{c:,.2f}</td>
                  <td style="padding: 8px; text-align: right;">{p:,.2f}</td>
                  <td style="padding: 8px; text-align: right;">{t:,.2f}</td>
                </tr>
                '''
            
            filas_nuevas_html += f'''
                <tr style="background-color: #f5f5f5; font-weight: bold;">
                  <td style="padding: 8px;">TOTALES</td>
                  <td style="padding: 8px; text-align: right;">{sum_ventas:,.2f}</td>
                  <td style="padding: 8px; text-align: right;">{sum_comis:,.2f}</td>
                  <td style="padding: 8px; text-align: right;">{sum_premios:,.2f}</td>
                  <td style="padding: 8px; text-align: right; color: #0d47a1;">{sum_totales:,.2f}</td>
                </tr>
            </table></div>
            '''
            
            detalle_html = detalle_html.replace(tabla_html_actual, filas_nuevas_html)
            cursor.execute("UPDATE reportes SET ventas = %s WHERE id = %s", (sum_totales, rep['id']))

        cursor.execute("UPDATE reportes SET detalle_html = %s WHERE id = %s", (detalle_html, rep['id']))
        conn.commit()

    detalle_transaccion = f"Modificación {sistema} - Venta: {venta_val:,.2f} | Premio: {premio_val:,.2f}"
    cursor.execute(
        "INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, 'MODIFICACION', %s, 'MODIFICACION', 'APROBADO')",
        (agencia_norm, fecha, 0.0, detalle_transaccion)
    )
    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/guardar-reporte-colab")
def guardar_reporte_colab(
    agencia: str = Form(...), 
    fecha: str = Form(...), 
    monto: float = Form(...), 
    ventas: float = Form(0.0), 
    premios: float = Form(0.0), 
    detalle_html: Optional[str] = Form(""),
    cashea_monto: Optional[float] = Form(0.0),
    cashea_detalle: Optional[str] = Form("")
):
    agencia_norm = normalizar(agencia)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM reportes WHERE agencia = %s AND fecha = %s", (agencia_norm, fecha))
    existente = cursor.fetchone()
    
    if existente:
        cursor.execute("UPDATE reportes SET monto = %s, ventas = %s, premios = %s, detalle_html = %s WHERE agencia = %s AND fecha = %s", (monto, ventas, premios, detalle_html, agencia_norm, fecha))
    else:
        cursor.execute("INSERT INTO reportes (agencia, fecha, monto, ventas, premios, detalle_html) VALUES (%s, %s, %s, %s, %s, %s)", (agencia_norm, fecha, monto, ventas, premios, detalle_html))
        
    if cashea_monto and cashea_monto > 0:
        cursor.execute("SELECT id FROM pagos WHERE agencia = %s AND fecha = %s AND tipo = 'CASHEA'", (agencia_norm, fecha))
        existe_cashea = cursor.fetchone()
        if not existe_cashea:
            cursor.execute(
                "INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado) VALUES (%s, %s, %s, %s, %s, 'CASHEA', 'APROBADO')",
                (agencia_norm, fecha, cashea_monto, cashea_detalle or "CASHEA Automático", cashea_detalle or "Sincronizado de Sheet")
            )

    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return {"status": "ok", "mensaje": f"Reporte y Cashea sincronizados para {agencia_norm}"}
