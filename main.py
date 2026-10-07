import os
import sqlite3
import unicodedata
from typing import Optional
from fastapi import FastAPI, Request, Form, UploadFile, File, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Directorios de almacenamiento
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

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    # Tabla de Usuarios / Agencias
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT UNIQUE,
            clave TEXT
        )
    ''')
    
    # Tabla de Historial de Reportes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reportes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT,
            fecha TEXT,
            monto REAL,
            factura TEXT,
            comprobante TEXT,
            estado TEXT DEFAULT 'PENDIENTE'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- LOGIN ---
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
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Por favor ingresa usuario y clave"})

    usuario_norm = normalizar(usuario)

    # Credenciales del Administrador Master
    if usuario_norm == "ADMIN" and clave == "admin123":
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value="ADMIN")
        return response

    # Validar usuarios creados en la Base de Datos
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

# --- PANEL ADMIN ---
@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request):
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reportes ORDER BY id DESC")
    reportes = cursor.fetchall()
    
    cursor.execute("SELECT * FROM usuarios ORDER BY agencia ASC")
    agencias = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request, 
        name="admin.html", 
        context={"reportes": reportes, "agencias": agencias}
    )

# Crear o Editar Usuarios/Claves desde el Admin
@app.post("/admin/crear-agencia")
def crear_agencia(agencia: str = Form(...), clave: str = Form(...)):
    agencia_norm = normalizar(agencia)
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO usuarios (agencia, clave)
        VALUES (?, ?)
        ON CONFLICT(agencia) DO UPDATE SET clave=excluded.clave
    ''', (agencia_norm, clave))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

# Cambiar Estado de Pago (Aprobado / Rechazado / Pendiente)
@app.post("/admin/cambiar-estado")
def cambiar_estado(reporte_id: int = Form(...), nuevo_estado: str = Form(...)):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reportes SET estado = ? WHERE id = ?", (nuevo_estado, reporte_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

# --- PANEL AGENCIA ---
@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(request: Request, nombre: str = ""):
    nombre_norm = normalizar(nombre)
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reportes WHERE agencia = ? ORDER BY id DESC", (nombre_norm,))
    mis_reportes = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request, 
        name="agencia.html", 
        context={"agencia": nombre_norm, "reportes": mis_reportes}
    )

# Cargar nuevo reporte de pago con imagen
@app.post("/reportar")
async def reportar_pago(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: float = Form(...),
    factura: str = Form(...),
    comprobante: UploadFile = File(...)
):
    agencia_norm = normalizar(agencia)
    ruta_archivo = f"uploads/{agencia_norm}_{factura}_{comprobante.filename}"
    
    with open(ruta_archivo, "wb") as buffer:
        buffer.write(await comprobante.read())

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reportes (agencia, fecha, monto, factura, comprobante, estado)
        VALUES (?, ?, ?, ?, ?, 'PENDIENTE')
    ''', (agencia_norm, fecha, monto, factura, ruta_archivo))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&exito=1", status_code=status.HTTP_303_SEE_OTHER)
