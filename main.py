import os
import sqlite3
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

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    # Verificar o crear tabla usuarios completa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT UNIQUE,
            clave TEXT
        )
    ''')
    
    # Verificar si faltan columnas en usuarios existente
    cursor.execute("PRAGMA table_info(usuarios)")
    columnas_u = [col[1] for col in cursor.fetchall()]
    if 'agencia' not in columnas_u:
        cursor.execute("DROP TABLE IF EXISTS usuarios")
        cursor.execute('''
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agencia TEXT UNIQUE,
                clave TEXT
            )
        ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reportes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT,
            fecha TEXT,
            monto REAL,
            ventas REAL DEFAULT 0,
            premios REAL DEFAULT 0,
            detalle_html TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT,
            fecha TEXT,
            monto REAL,
            factura TEXT,
            comprobante TEXT,
            tipo TEXT DEFAULT 'PAGO_TAQUILLA',
            estado TEXT DEFAULT 'APROBADO'
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def recalcular_y_actualizar_reporte(agencia: str, fecha_reporte: str):
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes WHERE agencia = ? AND fecha = ?", (agencia, fecha_reporte))
    rep = cursor.fetchone()
    
    if not rep:
        conn.close()
        return

    cursor.execute("SELECT * FROM pagos WHERE agencia = ? AND fecha = ? AND estado = 'APROBADO'", (agencia, fecha_reporte))
    todos_pagos = cursor.fetchall()
    conn.close()

    total_tripletas = 0.0
    total_adelantos = 0.0
    total_pagos_taquilla = 0.0
    total_cashea = 0.0
    
    tripletas_rows_html = ""
    adelantos_rows_html = ""
    cashea_rows_html = ""

    for p in todos_pagos:
        monto_p = p['monto'] or 0.0
        tipo_p = str(p['tipo']).strip().upper()
        
        if tipo_p == 'TRIPLETA':
            total_tripletas += monto_p
            tripletas_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['comprobante']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #ffb300; font-weight: bold;">+ Bs. {monto_p:,.2f}</td>
            </tr>
            '''
        elif tipo_p == 'ADELANTO':
            total_adelantos += monto_p
            adelantos_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['comprobante']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #ffb300; font-weight: bold;">+ Bs. {monto_p:,.2f}</td>
            </tr>
            '''
        elif tipo_p == 'CASHEA':
            total_cashea += monto_p
            cashea_rows_html += f'''
            <tr style="font-size: 13px; background-color: #ffffff; color: #1a252c;">
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">{p['fecha']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">Factura: {p['factura']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; color: #e91e63; font-weight: bold;">Bs. {monto_p:,.2f}</td>
            </tr>
            '''
        elif tipo_p == 'PAGO_TAQUILLA':
            total_pagos_taquilla += monto_p

    detalle_original = rep['detalle_html'] or ""
    
    match_sistemas = re.search(r'(<div class="mb-4" style="background: #ffffff; border-radius: 12px; padding: 20px;.*?REPORTE DE SISTEMAS.*?<\/div>\s*<\/div>)', detalle_original, re.DOTALL)
    tabla_sistemas_html = match_sistemas.group(1) if match_sistemas else ""
    if not tabla_sistemas_html:
        tabla_sistemas_html = detalle_original.split('<!-- CASHEA -->')[0]

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

    monto_final = total_neto_sistemas - total_pagos_taquilla + total_tripletas + total_adelantos - total_cashea

    bloque_tripletas = f'''
    <div class="mb-4" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #ffb300;">
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
    <div class="mb-4" style="background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid #ffb300;">
        <h5 style="color: #0d47a1; font-weight: bold; border-bottom: 2px solid #ffb300; padding-bottom: 10px; margin-bottom: 15px;"><i class="fas fa-hand-holding-usd"></i> ADELANTOS (Plata entregada por Admin)</h5>
        <table class="table table-sm align-middle mb-0" style="width: 100%;">
            <tr style="background-color: #e3f2fd; color: #0d47a1; font-size: 13px;">
                <th style="padding: 10px;">FECHA</th>
                <th style="padding: 10px;">MOTIVO</th>
                <th style="padding: 10px; text-align: right;">MONTO</th>
            </tr>
            {adelantos_rows_html if adelantos_rows_html else '<tr><td colspan="3" class="text-center text-muted py-3" style="font-size: 13px;">Adelanto: 0.00 Bs.</td></tr>'}
        </table>
    </div>
    '''

    bloque_pendientes = f'''
    <div class="mb-2" style="background: #ffffff; border-radius: 12px; padding: 20px; color: #1a252c; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border-left: 6px solid #0d47a1; border: 1px solid #e0e0e0;">
        <h5 style="color: #0d47a1; font-weight: bold; border-bottom: 1px solid #e0e0e0; padding-bottom: 10px; margin-bottom: 12px;"><i class="fas fa-clock"></i> ESTADO DE CUENTA FINAL</h5>
        <div class="d-flex justify-content-between align-items-center">
            <span style="font-size: 14px; color: #555;">Fecha: {fecha_reporte}</span>
            <span style="font-size: 14px; font-weight: bold; color: #333;">{("Total a Pagar" if monto_final >= 0 else "Saldo a favor / Solicitar")}</span>
            <span style="font-size: 18px; font-weight: bold; color: {('#2e7d32' if monto_final < 0 else '#e91e63')};">Bs. {monto_final:,.2f}</span>
        </div>
    </div>
    '''

    match_cashea_orig = re.search(r'(<div class="mb-4" style="background: #ffffff; border-radius: 12px; padding: 20px;.*?CASHEA.*?<\/div>\s*<\/div>)', detalle_original, re.DOTALL)
    tabla_cashea_html = match_cashea_orig.group(1) if match_cashea_orig else ""

    detalle_actualizado = tabla_sistemas_html + tabla_cashea_html + bloque_tripletas + bloque_adelantos + bloque_pendientes

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reportes SET monto = ?, detalle_html = ? WHERE id = ?", (monto_final, detalle_actualizado, rep['id']))
    conn.commit()
    conn.close()

