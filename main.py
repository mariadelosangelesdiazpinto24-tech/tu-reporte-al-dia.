from fastapi import FastAPI, Request, Form, UploadFile, File, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
import shutil
import os
import unicodedata

app = FastAPI()

# Asegurar directorios
os.makedirs("uploads", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

def normalizar_agencia(texto: str) -> str:
    if not texto:
        return ""
    # Quitar tildes y caracteres especiales
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.strip().upper()

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reportes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT,
            fecha TEXT,
            monto REAL,
            factura TEXT,
            comprobante TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Rutas para el Login (Acepta GET y POST sin errores)
@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
def post_login(request: Request, usuario: str = Form(...), clave: str = Form(...)):
    usuario_norm = normalizar_agencia(usuario)
    
    if usuario_norm == "ADMIN" and clave == "admin123":
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value="ADMIN")
        return response
    
    if clave == "1234":
        response = RedirectResponse(url=f"/agencia?nombre={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value=usuario_norm)
        return response
        
    return templates.TemplateResponse(request=request, name="login.html", context={"error": "Credenciales inválidas"})

# Ruta para el Panel de Agencia
@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(request: Request, nombre: str = ""):
    nombre_norm = normalizar_agencia(nombre)
    return templates.TemplateResponse(request=request, name="agencia.html", context={"agencia": nombre_norm})

# Ruta para reportar pago
@app.post("/reportar")
async def reportar_pago(
    agencia: str = Form(...),
    fecha: str = Form(...),
    monto: float = Form(...),
    factura: str = Form(...),
    comprobante: UploadFile = File(...)
):
    agencia_norm = normalizar_agencia(agencia)
    
    # Guardar la imagen del comprobante
    ruta_archivo = f"uploads/{agencia_norm}_{factura}_{comprobante.filename}"
    with open(ruta_archivo, "wb") as buffer:
        shutil.copyfileobj(comprobante.file, buffer)

    # Guardar reporte en base de datos
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reportes (agencia, fecha, monto, factura, comprobante)
        VALUES (?, ?, ?, ?, ?)
    ''', (agencia_norm, fecha, monto, factura, ruta_archivo))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/agencia?nombre={agencia_norm}&exito=1", status_code=status.HTTP_303_SEE_OTHER)

# Ruta para el Panel de Administrador
@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT agencia, fecha, monto, factura, comprobante FROM reportes ORDER BY id DESC")
    reportes = cursor.fetchall()
    conn.close()
    
    return templates.TemplateResponse(request=request, name="admin.html", context={"reportes": reportes})
