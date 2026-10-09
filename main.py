import os
import sqlite3
import unicodedata
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
    
    cursor.execute("PRAGMA table_info(usuarios)")
    columnas_u = [col[1] for col in cursor.fetchall()]
    if not columnas_u or 'agencia' not in columnas_u:
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
            estado TEXT DEFAULT 'EN ESPERA'
        )
    ''')
    
    cursor.execute("PRAGMA table_info(pagos)")
    columnas_p = [col[1] for col in cursor.fetchall()]
    if 'tipo' not in columnas_p:
        cursor.execute("ALTER TABLE pagos ADD COLUMN tipo TEXT DEFAULT 'PAGO_TAQUILLA'")
    if 'estado' not in columnas_p:
        cursor.execute("ALTER TABLE pagos ADD COLUMN estado TEXT DEFAULT 'EN ESPERA'")
        
    conn.commit()
    conn.close()

init_db()

def aplicar_formula_y_actualizar(agencia: str, fecha: str):
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes WHERE agencia = ? AND fecha = ?", (agencia, fecha))
    rep = cursor.fetchone()
    
    if not rep:
        conn.close()
        return

    # Sumar solo movimientos aprobados o automáticos (como tripletas y pendientes directos)
    cursor.execute("SELECT tipo, SUM(monto) as total FROM pagos WHERE agencia = ? AND fecha = ? AND estado = 'APROBADO' GROUP BY tipo", (agencia, fecha))
    movimientos = {row['tipo']: row['total'] for row in cursor.fetchall()}
    conn.close()

    total_tripletas = movimientos.get('TRIPLETA', 0.0)
    total_adelantos = movimientos.get('ADELANTO', 0.0)
    total_pendientes = movimientos.get('PENDIENTE_POR_COBRAR', 0.0)
    
    monto_base = rep['ventas'] if rep['ventas'] > 0 else rep['monto']
    
    # Fórmula: Reporte - Tripletas + Adelantos + Pendientes
    monto_final = monto_base - total_tripletas + total_adelantos + total_pendientes

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reportes SET monto = ? WHERE id = ?", (monto_final, rep['id']))
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
        aplicar_formula_y_actualizar(pago['agencia'], pago['fecha'])

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

    conn.close()

    return templates.TemplateResponse(
        request=request, 
        name="agencia.html", 
        context={"agencia": nombre_norm, "reportes": mis_reportes, "pagos": mis_pagos}
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

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (?, ?, ?, ?, ?, 'SOLICITUD_SALDO', 'EN ESPERA')
    ''', (agencia_norm, fecha, monto_val, observacion))
    conn.commit()
    conn.close()

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
        VALUES (?, ?, ?, ?, ?, 'ADELANTO', 'EN ESPERA')
    ''', (agencia_norm, fecha, monto_val, observacion))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&adelanto=1", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/reportar-pendiente")
def reportar_pendiente(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: str = Form(...),
    observacion: str = Form(...)
):
    agencia_norm = normalizar(agencia)
    monto_val = float(monto.replace(',', '')) if monto else 0.0

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    # Entra AUTOMÁTICAMENTE APROBADO para que afecte la cuenta de inmediato
    cursor.execute('''
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (?, ?, ?, ?, 'Automático', 'PENDIENTE_POR_COBRAR', 'APROBADO')
    ''', (agencia_norm, fecha, monto_val, observacion))
    conn.commit()
    conn.close()

    aplicar_formula_y_actualizar(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&pendiente=1", status_code=status.HTTP_303_SEE_OTHER)

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
    # Entra AUTOMÁTICAMENTE APROBADO para que entre directo a la cuenta
    cursor.execute('''
        INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
        VALUES (?, ?, ?, ?, 'Automático', 'TRIPLETA', 'APROBADO')
    ''', (agencia_norm, fecha, monto_val, detalle_str))
    conn.commit()
    conn.close()

    aplicar_formula_y_actualizar(agencia_norm, fecha)
    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&tripleta=1", status_code=status.HTTP_303_SEE_OTHER)

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
    
    if not detalle_html or len(detalle_html.strip()) < 5:
        detalle_html = f'''
        <div class="card bg-dark text-white p-3 border-info shadow">
            <h5 class="text-info border-bottom pb-2"><i class="fas fa-chart-pie"></i> Resumen General</h5>
            <p class="mb-1"><b>Ventas Totales:</b> Bs. {ventas:.2f}</p>
            <p class="mb-1"><b>Premios Pagados:</b> Bs. {premios:.2f}</p>
            <h4 class="text-warning mt-2"><b>TOTAL A PAGAR:</b> Bs. {monto:.2f}</h4>
        </div>
        '''

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

    aplicar_formula_y_actualizar(agencia_norm, fecha)

    return {"status": "ok", "mensaje": f"Reporte sincronizado para {agencia_norm}"}