@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
def post_login(
    request: Request, 
    usuario: Optional[str] = Form(None), 
    clave: Optional[str] = Form(None)
):
    if not usuario or not clave:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Ingresa usuario y clave"})

    usuario_norm = normalizar(usuario)

    if usuario_norm == "ADMIN" and clave == "admin123":
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value="ADMIN")
        return response

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT clave FROM usuarios WHERE agencia = ?", (usuario_norm,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data and user_data[0] == clave:
        response = RedirectResponse(url=f"/agencia?nombre={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value=usuario_norm)
        return response

    return templates.TemplateResponse(request=request, name="login.html", context={"error": "Usuario o clave incorrectos"})

@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request):
    try:
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reportes ORDER BY id DESC")
        reportes = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM pagos ORDER BY id DESC")
        pagos = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM usuarios ORDER BY id DESC")
        agencias = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        reportes, pagos, agencias = [], [], []

    return templates.TemplateResponse(
        request=request, 
        name="admin.html", 
        context={"reportes": reportes, "pagos": pagos, "agencias": agencias}
    )

@app.post("/admin/crear-agencia")
def crear_agencia(agencia: str = Form(...), clave: str = Form(...)):
    agencia_norm = normalizar(agencia)
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM usuarios WHERE agencia = ?", (agencia_norm,))
    existe = cursor.fetchone()
    if existe:
        cursor.execute("UPDATE usuarios SET clave = ? WHERE agencia = ?", (clave, agencia_norm))
    else:
        cursor.execute("INSERT INTO usuarios (agencia, clave) VALUES (?, ?)", (agencia_norm, clave))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/cambiar-estado-pago")
def cambiar_estado_pago(pago_id: int = Form(...), nuevo_estado: str = Form(...)):
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT agencia, fecha FROM pagos WHERE id = ?", (pago_id,))
    pago = cursor.fetchone()
    
    cursor.execute("UPDATE pagos SET estado = ? WHERE id = ?", (nuevo_estado, pago_id))
    conn.commit()
    conn.close()

    if pago:
        recalcular_y_actualizar_reporte(pago['agencia'], pago['fecha'])

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(request: Request, nombre: str = ""):
    nombre_norm = normalizar(nombre)
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes WHERE agencia = ? ORDER BY id DESC", (nombre_norm,))
    mis_reportes = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM pagos WHERE agencia = ? ORDER BY id DESC", (nombre_norm,))
    mis_pagos = [dict(row) for row in cursor.fetchall()]

    mis_casheas = [p for p in mis_pagos if str(p['tipo']).strip().upper() == 'CASHEA']

    conn.close()

    return templates.TemplateResponse(
        request=request, 
        name="agencia.html", 
        context={"agencia": nombre_norm, "reportes": mis_reportes, "pagos": mis_pagos, "casheas": mis_casheas}
    )

@app.post("/reportar")
async def reportar_pago(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: str = Form(...),
    factura: str = Form(...),
    comprobante: UploadFile = File(...)
):
    agencia_norm = normalizar(agencia)
    monto_val = float(monto.replace(',', '')) if monto else 0.0

    ruta_archivo = f"uploads/{agencia_norm}_{factura}_{comprobante.filename}"
    with open(ruta_archivo, "wb") as buffer:
        buffer.write(await comprobante.read())

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (?, ?, ?, ?, ?, 'PAGO_TAQUILLA', 'EN ESPERA')
    ''', (agencia_norm, fecha, monto_val, factura, ruta_archivo))
    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&exito=1", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/solicitar-saldo")
def solicitar_saldo(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: str = Form(...),
    observacion: str = Form(...)
):
    agencia_norm = normalizar(agencia)
    monto_val = float(monto.replace(',', '')) if monto else 0.0
    tipo_pago = 'CASHEA' if 'CASHEA' in observacion.upper() else 'SOLICITUD_SALDO'

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (?, ?, ?, ?, ?, ?, 'APROBADO')
    ''', (agencia_norm, fecha, monto_val, observacion, observacion, tipo_pago))
    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&solicitud=1", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/solicitar-adelanto")
def solicitar_adelanto(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: str = Form(...),
    observacion: str = Form(...)
):
    agencia_norm = normalizar(agencia)
    monto_val = float(monto.replace(',', '')) if monto else 0.0

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (?, ?, ?, ?, ?, 'ADELANTO', 'APROBADO')
    ''', (agencia_norm, fecha, monto_val, observacion, observacion))
    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&adelanto=1", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/reportar-tripleta")
def reportar_tripleta(
    agencia: str = Form(...),
    fecha: str = Form(...),
    sistema: str = Form(...),
    ticket: str = Form(...),
    monto: str = Form(...)
):
    agencia_norm = normalizar(agencia)
    monto_val = float(monto.replace(',', '')) if monto else 0.0
    detalle_str = f"Sistema: {sistema} | Ticket: {ticket}"

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (?, ?, ?, ?, ?, 'TRIPLETA', 'APROBADO')
    ''', (agencia_norm, fecha, monto_val, ticket, detalle_str))
    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tripleta=1", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/actualizar-reporte-sistema")
def actualizar_reporte_sistema(
    agencia: str = Form(...),
    fecha: str = Form(...),
    sistema: str = Form(...),
    venta: str = Form(...),
    premio: str = Form(...)
):
    agencia_norm = normalizar(agencia)
    venta_val = float(venta.replace(',', '')) if venta else 0.0
    premio_val = float(premio.replace(',', '')) if premio else 0.0

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reportes WHERE agencia = ? AND fecha = ?", (agencia_norm, fecha))
    rep = cursor.fetchone()

    if rep:
        detalle_html = rep['detalle_html'] or ""
        comision_val = venta_val * 0.14
        total_sistema = venta_val - comision_val - premio_val

        patron_fila = re.compile(rf'(<tr>\s*<td[^>]*>\s*(?:<b>)?{re.escape(sistema)}(?:<\/b>)?<\/td>.*?<\/tr>)', re.IGNORECASE | re.DOTALL)
        
        nueva_fila = f'''
        <tr style="border-bottom: 1px solid #e0e0e0; font-size: 12px; color: #1a252c;">
          <td style="padding: 8px; text-align: left; font-weight: bold;">{sistema}</td>
          <td style="padding: 8px; text-align: right; color: #333;">{venta_val:,.2f}</td>
          <td style="padding: 8px; text-align: right; color: #333;">{comision_val:,.2f}</td>
          <td style="padding: 8px; text-align: right; color: #333;">{premio_val:,.2f}</td>
          <td style="padding: 8px; text-align: right; font-weight: bold; color: #0d47a1;">{total_sistema:,.2f}</td>
        </tr>
        '''

        if patron_fila.search(detalle_html):
            detalle_html = patron_fila.sub(nueva_fila, detalle_html)
        
        cursor.execute("UPDATE reportes SET detalle_html = ? WHERE id = ?", (detalle_html, rep['id']))
        conn.commit()

    conn.close()
    recalcular_y_actualizar_reporte(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&modificado=1", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/guardar-reporte-colab")
def guardar_reporte_colab(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: float = Form(...),
    ventas: float = Form(0.0),
    premios: float = Form(0.0),
    detalle_html: Optional[str] = Form("")
):
    agencia_norm = normalizar(agencia)
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM reportes WHERE agencia = ? AND fecha = ?", (agencia_norm, fecha))
    existente = cursor.fetchone()
    
    if existente:
        cursor.execute('''
            UPDATE reportes 
            SET monto = ?, ventas = ?, premios = ?, detalle_html = ?
            WHERE agencia = ? AND fecha = ?
        ''', (monto, ventas, premios, detalle_html, agencia_norm, fecha))
    else:
        cursor.execute('''
            INSERT INTO reportes (agencia, fecha, monto, ventas, premios, detalle_html)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (agencia_norm, fecha, monto, ventas, premios, detalle_html))
        
    conn.commit()
    conn.close()

    recalcular_y_actualizar_reporte(agencia_norm, fecha)

    return {"status": "ok", "mensaje": f"Reporte sincronizado para {agencia_norm}"}
